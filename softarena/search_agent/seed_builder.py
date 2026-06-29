from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

from softarena.search_agent.ale_toolize_loader import load_category_summary, load_toolize_review
from softarena.search_agent.demand_source_loader import load_demand_source_slice
from softarena.search_agent.research_client import ResearchClient, extract_json_object, extract_response_text
from softarena.search_agent.schemas import SELECTED_TOOLS, DiversityTask, SeedSpec, SourceEvidence


DEFAULT_QUERIES = [
    "official jq manual URL",
    "official SQLite command line shell documentation URL",
    "ripgrep GitHub README URL",
    "ShellCheck GitHub wiki URL",
]


def normalize_text_list(value: Any, *, fallback: list[str] | None = None, max_items: int = 8) -> list[str]:
    if value is None:
        items: list[Any] = []
    elif isinstance(value, str):
        raw = value.strip()
        if raw:
            parts = [part.strip(" -\t\r\n") for part in re_split_list_text(raw)]
            items = parts if len(parts) > 1 else [raw]
        else:
            items = []
    elif isinstance(value, list):
        if value and all(isinstance(item, str) and len(item) == 1 for item in value):
            joined = "".join(str(item) for item in value).strip()
            parts = [part.strip(" -\t\r\n") for part in re_split_list_text(joined)]
            items = parts if len(parts) > 1 else ([joined] if joined else [])
        else:
            items = value
    else:
        items = [value]

    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item).strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        out.append(text[:260])
        seen.add(key)
        if len(out) >= max_items:
            break
    return out or list(fallback or [])


def re_split_list_text(raw: str) -> list[str]:
    import re

    text = raw.strip()
    if not text:
        return []
    return [
        part.strip()
        for part in re.split(r"(?:\n+|;|\s+\|\s+|,\s+(?=[A-Z0-9a-z_./-]{3,}))", text)
        if part.strip()
    ]


def stable_id(prefix: str, text: str, length: int = 10) -> str:
    digest = hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:length]
    return f"{prefix}_{digest}"


