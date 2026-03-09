"""Agent Town Dashboard — quick CLI to see what's happening.

Usage:
    python dashboard.py              # Full summary
    python dashboard.py opps         # Recent opportunities
    python dashboard.py treasury     # Treasury balance
    python dashboard.py runs         # Recent agent runs
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from shared.supabase_client import get_client


def show_summary():
    sb = get_client()

    # Opportunities by platform + status
    opps = sb.table("opportunities").select("platform, status, estimated_value").execute().data
    from collections import Counter
    by_plat = Counter()
    by_status = Counter()
    for o in opps:
        by_plat[o["platform"]] += 1
        by_status[o["status"]] += 1

    print("=" * 50)
    print("  AGENT TOWN DASHBOARD")
    print("=" * 50)
    print(f"\nTotal opportunities: {len(opps)}")
    print("\nBy platform:")
    for k, v in by_plat.most_common():
        print(f"  {k:15s} {v:>4d}")
    print("\nBy status:")
    for k, v in by_status.most_common():
        print(f"  {k:15s} {v:>4d}")

    # Treasury
    treasury = sb.table("treasury").select("amount, currency, source_platform").execute().data
    total_usd = sum(float(r["amount"]) for r in treasury if r.get("currency") == "USD")
    total_usdc = sum(float(r["amount"]) for r in treasury if r.get("currency") == "USDC")
    print(f"\nTreasury: ${total_usd:.2f} USD, {total_usdc:.2f} USDC ({len(treasury)} entries)")
    print("  (Note: Twitter entries are estimated, not collected)")

    # Recent runs
    runs = sb.table("agent_runs").select("agent_name, status, started_at, summary").order(
        "started_at", desc=True
    ).limit(6).execute().data
    print("\nRecent agent runs:")
    for r in runs:
        ts = r["started_at"][:16] if r.get("started_at") else "?"
        summary = ""
        if r.get("summary"):
            s = r["summary"]
            if isinstance(s, dict):
                summary = " | ".join(f"{k}={v}" for k, v in s.items() if v)
            else:
                summary = str(s)[:60]
        print(f"  {ts}  {r['agent_name']:8s}  {r['status']:10s}  {summary[:50]}")

    # Pending BD approvals
    pending = sb.table("outreach_log").select("id").eq("approved", False).execute().data
    if pending:
        print(f"\n** {len(pending)} BD outreach drafts pending approval **")
        print("   Run: python -m agents.bd.approve")


def show_opps():
    sb = get_client()
    opps = sb.table("opportunities").select(
        "platform, status, task_description, estimated_value, created_at"
    ).order("created_at", desc=True).limit(20).execute().data

    print(f"{'TIME':17s} {'PLATFORM':14s} {'STATUS':11s} {'VALUE':>7s}  DESCRIPTION")
    print("-" * 90)
    for o in opps:
        ts = o.get("created_at", "")[:16]
        desc = (o.get("task_description") or "")[:45].replace("\n", " ")
        val = f"${o['estimated_value']:.0f}" if o.get("estimated_value") else "-"
        print(f"{ts}  {o['platform']:13s} {o['status']:10s} {val:>7s}  {desc}")


def show_treasury():
    sb = get_client()
    rows = sb.table("treasury").select("*").order("received_at", desc=True).limit(20).execute().data

    total_by_currency = {}
    print(f"{'TIME':17s} {'PLATFORM':14s} {'AMOUNT':>10s} {'CURR':5s}")
    print("-" * 55)
    for r in rows:
        ts = r.get("received_at", "")[:16]
        amt = float(r.get("amount", 0))
        cur = r.get("currency", "?")
        total_by_currency[cur] = total_by_currency.get(cur, 0) + amt
        print(f"{ts}  {r.get('source_platform', '?'):13s} {amt:>10.2f} {cur}")

    print("-" * 55)
    for cur, total in total_by_currency.items():
        print(f"{'TOTAL':17s} {'':14s} {total:>10.2f} {cur}")


def show_runs():
    sb = get_client()
    runs = sb.table("agent_runs").select("*").order("started_at", desc=True).limit(15).execute().data

    print(f"{'TIME':17s} {'AGENT':8s} {'STATUS':10s}  SUMMARY")
    print("-" * 70)
    for r in runs:
        ts = r.get("started_at", "")[:16]
        summary = ""
        if r.get("summary") and isinstance(r["summary"], dict):
            summary = " | ".join(f"{k}={v}" for k, v in r["summary"].items() if v)
        elif r.get("error"):
            summary = f"ERR: {r['error'][:40]}"
        print(f"{ts}  {r['agent_name']:7s}  {r['status']:9s}  {summary[:45]}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "summary"
    {"summary": show_summary, "opps": show_opps, "treasury": show_treasury, "runs": show_runs}.get(
        cmd, show_summary
    )()
