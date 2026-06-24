from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path
from typing import Any


class ToolRuntimeError(RuntimeError):
    pass


def call_sqlite_tool(tool_name: str, arguments: dict[str, Any], timeout_secs: int = 30) -> dict[str, Any]:
    if tool_name == "sqlite_exec":
        return _sqlite_exec(arguments, timeout_secs)
    if tool_name == "sqlite_query":
        return _sqlite_query(arguments, timeout_secs)
    if tool_name == "sqlite_schema":
        return _sqlite_schema(arguments)
    raise ToolRuntimeError(f"Unsupported local sqlite tool: {tool_name}")


def _sqlite_exec(arguments: dict[str, Any], timeout_secs: int) -> dict[str, Any]:
    db_path = arguments["db_path"]
    sql = arguments["sql"]
    result = subprocess.run(
        ["sqlite3", db_path, sql],
        text=True,
        capture_output=True,
        timeout=timeout_secs,
        check=False,
    )
    return {
        "ok": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
    }


def _sqlite_query(arguments: dict[str, Any], timeout_secs: int) -> dict[str, Any]:
    db_path = arguments["db_path"]
    sql = arguments["sql"]
    result = subprocess.run(
        ["sqlite3", "-json", db_path, sql],
        text=True,
        capture_output=True,
        timeout=timeout_secs,
        check=False,
    )
    payload: Any = []
    if result.stdout.strip():
        payload = json.loads(result.stdout)
    return {
        "ok": result.returncode == 0,
        "content": payload,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
    }


def _sqlite_schema(arguments: dict[str, Any]) -> dict[str, Any]:
    db_path = Path(arguments["db_path"])
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        table_rows = conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        tables = {}
        for row in table_rows:
            columns = [dict(col) for col in conn.execute(f"PRAGMA table_info({row['name']})").fetchall()]
            indexes = [dict(idx) for idx in conn.execute(f"PRAGMA index_list({row['name']})").fetchall()]
            tables[row["name"]] = {
                "create_sql": row["sql"],
                "columns": columns,
                "indexes": indexes,
            }
        return {"ok": True, "content": {"tables": tables}}
    finally:
        conn.close()
