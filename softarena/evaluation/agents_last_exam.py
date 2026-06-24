from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any


DEFAULT_EXPERIMENT = """name: softarena_ale_dummy_smoke
agents:
  - configs/agents/dummy.yaml
environment: configs/environments/docker.yaml
tasks: selected_tasks/helloworld.txt
output:
  root: .logs/ale
concurrency: 1
wall_time_s: 600
cleanup_mode: delete
"""


def run_agents_last_exam(
    model: str,
    repo_dir: Path,
    output_dir: Path,
    experiment: Path | None = None,
    dry_run: bool = False,
    timeout_s: int = 3600,
) -> dict[str, Any]:
    """Run the official Agents' Last Exam harness and persist a SoftArena report."""
    run_id = f"agents_last_exam_{_slug(model)}_{time.strftime('%Y%m%d_%H%M%S', time.gmtime())}"
    run_dir = output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    started_at = _now()
    if not repo_dir.exists():
        return _write_report(
            run_dir,
            {
                "run_id": run_id,
                "benchmark": "agents_last_exam",
                "model": model,
                "status": "blocked",
                "error": f"Agents' Last Exam repo_dir does not exist: {repo_dir}",
                "repo_dir": str(repo_dir),
                "run_dir": str(run_dir),
                "started_at": started_at,
                "finished_at": _now(),
            },
        )

    exp_path = experiment or (repo_dir / "local_dummy_docker_exp.yaml")
    if experiment is None and not exp_path.exists():
        exp_path.write_text(DEFAULT_EXPERIMENT)

    cmd_exp_path = exp_path.name if exp_path.resolve().parent == repo_dir.resolve() else str(exp_path)
    cmd = ["uv", "run", "python", "-m", "ale_run", "run", cmd_exp_path]
    if dry_run:
        cmd.append("--dry-run")

    try:
        result = subprocess.run(
            cmd,
            cwd=repo_dir,
            text=True,
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
        status = "complete" if result.returncode == 0 else _blocked_status(result.stderr + result.stdout)
        error = None if result.returncode == 0 else _summarize_error(result.stderr + result.stdout)
    except FileNotFoundError as exc:
        result = None
        status = "blocked"
        error = f"Required executable not found: {exc.filename}"
    except subprocess.TimeoutExpired as exc:
        result = exc
        status = "timeout"
        error = f"ALE command timed out after {timeout_s}s"

    report = {
        "run_id": run_id,
        "benchmark": "agents_last_exam",
        "model": model,
        "status": status,
        "error": error,
        "repo_dir": str(repo_dir),
        "experiment": str(exp_path),
        "dry_run": dry_run,
        "command": cmd,
        "run_dir": str(run_dir),
        "episodes": _parse_units(result.stdout if isinstance(result, subprocess.CompletedProcess) else ""),
        "passed": _parse_completed(result.stdout if isinstance(result, subprocess.CompletedProcess) else ""),
        "pass_rate": 0.0,
        "avg_score": _parse_avg_score(result.stdout if isinstance(result, subprocess.CompletedProcess) else ""),
        "returncode": result.returncode if isinstance(result, subprocess.CompletedProcess) else None,
        "stdout_path": str(run_dir / "stdout.txt"),
        "stderr_path": str(run_dir / "stderr.txt"),
        "started_at": started_at,
        "finished_at": _now(),
    }
    if report["episodes"]:
        report["pass_rate"] = round(report["passed"] / report["episodes"], 6)

    stdout = result.stdout if isinstance(result, subprocess.CompletedProcess) else getattr(result, "stdout", "") or ""
    stderr = result.stderr if isinstance(result, subprocess.CompletedProcess) else getattr(result, "stderr", "") or ""
    (run_dir / "stdout.txt").write_text(stdout)
    (run_dir / "stderr.txt").write_text(stderr)
    return _write_report(run_dir, report)


def run_agents_last_exam_probe(model: str, dataset_dir: Path | None, output_dir: Path) -> dict[str, Any]:
    repo_dir = dataset_dir or Path("external/agents-last-exam")
    return run_agents_last_exam(model=model, repo_dir=repo_dir, output_dir=output_dir, dry_run=True)


def _write_report(run_dir: Path, report: dict[str, Any]) -> dict[str, Any]:
    report.setdefault("episodes", 0)
    report.setdefault("passed", 0)
    report.setdefault("pass_rate", 0.0)
    report.setdefault("avg_score", 0.0)
    (run_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return report


def _blocked_status(text: str) -> str:
    if "No such file or directory: 'docker'" in text or "docker" in text.lower():
        return "blocked"
    return "failed"


def _summarize_error(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in reversed(lines):
        if "FileNotFoundError" in line or "No such file or directory" in line:
            return line[-1000:]
    for line in reversed(lines):
        if "ERROR" in line or "failed" in line.lower():
            return line[-1000:]
    return lines[-1][-1000:] if lines else "ALE command failed"


def _parse_units(stdout: str) -> int:
    for line in stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("units ("):
            return int(stripped.split("units (", 1)[1].split(")", 1)[0])
    rows = _result_rows(stdout)
    return len(rows)


def _parse_completed(stdout: str) -> int:
    return sum(1 for row in _result_rows(stdout) if " completed " in f" {row} ")


def _parse_avg_score(stdout: str) -> float:
    scores = []
    for row in _result_rows(stdout):
        parts = row.split()
        for part in parts:
            try:
                value = float(part)
            except ValueError:
                continue
            if 0.0 <= value <= 1.0:
                scores.append(value)
                break
    return round(sum(scores) / len(scores), 6) if scores else 0.0


def _result_rows(stdout: str) -> list[str]:
    rows = []
    capture = False
    for line in stdout.splitlines():
        if line.startswith("agent") and "task" in line and "status" in line:
            capture = True
            continue
        if capture and set(line.strip()) == {"-"}:
            continue
        if capture and line.strip():
            rows.append(line)
    return rows


def _slug(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value).strip("_").lower()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
