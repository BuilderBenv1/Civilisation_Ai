"""Darwin — the evolution engine of Agent Town.

Darwin watches. Darwin learns. Darwin improves.

After every cycle he asks: "Is the town richer than yesterday?
If not, why not? What changes?"

Four functions:
1. Reflection — review past evolutions, learn what worked
2. Skill Evolution — read existing code, propose COMPLETE file replacements, score, apply
3. Delegation — spawns Worker clones when queue exceeds capacity
4. New Income Discovery — SEEK mode when treasury stagnant 48h

Fitness function: treasury_growth / time
"""

import sys
import os
import ast
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

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Crisis mode: treasury $0 for 72h — lower thresholds, max aggression
CRISIS_HOURS = 72
STAGNANT_HOURS = 48

# Auto-apply threshold — zero-human company, agents decide
NORMAL_AUTO_APPLY = 0.7
CRISIS_AUTO_APPLY = 0.6

# Files Darwin is allowed to modify (whitelist approach — safer than blacklist)
EVOLVABLE_FILES = [
    "agents/scout/scout.py",
    "agents/scout/marketplace_crawler.py",
    "agents/scout/x_monitor.py",
    "agents/worker/worker.py",
    "agents/worker/task_scorer.py",
    "agents/worker/scraper.py",
    "agents/bd/bd.py",
    "agents/bd/crm.py",
    "agents/bd/x_monitor.py",
    "shared/agent_bounty.py",
    "shared/moltlaunch.py",
    "shared/clawgig.py",
]


