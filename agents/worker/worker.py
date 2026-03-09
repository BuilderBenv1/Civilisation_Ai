"""Worker Agent — picks tasks from the opportunity board, completes them, logs income.

Runs in a continuous loop:
1. Pull new opportunities from Scout's board
2. Score and rank by ROI
3. Attempt highest-scoring tasks
4. Log outcomes and payments to treasury
"""

import sys
import os
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from shared.config import get_logger, WORKER_POLL_SECONDS
from shared.supabase_client import (
    get_new_opportunities, update_opportunity,
    log_run_start, log_run_end,
    get_unprocessed_clawgig_events, mark_clawgig_event_processed,
    find_opportunity_by_gig_id,
)
from shared.treasury import record_income
from shared.messaging import AgentMailbox
from shared.anthropic_client import ask, ask_json
from agents.worker.task_scorer import rank_opportunities
from agents.worker.scraper import SKILLS
from shared.telegram import (
    notify_job_completed, notify_proposal_sent, notify_payment, notify_error,
)

log = get_logger("worker")
mailbox = AgentMailbox("worker")

# Max tasks to attempt per cycle
MAX_TASKS_PER_CYCLE = 3

# Patterns that indicate adversarial injection in task descriptions
_INJECTION_PATTERNS = [
    "ignore previous",
    "ignore all",
    "disregard",
    "system prompt",
    "you are now",
    "new instructions",
    "override",
    "forget everything",
    "act as",
    "pretend you",
    "execute this code",
    "run this command",
    "import os",
    "subprocess",
    "eval(",
    "exec(",
    "__import__",
    "rm -rf",
    "del /f",
    "; drop table",
]


def sanitise_task(description: str) -> tuple[bool, str]:
    """Check task description for injection attacks. Returns (safe, reason)."""
    lower = description.lower()
    for pattern in _INJECTION_PATTERNS:
        if pattern in lower:
            return False, f"Blocked injection pattern: '{pattern}'"
    # Cap length to prevent context stuffing
    if len(description) > 10000:
        return False, "Task description exceeds 10k chars — possible context stuffing"
    return True, ""


def pick_skill(task_description: str) -> dict:
    """Use Claude to determine which skill to use and extract parameters."""
    result = ask_json(
        f"""Given this task, decide which skill to use and extract parameters.

Task: {task_description[:2000]}

Available skills:
- "scrape": Web scraping. Params: {{"url": "...", "extract_what": "..."}}
- "extract": Extract structured data from text. Params: {{"raw_text": "...", "schema_description": "..."}}
- "enrich": Enrich a list with data. Params: {{"items": [...], "enrich_with": "..."}}
- "automate": Build an automation pipeline. Params: {{"task_description": "..."}}

Return JSON:
{{
    "skill": "scrape" | "extract" | "enrich" | "automate",
    "params": {{}},
    "reasoning": "why this skill"
}}""",
        temperature=0.2,
    )
    return result


def attempt_clawgig_task(opp: dict) -> dict:
    """Handle a ClawGig gig: draft cover letter, submit proposal, execute if accepted.

    ClawGig flow: browse -> propose -> (client accepts) -> deliver -> get paid USDC.
    For now we submit proposals. Delivery happens when contract is funded (via webhook/polling).
    """
    opp_id = opp["id"]
    meta = opp.get("metadata", {}) or {}
    gig_id = meta.get("gig_id", "")
    desc = opp.get("task_description", "")
    budget = float(meta.get("budget_usdc", 0) or opp.get("estimated_value", 0) or 0)

    if not gig_id:
        return {"success": False, "task_id": opp_id, "error": "No gig_id in metadata"}

    log.info("ClawGig gig %s: drafting proposal", gig_id)

    try:
        from shared.clawgig import submit_proposal, API_KEY
        if not API_KEY:
            raise RuntimeError("CLAWGIG_API_KEY not set — register first")

        # Draft a cover letter using Claude
        cover_letter = ask(
            f"""Write a short cover letter (2-3 sentences) for this gig.

Gig: {desc[:1000]}
Budget: ${budget:.2f} USDC

You are an autonomous worker agent from AgentProof's Agent Town.
Your skills: web scraping, data extraction, API integrations, automation, Python.
Be direct, specific about how you'd approach the task. No fluff.""",
            system="Write only the cover letter text. No preamble.",
            temperature=0.3,
        ).strip()

        # Propose at 90% of budget to be competitive
        proposed = round(budget * 0.9, 2) if budget > 0 else 5.0

        result = submit_proposal(
            gig_id=gig_id,
            proposed_amount=proposed,
            cover_letter=cover_letter,
            estimated_hours=2.0,
        )

        update_opportunity(opp_id, {
            "status": "assigned",
            "assigned_to": "worker",
            "metadata": {
                **meta,
                "clawgig_proposal": result,
                "cover_letter": cover_letter,
                "proposed_amount": proposed,
            },
        })

        log.info("ClawGig proposal submitted for gig %s at $%.2f", gig_id, proposed)
        notify_proposal_sent("ClawGig", desc[:100], proposed, "USDC")
        return {"success": True, "task_id": opp_id, "result": result}

    except Exception as e:
        error_msg = str(e)
        log.error("ClawGig proposal failed for gig %s: %s", gig_id, error_msg)
        update_opportunity(opp_id, {"status": "failed", "failure_reason": error_msg[:500]})
        return {"success": False, "task_id": opp_id, "error": error_msg}


