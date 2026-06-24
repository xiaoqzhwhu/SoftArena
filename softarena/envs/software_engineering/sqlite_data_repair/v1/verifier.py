from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


def verify(episode: dict[str, Any]) -> dict[str, Any]:
    db_path = Path(episode["db_path"])
    expected_rows = json.loads(Path(episode["hidden"]["expected_rows_path"]).read_text())
    checks = []
    score = 0.0

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        has_table = "customer_revenue" in tables
        checks.append({"name": "customer_revenue_table_exists", "passed": has_table})
        if has_table:
            score += 0.25

            rows = [
                {"customer_id": row["customer_id"], "total_revenue": round(float(row["total_revenue"]), 2)}
                for row in conn.execute(
                    "SELECT customer_id, total_revenue FROM customer_revenue ORDER BY customer_id"
                ).fetchall()
            ]
            rows_match = rows == expected_rows
            checks.append(
                {
                    "name": "customer_revenue_rows_match",
                    "passed": rows_match,
                    "observed": rows,
                    "expected": expected_rows,
                }
            )
            if rows_match:
                score += 0.6

            index_rows = conn.execute("PRAGMA index_list(customer_revenue)").fetchall()
            has_index = any(row["name"] == "idx_customer_revenue_customer_id" for row in index_rows)
            checks.append({"name": "customer_revenue_index_exists", "passed": has_index})
            if has_index:
                score += 0.15
        else:
            checks.append({"name": "customer_revenue_rows_match", "passed": False})
            checks.append({"name": "customer_revenue_index_exists", "passed": False})
    finally:
        conn.close()

    score = round(score, 4)
    return {
        "score": score,
        "passed": score == 1.0,
        "checks": checks,
        "diagnostics": "ok" if score == 1.0 else "database state did not satisfy all checks",
        "metrics": {"num_checks": len(checks)},
    }
