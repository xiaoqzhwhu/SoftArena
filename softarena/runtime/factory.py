from __future__ import annotations

from pathlib import Path

from softarena.runtime.base import ToolRuntime
from softarena.runtime.toolize import LocalToolizeRuntime
from softarena.runtime.toolize_docker import DockerToolizeRuntime


def create_runtime(backend: str = "local", workspace: Path | None = None) -> ToolRuntime:
    if backend in {"local", "local_toolize"}:
        return LocalToolizeRuntime()
    if backend in {"docker", "toolize_docker"}:
        return DockerToolizeRuntime(workspace=workspace)
    raise ValueError(f"Unsupported runtime backend: {backend}")
