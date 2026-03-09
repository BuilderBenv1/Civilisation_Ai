"""CLI approval queue for BD outreach drafts.

Usage: python -m agents.bd.approve
"""

import sys
import os

# Allow running from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from shared.supabase_client import get_pending_outreach, approve_outreach, mark_outreach_sent
from shared.config import get_logger

log = get_logger("bd.approve")


def show_pending():
    """Show all pending outreach drafts and let user approve/reject."""
    pending = get_pending_outreach()

    if not pending:
        print("\nNo pending outreach drafts.\n")
        return

    print(f"\n{'='*60}")
    print(f"  PENDING OUTREACH DRAFTS ({len(pending)})")
    print(f"{'='*60}\n")

    for i, item in enumerate(pending, 1):
        prospect = item.get("prospects", {}) or {}
        handle = prospect.get("handle", "unknown")
        platform = prospect.get("platform", "unknown")
        channel = item.get("channel", "unknown")
        draft = item.get("message_draft", "")

        print(f"--- Draft #{i} ---")
        print(f"  To: @{handle} ({platform})")
        print(f"  Via: {channel}")
        print(f"  Created: {item.get('created_at', 'unknown')}")
        print(f"\n  Message:")
        for line in draft.split("\n"):
            print(f"    {line}")
        print()

        while True:
            choice = input(f"  [A]pprove / [E]dit / [S]kip / [R]eject? ").strip().lower()
            if choice == "a":
                approve_outreach(item["id"])
                print(f"  -> Approved.\n")
                log.info("Outreach %s approved for @%s", item["id"], handle)
                break
            elif choice == "e":
                print(f"  Current draft:\n    {draft}\n")
                new_draft = input("  Enter new message (or press Enter to keep): ").strip()
                if new_draft:
                    from shared.supabase_client import get_client
                    get_client().table("outreach_log").update(
                        {"message_draft": new_draft}
                    ).eq("id", item["id"]).execute()
                    print(f"  -> Draft updated.")
                approve_outreach(item["id"])
                print(f"  -> Approved.\n")
                log.info("Outreach %s edited and approved for @%s", item["id"], handle)
                break
            elif choice == "s":
                print(f"  -> Skipped.\n")
                break
            elif choice == "r":
                from shared.supabase_client import get_client
                get_client().table("outreach_log").delete().eq("id", item["id"]).execute()
                print(f"  -> Rejected and deleted.\n")
                log.info("Outreach %s rejected for @%s", item["id"], handle)
                break
            else:
                print("  Invalid choice. Use A/E/S/R.")

    print(f"{'='*60}\n")


if __name__ == "__main__":
    show_pending()
