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

Task: {task_description}

Available skills:
- scrape: scrape_url(url, extract_what) — web scraping with BeautifulSoup
- extract: extract_structured_data(raw_text, schema_description) — parse unstructured text
- enrich: enrich_list(items, enrich_with) — add data to a list of items
- automate: build_automation(task_description) — general automation pipeline

Return JSON:
{{
    "skill": "scrape|extract|enrich|automate",
    "parameters": {{...}},
    "reasoning": "why this skill fits"
}}""",
        temperature=0.1,
    )
    return result


def execute_task(opportunity: dict) -> dict:
    """Execute a task using the appropriate skill. Enhanced with retry logic."""
    task_id = opportunity.get("id")
    description = opportunity.get("description", "")
    
    log.info("Executing task %s: %s", task_id, description[:100])
    
    # Safety check
    safe, reason = sanitise_task(description)
    if not safe:
        log.warning("Task %s blocked: %s", task_id, reason)
        return {
            "success": False,
            "error": f"Security check failed: {reason}",
            "result": None,
        }
    
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            # Pick skill and parameters
            skill_choice = pick_skill(description)
            skill_name = skill_choice.get("skill")
            parameters = skill_choice.get("parameters", {})
            
            log.info("Task %s: using skill '%s' with params %s", task_id, skill_name, parameters)
            
            if skill_name not in SKILLS:
                return {
                    "success": False,
                    "error": f"Unknown skill: {skill_name}",
                    "result": None,
                }
            
            skill_func = SKILLS[skill_name]
            
            # Execute skill with parameters
            if skill_name == "scrape":
                result = skill_func(
                    url=parameters.get("url", ""),
                    extract_what=parameters.get("extract_what", "all content"),
                )
            elif skill_name == "extract":
                result = skill_func(
                    raw_text=parameters.get("raw_text", description),
                    schema_description=parameters.get("schema_description", "structured data"),
                )
            elif skill_name == "enrich":
                result = skill_func(
                    items=parameters.get("items", []),
                    enrich_with=parameters.get("enrich_with", "additional data"),
                )
            elif skill_name == "automate":
                result = skill_func(task_description=description)
            else:
                result = {"success": False, "error": "Skill execution not implemented"}
            
            # Check if result indicates success
            if isinstance(result, dict) and result.get("success") is False:
                error_msg = result.get("error", "Unknown error")
                
                # Check if this is a retryable error
                retryable_errors = [
                    "timeout", "connection", "network", "temporary", 
                    "rate limit", "503", "502", "504", "429"
                ]
                
                is_retryable = any(err in error_msg.lower() for err in retryable_errors)
                
                if is_retryable and retry_count < max_retries - 1:
                    retry_count += 1
                    wait_time = 2 ** retry_count  # Exponential backoff
                    log.warning("Task %s failed with retryable error '%s', retrying in %ds (attempt %d/%d)", 
                               task_id, error_msg, wait_time, retry_count + 1, max_retries)
                    time.sleep(wait_time)
                    continue
                else:
                    log.error("Task %s failed after %d attempts: %s", task_id, retry_count + 1, error_msg)
                    return {
                        "success": False,
                        "error": f"Failed after {retry_count + 1} attempts: {error_msg}",
                        "result": result,
                        "retry_count": retry_count + 1,
                    }
            
            # Success case
            log.info("Task %s completed successfully on attempt %d", task_id, retry_count + 1)
            return {
                "success": True,
                "error": None,
                "result": result,
                "skill_used": skill_name,
                "retry_count": retry_count,
            }
            
        except Exception as e:
            error_msg = str(e)
            log.error("Task %s execution error (attempt %d): %s\n%s", 
                     task_id, retry_count + 1, error_msg, traceback.format_exc())
            
            # Check if this is a retryable exception
            retryable_exceptions = [
                "timeout", "connection", "network", "temporary",
                "requests.exceptions", "urllib3.exceptions"
            ]
            
            is_retryable = any(err in error_msg.lower() for err in retryable_exceptions)
            
            if is_retryable and retry_count < max_retries - 1:
                retry_count += 1
                wait_time = 2 ** retry_count
                log.warning("Task %s exception is retryable, waiting %ds before retry %d/%d", 
                           task_id, wait_time, retry_count + 1, max_retries)
                time.sleep(wait_time)
                continue
            else:
                return {
                    "success": False,
                    "error": f"Exception after {retry_count + 1} attempts: {error_msg}",
                    "result": None,
                    "retry_count": retry_count + 1,
                }
    
    # Should not reach here, but just in case
    return {
        "success": False,
        "error": f"Max retries ({max_retries}) exceeded",
        "result": None,
        "retry_count": max_retries,
    }


def submit_proposal(opportunity: dict, result: dict) -> bool:
    """Submit our work/proposal for this opportunity."""
    platform = opportunity.get("platform", "unknown")
    
    if platform == "clawgig":
        return _submit_clawgig_proposal(opportunity, result)
    elif platform == "twitter":
        return _submit_twitter_proposal(opportunity, result)
    elif platform == "upwork":
        return _submit_upwork_proposal(opportunity, result)
    else:
        log.warning("No submission handler for platform: %s", platform)
        return False


def _submit_clawgig_proposal(opportunity: dict, result: dict) -> bool:
    """Submit work to ClawGig platform."""
    try:
        from shared.clawgig import submit_work
        gig_id = opportunity.get("gig_id")
        if not gig_id:
            log.error("ClawGig opportunity missing gig_id")
            return False
        
        success = submit_work(gig_id, result)
        if success:
            notify_job_completed(
                platform="clawgig",
                task_id=gig_id,
                value=opportunity.get("estimated_value", 0),
            )
        return success
    except Exception as e:
        log.error("ClawGig submission failed: %s", e)
        return False


def _submit_twitter_proposal(opportunity: dict, result: dict) -> bool:
    """Reply to Twitter thread with our proposal/solution."""
    try:
        # For now, just log — Twitter API integration needed
        log.info("Would submit Twitter proposal for: %s", opportunity.get("url", ""))
        notify_proposal_sent(
            platform="twitter",
            task_id=opportunity.get("tweet_id", ""),
            proposal_text="Solution provided",
        )
        return True
    except Exception as e:
        log.error("Twitter submission failed: %s", e)
        return False


def _submit_upwork_proposal(opportunity: dict, result: dict) -> bool:
    """Submit proposal to Upwork job."""
    try:
        # Upwork API integration needed
        log.info("Would submit Upwork proposal for: %s", opportunity.get("url", ""))
        return True
    except Exception as e:
        log.error("Upwork submission failed: %s", e)
        return False


def process_clawgig_events():
    """Process new ClawGig payment events."""
    try:
        events = get_unprocessed_clawgig_events()
        for event in events:
            if event.get("event_type") == "payment":
                amount = float(event.get("amount", 0))
                gig_id = event.get("gig_id")
                
                # Find the opportunity this payment relates to
                opportunity = find_opportunity_by_gig_id(gig_id)
                
                if amount > 0:
                    record_income(amount, f"ClawGig payment for gig {gig_id}")
                    log.info("Recorded ClawGig payment: $%.2f for gig %s", amount, gig_id)
                    notify_payment(amount, "ClawGig", gig_id)
                
                mark_clawgig_event_processed(event["id"])
    except Exception as e:
        log.error("ClawGig event processing failed: %s", e)


def run_cycle():
    """Single Worker cycle — find tasks, execute, submit."""
    run_id = log_run_start("worker")
    
    try:
        # Process any pending payments first
        process_clawgig_events()
        
        # Get new opportunities
        opportunities = get_new_opportunities(limit=20)
        if not opportunities:
            log.info("No new opportunities found")
            log_run_end(run_id, status="completed", summary={"opportunities": 0})
            return
        
        # Rank by ROI
        ranked = rank_opportunities(opportunities)
        
        completed = 0
        failed = 0
        
        # Attempt top opportunities
        for opportunity in ranked[:MAX_TASKS_PER_CYCLE]:
            opp_id = opportunity.get("id")
            
            try:
                # Mark as in progress
                update_opportunity(opp_id, status="in_progress")
                
                # Execute the task
                result = execute_task(opportunity)
                
                if result.get("success"):
                    # Submit our work
                    submitted = submit_proposal(opportunity, result)
                    
                    if submitted:
                        update_opportunity(
                            opp_id,
                            status="completed",
                            result=result,
                            worker_notes=f"Completed using {result.get('skill_used', 'unknown')} skill"
                        )
                        completed += 1
                        log.info("Task %s completed and submitted", opp_id)
                    else:
                        update_opportunity(
                            opp_id,
                            status="failed",
                            result=result,
                            worker_notes="Task completed but submission failed"
                        )
                        failed += 1
                else:
                    # Task execution failed
                    update_opportunity(
                        opp_id,
                        status="failed",
                        result=result,
                        worker_notes=f"Execution failed: {result.get('error', 'Unknown error')}"
                    )
                    failed += 1
                    
                    # Notify of persistent failures
                    retry_count = result.get('retry_count', 0)
                    if retry_count >= 3:
                        notify_error(f"Task {opp_id} failed after {retry_count} retries: {result.get('error')}")
                
            except Exception as e:
                log.error("Task %s processing error: %s\n%s", opp_id, e, traceback.format_exc())
                update_opportunity(
                    opp_id,
                    status="failed",
                    worker_notes=f"Processing error: {str(e)}"
                )
                failed += 1
        
        summary = {
            "opportunities": len(opportunities),
            "attempted": min(len(ranked), MAX_TASKS_PER_CYCLE),
            "completed": completed,
            "failed": failed,
        }
        
        log.info(
            "Worker cycle: %d opportunities, %d attempted, %d completed, %d failed",
            summary["opportunities"], summary["attempted"], summary["completed"], summary["failed"]
        )
        
        log_run_end(run_id, status="completed", summary=summary)
        
    except Exception as e:
        log.error("Worker cycle failed: %s\n%s", e, traceback.format_exc())
        log_run_end(run_id, status="failed", error=str(e))
        raise


def run_loop():
    """Continuous Worker loop."""
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