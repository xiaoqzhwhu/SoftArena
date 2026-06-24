from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def iter_trajectories(input_dir: Path):
    for path in sorted(input_dir.rglob("*.json")):
        yield path, json.loads(path.read_text())


def build_sft_dataset(input_dir: Path, output_path: Path, require_passed: bool = True) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    skipped = 0
    with output_path.open("w") as out:
        for path, trajectory in iter_trajectories(input_dir):
            verifier = trajectory.get("verifier", {})
            if require_passed and not verifier.get("passed", False):
                skipped += 1
                continue
            messages = trajectory.get("messages")
            if not messages:
                skipped += 1
                continue
            sample = {
                "sample_id": trajectory["episode_id"],
                "env_id": trajectory["env_id"],
                "task_id": trajectory["task_id"],
                "difficulty": trajectory.get("difficulty"),
                "score": verifier.get("score"),
                "messages": messages,
            }
            out.write(json.dumps(sample, ensure_ascii=False) + "\n")
            written += 1
    return {"written": written, "skipped": skipped, "output_path": str(output_path)}
