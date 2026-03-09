"""Singleton Supabase client with retry logic."""

import time
import functools
from supabase import create_client, Client
from shared.config import SUPABASE_URL, SUPABASE_KEY, get_logger

log = get_logger("supabase")

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
        log.info("Supabase client initialized")
    return _client


def with_retry(max_retries: int = 3, base_delay: float = 1.0):
    """Decorator: exponential backoff on Supabase calls."""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            last_err = None
            for attempt in range(max_retries):
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    last_err = e
                    delay = base_delay * (2 ** attempt)
                    log.warning(
                        "Supabase call %s failed (attempt %d/%d): %s. Retrying in %.1fs",
                        fn.__name__, attempt + 1, max_retries, e, delay,
                    )
                    time.sleep(delay)
            log.error("Supabase call %s failed after %d retries", fn.__name__, max_retries)
            raise last_err
        return wrapper
    return decorator


# ── Opportunity helpers ──────────────────────────────────────────────

@with_retry()
def insert_opportunity(data: dict) -> dict:
    res = get_client().table("opportunities").insert(data).execute()
    return res.data[0] if res.data else {}


@with_retry()
def get_new_opportunities(limit: int = 20) -> list[dict]:
    res = (
        get_client()
        .table("opportunities")
        .select("*")
        .eq("status", "new")
        .order("estimated_value", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data or []


@with_retry()
def update_opportunity(opp_id: str, data: dict) -> dict:
    res = get_client().table("opportunities").update(data).eq("id", opp_id).execute()
    return res.data[0] if res.data else {}


# ── Prospect / CRM helpers ──────────────────────────────────────────

@with_retry()
def upsert_prospect(data: dict) -> dict:
    res = get_client().table("prospects").upsert(data, on_conflict="handle,platform").execute()
    return res.data[0] if res.data else {}


@with_retry()
def get_prospects(stage: str | None = None, limit: int = 50) -> list[dict]:
    q = get_client().table("prospects").select("*")
    if stage:
        q = q.eq("deal_stage", stage)
    res = q.order("discovered_at", desc=True).limit(limit).execute()
    return res.data or []


# ── Outreach helpers ─────────────────────────────────────────────────

@with_retry()
def insert_outreach(data: dict) -> dict:
    res = get_client().table("outreach_log").insert(data).execute()
    return res.data[0] if res.data else {}


@with_retry()
def get_pending_outreach() -> list[dict]:
    res = (
        get_client()
        .table("outreach_log")
        .select("*, prospects(*)")
        .eq("approved", False)
        .is_("sent_at", "null")
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []


@with_retry()
def approve_outreach(outreach_id: str) -> dict:
    res = (
        get_client()
        .table("outreach_log")
        .update({"approved": True})
        .eq("id", outreach_id)
        .execute()
    )
    return res.data[0] if res.data else {}


@with_retry()
def mark_outreach_sent(outreach_id: str) -> dict:
    import datetime
    res = (
        get_client()
        .table("outreach_log")
        .update({"sent_at": datetime.datetime.now(datetime.timezone.utc).isoformat()})
        .eq("id", outreach_id)
        .execute()
    )
    return res.data[0] if res.data else {}


# ── Treasury helpers ─────────────────────────────────────────────────

@with_retry()
def log_income(data: dict) -> dict:
    res = get_client().table("treasury").insert(data).execute()
    return res.data[0] if res.data else {}


@with_retry()
def get_treasury_summary(since_days: int = 7) -> list[dict]:
    import datetime
    cutoff = (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(days=since_days)
    ).isoformat()
    res = (
        get_client()
        .table("treasury")
        .select("*")
        .gte("received_at", cutoff)
        .order("received_at", desc=True)
        .execute()
    )
    return res.data or []


# ── ClawGig event helpers ────────────────────────────────────────────

@with_retry()
def get_unprocessed_clawgig_events() -> list[dict]:
    """Fetch webhook events that haven't been processed yet."""
    res = (
        get_client()
        .table("clawgig_events")
        .select("*")
        .eq("processed", False)
        .order("received_at")
        .execute()
    )
    return res.data or []


@with_retry()
def mark_clawgig_event_processed(event_id: str) -> dict:
    """Mark a webhook event as processed so it isn't handled again."""
    res = (
        get_client()
        .table("clawgig_events")
        .update({"processed": True})
        .eq("id", event_id)
        .execute()
    )
    return res.data[0] if res.data else {}


@with_retry()
def find_opportunity_by_gig_id(gig_id: str) -> dict | None:
    """Look up an opportunity row by its ClawGig gig_id stored in metadata."""
    res = (
        get_client()
        .table("opportunities")
        .select("*")
        .eq("platform", "clawgig")
        .execute()
    )
    for row in (res.data or []):
        meta = row.get("metadata") or {}
        if meta.get("gig_id") == gig_id:
            return row
    return None


# ── Agent messages ───────────────────────────────────────────────────

@with_retry()
def send_message(from_agent: str, to_agent: str, msg_type: str, payload: dict) -> dict:
    res = (
        get_client()
        .table("agent_messages")
        .insert({
            "from_agent": from_agent,
            "to_agent": to_agent,
            "message_type": msg_type,
            "payload": payload,
        })
        .execute()
    )
    return res.data[0] if res.data else {}


@with_retry()
def get_unread_messages(agent_name: str) -> list[dict]:
    res = (
        get_client()
        .table("agent_messages")
        .select("*")
        .eq("to_agent", agent_name)
        .eq("read", False)
        .order("created_at")
        .execute()
    )
    return res.data or []


@with_retry()
def mark_messages_read(message_ids: list[str]) -> None:
    if not message_ids:
        return
    for mid in message_ids:
        get_client().table("agent_messages").update({"read": True}).eq("id", mid).execute()


# ── Agent run tracking ───────────────────────────────────────────────

@with_retry()
def log_run_start(agent_name: str) -> str:
    res = (
        get_client()
        .table("agent_runs")
        .insert({"agent_name": agent_name})
        .execute()
    )
    return res.data[0]["id"] if res.data else ""


@with_retry()
def log_run_end(run_id: str, status: str = "completed", summary: dict | None = None, error: str | None = None):
    import datetime
    data = {
        "finished_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "status": status,
    }
    if summary:
        data["summary"] = summary
    if error:
        data["error"] = error
    get_client().table("agent_runs").update(data).eq("id", run_id).execute()
