from __future__ import annotations

import argparse
import json
from pathlib import Path

from softarena.registry.envs import discover_envs, find_env, validate_env_tools, write_env_index
from softarena.registry.tools import scan_toolize_tools, write_tool_index
from softarena.rollout.jobs import RolloutJob, run_rollout_job
from softarena.rollout.runner import load_tasks, run_episode
from softarena.training.datasets import build_reward_dataset, build_sft_dataset
from softarena.training.trainer import TrainingRecipe, list_training_runs, run_training_recipe
from softarena.runtime.factory import create_runtime
from softarena.doctor import run_doctor
from softarena.evaluation.runner import EvalJob, run_eval_job


def main() -> None:
    parser = argparse.ArgumentParser(prog="softarena")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list-tools")
    subparsers.add_parser("list-envs")
    subparsers.add_parser("doctor")

    tool_parser = subparsers.add_parser("tool")
    tool_subparsers = tool_parser.add_subparsers(dest="tool_command", required=True)
    tool_call_parser = tool_subparsers.add_parser("call")
    tool_call_parser.add_argument("--tool", required=True)
    tool_call_parser.add_argument("--args", default="{}")
    tool_call_parser.add_argument("--runtime", default="local", choices=["local", "local_toolize", "docker", "toolize_docker"])
    tool_call_parser.add_argument("--workspace")

    env_parser = subparsers.add_parser("env")
    env_subparsers = env_parser.add_subparsers(dest="env_command", required=True)
    env_subparsers.add_parser("discover")
    env_subparsers.add_parser("validate-tools")

    rollout_parser = subparsers.add_parser("rollout")
    rollout_subparsers = rollout_parser.add_subparsers(dest="rollout_command", required=True)
    run_parser = rollout_subparsers.add_parser("run")
    run_parser.add_argument("--env", required=True)
    run_parser.add_argument("--split", default="smoke")
    run_parser.add_argument("--model", default="scripted-sqlite-v0")
    run_parser.add_argument("--output-dir", default="runs/smoke")
    run_parser.add_argument("--seed", type=int, default=0)
    run_parser.add_argument("--policy", default="scripted_sqlite")
    run_parser.add_argument("--runtime", default="local", choices=["local", "local_toolize", "docker", "toolize_docker"])
    batch_parser = rollout_subparsers.add_parser("batch")
    batch_parser.add_argument("--job", required=True)
    batch_parser.add_argument("--runtime", choices=["local", "local_toolize", "docker", "toolize_docker"])

    dataset_parser = subparsers.add_parser("dataset")
    dataset_subparsers = dataset_parser.add_subparsers(dest="dataset_command", required=True)
    build_parser = dataset_subparsers.add_parser("build")
    build_parser.add_argument("--input-dir", required=True)
    build_parser.add_argument("--output", required=True)
    build_parser.add_argument("--kind", choices=["sft", "reward"], default="sft")
    build_parser.add_argument("--include-failed", action="store_true")

    eval_parser = subparsers.add_parser("eval")
    eval_subparsers = eval_parser.add_subparsers(dest="eval_command", required=True)
    eval_run_parser = eval_subparsers.add_parser("run")
    eval_run_parser.add_argument("--suite", required=True)
    eval_run_parser.add_argument("--provider", choices=["scripted", "openai"])
    eval_run_parser.add_argument("--model")
    eval_run_parser.add_argument("--runtime", choices=["local", "local_toolize", "docker", "toolize_docker"])
    eval_report_parser = eval_subparsers.add_parser("report")
    eval_report_parser.add_argument("--run-dir", required=True)

    train_parser = subparsers.add_parser("train")
    train_subparsers = train_parser.add_subparsers(dest="train_command", required=True)
    train_run_parser = train_subparsers.add_parser("run")
    train_run_parser.add_argument("--recipe", required=True)
    train_run_parser.add_argument("--execute", action="store_true")
    train_list_parser = train_subparsers.add_parser("list")
    train_list_parser.add_argument("--models-dir", default="models")

    args = parser.parse_args()

    if args.command == "list-tools":
        tools = scan_toolize_tools()
        print(json.dumps({"count": len(tools), "tools": [t.to_dict() for t in tools]}, indent=2))
        return

    if args.command == "doctor":
        print(json.dumps(run_doctor(), indent=2))
        return

    if args.command == "tool" and args.tool_command == "call":
        arguments = json.loads(args.args)
        workspace = Path(args.workspace) if args.workspace else None
        print(json.dumps(create_runtime(args.runtime, workspace=workspace).call(args.tool, arguments), indent=2, ensure_ascii=False))
        return

    if args.command == "list-envs":
        envs = discover_envs()
        print(
            json.dumps(
                {
                    "count": len(envs),
                    "envs": [
                        {
                            "env_id": e.env_id,
                            "domain": e.domain,
                            "status": e.status,
                            "path": str(e.path),
                            "splits": sorted(e.splits),
                        }
                        for e in envs
                    ],
                },
                indent=2,
            )
        )
        return

    if args.command == "env" and args.env_command == "discover":
        write_env_index(Path("softarena/registry/env_index.generated.json"))
        write_tool_index(Path("softarena/registry/tool_index.generated.json"))
        print("wrote softarena/registry/env_index.generated.json")
        print("wrote softarena/registry/tool_index.generated.json")
        return

    if args.command == "env" and args.env_command == "validate-tools":
        result = validate_env_tools()
        print(json.dumps(result, indent=2))
        if not result["passed"]:
            raise SystemExit(1)
        return

    if args.command == "rollout" and args.rollout_command == "run":
        env = find_env(args.env)
        tasks = load_tasks(env, args.split)
        output_dir = Path(args.output_dir) / env.env_id / args.split
        trajectories = [
            run_episode(
                env,
                task,
                args.model,
                output_dir,
                split=args.split,
                seed=args.seed + index,
                policy=args.policy,
                runtime_backend=args.runtime,
            )
            for index, task in enumerate(tasks)
        ]
        passed = sum(1 for t in trajectories if t["verifier"]["passed"])
        print(
            json.dumps(
                {
                    "env_id": env.env_id,
                    "split": args.split,
                    "episodes": len(trajectories),
                    "passed": passed,
                    "output_dir": str(output_dir),
                },
                indent=2,
            )
        )
        return

    if args.command == "rollout" and args.rollout_command == "batch":
        job = RolloutJob.from_json(Path(args.job))
        if args.runtime:
            job = RolloutJob(
                job_id=job.job_id,
                env_id=job.env_id,
                split=job.split,
                model=job.model,
                policy=job.policy,
                seed_start=job.seed_start,
                max_tasks=job.max_tasks,
                output_dir=job.output_dir,
                runtime=args.runtime,
            )
        manifest = run_rollout_job(job)
        print(json.dumps(manifest, indent=2))
        return

    if args.command == "eval" and args.eval_command == "run":
        job = EvalJob.from_json(Path(args.suite))
        if args.provider or args.model or args.runtime:
            job = EvalJob(
                suite_id=job.suite_id,
                model=args.model or job.model,
                provider=args.provider or job.provider,
                split=job.split,
                env_ids=job.env_ids,
                output_dir=job.output_dir,
                runtime=args.runtime or job.runtime,
                max_tasks_per_env=job.max_tasks_per_env,
                seed_start=job.seed_start,
                policy=job.policy,
                max_steps=job.max_steps,
                temperature=job.temperature,
            )
        print(json.dumps(run_eval_job(job), indent=2, ensure_ascii=False))
        return

    if args.command == "eval" and args.eval_command == "report":
        report_path = Path(args.run_dir) / "report.json"
        print(report_path.read_text())
        return

    if args.command == "dataset" and args.dataset_command == "build":
        if args.kind == "sft":
            result = build_sft_dataset(
                input_dir=Path(args.input_dir),
                output_path=Path(args.output),
                require_passed=not args.include_failed,
            )
        else:
            result = build_reward_dataset(
                input_dir=Path(args.input_dir),
                output_path=Path(args.output),
            )
        print(json.dumps(result, indent=2))
        return

    if args.command == "train" and args.train_command == "run":
        result = run_training_recipe(TrainingRecipe.from_json(Path(args.recipe)), execute=args.execute)
        print(json.dumps(result, indent=2))
        return

    if args.command == "train" and args.train_command == "list":
        print(json.dumps({"runs": list_training_runs(Path(args.models_dir))}, indent=2))
        return


if __name__ == "__main__":
    main()
