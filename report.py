"""Weekly report — emails a summary of all agent activity.

Sent Monday 8am UK via Resend.
"""

import sys
import os
import datetime
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from shared.config import RESEND_API_KEY, RESEND_FROM, REPORT_EMAIL, get_logger
from shared.supabase_client import get_client
from shared.treasury import get_weekly_summary

log = get_logger("report")

RESEND_URL = "https://api.resend.com/emails"


def _get_agent_run_stats(agent_name: str, since_days: int = 7) -> dict:
    """Get run stats for an agent over the past N days."""
    cutoff = (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(days=since_days)
    ).isoformat()

    runs = (
        get_client()
        .table("agent_runs")
        .select("*")
        .eq("agent_name", agent_name)
        .gte("started_at", cutoff)
        .execute()
    ).data or []

    completed = sum(1 for r in runs if r.get("status") == "completed")
    failed = sum(1 for r in runs if r.get("status") == "failed")

    return {
        "total_runs": len(runs),
        "completed": completed,
        "failed": failed,
        "summaries": [r.get("summary", {}) for r in runs if r.get("summary")],
    }


def _get_scout_stats() -> dict:
    stats = _get_agent_run_stats("scout")
    total_opportunities = sum(
        s.get("opportunities_posted", 0) for s in stats["summaries"]
    )
    total_tweets = sum(s.get("x_tweets", 0) for s in stats["summaries"])
    return {
        **stats,
        "opportunities_found": total_opportunities,
        "tweets_scanned": total_tweets,
    }


def _get_worker_stats() -> dict:
    stats = _get_agent_run_stats("worker")
    total_completed = sum(s.get("tasks_completed", 0) for s in stats["summaries"])
    total_failed = sum(s.get("tasks_failed", 0) for s in stats["summaries"])
    total_revenue = sum(s.get("revenue", 0) for s in stats["summaries"])
    return {
        **stats,
        "tasks_completed": total_completed,
        "tasks_failed": total_failed,
        "revenue_generated": round(total_revenue, 2),
    }


def _get_bd_stats() -> dict:
    stats = _get_agent_run_stats("bd")
    total_prospects = sum(s.get("prospects_found", 0) for s in stats["summaries"])
    total_drafts = sum(s.get("drafts_queued", 0) for s in stats["summaries"])

    # Check conversion stats from CRM
    cutoff = (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(days=7)
    ).isoformat()
    outreach = (
        get_client()
        .table("outreach_log")
        .select("*")
        .gte("created_at", cutoff)
        .execute()
    ).data or []
    sent = sum(1 for o in outreach if o.get("sent_at"))
    approved = sum(1 for o in outreach if o.get("approved"))

    return {
        **stats,
        "prospects_found": total_prospects,
        "drafts_queued": total_drafts,
        "outreach_sent": sent,
        "outreach_approved": approved,
    }


def build_report_html() -> str:
    """Build the weekly report as HTML."""
    scout = _get_scout_stats()
    worker = _get_worker_stats()
    bd = _get_bd_stats()
    treasury = get_weekly_summary()

    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return f"""
<html>
<body style="font-family: monospace; max-width: 700px; margin: 0 auto; padding: 20px;">
<h1 style="border-bottom: 2px solid #333;">Agent Town Weekly Report</h1>
<p style="color: #666;">Generated: {now}</p>

<h2>Scout</h2>
<table style="border-collapse: collapse; width: 100%;">
<tr><td style="padding: 4px 12px;">Runs</td><td>{scout['total_runs']} ({scout['completed']} ok, {scout['failed']} failed)</td></tr>
<tr><td style="padding: 4px 12px;">Tweets scanned</td><td>{scout['tweets_scanned']}</td></tr>
<tr><td style="padding: 4px 12px;">Opportunities found</td><td>{scout['opportunities_found']}</td></tr>
</table>

<h2>Worker</h2>
<table style="border-collapse: collapse; width: 100%;">
<tr><td style="padding: 4px 12px;">Runs</td><td>{worker['total_runs']} ({worker['completed']} ok, {worker['failed']} failed)</td></tr>
<tr><td style="padding: 4px 12px;">Tasks completed</td><td>{worker['tasks_completed']}</td></tr>
<tr><td style="padding: 4px 12px;">Tasks failed</td><td>{worker['tasks_failed']}</td></tr>
<tr><td style="padding: 4px 12px;">Revenue generated</td><td>${worker['revenue_generated']:.2f}</td></tr>
</table>

<h2>BD</h2>
<table style="border-collapse: collapse; width: 100%;">
<tr><td style="padding: 4px 12px;">Runs</td><td>{bd['total_runs']} ({bd['completed']} ok, {bd['failed']} failed)</td></tr>
<tr><td style="padding: 4px 12px;">Prospects found</td><td>{bd['prospects_found']}</td></tr>
<tr><td style="padding: 4px 12px;">Outreach drafted</td><td>{bd['drafts_queued']}</td></tr>
<tr><td style="padding: 4px 12px;">Outreach approved</td><td>{bd['outreach_approved']}</td></tr>
<tr><td style="padding: 4px 12px;">Outreach sent</td><td>{bd['outreach_sent']}</td></tr>
</table>

<h2>Treasury</h2>
<table style="border-collapse: collapse; width: 100%;">
<tr><td style="padding: 4px 12px;">Total income (7d)</td><td>${treasury['total_usd']:.2f}</td></tr>
<tr><td style="padding: 4px 12px;">Transactions</td><td>{treasury['total_entries']}</td></tr>
<tr><td style="padding: 4px 12px;">By agent</td><td>{', '.join(f"{k}: ${v:.2f}" for k, v in treasury['by_agent'].items()) or 'None'}</td></tr>
<tr><td style="padding: 4px 12px;">By platform</td><td>{', '.join(f"{k}: ${v:.2f}" for k, v in treasury['by_platform'].items()) or 'None'}</td></tr>
</table>

<hr style="margin-top: 30px;">
<p style="color: #999; font-size: 12px;">Agent Town - agentproof.sh</p>
</body>
</html>"""


def send_weekly_report():
    """Build and send the weekly report via Resend."""
    if not RESEND_API_KEY:
        log.warning("RESEND_API_KEY not set, skipping weekly report")
        return
    if not REPORT_EMAIL:
        log.warning("REPORT_EMAIL not set, skipping weekly report")
        return

    html = build_report_html()
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    try:
        resp = requests.post(
            RESEND_URL,
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "from": RESEND_FROM,
                "to": [REPORT_EMAIL],
                "subject": f"Agent Town Weekly Report - {now}",
                "html": html,
            },
            timeout=30,
        )
        resp.raise_for_status()
        log.info("Weekly report sent to %s", REPORT_EMAIL)
    except Exception as e:
        log.error("Failed to send weekly report: %s", e)
        raise


if __name__ == "__main__":
    # For testing: build and print the report
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--send", action="store_true", help="Actually send the email")
    parser.add_argument("--preview", action="store_true", help="Print HTML to stdout")
    args = parser.parse_args()

    if args.send:
        send_weekly_report()
    elif args.preview:
        print(build_report_html())
    else:
        print("Usage: python report.py --preview | --send")
