from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from softarena.registry.envs import find_env
from softarena.rollout.runner import load_tasks, run_episode


@dataclass(frozen=True)
class RolloutJob:
    job_id: str
    env_id: str
    split: str
    model: str
    policy: str
    seed_start: int
    max_tasks: int | None
    output_dir: Path
    runtime: str = "local"

    @classmethod
    def from_json(cls, path: Path) -> "RolloutJob":
        data = json.loads(path.read_text())
        return cls(
            job_id=data["job_id"],
            env_id=data["env_id"],
            split=data.get("split", "smoke"),
            model=data.get("model", "scripted-sqlite-v0"),
            policy=data.get("policy", "scripted_sqlite"),
            seed_start=int(data.get("seed_start", 0)),
            max_tasks=data.get("max_tasks"),
            output_dir=Path(data.get("output_dir", "runs/rollouts")),
            runtime=data.get("runtime", "local"),
        )


def run_rollout_job(job: RolloutJob) -> dict[str, Any]:
    env = find_env(job.env_id)
    tasks = load_tasks(env, job.split)
    if job.max_tasks is not None:
        tasks = tasks[: job.max_tasks]

    run_dir = job.output_dir / job.job_id
    episode_dir = run_dir / "episodes"
    episode_dir.mkdir(parents=True, exist_ok=True)
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    trajectories = []
    jsonl_path = run_dir / "trajectories.jsonl"
    with jsonl_path.open("w") as jsonl:
        for offset, task in enumerate(tasks):
            trajectory = run_episode(
                env=env,
                task=task,
                model=job.model,
                output_dir=episode_dir,
                split=job.split,
                seed=job.seed_start + offset,
                policy=job.policy,
                runtime_backend=job.runtime,
            )
            trajectories.append(trajectory)
            jsonl.write(json.dumps(trajectory, ensure_ascii=False) + "\n")

    passed = sum(1 for t in trajectories if t.get("verifier", {}).get("passed"))
    manifest = {
        "job_id": job.job_id,
        "env_id": job.env_id,
        "split": job.split,
        "model": job.model,
        "policy": job.policy,
        "runtime": job.runtime,
        "started_at": started_at,
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "episodes": len(trajectories),
        "passed": passed,
        "pass_rate": passed / len(trajectories) if trajectories else 0.0,
        "run_dir": str(run_dir),
        "episodes_dir": str(episode_dir),
        "trajectories_jsonl": str(jsonl_path),
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    return manifest
