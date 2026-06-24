from __future__ import annotations
import json
from pathlib import Path
from typing import Any

def verify(episode: dict[str, Any]) -> dict[str, Any]:
    report = Path(episode["report_path"])
    expected = json.loads(Path(episode["hidden"]["expected_path"]).read_text())
    if not report.exists():
        return {"score":0.0,"passed":False,"checks":[{"name":"report_exists","passed":False}],"diagnostics":"missing report","metrics":{}}
    observed = json.loads(report.read_text())
    checks=[]; score=0.0
    for field, weight in [("root_cause",0.6),("remediation",0.4)]:
        passed = observed.get(field) == expected[field]
        checks.append({"name":field,"passed":passed})
        if passed: score += weight
    return {"score":round(score,4),"passed":score==1.0,"checks":checks,"diagnostics":"ok" if score==1.0 else "diagnosis mismatch","metrics":{}}
