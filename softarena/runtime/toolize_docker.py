from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from softarena.registry.tools import ToolSpec, find_tool
from softarena.runtime.base import ToolObservation


class DockerToolizeRuntime:
    """Toolize JSON-RPC 2.0 over Docker stdio runtime.

    Each call invokes a Toolize image using JSON-RPC over stdin/stdout. This is
    intentionally simple and robust for MVP validation. A later session runtime
    can keep containers warm behind the same call(tool_id, args) interface.
    """

    def __init__(
        self,
        workspace: Path | None = None,
        image_prefix: str | None = None,
        container_workspace: str = "/workspace",
        docker_bin: str = "docker",
    ):
        self.workspace = workspace.resolve() if workspace else None
        self.image_prefix = image_prefix or os.environ.get("SOFTARENA_TOOLIZE_IMAGE_PREFIX", "mass-toolize")
        self.container_workspace = container_workspace
        self.docker_bin = docker_bin

    def call(self, tool_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        started = time.time()
        spec = self._tool_spec(tool_id)
        image = self.resolve_image(spec)
        tool_name = spec.name
        mapped_args = self._map_paths(arguments)
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": mapped_args},
        }
        cmd = [self.docker_bin, "run", "--rm", "-i"]
        if self.workspace is not None:
            cmd += ["-v", f"{self.workspace}:{self.container_workspace}", "-w", self.container_workspace]
        cmd.append(image)
        try:
            result = subprocess.run(
                cmd,
                input=json.dumps(request),
                text=True,
                capture_output=True,
                timeout=spec.timeout_secs + 30,
                check=False,
            )
        except FileNotFoundError:
            return self._error(tool_id, image, started, "docker executable not found")
        except subprocess.TimeoutExpired as exc:
            return self._error(tool_id, image, started, f"docker call timed out: {exc}")

        parsed: Any | None = None
        stderr = result.stderr
        ok = result.returncode == 0
        content: Any = None
        if result.stdout.strip():
            try:
                parsed = json.loads(result.stdout)
                if isinstance(parsed, dict) and parsed.get("error"):
                    ok = False
                    stderr = stderr + json.dumps(parsed["error"], ensure_ascii=False)
                content = parsed.get("result") if isinstance(parsed, dict) else parsed
            except json.JSONDecodeError:
                ok = False
                stderr = stderr + "\nfailed to parse JSON-RPC response"
                content = result.stdout

        obs = ToolObservation(
            ok=ok,
            content=content,
            stdout=result.stdout,
            stderr=stderr,
            returncode=result.returncode,
            metadata={
                "backend": "toolize_docker",
                "tool_id": tool_id,
                "tool_name": tool_name,
                "image": image,
                "request": request,
                "duration_ms": int((time.time() - started) * 1000),
            },
        )
        return obs.to_dict()

    def list_tools(self, package: str) -> dict[str, Any]:
        image = f"{self.image_prefix}/{package}"
        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        cmd = [self.docker_bin, "run", "--rm", "-i", image]
        result = subprocess.run(cmd, input=json.dumps(request), text=True, capture_output=True, check=False)
        try:
            content = json.loads(result.stdout) if result.stdout.strip() else None
        except json.JSONDecodeError:
            content = result.stdout
        return ToolObservation(
            ok=result.returncode == 0,
            content=content,
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
            metadata={"backend": "toolize_docker", "image": image, "request": request},
        ).to_dict()

    def resolve_image(self, spec: ToolSpec) -> str:
        override_key = f"SOFTARENA_TOOLIZE_IMAGE_{spec.category}_{spec.package}".upper().replace("-", "_")
        if override_key in os.environ:
            return os.environ[override_key]
        return f"{self.image_prefix}/{spec.package}"

    def _tool_spec(self, tool_id: str) -> ToolSpec:
        try:
            return find_tool(tool_id)
        except KeyError:
            parts = tool_id.split("/")
            category = parts[0] if len(parts) > 0 else "unknown"
            package = parts[1] if len(parts) > 1 else category
            name = parts[-1]
            return ToolSpec(tool_id=tool_id, package=package, category=category, name=name, description="runtime alias", timeout_secs=300, schema={}, command=None, args=[])

    def _map_paths(self, value: Any) -> Any:
        if self.workspace is None:
            return value
        if isinstance(value, dict):
            return {k: self._map_paths(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._map_paths(v) for v in value]
        if isinstance(value, str):
            try:
                path = Path(value).resolve()
            except OSError:
                return value
            try:
                rel = path.relative_to(self.workspace)
            except ValueError:
                return value
            return str(Path(self.container_workspace) / rel)
        return value

    def _error(self, tool_id: str, image: str, started: float, message: str) -> dict[str, Any]:
        return ToolObservation(
            ok=False,
            stderr=message,
            returncode=1,
            metadata={"backend": "toolize_docker", "tool_id": tool_id, "image": image, "duration_ms": int((time.time() - started) * 1000)},
        ).to_dict()
