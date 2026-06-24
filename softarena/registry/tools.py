from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ToolSpec:
    tool_id: str
    package: str
    category: str
    name: str
    description: str
    timeout_secs: int
    schema: dict[str, Any]
    command: str | None
    args: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def scan_toolize_tools(root: Path | None = None) -> list[ToolSpec]:
    root = root or repo_root()
    baseline = root / "toolize" / "baseline"
    specs: list[ToolSpec] = []
    for config_path in baseline.glob("*/*/config.toml"):
        rel = config_path.relative_to(baseline)
        category = rel.parts[0]
        package = rel.parts[1]
        with config_path.open("rb") as f:
            config = tomllib.load(f)
        for tool in config.get("tools", []):
            if not isinstance(tool, dict) or "name" not in tool:
                continue
            name = tool["name"]
            exec_spec = tool.get("exec", {})
            specs.append(
                ToolSpec(
                    tool_id=f"{category}/{package}/{name}",
                    package=package,
                    category=category,
                    name=name,
                    description=tool.get("description", "").strip(),
                    timeout_secs=int(tool.get("timeout_secs", 300)),
                    schema=tool.get("params", {}),
                    command=exec_spec.get("command"),
                    args=list(exec_spec.get("args", [])),
                )
            )
    return specs


def find_tool(tool_id: str, root: Path | None = None) -> ToolSpec:
    for spec in scan_toolize_tools(root):
        if spec.tool_id == tool_id:
            return spec
    raise KeyError(f"Unknown tool_id: {tool_id}")


def write_tool_index(path: Path, root: Path | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tools = [spec.to_dict() for spec in scan_toolize_tools(root)]
    path.write_text(json.dumps({"tools": tools}, indent=2, ensure_ascii=False) + "\n")
