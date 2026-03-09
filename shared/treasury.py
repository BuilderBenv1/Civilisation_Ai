"""Treasury management — logs income, queries balance."""

from shared.supabase_client import log_income, get_treasury_summary
from shared.config import get_logger

log = get_logger("treasury")


def record_income(
    source_agent: str,
    source_platform: str,
    amount: float,
    currency: str = "USD",
    tx_hash: str | None = None,
    task_id: str | None = None,
    metadata: dict | None = None,
) -> dict:
    """Record incoming payment to treasury."""
    data = {
        "source_agent": source_agent,
        "source_platform": source_platform,
        "amount": amount,
        "currency": currency,
    }
    if tx_hash:
        data["tx_hash"] = tx_hash
    if task_id:
        data["task_id"] = task_id
    if metadata:
        data["metadata"] = metadata
    result = log_income(data)
    log.info(
        "Income recorded: %.4f %s from %s via %s",
        amount, currency, source_agent, source_platform,
    )
    return result


def get_weekly_summary() -> dict:
    """Get treasury stats for the last 7 days."""
    entries = get_treasury_summary(since_days=7)
    total_usd = sum(
        float(e.get("amount", 0))
        for e in entries
        if e.get("currency") == "USD"
    )
    by_agent = {}
    by_platform = {}
    for e in entries:
        agent = e.get("source_agent", "unknown")
        platform = e.get("source_platform", "unknown")
        amt = float(e.get("amount", 0))
        by_agent[agent] = by_agent.get(agent, 0) + amt
        by_platform[platform] = by_platform.get(platform, 0) + amt
    return {
        "total_entries": len(entries),
        "total_usd": round(total_usd, 2),
        "by_agent": by_agent,
        "by_platform": by_platform,
        "entries": entries,
    }
