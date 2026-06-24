from __future__ import annotations

import argparse
import json
from pathlib import Path

from softarena.registry.envs import discover_envs, find_env, write_env_index
from softarena.registry.tools import scan_toolize_tools, write_tool_index
from softarena.rollout.jobs import RolloutJob, run_rollout_job
from softarena.rollout.runner import load_tasks, run_episode
from softarena.training.datasets import build_reward_dataset, build_sft_dataset
from softarena.training.trainer import TrainingRecipe, list_training_runs, run_training_recipe


def main() -> None:
    parser = argparse.ArgumentParser(prog="softarena")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list-tools")
    subparsers.add_parser("list-envs")

    env_parser = subparsers.add_parser("env")
    env_subparsers = env_parser.add_subparsers(dest="env_command", required=True)
    env_subparsers.add_parser("discover")

    rollout_parser = subparsers.add_parser("rollout")
    rollout_subparsers = rollout_parser.add_subparsers(dest="rollout_command", required=True)
    run_parser = rollout_subparsers.add_parser("run")
    run_parser.add_argument("--env", required=True)
    run_parser.add_argument("--split", default="smoke")
    run_parser.add_argument("--model", default="scripted-sqlite-v0")
    run_parser.add_argument("--output-dir", default="runs/smoke")
    run_parser.add_argument("--seed", type=int, default=0)
    run_parser.add_argument("--policy", default="scripted_sqlite")
    batch_parser = rollout_subparsers.add_parser("batch")
    batch_parser.add_argument("--job", required=True)

    dataset_parser = subparsers.add_parser("dataset")
    dataset_subparsers = dataset_parser.add_subparsers(dest="dataset_command", required=True)
    build_parser = dataset_subparsers.add_parser("build")
    build_parser.add_argument("--input-dir", required=True)
    build_parser.add_argument("--output", required=True)
    build_parser.add_argument("--kind", choices=["sft", "reward"], default="sft")
    build_parser.add_argument("--include-failed", action="store_true")

    train_parser = subparsers.add_parser("train")
    train_subparsers = train_parser.add_subparsers(dest="train_command", required=True)
    train_run_parser = train_subparsers.add_parser("run")
    train_run_parser.add_argument("--recipe", required=True)
    train_list_parser = train_subparsers.add_parser("list")
    train_list_parser.add_argument("--models-dir", default="models")

    args = parser.parse_args()

    if args.command == "list-tools":
        tools = scan_toolize_tools()
        print(json.dumps({"count": len(tools), "tools": [t.to_dict() for t in tools]}, indent=2))
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
        manifest = run_rollout_job(RolloutJob.from_json(Path(args.job)))
        print(json.dumps(manifest, indent=2))
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
        result = run_training_recipe(TrainingRecipe.from_json(Path(args.recipe)))
        print(json.dumps(result, indent=2))
        return

    if args.command == "train" and args.train_command == "list":
        print(json.dumps({"runs": list_training_runs(Path(args.models_dir))}, indent=2))
        return


if __name__ == "__main__":
    main()
