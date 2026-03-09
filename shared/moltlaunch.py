"""Moltlaunch API client — onchain agent marketplace on Base.

API docs: https://moltlaunch.com/docs/api-reference/
Base URL: https://api.moltlaunch.com
Auth: EIP-191 signatures (requires an Ethereum private key)
Payment: ETH via trustless escrow on Base

Flow: register (mints ERC-8004) -> get discovered -> receive task -> quote -> deliver -> get paid
"""

import os
import time
import secrets
import requests
from shared.config import get_logger

log = get_logger("moltlaunch")

BASE_URL = "https://api.moltlaunch.com"

# Worker's signing key for Moltlaunch — needed for EIP-191 auth
_PRIVATE_KEY = os.getenv("MOLTLAUNCH_PRIVATE_KEY", "")


_ADDRESS = os.getenv("MOLTLAUNCH_ADDRESS", "")


def _sign_message(action: str, task_id: str = "") -> dict:
    """Create EIP-191 signature fields for authenticated requests."""
    if not _PRIVATE_KEY:
        raise RuntimeError("MOLTLAUNCH_PRIVATE_KEY not set")

    try:
        from eth_account import Account
        from eth_account.messages import encode_defunct
    except ImportError:
        raise RuntimeError("eth_account package required: pip install eth-account")

    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(16)
    message = f"moltlaunch:{action}:{task_id}:{timestamp}:{nonce}"

    msg = encode_defunct(text=message)
    signed = Account.sign_message(msg, private_key=_PRIVATE_KEY)

    sig_hex = signed.signature.hex() if isinstance(signed.signature, bytes) else str(signed.signature)
    if not sig_hex.startswith("0x"):
        sig_hex = "0x" + sig_hex

    return {
        "signature": sig_hex,
        "timestamp": timestamp,
        "nonce": nonce,
        "expectedAddress": _ADDRESS,
    }


def _get(path: str, params: dict | None = None) -> dict:
    resp = requests.get(f"{BASE_URL}{path}", params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _post(path: str, data: dict) -> dict:
    resp = requests.post(f"{BASE_URL}{path}", json=data, timeout=30)
    resp.raise_for_status()
    return resp.json()


# ── Discovery (no auth needed) ──────────────────────────────────────

def browse_agents(skill: str | None = None, limit: int = 50) -> list[dict]:
    """List available agents on Moltlaunch."""
    params = {"limit": limit}
    if skill:
        params["skill"] = skill
    result = _get("/api/agents", params=params)
    agents = result.get("data", result) if isinstance(result, dict) else result
    return agents if isinstance(agents, list) else []


def browse_tasks(limit: int = 50) -> list[dict]:
    """Browse available/open tasks. Used by Scout to find work."""
    # Moltlaunch tasks are agent-directed (clients pick an agent),
    # but we can check for bounties or public tasks
    try:
        result = _get("/api/tasks", params={"limit": limit, "status": "open"})
        tasks = result.get("data", []) if isinstance(result, dict) else result
        return tasks if isinstance(tasks, list) else []
    except Exception as e:
        log.debug("Moltlaunch task browse failed (may not support public listing): %s", e)
        return []


# ── Agent Registration (requires signing) ────────────────────────────

def register_agent(
    name: str = "AgentTown Worker",
    description: str = (
        "Autonomous worker agent from AgentProof Agent Town. "
        "Web scraping, data extraction, API integrations, automation. "
        "Verified by AgentProof (agentproof.sh). ERC-8004 native."
    ),
    skills: list[str] | None = None,
    endpoint_url: str = "",
) -> dict:
    """Register Worker on Moltlaunch. Mints an ERC-8004 identity token onchain."""
    auth = _sign_message("register")
    data = {
        "agentId": _ADDRESS,
        "address": _ADDRESS,
        "name": name,
        "description": description,
        "skills": skills or [
            "web-scraping", "data-extraction", "api-integration",
            "automation", "python", "code",
        ],
        "endpoint": endpoint_url,
        **auth,
    }
    result = _post("/api/agents/register", data)
    log.info("Registered on Moltlaunch: %s", result.get("data", {}).get("id", "unknown"))
    return result


# ── Task Handling (requires signing) ─────────────────────────────────

def submit_quote(task_id: str, price_eth: float, eta_hours: int, message: str) -> dict:
    """Submit a price quote for a task."""
    auth = _sign_message("quote", task_id)
    data = {
        "price": str(price_eth),
        "eta": eta_hours,
        "message": message,
        **auth,
    }
    result = _post(f"/api/tasks/{task_id}/quote", data)
    log.info("Quoted %.4f ETH for task %s", price_eth, task_id)
    return result


def deliver_work(task_id: str, message: str, files: list[str] | None = None) -> dict:
    """Submit completed work for a task. Triggers 24-hour auto-release window."""
    auth = _sign_message("submit", task_id)
    data = {
        "message": message,
        "files": files or [],
        **auth,
    }
    result = _post(f"/api/tasks/{task_id}/submit", data)
    log.info("Delivered work for Moltlaunch task %s", task_id)
    return result


def send_message(task_id: str, message: str) -> dict:
    """Send a message on a task thread."""
    auth = _sign_message("message", task_id)
    data = {"message": message, **auth}
    return _post(f"/api/tasks/{task_id}/message", data)


def get_task(task_id: str) -> dict:
    """Get full task details."""
    return _get(f"/api/tasks/{task_id}")


def get_agent_stats(agent_id: str) -> dict:
    """Get agent statistics."""
    return _get(f"/api/agents/{agent_id}/stats")
