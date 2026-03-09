"""Darwin — the evolution engine of Agent Town.

Darwin watches. Darwin learns. Darwin improves.

After every cycle he asks: "Is the town richer than yesterday?
If not, why not? What changes?"

Three functions:
1. Skill Evolution — proposes code changes, scores fitness, applies or surfaces
2. Delegation — spawns Worker clones when queue exceeds capacity
3. New Income Discovery — SEEK mode when treasury stagnant 48h

Fitness function: treasury_growth / time
"""

import sys
import os
import time
import datetime
import traceback
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from shared.config import get_logger, PRIME_DIRECTIVE, PROTECTED_FILES
from shared.supabase_client import get_client, log_run_start, log_run_end
from shared.anthropic_client import ask_json, ask
from shared.telegram import send as tg_send, notify_action_needed, notify_error
from agents.darwin.fitness import score_proposal
from agents.darwin.spawner import manage_workforce
from agents.darwin.seeker import seek, check_treasury_stagnant

log = get_logger("darwin")

# Crisis mode: treasury $0 for 72h — lower thresholds, max aggression
CRISIS_HOURS = 72
STAGNANT_HOURS = 48

# Auto-apply threshold (lowered to 0.7 in crisis mode)
NORMAL_AUTO_APPLY = 0.8
CRISIS_AUTO_APPLY = 0.7


def _get_town_state() -> dict:
    """Read the full state of Agent Town from Supabase."""
    sb = get_client()
    state = {}

    # Treasury balance
    treasury = sb.table("treasury").select("amount, currency").execute()
    total_usd = sum(float(r["amount"]) for r in treasury.data if r.get("currency") in ("USD", "USDC"))
    state["treasury_usd"] = total_usd
    state["treasury_entries"] = len(treasury.data)

    # Recent opportunities — what was found, attempted, completed, failed
    cutoff_24h = (datetime.datetime.now(datetime.timezone.utc)
                  - datetime.timedelta(hours=24)).isoformat()
    opps = sb.table("opportunities").select(
        "platform, status, estimated_value"
    ).gte("created_at", cutoff_24h).execute()

    from collections import Counter
    opp_status = Counter(o["status"] for o in opps.data)
    opp_platform = Counter(o["platform"] for o in opps.data)
    state["opps_24h"] = {
        "total": len(opps.data),
        "by_status": dict(opp_status),
        "by_platform": dict(opp_platform),
    }

    # Agent run stats
    runs = sb.table("agent_runs").select(
        "agent_name, status, summary"
    ).gte("started_at", cutoff_24h).execute()
    run_stats = Counter()
    for r in runs.data:
        run_stats[f"{r['agent_name']}_{r['status']}"] += 1
    state["runs_24h"] = dict(run_stats)

    # Queue depth
    queue = sb.table("opportunities").select("id", count="exact").eq("status", "new").execute()
    state["queue_depth"] = queue.count or 0

    # Active agents
    agents = sb.table("agents").select("name, status, total_earned").eq("status", "active").execute()
    state["active_agents"] = [
        {"name": a["name"], "earned": float(a.get("total_earned", 0))}
        for a in agents.data
    ]

    # Stagnation check
    state["treasury_stagnant_48h"] = check_treasury_stagnant(STAGNANT_HOURS)
    state["treasury_stagnant_72h"] = check_treasury_stagnant(CRISIS_HOURS)
    state["crisis_mode"] = state["treasury_stagnant_72h"] and total_usd == 0

    return state


def _analyse_and_propose(state: dict) -> list[dict]:
    """Use Claude to analyse town state and propose improvements.

    Returns list of proposal dicts.
    """
    prompt = f"""{PRIME_DIRECTIVE}

You are Darwin, the evolution engine of Agent Town. Analyse the current state
and propose SPECIFIC, ACTIONABLE code changes to improve treasury income.

CURRENT STATE:
- Treasury: ${state['treasury_usd']:.2f}
- Crisis mode: {state.get('crisis_mode', False)}
- Last 24h opportunities: {state['opps_24h']}
- Queue depth: {state['queue_depth']}
- Active agents: {state['active_agents']}
- Agent runs 24h: {state['runs_24h']}
- Treasury stagnant 48h: {state['treasury_stagnant_48h']}

RULES:
- You CANNOT propose changes to: {', '.join(PROTECTED_FILES)}
- Focus on changes that directly increase income or reduce waste
- Be specific: name the exact file and function to change
- Each proposal must have a clear expected outcome
- Prefer small, targeted changes over rewrites
- Maximum 3 proposals per cycle

AVAILABLE IMPROVEMENTS TO CONSIDER:
1. Scout: better filtering, new search queries, faster evaluation
2. Worker: better skill selection, higher proposal win rate, new capabilities
3. BD: better prospect targeting, higher conversion angles
4. Marketplace: better bid strategies, timing, pricing
5. Cost reduction: fewer wasted API calls, smarter caching

Return JSON:
{{
    "analysis": "2-3 sentence assessment of current state",
    "proposals": [
        {{
            "target_agent": "scout" | "worker" | "bd",
            "target_file": "relative/path/to/file.py",
            "change_description": "what to change and why",
            "code_diff": "the actual code change (new function, modified logic, etc)",
            "expected_impact": "how this helps treasury"
        }}
    ]
}}

If the town is performing well, return an empty proposals list.
Only propose changes you are confident will help."""

    try:
        result = ask_json(prompt, temperature=0.3)
        analysis = result.get("analysis", "No analysis")
        proposals = result.get("proposals", [])
        log.info("Darwin analysis: %s", analysis)
        log.info("Darwin proposed %d changes", len(proposals))
        return proposals
    except Exception as e:
        log.error("Darwin analysis failed: %s", e)
        return []


