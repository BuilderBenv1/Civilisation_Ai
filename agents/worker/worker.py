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


def validate_task_parameters(skill_name: str, params: dict, description: str) -> tuple[bool, str]:
    """Validate that we have all required parameters for successful task execution."""
    if skill_name == "scrape":
        url = params.get("url", "")
        if not url or not url.startswith(("http://", "https://")):
            return False, "Missing or invalid URL for scraping task"
        if len(url) > 2000:
            return False, "URL too long, likely malformed"
    
    elif skill_name == "extract":
        raw_text = params.get("raw_text", "")
        schema = params.get("schema_description", "")
        if not raw_text or len(raw_text.strip()) < 10:
            return False, "Insufficient text content for extraction"
        if not schema or len(schema.strip()) < 5:
            return False, "Missing or insufficient schema description"
    
    elif skill_name == "enrich":
        items = params.get("items", [])
        enrich_with = params.get("enrich_with", "")
        if not items or not isinstance(items, list) or len(items) == 0:
            return False, "Missing or empty items list for enrichment"
        if not enrich_with or len(enrich_with.strip()) < 5:
            return False, "Missing enrichment specification"
    
    elif skill_name == "automate":
        workflow = params.get("workflow_description", "")
        if not workflow or len(workflow.strip()) < 20:
            return False, "Insufficient workflow description for automation"
    
    # Check if description contains enough context
    if len(description.strip()) < 30:
        return False, "Task description too brief for reliable execution"
    
    return True, ""


def pick_skill(task_description: str) -> dict:
    """Use Claude to determine which skill to use and extract parameters."""
    result = ask_json(
        f"""Given this task, decide which skill to use and extract parameters.

Task: {task_description}

Available skills:
- scrape: Extract data from websites (needs: url, extract_what)
- extract: Parse structured data from text (needs: raw_text, schema_description)
- enrich: Add data to a list of items (needs: items, enrich_with)
- automate: Build a workflow/pipeline (needs: workflow_description)

Return JSON with:
{{
    "skill": "skill_name",
    "confidence": 0.0-1.0,
    "parameters": {{...}},
    "reasoning": "why this skill fits"
}}""",
        temperature=0.1,
    )
    return result


def calculate_bid_price(opportunity: dict) -> float:
    """Calculate competitive bid price based on opportunity budget and complexity."""
    estimated_value = float(opportunity.get("estimated_value", 0))
    complexity = opportunity.get("complexity", "medium")
    platform = opportunity.get("platform", "unknown")
    
    # Base pricing by complexity
    complexity_multipliers = {
        "low": 0.6,     # Bid 60% of estimated value for simple tasks
        "medium": 0.75, # Bid 75% for medium complexity
        "high": 0.9,    # Bid 90% for complex tasks (less competition)
    }
    
    base_price = estimated_value * complexity_multipliers.get(complexity, 0.75)
    
    # Platform adjustments
    if platform == "clawgig":
        base_price *= 0.95  # Slightly lower for established platform
    elif platform == "twitter":
        base_price *= 0.8   # More aggressive pricing for speculative leads
    
    # Minimum viable price
    return max(base_price, 10.0)


