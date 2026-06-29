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
    specs = scan_baseline_tools(root)
    if specs:
        return specs
    return builtin_mvp_tools()


def builtin_mvp_tools() -> list[ToolSpec]:
    """Minimal local tool metadata for SoftArena smoke environments.

    Real Toolize metadata wins whenever `toolize/bin2mcp` or legacy baseline
    configs are present. These specs keep the repository self-testable before
    the large external Toolize corpus is installed.
    """
    specs = [
        _builtin_tool("postgresql-client-mcp", "sql_execute", "Execute SQL against a local database.", {"db_path": "string", "sql": "string"}, ["db_path", "sql"]),
        _builtin_tool("postgresql-client-mcp", "sql_describe", "Describe the local database schema.", {"db_path": "string"}, ["db_path"]),
        _builtin_tool("postgresql-client-mcp", "sql_list_tables", "List local database tables.", {"db_path": "string"}, ["db_path"]),
        _builtin_tool("postgresql-client-mcp", "sql_export_csv", "Export a SQL result set as CSV.", {"db_path": "string", "sql": "string", "output_path": "string"}, ["db_path", "sql", "output_path"]),
        _builtin_tool("bind9-dnsutils-mcp", "dns_lookup", "Resolve a domain name.", {"domain": "string"}, ["domain"]),
        _builtin_tool("bind9-dnsutils-mcp", "dns_reverse_lookup", "Resolve a reverse DNS name.", {"ip": "string"}, ["ip"]),
        _builtin_tool("bind9-dnsutils-mcp", "dns_set_server", "Select the DNS server used by later lookups.", {"server": "string"}, ["server"]),
        _builtin_tool("bind9-dnsutils-mcp", "dns_ping", "Probe DNS-related reachability for a domain.", {"domain": "string"}, ["domain"]),
        _builtin_tool("busybox-mcp", "decompress_file", "Extract an archive into an output directory.", {"archive_path": "string", "output_dir": "string"}, ["archive_path", "output_dir"]),
        _builtin_tool("busybox-mcp", "file_info", "Return basic metadata for a file.", {"path": "string"}, ["path"]),
        _builtin_tool("busybox-mcp", "checksum", "Compute a file checksum.", {"path": "string"}, ["path"]),
        _builtin_tool("busybox-mcp", "write_file", "Write content to a file.", {"path": "string", "content": "string"}, ["path"]),
        _builtin_tool("busybox-mcp", "read_file", "Read a file.", {"path": "string"}, ["path"]),
        _builtin_tool("busybox-mcp", "search_files", "Search files under a path.", {"path": "string", "pattern": "string"}, ["path", "pattern"]),
        _builtin_tool("file-mcp", "identify_file", "Identify a file type.", {"path": "string"}, ["path"]),
        _builtin_tool("xxhash-mcp", "xxhash_compute", "Compute a digest for data.", {"data": "string", "algorithm": "string"}, ["data"]),
        _builtin_tool("ffjson-mcp", "generate_ffjson", "Generate filtered JSON output.", {"filter": "string"}, ["filter"]),
        _builtin_tool("bmake-mcp", "run_build", "Run a build target.", {"cwd": "string", "target": "string"}, ["cwd"]),
        _builtin_tool("bmake-mcp", "trace_build", "Trace a build target.", {"cwd": "string", "target": "string"}, ["cwd"]),
        _builtin_tool("bmake-mcp", "makefile_targets", "List Makefile targets.", {"cwd": "string"}, ["cwd"]),
        _builtin_tool("clang-mcp", "clang_compile", "Compile source files with clang.", {"cwd": "string", "args": "string"}, ["cwd"]),
        _builtin_tool("bear-mcp", "run_intercepted_build", "Run a build while recording compile commands.", {"cwd": "string", "target": "string"}, ["cwd"]),
        _builtin_tool("bear-mcp", "get_compile_commands", "Return compile commands for a project.", {"cwd": "string"}, ["cwd"]),
    ]
    return sorted(specs, key=lambda spec: spec.tool_id)


def _builtin_tool(
    package: str,
    name: str,
    description: str,
    properties: dict[str, str],
    required: list[str],
) -> ToolSpec:
    return ToolSpec(
        tool_id=f"bin2mcp/{package}/{name}",
        package=package,
        category="bin2mcp",
        name=name,
        description=description,
        timeout_secs=300,
        schema={
            "type": "object",
            "properties": {key: {"type": value} for key, value in properties.items()},
            "required": required,
        },
        command=None,
        args=[],
    )


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
