#!/usr/bin/env python3
"""
Add **Complexity:** and **Business Value:** to each feature block in FEATURES_AND_IDEAS.md
by inferring from the value table, priority, and description. Run from repo root or _docs/product/kaban/.

Usage: python3 add_scores_to_features_md.py
"""
import re
from pathlib import Path

MD_PATH = Path(__file__).resolve().parent.parent / "FEATURES_AND_IDEAS.md"


def _parse_value_table(content: str) -> dict[str, int]:
    """Parse 'Why it maximises value' table; return feat_id -> business value score 1-5 (by position)."""
    result: dict[str, int] = {}
    lines = content.split("\n")
    in_table = False
    row_num = 0
    for line in lines:
        if "Why it maximises value" in line and "| # |" in line:
            in_table = True
            continue
        if in_table:
            if not line.strip().startswith("|") or "---" in line:
                if "**Next tier" in line or "**Additional" in line:
                    in_table = False
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 4 and re.match(r"FEAT-\d+", (parts[3] or "").strip()):
                feat_id = parts[3].strip()
                row_num += 1
                # Top rows = higher value: 1-5 → 5, 6-10 → 4, 11-14 → 3
                if row_num <= 5:
                    result[feat_id] = 5
                elif row_num <= 10:
                    result[feat_id] = 4
                else:
                    result[feat_id] = 3
            if "**Next tier" in line or "**Additional" in line:
                break
    return result


def _infer_business_value(feat_id: str, priority: str, value_table: dict[str, int]) -> int:
    if feat_id in value_table:
        return value_table[feat_id]
    u = (priority or "").upper()
    if u == "HIGH":
        return 4
    if u == "MEDIUM":
        return 3
    return 2


def _infer_complexity(title: str, description: str) -> str:
    """Infer Low/Medium/High from title and description."""
    combined = (title + " " + (description or ""))[:800].lower()
    # Low: small scope, UI-only, icon, styling, docs
    if any(x in combined for x in ["add icon", "projects view", "icon to", "documentation generator", "workflow documentation"]):
        return "Low"
    if "legal ui" in combined or "gdpr" in combined and "styling" in combined:
        return "Low"
    if "marketplace" in combined and "template" in combined:
        return "Low"
    # High: cross-cutting, multi-system, encryption, tenant, ingestion, RAG pipeline, git, licensing, governance
    if any(x in combined for x in [
        "tenant-level isolation", "content ingestion", "rag ingestion pipeline",
        "encrypted fields", "capability management system", "cross-environment",
        "universal data ingestion", "real-time collaborative", "chat-to-workflow",
        "unified liliflow agent", "external model deployment", "git integration",
        "licensing", "governance", "pii", "mfa", "sso", "environment credential",
        "voice input for ai", "datatables", "own table per dataset"
    ]):
        return "High"
    # Medium: packaging, sharing, approval, forms, system templates, triggers, etc.
    return "Medium"


def main():
    content = MD_PATH.read_text(encoding="utf-8")
    value_table = _parse_value_table(content)

    blocks = re.split(r"\n(?=### )", content)
    out_blocks = []
    for block in blocks:
        block = block.rstrip()
        if not block:
            out_blocks.append(block)
            continue
        # Only process feature blocks that have **Feature ID:** and no **Complexity:** yet
        id_match = re.search(r"\*\*Feature ID:\*\*\s*`([^`]+)`", block)
        if not id_match:
            out_blocks.append(block)
            continue
        feat_id = id_match.group(1).strip()
        if "**Complexity:**" in block and "**Business Value:**" in block:
            out_blocks.append(block)
            continue

        # Priority from first line or **Priority:**
        priority = "MEDIUM"
        if "[HIGH]" in block.split("\n")[0]:
            priority = "HIGH"
        elif "[LOW]" in block.split("\n")[0]:
            priority = "LOW"
        pm = re.search(r"\*\*Priority:\*\*\s*\[?(HIGH|MEDIUM|LOW)\]?", block, re.I)
        if pm:
            priority = pm.group(1).upper()

        # Title: first ### line
        first_line = block.split("\n")[0]
        title = re.sub(r"^###\s*", "", first_line)
        title = re.sub(r"\[IDEA\]\s*\[HIGH\]\s*", "", title, flags=re.I)
        title = re.sub(r"\[PLANNED\]\s*\[HIGH\]\s*", "", title, flags=re.I)
        title = re.sub(r"\[.*?\]\s*", "", title)
        desc_match = re.search(r"\*\*Description(?:\s*\([^)]*\))?:\s*([\s\S]*?)(?=\n\s*\*\*[A-Za-z]|\Z)", block)
        description = desc_match.group(1).strip()[:500] if desc_match else ""

        complexity = _infer_complexity(title, description)
        value = _infer_business_value(feat_id, priority, value_table)

        # Insert **Complexity:** and **Business Value:** after the **Feature ID:** line
        # The line looks like: **Feature ID:** `FEAT-XXX` | **Status:** ... | **Last Updated:** ...
        feature_id_line_pattern = re.compile(
            r"(\*\*Feature ID:\*\*\s*`[^`]+`[^\n]*)(\n)",
            re.MULTILINE
        )
        insert = f"\n**Complexity:** {complexity}\n**Business Value:** {value}\n"
        new_block, n = feature_id_line_pattern.subn(r"\1" + insert + r"\2", block, count=1)
        if n == 0:
            out_blocks.append(block)
        else:
            out_blocks.append(new_block)

    new_content = "\n".join(out_blocks)
    # Fix double newlines from join (blocks already had newlines)
    if new_content != content:
        MD_PATH.write_text(new_content, encoding="utf-8")
        print(f"Updated {MD_PATH} with **Complexity:** and **Business Value:** for all feature blocks.")
    else:
        print("No changes (scores already present or no blocks matched).")


if __name__ == "__main__":
    main()
