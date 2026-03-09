"""Scout X/Twitter monitor — finds tasks and gigs agents can complete."""

import requests
from shared.config import RAPIDAPI_KEY, get_logger

log = get_logger("scout.x_monitor")

SEARCH_QUERIES = [
    "looking for agent to",
    "need automation for",
    "agent marketplace",
    "a2a task",
    "hiring bot developer",
    "need scraping done",
    "data extraction project",
    "automate this workflow",
    "need an AI agent",
    "agent bounty",
]

TWITTER_SEARCH_URL = "https://twitter-api45.p.rapidapi.com/search.php"
TWITTER_HEADERS = {
    "x-rapidapi-key": RAPIDAPI_KEY,
    "x-rapidapi-host": "twitter-api45.p.rapidapi.com",
}


def search_x(query: str, count: int = 20) -> list[dict]:
    """Search X for task opportunities."""
    if not RAPIDAPI_KEY:
        log.warning("RAPIDAPI_KEY not set, skipping X search for: %s", query)
        return []

    try:
        resp = requests.get(
            TWITTER_SEARCH_URL,
            headers=TWITTER_HEADERS,
            params={"query": query, "search_type": "Latest"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        log.error("X search failed for '%s': %s", query, e)
        return []

    tweets = []
    timeline = data.get("timeline", [])
    for item in timeline[:count]:
        tweets.append({
            "text": item.get("text", ""),
            "author": item.get("screen_name", ""),
            "tweet_id": item.get("tweet_id", ""),
            "created_at": item.get("created_at", ""),
            "url": f"https://x.com/{item.get('screen_name', '')}/status/{item.get('tweet_id', '')}",
        })
    log.info("Scout X search '%s': found %d tweets", query, len(tweets))
    return tweets


def scan_all_queries() -> list[dict]:
    """Run all Scout search queries and return deduplicated results."""
    all_tweets = []
    seen_ids = set()
    for query in SEARCH_QUERIES:
        for tweet in search_x(query):
            tid = tweet.get("tweet_id")
            if tid and tid not in seen_ids:
                seen_ids.add(tid)
                tweet["matched_query"] = query
                all_tweets.append(tweet)
    log.info("Scout X scan: %d unique tweets from %d queries", len(all_tweets), len(SEARCH_QUERIES))
    return all_tweets
