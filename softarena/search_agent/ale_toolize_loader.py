from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any


def load_category_summary(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    counts: dict[str, int] = {}
    for line in text.splitlines():
        match = re.search(r"\|\s*Computing & Mathematical Sciences.*?`\s*computing_math\s*`\s*\|\s*(\d+)\s*\|", line)
        if match:
            counts["computing_math"] = max(counts.get("computing_math", 0), int(match.group(1)))
    return {
        "path": str(path),
        "computing_math_count_hint": counts.get("computing_math"),
        "summary": "ALE public tasks and Toolize baseline both peak in computing_math; baseline has 1366 computing_math toolsets.",
    }


def load_toolize_review(path: Path, selected_tools: list[str], limit: int = 80) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    selected = {tool.lower() for tool in selected_tools}
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("ale_review_decision") != "include":
                continue
            if row.get("final_ale_domain_code") != "computing_math":
                continue
            haystack = " ".join(
                str(row.get(key) or "")
                for key in (
                    "package",
                    "baseline_id",
                    "toolset_description",
                    "readme_summary",
                    "tool_names_sample",
                    "tool_descriptions_sample",
                )
            ).lower()
            matched = sorted(tool for tool in selected if tool in haystack)
            if not matched:
                # Keep strong computing_math rows as background even without direct selected-tool string match.
                if str(row.get("fit_level") or "").lower() != "strong":
                    continue
            compact = {
                "baseline_id": row.get("baseline_id", ""),
                "package": row.get("package", ""),
                "fit_level": row.get("fit_level", ""),
                "toolset_description": row.get("toolset_description", ""),
                "readme_summary": row.get("readme_summary", ""),
                "tool_names_sample": row.get("tool_names_sample", ""),
                "matched_selected_tools": matched,
            }
            rows.append(compact)
            if len(rows) >= limit:
                break
    return rows