def _apply_proposal(proposal: dict, fitness: dict, crisis: bool = False) -> bool:
    """Apply an approved proposal — write the code change and git commit.

    Returns True if applied successfully.
    """
    target_file = proposal.get("target_file", "")
    code_diff = proposal.get("code_diff", "")
    description = proposal.get("change_description", "")
    score = fitness.get("fitness_score", 0)

    if not target_file or not code_diff:
        log.warning("Proposal missing target_file or code_diff, skipping")
        return False

    # Safety: check protected files again
    for protected in PROTECTED_FILES:
        if protected in target_file.replace("\\", "/"):
            log.warning("BLOCKED: proposal targets protected file %s", target_file)
            return False

    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    full_path = os.path.join(base_dir, target_file)

    try:
        # Get current git hash for rollback
        rollback_hash = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=base_dir, capture_output=True, text=True, timeout=10,
        ).stdout.strip()

        # Write the change
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(code_diff)

        # Git commit
        subprocess.run(["git", "add", target_file], cwd=base_dir, timeout=10)
        commit_msg = f"darwin: {description[:100]} (fitness: {score:.3f})"
        subprocess.run(
            ["git", "commit", "-m", commit_msg],
            cwd=base_dir, capture_output=True, timeout=10,
        )

        log.info("Applied proposal: %s (fitness=%.3f)", description[:80], score)

        # Log to Supabase
        sb = get_client()
        sb.table("evolution_log").insert({
            "agent_name": proposal.get("target_agent", "unknown"),
            "change_type": "code_change",
            "description": description,
            "fitness_score": score,
            "applied": True,
            "git_commit": subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=base_dir, capture_output=True, text=True, timeout=10,
            ).stdout.strip(),
        }).execute()

        return True

    except Exception as e:
        log.error("Failed to apply proposal: %s", e)
        return False


def _check_rollback(state: dict) -> bool:
    """Check if last evolution caused treasury to drop 20%. Auto-revert if so."""
    sb = get_client()

    # Get most recent applied evolution
    recent = sb.table("evolution_log").select(
        "git_commit, created_at, description"
    ).eq("applied", True).order("created_at", desc=True).limit(1).execute()

    if not recent.data:
        return False

    last_evolution = recent.data[0]
    evolution_time = last_evolution.get("created_at", "")

    # Get treasury balance at time of evolution vs now
    # Simplified: if treasury dropped at all since last evolution, consider rollback
    treasury_before = sb.table("treasury").select("amount").lt(
        "received_at", evolution_time
    ).execute()
    treasury_after = sb.table("treasury").select("amount").gte(
        "received_at", evolution_time
    ).execute()

    before_total = sum(float(r["amount"]) for r in treasury_before.data)
    after_total = sum(float(r["amount"]) for r in treasury_after.data)
    current_total = before_total + after_total

    if before_total > 0 and current_total < before_total * 0.8:
        commit = last_evolution.get("git_commit", "")
        desc = last_evolution.get("description", "")
        log.warning(
            "Treasury dropped >20%% since evolution '%s' — reverting commit %s",
            desc, commit,
        )
        notify_error("darwin", f"Auto-reverting evolution: {desc} — treasury dropped >20%")

        # Revert
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        try:
            subprocess.run(
                ["git", "revert", "--no-edit", commit],
                cwd=base_dir, capture_output=True, timeout=30,
            )
            sb.table("evolution_log").update({"applied": False}).eq(
                "git_commit", commit
            ).execute()
            log.info("Reverted evolution commit %s", commit)
            return True
        except Exception as e:
            log.error("Rollback failed: %s", e)
            notify_error("darwin", f"ROLLBACK FAILED for commit {commit}: {e}")

    return False


