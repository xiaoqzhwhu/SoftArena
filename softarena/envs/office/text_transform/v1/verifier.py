from __future__ import annotations
import json
from pathlib import Path
from typing import Any

def verify(episode: dict[str, Any]) -> dict[str, Any]:
    output = Path(episode["output_path"])
    expected = json.loads(Path(episode["hidden"]["expected_path"]).read_text())
    if not output.exists():
        return {"score":0.0,"passed":False,"checks":[{"name":"output_exists","passed":False}],"diagnostics":"missing output","metrics":{}}
    observed = [json.loads(line) for line in output.read_text().splitlines() if line.strip()]
    passed = observed == expected
    return {"score":1.0 if passed else 0.0,"passed":passed,"checks":[{"name":"semantic_jsonl_match","passed":passed,"observed":observed,"expected":expected}],"diagnostics":"ok" if passed else "semantic diff mismatch","metrics":{"rows":len(observed)}}
