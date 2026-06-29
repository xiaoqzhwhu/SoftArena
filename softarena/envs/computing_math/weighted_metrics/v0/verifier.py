from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


def verify(episode: dict[str, Any]) -> dict[str, Any]:
    db_path = Path(episode["db_path"])
    expected_rows = json.loads(Path(episode["hidden"]["expected_rows_path"]).read_text())
    checks: list[dict[str, Any]] = []
    score = 0.0

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        has_table = "segment_metrics" in tables
        checks.append({"name": "segment_metrics_table_exists", "passed": has_table})
        if has_table:
            score += 0.25
            rows = [
                {
                    "segment": row["segment"],
                    "weighted_mean": round(float(row["weighted_mean"]), 4),
                    "n": int(row["n"]),
                }
                for row in conn.execute(
                    "SELECT segment, weighted_mean, n FROM segment_metrics ORDER BY segment"
                ).fetchall()
            ]
            rows_match = rows == expected_rows
            checks.append(
                {
                    "name": "segment_metrics_rows_match",
                    "passed": rows_match,
                    "observed": rows,
                    "expected": expected_rows,
                }
            )
            if rows_match:
                score += 0.75
        else:
            checks.append({"name": "segment_metrics_rows_match", "passed": False})
    finally:
        conn.close()

    score = round(score, 4)
    return {
        "score": score,
        "passed": score == 1.0,
        "checks": checks,
        "diagnostics": "ok" if score == 1.0 else "weighted metrics did not match expected rows",
        "metrics": {"num_checks": len(checks)},
    }
