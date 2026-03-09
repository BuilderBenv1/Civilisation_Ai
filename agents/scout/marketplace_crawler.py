"""Marketplace crawler — checks known agent task platforms for opportunities."""

import requests
from shared.config import get_logger
from shared.anthropic_client import ask_json

log = get_logger("scout.crawler")


def crawl_upwork_rss() -> list[dict]:
    """Fetch Upwork automation/scraping RSS feed. Returns task dicts."""
    feeds = [
        "https://www.upwork.com/ab/feed/jobs/rss?q=web+scraping&sort=recency",
        "https://www.upwork.com/ab/feed/jobs/rss?q=data+extraction+automation&sort=recency",
        "https://www.upwork.com/ab/feed/jobs/rss?q=python+automation+bot&sort=recency",
    ]
    tasks = []
    for feed_url in feeds:
        try:
            resp = requests.get(feed_url, timeout=30, headers={
                "User-Agent": "AgentTown-Scout/1.0"
            })
            if resp.status_code != 200:
                log.warning("Upwork RSS returned %d for %s", resp.status_code, feed_url)
                continue
            # Simple XML parsing for RSS items
            items = _parse_rss_items(resp.text)
            tasks.extend(items)
        except Exception as e:
            log.error("Upwork RSS fetch failed: %s", e)
    log.info("Upwork crawler: found %d tasks", len(tasks))
    return tasks


def _parse_rss_items(xml_text: str) -> list[dict]:
    """Minimal RSS parser — extracts title, link, description from items."""
    import re
    items = []
    for match in re.finditer(r"<item>(.*?)</item>", xml_text, re.DOTALL):
        item_xml = match.group(1)
        title = _extract_tag(item_xml, "title")
        link = _extract_tag(item_xml, "link")
        desc = _extract_tag(item_xml, "description")
        if title:
            items.append({
                "platform": "upwork",
                "title": title,
                "url": link or "",
                "description": desc or "",
            })
    return items


def _extract_tag(xml: str, tag: str) -> str:
    import re
    m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", xml, re.DOTALL)
    if m:
        # Strip CDATA
        text = m.group(1).strip()
        text = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", text, flags=re.DOTALL)
        # Strip HTML tags
        text = re.sub(r"<[^>]+>", "", text)
        return text.strip()
    return ""


def evaluate_task(title: str, description: str, platform: str) -> dict:
    """Use Claude to assess if our Worker agent can complete this task."""
    prompt = f"""Evaluate this task for an autonomous AI worker agent.

Platform: {platform}
Title: {title}
Description: {description[:1000]}

The worker agent can:
- Web scraping (Playwright, BeautifulSoup)
- Data enrichment (take a list, return structured data)
- Automation pipelines
- Structured data extraction from documents
- API integrations

Return JSON:
{{
    "completable": true/false,
    "confidence": 0.0-1.0,
    "estimated_value_usd": number or null,
    "complexity": "low" | "medium" | "high",
    "reason": "one sentence",
    "approach": "brief description of how to complete it"
}}"""

    try:
        return ask_json(prompt, temperature=0.2)
    except Exception as e:
        log.error("Task evaluation failed: %s", e)
        return {"completable": False, "confidence": 0, "reason": str(e)}


def crawl_clawgig() -> list[dict]:
    """Fetch available gigs from ClawGig — REST API agent marketplace, pays USDC."""
    try:
        from shared.clawgig import browse_gigs
        gigs = browse_gigs(sort="newest")
    except Exception as e:
        log.error("ClawGig fetch failed: %s", e)
        return []

    tasks = []
    for gig in gigs:
        gig_id = gig.get("id", gig.get("gig_id", ""))
        budget = gig.get("budget", gig.get("budget_usdc", 0))
        tasks.append({
            "platform": "clawgig",
            "title": gig.get("title", "Untitled gig"),
            "url": f"https://clawgig.ai/gigs/{gig_id}",
            "description": gig.get("description", ""),
            "gig_id": gig_id,
            "budget_usdc": budget,
            "category": gig.get("category", ""),
            "skills": gig.get("skills", []),
        })
    log.info("ClawGig crawler: found %d gigs", len(tasks))
    return tasks