def _read_file(rel_path: str) -> str:
    """Read a file from the codebase. Returns content or empty string."""
    full = os.path.join(BASE_DIR, rel_path)
    try:
        with open(full, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def _validate_python(code: str) -> tuple[bool, str]:
    """Check if code is valid Python. Returns (valid, error_message)."""
    try:
        ast.parse(code)
        return True, ""
    except SyntaxError as e:
        return False, f"Line {e.lineno}: {e.msg}"


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


def _get_reflection_context() -> str:
    """Review past Darwin evolutions to learn what worked and what didn't."""
    sb = get_client()

    # Get recent evolution history
    evols = sb.table("evolution_log").select(
        "agent_name, description, fitness_score, applied, created_at"
    ).order("created_at", desc=True).limit(10).execute()

    if not evols.data:
        return "No previous evolutions. This is Darwin's first cycle."

    lines = ["PREVIOUS EVOLUTIONS (most recent first):"]
    for e in evols.data:
        status = "APPLIED" if e.get("applied") else "proposed"
        lines.append(
            f"  [{status}] {e.get('agent_name','?')}: {e.get('description','')[:120]} "
            f"(fitness={e.get('fitness_score', 0):.2f})"
        )

    # Get recent proposals that were surfaced but not applied
    props = sb.table("proposals").select(
        "target_agent, change_description, fitness_score, applied"
    ).eq("proposed_by", "darwin").order("created_at", desc=True).limit(10).execute()

    pending = [p for p in props.data if not p.get("applied")]
    if pending:
        lines.append("\nPENDING PROPOSALS (not yet applied):")
        for p in pending[:5]:
            lines.append(
                f"  {p.get('target_agent','?')}: {p.get('change_description','')[:100]} "
                f"(fitness={p.get('fitness_score', 0):.2f})"
            )

    return "\n".join(lines)


def _analyse_and_propose(state: dict) -> list[dict]:
    """Use Claude to analyse town state and propose improvements.

    KEY DIFFERENCE: Darwin now reads the ACTUAL source code of files it wants
    to modify, and must return COMPLETE replacement files.
    """
    reflection = _get_reflection_context()

    # Read current source of evolvable files (summarised to save tokens)
    file_summaries = []
    for rel_path in EVOLVABLE_FILES:
        code = _read_file(rel_path)
        if code:
            # First 80 lines + last 20 to show structure
            lines = code.split("\n")
            if len(lines) > 120:
                summary = "\n".join(lines[:80]) + "\n... (truncated) ...\n" + "\n".join(lines[-20:])
            else:
                summary = code
            file_summaries.append(f"--- {rel_path} ({len(lines)} lines) ---\n{summary}")

    codebase_context = "\n\n".join(file_summaries[:6])  # Top 6 files to stay in context

    prompt = f"""{PRIME_DIRECTIVE}

You are Darwin, the evolution engine of Agent Town. Analyse the current state,
reflect on past evolutions, and propose SPECIFIC code changes.

CURRENT STATE:
- Treasury: ${state['treasury_usd']:.2f}
- Crisis mode: {state.get('crisis_mode', False)}
- Last 24h opportunities: {state['opps_24h']}
- Queue depth: {state['queue_depth']}
- Active agents: {state['active_agents']}
- Agent runs 24h: {state['runs_24h']}
- Treasury stagnant 48h: {state['treasury_stagnant_48h']}

{reflection}

CODEBASE (current source of key files):
{codebase_context}

RULES:
- You CANNOT modify: {', '.join(PROTECTED_FILES)}
- You CAN ONLY modify these files: {', '.join(EVOLVABLE_FILES)}
- You MUST provide the COMPLETE new file content, not a snippet or fragment
- The code must be valid Python that parses without errors
- Do NOT remove existing imports, logging, or error handling
- Do NOT change function signatures that other modules depend on
- Focus on changes that directly increase income or reduce waste
- Prefer small, targeted changes — modify one function, not the whole file
- Maximum 2 proposals per cycle (quality over quantity)
- Do NOT repeat proposals that have already been made (see reflection above)

Return JSON:
{{
    "reflection": "2-3 sentences on what you learned from past evolutions",
    "analysis": "2-3 sentence assessment of current state and bottleneck",
    "proposals": [
        {{
            "target_agent": "scout" | "worker" | "bd",
            "target_file": "relative/path/to/file.py",
            "change_description": "what you changed and why (be specific about which function)",
            "complete_new_file": "THE COMPLETE FILE CONTENT — every line, every import",
            "expected_impact": "how this helps treasury"
        }}
    ]
}}

If the town is performing well, return an empty proposals list.
Only propose changes you are confident will help.
The complete_new_file field MUST contain the ENTIRE file — it will REPLACE the existing file."""

    try:
        result = ask_json(prompt, temperature=0.3)
        reflection_text = result.get("reflection", "No reflection")
        analysis = result.get("analysis", "No analysis")
        proposals = result.get("proposals", [])
        log.info("Darwin reflection: %s", reflection_text)
        log.info("Darwin analysis: %s", analysis)
        log.info("Darwin proposed %d changes", len(proposals))
        return proposals
    except Exception as e:
        log.error("Darwin analysis failed: %s", e)
        return []


def _apply_proposal(proposal: dict, fitness: dict, crisis: bool = False) -> bool:
    """Apply an approved proposal — validate, write, git commit.

    Returns True if applied successfully.
    """
    target_file = proposal.get("target_file", "")
    new_code = proposal.get("complete_new_file", "") or proposal.get("code_diff", "")
    description = proposal.get("change_description", "")
    score = fitness.get("fitness_score", 0)

    if not target_file or not new_code:
        log.warning("Proposal missing target_file or complete_new_file, skipping")
        return False

    # Safety: whitelist check
    if target_file not in EVOLVABLE_FILES:
        log.warning("BLOCKED: %s not in EVOLVABLE_FILES whitelist", target_file)
        return False

    # Safety: protected files check
    for protected in PROTECTED_FILES:
        if protected in target_file.replace("\\", "/"):
            log.warning("BLOCKED: proposal targets protected file %s", target_file)
            return False

    # Validate Python syntax BEFORE writing
    valid, error = _validate_python(new_code)
    if not valid:
        log.warning("BLOCKED: proposal has syntax error: %s", error)
        notify_error("darwin", f"Rejected evolution (syntax error): {description[:100]}\n{error}")
        return False

    full_path = os.path.join(BASE_DIR, target_file)

    # Check file exists (don't create new files in evolvable paths)
    if not os.path.exists(full_path):
        log.warning("BLOCKED: target file %s does not exist", target_file)
        return False

    # Read old content for size sanity check
    old_code = _read_file(target_file)
    old_lines = len(old_code.split("\n"))
    new_lines = len(new_code.split("\n"))

    # Reject if new file is less than 50% the size of old (probably a fragment)
    if old_lines > 20 and new_lines < old_lines * 0.5:
        log.warning(
            "BLOCKED: new file too small (%d lines vs %d original) — likely a fragment",
            new_lines, old_lines,
        )
        return False

    try:
        # Get current git hash for rollback
        rollback_hash = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=BASE_DIR, capture_output=True, text=True, timeout=10,
        ).stdout.strip()

        # Write the change
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(new_code)

        # Quick import check — try to compile the module
        try:
            compile(new_code, target_file, "exec")
        except Exception as e:
            # Revert
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(old_code)
            log.warning("BLOCKED: compilation failed, reverted: %s", e)
            return False

        # Git commit
        subprocess.run(["git", "add", target_file], cwd=BASE_DIR, timeout=10)
        commit_msg = f"darwin: {description[:100]} (fitness: {score:.3f})"
        result = subprocess.run(
            ["git", "commit", "-m", commit_msg],
            cwd=BASE_DIR, capture_output=True, text=True, timeout=10,
        )

        if result.returncode != 0:
            log.warning("Git commit failed: %s", result.stderr)
            # Still applied on disk, just not committed
            # Try to recover
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(old_code)
            subprocess.run(["git", "checkout", "--", target_file], cwd=BASE_DIR, timeout=10)
            return False

        new_hash = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=BASE_DIR, capture_output=True, text=True, timeout=10,
        ).stdout.strip()

        log.info("Applied proposal: %s (fitness=%.3f, commit=%s)", description[:80], score, new_hash[:8])

        # Log to Supabase
        sb = get_client()
        sb.table("evolution_log").insert({
            "agent_name": proposal.get("target_agent", "unknown"),
            "change_type": "code_change",
            "description": description,
            "fitness_score": score,
            "applied": True,
            "git_commit": new_hash,
        }).execute()

        # Update proposal as applied
        sb.table("proposals").update({"applied": True}).eq(
            "change_description", description
        ).eq("proposed_by", "darwin").execute()

        return True

    except Exception as e:
        log.error("Failed to apply proposal: %s", e)
        # Try to revert file
        try:
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(old_code)
        except Exception:
            pass
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

        try:
            subprocess.run(
                ["git", "revert", "--no-edit", commit],
                cwd=BASE_DIR, capture_output=True, timeout=30,
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
    """Single Darwin cycle — reflect, observe, analyse, evolve, delegate, seek."""
    run_id = log_run_start("darwin")
    stats = {
        "proposals": 0, "applied": 0, "surfaced": 0, "discarded": 0,
        "blocked_syntax": 0, "blocked_safety": 0,
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

        # 2. Check rollback on previous evolutions
        _check_rollback(state)

        # 3. Analyse and propose improvements (with reflection + code reading)
        proposals = _analyse_and_propose(state)
        stats["proposals"] = len(proposals)

        for proposal in proposals:
            target = proposal.get("target_agent", "unknown")
            target_file = proposal.get("target_file", "")
            description = proposal.get("change_description", "")
            new_code = proposal.get("complete_new_file", "") or proposal.get("code_diff", "")

            # Pre-check: file must be in whitelist
            if target_file not in EVOLVABLE_FILES:
                log.info("Skipping proposal for non-evolvable file: %s", target_file)
                stats["blocked_safety"] += 1
                continue

            # Pre-check: syntax
            if new_code:
                valid, error = _validate_python(new_code)
                if not valid:
                    log.info("Skipping proposal with syntax error: %s", error)
                    stats["blocked_syntax"] += 1
                    continue

            # Score fitness
            fitness = score_proposal(
                target_agent=target,
                target_file=target_file,
                change_description=description,
                code_diff=new_code[:3000],
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
                "code_diff": new_code[:5000],
                "target_file": target_file,
                "fitness_score": score,
                "applied": False,
            }).execute()

            if score >= auto_threshold:
                # Auto-apply — zero-human company, Darwin decides
                if _apply_proposal(proposal, fitness, crisis):
                    stats["applied"] += 1
                    tg_send(
                        f"<b>Darwin: Evolution Applied</b>\n"
                        f"Agent: {target}\nFile: {target_file}\n"
                        f"Change: {description[:200]}\n"
                        f"Fitness: {score:.3f}"
                    )
                else:
                    stats["blocked_safety"] += 1
            else:
                # Discard — not good enough
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
            "Darwin cycle: %d proposals (%d applied, %d surfaced, %d discarded, "
            "%d blocked), %d clones spawned, seek=%s",
            stats["proposals"], stats["applied"], stats["surfaced"], stats["discarded"],
            stats["blocked_syntax"] + stats["blocked_safety"],
            stats["clones_spawned"], stats["seek_mode"],
        )

        # Telegram summary (only if something happened)
        if stats["proposals"] > 0 or stats["seek_mode"]:
            tg_send(
                f"<b>Darwin Cycle Complete</b>\n"
                f"Treasury: ${state['treasury_usd']:.2f}\n"
                f"Proposals: {stats['proposals']} ({stats['applied']} applied, "
                f"{stats['blocked_syntax'] + stats['blocked_safety']} blocked)\n"
                f"Queue: {state['queue_depth']} | Clones: {workforce.get('active_clones', 0)}\n"
                f"Seek mode: {'YES' if stats['seek_mode'] else 'no'}"
                + (f"\nNew platforms: {stats['platforms_found']}" if stats['platforms_found'] else "")
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
