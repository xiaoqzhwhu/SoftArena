from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from softarena.search_agent.exporter import export_seed_library
from softarena.search_agent.research_client import ResearchClient
from softarena.search_agent.schemas import SELECTED_TOOLS
from softarena.search_agent.seed_builder import SearchAgentBuilder


def main() -> None:
    parser = argparse.ArgumentParser(prog="softarena.search_agent")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--reports-dir", default="/root")
    build.add_argument(
        "--demand-source",
        dest="demand_source",
        default=os.environ.get("SOFTARENA_DEMAND_SOURCE", "data/demand_source"),
        help="Path to the private demand-source slice.",
    )
    build.add_argument("--output", default="/root/softarena_v0_cloud_bundle/search_agent_seed_library")
    build.add_argument("--target-count", type=int, default=8)
    build.add_argument("--offline", action="store_true")
    build.add_argument("--selected-tools", default=",".join(SELECTED_TOOLS))

    args = parser.parse_args()
    if args.command == "build":
        tools = [item.strip() for item in args.selected_tools.split(",") if item.strip()]
        client = None if args.offline else ResearchClient.from_env()
        builder = SearchAgentBuilder(
            reports_dir=Path(args.reports_dir),
            demand_source=Path(args.demand_source),
            selected_tools=tools,
            research_client=client,
            offline=bool(args.offline),
        )
        bundle = builder.build(target_count=args.target_count)
        result = export_seed_library(Path(args.output), bundle)
        print(json.dumps({**result, "readiness_payload": bundle["readiness"]}, indent=2, ensure_ascii=False))
        if not bundle["readiness"].get("passed"):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
