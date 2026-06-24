from __future__ import annotations

import importlib.util
import json
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any

from softarena.training.trainer import TrainingRecipe


def has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def render_message(message: dict[str, Any]) -> str:
    role = message.get("role", "unknown")
    content = message.get("content", "")
    chunks = [f"<{role}>\n{content}\n</{role}>"]
    for call in message.get("tool_calls", []) or []:
        chunks.append("<tool_call>\n" + json.dumps(call, ensure_ascii=False) + "\n</tool_call>")
    return "\n".join(chunks)


def split_prompt_response(messages: list[dict[str, Any]]) -> tuple[str, str]:
    if len(messages) < 2:
        return "", "\n".join(render_message(m) for m in messages)
    prompt_messages = messages[:2]
    response_messages = messages[2:]
    return (
        "\n".join(render_message(m) for m in prompt_messages),
        "\n".join(render_message(m) for m in response_messages),
    )


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def maybe_write_parquet(path: Path, rows: list[dict[str, Any]]) -> str | None:
    if not (has_module("pandas") and has_module("pyarrow")):
        return None
    import pandas as pd  # type: ignore

    parquet_path = path.with_suffix(".parquet")
    pd.DataFrame(rows).to_parquet(parquet_path, index=False)
    return str(parquet_path)


def build_verl_sft_rows(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for sample in samples:
        prompt, response = split_prompt_response(sample["messages"])
        rows.append(
            {
                "prompt": prompt,
                "response": response,
                "messages": json.dumps(sample["messages"], ensure_ascii=False),
                "sample_id": sample["sample_id"],
                "env_id": sample["env_id"],
                "task_id": sample["task_id"],
                "score": sample.get("score", 0.0),
            }
        )
    return rows


def build_verl_grpo_rows(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for sample in samples:
        prompt, _response = split_prompt_response(sample["messages"])
        rows.append(
            {
                "prompt": prompt,
                "data_source": sample["env_id"],
                "ability": "tool_use",
                "reward_model": {"style": "rule", "ground_truth": str(sample.get("score", 0.0))},
                "extra_info": {
                    "sample_id": sample["sample_id"],
                    "env_id": sample["env_id"],
                    "task_id": sample["task_id"],
                    "score": sample.get("score", 0.0),
                },
            }
        )
    return rows


def shell_join(parts: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in parts)


def build_sft_command(recipe: TrainingRecipe, train_file: str, run_dir: Path) -> list[str]:
    hp = recipe.hyperparameters
    return [
        "python3",
        "-m",
        "verl.trainer.fsdp_sft_trainer",
        f"data.train_files={train_file}",
        f"data.val_files={train_file}",
        "data.prompt_key=prompt",
        "data.response_key=response",
        f"model.partial_pretrain={recipe.base_model}",
        f"trainer.default_local_dir={run_dir}",
        f"trainer.project_name=SoftArena",
        f"trainer.experiment_name={recipe.recipe_id}",
        f"trainer.total_epochs={hp.get('epochs', 1)}",
        f"optim.lr={hp.get('learning_rate', 1e-5)}",
        f"data.micro_batch_size={hp.get('batch_size', 1)}",
    ]


def build_grpo_command(recipe: TrainingRecipe, train_file: str, run_dir: Path) -> list[str]:
    hp = recipe.hyperparameters
    return [
        "python3",
        "-m",
        "verl.trainer.main_ppo",
        "algorithm.adv_estimator=grpo",
        f"data.train_files={train_file}",
        f"data.val_files={train_file}",
        "data.prompt_key=prompt",
        f"actor_rollout_ref.model.path={recipe.base_model}",
        "custom_reward_function.path=softarena/training/verl_reward.py",
        "custom_reward_function.name=compute_score",
        f"trainer.default_local_dir={run_dir}",
        f"trainer.project_name=SoftArena",
        f"trainer.experiment_name={recipe.recipe_id}",
        f"trainer.total_epochs={hp.get('epochs', 1)}",
        f"actor_rollout_ref.actor.optim.lr={hp.get('learning_rate', 1e-6)}",
        f"data.train_batch_size={hp.get('batch_size', 8)}",
    ]


def run_verl_recipe(recipe: TrainingRecipe, execute: bool = False) -> dict[str, Any]:
    if recipe.method not in {"sft", "rft", "grpo"}:
        raise ValueError(f"Unsupported verl method: {recipe.method}")
    samples = load_jsonl(recipe.dataset)
    if not samples:
        raise ValueError(f"Dataset has no samples: {recipe.dataset}")

    run_id = f"{recipe.recipe_id}_{time.strftime('%Y%m%d_%H%M%S', time.gmtime())}"
    run_dir = recipe.output_dir / run_id
    data_dir = run_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    if recipe.method in {"sft", "rft"}:
        rows = build_verl_sft_rows(samples)
        data_jsonl = data_dir / "train_sft.jsonl"
        command_builder = build_sft_command
    else:
        rows = build_verl_grpo_rows(samples)
        data_jsonl = data_dir / "train_grpo.jsonl"
        command_builder = build_grpo_command

    write_jsonl(data_jsonl, rows)
    parquet_file = maybe_write_parquet(data_jsonl, rows)
    train_file = parquet_file or str(data_jsonl)
    command = command_builder(recipe, train_file, run_dir)
    launcher = run_dir / "launch_verl.sh"
    launcher.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + shell_join(command) + "\n")
    launcher.chmod(0o755)

    result: dict[str, Any] = {
        "run_id": run_id,
        "recipe_id": recipe.recipe_id,
        "method": recipe.method,
        "trainer": "verl",
        "base_model": recipe.base_model,
        "dataset": str(recipe.dataset),
        "run_dir": str(run_dir),
        "prepared_rows": len(rows),
        "train_file": train_file,
        "parquet_available": parquet_file is not None,
        "verl_available": has_module("verl"),
        "launcher": str(launcher),
        "command": command,
        "executed": False,
        "status": "prepared",
    }

    if execute:
        if not has_module("verl"):
            raise RuntimeError("trainer=verl requested with execute=true, but Python module 'verl' is not installed.")
        completed = subprocess.run(command, text=True, capture_output=True, check=False)
        (run_dir / "stdout.log").write_text(completed.stdout)
        (run_dir / "stderr.log").write_text(completed.stderr)
        result.update(
            {
                "executed": True,
                "returncode": completed.returncode,
                "status": "complete" if completed.returncode == 0 else "failed",
            }
        )
        if completed.returncode != 0:
            raise RuntimeError(f"verl trainer failed; see {run_dir / 'stderr.log'}")

    (run_dir / "train_manifest.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return result
