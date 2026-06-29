from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_jsonl(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rows.append(json.loads(line))
            if limit is not None and len(rows) >= limit:
                break
    return rows


def load_demand_source_slice(root: Path, limit: int = 160) -> dict[str, list[dict[str, Any]]]:
    demand_library = root / "demand_library"
    if not demand_library.exists():
        # Compatibility with the internal demand-source slice layout.
        demand_library = root / "mother_library"
    cards = read_jsonl(demand_library / "real_need_cards.jsonl")
    wanted_domains = {"编码开发", "数据与BI", "IT与安全", "办公自动化", "项目与协作", "业务运营"}
    filtered_cards = [
        row
        for row in cards
        if str(row.get("domain") or "") in wanted_domains
        or any(tag in str(row.get("real_world_need") or "") for tag in ("数据", "代码", "脚本", "日志", "配置", "API", "SQL"))
    ][:limit]
    need_ids = {str(row.get("need_id") or "") for row in filtered_cards}
    return {
        "real_need_cards": filtered_cards,
        "artifact_blueprints": [
            row for row in read_jsonl(demand_library / "artifact_blueprints.jsonl") if str(row.get("need_id") or "") in need_ids
        ],
        "failure_events": [
            row for row in read_jsonl(demand_library / "failure_events.jsonl") if str(row.get("need_id") or "") in need_ids
        ],
        "self_check_rubrics": [
            row for row in read_jsonl(demand_library / "self_check_rubrics.jsonl") if str(row.get("need_id") or "") in need_ids
        ],
        "generation_rules": read_jsonl(demand_library / "generation_rules.jsonl", limit=limit),
    }


def load_mother_slice(root: Path, limit: int = 160) -> dict[str, list[dict[str, Any]]]:
    return load_demand_source_slice(root, limit=limit)
