from __future__ import annotations

import ast
import json
import tomllib
import warnings
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
    specs = scan_bin2mcp_tools(root)
    if specs:
        return specs
    return scan_baseline_tools(root)


def scan_bin2mcp_tools(root: Path | None = None) -> list[ToolSpec]:
    root = root or repo_root()
    bin2mcp = root / "toolize" / "bin2mcp"
    specs: list[ToolSpec] = []
    if not bin2mcp.exists():
        return specs

    for adapter_dir in sorted(p for p in bin2mcp.iterdir() if p.is_dir() and p.name.endswith("-mcp")):
        for tool in _discover_mcp_tools(adapter_dir):
            specs.append(
                ToolSpec(
                    tool_id=f"bin2mcp/{adapter_dir.name}/{tool['name']}",
                    package=adapter_dir.name,
                    category="bin2mcp",
                    name=tool["name"],
                    description=tool.get("description", ""),
                    timeout_secs=300,
                    schema=tool.get("schema", {}),
                    command=str(tool["server_path"].relative_to(root)),
                    args=[],
                )
            )
    return specs


def scan_baseline_tools(root: Path | None = None) -> list[ToolSpec]:
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


def _discover_mcp_tools(adapter_dir: Path) -> list[dict[str, Any]]:
    tools: dict[str, dict[str, Any]] = {}
    for py_file in sorted(adapter_dir.rglob("*.py")):
        if any(part in {"tests", "example_outputs", "test_fixtures", "build"} for part in py_file.parts):
            continue
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                tree = ast.parse(py_file.read_text(errors="ignore"))
        except SyntaxError:
            continue
        for tool in _tools_from_fastmcp_decorators(tree, py_file):
            tools.setdefault(tool["name"], tool)
        for tool in _tools_from_mcp_tool_objects(tree, py_file):
            tools.setdefault(tool["name"], tool)
    return sorted(tools.values(), key=lambda item: item["name"])


def _tools_from_fastmcp_decorators(tree: ast.AST, py_file: Path) -> list[dict[str, Any]]:
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            if isinstance(target, ast.Attribute) and target.attr == "tool":
                found.append(
                    {
                        "name": node.name,
                        "description": ast.get_docstring(node) or "",
                        "schema": _schema_from_function(node),
                        "server_path": py_file,
                    }
                )
    return found


def _tools_from_mcp_tool_objects(tree: ast.AST, py_file: Path) -> list[dict[str, Any]]:
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "Tool":
            continue
        data = {"name": "", "description": "", "schema": {}, "server_path": py_file}
        for keyword in node.keywords:
            if keyword.arg == "name":
                data["name"] = _literal_string(keyword.value)
            elif keyword.arg == "description":
                data["description"] = _literal_string(keyword.value)
            elif keyword.arg == "inputSchema":
                data["schema"] = _literal_value(keyword.value)
        if data["name"]:
            found.append(data)
    return found


def _schema_from_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required = []
    defaults = [None] * (len(node.args.args) - len(node.args.defaults)) + list(node.args.defaults)
    for arg, default in zip(node.args.args, defaults):
        if arg.arg in {"self", "ctx"}:
            continue
        properties[arg.arg] = {"type": _json_type_from_annotation(arg.annotation)}
        if default is None:
            required.append(arg.arg)
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _json_type_from_annotation(annotation: ast.expr | None) -> str:
    if isinstance(annotation, ast.Name):
        return {"str": "string", "int": "integer", "float": "number", "bool": "boolean"}.get(annotation.id, "string")
    return "string"


def _literal_string(node: ast.AST) -> str:
    value = _literal_value(node)
    return value if isinstance(value, str) else ""


def _literal_value(node: ast.AST) -> Any:
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        return {}


def find_tool(tool_id: str, root: Path | None = None) -> ToolSpec:
    for spec in scan_toolize_tools(root):
        if spec.tool_id == tool_id:
            return spec
    raise KeyError(f"Unknown tool_id: {tool_id}")


def write_tool_index(path: Path, root: Path | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tools = [spec.to_dict() for spec in scan_toolize_tools(root)]
    path.write_text(json.dumps({"tools": tools}, indent=2, ensure_ascii=False) + "\n")