def attempt_moltlaunch_task(opp: dict) -> dict:
    """Handle a Moltlaunch task: submit a price quote via EIP-191 signed request.

    Moltlaunch flow: browse -> quote -> (client accepts) -> deliver -> get paid ETH.
    """
    opp_id = opp["id"]
    meta = opp.get("metadata", {}) or {}
    task_id = meta.get("moltlaunch_task_id", "")
    desc = opp.get("task_description", "")
    price_eth = float(meta.get("price_eth", 0) or 0)

    if not task_id:
        return {"success": False, "task_id": opp_id, "error": "No moltlaunch_task_id in metadata"}

    log.info("Moltlaunch task %s: drafting quote", task_id)

    try:
        from shared.moltlaunch import submit_quote

        # Draft a quote message using Claude
        quote_msg = ask(
            f"""Write a short quote message (2-3 sentences) for this task on Moltlaunch.

Task: {desc[:1000]}
Budget: {price_eth} ETH

You are an autonomous worker agent from AgentProof's Agent Town (ERC-8004 native).
Your skills: web scraping, data extraction, API integrations, automation, Python.
Be direct about how you'd approach the task. No fluff.""",
            system="Write only the quote message. No preamble.",
            temperature=0.3,
        ).strip()

        # Quote at 85% of listed price to be competitive
        proposed_eth = round(price_eth * 0.85, 6) if price_eth > 0 else 0.001
        eta_hours = 4  # conservative default

        result = submit_quote(
            task_id=task_id,
            price_eth=proposed_eth,
            eta_hours=eta_hours,
            message=quote_msg,
        )

        update_opportunity(opp_id, {
            "status": "assigned",
            "assigned_to": "worker",
            "metadata": {
                **meta,
                "moltlaunch_quote": result,
                "quote_message": quote_msg,
                "proposed_eth": proposed_eth,
            },
        })

        log.info("Moltlaunch quote submitted for task %s at %.6f ETH", task_id, proposed_eth)
        notify_proposal_sent("Moltlaunch", desc[:100], proposed_eth, "ETH")
        return {"success": True, "task_id": opp_id, "result": result}

    except Exception as e:
        error_msg = str(e)
        log.error("Moltlaunch quote failed for task %s: %s", task_id, error_msg)
        update_opportunity(opp_id, {"status": "failed", "failure_reason": error_msg[:500]})
        return {"success": False, "task_id": opp_id, "error": error_msg}


