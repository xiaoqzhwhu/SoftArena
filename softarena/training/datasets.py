from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

SKIP_JSON_NAMES = {"manifest.json", "metrics.json", "train_manifest.json", "model_card.json"}


def iter_trajectories(input_path: Path) -> Iterable[tuple[str, dict[str, Any]]]:
    if input_path.is_file() and input_path.suffix == ".jsonl":
        for idx, line in enumerate(input_path.read_text().splitlines()):
            if line.strip():
                yield f"{input_path}:{idx}", json.loads(line)
        return
    if input_path.is_file():
        yield str(input_path), json.loads(input_path.read_text())
        return
    for path in sorted(input_path.rglob("*.json")):
        if path.name in SKIP_JSON_NAMES or path.name.endswith(".manifest.json"):
            continue
        yield str(path), json.loads(path.read_text())
    for path in sorted(input_path.rglob("*.jsonl")):
        for idx, line in enumerate(path.read_text().splitlines()):
            if line.strip():
                yield f"{path}:{idx}", json.loads(line)


def build_sft_dataset(input_dir: Path, output_path: Path, require_passed: bool = True) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    skipped = 0
    env_counts: dict[str, int] = {}
    seen_sample_ids: set[str] = set()
    with output_path.open("w") as out:
        for source, trajectory in iter_trajectories(input_dir):
            verifier = trajectory.get("verifier", {})
            if require_passed and not verifier.get("passed", False):
                skipped += 1
                continue
            messages = trajectory.get("messages")
            sample_id = trajectory.get("episode_id")
            if not messages or not sample_id:
                skipped += 1
                continue
            if sample_id in seen_sample_ids:
                skipped += 1
                continue
            seen_sample_ids.add(sample_id)
            sample = {
                "sample_id": sample_id,
                "source": source,
                "env_id": trajectory["env_id"],
                "task_id": trajectory["task_id"],
                "split": trajectory.get("split"),
                "difficulty": trajectory.get("difficulty"),
                "score": verifier.get("score"),
                "messages": messages,
            }
            out.write(json.dumps(sample, ensure_ascii=False) + "\n")
            written += 1
            env_counts[sample["env_id"]] = env_counts.get(sample["env_id"], 0) + 1
    manifest = {
        "kind": "sft",
        "input": str(input_dir),
        "output_path": str(output_path),
        "written": written,
        "skipped": skipped,
        "env_counts": env_counts,
        "require_passed": require_passed,
    }
    output_path.with_suffix(output_path.suffix + ".manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    )
    return manifest


def build_reward_dataset(input_dir: Path, output_path: Path) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    skipped = 0
    seen_sample_ids: set[str] = set()
    with output_path.open("w") as out:
        for source, trajectory in iter_trajectories(input_dir):
            sample_id = trajectory.get("episode_id")
            if not sample_id or sample_id in seen_sample_ids:
                skipped += 1
                continue
            seen_sample_ids.add(sample_id)
            verifier = trajectory.get("verifier", {})
            sample = {
                "sample_id": sample_id,
                "source": source,
                "env_id": trajectory.get("env_id"),
                "task_id": trajectory.get("task_id"),
                "score": float(verifier.get("score") or 0.0),
                "passed": bool(verifier.get("passed", False)),
                "num_steps": len(trajectory.get("steps", [])),
                "checks": verifier.get("checks", []),
            }
            out.write(json.dumps(sample, ensure_ascii=False) + "\n")
            written += 1
    manifest = {"kind": "reward", "input": str(input_dir), "output_path": str(output_path), "written": written, "skipped": skipped}
    output_path.with_suffix(output_path.suffix + ".manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    )
    return manifest
