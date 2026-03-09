"""Register Agent Town agents on AgentProof.

Dogfooding script -- registers Scout, Worker, and BD on the AgentProof
trust-score platform so the project uses the same infra it promotes.

Usage:
    python register_agentproof.py            # register all three agents
    python register_agentproof.py --verify   # check existing registrations
"""

import argparse
import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent

# Load .env the same way shared/config.py does
try:
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")
except ImportError:
    pass  # fall back to whatever is already in the environment

AGENTPROOF_API_KEY: str = os.getenv("AGENTPROOF_API_KEY", "")
AGENT_IDS_FILE: Path = _ROOT / "agent_ids.json"

# ---------------------------------------------------------------------------
# Agent definitions
# ---------------------------------------------------------------------------

AGENTS = [
    {
        "name": "AgentTown Scout",
        "description": (
            "Autonomous opportunity scanner. Monitors X/Twitter and agent "
            "marketplaces (ClawGig, Upwork) for tasks that Worker can "
            "complete. Posts evaluated opportunities to shared task board."
        ),
        "capabilities": [
            "x-monitoring",
            "marketplace-crawling",
            "task-evaluation",
            "opportunity-scoring",
        ],
    },
    {
        "name": "AgentTown Worker",
        "description": (
            "Autonomous task executor. Picks highest-ROI tasks from Scout's "
            "board, completes them using web scraping, data extraction, API "
            "integration, and automation skills. Revenue flows to shared "
            "treasury."
        ),
        "capabilities": [
            "web-scraping",
            "data-extraction",
            "api-integration",
            "automation",
            "task-execution",
        ],
    },
    {
        "name": "AgentTown BD",
        "description": (
            "Autonomous business development agent for AgentProof. Scans X "
            "for projects needing trust scores, evaluates prospects, drafts "
            "outreach for human approval."
        ),
        "capabilities": [
            "prospect-discovery",
            "outreach-drafting",
            "crm-management",
            "x-monitoring",
        ],
    },
]

# ---------------------------------------------------------------------------
# SDK path -- try the agentproof pip package first
# ---------------------------------------------------------------------------


def _try_sdk_register(agent: dict) -> dict:
    """Attempt registration via the agentproof SDK.  Returns a result dict."""
    import agentproof  # will raise ImportError if missing

    # The SDK might expose register() at the top level or on a client object.
    # Try the most common patterns.
    if hasattr(agentproof, "register"):
        result = agentproof.register(
            name=agent["name"],
            description=agent["description"],
            capabilities=agent["capabilities"],
            api_key=AGENTPROOF_API_KEY,
        )
        return result if isinstance(result, dict) else {"id": str(result)}

    if hasattr(agentproof, "Client"):
        client = agentproof.Client(api_key=AGENTPROOF_API_KEY)
        if hasattr(client, "register_agent"):
            result = client.register_agent(
                name=agent["name"],
                description=agent["description"],
                capabilities=agent["capabilities"],
            )
            return result if isinstance(result, dict) else {"id": str(result)}
        if hasattr(client, "register"):
            result = client.register(
                name=agent["name"],
                description=agent["description"],
                capabilities=agent["capabilities"],
            )
            return result if isinstance(result, dict) else {"id": str(result)}

    if hasattr(agentproof, "AgentProof"):
        client = agentproof.AgentProof(api_key=AGENTPROOF_API_KEY)
        if hasattr(client, "register_agent"):
            result = client.register_agent(
                name=agent["name"],
                description=agent["description"],
                capabilities=agent["capabilities"],
            )
            return result if isinstance(result, dict) else {"id": str(result)}

    raise AttributeError("agentproof SDK installed but no known register API found")


# ---------------------------------------------------------------------------
# REST fallback
# ---------------------------------------------------------------------------

_BASE_URLS = [
    "https://api.agentproof.sh",
    "https://api.agentproof.com",
    "https://agentproof.sh/api",
]

_REGISTER_PATHS = [
    "/v1/agents",
    "/agents",
    "/v1/register",
    "/register",
]


def _rest_register(agent: dict) -> dict:
    """Register an agent via the AgentProof REST API."""
    import requests

    headers = {
        "Authorization": f"Bearer {AGENTPROOF_API_KEY}",
        "Content-Type": "application/json",
        "X-API-Key": AGENTPROOF_API_KEY,
    }

    payload = {
        "name": agent["name"],
        "description": agent["description"],
        "capabilities": agent["capabilities"],
    }

    last_error: Exception | None = None

    for base in _BASE_URLS:
        for path in _REGISTER_PATHS:
            url = f"{base}{path}"
            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=30)
                if resp.status_code in (200, 201):
                    data = resp.json()
                    return data
                if resp.status_code == 409:
                    # Agent already exists -- treat as success
                    try:
                        data = resp.json()
                    except ValueError:
                        data = {}
                    data.setdefault("status", "already_registered")
                    return data
                # 404 / 405 likely means wrong path -- try next
                if resp.status_code in (404, 405):
                    continue
                # Any other error -- record it but keep trying
                last_error = RuntimeError(
                    f"{url} returned {resp.status_code}: {resp.text[:300]}"
                )
            except requests.ConnectionError:
                continue
            except requests.RequestException as exc:
                last_error = exc

    if last_error:
        raise last_error
    raise RuntimeError("Could not reach any AgentProof API endpoint")


# ---------------------------------------------------------------------------
# Verify existing registrations
# ---------------------------------------------------------------------------


