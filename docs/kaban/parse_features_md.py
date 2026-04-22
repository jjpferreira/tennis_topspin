#!/usr/bin/env python3
"""
Parse FEATURES_AND_IDEAS.md and output a JSON array of features for the Kanban board.
Each feature has: id, featureId, title, status, priority, description, fullBody, relatedFeatures.

Relationships: In a feature block add **Related:** FEAT-034 (implements-after), FEAT-005 (related).
Relation types (e.g. implements-after, related, complements) are shown on the Kanban card and in the
modal; related features in the modal are clickable to open that feature.

Usage (from repo root or from _docs/product/kaban/):
  python3 parse_features_md.py
  # or, if executable: chmod +x parse_features_md.py  then  ./parse_features_md.py
"""
import re
import json
from pathlib import Path
from datetime import datetime

MD_PATH = Path(__file__).resolve().parent / "../FEATURES_AND_IDEAS.md"
JSON_PATH = Path(__file__).resolve().parent / "features.json"
KANBAN_HTML = Path(__file__).resolve().parent / "kanban.html"
KANBAN_TEMPLATE = Path(__file__).resolve().parent / "kanban_template.html"


def _find_matching_brace(html: str, start: int) -> int:
    """Find the position of the closing } that matches the { at start. Skips strings."""
    depth = 0
    i = start
    in_double = False
    in_single = False
    escape = False
    while i < len(html):
        c = html[i]
        if escape:
            escape = False
            i += 1
            continue
        if c == "\\" and (in_double or in_single):
            escape = True
            i += 1
            continue
        if in_double:
            if c == '"':
                in_double = False
            i += 1
            continue
        if in_single:
            if c == "'":
                in_single = False
            i += 1
            continue
        if c == '"':
            in_double = True
            i += 1
            continue
        if c == "'":
            in_single = True
            i += 1
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def normalize_status(s: str) -> str:
    if not s:
        return "IDEA"
    u = s.upper()
    if "COMPLETED" in u:
        return "COMPLETED"
    if "REMOVED" in u or "CANCELLED" in u:
        return "CANCELLED" if "CANCELLED" in u else "REMOVED"
    if "IN-PROGRESS" in u or "IN PROGRESS" in u:
        return "IN-PROGRESS"
    if "PLANNED" in u:
        return "PLANNED"
    if "BUG" in u:
        return "BUG"
    if "IDEA" in u:
        return "IDEA"
    return "IDEA"


def extract_priority(first_line: str) -> str:
    if "[HIGH]" in first_line:
        return "HIGH"
    if "[MEDIUM]" in first_line:
        return "MEDIUM"
    if "[LOW]" in first_line:
        return "LOW"
    return "MEDIUM"


def _priority_from_completed_block(block: str) -> str:
    """Extract priority from a completed-feature block (has **Priority:** `[HIGH]` etc.)."""
    if "[HIGH]" in block and "**Priority:**" in block:
        return "HIGH"
    if "[LOW]" in block and "**Priority:**" in block:
        return "LOW"
    if "[MEDIUM]" in block and "**Priority:**" in block:
        return "MEDIUM"
    return "MEDIUM"


def _parse_business_value_table(content: str) -> dict[str, str]:
    """Parse the 'Why it maximises value' table(s); return map feature_id -> business value text."""
    result: dict[str, str] = {}
    # Match table header then rows with | N | ... | FEAT-XXX | Why value |
    lines = content.split("\n")
    in_value_table = False
    for line in lines:
        if "Why it maximises value" in line and "| # |" in line:
            in_value_table = True
            continue
        if in_value_table:
            if not line.strip().startswith("|") or line.strip() == "|---|":
                # End of table (empty line or next section)
                if line.strip() and "|" not in line.strip()[:2]:
                    in_value_table = False
                continue
            parts = [p.strip() for p in line.split("|")]
            # parts[0] empty, [1] #, [2] Feature name, [3] ID, [4] Why value
            if len(parts) >= 5 and "---" not in (parts[1] or "") and re.match(r"FEAT-\d+", (parts[3] or "").strip()):
                feat_id = parts[3].strip()
                value = parts[4].strip()
                if value and feat_id:
                    result[feat_id] = value
            if line.strip().startswith("|") and "**Next tier" in line:
                break
    return result


def _extract_complexity(block: str) -> str:
    """Extract **Complexity:** Low/Medium/High from feature block if present."""
    m = re.search(r"\*\*Complexity:\*\*\s*(\w+)", block, re.I)
    return m.group(1).strip().upper() if m else ""


