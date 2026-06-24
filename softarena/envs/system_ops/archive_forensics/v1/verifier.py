from __future__ import annotations
import json
from pathlib import Path
from typing import Any

def verify(episode: dict[str, Any]) -> dict[str, Any]:
    report_path = Path(episode["report_path"])
    expected = json.loads(Path(episode["hidden"]["expected_path"]).read_text())
    if not report_path.exists():
        return {"score": 0.0, "passed": False, "checks": [{"name":"report_exists", "passed":False}], "diagnostics":"missing report", "metrics": {}}
    report = json.loads(report_path.read_text())
    checks=[]; score=0.0
    for name, passed, weight in [("evidence_file", report.get("evidence_file") == expected["evidence_file"], 0.3), ("sha256", report.get("sha256") == expected["sha256"], 0.5), ("file_type", expected["file_type_contains"] in report.get("file_type", ""), 0.2)]:
        checks.append({"name": name, "passed": passed})
        if passed: score += weight
    return {"score": round(score, 4), "passed": score == 1.0, "checks": checks, "diagnostics": "ok" if score == 1.0 else "report mismatch", "metrics": {}}