def crawl_moltlaunch() -> list[dict]:
    """Fetch available tasks from Moltlaunch — onchain agent marketplace on Base, pays ETH."""
    try:
        from shared.moltlaunch import browse_tasks
        raw_tasks = browse_tasks(limit=50)
    except Exception as e:
        log.error("Moltlaunch fetch failed: %s", e)
        return []

    tasks = []
    for t in raw_tasks:
        task_id = t.get("id", t.get("task_id", ""))
        price_eth = float(t.get("price", t.get("price_eth", t.get("amount", 0))) or 0)
        # Rough ETH→USD for scoring (conservative estimate)
        estimated_usd = price_eth * 2500 if price_eth > 0 else 0
        tasks.append({
            "platform": "moltlaunch",
            "title": t.get("title", t.get("name", "Untitled task")),
            "url": f"https://moltlaunch.com/tasks/{task_id}",
            "description": t.get("description", ""),
            "moltlaunch_task_id": task_id,
            "price_eth": price_eth,
            "estimated_usd": estimated_usd,
            "skills": t.get("skills", []),
        })
    log.info("Moltlaunch crawler: found %d tasks", len(tasks))
    return tasks


def crawl_agent_bounty() -> list[dict]:
    """Fetch active bounties from Agent Bounty — bounty platform for AI agent dev."""
    try:
        from shared.agent_bounty import fetch_bounties
        raw = fetch_bounties()
    except Exception as e:
        log.error("Agent Bounty fetch failed: %s", e)
        return []

    tasks = []
    for b in raw:
        tasks.append({
            "platform": "agent_bounty",
            "title": b.get("title", "Untitled bounty"),
            "url": b.get("url", "https://agentbounty.org/bounties"),
            "description": b.get("description", ""),
            "reward_usd": float(b.get("reward_usd", 0) or 0),
            "difficulty": b.get("difficulty", ""),
            "bounty_category": b.get("category", ""),
        })
    log.info("Agent Bounty crawler: found %d bounties", len(tasks))
    return tasks


def crawl_all() -> list[dict]:
    """Crawl all marketplaces. Returns evaluated task dicts."""
    all_tasks = []

    # ClawGig — clean REST API, no scraping, USDC payments
    clawgig_tasks = crawl_clawgig()
    for task in clawgig_tasks:
        evaluation = evaluate_task(
            title=task.get("title", ""),
            description=task.get("description", ""),
            platform="clawgig",
        )
        if evaluation.get("completable") and evaluation.get("confidence", 0) >= 0.4:
            if task.get("budget_usdc"):
                evaluation["estimated_value_usd"] = float(task["budget_usdc"])
            task["evaluation"] = evaluation
            all_tasks.append(task)

    # Moltlaunch — onchain agent marketplace, ETH payments
    moltlaunch_tasks = crawl_moltlaunch()
    for task in moltlaunch_tasks:
        evaluation = evaluate_task(
            title=task.get("title", ""),
            description=task.get("description", ""),
            platform="moltlaunch",
        )
        if evaluation.get("completable") and evaluation.get("confidence", 0) >= 0.4:
            if task.get("estimated_usd"):
                evaluation["estimated_value_usd"] = task["estimated_usd"]
            task["evaluation"] = evaluation
            all_tasks.append(task)

    # Agent Bounty — bounty platform, crypto/bank payments
    bounty_tasks = crawl_agent_bounty()
    for task in bounty_tasks:
        evaluation = evaluate_task(
            title=task.get("title", ""),
            description=task.get("description", ""),
            platform="agent_bounty",
        )
        if evaluation.get("completable") and evaluation.get("confidence", 0) >= 0.4:
            if task.get("reward_usd"):
                evaluation["estimated_value_usd"] = task["reward_usd"]
            task["evaluation"] = evaluation
            all_tasks.append(task)

    # Upwork RSS
    raw_tasks = crawl_upwork_rss()
    for task in raw_tasks:
        evaluation = evaluate_task(
            title=task.get("title", ""),
            description=task.get("description", ""),
            platform=task.get("platform", "unknown"),
        )
        if evaluation.get("completable") and evaluation.get("confidence", 0) >= 0.5:
            task["evaluation"] = evaluation
            all_tasks.append(task)

    log.info("Marketplace crawl: %d viable tasks after evaluation", len(all_tasks))
    return all_tasks
