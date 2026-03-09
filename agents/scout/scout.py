"""Scout Agent — finds tasks and opportunities for the Worker to complete.

Runs on a 2-hour cycle:
1. Scan X/Twitter for agent-completable tasks
2. Crawl marketplace RSS feeds (Upwork, etc.)
3. Evaluate each opportunity with Claude
4. Post qualified opportunities to the Supabase task board
"""

import sys
import os
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from shared.config import get_logger
from shared.supabase_client import (
    insert_opportunity, log_run_start, log_run_end, get_new_opportunities,
)
from shared.messaging import AgentMailbox
from shared.anthropic_client import ask_json
from agents.scout.x_monitor import scan_all_queries
from agents.scout.marketplace_crawler import crawl_all, evaluate_task
from shared.telegram import notify_scout_cycle

log = get_logger("scout")
mailbox = AgentMailbox("scout")

# ── Tweet pre-filter — fast keyword check before Claude evaluation ────
# Drops tweets that are just commentary/news/promotion with no actionable task.
# Only tweets that pass this gate get sent to Claude for full evaluation.

# Someone is actively requesting paid work — first person, transactional language
_HIRE_SIGNALS = [
    "hiring", "looking to hire", "paying", "budget is",
    "dm me", "dm for rates", "per hour", "fixed price",
    "need someone to", "need a dev", "need a bot",
    "looking for someone", "looking for a dev", "looking for an agent",
    "can someone build", "who can build", "build me",
    "freelance", "contract work",
]

# Mentions money explicitly
_MONEY_SIGNALS = ["$", "usd", "usdc", "eth", "budget", "bounty", "reward"]

_NOISE_SIGNALS = [
    "just launched", "check out", "introducing", "we're excited",
    "thread", "now live", "announcing", "is live",
    "follow me", "retweet", "like and", "rt if", "giveaway",
    "breaking:", "news:", "update:", "recap", "icymi",
    "nfa", "dyor", "alpha", "not financial",
    "subscribe", "join our", "sign up", "airdrop",
    "tutorial", "learn how", "course", "webinar",
    "meme", "lol", "lmao", "ratio",
]

# Cross-cycle dedup — remember tweet IDs we've already evaluated
_seen_tweet_ids: set[str] = set()
_MAX_SEEN = 5000

# Cap Claude evaluations per cycle — hard limit on API spend
_MAX_EVALUATIONS_PER_CYCLE = 15


def prefilter_tweet(tweet: dict) -> bool:
    """Tight keyword gate — only passes tweets where someone is clearly hiring/paying.

    Requires explicit hire/transactional language OR money mention + task language.
    """
    text = tweet.get("text", "").lower()
    if len(text) < 50:
        return False

    hire_hits = sum(1 for s in _HIRE_SIGNALS if s in text)
    money_hits = sum(1 for s in _MONEY_SIGNALS if s in text)
    noise_hits = sum(1 for s in _NOISE_SIGNALS if s in text)

    if noise_hits >= 2:
        return False

    # Either clear hiring language, or money + task intent
    return hire_hits >= 1 or (money_hits >= 1 and hire_hits >= 0 and
                               any(w in text for w in ["need", "build", "scrape", "automate", "extract", "bot"]))


