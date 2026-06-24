from __future__ import annotations
import json, sqlite3
from pathlib import Path
from typing import Any

def create_episode(task: dict[str, Any], workspace: Path) -> dict[str, Any]:
    workspace.mkdir(parents=True, exist_ok=True)
    db_path = workspace / "accounting.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE ledger(account_id TEXT, amount REAL)")
        conn.execute("CREATE TABLE bank(account_id TEXT, amount REAL)")
        conn.executemany("INSERT INTO ledger VALUES (?, ?)", task["ledger"])
        conn.executemany("INSERT INTO bank VALUES (?, ?)", task["bank"])
        conn.commit()
    finally:
        conn.close()
    expected_path = workspace / "expected.json"
    expected_path.write_text(json.dumps(task["expected"], indent=2) + "\n")
    return {"task_id":task["task_id"],"difficulty":task["difficulty"],"prompt":task["prompt"].format(db_path=str(db_path)),"workspace":str(workspace),"db_path":str(db_path),"hidden":{"expected_path":str(expected_path)}}
