from __future__ import annotations

import hashlib
import json
import mimetypes
import shutil
import sqlite3
import subprocess
import tarfile
import time
from pathlib import Path
from typing import Any

from softarena.registry.tools import ToolSpec, find_tool
from softarena.runtime.base import ToolObservation


class ToolizeRuntimeError(RuntimeError):
    pass


class LocalToolizeRuntime:
    """Execute Toolize-declared tools through local real binaries.

    This is the first concrete runtime backend. It reads Toolize ToolSpec metadata
    for validation/timeout, while executing stable local equivalents on macOS.
    A Docker/MCP backend can implement the same call(tool_id, args) interface.
    """

    def __init__(self, root: Path | None = None):
        self.root = root

    def call(self, tool_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        started = time.time()
        spec = self._tool_spec(tool_id)
        try:
            observation = self._dispatch(spec, arguments)
        except Exception as exc:  # keep trajectory serializable
            observation = ToolObservation(ok=False, stderr=str(exc), returncode=1, metadata={"tool_id": tool_id})
        data = observation.to_dict()
        data.setdefault("metadata", {})["tool_id"] = tool_id
        data["metadata"]["duration_ms"] = int((time.time() - started) * 1000)
        data["metadata"]["backend"] = "local_toolize"
        return data

    def _tool_spec(self, tool_id: str) -> ToolSpec:
        try:
            return find_tool(tool_id, self.root)
        except KeyError:
            # Some MVP tool ids are canonical planned ids before Toolize has an exact package config.
            return ToolSpec(tool_id=tool_id, package=tool_id.split('/')[1] if '/' in tool_id else tool_id, category=tool_id.split('/')[0], name=tool_id.rsplit('/', 1)[-1], description="synthetic local alias", timeout_secs=300, schema={}, command=None, args=[])

    def _dispatch(self, spec: ToolSpec, arguments: dict[str, Any]) -> ToolObservation:
        name = spec.name
        tool_id = spec.tool_id
        if name in {"sqlite_exec", "sqlite_query", "sqlite_schema", "sql_execute", "sql_describe", "sql_list_tables"}:
            return self._sqlite(name, arguments, spec.timeout_secs)
        if "tar" in tool_id or name in {"tar_extract", "decompress_file"}:
            return self._tar_extract(arguments)
        if "file" in tool_id or name in {"file_identify", "identify_file", "file_info"}:
            return self._file_identify(arguments)
        if "sha" in tool_id or "xxhash" in tool_id or name in {"sha256sum", "shasum", "checksum", "xxhash_compute"}:
            return self._sha256(arguments)
        if name == "openssl_hash":
            return self._openssl_hash(arguments)
        if name in {"make", "make_test", "run_build", "trace_build"} or "make" in tool_id or "bmake" in tool_id:
            return self._make(arguments, spec.timeout_secs)
        if name in {"cc", "gcc", "clang"}:
            return self._subprocess([name] + list(arguments.get("args", [])), arguments.get("cwd"), spec.timeout_secs)
        raise ToolizeRuntimeError(f"LocalToolizeRuntime does not support {tool_id}")

    def _sqlite(self, name: str, arguments: dict[str, Any], timeout: int) -> ToolObservation:
        db_path = arguments["db_path"]
        sql = arguments.get("sql") or arguments.get("query") or ""
        if name in {"sqlite_exec", "sql_execute"} and not sql.lstrip().lower().startswith(("select", "pragma", "with")):
            return self._subprocess(["sqlite3", db_path, sql], None, timeout)
        if name in {"sqlite_query", "sql_execute"}:
            result = subprocess.run(["sqlite3", "-json", db_path, sql], text=True, capture_output=True, timeout=timeout, check=False)
            content: Any = []
            if result.stdout.strip():
                content = json.loads(result.stdout)
            return ToolObservation(ok=result.returncode == 0, content=content, stdout=result.stdout, stderr=result.stderr, returncode=result.returncode)
        conn = sqlite3.connect(db_path); conn.row_factory = sqlite3.Row
        try:
            table_rows = conn.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
            tables = {}
            for row in table_rows:
                columns = [dict(col) for col in conn.execute(f"PRAGMA table_info({row['name']})").fetchall()]
                indexes = [dict(idx) for idx in conn.execute(f"PRAGMA index_list({row['name']})").fetchall()]
                tables[row["name"]] = {"create_sql": row["sql"], "columns": columns, "indexes": indexes}
            if name == "sql_list_tables":
                return ToolObservation(ok=True, content={"tables": sorted(tables)})
            return ToolObservation(ok=True, content={"tables": tables})
        finally:
            conn.close()

    def _tar_extract(self, arguments: dict[str, Any]) -> ToolObservation:
        archive_path = Path(arguments["archive_path"])
        output_dir = Path(arguments["output_dir"]); output_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive_path, "r:*") as tar:
            members = tar.getnames(); tar.extractall(output_dir)
        return ToolObservation(ok=True, content={"members": members})

    def _file_identify(self, arguments: dict[str, Any]) -> ToolObservation:
        path = Path(arguments["path"])
        if not shutil.which("file"):
            guessed = mimetypes.guess_type(path.name)[0]
            try:
                text = path.read_text(errors="strict")
                file_type = "ASCII text" if text.isascii() else "Unicode text"
            except UnicodeDecodeError:
                file_type = guessed or "application/octet-stream"
            return ToolObservation(ok=True, content={"file_type": file_type}, stdout=file_type + "\n")
        result = subprocess.run(["file", "-b", str(path)], text=True, capture_output=True, check=False)
        file_type = result.stdout.strip() or mimetypes.guess_type(path.name)[0] or "unknown"
        return ToolObservation(ok=result.returncode == 0, content={"file_type": file_type}, stdout=result.stdout, stderr=result.stderr, returncode=result.returncode)

    def _sha256(self, arguments: dict[str, Any]) -> ToolObservation:
        if "data" in arguments:
            digest = hashlib.sha256(str(arguments["data"]).encode()).hexdigest()
            return ToolObservation(ok=True, content={"sha256": digest, "hash": digest}, stdout=digest + "\n")
        path = Path(arguments["path"])
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return ToolObservation(ok=True, content={"sha256": digest, "hash": digest}, stdout=f"{digest}  {path}\n")

    def _openssl_hash(self, arguments: dict[str, Any]) -> ToolObservation:
        algorithm = arguments.get("algorithm", "sha256")
        data = arguments.get("data", "")
        if algorithm != "sha256":
            return ToolObservation(ok=False, stderr=f"unsupported local hash algorithm: {algorithm}", returncode=1)
        digest = hashlib.sha256(data.encode()).hexdigest()
        return ToolObservation(ok=True, content={"hash": digest, "algorithm": algorithm}, stdout=digest + "\n")

    def _make(self, arguments: dict[str, Any], timeout: int) -> ToolObservation:
        target = arguments.get("target", "test")
        cwd = arguments.get("cwd")
        return self._subprocess(["make", target], cwd, timeout)

    def _subprocess(self, cmd: list[str], cwd: str | None, timeout: int) -> ToolObservation:
        result = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, timeout=timeout, check=False)
        return ToolObservation(ok=result.returncode == 0, stdout=result.stdout, stderr=result.stderr, returncode=result.returncode)
