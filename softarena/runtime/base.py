from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolObservation:
    ok: bool
    content: Any | None = None
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "content": self.content,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "returncode": self.returncode,
            "metadata": self.metadata or {},
        }


class ToolRuntime(Protocol):
    def call(self, tool_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        ...
