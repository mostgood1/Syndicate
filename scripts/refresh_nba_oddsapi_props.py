from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_source_module(source_root: Path):
    src_root = source_root / "src"
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))
    return importlib.import_module("nba_betting.refresh_oddsapi_props_job")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the NBA OddsAPI props refresh job through a Syndicate-owned entrypoint.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--regions", default="us")
    parser.add_argument("--bookmakers", default="")
    parser.add_argument("--markets", default="")
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--log-file", required=True)
    parser.add_argument("--do-edges", action="store_true")
    parser.add_argument("--do-export", action="store_true")
    parser.add_argument("--do-push", action="store_true")
    parser.add_argument("--started-at")
    args = parser.parse_args()

    source_root = Path(args.source_root).resolve()
    source_module = _load_source_module(source_root)
    state = source_module.run_refresh_oddsapi_props_job(
        date_str=args.date,
        regions=args.regions,
        bookmakers=args.bookmakers,
        markets=args.markets,
        do_edges=bool(args.do_edges),
        do_export=bool(args.do_export),
        do_push=bool(args.do_push),
        log_file=Path(args.log_file).resolve(),
        started_at=args.started_at or None,
    )
    print(json.dumps(state, indent=2, sort_keys=True))

    snapshot_rows = int(state.get("snapshot_rows") or 0)
    alias_rows = int(state.get("snapshot_alias_rows") or 0)
    edges_rows = int(state.get("edges_rows") or 0)
    recs_rows = int(state.get("recs_rows") or 0)
    if state.get("error"):
        return 1
    if snapshot_rows > 0 and alias_rows <= 0:
        return 1
    if bool(args.do_edges) and snapshot_rows > 0 and edges_rows <= 0:
        return 1
    if bool(args.do_export) and snapshot_rows > 0 and recs_rows <= 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())