from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


def create_episode(task: dict[str, Any], workspace: Path) -> dict[str, Any]:
    workspace.mkdir(parents=True, exist_ok=True)
    materials = task["materials"]
    db_path = workspace / "tool_seed.db"
    materials_path = workspace / "materials.json"
    materials_path.write_text(json.dumps(materials, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE seed_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE artifact_requirements (artifact TEXT PRIMARY KEY, source_name TEXT, description TEXT)"
        )
        conn.execute(
            "CREATE TABLE selected_tools (tool TEXT PRIMARY KEY, requirement TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE failure_modes (failure_id TEXT PRIMARY KEY, description TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE validation_checks (check_id TEXT PRIMARY KEY, description TEXT NOT NULL)"
        )
        conn.executemany(
            "INSERT INTO seed_metadata VALUES (?, ?)",
            [
                ("source_task_id", task.get("source_task_id", "")),
                ("title", task.get("title", "")),
                ("privacy", materials.get("privacy", "synthetic_only_no_private_data")),
            ],
        )
        conn.executemany(
            "INSERT INTO artifact_requirements VALUES (:artifact, :source_name, :description)",
            materials["artifact_requirements"],
        )
        conn.executemany(
            "INSERT INTO selected_tools VALUES (?, ?)",
            [(tool, "required") for tool in materials.get("selected_tools", [])],
        )
        conn.executemany(
            "INSERT INTO failure_modes VALUES (?, ?)",
            [(f"F{idx:03d}", value) for idx, value in enumerate(materials.get("failure_modes", []), start=1)],
        )
        conn.executemany(
            "INSERT INTO validation_checks VALUES (?, ?)",
            [
                ("C001", "candidate package contains all expected artifacts"),
                ("C002", materials.get("validation_metric", "deterministic artifact checks")),
                ("C003", "validation report records local tool execution"),
                ("C004", "materials are synthetic and reproducible"),
                ("C005", "evaluator rubric has at least five deterministic checks"),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    expected_path = workspace / "expected.json"
    expected = {
        "required_artifacts": task["expected_artifacts"],
        "expected_counts": task["expected_counts"],
    }
    expected_path.write_text(json.dumps(expected, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return {
        "task_id": task["task_id"],
        "difficulty": task["difficulty"],
        "prompt": task["prompt"].format(db_path=str(db_path)),
        "workspace": str(workspace),
        "db_path": str(db_path),
        "materials_path": str(materials_path),
        "hidden": {"expected_path": str(expected_path)},
    }
