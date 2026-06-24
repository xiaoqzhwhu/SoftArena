from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TrainingRecipe:
    recipe_id: str
    method: str
    trainer: str
    base_model: str
    dataset: Path
    output_dir: Path
    hyperparameters: dict[str, Any]
    metadata: dict[str, Any]

    @classmethod
    def from_json(cls, path: Path) -> "TrainingRecipe":
        data = json.loads(path.read_text())
        return cls(
            recipe_id=data["recipe_id"],
            method=data.get("method", "sft"),
            trainer=data.get("trainer", "dry_run"),
            base_model=data.get("base_model", "unknown"),
            dataset=Path(data["dataset"]),
            output_dir=Path(data.get("output_dir", "models")),
            hyperparameters=dict(data.get("hyperparameters", {})),
            metadata=dict(data.get("metadata", {})),
        )


def run_training_recipe(recipe: TrainingRecipe, execute: bool = False) -> dict[str, Any]:
    if recipe.trainer == "verl":
        from softarena.training.adapters.verl import run_verl_recipe

        return run_verl_recipe(recipe, execute=execute)
    if recipe.trainer != "dry_run":
        raise ValueError(
            f"Unsupported trainer {recipe.trainer!r}. Supported trainers: dry_run, verl."
        )
    if recipe.method != "sft":
        raise ValueError(f"Unsupported training method for dry_run: {recipe.method}")
    return run_dry_sft(recipe)


def run_dry_sft(recipe: TrainingRecipe) -> dict[str, Any]:
    samples = [json.loads(line) for line in recipe.dataset.read_text().splitlines() if line.strip()]
    if not samples:
        raise ValueError(f"Dataset has no samples: {recipe.dataset}")

    dataset_bytes = recipe.dataset.read_bytes()
    dataset_sha = hashlib.sha256(dataset_bytes).hexdigest()
    run_id = f"{recipe.recipe_id}_{time.strftime('%Y%m%d_%H%M%S', time.gmtime())}"
    run_dir = recipe.output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    message_count = sum(len(sample.get("messages", [])) for sample in samples)
    tool_call_count = sum(
        1
        for sample in samples
        for message in sample.get("messages", [])
        if message.get("tool_calls")
    )
    avg_score = sum(float(sample.get("score") or 0.0) for sample in samples) / len(samples)

    metrics = {
        "num_samples": len(samples),
        "num_messages": message_count,
        "num_tool_call_messages": tool_call_count,
        "avg_score": round(avg_score, 6),
    }
    manifest = {
        "run_id": run_id,
        "recipe_id": recipe.recipe_id,
        "method": recipe.method,
        "trainer": recipe.trainer,
        "base_model": recipe.base_model,
        "dataset": str(recipe.dataset),
        "dataset_sha256": dataset_sha,
        "hyperparameters": recipe.hyperparameters,
        "metadata": recipe.metadata,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "run_dir": str(run_dir),
        "status": "dry_run_complete",
        "next_step": "Replace trainer=dry_run with a concrete SFT backend such as TRL/verl/LLaMA-Factory.",
    }
    model_card = {
        "model_id": run_id,
        "base_model": recipe.base_model,
        "training_data": str(recipe.dataset),
        "training_data_sha256": dataset_sha,
        "intended_use": "SoftArena tool-use policy warm start",
        "limitations": "Dry-run artifact; no model weights were updated.",
    }

    (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n")
    (run_dir / "train_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    (run_dir / "model_card.json").write_text(json.dumps(model_card, indent=2, ensure_ascii=False) + "\n")
    return {"manifest": manifest, "metrics": metrics}


def list_training_runs(models_dir: Path) -> list[dict[str, Any]]:
    runs = []
    for manifest_path in sorted(models_dir.glob("*/train_manifest.json")):
        runs.append(json.loads(manifest_path.read_text()))
    return runs
