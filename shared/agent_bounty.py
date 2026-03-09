"""Agent Bounty client — bounty platform for AI agent development.

Site: https://agentbounty.org
No documented API — uses web scraping to monitor bounties.
Payment: crypto or bank transfer, avg $4,200/bounty.
"""

import requests
import re
from shared.config import get_logger

log = get_logger("agent_bounty")

BASE_URL = "https://agentbounty.org"


def fetch_bounties() -> list[dict]:
    """Scrape active bounties from Agent Bounty. Returns structured list."""
    try:
        resp = requests.get(
            f"{BASE_URL}/bounties",
            timeout=30,
            headers={"User-Agent": "AgentTown-Scout/1.0"},
        )
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        log.error("Agent Bounty fetch failed: %s", e)
        return []

    bounties = _parse_bounties(html)
    log.info("Agent Bounty: found %d bounties", len(bounties))
    return bounties


def _parse_bounties(html: str) -> list[dict]:
    """Extract bounty data from HTML. Fragile — depends on page structure."""
    bounties = []

    # Try to extract structured bounty data from the page
    # Look for common patterns: title + reward amount
    # Pattern: reward amounts like $15,000 or $3,200
    reward_pattern = re.compile(r'\$[\d,]+(?:\.\d{2})?')
    rewards = reward_pattern.findall(html)

    # Look for bounty titles — typically in headings or card titles
    # This is best-effort scraping; the exact selectors depend on the site structure
    title_patterns = [
        re.compile(r'<h[23][^>]*>(.*?)</h[23]>', re.DOTALL),
        re.compile(r'class="[^"]*title[^"]*"[^>]*>(.*?)</', re.DOTALL),
        re.compile(r'class="[^"]*bounty[^"]*name[^"]*"[^>]*>(.*?)</', re.DOTALL),
    ]

    titles = []
    for pattern in title_patterns:
        matches = pattern.findall(html)
        # Strip HTML tags from matches
        cleaned = [re.sub(r'<[^>]+>', '', m).strip() for m in matches]
        cleaned = [t for t in cleaned if len(t) > 10 and len(t) < 200]
        if cleaned:
            titles = cleaned
            break

    # Look for difficulty levels
    difficulties = re.findall(
        r'(?:Intermediate|Advanced|Expert|Beginner)',
        html,
        re.IGNORECASE,
    )

    # Look for categories
    categories = re.findall(
        r'(?:Agent Frameworks|Benchmarks|Open Source|Research|Integration|Security)',
        html,
        re.IGNORECASE,
    )

    # Zip what we found into structured bounties
    for i, title in enumerate(titles):
        bounty = {
            "platform": "agent_bounty",
            "title": title,
            "url": f"{BASE_URL}/bounties",
            "description": title,
        }
        if i < len(rewards):
            # Parse reward: "$15,000" -> 15000.0
            reward_str = rewards[i].replace('$', '').replace(',', '')
            try:
                bounty["reward_usd"] = float(reward_str)
            except ValueError:
                pass
        if i < len(difficulties):
            bounty["difficulty"] = difficulties[i].lower()
        if i < len(categories):
            bounty["category"] = categories[i]

        bounties.append(bounty)

    return bounties


def evaluate_bounty_fit(title: str, description: str, reward: float = 0) -> dict:
    """Use Claude to assess if Worker can complete this bounty.

    Deliberately conservative — a bad submission on a $4k bounty damages
    reputation more than the revenue is worth. Better to skip 3 good
    bounties than to submit poorly on one.
    """
    from shared.anthropic_client import ask_json

    prompt = f"""Evaluate this bounty for an autonomous AI worker agent. BE CONSERVATIVE.

Bounty: {title}
Description: {description[:1000]}
Reward: ${reward:.0f}

The worker agent can do WELL:
- Web scraping (Playwright, BeautifulSoup)
- Data enrichment and structured extraction
- API integrations and automation pipelines
- Python code generation and execution

The worker agent CANNOT do (mark completable=false):
- Long-term research projects (multi-week)
- Hardware, physical, or UI/UX design work
- Tasks requiring human judgement, creativity, or subjective quality
- Tasks needing access to proprietary systems or credentials we don't have
- Anything requiring manual review loops or iterative human feedback

IMPORTANT: A failed or low-quality submission on a high-value bounty destroys
platform reputation. Only return completable=true AND confidence >= 0.8 if you
are genuinely certain the agent can deliver a HIGH QUALITY result autonomously
in one pass. When in doubt, return completable=false.

Return JSON:
{{
    "completable": true/false,
    "confidence": 0.0-1.0,
    "estimated_hours": number,
    "complexity": "low" | "medium" | "high",
    "reason": "one sentence",
    "approach": "brief description",
    "risk_factors": ["list of things that could go wrong"]
}}"""

    try:
        return ask_json(prompt, temperature=0.1)
    except Exception as e:
        log.error("Bounty evaluation failed: %s", e)
        return {"completable": False, "confidence": 0, "reason": str(e)}