def run_cycle():
    """Single Scout cycle: scan sources -> evaluate -> post opportunities."""
    run_id = log_run_start("scout")
    stats = {"x_tweets": 0, "marketplace_tasks": 0, "opportunities_posted": 0}

    try:
        log.info("Starting Scout scan cycle")

        # Track URLs/tweet IDs we've already posted to avoid duplicates
        existing = get_new_opportunities(limit=100)
        existing_urls = {
            o.get("metadata", {}).get("source_url", "")
            for o in existing if o.get("metadata")
        }

        # 1. Scan X/Twitter for task requests
        tweets = scan_all_queries()
        stats["x_tweets"] = len(tweets)

        # Pre-filter: keyword gate + cross-cycle dedup
        filtered_tweets = []
        skipped_seen = 0
        for t in tweets:
            tid = t.get("tweet_id", t.get("url", ""))
            if tid in _seen_tweet_ids:
                skipped_seen += 1
                continue
            _seen_tweet_ids.add(tid)
            if prefilter_tweet(t):
                filtered_tweets.append(t)

        # Trim dedup set if it gets too large
        if len(_seen_tweet_ids) > _MAX_SEEN:
            excess = len(_seen_tweet_ids) - _MAX_SEEN
            for _ in range(excess):
                _seen_tweet_ids.pop()

        # Hard cap — don't burn API on more than 15 tweets per cycle
        if len(filtered_tweets) > _MAX_EVALUATIONS_PER_CYCLE:
            filtered_tweets = filtered_tweets[:_MAX_EVALUATIONS_PER_CYCLE]

        log.info(
            "Pre-filter: %d/%d tweets to evaluate (%d already seen, %d dropped by keywords, cap=%d)",
            len(filtered_tweets), len(tweets), skipped_seen,
            len(tweets) - skipped_seen - len(filtered_tweets),
            _MAX_EVALUATIONS_PER_CYCLE,
        )

        for tweet in filtered_tweets:
            url = tweet.get("url", "")
            if url in existing_urls:
                continue

            # Evaluate tweet as a potential task
            evaluation = evaluate_task(
                title=f"X post by @{tweet.get('author', '')}",
                description=tweet.get("text", ""),
                platform="twitter",
            )

            if evaluation.get("completable") and evaluation.get("confidence", 0) >= 0.5:
                opp = insert_opportunity({
                    "platform": "twitter",
                    "task_description": (
                        f"From @{tweet['author']}: {tweet['text'][:500]}\n\n"
                        f"Approach: {evaluation.get('approach', 'N/A')}"
                    ),
                    "estimated_value": evaluation.get("estimated_value_usd"),
                    "complexity": evaluation.get("complexity", "medium"),
                    "source_url": url,
                    "metadata": {
                        "source_url": url,
                        "tweet_id": tweet.get("tweet_id"),
                        "author": tweet.get("author"),
                        "matched_query": tweet.get("matched_query"),
                        "evaluation": evaluation,
                    },
                })
                existing_urls.add(url)
                stats["opportunities_posted"] += 1
                log.info("Posted opportunity from @%s", tweet.get("author"))

        # 2. Crawl marketplace feeds
        marketplace_tasks = crawl_all()
        stats["marketplace_tasks"] = len(marketplace_tasks)

        for task in marketplace_tasks:
            url = task.get("url", "")
            if url in existing_urls:
                continue

            ev = task.get("evaluation", {})
            opp = insert_opportunity({
                "platform": task.get("platform", "unknown"),
                "task_description": (
                    f"{task.get('title', 'Untitled')}\n\n"
                    f"{task.get('description', '')[:500]}\n\n"
                    f"Approach: {ev.get('approach', 'N/A')}"
                ),
                "estimated_value": ev.get("estimated_value_usd"),
                "complexity": ev.get("complexity", "medium"),
                "source_url": url,
                "metadata": {
                    "source_url": url,
                    "evaluation": ev,
                    # ClawGig-specific fields
                    "gig_id": task.get("gig_id", ""),
                    "budget_usdc": task.get("budget_usdc", 0),
                    "category": task.get("category", ""),
                    "skills": task.get("skills", []),
                    # Moltlaunch-specific fields
                    "moltlaunch_task_id": task.get("moltlaunch_task_id", ""),
                    "price_eth": task.get("price_eth", 0),
                    # Agent Bounty-specific fields
                    "reward_usd": task.get("reward_usd", 0),
                    "difficulty": task.get("difficulty", ""),
                    "bounty_category": task.get("bounty_category", ""),
                },
            })
            existing_urls.add(url)
            stats["opportunities_posted"] += 1

        # 3. Notify Worker about new opportunities
        if stats["opportunities_posted"] > 0:
            mailbox.send("worker", "new_opportunities", {
                "count": stats["opportunities_posted"],
                "message": f"Scout found {stats['opportunities_posted']} new opportunities",
            })

        # 4. Check mailbox (e.g., Worker feedback on failed tasks)
        messages = mailbox.receive()
        for msg in messages:
            if msg.get("message_type") == "task_feedback":
                payload = msg.get("payload", {})
                log.info(
                    "Worker feedback on task %s: %s",
                    payload.get("task_id"), payload.get("feedback"),
                )
        if messages:
            mailbox.ack(messages)

        log.info(
            "Scout cycle complete: %d tweets, %d marketplace, %d posted",
            stats["x_tweets"], stats["marketplace_tasks"], stats["opportunities_posted"],
        )
        notify_scout_cycle(
            tweets=stats["x_tweets"],
            filtered=len(filtered_tweets),
            marketplace=stats["marketplace_tasks"],
            posted=stats["opportunities_posted"],
        )
        log_run_end(run_id, status="completed", summary=stats)

    except Exception as e:
        log.error("Scout cycle failed: %s\n%s", e, traceback.format_exc())
        log_run_end(run_id, status="failed", error=str(e))
        raise


if __name__ == "__main__":
    run_cycle()