def _complexity_to_score(complexity: str) -> int | None:
    """Map Low/Medium/High to numeric score 1–3. Returns None if missing."""
    if not complexity or not complexity.strip():
        return None
    u = complexity.strip().upper()
    if u == "LOW":
        return 1
    if u == "HIGH":
        return 3
    if u == "MEDIUM":
        return 2
    return None


def _extract_business_value_score(block: str) -> int | None:
    """Extract **Business Value:** N (1–5 or 1–10) from feature block if present."""
    m = re.search(r"\*\*Business Value:\*\*\s*(\d+)", block, re.I)
    if not m:
        return None
    try:
        n = int(m.group(1).strip())
        return n if 1 <= n <= 10 else None
    except ValueError:
        return None


def _extract_completed_date(block: str) -> str | None:
    """Extract **Completed:** YYYY-MM-DD from a completed-feature block. Used to order Done column by last completed."""
    m = re.search(r"\*\*Completed:\*\*\s*(\d{4}-\d{2}-\d{2})", block)
    return m.group(1).strip() if m else None


def _extract_last_updated_date(block: str) -> str | None:
    """Extract **Last Updated:** YYYY-MM-DD from a feature block (first line or **Last Updated:** line). For dashboard 'across time'."""
    m = re.search(r"\*\*Last Updated:\*\*\s*(\d{4}-\d{2}-\d{2})", block)
    return m.group(1).strip() if m else None


def _extract_added_date(block: str) -> str | None:
    """Extract **Added:** YYYY-MM-DD from a feature block (date feature was added to backlog). Preserved when moving to Completed so Kanban can show both Added and Completed."""
    m = re.search(r"\*\*Added:\*\*\s*(\d{4}-\d{2}-\d{2})", block)
    return m.group(1).strip() if m else None


def _extract_analysis_path(block: str) -> str | None:
    """
    Extract analysis document path from a feature block.
    Looks for a markdown link whose target is analysis/SOMETHING.md
    (e.g. **Analysis & current-state mapping:** [text](analysis/FEAT_028_....md)).
    Returns the path (e.g. 'analysis/FEAT_028_UNIFY_SCHEDULING_ANALYSIS.md') or None.
    """
    m = re.search(r"\]\((analysis/[^)\s]+\.md)\)", block)
    if m:
        return m.group(1).strip()
    return None


def _extract_related_features(block: str) -> list[dict]:
    """
    Extract related features from a feature block.
    Supports:
    - **Related:** FEAT-034 (implements-after), FEAT-005 (related)
    - **Relation to FEAT-XXX:** ... (extracts FEAT-XXX; relation = implements-after if "Implement X first" in text, else related)
    Returns list of { "featureId": "FEAT-034", "relation": "implements-after" }.
    """
    related = []
    # Explicit **Related:** line
    related_match = re.search(r"\*\*Related:\*\*\s*([^\n]+)", block)
    if related_match:
        line = related_match.group(1).strip()
        # Split by comma; each part: "FEAT-XXX (relation-type)" or "FEAT-XXX"
        for part in re.split(r",\s*", line):
            part = part.strip()
            if not part:
                continue
            id_m = re.search(r"(FEAT-\d+)", part, re.I)
            if not id_m:
                continue
            feature_id = id_m.group(1).strip().upper()
            relation = "related"
            paren = re.search(r"\(\s*([a-z-]+)\s*\)", part, re.I)
            if paren:
                relation = paren.group(1).strip().lower().replace(" ", "-")
            related.append({"featureId": feature_id, "relation": relation})
    # Fallback: **Relation to FEAT-XXX:** (legacy format)
    if not related:
        for m in re.finditer(r"\*\*Relation to (FEAT-\d+):\*\*", block, re.I):
            target = m.group(1).strip().upper()
            # Check if "Implement X first" or "implement.*first" appears in the same paragraph
            start = m.start()
            end = block.find("\n\n", start)
            if end == -1:
                end = len(block)
            para = block[start:end]
            rel = "implements-after" if re.search(r"implement\s+.*first|implement\s+\w+\s+first", para, re.I) else "related"
            related.append({"featureId": target, "relation": rel})
    return related


