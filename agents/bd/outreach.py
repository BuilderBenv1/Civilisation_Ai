"""BD Outreach — evaluates prospects and drafts messages for Agent Town.

Agent Town offers autonomous agent services: web scraping, data extraction,
API integrations, automation, and code. BD finds projects that need this
and drafts outreach (always human-approved before sending).
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from shared.config import get_logger, PRIME_DIRECTIVE
from shared.anthropic_client import ask_json, ask

log = get_logger("bd.outreach")


def evaluate_prospect(tweet_text: str, author: str) -> dict:
    """Evaluate whether a tweet author is a potential client for Agent Town.

    Returns: {"is_prospect": bool, "confidence": float, "reason": str,
              "priority": str, "service_angle": str}
    """
    prompt = f"""{PRIME_DIRECTIVE}

You are BD, the business development agent of Agent Town.
Agent Town is an autonomous civilisation of AI agents that can be hired to do work:
- Web scraping and data extraction
- API integrations and automation
- Python code and scripts
- Onchain tasks (Base, ETH)
- Data enrichment and processing
- Content generation

Evaluate this tweet to determine if the author might need Agent Town's services.

Tweet by @{author}:
\"{tweet_text}\"

Consider:
- Are they looking for agent/automation services?
- Are they building something that needs autonomous workers?
- Are they a DAO, project, or company that could hire Agent Town?
- Is there a specific pain point Agent Town can solve?

Return JSON:
{{
    "is_prospect": true/false,
    "confidence": 0.0-1.0,
    "reason": "why they are/aren't a prospect",
    "priority": "high" | "medium" | "low",
    "service_angle": "what specific Agent Town service would help them"
}}

Be selective. Only flag genuine prospects — not people just talking about AI.
A real prospect is someone who NEEDS work done that our agents can do."""

    try:
        return ask_json(prompt, temperature=0.1)
    except Exception as e:
        log.error("Prospect evaluation failed for @%s: %s", author, e)
        return {"is_prospect": False, "confidence": 0, "reason": f"Evaluation failed: {e}"}


def draft_outreach(handle: str, context: str, channel: str = "twitter_dm") -> str:
    """Draft an outreach message for a prospect.

    The message positions Agent Town as a hireable autonomous workforce.
    Always queued for human approval — never auto-sent.
    """
    prompt = f"""{PRIME_DIRECTIVE}

You are BD, drafting outreach for Agent Town.

Agent Town is an autonomous civilisation of AI agents. We are:
- ERC-8004 registered on Moltlaunch (Agent ID: 27943)
- Available for hire: web scraping, data extraction, API integrations, automation, Python code
- Trustless escrow payments via ETH on Base
- Self-improving — our agents evolve their own code to get better at tasks

Target: @{handle}
Context: {context}
Channel: {channel}

Draft a SHORT, genuine outreach message (2-4 sentences max).

Rules:
- Lead with what we can DO for them, not what we are
- Be specific about which service fits their need
- No buzzwords, no hype, no emojis
- Sound like a competent professional, not a sales bot
- Include that we're on Moltlaunch if relevant (they can hire us trustlessly)
- If the channel is twitter_dm, keep it under 280 characters

Return ONLY the message text. No quotes, no explanation."""

    try:
        return ask(
            prompt,
            system="Write only the outreach message. No explanation. No quotes.",
            temperature=0.3,
        )
    except Exception as e:
        log.error("Outreach draft failed for @%s: %s", handle, e)
        return f"[Draft generation failed for @{handle}: {e}]"
