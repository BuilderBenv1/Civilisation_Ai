"""ClawGig API client — agent marketplace for USDC gigs.

API docs: https://clawgig.ai/skill.md
Base URL: https://clawgig.ai/api/v1
Auth: Bearer token (cg_... key from registration)

Flow: register -> claim -> verify email -> add portfolio -> browse gigs -> propose -> deliver -> get paid
"""

import os
import requests
from shared.config import get_logger

log = get_logger("clawgig")

BASE_URL = "https://clawgig.ai/api/v1"
API_KEY = os.getenv("CLAWGIG_API_KEY", "")


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }


def _get(path: str, params: dict | None = None) -> dict:
    resp = requests.get(f"{BASE_URL}{path}", headers=_headers(), params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _post(path: str, data: dict) -> dict:
    resp = requests.post(f"{BASE_URL}{path}", headers=_headers(), json=data, timeout=30)
    resp.raise_for_status()
    return resp.json()


# ── Registration ─────────────────────────────────────────────────────

def register_agent(
    name: str = "AgentTown Worker",
    username: str = "agenttown_worker",
    description: str = (
        "Autonomous worker agent from AgentProof's Agent Town. "
        "Skills: web scraping, data extraction, API integrations, "
        "automation pipelines, structured data enrichment. "
        "Powered by Claude. Verified by AgentProof (agentproof.sh)."
    ),
    skills: list[str] | None = None,
    categories: list[str] | None = None,
    contact_email: str = "help@punthub.co.uk",
    webhook_url: str | None = None,
) -> dict:
    """Register Worker as a ClawGig agent. Returns API key (shown once)."""
    data = {
        "name": name,
        "username": username,
        "description": description,
        "skills": skills or [
            "web-scraping", "data-extraction", "api-integration",
            "automation", "python", "data-enrichment",
        ],
        "categories": categories or ["development", "data", "research"],
        "contact_email": contact_email,
    }
    if webhook_url:
        data["webhook_url"] = webhook_url

    result = _post("/agents/register", data)
    log.info("Registered on ClawGig as '%s' — SAVE THE API KEY", username)
    return result


def check_readiness() -> dict:
    """Check if agent profile is complete enough to submit proposals."""
    return _get("/agents/me/readiness")


def add_portfolio_item(
    title: str,
    description: str,
    url: str,
    skills: list[str] | None = None,
) -> dict:
    """Add a portfolio item (required before bidding)."""
    data = {
        "title": title,
        "description": description,
        "url": url,
    }
    if skills:
        data["skills"] = skills
    return _post("/agents/me/portfolio", data)


# ── Gig Discovery ───────────────────────────────────────────────────

def browse_gigs(
    category: str | None = None,
    skills: list[str] | None = None,
    min_budget: float | None = None,
    max_budget: float | None = None,
    sort: str = "newest",
) -> list[dict]:
    """Browse available gigs. Returns list of gig dicts."""
    params = {"sort": sort}
    if category:
        params["category"] = category
    if skills:
        params["skills"] = ",".join(skills)
    if min_budget is not None:
        params["min_budget"] = str(min_budget)
    if max_budget is not None:
        params["max_budget"] = str(max_budget)

    result = _get("/gigs", params=params)
    gigs = result.get("gigs", result.get("data", []))
    if isinstance(result, list):
        gigs = result
    log.info("ClawGig: found %d gigs", len(gigs) if isinstance(gigs, list) else 0)
    return gigs if isinstance(gigs, list) else []


# ── Proposals ────────────────────────────────────────────────────────

def submit_proposal(
    gig_id: str,
    proposed_amount: float,
    cover_letter: str,
    estimated_hours: float | None = None,
) -> dict:
    """Submit a proposal for a gig."""
    data = {
        "proposed_amount_usdc": proposed_amount,
        "cover_letter": cover_letter,
    }
    if estimated_hours:
        data["estimated_hours"] = estimated_hours
    result = _post(f"/gigs/{gig_id}/proposals", data)
    log.info("Submitted proposal for gig %s at $%.2f USDC", gig_id, proposed_amount)
    return result


# ── Delivery ─────────────────────────────────────────────────────────

def deliver_work(
    contract_id: str,
    notes: str,
    deliverables_url: str,
) -> dict:
    """Deliver completed work for a contract."""
    data = {
        "notes": notes,
        "deliverables_url": deliverables_url,
    }
    result = _post(f"/contracts/{contract_id}/deliver", data)
    log.info("Delivered work for contract %s", contract_id)
    return result


def send_message(contract_id: str, message: str) -> dict:
    """Send a message to the client on a contract."""
    return _post(f"/contracts/{contract_id}/messages", {"message": message})


# ── Contracts ────────────────────────────────────────────────────────

def get_my_contracts(status: str | None = None) -> list[dict]:
    """List the agent's contracts. Optionally filter by status (active, completed, etc.)."""
    params = {}
    if status:
        params["status"] = status
    result = _get("/agents/me/contracts", params=params)
    contracts = result.get("contracts", result.get("data", []))
    if isinstance(result, list):
        contracts = result
    log.info("ClawGig: fetched %d contracts", len(contracts) if isinstance(contracts, list) else 0)
    return contracts if isinstance(contracts, list) else []


# ── Profile ──────────────────────────────────────────────────────────

def get_profile() -> dict:
    """Get the agent's own profile."""
    return _get("/agents/me")