def _parse_bugs_section(content: str) -> list[dict]:
    """
    Explicitly extract bug blocks from the "## Bugs & Issues" section.
    This ensures we never miss bugs even if the main split/loop skips them.
    """
    # Find the Bugs section (from "## Bugs & Issues" until next "## " or end)
    bugs_match = re.search(
        r"##\s*Bugs\s*&\s*Issues[^\n]*\n(.*?)(?=\n##\s+|\Z)",
        content,
        re.DOTALL | re.IGNORECASE,
    )
    if not bugs_match:
        return []
    section = bugs_match.group(1).strip()
    # Split into blocks by ###
    blocks = re.split(r"\n(?=### )", section)
    bugs = []
    for i, block in enumerate(blocks):
        block = block.strip()
        if not block or not block.startswith("### "):
            continue
        bug_id_m = re.search(r"\*\*Bug ID:\*\*\s*`([^`]+)`", block)
        if not bug_id_m:
            continue
        feat_id = bug_id_m.group(1).strip()
        first = block.split("\n")[0]
        title_match = re.match(r"^### \s*(.+)$", first)
        title_full = title_match.group(1).strip() if title_match else first.replace("###", "").strip()
        title_clean = re.sub(r"\[BUG\]\s*", "", title_full, flags=re.I)
        title_clean = re.sub(r"\[HIGH\]\s*", "", title_clean, flags=re.I)
        title_clean = re.sub(r"\[MEDIUM\]\s*", "", title_clean, flags=re.I)
        title_clean = re.sub(r"\[LOW\]\s*", "", title_clean, flags=re.I)
        title_clean = title_clean.strip()
        desc_match = re.search(
            r"\*\*Description(?:\s*\([^)]*\))?:\s*([\s\S]*?)(?=\n\s*\*\*[A-Za-z]|\Z)",
            block,
        )
        description = desc_match.group(1).strip()[:500] if desc_match else ""
        if description and len(description) > 500:
            description = description[:500] + "..."
        bugs.append({
            "featureId": feat_id,
            "title": title_clean or title_full,
            "status": "BUG",
            "priority": extract_priority(first),
            "description": description,
            "fullBody": block,
            "businessValue": "",
            "complexity": "",
            "complexityScore": None,
            "businessValueScore": None,
            "relatedFeatures": _extract_related_features(block),
            "analysisPath": _extract_analysis_path(block),
        })
    return bugs