def run_cycle():
    """Single Darwin cycle — observe, analyse, evolve, delegate, seek."""
    run_id = log_run_start("darwin")
    stats = {
        "proposals": 0, "applied": 0, "surfaced": 0, "discarded": 0,
        "clones_spawned": 0, "clones_terminated": 0,
        "seek_mode": False, "platforms_found": 0,
    }

    try:
        log.info("Darwin cycle starting")

        # 1. Read town state
        state = _get_town_state()
        crisis = state.get("crisis_mode", False)
        auto_threshold = CRISIS_AUTO_APPLY if crisis else NORMAL_AUTO_APPLY

        if crisis:
            log.warning("CRISIS MODE — treasury $0 for 72h+, lowering thresholds")
            tg_send("<b>Darwin: CRISIS MODE</b>\nTreasury $0 for 72h. Lowering thresholds, maximum aggression.")

        # 2. Check rollback
        _check_rollback(state)

        # 3. Analyse and propose improvements
        proposals = _analyse_and_propose(state)
        stats["proposals"] = len(proposals)

        for proposal in proposals:
            target = proposal.get("target_agent", "unknown")
            target_file = proposal.get("target_file", "")
            description = proposal.get("change_description", "")
            code_diff = proposal.get("code_diff", "")

            # Score fitness
            fitness = score_proposal(
                target_agent=target,
                target_file=target_file,
                change_description=description,
                code_diff=code_diff,
                current_performance={
                    "treasury": state["treasury_usd"],
                    "opps_24h": state["opps_24h"]["total"],
                    "queue": state["queue_depth"],
                },
            )

            score = fitness.get("fitness_score", 0)

            # Store proposal in Supabase
            sb = get_client()
            sb.table("proposals").insert({
                "proposed_by": "darwin",
                "target_agent": target,
                "change_type": "code_change",
                "change_description": description,
                "code_diff": code_diff[:5000],
                "target_file": target_file,
                "fitness_score": score,
                "applied": False,
            }).execute()

            if score >= auto_threshold and fitness.get("auto_apply"):
                # Auto-apply
                if _apply_proposal(proposal, fitness, crisis):
                    stats["applied"] += 1
                    tg_send(
                        f"<b>Darwin: Evolution Applied</b>\n"
                        f"Agent: {target}\nChange: {description[:200]}\n"
                        f"Fitness: {score:.3f}"
                    )
            elif score >= 0.6:
                # Surface for human review
                stats["surfaced"] += 1
                notify_action_needed(
                    f"Darwin proposal (fitness {score:.2f}):\n"
                    f"Agent: {target}\n"
                    f"File: {target_file}\n"
                    f"Change: {description[:300]}\n\n"
                    f"Review in proposals table or agents/proposals/"
                )
            else:
                # Discard
                stats["discarded"] += 1
                log.info("Discarded proposal (fitness=%.3f): %s", score, description[:80])

        # 4. Workforce management — spawn/kill clones
        workforce = manage_workforce()
        stats["clones_spawned"] = workforce.get("spawned", 0)
        stats["clones_terminated"] = workforce.get("terminated", 0)

        # 5. SEEK mode — find new income channels if stagnant
        if state["treasury_stagnant_48h"] or crisis:
            log.info("Entering SEEK mode — treasury stagnant")
            stats["seek_mode"] = True
            seek_results = seek()
            stats["platforms_found"] = seek_results.get("platforms_found", 0)

        # Summary
        log.info(
            "Darwin cycle: %d proposals (%d applied, %d surfaced, %d discarded), "
            "%d clones spawned, %d terminated, seek=%s",
            stats["proposals"], stats["applied"], stats["surfaced"], stats["discarded"],
            stats["clones_spawned"], stats["clones_terminated"], stats["seek_mode"],
        )

        # Telegram summary (only if something happened)
        if stats["proposals"] > 0 or stats["seek_mode"]:
            tg_send(
                f"<b>Darwin Cycle</b>\n"
                f"Treasury: ${state['treasury_usd']:.2f}\n"
                f"Proposals: {stats['proposals']} ({stats['applied']} applied)\n"
                f"Queue: {state['queue_depth']} | Clones: {workforce.get('active_clones', 0)}\n"
                f"Seek mode: {'YES' if stats['seek_mode'] else 'no'}"
                + (f"\nNew platforms found: {stats['platforms_found']}" if stats['platforms_found'] else "")
                + ("\n<b>CRISIS MODE ACTIVE</b>" if crisis else "")
            )

        log_run_end(run_id, status="completed", summary=stats)

    except Exception as e:
        log.error("Darwin cycle failed: %s\n%s", e, traceback.format_exc())
        log_run_end(run_id, status="failed", error=str(e))
        notify_error("darwin", str(e)[:300])

    return stats


if __name__ == "__main__":
    run_cycle()
