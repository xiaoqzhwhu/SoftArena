from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


SELECTED_TOOLS = [
    "jq",
    "sqlite3",
    "ripgrep",
    "mawk",
    "node-js-yaml",
    "shellcheck",
    "pylint",
    "cppcheck",
    "gcovr",
    "apache2-utils",
    "nginx",
    "diffstat",
]


@dataclass
class SourceEvidence:
    source_id: str
    query: str
    title: str
    url: str
    source_type: str
    summary: str
    tool_hints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SeedSpec:
    seed_id: str
    title: str
    domain: str
    subdomain: str
    persona: str
    real_demand: str
    selected_tools: list[str]
    artifact_mix: list[str]
    workspace_seed: dict[str, Any]
    evaluator_hints: list[str]
    failure_modes: list[str]
    ale_toolize_rationale: str
    diversity_axes: dict[str, Any]
    source_evidence_ids: list[str]
    demand_source_refs: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DiversityTask:
    task_id: str
    title: str
    objective: str
    domain: str
    subdomain: str
    subdomain_zh: str
    language: str
    seed_query: str
    max_turns: int
    thinking: str
    timeout_sec: int
    executor_guardrail: str
    final_checklist: list[str]
    task_tags: list[str]
    question_style: str
    question_style_hint: str
    recommended_finish_turns: list[int]
    min_tool_kinds: int
    stretch_tool_kinds: int
    min_action_modes: int
    stretch_action_modes: int
    require_web_materials: bool
    task_variant: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
