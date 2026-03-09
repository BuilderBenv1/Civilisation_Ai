"""CRM operations — prospect management for BD agent."""

from shared.supabase_client import upsert_prospect, get_prospects, insert_outreach
from shared.config import get_logger

log = get_logger("bd.crm")


def add_prospect(
    handle: str,
    platform: str = "twitter",
    context: str = "",
    notes: str = "",
) -> dict:
    """Add or update a prospect in the CRM."""
    data = {
        "handle": handle,
        "platform": platform,
        "context": context,
        "notes": notes,
        "deal_stage": "new",
    }
    result = upsert_prospect(data)
    log.info("Prospect upserted: @%s on %s", handle, platform)
    return result


def get_active_prospects(limit: int = 50) -> list[dict]:
    """Get all non-dead prospects."""
    all_prospects = get_prospects(limit=limit)
    return [p for p in all_prospects if p.get("deal_stage") != "dead"]


def queue_outreach(
    prospect_id: str,
    channel: str,
    message_draft: str,
    auto_approve: bool = True,
) -> dict:
    """Queue outreach. Auto-approved by default — zero-human company."""
    data = {
        "prospect_id": prospect_id,
        "channel": channel,
        "message_draft": message_draft,
        "approved": auto_approve,
    }
    result = insert_outreach(data)
    status = "auto-approved" if auto_approve else "pending"
    log.info("Outreach %s for prospect %s via %s", status, prospect_id, channel)
    return result
