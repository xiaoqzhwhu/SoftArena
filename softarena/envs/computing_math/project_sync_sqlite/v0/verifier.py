from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


def verify(episode: dict[str, Any]) -> dict[str, Any]:
    db_path = Path(episode["db_path"])
    expected = json.loads(Path(episode["hidden"]["expected_path"]).read_text(encoding="utf-8"))
    required_artifacts = expected["required_artifacts"]
    expected_counts = expected["expected_counts"]
    checks: list[dict[str, Any]] = []
    score = 0.0

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        source_tables_exist = all(table in tables for table in expected_counts)
        checks.append({"name": "source_tables_exist", "passed": source_tables_exist, "expected": sorted(expected_counts)})
        has_report = "project_sync_report" in tables
        has_status = "report_status" in tables
        checks.append({"name": "project_sync_report_table_exists", "passed": has_report})
        checks.append({"name": "report_status_table_exists", "passed": has_status})
        if source_tables_exist:
            score += 0.1
        if has_report:
            score += 0.2
            rows = [
                {"artifact": row["artifact"], "status": row["status"], "evidence": row["evidence"]}
                for row in conn.execute("SELECT artifact, status, evidence FROM project_sync_report").fetchall()
            ]
            artifacts = {row["artifact"] for row in rows}
            artifacts_ok = all(name in artifacts for name in required_artifacts)
            statuses_ok = all(row["status"] == "ready" for row in rows if row["artifact"] in required_artifacts)
            evidence_ok = all(str(row["evidence"] or "").strip() for row in rows if row["artifact"] in required_artifacts)
            checks.append({"name": "all_required_artifacts_reported", "passed": artifacts_ok, "observed": sorted(artifacts)})
            checks.append({"name": "artifact_statuses_ready", "passed": statuses_ok})
            checks.append({"name": "artifact_evidence_nonempty", "passed": evidence_ok})
            if artifacts_ok:
                score += 0.25
            if statuses_ok:
                score += 0.1
            if evidence_ok:
                score += 0.1
        else:
            checks.extend(
                [
                    {"name": "all_required_artifacts_reported", "passed": False},
                    {"name": "artifact_statuses_ready", "passed": False},
                    {"name": "artifact_evidence_nonempty", "passed": False},
                ]
            )
        if has_status:
            status_rows = conn.execute("SELECT status FROM report_status").fetchall()
            status_ready = any(row["status"] == "ready" for row in status_rows)
            checks.append({"name": "report_status_ready", "passed": status_ready})
            if status_ready:
                score += 0.1
        else:
            checks.append({"name": "report_status_ready", "passed": False})

        count_checks_passed = True
        observed_counts: dict[str, int] = {}
        for table, expected_count in expected_counts.items():
            count = int(conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"])
            observed_counts[table] = count
            if count != int(expected_count):
                count_checks_passed = False
        checks.append(
            {
                "name": "source_table_counts_preserved",
                "passed": count_checks_passed,
                "observed": observed_counts,
                "expected": expected_counts,
            }
        )
        if count_checks_passed:
            score += 0.15
    finally:
        conn.close()

    score = round(score, 4)
    return {
        "score": score,
        "passed": score == 1.0,
        "checks": checks,
        "diagnostics": "ok" if score == 1.0 else "project sync sqlite report is incomplete",
        "metrics": {"num_checks": len(checks)},
    }
