from __future__ import annotations
import json
from pathlib import Path
from typing import Any

def create_episode(task: dict[str, Any], workspace: Path) -> dict[str, Any]:
    workspace.mkdir(parents=True, exist_ok=True)
    evidence_path = workspace / "network_evidence.json"; report_path = workspace / "diagnosis.json"; expected_path = workspace / "expected.json"
    evidence_path.write_text(json.dumps(task["evidence"], indent=2) + "\n")
    expected_path.write_text(json.dumps(task["expected"], indent=2) + "\n")
    return {"task_id":task["task_id"],"difficulty":task["difficulty"],"prompt":task["prompt"].format(evidence_path=str(evidence_path), report_path=str(report_path)),"workspace":str(workspace),"evidence_path":str(evidence_path),"report_path":str(report_path),"hidden":{"expected_path":str(expected_path)}}
