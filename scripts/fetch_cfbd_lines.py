"""Fetch and cache real CFBD `/lines` market data per week.

Read-only against the CFBD API; writes one JSON file per week to a cache
directory (default: ``data/ncaaf_source/data/``, gitignored) so downstream
backtests/backfills don't need to re-fetch. Does not touch SmartSim 2.0, the
Enhanced Totals Engine, or any blend/policy code.

Usage:
    python scripts/fetch_cfbd_lines.py --season 2025 --weeks 1,2,3 --out-dir data/ncaaf_source/data
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.ncaaf.cfbd import CfbdClient  # noqa: E402
from syndicate.features.ncaaf.sources import default_ncaaf_source_root  # noqa: E402


def fetch_week_lines(client: CfbdClient, *, season: int, week: int) -> list[dict]:
    payload = client._get_json("/lines", params={"year": season, "week": week, "seasonType": "regular"})
    return payload if isinstance(payload, list) else []


def _load_env() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        return
    load_dotenv()


def main() -> None:
    _load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=2025)
    parser.add_argument("--weeks", type=str, required=True, help="Comma-separated week numbers")
    parser.add_argument("--out-dir", type=Path, default=default_ncaaf_source_root() / "data")
    args = parser.parse_args()

    client = CfbdClient.from_env()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    for week in [int(w) for w in args.weeks.split(",") if w.strip()]:
        games = fetch_week_lines(client, season=args.season, week=week)
        # Must match _smartsim2_standalone_market_lines's real read path in
        # syndicate/features/ncaaf/cards.py (cfbd_lines_{season}_wk{week}.json)
        # -- the season-less name this used to write here was never read by
        # anything downstream.
        out_path = args.out_dir / f"cfbd_lines_{args.season}_wk{week}.json"
        with out_path.open("w", encoding="utf-8") as handle:
            json.dump(games, handle)
        print(f"week={week} games={len(games)} path={out_path}")


if __name__ == "__main__":
    main()
