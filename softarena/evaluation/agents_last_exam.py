from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def run_agents_last_exam_probe(model: str, dataset_dir: Path | None, output_dir: Path) -> dict[str, Any]:
    """Create an explicit Agents' Last Exam report.

    This is intentionally not wired to SoftArena's internal environments. The
    official Agents' Last Exam task package/harness is external; until a local
    dataset_dir with a manifest is supplied, the run is marked blocked.
    """
    run_id = f"agents_last_exam_{_slug(model)}_{time.strftime('%Y%m%d_%H%M%S', time.gmtime())}"
    run_dir = output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    reason = None
    manifest: dict[str, Any] | None = None
    if dataset_dir is None:
        reason = "Agents' Last Exam dataset_dir was not provided. This command does not run SoftArena smoke tasks as a substitute."
    elif not dataset_dir.exists():
        reason = f"Agents' Last Exam dataset_dir does not exist: {dataset_dir}"
    else:
        manifest_path = dataset_dir / "manifest.json"
        if not manifest_path.exists():
            reason = f"Agents' Last Exam manifest.json not found under dataset_dir: {dataset_dir}"
        else:
            manifest = json.loads(manifest_path.read_text())
            reason = "Agents' Last Exam manifest was found, but the official harness adapter is not implemented for this manifest format yet."

    report = {
        "run_id": run_id,
        "benchmark": "agents_last_exam",
        "model": model,
        "status": "blocked",
        "error": reason,
        "dataset_dir": str(dataset_dir) if dataset_dir else None,
        "run_dir": str(run_dir),
        "episodes": 0,
        "passed": 0,
        "skipped": 0,
        "pass_rate": 0.0,
        "avg_score": 0.0,
        "manifest": manifest,
        "started_at": _now(),
        "finished_at": _now(),
    }
    (run_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return report


def _slug(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value).strip("_").lower()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
