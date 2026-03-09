"""Telegram notifications — pushes updates to the Agent Town group."""

import requests
from shared.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, get_logger

log = get_logger("telegram")

_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}" if TELEGRAM_BOT_TOKEN else ""


def send(text: str, parse_mode: str = "HTML") -> bool:
    """Send a message to the Agent Town Telegram group. Returns success flag."""
    if not _API or not TELEGRAM_CHAT_ID:
        log.debug("Telegram not configured, skipping notification")
        return False
    try:
        resp = requests.post(
            f"{_API}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": parse_mode},
            timeout=10,
        )
        if not resp.ok:
            log.warning("Telegram send failed: %s", resp.text[:200])
            return False
        return True
    except Exception as e:
        log.warning("Telegram send error: %s", e)
        return False


# ── Pre-built notification helpers ────────────────────────────────────

def notify_job_completed(platform: str, title: str, value: float = 0, currency: str = "USD"):
    """Worker completed a task."""
    money = f" — <b>${value:.0f} {currency}</b>" if value > 0 else ""
    send(f"<b>Job Completed</b>\n{platform.upper()}: {_esc(title[:200])}{money}")


def notify_proposal_sent(platform: str, title: str, amount: float, currency: str):
    """Worker submitted a proposal/quote."""
    send(f"<b>Proposal Sent</b>\n{platform.upper()}: {_esc(title[:200])}\nBid: {amount:.2f} {currency}")


def notify_payment(platform: str, amount: float, currency: str, tx_hash: str = ""):
    """Payment received in treasury."""
    tx = f"\ntx: <code>{tx_hash}</code>" if tx_hash else ""
    send(f"<b>Payment Received</b>\n{platform.upper()}: {amount:.2f} {currency}{tx}")


def notify_action_needed(description: str):
    """Something needs human attention (BD approval, error, etc.)."""
    send(f"<b>Action Needed</b>\n{_esc(description[:500])}")


def notify_scout_cycle(tweets: int, filtered: int, marketplace: int, posted: int):
    """Scout completed a scan cycle."""
    send(
        f"<b>Scout Cycle</b>\n"
        f"Tweets: {tweets} scanned, {filtered} passed filter\n"
        f"Marketplace: {marketplace} tasks found\n"
        f"Opportunities posted: {posted}"
    )


def notify_error(agent: str, error: str):
    """An agent hit a significant error."""
    send(f"<b>Error [{agent.upper()}]</b>\n<code>{_esc(error[:400])}</code>")


def _esc(text: str) -> str:
    """Escape HTML entities for Telegram."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
