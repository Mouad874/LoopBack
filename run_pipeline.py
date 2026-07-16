"""
run_pipeline.py — One-shot CLI orchestrator.

Usage:
    python run_pipeline.py            # fresh seed + triage + auto-execute
    python run_pipeline.py --no-seed  # skip seeding (re-triage existing pending)
    python run_pipeline.py --execute-approved  # also process any approved events

This is the script to run on camera for the demo to show the full pipeline.
"""

import argparse
import os
import sys
import io
from dotenv import load_dotenv

# Fix Windows terminal UTF-8 encoding for emoji output
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

load_dotenv()

def main():
    parser = argparse.ArgumentParser(description="LoopBack — full pipeline runner")
    parser.add_argument("--no-seed", action="store_true", help="Skip seeding the database")
    parser.add_argument("--execute-approved", action="store_true", help="Also execute approved events")
    parser.add_argument("--quiet", action="store_true", help="Suppress verbose output")
    args = parser.parse_args()

    verbose = not args.quiet

    if not os.getenv("DASHSCOPE_API_KEY"):
        print("❌ DASHSCOPE_API_KEY not set. Check your .env file.")
        sys.exit(1)

    # Step 1: Init DB
    from store import init_db
    init_db()
    if verbose:
        print("✅ Database initialized (events.db)\n")

    # Step 2: Seed events (unless --no-seed)
    if not args.no_seed:
        from seed_data import main as seed_main
        if verbose:
            print("🌱 Seeding mock events...")
        seed_main()
        if verbose:
            print()

    # Step 3: Triage all pending events
    if verbose:
        print("🤖 Running Qwen triage (function-calling)...")
    from triage import triage_all
    triaged = triage_all(verbose=verbose)
    if verbose:
        print()

    # Step 4: Auto-execute LOW-RISK events immediately
    if verbose:
        print("⚡ Auto-executing low-risk events...")
    from executor import execute_auto_events
    executed = execute_auto_events(verbose=verbose)
    if verbose:
        print()

    # Step 5 (optional): Execute approved events (run after human approves in dashboard)
    if args.execute_approved:
        if verbose:
            print("📤 Executing approved events (with tool-call chain)...")
        from executor import execute_approved_events
        execute_approved_events(verbose=verbose)
        if verbose:
            print()

    # Summary
    if verbose:
        from store import get_by_status
        from store import (STATUS_AUTO_HANDLED, STATUS_AWAITING_APPROVAL,
                           STATUS_ESCALATED, STATUS_APPROVED, STATUS_SENT,
                           STATUS_REJECTED, STATUS_PENDING_TRIAGE)
        print("=" * 55)
        print("  PIPELINE COMPLETE — Event Status Summary")
        print("=" * 55)
        statuses = [
            (STATUS_PENDING_TRIAGE,    "⏳ Pending triage"),
            (STATUS_AUTO_HANDLED,      "✅ Auto-handled"),
            (STATUS_AWAITING_APPROVAL, "📋 Awaiting approval"),
            (STATUS_ESCALATED,         "🚨 Escalated"),
            (STATUS_APPROVED,          "👍 Approved"),
            (STATUS_REJECTED,          "❌ Rejected"),
            (STATUS_SENT,              "📤 Sent"),
        ]
        for status, label in statuses:
            count = len(get_by_status(status))
            if count:
                print(f"  {label:30s} {count}")
        print("=" * 55)
        print("\nOpen the dashboard: streamlit run dashboard.py")


if __name__ == "__main__":
    main()
