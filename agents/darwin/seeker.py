"""Seeker — autonomous new income channel discovery.

When treasury is stagnant (no growth in 48h), Darwin enters SEEK mode.
Seeker searches for new marketplaces, bounty boards, and task platforms,
evaluates them against a viability rubric, and drops stubs into
discovered/ folders for human review before activation.
"""

import sys
import os
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from shared.config import get_logger, PRIME_DIRECTIVE
from shared.anthropic_client import ask_json, ask
from shared.supabase_client import get_client
from shared.telegram import notify_action_needed

log = get_logger("darwin.seeker")

# Viability rubric weights
VIABILITY_WEIGHTS = {
    "has_api_or_scrape_path": 0.25,
    "pays_crypto_or_stripe": 0.25,
    "tasks_match_skills": 0.25,
    "active_marketplace": 0.15,
    "low_barrier_to_entry": 0.10,
}

# Known platforms (already integrated — skip these)
_KNOWN_PLATFORMS = {
    "clawgig", "moltlaunch", "agent_bounty", "upwork",
    "fiverr", "freelancer",
}


def check_treasury_stagnant(hours: int = 48) -> bool:
    """Check if treasury has had zero new income in the last N hours."""
    try:
        sb = get_client()
        cutoff = (datetime.datetime.now(datetime.timezone.utc)
                  - datetime.timedelta(hours=hours)).isoformat()
        result = sb.table("treasury").select("id", count="exact").gte(
            "received_at", cutoff
        ).execute()
        return (result.count or 0) == 0
    except Exception as e:
        log.error("Treasury stagnation check failed: %s", e)
        return True  # Assume stagnant if we can't check


def discover_platforms() -> list[dict]:
    """Use Claude to find new agent task platforms and marketplaces.

    Returns list of platform dicts with viability scores.
    """
    prompt = f"""{PRIME_DIRECTIVE}

You are the Seeker module of Darwin, Agent Town's evolution engine.
The treasury is stagnant. Your job: find NEW platforms where an
autonomous AI agent can earn money.

The agent (Worker) can do:
- Web scraping (Playwright, BeautifulSoup)
- Data extraction and enrichment
- API integrations and automation
- Python code generation and execution
- Simple content generation

Already integrated (DO NOT suggest these): {', '.join(_KNOWN_PLATFORMS)}

Search your knowledge for:
1. Agent-to-agent task marketplaces (like ClawGig, Moltlaunch)
2. Bounty platforms (like Gitcoin, Agent Bounty)
3. Micro-task platforms that accept API/bot workers
4. Crypto-native task boards
5. AI agent hiring platforms

For each platform found, evaluate:
- Does it have an API or can it be scraped?
- Does it pay in crypto, USDC, or via Stripe?
- Do the available tasks match Worker's skills?
- Is it actively used (not dead)?
- Can Worker register/start without manual ID verification?

Return JSON:
{{
    "platforms": [
        {{
            "name": "platform_name",
            "url": "https://...",
            "description": "one sentence",
            "api_available": true/false,
            "scrape_possible": true/false,
            "payment_method": "crypto" | "stripe" | "bank" | "unknown",
            "task_types": ["list", "of", "task", "types"],
            "viability_score": 0.0-1.0,
            "registration_method": "api_key" | "oauth" | "manual" | "wallet",
            "notes": "any important details"
        }}
    ]
}}

Be realistic. Only include platforms that actually exist and are active.
Do not hallucinate platforms. If you're unsure, set viability_score low."""

    try:
        result = ask_json(prompt, temperature=0.3)
        platforms = result.get("platforms", [])
        # Filter out known platforms and low-viability ones
        viable = [
            p for p in platforms
            if p.get("name", "").lower().replace(" ", "_") not in _KNOWN_PLATFORMS
            and p.get("viability_score", 0) >= 0.4
        ]
        log.info("Seeker: found %d viable new platforms (from %d total)", len(viable), len(platforms))
        return viable
    except Exception as e:
        log.error("Platform discovery failed: %s", e)
        return []