def execute_task(opportunity: dict) -> dict:
    """Execute a task opportunity and return results."""
    task_id = opportunity.get("id")
    description = opportunity.get("description", "")
    
    log.info("Executing task %s: %s", task_id, description[:100])
    
    try:
        # Security check
        safe, reason = sanitise_task(description)
        if not safe:
            return {"success": False, "error": f"Security check failed: {reason}"}
        
        # Pick skill and extract parameters
        skill_choice = pick_skill(description)
        skill_name = skill_choice.get("skill")
        confidence = skill_choice.get("confidence", 0)
        parameters = skill_choice.get("parameters", {})
        
        if confidence < 0.3:
            return {"success": False, "error": f"Low confidence in skill selection: {confidence}"}
        
        if skill_name not in SKILLS:
            return {"success": False, "error": f"Unknown skill: {skill_name}"}
        
        # Validate parameters before execution
        valid, validation_error = validate_task_parameters(skill_name, parameters, description)
        if not valid:
            return {"success": False, "error": f"Parameter validation failed: {validation_error}"}
        
        # Execute the skill
        skill_func = SKILLS[skill_name]
        
        if skill_name == "scrape":
            result = skill_func(
                url=parameters.get("url"),
                extract_what=parameters.get("extract_what", "all content")
            )
        elif skill_name == "extract":
            result = skill_func(
                raw_text=parameters.get("raw_text"),
                schema_description=parameters.get("schema_description")
            )
        elif skill_name == "enrich":
            result = skill_func(
                items=parameters.get("items"),
                enrich_with=parameters.get("enrich_with")
            )
        elif skill_name == "automate":
            result = skill_func(
                workflow_description=parameters.get("workflow_description")
            )
        else:
            return {"success": False, "error": f"Skill {skill_name} not implemented"}
        
        if result.get("success"):
            log.info("Task %s completed successfully", task_id)
            return {
                "success": True,
                "skill_used": skill_name,
                "result": result,
                "confidence": confidence
            }
        else:
            log.warning("Task %s failed: %s", task_id, result.get("error"))
            return {"success": False, "error": result.get("error", "Unknown skill error")}
    
    except Exception as e:
        log.error("Task execution error for %s: %s\n%s", task_id, e, traceback.format_exc())
        return {"success": False, "error": f"Execution exception: {str(e)}"}


def handle_clawgig_events():
    """Process new ClawGig events and update opportunity statuses."""
    events = get_unprocessed_clawgig_events()
    for event in events:
        try:
            gig_id = event.get("gig_id")
            event_type = event.get("event_type")
            
            if event_type == "gig_completed":
                # Find our opportunity record
                opp = find_opportunity_by_gig_id(gig_id)
                if opp:
                    # Record payment
                    amount = float(event.get("amount_usdc", 0))
                    if amount > 0:
                        record_income(amount, f"ClawGig completion: {gig_id}")
                        notify_payment(amount, "USDC", "ClawGig")
                        log.info("Recorded ClawGig payment: $%.2f USDC", amount)
            
            mark_clawgig_event_processed(event["id"])
        except Exception as e:
            log.error("Error processing ClawGig event %s: %s", event.get("id"), e)


def run_cycle():
    """Run one Worker cycle — pick tasks, execute them, log results."""
    run_id = log_run_start("worker")
    
    try:
        # Handle ClawGig events first
        handle_clawgig_events()
        
        # Get new opportunities
        opportunities = get_new_opportunities(limit=20)
        if not opportunities:
            log.info("No new opportunities found")
            log_run_end(run_id, status="completed", summary={"tasks_attempted": 0})
            return
        
        # Rank by ROI
        ranked = rank_opportunities(opportunities)
        
        # Attempt top tasks
        attempted = 0
        completed = 0
        
        for opp in ranked[:MAX_TASKS_PER_CYCLE]:
            attempted += 1
            
            # Mark as in progress
            update_opportunity(opp["id"], status="in_progress")
            
            # Execute task
            result = execute_task(opp)
            
            if result["success"]:
                completed += 1
                update_opportunity(
                    opp["id"],
                    status="completed",
                    result=result["result"],
                    metadata={"skill_used": result["skill_used"]}
                )
                
                # Calculate and record payment
                bid_price = calculate_bid_price(opp)
                record_income(bid_price, f"Task completion: {opp['id']}")
                
                notify_job_completed(
                    task_id=opp["id"],
                    platform=opp.get("platform", "unknown"),
                    amount=bid_price,
                    skill=result["skill_used"]
                )
                
                log.info("Task %s completed, recorded $%.2f income", opp["id"], bid_price)
            else:
                update_opportunity(
                    opp["id"],
                    status="failed",
                    error=result["error"]
                )
                log.warning("Task %s failed: %s", opp["id"], result["error"])
        
        summary = {
            "opportunities_found": len(opportunities),
            "tasks_attempted": attempted,
            "tasks_completed": completed,
            "success_rate": completed / attempted if attempted > 0 else 0
        }
        
        log.info(
            "Worker cycle: %d opportunities, %d attempted, %d completed (%.1f%% success)",
            len(opportunities), attempted, completed,
            100 * completed / attempted if attempted > 0 else 0
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