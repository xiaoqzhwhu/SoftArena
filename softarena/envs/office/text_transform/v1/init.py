from __future__ import annotations
import csv, json
from pathlib import Path
from typing import Any

def create_episode(task: dict[str, Any], workspace: Path) -> dict[str, Any]:
    workspace.mkdir(parents=True, exist_ok=True)
    input_path = workspace / "contacts.csv"
    with input_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "name", "email", "status"])
        writer.writeheader(); writer.writerows(task["rows"])
    output_path = workspace / "active_contacts.jsonl"
    expected_path = workspace / "expected.json"
    expected_path.write_text(json.dumps(task["expected"], indent=2) + "\n")
    return {"task_id": task["task_id"], "difficulty": task["difficulty"], "prompt": task["prompt"].format(input_path=str(input_path), output_path=str(output_path)), "workspace": str(workspace), "input_path": str(input_path), "output_path": str(output_path), "hidden": {"expected_path": str(expected_path)}}