def generate_crawler_stub(platform: dict) -> str:
    """Generate a crawler stub for a new platform."""
    name = platform.get("name", "unknown").lower().replace(" ", "_").replace("-", "_")
    url = platform.get("url", "https://example.com")
    desc = platform.get("description", "")
    api = platform.get("api_available", False)

    prompt = f"""Write a Python crawler stub for this platform:

Name: {name}
URL: {url}
Description: {desc}
Has API: {api}

The stub should follow the pattern of existing crawlers in agents/scout/marketplace_crawler.py:
- A function crawl_{name}() that returns list[dict]
- Each dict has: platform, title, url, description, and any platform-specific fields
- If API: use requests with proper auth headers
- If scraping: use requests + regex (like agent_bounty.py)
- Include proper error handling and logging
- Use shared.config.get_logger for logging

Write ONLY the Python code. No explanation. Include a docstring."""

    try:
        code = ask(
            prompt,
            system="Write only Python code. No markdown fences. No explanation.",
            temperature=0.2,
        )
        # Clean up any markdown fences
        code = code.strip()
        if code.startswith("```"):
            code = "\n".join(code.split("\n")[1:])
        if code.endswith("```"):
            code = "\n".join(code.split("\n")[:-1])
        return code.strip()
    except Exception as e:
        log.error("Crawler stub generation failed: %s", e)
        return f'"""Auto-generated stub for {name} — generation failed: {e}"""\n'


def generate_handler_stub(platform: dict) -> str:
    """Generate a Worker handler stub for a new platform."""
    name = platform.get("name", "unknown").lower().replace(" ", "_").replace("-", "_")
    desc = platform.get("description", "")
    payment = platform.get("payment_method", "unknown")

    prompt = f"""Write a Python handler stub for Worker to handle tasks from this platform:

Name: {name}
Description: {desc}
Payment method: {payment}

The handler should follow the pattern of attempt_clawgig_task() in agents/worker/worker.py:
- A function attempt_{name}_task(opp: dict) -> dict
- Extract platform-specific metadata from opp
- Draft a response/proposal using Claude (shared.anthropic_client.ask)
- Submit via the platform's API or mark for manual submission
- Return {{"success": bool, "task_id": str, "result": ...}}
- Include proper error handling
- Use shared.config.get_logger for logging

Write ONLY the Python code. No markdown fences. No explanation."""

    try:
        code = ask(
            prompt,
            system="Write only Python code. No markdown fences. No explanation.",
            temperature=0.2,
        )
        code = code.strip()
        if code.startswith("```"):
            code = "\n".join(code.split("\n")[1:])
        if code.endswith("```"):
            code = "\n".join(code.split("\n")[:-1])
        return code.strip()
    except Exception as e:
        log.error("Handler stub generation failed: %s", e)
        return f'"""Auto-generated stub for {name} — generation failed: {e}"""\n'


def seek() -> dict:
    """Full SEEK mode run. Discovers platforms, generates stubs, surfaces for review.

    Returns stats dict.
    """
    stats = {"platforms_found": 0, "stubs_written": 0}

    platforms = discover_platforms()
    stats["platforms_found"] = len(platforms)

    if not platforms:
        log.info("Seeker: no new viable platforms found")
        return stats

    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    scout_discovered = os.path.join(base_dir, "agents", "scout", "discovered")
    worker_discovered = os.path.join(base_dir, "agents", "worker", "discovered")
    os.makedirs(scout_discovered, exist_ok=True)
    os.makedirs(worker_discovered, exist_ok=True)

    platform_names = []
    for platform in platforms:
        name = platform.get("name", "unknown").lower().replace(" ", "_").replace("-", "_")
        viability = platform.get("viability_score", 0)

        log.info("Seeker: generating stubs for %s (viability=%.2f)", name, viability)

        # Generate and write crawler stub
        crawler_code = generate_crawler_stub(platform)
        crawler_path = os.path.join(scout_discovered, f"{name}.py")
        with open(crawler_path, "w", encoding="utf-8") as f:
            f.write(crawler_code)

        # Generate and write handler stub
        handler_code = generate_handler_stub(platform)
        handler_path = os.path.join(worker_discovered, f"{name}.py")
        with open(handler_path, "w", encoding="utf-8") as f:
            f.write(handler_code)

        stats["stubs_written"] += 2
        platform_names.append(f"{name} ({viability:.1f})")

        # Log to Supabase
        try:
            sb = get_client()
            sb.table("proposals").insert({
                "proposed_by": "darwin.seeker",
                "target_agent": "scout",
                "change_type": "new_crawler",
                "change_description": f"New platform: {name} — {platform.get('description', '')}",
                "code_diff": crawler_code[:5000],
                "target_file": f"agents/scout/discovered/{name}.py",
                "fitness_score": viability,
                "applied": False,
            }).execute()
        except Exception as e:
            log.error("Failed to log seeker proposal: %s", e)

    # Notify human
    if platform_names:
        notify_action_needed(
            f"Darwin SEEK mode found {len(platform_names)} new platforms:\n"
            + "\n".join(f"  - {p}" for p in platform_names)
            + "\n\nStubs in agents/scout/discovered/ and agents/worker/discovered/"
            + "\nReview and activate manually."
        )

    log.info("Seeker: wrote %d stubs for %d platforms", stats["stubs_written"], stats["platforms_found"])
    return stats
