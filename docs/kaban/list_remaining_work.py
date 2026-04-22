#!/usr/bin/env python3
"""
List all features and bugs that are NOT completed (bulk view of what's left to do).
Reads from features.json — run parse_features_md.py first if the file is missing or stale.

Usage (from repo root):
  python3 _docs/product/kaban/list_remaining_work.py

Or from _docs/product/kaban/:
  python3 list_remaining_work.py
"""
import json
from pathlib import Path

JSON_PATH = Path(__file__).resolve().parent / "features.json"

# Statuses that count as "remaining" (not done)
REMAINING_STATUSES = {"IDEA", "PLANNED", "IN-PROGRESS", "BUG"}


def main() -> None:
    if not JSON_PATH.exists():
        print("features.json not found. Run first:")
        print("  python3 _docs/product/kaban/parse_features_md.py")
        return

    with open(JSON_PATH, encoding="utf-8") as f:
        data = json.load(f)

    features = data.get("features") or []
    remaining = [f for f in features if (f.get("status") or "").upper() in REMAINING_STATUSES]

    # Sort: BUG first, then IN-PROGRESS, PLANNED, IDEA; then by priority HIGH/MEDIUM/LOW; then by id
    def order_key(f: dict) -> tuple:
        s = (f.get("status") or "").upper()
        status_order = ("BUG", "IN-PROGRESS", "PLANNED", "IDEA")
        p = (f.get("priority") or "").upper()
        priority_order = ("HIGH", "MEDIUM", "LOW")
        return (
            status_order.index(s) if s in status_order else 99,
            -(priority_order.index(p)) if p in priority_order else 0,
            (f.get("featureId") or ""),
        )

    remaining.sort(key=order_key)

    print("Remaining work (not COMPLETED / CANCELLED)")
    print("Run: python3 _docs/product/kaban/parse_features_md.py  to refresh from FEATURES_AND_IDEAS.md")
    print("-" * 100)
    print(f"{'Status':<14} {'ID':<14} {'Priority':<8} Title")
    print("-" * 100)

    for f in remaining:
        status = (f.get("status") or "?").upper()
        fid = f.get("featureId") or "?"
        priority = (f.get("priority") or "-").upper()
        title = (f.get("title") or f.get("description") or "?").strip()
        if len(title) > 58:
            title = title[:55] + "..."
        print(f"{status:<14} {fid:<14} {priority:<8} {title}")

    print("-" * 100)
    print(f"Total remaining: {len(remaining)}")
    print("\nOpen kanban.html in a browser for the visual board.")


if __name__ == "__main__":
    main()
