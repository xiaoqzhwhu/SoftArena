from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class EnvSpec:
    env_id: str
    domain: str
    version: int
    status: str
    path: Path
    tool_allowlist: list[str]
    splits: dict[str, str]
    entrypoint: dict[str, str]
    episode: dict[str, Any]
    tags: list[str]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def discover_envs(root: Path | None = None) -> list[EnvSpec]:
    root = root or repo_root()
    env_root = root / "softarena" / "envs"
    specs: list[EnvSpec] = []
    for env_file in env_root.glob("*/*/v*/env.json"):
        data = json.loads(env_file.read_text())
        specs.append(
            EnvSpec(
                env_id=data["env_id"],
                domain=data["domain"],
                version=int(data["version"]),
                status=data.get("status", "draft"),
                path=env_file.parent,
                tool_allowlist=list(data.get("tool_allowlist", [])),
                splits=dict(data.get("splits", {})),
                entrypoint=dict(data.get("entrypoint", {})),
                episode=dict(data.get("episode", {})),
                tags=list(data.get("tags", [])),
            )
        )
    return sorted(specs, key=lambda s: s.env_id)


def find_env(env_id: str, root: Path | None = None) -> EnvSpec:
    for spec in discover_envs(root):
        if spec.env_id == env_id:
            return spec
    raise KeyError(f"Unknown env_id: {env_id}")


def load_entrypoint(env: EnvSpec, ref: str) -> Callable[..., Any]:
    module_name, function_name = ref.split(":", 1)
    module_path = env.path / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(
        f"softarena_dynamic_{env.env_id.replace('.', '_')}_{module_name}",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, function_name)


def write_env_index(path: Path, root: Path | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    envs = []
    for spec in discover_envs(root):
        envs.append(
            {
                "env_id": spec.env_id,
                "path": str(spec.path.relative_to(root or repo_root())),
                "domain": spec.domain,
                "status": spec.status,
                "splits": sorted(spec.splits),
                "tags": spec.tags,
            }
        )
    path.write_text(json.dumps({"envs": envs}, indent=2, ensure_ascii=False) + "\n")