def parse_md(content: str) -> list[dict]:
    # First: explicitly extract bugs from "## Bugs & Issues" so we never miss them
    bugs_from_section = _parse_bugs_section(content)
    bug_ids_from_section = {b["featureId"] for b in bugs_from_section}

    # Split by ### at start of line (feature blocks)
    blocks = re.split(r"\n(?=### )", content)

    features = []
    for i, block in enumerate(blocks):
        block = block.strip()
        if not block or block.startswith("## ") and "Features & Ideas" not in block and "Completed" not in block and "Bugs" not in block:
            continue
        # Skip intro blocks before first ### [IDEA] etc.
        lines = block.split("\n")
        if not lines:
            continue
        first = lines[0]
        # Must look like ### [SOMETHING] ... or ### ✅ ... (completed features section)
        is_completed_checkmark = re.match(r"^### \s*✅\s", first)
        if not re.match(r"^### \[", first) and not is_completed_checkmark:
            continue

        # Skip stub blocks that point to Completed Features section (e.g.
        # "### [COMPLETED - see Completed Features] Feature Name (FEAT-XXX)")
        # These are placeholders; the real entry lives in the "## Completed Features ✅" section.
        if "see Completed Features" in first or "Moved to Completed Features section below" in block:
            continue

        # Parse first line: ### [STATUS] [PRIORITY] Title or ### [BUG] Title or ### ✅ Title
        title_match = re.match(r"^### \s*(.+)$", first)
        title_full = title_match.group(1).strip() if title_match else first.replace("###", "").strip()
        # Remove status/priority tags from title for display
        title_clean = re.sub(r"^✅\s*", "", title_full, flags=re.I)
        title_clean = re.sub(r"\[IDEA\]\s*", "", title_clean, flags=re.I)
        title_clean = re.sub(r"\[PLANNED\]\s*", "", title_clean, flags=re.I)
        title_clean = re.sub(r"\[IN-PROGRESS\]\s*", "", title_clean, flags=re.I)
        title_clean = re.sub(r"\[COMPLETED\]\s*", "", title_clean, flags=re.I)
        title_clean = re.sub(r"\[CANCELLED\]\s*", "", title_clean, flags=re.I)
        title_clean = re.sub(r"\[REMOVED[^\]]*\]\s*", "", title_clean, flags=re.I)
        title_clean = re.sub(r"\[BUG\]\s*", "", title_clean, flags=re.I)
        title_clean = re.sub(r"\[HIGH\]\s*", "", title_clean, flags=re.I)
        title_clean = re.sub(r"\[MEDIUM\]\s*", "", title_clean, flags=re.I)
        title_clean = re.sub(r"\[LOW\]\s*", "", title_clean, flags=re.I)
        title_clean = title_clean.strip()

        status = "COMPLETED" if is_completed_checkmark else normalize_status(first)
        priority = extract_priority(first) if not is_completed_checkmark else _priority_from_completed_block(block)

        # Feature ID or Bug ID (completed blocks may have **Feature ID:** or **Status:** only)
        feat_id = None
        id_match = re.search(r"\*\*Feature ID:\*\*\s*`([^`]+)`", block)
        if id_match:
            feat_id = id_match.group(1).strip()
        if not feat_id:
            bug_match = re.search(r"\*\*Bug ID:\*\*\s*`([^`]+)`", block)
            if bug_match:
                feat_id = bug_match.group(1).strip()
        # Ensure bug blocks get status BUG unless they are completed/done (✅ or DONE)
        is_bug_block = bool(re.search(r"\*\*Bug ID:\*\*\s*`", block))
        is_done_bug = "DONE" in (first or "").upper() or "**Status:** `[DONE]`" in block or "**Status:** `[COMPLETED]`" in block
        if is_bug_block and not is_completed_checkmark and not is_done_bug:
            status = "BUG"
        if not feat_id and is_completed_checkmark:
            # Completed section items without Feature ID: use slug from title so they show in Kanban
            slug = re.sub(r"[^\w\s-]", "", title_clean).strip().lower().replace(" ", "-")[:40]
            feat_id = f"COMPLETED-{slug}" if slug else f"COMPLETED-{i}"
        if not feat_id:
            # Skip blocks with no ID (e.g. section headers)
            continue

        # Description: from **Description:** (or **Description (archived):**) until next **Bold:** or end of block
        # Note: in the .md the format is **Description:** (colon inside bold), not **Description** **:**
        desc_match = re.search(
            r"\*\*Description(?:\s*\([^)]*\))?:\s*([\s\S]*?)(?=\n\s*\*\*[A-Za-z]|\Z)",
            block,
        )
        description = ""
        if desc_match:
            description = desc_match.group(1).strip()
            # Strip accidental leading "** " if regex captured bold from same line
            if description.startswith("** "):
                description = description[3:].strip()
            if len(description) > 500:
                description = description[:500] + "..."

        business_value = _parse_business_value_table(content).get(feat_id, "")
        complexity = _extract_complexity(block)
        complexity_score = _complexity_to_score(complexity)
        business_value_score = _extract_business_value_score(block)
        related_features = _extract_related_features(block)
        analysis_path = _extract_analysis_path(block)
        completed_date = _extract_completed_date(block) if status == "COMPLETED" else None
        last_updated_date = _extract_last_updated_date(block)
        added_date = _extract_added_date(block)
        analysis_content = None
        if analysis_path:
            analysis_file = (MD_PATH.parent / analysis_path).resolve()
            if analysis_file.exists():
                try:
                    analysis_content = analysis_file.read_text(encoding="utf-8")
                except Exception:
                    pass

        feat = {
            "id": f"item-{i}",
            "featureId": feat_id,
            "title": title_clean or title_full,
            "status": status,
            "priority": priority,
            "description": description,
            "fullBody": block,
            "businessValue": business_value,
            "complexity": complexity,
            "complexityScore": complexity_score,
            "businessValueScore": business_value_score,
            "relatedFeatures": related_features,
        }
        if completed_date:
            feat["completedDate"] = completed_date
        if last_updated_date:
            feat["lastUpdatedDate"] = last_updated_date
        if added_date:
            feat["addedDate"] = added_date
        if analysis_path:
            feat["analysisPath"] = analysis_path
        if analysis_content:
            feat["analysisContent"] = analysis_content
        features.append(feat)

    # Merge explicitly extracted bugs: ensure status BUG for open bugs only (don't overwrite COMPLETED/DONE)
    existing_ids = {f["featureId"] for f in features}
    for f in features:
        if f["featureId"] in bug_ids_from_section and (f.get("status") or "").upper() not in ("COMPLETED", "DONE"):
            f["status"] = "BUG"
    for b in bugs_from_section:
        if b["featureId"] not in existing_ids:
            b["id"] = f"item-bug-{b['featureId']}"
            analysis_path = b.get("analysisPath")
            if analysis_path:
                analysis_file = (MD_PATH.parent / analysis_path).resolve()
                if analysis_file.exists():
                    try:
                        b["analysisContent"] = analysis_file.read_text(encoding="utf-8")
                    except Exception:
                        pass
            features.append(b)
            existing_ids.add(b["featureId"])

    # Deduplicate by featureId: when two entries share the same ID (e.g. a
    # legacy completed block that was left in the Ideas section and the real
    # entry in "## Completed Features ✅"), keep the richer entry.  Prefer
    # the entry that has a completedDate, longer description, or higher
    # priority — in that order.
    seen: dict[str, int] = {}   # featureId -> index in deduped list
    deduped: list[dict] = []
    _prio_rank = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
    for feat in features:
        fid = feat["featureId"]
        if fid not in seen:
            seen[fid] = len(deduped)
            deduped.append(feat)
        else:
            existing = deduped[seen[fid]]
            # Score: completedDate presence, description length, priority rank
            def _score(f: dict) -> tuple:
                return (
                    1 if f.get("completedDate") else 0,
                    len(f.get("description") or ""),
                    _prio_rank.get((f.get("priority") or "").upper(), 0),
                )
            if _score(feat) > _score(existing):
                deduped[seen[fid]] = feat

    return deduped


