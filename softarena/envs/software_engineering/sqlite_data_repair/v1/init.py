from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


def create_episode(task: dict[str, Any], workspace: Path) -> dict[str, Any]:
    workspace.mkdir(parents=True, exist_ok=True)
    db_path = workspace / "orders.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE raw_orders (customer_id TEXT, status TEXT, quantity INTEGER, unit_price REAL)"
        )
        conn.executemany(
            "INSERT INTO raw_orders VALUES (?, ?, ?, ?)",
            task["orders"],
        )
        conn.commit()
    finally:
        conn.close()

    task_prompt = task["prompt"].format(db_path=str(db_path))
    hidden_path = workspace / "expected.json"
    hidden_path.write_text(json.dumps(task["expected_rows"], indent=2) + "\n")
    return {
        "task_id": task["task_id"],
        "difficulty": task["difficulty"],
        "prompt": task_prompt,
        "workspace": str(workspace),
        "db_path": str(db_path),
        "hidden": {
            "expected_rows_path": str(hidden_path)
        }
    }
