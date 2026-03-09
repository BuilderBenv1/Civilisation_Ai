"""BD Agent — finds projects needing AgentProof trust scores and drafts outreach.

Runs on a 2-hour cycle:
1. Scan X for relevant conversations
2. Evaluate each as a prospect via Claude
3. Add qualified prospects to CRM
4. Draft outreach for new prospects (queued for human approval)
"""

import sys
import os
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from shared.config import get_logger
from shared.supabase_client import log_run_start, log_run_end, get_prospects
from shared.messaging import AgentMailbox
from agents.bd.x_monitor import scan_all_queries
from agents.bd.crm import add_prospect, queue_outreach, get_active_prospects
from agents.bd.outreach import draft_outreach, evaluate_prospect
from shared.telegram import notify_action_needed, send as tg_send

log = get_logger("bd")
mailbox = AgentMailbox("bd")

# Minimum confidence to add as prospect
PROSPECT_THRESHOLD = 0.6


def run_cycle():
    """Single BD cycle: scan -> evaluate -> prospect -> draft outreach."""
    run_id = log_run_start("bd")
    stats = {"tweets_scanned": 0, "prospects_found": 0, "drafts_queued": 0}
    drafts_queued_handles = []

    try:
        # 1. Scan X/Twitter
        log.info("Starting BD scan cycle")
        tweets = scan_all_queries()
        stats["tweets_scanned"] = len(tweets)

        # Get existing prospect handles to avoid duplicates
        existing = {p["handle"].lower() for p in get_active_prospects()}

        # 2. Evaluate each tweet
        for tweet in tweets:
            author = tweet.get("author", "")
            if not author or author.lower() in existing:
                continue

            evaluation = evaluate_prospect(tweet["text"], author)

            if (
                evaluation.get("is_prospect")
                and evaluation.get("confidence", 0) >= PROSPECT_THRESHOLD
            ):
                # 3. Add to CRM
                context = (
                    f"Tweet: {tweet['text'][:500]}\n"
                    f"Matched query: {tweet.get('matched_query', '')}\n"
                    f"Evaluation: {evaluation.get('reason', '')}\n"
                    f"Integration angle: {evaluation.get('integration_angle', '')}"
                )
                prospect = add_prospect(
                    handle=author,
                    platform="twitter",
                    context=context,
                    notes=f"Priority: {evaluation.get('priority', 'medium')}",
                )
                existing.add(author.lower())
                stats["prospects_found"] += 1

                # 4. Draft outreach for high/medium priority
                if evaluation.get("priority") in ("high", "medium") and prospect.get("id"):
                    draft = draft_outreach(
                        handle=author,
                        context=context,
                        channel="twitter_dm",
                    )
                    queue_outreach(
                        prospect_id=prospect["id"],
                        channel="twitter_dm",
                        message_draft=draft,
                    )
                    stats["drafts_queued"] += 1
                    drafts_queued_handles.append(f"@{author}")

        # Single batched Telegram notification for all drafts
        if drafts_queued_handles:
            handles_list = ", ".join(drafts_queued_handles)
            notify_action_needed(
                f"{len(drafts_queued_handles)} BD outreach drafts need approval:\n"
                f"{handles_list}\n\n"
                f"Run: python -m agents.bd.approve"
            )

        # Check mailbox for messages from other agents
        messages = mailbox.receive()
        for msg in messages:
            log.info("BD received message: %s from %s", msg.get("message_type"), msg.get("from_agent"))
        if messages:
            mailbox.ack(messages)

        log.info(
            "BD cycle complete: %d tweets scanned, %d prospects, %d drafts",
            stats["tweets_scanned"], stats["prospects_found"], stats["drafts_queued"],
        )
        log_run_end(run_id, status="completed", summary=stats)

    except Exception as e:
        log.error("BD cycle failed: %s\n%s", e, traceback.format_exc())
        log_run_end(run_id, status="failed", error=str(e))
        raise


def seed_quantu_prospect():
    """First live task: seed Quantu as a prospect and draft outreach."""
    log.info("Seeding Quantu prospect")

    context = (
        "Quantu (@Quantu_AI) announced an agent economy layer on Solana:\n"
        "- Agent identity registry (ERC-8004 on Solana)\n"
        "- Perp DEX for agents\n"
        "- Settlers who execute trades, stake $QX, build reputation\n"
        "- Structured feedback written to agent identities after each trade\n"
        "- Testnet launching end of March 2026\n\n"
        "Integration angle: Quantu settlers need trust scores. Their trading agents "
        "produce feedback that needs independent verification. AgentProof is the scoring "
        "layer that makes settler reputation legible to the rest of the EVM ecosystem."
    )

    prospect = add_prospect(
        handle="Quantu_AI",
        platform="twitter",
        context=context,
        notes="Priority: high. First BD target. ERC-8004 shared spec. Testnet end of March.",
    )

    if prospect.get("id"):
        draft = draft_outreach(
            handle="Quantu_AI",
            context=context,
            channel="twitter_dm",
        )
        queue_outreach(
            prospect_id=prospect["id"],
            channel="twitter_dm",
            message_draft=draft,
        )
        log.info("Quantu outreach queued for approval")
    else:
        log.error("Failed to create Quantu prospect")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="BD Agent")
    parser.add_argument("--seed-quantu", action="store_true", help="Seed Quantu as first prospect")
    parser.add_argument("--cycle", action="store_true", help="Run one BD cycle")
    args = parser.parse_args()

    if args.seed_quantu:
        seed_quantu_prospect()
    elif args.cycle:
        run_cycle()
    else:
        print("Usage: python -m agents.bd.bd --seed-quantu | --cycle")
