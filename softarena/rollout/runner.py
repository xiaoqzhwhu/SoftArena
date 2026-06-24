from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from typing import Any

from softarena.registry.envs import EnvSpec, load_entrypoint
from softarena.runtime.sqlite_tools import call_sqlite_tool


def load_tasks(env: EnvSpec, split: str) -> list[dict[str, Any]]:
    if split not in env.splits:
        raise ValueError(f"Env {env.env_id} has no split: {split}")
    task_path = env.path / env.splits[split]
    payload = json.loads(task_path.read_text())
    return list(payload["tasks"])


def run_episode(env: EnvSpec, task: dict[str, Any], model: str, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    init_fn = load_entrypoint(env, env.entrypoint["init"])
    verify_fn = load_entrypoint(env, env.entrypoint["verifier"])

    with tempfile.TemporaryDirectory(prefix="softarena_") as tmp:
        workspace = Path(tmp)
        episode = init_fn(task, workspace)
        start_time = time.time()
        steps = scripted_sqlite_policy(episode)
        verifier = verify_fn(episode)
        elapsed_ms = int((time.time() - start_time) * 1000)
        final_answer = "Created customer_revenue and idx_customer_revenue_customer_id."

        trajectory = {
            "episode_id": f"{env.env_id}:{task['task_id']}:seed0",
            "env_id": env.env_id,
            "env_version": env.version,
            "task_id": task["task_id"],
            "split": "smoke",
            "difficulty": task.get("difficulty", "unknown"),
            "model": {"name": model, "kind": "scripted"},
            "prompt": episode["prompt"],
            "messages": build_training_messages(episode["prompt"], steps, final_answer),
            "steps": steps,
            "final_answer": final_answer,
            "verifier": verifier,
            "elapsed_ms": elapsed_ms,
        }

        out_path = output_dir / f"{task['task_id']}.json"
        out_path.write_text(json.dumps(trajectory, indent=2, ensure_ascii=False) + "\n")
        return trajectory


def scripted_sqlite_policy(episode: dict[str, Any]) -> list[dict[str, Any]]:
    db_path = episode["db_path"]
    actions = [
        {
            "name": "sqlite_schema",
            "arguments": {"db_path": db_path},
            "rationale": "Inspect the existing database schema before changing state.",
        },
        {
            "name": "sqlite_exec",
            "arguments": {
                "db_path": db_path,
                "sql": (
                    "DROP TABLE IF EXISTS customer_revenue;"
                    "CREATE TABLE customer_revenue AS "
                    "SELECT customer_id, ROUND(SUM(quantity * unit_price), 2) AS total_revenue "
                    "FROM raw_orders WHERE status = 'paid' GROUP BY customer_id;"
                    "CREATE INDEX idx_customer_revenue_customer_id "
                    "ON customer_revenue(customer_id);"
                ),
            },
            "rationale": "Materialize the requested paid-order aggregate and create the required lookup index.",
        },
        {
            "name": "sqlite_query",
            "arguments": {
                "db_path": db_path,
                "sql": "SELECT customer_id, total_revenue FROM customer_revenue ORDER BY customer_id",
            },
            "rationale": "Query the final table in deterministic order to verify the state before answering.",
        },
    ]

    steps = []
    for index, action in enumerate(actions):
        started = time.time()
        observation = call_sqlite_tool(action["name"], action["arguments"])
        steps.append(
            {
                "index": index,
                "rationale": action["rationale"],
                "tool_call": action,
                "observation": observation,
                "latency_ms": int((time.time() - started) * 1000),
            }
        )
        if not observation.get("ok"):
            break
    return steps


def build_training_messages(prompt: str, steps: list[dict[str, Any]], final_answer: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "You are a software agent operating in SoftArena. Use the available tools to update "
                "the environment state. Provide concise, auditable rationales for tool choices."
            ),
        },
        {"role": "user", "content": prompt},
    ]
    for step in steps:
        call = step["tool_call"]
        messages.append(
            {
                "role": "assistant",
                "content": step["rationale"],
                "tool_calls": [
                    {
                        "name": call["name"],
                        "arguments": call["arguments"],
                    }
                ],
            }
        )
        messages.append(
            {
                "role": "tool",
                "name": call["name"],
                "content": step["observation"],
            }
        )
    messages.append({"role": "assistant", "content": final_answer})
    return messages