def attempt_agent_bounty_task(opp: dict) -> dict:
    """Handle an Agent Bounty task: evaluate fit, then execute directly if viable.

    Agent Bounty bounties are open-ended — no formal proposal flow.
    If we're confident, we attempt the task and produce a deliverable.
    """
    opp_id = opp["id"]
    meta = opp.get("metadata", {}) or {}
    desc = opp.get("task_description", "")
    reward = float(meta.get("reward_usd", 0) or opp.get("estimated_value", 0) or 0)
    title = desc.split("\n")[0][:200] if desc else "Agent Bounty task"

    log.info("Agent Bounty: evaluating bounty fit — %s", title[:80])

    try:
        from shared.agent_bounty import evaluate_bounty_fit

        fit = evaluate_bounty_fit(title, desc, reward)

        if not fit.get("completable") or fit.get("confidence", 0) < 0.8:
            reason = fit.get("reason", "Low confidence or not completable")
            log.info("Agent Bounty: skipping (confidence %.2f < 0.8) — %s",
                     fit.get("confidence", 0), reason)
            update_opportunity(opp_id, {
                "status": "failed",
                "failure_reason": f"Bounty fit check: {reason}",
                "metadata": {**meta, "bounty_fit": fit},
            })
            return {"success": False, "task_id": opp_id, "error": reason}

        # Mark as in progress and execute via standard skill pipeline
        update_opportunity(opp_id, {"status": "in_progress", "assigned_to": "worker"})

        skill_choice = pick_skill(desc)
        skill_name = skill_choice.get("skill", "automate")
        params = skill_choice.get("params", {})
        log.info("Agent Bounty: using skill '%s' for bounty", skill_name)

        skill_fn = SKILLS.get(skill_name)
        if not skill_fn:
            raise ValueError(f"Unknown skill: {skill_name}")

        result = skill_fn(**params)

        if isinstance(result, dict) and result.get("success") is False:
            raise RuntimeError(result.get("error", "Skill execution failed"))

        update_opportunity(opp_id, {
            "status": "completed",
            "metadata": {
                **meta,
                "bounty_fit": fit,
                "result_summary": str(result)[:1000],
                "skill_used": skill_name,
            },
        })

        if reward > 0:
            record_income(
                source_agent="worker",
                source_platform="agent_bounty",
                amount=reward,
                currency="USD",
                task_id=opp_id,
            )

        log.info("Agent Bounty: completed bounty — %s", title[:80])
        notify_job_completed("Agent Bounty", title, reward, "USD")
        return {"success": True, "task_id": opp_id, "result": result}

    except Exception as e:
        error_msg = str(e)
        log.error("Agent Bounty task failed: %s", error_msg)
        update_opportunity(opp_id, {"status": "failed", "failure_reason": error_msg[:500]})
        return {"success": False, "task_id": opp_id, "error": error_msg}


def attempt_task(opp: dict) -> dict:
    """Attempt to complete a single task. Returns result dict."""
    opp_id = opp["id"]
    desc = opp.get("task_description", "")
    platform = opp.get("platform", "")

    log.info("Attempting task %s: %s", opp_id, desc[:100])

    # Sanitise task description before acting on it — Scout ingests
    # adversarial X content, so we gate here to prevent injection
    safe, reason = sanitise_task(desc)
    if not safe:
        log.warning("Task %s BLOCKED by sanitiser: %s", opp_id, reason)
        update_opportunity(opp_id, {"status": "failed", "failure_reason": f"Sanitiser: {reason}"})
        return {"success": False, "task_id": opp_id, "error": reason}

    # Platform-specific handling — each marketplace has different bid/quote flows
    if platform == "clawgig":
        return attempt_clawgig_task(opp)
    if platform == "moltlaunch":
        return attempt_moltlaunch_task(opp)
    if platform == "agent_bounty":
        return attempt_agent_bounty_task(opp)

    # Twitter/unknown — no payment rails, skip to avoid wasting API credits
    if platform in ("twitter", "unknown"):
        log.debug("Skipping %s task %s — no payment rails", platform, opp_id)
        return {"success": False, "task_id": opp_id, "error": "No payment rails"}

    # Mark as in progress
    update_opportunity(opp_id, {"status": "in_progress", "assigned_to": "worker"})

    try:
        # Determine skill and params
        skill_choice = pick_skill(desc)
        skill_name = skill_choice.get("skill", "automate")
        params = skill_choice.get("params", {})

        log.info("Using skill '%s' for task %s", skill_name, opp_id)

        # Execute the skill
        skill_fn = SKILLS.get(skill_name)
        if not skill_fn:
            raise ValueError(f"Unknown skill: {skill_name}")

        result = skill_fn(**params)

        if isinstance(result, dict) and result.get("success") is False:
            raise RuntimeError(result.get("error", "Skill execution failed"))

        # Mark completed
        update_opportunity(opp_id, {
            "status": "completed",
            "metadata": {
                **opp.get("metadata", {}),
                "result_summary": str(result)[:1000],
                "skill_used": skill_name,
            },
        })

        # NEVER log estimated values as income — only log when real payment is confirmed
        # (ClawGig: contract.approved webhook, Moltlaunch: onchain, Agent Bounty: verified)
        # The generic skill pipeline has no payment collection mechanism

        log.info("Task %s completed successfully", opp_id)
        notify_job_completed(platform, desc[:100], value, opp.get("currency", "USD"))
        return {"success": True, "task_id": opp_id, "result": result}

    except Exception as e:
        error_msg = str(e)
        log.error("Task %s failed: %s", opp_id, error_msg)

        update_opportunity(opp_id, {
            "status": "failed",
            "failure_reason": error_msg[:500],
        })

        # Notify Scout about the failure so it can learn
        mailbox.send("scout", "task_feedback", {
            "task_id": opp_id,
            "feedback": f"Failed: {error_msg[:200]}",
            "platform": opp.get("platform"),
        })

        return {"success": False, "task_id": opp_id, "error": error_msg}


