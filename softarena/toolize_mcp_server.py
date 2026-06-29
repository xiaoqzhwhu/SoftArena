from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable


SERVER_INFO = {"name": "softarena-toolize", "version": "0.1.0"}
PROTOCOL_VERSION = "2024-11-05"


def main() -> None:
    server = ToolizeMcpServer()
    server.run()


class ToolizeMcpServer:
    def __init__(self) -> None:
        self.tools: dict[str, tuple[dict[str, Any], Callable[[dict[str, Any]], dict[str, Any]]]] = {
            "sqlite_query": (
                _tool(
                    "sqlite_query",
                    "Run a read-only sqlite3 query and return JSON rows.",
                    {"db_path": "string", "sql": "string"},
                    ["db_path", "sql"],
                ),
                self.sqlite_query,
            ),
            "sqlite_exec": (
                _tool(
                    "sqlite_exec",
                    "Execute sqlite3 SQL statements against a workspace database.",
                    {"db_path": "string", "sql": "string"},
                    ["db_path", "sql"],
                ),
                self.sqlite_exec,
            ),
            "jq_filter": (
                _tool(
                    "jq_filter",
                    "Run jq against a JSON file or provided JSON string.",
                    {"filter": "string", "path": "string", "input_json": "string"},
                    ["filter"],
                ),
                self.jq_filter,
            ),
            "ripgrep_search": (
                _tool(
                    "ripgrep_search",
                    "Search workspace files with ripgrep.",
                    {"pattern": "string", "path": "string"},
                    ["pattern", "path"],
                ),
                self.ripgrep_search,
            ),
            "gawk_run": (
                _tool(
                    "gawk_run",
                    "Run gawk or mawk over a workspace file or provided text.",
                    {"program": "string", "path": "string", "input_text": "string"},
                    ["program"],
                ),
                self.gawk_run,
            ),
            "js_yaml_to_json": (
                _tool(
                    "js_yaml_to_json",
                    "Parse YAML with node js-yaml and return JSON.",
                    {"path": "string", "input_text": "string"},
                    [],
                ),
                self.js_yaml_to_json,
            ),
            "shellcheck_file": (
                _tool("shellcheck_file", "Run shellcheck on a shell script.", {"path": "string"}, ["path"]),
                self.shellcheck_file,
            ),
            "pylint_file": (
                _tool("pylint_file", "Run pylint syntax-error checks on a Python file.", {"path": "string"}, ["path"]),
                self.pylint_file,
            ),
            "cppcheck_file": (
                _tool("cppcheck_file", "Run cppcheck warning checks on a C/C++ file.", {"path": "string"}, ["path"]),
                self.cppcheck_file,
            ),
            "gcovr_version": (
                _tool("gcovr_version", "Return gcovr version information.", {}, []),
                self.gcovr_version,
            ),
            "apachebench_version": (
                _tool("apachebench_version", "Return apache2-utils ab version information.", {}, []),
                self.apachebench_version,
            ),
            "nginx_version": (
                _tool("nginx_version", "Return nginx version information.", {}, []),
                self.nginx_version,
            ),
            "diffstat_summary": (
                _tool("diffstat_summary", "Run diffstat over a patch file.", {"path": "string"}, ["path"]),
                self.diffstat_summary,
            ),
        }

    def run(self) -> None:
        for raw in sys.stdin:
            raw = raw.strip()
            if not raw:
                continue
            try:
                request = json.loads(raw)
                response = self.handle(request)
            except Exception as exc:
                response = _error(None, -32603, f"{type(exc).__name__}: {exc}")
            if response is not None:
                print(json.dumps(response, ensure_ascii=False), flush=True)

    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        method = request.get("method")
        request_id = request.get("id")
        if method == "initialize":
            return _result(
                request_id,
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": SERVER_INFO,
                },
            )
        if method == "notifications/initialized":
            return None
        if method == "tools/list":
            return _result(request_id, {"tools": [spec for spec, _handler in self.tools.values()]})
        if method == "tools/call":
            params = request.get("params") or {}
            name = str(params.get("name") or "")
            arguments = params.get("arguments") or {}
            if name not in self.tools:
                return _error(request_id, -32602, f"unknown tool: {name}")
            try:
                observation = self.tools[name][1](arguments)
                self._log_call(name, arguments, observation)
                return _result(
                    request_id,
                    {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(observation, ensure_ascii=False),
                            }
                        ],
                        "isError": not bool(observation.get("ok")),
                    },
                )
            except Exception as exc:
                observation = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
                self._log_call(name, arguments, observation)
                return _result(
                    request_id,
                    {
                        "content": [{"type": "text", "text": json.dumps(observation, ensure_ascii=False)}],
                        "isError": True,
                    },
                )
        if method in {"resources/list", "prompts/list"}:
            key = "resources" if method.startswith("resources/") else "prompts"
            return _result(request_id, {key: []})
        return _error(request_id, -32601, f"unsupported method: {method}")

    def sqlite_query(self, arguments: dict[str, Any]) -> dict[str, Any]:
        db_path = self._workspace_path(arguments["db_path"])
        sql = str(arguments.get("sql") or "")
        if not sql.lstrip().lower().startswith(("select", "pragma", "with")):
            return {"ok": False, "stderr": "sqlite_query only accepts SELECT/PRAGMA/WITH statements", "returncode": 2}
        result = self._run(["sqlite3", "-json", str(db_path), sql])
        rows: Any = []
        if result["stdout"].strip():
            try:
                rows = json.loads(result["stdout"])
            except json.JSONDecodeError:
                rows = result["stdout"]
        result["content"] = rows
        return result

    def sqlite_exec(self, arguments: dict[str, Any]) -> dict[str, Any]:
        db_path = self._workspace_path(arguments["db_path"])
        sql = str(arguments.get("sql") or "")
        return self._run(["sqlite3", str(db_path), sql])

    def jq_filter(self, arguments: dict[str, Any]) -> dict[str, Any]:
        jq_filter = str(arguments.get("filter") or ".")
        if arguments.get("path"):
            path = self._workspace_path(arguments["path"])
            return self._run(["jq", jq_filter, str(path)])
        return self._run(["jq", jq_filter], input_text=str(arguments.get("input_json") or ""))

    def ripgrep_search(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = self._workspace_path(arguments.get("path") or ".")
        return self._run(["rg", str(arguments["pattern"]), str(path)])

    def gawk_run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        binary = "gawk" if shutil.which("gawk") else "mawk"
        program = str(arguments["program"])
        if arguments.get("path"):
            path = self._workspace_path(arguments["path"])
            return self._run([binary, program, str(path)])
        return self._run([binary, program], input_text=str(arguments.get("input_text") or ""))

    def js_yaml_to_json(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if arguments.get("path"):
            path = self._workspace_path(arguments["path"])
            input_text = path.read_text(encoding="utf-8")
        else:
            input_text = str(arguments.get("input_text") or "")
        script = (
            "const yaml=require('js-yaml');"
            "const fs=require('fs');"
            "const input=fs.readFileSync(0,'utf8');"
            "console.log(JSON.stringify(yaml.load(input)));"
        )
        env = os.environ.copy()
        node_path = _global_node_path()
        if node_path:
            env["NODE_PATH"] = node_path
        return self._run(["node", "-e", script], input_text=input_text, env=env)

    def shellcheck_file(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._run(["shellcheck", str(self._workspace_path(arguments["path"]))])

    def pylint_file(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._run(["pylint", "--disable=all", "--enable=syntax-error", str(self._workspace_path(arguments["path"]))])

    def cppcheck_file(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._run(["cppcheck", "--enable=warning", str(self._workspace_path(arguments["path"]))])

    def gcovr_version(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._run(["gcovr", "--version"])

    def apachebench_version(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._run(["ab", "-V"])

    def nginx_version(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._run(["nginx", "-v"])

    def diffstat_summary(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._run(["diffstat", str(self._workspace_path(arguments["path"]))])

    def _workspace_path(self, value: str) -> Path:
        path = Path(value).expanduser()
        if not path.is_absolute():
            base = Path(os.environ.get("SOFTARENA_TOOLIZE_WORKSPACE") or os.getcwd())
            path = base / path
        path = path.resolve()
        workspace = os.environ.get("SOFTARENA_TOOLIZE_WORKSPACE")
        if workspace and not _is_relative_to(path, Path(workspace).resolve()):
            raise ValueError(f"path is outside SOFTARENA_TOOLIZE_WORKSPACE: {path}")
        return path

    def _run(
        self,
        cmd: list[str],
        *,
        input_text: str | None = None,
        env: dict[str, str] | None = None,
        timeout: int = 60,
    ) -> dict[str, Any]:
        binary = shutil.which(cmd[0])
        if not binary:
            return {"ok": False, "returncode": 127, "stdout": "", "stderr": f"missing executable: {cmd[0]}"}
        result = subprocess.run(
            [binary, *cmd[1:]],
            input=input_text,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=env,
        )
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout[-4000:],
            "stderr": result.stderr[-4000:],
        }

    def _log_call(self, name: str, arguments: dict[str, Any], observation: dict[str, Any]) -> None:
        log_path = os.environ.get("SOFTARENA_TOOLIZE_CALL_LOG")
        if not log_path:
            return
        path = Path(log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "server": SERVER_INFO["name"],
            "tool": name,
            "arguments": arguments,
            "observation": observation,
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _tool(name: str, description: str, properties: dict[str, str], required: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": {key: {"type": value} for key, value in properties.items()},
            "required": required,
        },
    }


def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _global_node_path() -> str:
    npm = shutil.which("npm")
    if not npm:
        return ""
    result = subprocess.run([npm, "root", "-g"], text=True, capture_output=True, timeout=5, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


if __name__ == "__main__":
    main()
