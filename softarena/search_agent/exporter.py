from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def export_seed_library(output_dir: Path, bundle: dict[str, Any]) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence_rows = [row.to_dict() for row in bundle["evidence"]]
    seed_rows = [row.to_dict() for row in bundle["seeds"]]
    task_rows = [row.to_dict() for row in bundle["diversity_tasks"]]

    write_jsonl(output_dir / "source_evidence_index.jsonl", evidence_rows)
    write_jsonl(output_dir / "tool_aligned_need_cards.jsonl", seed_rows)
    write_jsonl(output_dir / "environment_seed_specs.jsonl", seed_rows)
    write_jsonl(
        output_dir / "artifact_blueprints.jsonl",
        [{"seed_id": row["seed_id"], "artifact_mix": row["artifact_mix"], "workspace_seed": row["workspace_seed"]} for row in seed_rows],
    )
    write_jsonl(
        output_dir / "failure_events.jsonl",
        [{"seed_id": row["seed_id"], "failure_modes": row["failure_modes"]} for row in seed_rows],
    )
    write_jsonl(
        output_dir / "evaluator_rubric_seeds.jsonl",
        [{"seed_id": row["seed_id"], "evaluator_hints": row["evaluator_hints"]} for row in seed_rows],
    )
    (output_dir / "diversity_axes.json").write_text(
        json.dumps(
            {
                "selected_tools": sorted({tool for row in seed_rows for tool in row["selected_tools"]}),
                "subdomains": sorted({row["subdomain"] for row in seed_rows}),
                "axes": [row["diversity_axes"] for row in seed_rows],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "research_provider_status.json").write_text(
        json.dumps(
            {
                "providers": bundle.get("research_provider_status", []),
                "llm_seed_synthesis_status": bundle.get("llm_seed_synthesis_status", {}),
                "llm_refinement_status": bundle.get("llm_refinement_status", {}),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    diversity_payload = {
        "task_set_id": "softarena_search_agent_seed_v0",
        "source": "softarena.search_agent",
        "adapter": "generic_dynamic_task_source",
        "tasks": task_rows,
        "metadata": {
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "seed_count": len(seed_rows),
            "purpose": "Seeds for a private diversity harness; not final SoftArena tasks.",
        },
    }
    (output_dir / "diversity_tasks.json").write_text(json.dumps(diversity_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output_dir / "readiness.json").write_text(json.dumps(bundle["readiness"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output_dir / "search_report.md").write_text(_search_report(bundle), encoding="utf-8")
    return {
        "output_dir": str(output_dir),
        "diversity_tasks": str(output_dir / "diversity_tasks.json"),
        "readiness": str(output_dir / "readiness.json"),
    }


def _search_report(bundle: dict[str, Any]) -> str:
    readiness = bundle["readiness"]
    lines = [
        "# searchAgent Seed Library Report",
        "",
        "This is an offline seed library for a private diversity harness, not a final SoftArena task package.",
        "",
        f"- seeds: {readiness['seed_count']}",
        f"- diversity harness tasks: {readiness['diversity_task_count']}",
        f"- evidence rows: {readiness['evidence_count']}",
        f"- tools: {', '.join(readiness['tool_coverage'])}",
        f"- passed: {readiness['passed']}",
        f"- LLM seed synthesis: {readiness.get('llm_seed_synthesis_status', {}).get('status', 'unknown')}",
        f"- LLM refinement: {readiness.get('llm_refinement_status', {}).get('status', 'unknown')}",
        "",
        "## Research Providers",
    ]
    for provider in readiness.get("research_provider_status", []):
        lines.append(
            f"- `{provider.get('provider')}` status={provider.get('status')} "
            f"attempted={provider.get('attempted')} evidence={provider.get('evidence_count', 0)}"
        )
    lines.extend([
        "",
        "## Evidence",
    ])
    for evidence in bundle["evidence"]:
        row = evidence.to_dict()
        lines.append(f"- `{row['source_id']}` {row['title']} {row['url']}".rstrip())
    lines.extend(["", "## Seeds"])
    for seed in bundle["seeds"]:
        row = seed.to_dict()
        lines.append(f"- `{row['seed_id']}` {row['title']} | tools={', '.join(row['selected_tools'])}")
    return "\n".join(lines) + "\n"
