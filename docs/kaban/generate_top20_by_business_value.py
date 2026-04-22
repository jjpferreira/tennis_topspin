#!/usr/bin/env python3
"""Generate TOP_20_OPEN_BY_BUSINESS_VALUE.md from features.json.

Run after parse_features_md.py to refresh the top-20 list.
"""
import json
from pathlib import Path

DIR = Path(__file__).resolve().parent
FEATURES_JSON = DIR / "features.json"
OUT_MD = DIR / "TOP_20_OPEN_BY_BUSINESS_VALUE.md"


def bv_score(item):
    s = item.get("businessValueScore")
    if s is not None:
        return int(s) if isinstance(s, (int, float)) else 0
    p = (item.get("priority") or "").upper()
    return {"HIGH": 5, "MEDIUM": 3, "LOW": 1}.get(p, 0)


def main():
    with open(FEATURES_JSON) as f:
        data = json.load(f)
    open_items = [
        x for x in data["features"]
        if (x.get("status") or "").upper() not in ("COMPLETED", "DONE")
    ]
    def sort_key(x):
        bv = bv_score(x)
        p = (x.get("priority") or "").upper()
        prio_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(p, 3)
        return (-bv, prio_order, x.get("featureId") or "")
    sorted_open = sorted(open_items, key=sort_key)
    top20 = sorted_open[:20]
    lines = [
        "# Top 20 open items by business value",
        "",
        "Open bugs, features, and ideas from the feature kanban, ordered by **business value** (highest first).",
        "When `businessValueScore` is set in the backlog, it is used; otherwise priority is used as proxy (HIGH=5, MEDIUM=3, LOW=1).",
        "",
        "| # | ID | Type | Priority | Business value | Title |",
        "|---|-----|------|----------|----------------|-------|",
    ]
    for i, item in enumerate(top20, 1):
        fid = item.get("featureId") or ""
        status = (item.get("status") or "").upper()
        typ = "Bug" if status == "BUG" else "Feature"
        prio = item.get("priority") or ""
        bv = item.get("businessValueScore")
        bv_str = str(bv) if bv is not None else "—"
        title = (item.get("title") or "").replace("|", "\\|")[:70]
        lines.append(f"| {i} | {fid} | {typ} | {prio} | {bv_str} | {title} |")
    lines.extend([
        "",
        "*Generated from `features.json`. To refresh: run `python3 _docs/product/kaban/parse_features_md.py` then `python3 _docs/product/kaban/generate_top20_by_business_value.py`.*",
        "",
    ])
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT_MD} ({len(top20)} items)")


if __name__ == "__main__":
    main()