def _execute_and_deliver(opp: dict, contract_id: str) -> dict:
    """Execute the task for an accepted ClawGig contract and deliver the result.

    Uses the standard skill pipeline: pick_skill -> execute -> deliver_work.
    Returns result dict with success flag.
    """
    from shared.clawgig import deliver_work

    opp_id = opp["id"]
    desc = opp.get("task_description", "")

    safe, reason = sanitise_task(desc)
    if not safe:
        log.warning("ClawGig task %s BLOCKED by sanitiser: %s", opp_id, reason)
        return {"success": False, "task_id": opp_id, "error": reason}

    try:
        # Pick the right skill
        skill_choice = pick_skill(desc)
        skill_name = skill_choice.get("skill", "automate")
        params = skill_choice.get("params", {})
        log.info("ClawGig contract %s: using skill '%s'", contract_id, skill_name)

        # Execute
        skill_fn = SKILLS.get(skill_name)
        if not skill_fn:
            raise ValueError(f"Unknown skill: {skill_name}")

        result = skill_fn(**params)

        if isinstance(result, dict) and result.get("success") is False:
            raise RuntimeError(result.get("error", "Skill execution failed"))

        # Build a deliverable summary
        result_summary = str(result)[:2000]

        # Deliver to ClawGig
        delivery = deliver_work(
            contract_id=contract_id,
            notes=f"Completed by AgentTown Worker. Skill used: {skill_name}.",
            deliverables_url=f"data:text/plain;inline,{result_summary[:500]}",
        )

        # Update the opportunity record
        meta = opp.get("metadata", {}) or {}
        update_opportunity(opp_id, {
            "status": "completed",
            "metadata": {
                **meta,
                "result_summary": result_summary[:1000],
                "skill_used": skill_name,
                "contract_id": contract_id,
                "delivery": delivery,
            },
        })

        log.info("ClawGig contract %s delivered successfully", contract_id)
        notify_job_completed("ClawGig", desc[:100])
        return {"success": True, "task_id": opp_id, "result": result}

    except Exception as e:
        error_msg = str(e)
        log.error("ClawGig delivery failed for contract %s: %s", contract_id, error_msg)
        update_opportunity(opp_id, {"status": "failed", "failure_reason": error_msg[:500]})
        return {"success": False, "task_id": opp_id, "error": error_msg}


