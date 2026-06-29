from __future__ import annotations

import json
import os
import signal
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class ClaudeCodeRunConfig:
    harness_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("SOFTARENA_EXECUTOR_HARNESS_DIR", "/opt/softarena/claudecode_harness"))
    )
    config_path: Path = field(
        default_factory=lambda: Path(os.environ.get("SOFTARENA_EXECUTOR_CONFIG", "/opt/softarena/configs/executor.toml"))
    )
    timeout_sec: int = 120
    effort: str = "max"
    output_format: str = "stream-json"
    permission_mode: str = "bypassPermissions"
    allowed_tools: str = "Bash(*),Read,Write,Edit,MultiEdit,Glob,Grep,TodoWrite"
    run_as_user: str = "softarena"
    mcp_config_path: Path | None = None
    strict_mcp_config: bool = False


def run_claudecode_episode(
    *,
    episode: dict[str, Any],
    output_dir: Path,
    config: ClaudeCodeRunConfig | None = None,
    prompt_override: str | None = None,
    completion_check: Callable[[], dict[str, Any]] | None = None,
    completion_poll_sec: float = 2.0,
) -> dict[str, Any]:
    cfg = config or ClaudeCodeRunConfig()
    output_dir.mkdir(parents=True, exist_ok=True)
    workspace = Path(episode["workspace"])
    prompt = str(prompt_override if prompt_override is not None else episode["prompt"])
    report_path = output_dir / "claudecode_report.json"
    stream_path = output_dir / "session_stream.jsonl"
    stderr_path = output_dir / "stderr.log"
    toolize_call_log = output_dir / "toolize_calls.jsonl"

    if not shutil.which("claude"):
        report = {
            "status": "blocked",
            "reason": "claude_cli_missing",
            "workspace": str(workspace),
            "prompt_chars": len(prompt),
            "harness_dir": str(cfg.harness_dir),
            "created_at": _now(),
        }
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        return report

    harness = cfg.harness_dir / "scripts" / "run_claudecode_harness.sh"
    if not harness.exists():
        report = {
            "status": "blocked",
            "reason": "harness_script_missing",
            "harness": str(harness),
            "created_at": _now(),
        }
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        return report

    env = os.environ.copy()
    executor_config_env = os.environ.get("SOFTARENA_EXECUTOR_CONFIG_ENV", "SOFTARENA_EXECUTOR_CONFIG_FILE")
    env[executor_config_env] = str(cfg.config_path)
    env["CLAUDECODE_RAW_CALL_OUTPUT"] = str(output_dir / "raw_calls")
    env["SOFTARENA_TOOLIZE_WORKSPACE"] = str(workspace)
    env["SOFTARENA_TOOLIZE_CALL_LOG"] = str(toolize_call_log)
    mcp_config_path = cfg.mcp_config_path or _write_toolize_mcp_config(output_dir, workspace, toolize_call_log)
    supports_effort = _claude_supports_option("--effort")
    cmd = [
        str(harness),
        str(workspace),
        "-p",
        "--verbose",
        "--output-format",
        cfg.output_format,
        "--permission-mode",
        cfg.permission_mode,
        "--allowedTools",
        cfg.allowed_tools,
        "--mcp-config",
        str(mcp_config_path),
        "--append-system-prompt",
        (
            "Operate only inside the current SoftArena workspace. This is an execution benchmark, not a chat task. "
            "You must use tools to inspect and modify the workspace artifact requested by the user. "
            "Do not invent an unrelated task, game, or explanation. Stop only after the requested artifact exists."
        ),
        prompt,
    ]
    if cfg.strict_mcp_config:
        insert_at = cmd.index("--append-system-prompt")
        cmd[insert_at:insert_at] = ["--strict-mcp-config"]
    if supports_effort:
        cmd[-1:-1] = ["--effort", cfg.effort]
    if cfg.run_as_user:
        _chown_for_user(cfg.run_as_user, workspace, output_dir)
        sudo_env = [
            "env",
            f"PATH={env.get('PATH', '')}",
            f"{executor_config_env}={env[executor_config_env]}",
            f"CLAUDECODE_RAW_CALL_OUTPUT={env['CLAUDECODE_RAW_CALL_OUTPUT']}",
            f"SOFTARENA_TOOLIZE_WORKSPACE={env['SOFTARENA_TOOLIZE_WORKSPACE']}",
            f"SOFTARENA_TOOLIZE_CALL_LOG={env['SOFTARENA_TOOLIZE_CALL_LOG']}",
        ]
        cmd = ["sudo", "-H", "-u", cfg.run_as_user, *sudo_env, *cmd]
    started = time.time()
    completion_report: dict[str, Any] | None = None
    with stream_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(cfg.harness_dir),
                env=env,
                text=True,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
            deadline = started + cfg.timeout_sec
            error = ""
            while True:
                returncode = proc.poll()
                if returncode is not None:
                    status = "completed" if returncode == 0 else "failed"
                    break
                if completion_check is not None:
                    try:
                        current = completion_check()
                    except Exception as exc:
                        current = {"passed": False, "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
                    if current.get("passed"):
                        completion_report = current
                        _terminate_process_group(proc, timeout=10)
                        returncode = 0
                        status = "completed_by_evaluator"
                        break
                if time.time() >= deadline:
                    _terminate_process_group(proc, timeout=10, force=True)
                    status = "timeout"
                    returncode = 124
                    error = f"Claude Code timed out after {cfg.timeout_sec} seconds"
                    break
                time.sleep(max(0.2, float(completion_poll_sec)))
        except Exception as exc:
            status = "failed"
            returncode = 1
            error = str(exc)
    report = {
        "status": status,
        "returncode": returncode,
        "error": error,
        "completion_check": completion_report,
        **_summarize_stream(stream_path),
        "workspace": str(workspace),
        "stream_jsonl": str(stream_path),
        "stderr": str(stderr_path),
        "mcp_config": str(mcp_config_path),
        "toolize_call_log": str(toolize_call_log),
        "toolize_call_count": _count_jsonl(toolize_call_log),
        "elapsed_ms": int((time.time() - started) * 1000),
        "created_at": _now(),
    }
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return report


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _write_toolize_mcp_config(output_dir: Path, workspace: Path, call_log: Path) -> Path:
    config_path = output_dir / "toolize_mcp_config.json"
    server_path = os.environ.get("SOFTARENA_TOOLIZE_MCP_SERVER", "/opt/softarena/toolize_mcp_server.py")
    config = {
        "mcpServers": {
            "toolize": {
                "command": "python3",
                "args": [server_path],
                "env": {
                    "SOFTARENA_TOOLIZE_WORKSPACE": str(workspace),
                    "SOFTARENA_TOOLIZE_CALL_LOG": str(call_log),
                },
            }
        }
    }
    config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n")
    return config_path


def _count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip())


