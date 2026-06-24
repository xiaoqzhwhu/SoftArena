from __future__ import annotations
import json, sqlite3
from pathlib import Path
from typing import Any

def verify(episode: dict[str, Any]) -> dict[str, Any]:
    expected = json.loads(Path(episode["hidden"]["expected_path"]).read_text())
    conn = sqlite3.connect(episode["db_path"]); conn.row_factory = sqlite3.Row
    try:
        tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "reconciliation_report" not in tables:
            return {"score":0.0,"passed":False,"checks":[{"name":"report_table_exists","passed":False}],"diagnostics":"missing reconciliation_report","metrics":{}}
        rows = [dict(r) for r in conn.execute("SELECT account_id, ledger_total, bank_total, difference, status FROM reconciliation_report ORDER BY account_id")]
    finally:
        conn.close()
    for row in rows:
        for key in ["ledger_total","bank_total","difference"]:
            row[key] = round(float(row[key]), 2)
    passed = rows == expected
    return {"score":1.0 if passed else 0.0,"passed":passed,"checks":[{"name":"reconciliation_rows_match","passed":passed,"observed":rows,"expected":expected}],"diagnostics":"ok" if passed else "reconciliation mismatch","metrics":{"rows":len(rows)}}