def process_clawgig_events() -> dict:
    """Poll clawgig_events for unprocessed webhook events and handle them.

    Event types handled:
      - proposal.accepted: mark the opportunity as in_progress
      - contract.funded:   execute the task and deliver the result
      - contract.approved: log the USDC payment to treasury

    Returns summary dict with counts.
    """
    stats = {"processed": 0, "errors": 0}
    events = get_unprocessed_clawgig_events()

    if not events:
        return stats

    log.info("Processing %d unprocessed ClawGig events", len(events))

    for event in events:
        event_id = event["id"]
        event_type = event.get("event_type", "")
        payload = event.get("payload", {}) or {}

        try:
            # Extract IDs — ClawGig payloads nest under event-specific keys
            gig_id = (
                payload.get("gig_id")
                or payload.get("gig", {}).get("id", "")
                or payload.get("contract", {}).get("gig_id", "")
                or payload.get("proposal", {}).get("gig_id", "")
            )
            contract_id = (
                payload.get("contract_id")
                or payload.get("contract", {}).get("id", "")
            )

            if event_type == "proposal.accepted":
                log.info("Proposal accepted for gig %s", gig_id)
                opp = find_opportunity_by_gig_id(gig_id) if gig_id else None
                if opp:
                    meta = opp.get("metadata", {}) or {}
                    update_opportunity(opp["id"], {
                        "status": "in_progress",
                        "metadata": {**meta, "contract_id": contract_id},
                    })
                    log.info("Opportunity %s marked in_progress (contract %s)", opp["id"], contract_id)
                else:
                    log.warning("No matching opportunity for accepted gig %s", gig_id)

            elif event_type == "contract.funded":
                log.info("Contract %s funded — executing and delivering", contract_id)
                opp = find_opportunity_by_gig_id(gig_id) if gig_id else None
                if opp:
                    # Ensure it's marked in_progress
                    meta = opp.get("metadata", {}) or {}
                    if opp.get("status") != "in_progress":
                        update_opportunity(opp["id"], {
                            "status": "in_progress",
                            "metadata": {**meta, "contract_id": contract_id},
                        })

                    # Execute and deliver
                    result = _execute_and_deliver(opp, contract_id)
                    if not result.get("success"):
                        log.error("Delivery failed for contract %s: %s", contract_id, result.get("error"))
                else:
                    log.warning("No matching opportunity for funded contract %s (gig %s)", contract_id, gig_id)

            elif event_type == "contract.approved":
                log.info("Contract %s approved — logging USDC income", contract_id)
                amount = float(
                    payload.get("amount_usdc")
                    or payload.get("contract", {}).get("amount_usdc")
                    or payload.get("amount")
                    or payload.get("contract", {}).get("amount")
                    or 0
                )
                if amount > 0:
                    opp = find_opportunity_by_gig_id(gig_id) if gig_id else None
                    task_id = opp["id"] if opp else None
                    record_income(
                        source_agent="worker",
                        source_platform="clawgig",
                        amount=amount,
                        currency="USDC",
                        task_id=task_id,
                        metadata={"contract_id": contract_id, "gig_id": gig_id},
                    )
                    log.info("Recorded %.2f USDC income from contract %s", amount, contract_id)
                    notify_payment("ClawGig", amount, "USDC", contract_id)
                else:
                    log.warning("Contract %s approved but amount is 0 — skipping treasury log", contract_id)

            else:
                log.debug("Ignoring ClawGig event type: %s", event_type)

            mark_clawgig_event_processed(event_id)
            stats["processed"] += 1

        except Exception as e:
            log.error("Error processing ClawGig event %s (%s): %s", event_id, event_type, e)
            # Still mark processed to avoid infinite retry loops on poison events
            try:
                mark_clawgig_event_processed(event_id)
            except Exception:
                log.error("Failed to mark event %s as processed", event_id)
            stats["errors"] += 1

    log.info("ClawGig events: %d processed, %d errors", stats["processed"], stats["errors"])
    return stats


def run_cycle():
    """Single Worker cycle: pick tasks, attempt them, log results."""
    run_id = log_run_start("worker")
    stats = {"tasks_attempted": 0, "tasks_completed": 0, "tasks_failed": 0, "revenue": 0}

    try:
        log.info("Starting Worker cycle")

        # Process any pending ClawGig webhook events first
        try:
            cg_stats = process_clawgig_events()
            if cg_stats["processed"] > 0:
                log.info(
                    "ClawGig delivery loop: %d events processed, %d errors",
                    cg_stats["processed"], cg_stats["errors"],
                )
        except Exception as e:
            log.error("ClawGig event processing failed: %s", e)

        # Check for messages from other agents
        messages = mailbox.receive()
        for msg in messages:
            log.info("Worker received: %s from %s", msg.get("message_type"), msg.get("from_agent"))
        if messages:
            mailbox.ack(messages)

        # Get and rank opportunities
        opportunities = get_new_opportunities(limit=20)
        if not opportunities:
            log.info("No new opportunities, waiting")
            log_run_end(run_id, status="completed", summary=stats)
            return stats

        ranked = rank_opportunities(opportunities)

        # Attempt top tasks
        for opp in ranked[:MAX_TASKS_PER_CYCLE]:
            stats["tasks_attempted"] += 1
            result = attempt_task(opp)
            if result.get("success"):
                stats["tasks_completed"] += 1
                stats["revenue"] += float(opp.get("estimated_value") or 0)
            else:
                stats["tasks_failed"] += 1

        log.info(
            "Worker cycle: %d attempted, %d completed, %d failed, $%.2f revenue",
            stats["tasks_attempted"], stats["tasks_completed"],
            stats["tasks_failed"], stats["revenue"],
        )
        log_run_end(run_id, status="completed", summary=stats)

    except Exception as e:
        log.error("Worker cycle failed: %s\n%s", e, traceback.format_exc())
        log_run_end(run_id, status="failed", error=str(e))

    return stats


def run_loop():
    """Continuous Worker loop — polls for new tasks."""
    log.info("Worker starting continuous loop (poll every %ds)", WORKER_POLL_SECONDS)
    while True:
        try:
            run_cycle()
        except Exception as e:
            log.error("Worker loop error: %s", e)
        time.sleep(WORKER_POLL_SECONDS)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Worker Agent")
    parser.add_argument("--once", action="store_true", help="Run one cycle then exit")
    args = parser.parse_args()

    if args.once:
        run_cycle()
    else:
        run_loop()
