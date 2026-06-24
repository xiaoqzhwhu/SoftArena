from __future__ import annotations

import json
import py_compile
import time
from pathlib import Path
from typing import Any

from softarena.registry.envs import discover_envs
from softarena.registry.tools import scan_toolize_tools
from softarena.rollout.jobs import RolloutJob, run_rollout_job
from softarena.training.datasets import build_reward_dataset, build_sft_dataset
from softarena.training.trainer import TrainingRecipe, run_training_recipe


class DoctorError(RuntimeError):
    pass


def compile_sources(root: Path) -> dict[str, Any]:
    files = sorted(root.rglob("*.py"))
    failures = []
    for path in files:
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            failures.append({"path": str(path), "error": str(exc)})
    return {"files": len(files), "failures": failures, "passed": not failures}


def run_doctor() -> dict[str, Any]:
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    report: dict[str, Any] = {"started_at": started, "checks": {}}

    compile_result = compile_sources(Path("softarena"))
    report["checks"]["compile"] = compile_result
    if not compile_result["passed"]:
        raise DoctorError(json.dumps(report, indent=2))

    envs = discover_envs()
    tools = scan_toolize_tools()
    report["checks"]["registry"] = {
        "env_count": len(envs),
        "tool_count": len(tools),
        "active_env_ids": [e.env_id for e in envs if e.status == "active"],
        "has_sqlite_env": any(e.env_id == "software_engineering.sqlite_data_repair.v1" for e in envs),
    }

    rollout_manifests = []
    for job_path in sorted(Path("configs/rollout").glob("*_smoke.json")):
        rollout_manifests.append(run_rollout_job(RolloutJob.from_json(job_path)))
    report["checks"]["rollout"] = {
        "jobs": rollout_manifests,
        "episodes": sum(item["episodes"] for item in rollout_manifests),
        "passed": sum(item["passed"] for item in rollout_manifests),
    }
    if report["checks"]["rollout"]["passed"] != report["checks"]["rollout"]["episodes"]:
        raise DoctorError(json.dumps(report, indent=2))

    trajectories = Path("runs/rollouts")
    sft_manifest = build_sft_dataset(
        input_dir=trajectories,
        output_path=Path("datasets/sft/sqlite_smoke.jsonl"),
        require_passed=True,
    )
    reward_manifest = build_reward_dataset(
        input_dir=trajectories,
        output_path=Path("datasets/reward/sqlite_smoke.jsonl"),
    )
    report["checks"]["datasets"] = {"sft": sft_manifest, "reward": reward_manifest}
    if sft_manifest["written"] < 1 or reward_manifest["written"] < 1:
        raise DoctorError(json.dumps(report, indent=2))

    dry_run = run_training_recipe(TrainingRecipe.from_json(Path("configs/training/sft_sqlite_smoke.json")))
    verl_sft = run_training_recipe(TrainingRecipe.from_json(Path("configs/training/verl_sft_sqlite_smoke.json")))
    verl_grpo = run_training_recipe(TrainingRecipe.from_json(Path("configs/training/verl_grpo_sqlite_smoke.json")))
    report["checks"]["training"] = {
        "dry_run": dry_run,
        "verl_sft_prepare": verl_sft,
        "verl_grpo_prepare": verl_grpo,
    }

    report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    report["passed"] = True
    Path("runs/doctor").mkdir(parents=True, exist_ok=True)
    Path("runs/doctor/latest.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return report
