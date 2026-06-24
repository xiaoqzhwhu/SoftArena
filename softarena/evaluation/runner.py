from __future__ import annotations

import csv
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from softarena.evaluation.model_clients import ModelClientError, OpenAIResponsesClient
from softarena.registry.envs import EnvSpec, discover_envs, find_env, load_entrypoint
from softarena.registry.tools import find_tool
from softarena.rollout.runner import build_training_messages, load_tasks, run_episode
from softarena.runtime.factory import create_runtime


@dataclass(frozen=True)
class EvalJob:
    suite_id: str
    model: str
    provider: str
    split: str
    env_ids: list[str]
    output_dir: Path
    runtime: str = "local"
    max_tasks_per_env: int | None = None
    seed_start: int = 0
    policy: str = "auto"
    max_steps: int | None = None
    temperature: float = 0.0

    @classmethod
    def from_json(cls, path: Path) -> "EvalJob":
        data = json.loads(path.read_text())
        env_ids = data.get("env_ids") or [env.env_id for env in discover_envs() if env.status == "active"]
        return cls(
            suite_id=data.get("suite_id", path.stem),
            model=data["model"],
            provider=data.get("provider", "scripted"),
            split=data.get("split", "smoke"),
            env_ids=list(env_ids),
            output_dir=Path(data.get("output_dir", "runs/eval")),
            runtime=data.get("runtime", "local"),
            max_tasks_per_env=data.get("max_tasks_per_env"),
            seed_start=int(data.get("seed_start", 0)),
            policy=data.get("policy", "auto"),
            max_steps=data.get("max_steps"),
            temperature=float(data.get("temperature", 0.0)),
        )