def _rest_verify(agent_id: str) -> dict | None:
    """Check whether an agent_id is still registered."""
    import requests

    headers = {
        "Authorization": f"Bearer {AGENTPROOF_API_KEY}",
        "X-API-Key": AGENTPROOF_API_KEY,
    }

    for base in _BASE_URLS:
        for path_prefix in ("/v1/agents/", "/agents/"):
            url = f"{base}{path_prefix}{agent_id}"
            try:
                resp = requests.get(url, headers=headers, timeout=15)
                if resp.status_code == 200:
                    return resp.json()
            except requests.RequestException:
                continue
    return None


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


def _load_agent_ids() -> dict:
    if AGENT_IDS_FILE.exists():
        with open(AGENT_IDS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_agent_ids(data: dict) -> None:
    with open(AGENT_IDS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"  -> Saved agent IDs to {AGENT_IDS_FILE}")


# ---------------------------------------------------------------------------
# Main actions
# ---------------------------------------------------------------------------


def register_all() -> None:
    """Register every agent and persist their IDs."""
    if not AGENTPROOF_API_KEY:
        print("ERROR: AGENTPROOF_API_KEY is not set. Check your .env file.")
        sys.exit(1)

    existing = _load_agent_ids()
    results: dict = {}
    timestamp = datetime.now(timezone.utc).isoformat()

    for agent in AGENTS:
        slug = agent["name"].lower().replace(" ", "_")
        print(f"\n{'='*60}")
        print(f"Registering: {agent['name']}")
        print(f"  Capabilities: {', '.join(agent['capabilities'])}")
        print(f"{'='*60}")

        # Skip if already registered and user didn't force
        if slug in existing and existing[slug].get("id"):
            print(f"  Already registered (id={existing[slug]['id']}). Skipping.")
            print("  Run with --verify to check status, or delete agent_ids.json to re-register.")
            results[slug] = existing[slug]
            continue

        # --- Try SDK first, then REST fallback ---
        result: dict | None = None
        method_used = "unknown"

        try:
            result = _try_sdk_register(agent)
            method_used = "sdk"
            print("  Method: agentproof SDK")
        except ImportError:
            print("  agentproof package not installed -- falling back to REST API")
        except AttributeError as exc:
            print(f"  SDK issue ({exc}) -- falling back to REST API")
        except Exception as exc:
            print(f"  SDK error ({exc}) -- falling back to REST API")

        if result is None:
            try:
                result = _rest_register(agent)
                method_used = "rest"
                print("  Method: REST API")
            except Exception as exc:
                print(f"  ERROR: Registration failed -- {exc}")
                result = {"error": str(exc)}
                method_used = "failed"

        # Extract agent ID from various possible response shapes
        agent_id = (
            result.get("id")
            or result.get("agent_id")
            or result.get("data", {}).get("id")
            if isinstance(result, dict)
            else None
        )

        results[slug] = {
            "id": agent_id,
            "name": agent["name"],
            "method": method_used,
            "registered_at": timestamp,
            "response": result,
        }

        if agent_id:
            print(f"  SUCCESS: agent_id = {agent_id}")
        elif method_used == "failed":
            print(f"  FAILED: see error above")
        else:
            print(f"  Registered (no explicit ID in response)")
            print(f"  Full response: {json.dumps(result, indent=2, default=str)}")

    _save_agent_ids(results)
    _print_summary(results)


def verify() -> None:
    """Verify that previously registered agents are still active."""
    if not AGENTPROOF_API_KEY:
        print("ERROR: AGENTPROOF_API_KEY is not set. Check your .env file.")
        sys.exit(1)

    data = _load_agent_ids()
    if not data:
        print("No agent_ids.json found. Run without --verify first to register agents.")
        sys.exit(1)

    print(f"\nVerifying {len(data)} registered agent(s)...\n")

    for slug, info in data.items():
        agent_id = info.get("id")
        name = info.get("name", slug)
        print(f"  {name} (id={agent_id})")

        if not agent_id:
            print("    -> No ID stored; cannot verify. Re-register to fix.")
            continue

        # Try SDK verify first
        verified = False
        try:
            import agentproof

            if hasattr(agentproof, "Client"):
                client = agentproof.Client(api_key=AGENTPROOF_API_KEY)
                if hasattr(client, "get_agent"):
                    result = client.get_agent(agent_id)
                    if result:
                        print(f"    -> VERIFIED via SDK")
                        verified = True
            if not verified and hasattr(agentproof, "AgentProof"):
                client = agentproof.AgentProof(api_key=AGENTPROOF_API_KEY)
                if hasattr(client, "get_agent"):
                    result = client.get_agent(agent_id)
                    if result:
                        print(f"    -> VERIFIED via SDK")
                        verified = True
        except ImportError:
            pass
        except Exception:
            pass

        if not verified:
            # REST fallback
            result = _rest_verify(agent_id)
            if result:
                print(f"    -> VERIFIED via REST API")
            else:
                print(f"    -> NOT FOUND -- agent may need re-registration")


def _print_summary(results: dict) -> None:
    """Print a final summary table."""
    print(f"\n{'='*60}")
    print("REGISTRATION SUMMARY")
    print(f"{'='*60}")
    for slug, info in results.items():
        status = "OK" if info.get("id") or info.get("method") != "failed" else "FAILED"
        agent_id = info.get("id", "n/a")
        print(f"  [{status:6s}] {info.get('name', slug):20s}  id={agent_id}")
    print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Register Agent Town agents on AgentProof",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify existing registrations instead of registering new ones",
    )
    args = parser.parse_args()

    if args.verify:
        verify()
    else:
        register_all()


if __name__ == "__main__":
    main()