class SearchAgentBuilder:
    def __init__(
        self,
        *,
        reports_dir: Path,
        demand_source: Path,
        selected_tools: list[str] | None = None,
        research_client: ResearchClient | None = None,
        offline: bool = False,
    ) -> None:
        self.reports_dir = reports_dir
        self.demand_source = demand_source
        self.selected_tools = selected_tools or list(SELECTED_TOOLS)
        self.research_client = research_client
        self.offline = offline
        self.research_provider_status: list[dict[str, Any]] = []
        self.llm_seed_synthesis_status: dict[str, Any] = {"attempted": False, "status": "skipped"}

    def build(self, *, target_count: int = 8) -> dict[str, Any]:
        self.research_provider_status = []
        self.llm_seed_synthesis_status = {"attempted": False, "status": "skipped"}
        category_summary = load_category_summary(self.reports_dir / "06_ale_and_tool_collection_category_counts.md")
        toolize_rows = load_toolize_review(
            self.reports_dir / "06_baseline_human_clean_manual_review.csv",
            self.selected_tools,
        )
        mother = load_demand_source_slice(self.demand_source)
        evidence = self._collect_evidence(toolize_rows=toolize_rows)
        seeds = self._build_seed_specs(
            target_count=target_count,
            category_summary=category_summary,
            toolize_rows=toolize_rows,
            mother=mother,
            evidence=evidence,
        )
        llm_refinement_status = self._light_refine_seed_titles(seeds)
        tasks = [self._seed_to_diversity_task(seed, idx) for idx, seed in enumerate(seeds)]
        return {
            "category_summary": category_summary,
            "toolize_rows": toolize_rows,
            "mother": mother,
            "evidence": evidence,
            "seeds": seeds,
            "diversity_tasks": tasks,
            "research_provider_status": self.research_provider_status,
            "llm_seed_synthesis_status": self.llm_seed_synthesis_status,
            "llm_refinement_status": llm_refinement_status,
            "readiness": self._readiness(seeds, tasks, evidence, llm_refinement_status),
        }

    def _collect_evidence(self, *, toolize_rows: list[dict[str, Any]]) -> list[SourceEvidence]:
        if self.offline or self.research_client is None:
            self.research_provider_status.append(
                {"provider": "responses_web_search", "attempted": False, "status": "skipped_offline"}
            )
            self.research_provider_status.append(
                {"provider": "anysearch", "attempted": False, "status": "skipped_offline"}
            )
            return self._offline_evidence(toolize_rows)
        evidence = self._collect_responses_web_evidence()
        anysearch_evidence = self._collect_anysearch_evidence()
        evidence.extend(anysearch_evidence)
        return evidence or self._offline_evidence(toolize_rows)

    def _collect_responses_web_evidence(self) -> list[SourceEvidence]:
        evidence: list[SourceEvidence] = []
        provider_errors: list[str] = []
        for idx, query in enumerate(DEFAULT_QUERIES, start=1):
            prompt = (
                "Use web search. Find the requested public source for a CLI/tool workflow. Return ONLY JSON with keys: "
                "title, url, source_type, summary, tool_hints. Query: "
                + query
            )
            try:
                payload = self.research_client.responses(prompt, web_search=True, max_output_tokens=1200)
                text = extract_response_text(payload)
                try:
                    data = extract_json_object(text)
                except Exception:
                    data = {"title": query, "url": "", "source_type": "web_search_summary", "summary": text, "tool_hints": []}
            except Exception as exc:
                data = {
                    "title": query,
                    "url": "",
                    "source_type": "web_search_degraded",
                    "summary": f"web search failed or timed out: {type(exc).__name__}: {str(exc)[:300]}",
                    "tool_hints": [],
                }
                provider_errors.append(data["summary"])
            evidence.append(
                SourceEvidence(
                    source_id=f"web_{idx:03d}",
                    query=query,
                    title=str(data.get("title") or query),
                    url=str(data.get("url") or ""),
                    source_type=str(data.get("source_type") or "web"),
                    summary=str(data.get("summary") or text)[:1600],
                    tool_hints=[str(x) for x in data.get("tool_hints", []) if str(x).strip()]
                    if isinstance(data.get("tool_hints"), list)
                    else [],
                )
            )
        ok_count = len([row for row in evidence if row.source_type != "web_search_degraded"])
        self.research_provider_status.append(
            {
                "provider": "responses_web_search",
                "attempted": True,
                "status": "ok" if ok_count else "degraded",
                "tool": os.environ.get("RESEARCH_WEB_SEARCH_TOOL", "web_search").strip() or "web_search",
                "fallback_tool": "web_search_preview",
                "queries": len(DEFAULT_QUERIES),
                "evidence_count": ok_count,
                "errors": provider_errors[:4],
            }
        )
        return evidence

    def _collect_anysearch_evidence(self) -> list[SourceEvidence]:
        command_text = os.environ.get("ANYSEARCH_COMMAND", "anysearch").strip()
        command = shlex.split(command_text) if command_text else ["anysearch"]
        if not command:
            command = ["anysearch"]
        binary = shutil.which(command[0])
        if not binary:
            self.research_provider_status.append(
                {
                    "provider": "anysearch",
                    "attempted": False,
                    "status": "not_installed",
                    "detail": "No anysearch skill/tool is discoverable in this Codex session; set ANYSEARCH_COMMAND when available.",
                }
            )
            return []

        evidence: list[SourceEvidence] = []
        errors: list[str] = []
        for idx, query in enumerate(DEFAULT_QUERIES, start=1):
            try:
                result = subprocess.run(
                    [binary, *command[1:], query],
                    text=True,
                    capture_output=True,
                    timeout=25,
                    check=False,
                )
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {str(exc)[:240]}")
                continue
            if result.returncode != 0:
                errors.append((result.stderr or result.stdout or f"exit {result.returncode}")[:240])
                continue
            stdout = result.stdout.strip()
            if not stdout:
                continue
            data: dict[str, Any]
            try:
                data = extract_json_object(stdout)
            except Exception:
                data = {"title": query, "url": "", "summary": stdout[:1600], "tool_hints": []}
            evidence.append(
                SourceEvidence(
                    source_id=f"anysearch_{idx:03d}",
                    query=query,
                    title=str(data.get("title") or query),
                    url=str(data.get("url") or ""),
                    source_type="anysearch",
                    summary=str(data.get("summary") or data.get("snippet") or stdout)[:1600],
                    tool_hints=[str(x) for x in data.get("tool_hints", []) if str(x).strip()]
                    if isinstance(data.get("tool_hints"), list)
                    else [],
                )
            )
        self.research_provider_status.append(
            {
                "provider": "anysearch",
                "attempted": True,
                "status": "ok" if evidence else "degraded",
                "command": command_text,
                "queries": len(DEFAULT_QUERIES),
                "evidence_count": len(evidence),
                "errors": errors[:4],
            }
        )
        return evidence

    def _offline_evidence(self, toolize_rows: list[dict[str, Any]]) -> list[SourceEvidence]:
        rows = toolize_rows[:4] or [{"package": "sqlite3", "readme_summary": "SQLite command line data repair and analysis"}]
        out: list[SourceEvidence] = []
        for idx, row in enumerate(rows, start=1):
            out.append(
                SourceEvidence(
                    source_id=f"local_{idx:03d}",
                    query="local ALE/toolize review row",
                    title=str(row.get("package") or row.get("baseline_id") or f"local-{idx}"),
                    url="",
                    source_type="ale_toolize_manual_review",
                    summary=str(row.get("readme_summary") or row.get("toolset_description") or ""),
                    tool_hints=list(row.get("matched_selected_tools") or []),
                )
            )
        return out

    def _build_seed_specs(
        self,
        *,
        target_count: int,
        category_summary: dict[str, Any],
        toolize_rows: list[dict[str, Any]],
        mother: dict[str, list[dict[str, Any]]],
        evidence: list[SourceEvidence],
    ) -> list[SeedSpec]:
        if not self.offline and self.research_client is not None:
            llm_seeds = self._llm_seed_specs(target_count, category_summary, toolize_rows, mother, evidence)
            if len(llm_seeds) >= target_count:
                return llm_seeds[:target_count]
            fallback = self._fallback_seed_specs(target_count, category_summary, mother, evidence)
            seen = {seed.seed_id for seed in llm_seeds}
            for seed in fallback:
                if len(llm_seeds) >= target_count:
                    break
                if seed.seed_id in seen:
                    continue
                llm_seeds.append(seed)
                seen.add(seed.seed_id)
            return llm_seeds[:target_count]
        fallback = self._fallback_seed_specs(target_count, category_summary, mother, evidence)
        self.llm_seed_synthesis_status = {"attempted": False, "status": "skipped_offline_or_no_client"}
        return fallback

    def _llm_seed_specs(
        self,
        target_count: int,
        category_summary: dict[str, Any],
        toolize_rows: list[dict[str, Any]],
        mother: dict[str, list[dict[str, Any]]],
        evidence: list[SourceEvidence],
    ) -> list[SeedSpec]:
        assert self.research_client is not None
        batch_size = max(1, min(3, int(os.environ.get("SEARCH_AGENT_LLM_BATCH_SIZE", "2"))))
        out: list[SeedSpec] = []
        errors: list[str] = []
        batches = 0
        self.llm_seed_synthesis_status = {
            "attempted": True,
            "status": "running",
            "requested": target_count,
            "batch_size": batch_size,
        }
        for start in range(0, target_count, batch_size):
            requested = min(batch_size, target_count - start)
            batches += 1
            try:
                rows = self._llm_seed_rows_batch(
                    start_index=start,
                    batch_count=requested,
                    category_summary=category_summary,
                    toolize_rows=toolize_rows,
                    mother=mother,
                    evidence=evidence,
                )
            except Exception as exc:
                errors.append(f"batch_{batches}: {type(exc).__name__}: {str(exc)[:280]}")
                continue
            for offset, row in enumerate(rows[:requested], start=1):
                if not isinstance(row, dict):
                    continue
                seed = self._llm_row_to_seed(
                    row=row,
                    fallback_index=start + offset,
                    evidence=evidence,
                )
                if seed.seed_id not in {item.seed_id for item in out}:
                    out.append(seed)
        status = "ok" if len(out) >= target_count else "partial" if out else "failed"
        self.llm_seed_synthesis_status = {
            "attempted": True,
            "status": status,
            "requested": target_count,
            "produced": len(out),
            "batches": batches,
            "batch_size": batch_size,
            "errors": errors[:8],
        }
        if errors and not out:
            print(f"[search_agent] LLM seed synthesis failed; using deterministic fallback: {errors[0]}")
        elif errors:
            print(f"[search_agent] LLM seed synthesis partially degraded: {errors[0]}")
        return out

    def _llm_seed_rows_batch(
        self,
        *,
        start_index: int,
        batch_count: int,
        category_summary: dict[str, Any],
        toolize_rows: list[dict[str, Any]],
        mother: dict[str, list[dict[str, Any]]],
        evidence: list[SourceEvidence],
    ) -> list[dict[str, Any]]:
        assert self.research_client is not None
        batch_tools = [self._tools_for_index(start_index + idx) for idx in range(batch_count)]
        tool_filter = {tool for group in batch_tools for tool in group}
        compact_cards = mother["real_need_cards"][start_index : start_index + 6] or mother["real_need_cards"][:6]
        compact_toolize = [
            row
            for row in toolize_rows
            if set(row.get("matched_selected_tools") or []) & tool_filter
        ][:6] or toolize_rows[:6]
        compact_evidence = [row.to_dict() for row in evidence[start_index : start_index + 4] or evidence[:4]]
        prompt = (
            "You are searchAgent. Build private diversity harness seed specs, not final SoftArena task packages. "
            "Return ONLY compact JSON {\"seeds\":[...]} with exactly "
            f"{batch_count} seeds. Each seed must include title, persona, real_demand, selected_tools, "
            "artifact_mix, evaluator_hints, failure_modes, subdomain, risk_focus, validation_metric. "
            "Use selected_tools only from these planned tool groups: "
            + json.dumps(batch_tools, ensure_ascii=False)
            + "\nReference selected tools universe: "
            + ", ".join(self.selected_tools)
            + "\nALE/toolize summary:\n"
            + json.dumps(category_summary, ensure_ascii=False)[:2200]
            + "\nToolize review rows:\n"
            + json.dumps(compact_toolize, ensure_ascii=False)[:4200]
            + "\nprivate demand-source cards:\n"
            + json.dumps(compact_cards, ensure_ascii=False)[:5200]
            + "\nSearch evidence:\n"
            + json.dumps(compact_evidence, ensure_ascii=False)[:3600]
        )
        payload = self.research_client.responses(prompt, web_search=False, max_output_tokens=2400)
        data = extract_json_object(extract_response_text(payload))
        rows = data.get("seeds", [])
        return rows if isinstance(rows, list) else []

    def _llm_row_to_seed(
        self,
        *,
        row: dict[str, Any],
        fallback_index: int,
        evidence: list[SourceEvidence],
    ) -> SeedSpec:
        out: list[SeedSpec] = []
        seed_text = json.dumps(row, ensure_ascii=False, sort_keys=True)
        requested_tools = [str(x) for x in row.get("selected_tools", [])]
        tools = [t for t in self.selected_tools if t in requested_tools]
        if not tools:
            tools = self._tools_for_index(fallback_index - 1)
        source_ids = [evidence[(fallback_index - 1) % len(evidence)].source_id] if evidence else []
        out.append(
            SeedSpec(
                seed_id=stable_id("search_seed", seed_text),
                title=str(row.get("title") or f"Tool-aligned seed {fallback_index}")[:180],
                domain="Computing & Mathematical Sciences",
                subdomain=str(row.get("subdomain") or "tool_aligned_cli_workflow"),
                persona=str(row.get("persona") or "software/data operator"),
                real_demand=str(row.get("real_demand") or "Build a verifiable local CLI workflow."),
                selected_tools=tools,
                artifact_mix=normalize_text_list(
                    row.get("artifact_mix"),
                    fallback=["report", "structured sidecar"],
                    max_items=8,
                ),
                workspace_seed={"material_policy": "offline_builder_seed", "requires_private_materials": False},
                evaluator_hints=normalize_text_list(
                    row.get("evaluator_hints"),
                    fallback=["final artifact exists", "computed values match deterministic checks"],
                    max_items=8,
                ),
                failure_modes=normalize_text_list(
                    row.get("failure_modes"),
                    fallback=["malformed input", "partial validation failure"],
                    max_items=8,
                ),
                ale_toolize_rationale="computing_math has high ALE task count and dominant Toolize baseline coverage",
                diversity_axes={
                    "risk_focus": row.get("risk_focus", "deterministic_validation"),
                    "validation_metric": row.get("validation_metric", "artifact_correctness"),
                },
                source_evidence_ids=source_ids,
                demand_source_refs={},
            )
        )
        return out[0]

    def _fallback_seed_specs(
        self,
        target_count: int,
        category_summary: dict[str, Any],
        mother: dict[str, list[dict[str, Any]]],
        evidence: list[SourceEvidence],
    ) -> list[SeedSpec]:
        cards = mother["real_need_cards"] or [{}]
        out: list[SeedSpec] = []
        for idx in range(target_count):
            card = cards[idx % len(cards)]
            tools = self._tools_for_index(idx)
            title = f"{tools[0]} aligned {card.get('domain') or 'computing'} seed"
            need = str(card.get("real_world_need") or card.get("scenario") or "Build a verifiable local CLI workflow.")
            evidence_id = evidence[idx % len(evidence)].source_id if evidence else ""
            out.append(
                SeedSpec(
                    seed_id=stable_id("search_seed", f"{idx}|{title}|{need}|{tools}"),
                    title=title,
                    domain="Computing & Mathematical Sciences",
                    subdomain=self._subdomain_for_tools(tools),
                    persona=str(card.get("user_role") or "software/data operator"),
                    real_demand=need,
                    selected_tools=tools,
                    artifact_mix=["workspace files", "deterministic report", "validation sidecar"],
                    workspace_seed={"material_policy": "offline_seed", "requires_private_materials": False},
                    evaluator_hints=[
                        "final artifact exists",
                        "computed values match hidden expected data",
                        "report references the tool-derived evidence",
                    ],
                    failure_modes=["malformed input", "missing field", "stale config", "partial lint failure"],
                    ale_toolize_rationale=str(category_summary.get("summary") or ""),
                    diversity_axes={"tool_family": tools[0], "validation_metric": "deterministic_artifact_check"},
                    source_evidence_ids=[evidence_id] if evidence_id else [],
                    demand_source_refs={"need_id": card.get("need_id"), "domain": card.get("domain")},
                )
            )
        return out

    def _light_refine_seed_titles(self, seeds: list[SeedSpec]) -> dict[str, Any]:
        if self.offline or self.research_client is None or not seeds:
            return {"attempted": False, "status": "skipped"}
        compact = [
            {
                "seed_id": seed.seed_id,
                "title": seed.title,
                "subdomain": seed.subdomain,
                "selected_tools": seed.selected_tools,
            }
            for seed in seeds[:8]
        ]
        prompt = (
            "Return ONLY compact JSON {\"renames\":[{\"seed_id\":\"...\",\"title\":\"...\"}]}. "
            "Improve these seed titles for benchmark task generation. Keep meaning and tools unchanged. "
            + json.dumps(compact, ensure_ascii=False)
        )
        try:
            payload = self.research_client.responses(prompt, web_search=False, max_output_tokens=900)
            data = extract_json_object(extract_response_text(payload))
            renames = data.get("renames", [])
            if not isinstance(renames, list):
                return {"attempted": True, "status": "invalid_json_shape"}
            by_id = {str(item.get("seed_id")): str(item.get("title")) for item in renames if isinstance(item, dict)}
            changed = 0
            for seed in seeds:
                title = by_id.get(seed.seed_id, "").strip()
                if title:
                    seed.title = title[:160]
                    changed += 1
            return {"attempted": True, "status": "ok", "changed": changed}
        except Exception as exc:
            return {"attempted": True, "status": "failed", "error": f"{type(exc).__name__}: {str(exc)[:300]}"}

    def _tools_for_index(self, idx: int) -> list[str]:
        families = [
            ["sqlite3"],
            ["jq"],
            ["ripgrep", "mawk"],
            ["shellcheck"],
            ["pylint"],
            ["cppcheck", "diffstat"],
            ["gcovr"],
            ["nginx", "apache2-utils"],
            ["node-js-yaml"],
        ]
        return families[idx % len(families)]

    def _subdomain_for_tools(self, tools: list[str]) -> str:
        if "sqlite3" in tools:
            return "sqlite_metric_repair"
        if "jq" in tools:
            return "json_config_transform"
        if "ripgrep" in tools:
            return "repo_text_forensics"
        if any(t in tools for t in ("shellcheck", "pylint", "cppcheck")):
            return "script_quality_fix"
        if "nginx" in tools:
            return "service_config_validation"
        return "cli_artifact_validation"

    def _seed_to_diversity_task(self, seed: SeedSpec, idx: int) -> DiversityTask:
        tool_text = ", ".join(seed.selected_tools)
        artifact_text = ", ".join(seed.artifact_mix[:8]) or "workspace files, evaluator rubric, validation report"
        failure_text = "; ".join(seed.failure_modes[:5]) or "generic, unverifiable output"
        validation_metric = str(seed.diversity_axes.get("validation_metric") or "deterministic artifact checks")
        seed_query = (
            f"请把这个 searchAgent seed 实体化成一个 private diversity harness 可消费的任务候选包。"
            f"主题/子域: {seed.subdomain}; 工具: {tool_text}; persona: {seed.persona}.\n"
            f"真实需求: {seed.real_demand}\n"
            f"目标产物类型: {artifact_text}\n"
            f"需要规避的失败模式: {failure_text}\n\n"
            "你必须通过 tool_calls 在当前工作目录落盘并验证，不能只写文字方案。"
            "至少创建这些文件:\n"
            "- workspace_seed/README.md: 初始 workspace 材料说明和约束\n"
            "- workspace_seed/materials.json: 小型可复现输入材料，禁止私有数据\n"
            "- candidate_task.json: 包含 task_id、title、objective、init_files、expected_artifacts、tool_requirements、deterministic_checks\n"
            "- evaluator_rubric.json: 至少 5 条确定性检查，包含命令或文件断言\n"
            "- validation_report.md: 说明你运行了哪些本地工具验证这些文件\n"
            f"- seed 指定的业务产物文件: {artifact_text}\n"
            "candidate_task.json 的 expected_artifacts 必须列出这些业务产物和核心候选包文件。"
            "evaluator_rubric.json 的 criteria 数组必须不少于 5 条，且至少 2 条是可运行命令检查。"
            "validation_report.md 不能写“待运行后填充”，必须包含你实际执行的命令、退出码和关键 stdout/stderr 摘要。"
            "如果创建 SQL/YAML/JSON/shell/python/cpp 文件，必须用对应本地工具做一次语法或结构检查。"
            f"验证指标必须覆盖: {validation_metric}. "
            f"请至少调用一次 {seed.selected_tools[0] if seed.selected_tools else 'shell'} 相关命令；"
            "如果该工具不适合当前 seed，也要用 run_shell 做 JSON/schema/文件存在性检查。"
            "最后只返回简短总结和已创建文件列表。"
        )
        objective = (
            f"基于 searchAgent seed 构建 Toolize/ALE 对齐任务候选包。真实需求: {seed.real_demand} "
            f"候选工具: {tool_text}. 必须通过工具调用生成 workspace_seed、candidate_task.json、"
            "evaluator_rubric.json 和 validation_report.md，并运行确定性验证命令。"
        )
        return DiversityTask(
            task_id=f"searchagent-{seed.seed_id}",
            title=seed.title,
            objective=objective,
            domain="computing_math",
            subdomain=seed.subdomain,
            subdomain_zh=seed.subdomain,
            language="zh",
            seed_query=seed_query,
            max_turns=5,
            thinking="medium",
            timeout_sec=600,
            executor_guardrail=(
                "这是 searchAgent 生成的离线 seed，不是最终任务包。执行器应把它扩展成多样化任务候选；"
                "不得要求私有材料，不得把联网搜索结果复制成长正文；需要保留来源 URL/标题和可验证产物口径。"
                "必须使用 write_file/run_shell/read_file/list_dir 等 tool_calls 落盘并验证任务候选包；"
                "纯文字回答不能视为完成。"
            ),
            final_checklist=seed.evaluator_hints or ["产物可落盘", "可确定性评分", "工具调用路径清晰"],
            task_tags=["search_agent_seed", "toolize_aligned", "ale_computing_math", *seed.selected_tools],
            question_style="research_seed_builder",
            question_style_hint="像真实 benchmark/environment 设计者在要求扩展 seed，而不是直接让执行器完成最终业务任务",
            recommended_finish_turns=[2, 3],
            min_tool_kinds=1,
            stretch_tool_kinds=min(4, max(2, len(seed.selected_tools) + 1)),
            min_action_modes=2,
            stretch_action_modes=4,
            require_web_materials=True,
            task_variant={
                "source": "softarena.search_agent",
                "seed_id": seed.seed_id,
                "selected_tools": seed.selected_tools,
                "artifact_mix": seed.artifact_mix,
                "failure_modes": seed.failure_modes,
                "diversity_axes": seed.diversity_axes,
                "source_evidence_ids": seed.source_evidence_ids,
                "demand_source_refs": seed.demand_source_refs,
            },
        )

    def _readiness(
        self,
        seeds: list[SeedSpec],
        tasks: list[DiversityTask],
        evidence: list[SourceEvidence],
        llm_refinement_status: dict[str, Any],
    ) -> dict[str, Any]:
        tool_coverage = sorted({tool for seed in seeds for tool in seed.selected_tools})
        non_degraded_evidence = [
            row for row in evidence if row.source_type != "web_search_degraded" and (row.url or row.summary)
        ]
        online_search_ok = True if self.offline else bool(non_degraded_evidence)
        provider_status = list(self.research_provider_status)
        min_tool_coverage = min(4, max(1, len(seeds)))
        return {
            "passed": bool(seeds and tasks and evidence and len(tool_coverage) >= min_tool_coverage and online_search_ok),
            "seed_count": len(seeds),
            "diversity_task_count": len(tasks),
            "evidence_count": len(evidence),
            "non_degraded_evidence_count": len(non_degraded_evidence),
            "min_tool_coverage": min_tool_coverage,
            "research_provider_status": provider_status,
            "llm_seed_synthesis_status": self.llm_seed_synthesis_status,
            "llm_refinement_status": llm_refinement_status,
            "tool_coverage": tool_coverage,
            "notes": [
                "searchAgent outputs seeds for private diversity harness, not final SoftArena task packages",
                "online mode uses Responses web_search with preview fallback; anysearch is used when an anysearch command/skill bridge is installed",
            ],
        }