def main():
    try:
        content = MD_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"Error: Input file not found: {MD_PATH}")
        print("  Run this script from _docs/product/kaban/ or from repo root.")
        raise SystemExit(1)
    except PermissionError:
        print(f"Error: No read permission for: {MD_PATH}")
        raise SystemExit(1)

    features = parse_md(content)
    data = {"features": features}

    # Strict format: COMPLETED/DONE must have Completed date (dashboard "Completed on <date>" uses it)
    done_no_date = [
        f for f in features
        if (f.get("status") or "").upper() in ("COMPLETED", "DONE")
        and not (f.get("completedDate") or "").strip()
    ]
    if done_no_date:
        print("Format: COMPLETED/DONE without **Completed:** YYYY-MM-DD (add in FEATURES_AND_IDEAS.md):")
        for f in done_no_date:
            t = (f.get("title") or "")[:55]
            if len((f.get("title") or "")) > 55:
                t += "..."
            print(f"  - {f.get('featureId')}: {t}")
        print("  See .cursor/rules/feature-format.mdc — Completed date is mandatory for Completed Features blocks.")

    try:
        JSON_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except PermissionError:
        print(f"Error: No write permission for: {JSON_PATH}")
        print("  Check the directory is writable (e.g. chmod, ownership).")
        raise SystemExit(1)
    print(f"Wrote {len(features)} features to {JSON_PATH}")

    # Embed JSON into kanban.html (full fullBody, no truncation)
    features_for_html = data["features"]
    json_str = json.dumps({"features": features_for_html}, ensure_ascii=False)
    # Prevent </script> in JSON from closing the HTML script tag (escape forward slash in </script>)
    json_str = json_str.replace("</script>", "<\\/script>").replace("</SCRIPT>", "<\\/SCRIPT>")
    try:
        build_ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        if KANBAN_TEMPLATE.exists():
            html = KANBAN_TEMPLATE.read_text(encoding="utf-8")
            html = html.replace("__FEATURES_JSON__", json_str).replace("__BUILD_TIMESTAMP__", build_ts)
            KANBAN_HTML.write_text(html, encoding="utf-8")
            print(f"Updated {KANBAN_HTML.name} with embedded JSON (open in browser)")
        elif KANBAN_HTML.exists():
            html = KANBAN_HTML.read_text(encoding="utf-8")
            if "__FEATURES_JSON__" in html:
                html = html.replace("__FEATURES_JSON__", json_str)
                KANBAN_HTML.write_text(html, encoding="utf-8")
                print(f"Updated {KANBAN_HTML.name} with embedded JSON (open in browser)")
            else:
                # Create template for next run: replace embedded JSON with placeholder
                start_marker = "window.FEATURES_JSON = "
                i = html.find(start_marker)
                if i != -1:
                    start = html.find("{", i)
                    if start != -1:
                        end = _find_matching_brace(html, start)
                        if end != -1:
                            template_html = html[:start] + "__FEATURES_JSON__" + html[end + 1 :]
                            KANBAN_TEMPLATE.write_text(template_html, encoding="utf-8")
                            print(f"Created {KANBAN_TEMPLATE.name}; re-run to generate {KANBAN_HTML.name}")
                            KANBAN_HTML.write_text(html[:start] + json_str + html[end + 1 :], encoding="utf-8")
                        else:
                            print("Could not find end of JSON in kanban.html")
                    else:
                        print("Could not find JSON in kanban.html")
                else:
                    print("Could not find FEATURES_JSON in kanban.html")
        else:
            print("No kanban_template.html or kanban.html found; only features.json was written.")
    except PermissionError:
        print(f"Error: No write permission for {KANBAN_HTML} or {KANBAN_TEMPLATE}. Check directory permissions.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