def run_eval_job(job: EvalJob) -> dict[str, Any]:
    run_id = f"{job.suite_id}_{_slug(job.model)}_{time.strftime('%Y%m%d_%H%M%S', time.gmtime())}"
    run_dir = job.output_dir / run_id
    episodes_dir = run_dir / "episodes"
    run_dir.mkdir(parents=True, exist_ok=True)
    episodes_dir.mkdir(parents=True, exist_ok=True)

    manifests = []
    trajectories = []
    started_at = _now()
    error: str | None = None

    for env_id in job.env_ids:
        env = find_env(env_id)
        tasks = load_tasks(env, job.split)
        if job.max_tasks_per_env is not None:
            tasks = tasks[: job.max_tasks_per_env]
        env_dir = episodes_dir / env.env_id / job.split
        env_dir.mkdir(parents=True, exist_ok=True)
        env_trajectories = []
        for offset, task in enumerate(tasks):
            try:
                if job.provider == "scripted":
                    trajectory = run_episode(
                        env=env,
                        task=task,
                        model=job.model,
                        output_dir=env_dir,
                        split=job.split,
                        seed=job.seed_start + offset,
                        policy=job.policy,
                        runtime_backend=job.runtime,
                    )
                elif job.provider == "openai":
                    trajectory = run_openai_episode(
                        env=env,
                        task=task,
                        model=job.model,
                        output_dir=env_dir,
                        split=job.split,
                        seed=job.seed_start + offset,
                        runtime_backend=job.runtime,
                        max_steps=job.max_steps,
                        temperature=job.temperature,
                    )
                else:
                    raise ValueError(f"Unsupported eval provider: {job.provider}")
            except ModelClientError as exc:
                error = str(exc)
                trajectory = _skipped_trajectory(env, task, job, job.seed_start + offset, error)
            env_trajectories.append(trajectory)
            trajectories.append(trajectory)
            if error and job.provider == "openai":
                break
        manifests.append(_summarize_env(env.env_id, env_trajectories))
        if error and job.provider == "openai":
            break

    jsonl_path = run_dir / "trajectories.jsonl"
    with jsonl_path.open("w") as f:
        for trajectory in trajectories:
            f.write(json.dumps(trajectory, ensure_ascii=False) + "\n")

    report = _summarize_suite(job, run_id, run_dir, started_at, manifests, trajectories, error)
    (run_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    _write_leaderboard_csv(run_dir / "leaderboard.csv", report)
    return report


def run_openai_episode(
    env: EnvSpec,
    task: dict[str, Any],
    model: str,
    output_dir: Path,
    split: str,
    seed: int,
    runtime_backend: str,
    max_steps: int | None,
    temperature: float,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    init_fn = load_entrypoint(env, env.entrypoint["init"])
    verify_fn = load_entrypoint(env, env.entrypoint["verifier"])
    step_limit = max_steps or int(env.episode.get("max_steps", 8))
    client = OpenAIResponsesClient(model=model)

    import tempfile

    with tempfile.TemporaryDirectory(prefix="softarena_eval_") as tmp:
        workspace = Path(tmp)
        episode = init_fn(task, workspace)
        runtime = create_runtime(runtime_backend, workspace=workspace)
        messages = _initial_openai_messages(env, episode)
        steps: list[dict[str, Any]] = []
        final_answer = ""
        started_at = time.time()

        for index in range(step_limit):
            response = client.complete(messages, temperature=temperature)
            action = _parse_action(response.text)
            if "final_answer" in action:
                final_answer = str(action["final_answer"])
                messages.append({"role": "assistant", "content": response.text})
                break
            tool_id = action.get("tool")
            arguments = action.get("arguments", {})
            rationale = str(action.get("rationale", ""))
            if not isinstance(tool_id, str) or tool_id not in env.tool_allowlist:
                observation = {"ok": False, "stderr": f"invalid or disallowed tool: {tool_id}", "content": None, "returncode": 1, "metadata": {}}
            elif not isinstance(arguments, dict):
                observation = {"ok": False, "stderr": "arguments must be an object", "content": None, "returncode": 1, "metadata": {}}
            else:
                observation = runtime.call(tool_id, arguments)
            step = {
                "index": index,
                "rationale": rationale,
                "tool_call": {"name": tool_id, "arguments": arguments},
                "observation": observation,
                "model_response": response.text,
                "model_latency_ms": response.latency_ms,
                "latency_ms": response.latency_ms,
            }
            steps.append(step)
            messages.append({"role": "assistant", "content": response.text})
            messages.append({"role": "tool", "name": str(tool_id), "content": observation})
        if not final_answer:
            final_answer = "Reached step limit."

        verifier = verify_fn(episode)
        trajectory = {
            "episode_id": f"{env.env_id}:{task['task_id']}:seed{seed}",
            "env_id": env.env_id,
            "env_version": env.version,
            "task_id": task["task_id"],
            "split": split,
            "seed": seed,
            "difficulty": task.get("difficulty", "unknown"),
            "model": {"name": model, "kind": "openai", "provider": "openai", "runtime": runtime_backend},
            "prompt": episode["prompt"],
            "messages": build_training_messages(episode["prompt"], steps, final_answer),
            "steps": steps,
            "final_answer": final_answer,
            "verifier": verifier,
            "elapsed_ms": int((time.time() - started_at) * 1000),
        }
        (output_dir / f"{task['task_id']}_seed{seed}.json").write_text(json.dumps(trajectory, indent=2, ensure_ascii=False) + "\n")
        return trajectory


def _initial_openai_messages(env: EnvSpec, episode: dict[str, Any]) -> list[dict[str, Any]]:
    tools = []
    for tool_id in env.tool_allowlist:
        spec = find_tool(tool_id)
        tools.append({"tool_id": spec.tool_id, "description": spec.description, "schema": spec.schema})
    return [
        {
            "role": "system",
            "content": (
                "You are an ALE-style software agent in SoftArena. Use only the listed tools. "
                "Respond with strict JSON only. For a tool call, return "
                "{\"rationale\": str, \"tool\": str, \"arguments\": object}. "
                "When done, return {\"final_answer\": str}. Do not reveal hidden verifier data."
            ),
        },
        {"role": "user", "content": json.dumps({"task": episode["prompt"], "available_tools": tools}, ensure_ascii=False)},
    ]


def _parse_action(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ModelClientError(f"model did not return valid JSON action: {text[:500]}") from exc


def _skipped_trajectory(env: EnvSpec, task: dict[str, Any], job: EvalJob, seed: int, reason: str) -> dict[str, Any]:
    return {
        "episode_id": f"{env.env_id}:{task['task_id']}:seed{seed}",
        "env_id": env.env_id,
        "env_version": env.version,
        "task_id": task["task_id"],
        "split": job.split,
        "seed": seed,
        "difficulty": task.get("difficulty", "unknown"),
        "model": {"name": job.model, "kind": job.provider, "provider": job.provider, "runtime": job.runtime},
        "prompt": task.get("prompt", ""),
        "messages": [],
        "steps": [],
        "final_answer": "",
        "verifier": {"score": 0.0, "passed": False, "checks": [], "diagnostics": reason, "metrics": {}, "skipped": True},
        "elapsed_ms": 0,
    }


def _summarize_env(env_id: str, trajectories: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [float(t.get("verifier", {}).get("score") or 0.0) for t in trajectories]
    passed = sum(1 for t in trajectories if t.get("verifier", {}).get("passed"))
    skipped = sum(1 for t in trajectories if t.get("verifier", {}).get("skipped"))
    return {
        "env_id": env_id,
        "episodes": len(trajectories),
        "passed": passed,
        "skipped": skipped,
        "pass_rate": round(passed / len(trajectories), 6) if trajectories else 0.0,
        "avg_score": round(sum(scores) / len(scores), 6) if scores else 0.0,
    }


def _summarize_suite(job: EvalJob, run_id: str, run_dir: Path, started_at: str, envs: list[dict[str, Any]], trajectories: list[dict[str, Any]], error: str | None) -> dict[str, Any]:
    episodes = len(trajectories)
    passed = sum(env["passed"] for env in envs)
    skipped = sum(env["skipped"] for env in envs)
    scores = [float(t.get("verifier", {}).get("score") or 0.0) for t in trajectories]
    status = "blocked" if error and skipped == episodes else "complete_with_skips" if skipped else "complete"
    return {
        "run_id": run_id,
        "suite_id": job.suite_id,
        "provider": job.provider,
        "model": job.model,
        "runtime": job.runtime,
        "split": job.split,
        "started_at": started_at,
        "finished_at": _now(),
        "status": status,
        "error": error,
        "run_dir": str(run_dir),
        "episodes": episodes,
        "passed": passed,
        "skipped": skipped,
        "pass_rate": round(passed / episodes, 6) if episodes else 0.0,
        "avg_score": round(sum(scores) / len(scores), 6) if scores else 0.0,
        "envs": envs,
    }


def _write_leaderboard_csv(path: Path, report: dict[str, Any]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["suite_id", "model", "provider", "runtime", "episodes", "passed", "skipped", "pass_rate", "avg_score", "status"])
        writer.writeheader()
        writer.writerow({key: report.get(key) for key in writer.fieldnames})


def _slug(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value).strip("_").lower()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