def _claude_supports_option(option: str) -> bool:
    try:
        result = subprocess.run(["claude", "--help"], text=True, capture_output=True, timeout=10, check=False)
    except Exception:
        return False
    return option in (result.stdout + result.stderr)


def _chown_for_user(user: str, *paths: Path) -> None:
    existing = [str(path) for path in paths if path.exists()]
    if not existing:
        return
    subprocess.run(["chown", "-R", f"{user}:{user}", *existing], check=False)


def _terminate_process_group(proc: subprocess.Popen[str], *, timeout: int, force: bool = False) -> None:
    if proc.poll() is not None:
        return
    sig = signal.SIGKILL if force else signal.SIGTERM
    try:
        os.killpg(os.getpgid(proc.pid), sig)
    except ProcessLookupError:
        return
    except Exception:
        if force:
            proc.kill()
        else:
            proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            proc.kill()
        proc.wait(timeout=timeout)


def _summarize_stream(path: Path) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "api_error_status": None,
        "api_error_result": "",
        "stream_json_events": 0,
    }
    if not path.exists():
        return summary
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        raw = line.strip()
        if not raw.startswith("{"):
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        summary["stream_json_events"] = int(summary["stream_json_events"]) + 1
        if event.get("type") == "result" and event.get("is_error"):
            summary["api_error_status"] = event.get("api_error_status")
            summary["api_error_result"] = str(event.get("result") or "")[:600]
    return summary
