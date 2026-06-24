from __future__ import annotations
import hashlib, json, tarfile
from pathlib import Path
from typing import Any

def create_episode(task: dict[str, Any], workspace: Path) -> dict[str, Any]:
    workspace.mkdir(parents=True, exist_ok=True)
    source_dir = workspace / "source"
    source_dir.mkdir()
    evidence = source_dir / task["evidence_name"]
    evidence.write_text(task["evidence_content"])
    archive_path = workspace / "case.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tar:
        tar.add(evidence, arcname=task["evidence_name"])
    report_path = workspace / "report.json"
    expected_path = workspace / "expected.json"
    expected_path.write_text(json.dumps({"evidence_file": task["evidence_name"], "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(), "file_type_contains": task["expected_type"]}, indent=2) + "\n")
    return {"task_id": task["task_id"], "difficulty": task["difficulty"], "prompt": task["prompt"].format(archive_path=str(archive_path), report_path=str(report_path)), "workspace": str(workspace), "archive_path": str(archive_path), "extract_dir": str(workspace / "extracted"), "report_path": str(report_path), "hidden": {"expected_path": str(expected_path)}}
