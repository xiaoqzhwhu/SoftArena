from __future__ import annotations
import subprocess
from pathlib import Path
from typing import Any

def verify(episode: dict[str, Any]) -> dict[str, Any]:
    project = Path(episode["project_dir"])
    result = subprocess.run(["make", "test"], cwd=project, text=True, capture_output=True, check=False, timeout=30)
    passed = result.returncode == 0
    return {"score":1.0 if passed else 0.0,"passed":passed,"checks":[{"name":"make_test","passed":passed,"stdout":result.stdout,"stderr":result.stderr}],"diagnostics":"ok" if passed else "make test failed","metrics":{"returncode":result.returncode}}
