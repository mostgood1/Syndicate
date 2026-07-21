"""Fetch and cache real CFBD market lines for one NCAAF season/week.

Writes data/ncaaf_source/data/cfbd_lines_{season}_wk{week}.json -- read by
scripts/backfill_smartsim2_performance.py's ``load_market_lines()`` (season-
aware lookup added alongside this script).

This is a standalone, Enhanced-Totals-Engine-independent path to real market
lines: scripts/refresh_ncaaf_oddsapi.py hard-requires the Engine's predicted-
schedule CSV (a single, non-season-partitioned file only ever refreshed for
the Engine's own season), which makes it unusable while the Engine is
skipped for a season it has no data for (see smartsim_ats_policy_implementation_report.md
and the 2026 season bootstrap). This script calls CFBD's own /lines endpoint
directly instead.

Usage:
    python scripts/fetch_ncaaf_market_lines.py --season 2026 --week 1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.ncaaf.sources import default_ncaaf_source_root  # noqa: E402

CFBD_API_BASE = "https://api.collegefootballdata.com"
CFBD_ENV_VARS = ("CFBD_API_KEY", "COLLEGEFOOTBALLDATA_API_KEY", "COLLEGE_FOOTBALL_DATA_API_KEY")


def _api_key() -> str:
    for env_var in CFBD_ENV_VARS:
        value = os.environ.get(env_var)
        if value:
            return value
    raise RuntimeError("Missing CFBD API key. Set CFBD_API_KEY, COLLEGEFOOTBALLDATA_API_KEY, or COLLEGE_FOOTBALL_DATA_API_KEY.")


def fetch_lines(season: int, week: int) -> list[dict]:
    query = f"year={season}&week={week}&seasonType=regular"
    url = f"{CFBD_API_BASE}/lines?{query}"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {_api_key()}", "User-Agent": "syndicate-ncaaf-market-lines/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload if isinstance(payload, list) else []


def lines_cache_path(season: int, week: int, *, data_root: Path | None = None) -> Path:
    root = data_root if data_root is not None else default_ncaaf_source_root() / "data"
    return root / f"cfbd_lines_{season}_wk{week}.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    args = parser.parse_args()

    games = fetch_lines(args.season, args.week)
    priced_games = sum(1 for g in games if g.get("lines"))
    path = lines_cache_path(args.season, args.week)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(games, indent=2), encoding="utf-8")

    print(f"games_fetched={len(games)}")
    print(f"games_with_at_least_one_priced_line={priced_games}")
    print(f"cache_path={path}")


if __name__ == "__main__":
    main()
