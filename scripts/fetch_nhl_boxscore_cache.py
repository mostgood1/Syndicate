#!/usr/bin/env python3
"""Bulk-fetch NHL `boxscore` payloads for the truth cache's regular-season games.

Closes the gap flagged in `docs/ai_context/hockeysim_engine_reference.md` §5/§2d: the
`landing` feed the truth loader reads has no shot-by-strength-state breakdown, but the
SEPARATE `boxscore` endpoint does (`playerByGameStats.{home,away}Team.goalies[].
evenStrengthShotsAgainst`/`powerPlayShotsAgainst`/`shorthandedShotsAgainst`), verified against
one cached sample last session. Only 11 of 1,312 games had a cached boxscore before this script.

Uses `ingestion/nhl_web.py`'s existing `NhlWebIngestClient.boxscore()` -- cache-first, disk-cached
at `data/nhl_source/data/ingestion_cache/boxscore_{game_id}.json`, same convention the (partial)
lineup collector already uses. This script only adds the BULK enumeration; the fetch/cache
mechanism is not new.

Game ids come from the truth cache (`data/nhl_source/data/truth/raw/landing_*.json`), filtered to
`game_type == 2` (regular season) -- the same population the special-teams goal calibration
(`scripts/calibrate_nhl_special_teams_goal_mult.py`) used, so a follow-on shot-rate calibration
scores against a like-for-like sample.

Usage:
  py -3 scripts/fetch_nhl_boxscore_cache.py                    # fetch everything not cached
  py -3 scripts/fetch_nhl_boxscore_cache.py --limit 50          # smoke-test a small batch
  py -3 scripts/fetch_nhl_boxscore_cache.py --rate 5            # requests/sec (default 5, matches the client)
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.nhl_statsweb_loader import (  # noqa: E402
    NhlStatsWebTruthLoader,
)
from syndicate.features.nhl.sim_engine.hockeysim.ingestion.nhl_web import NhlWebIngestClient  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=None, help="fetch at most N games (for a smoke test)")
    ap.add_argument("--rate", type=float, default=5.0, help="requests/sec")
    ap.add_argument("--game-type", type=int, default=2, help="2=regular season, 3=playoffs; matches the truth loader's default population")
    args = ap.parse_args()

    truth_loader = NhlStatsWebTruthLoader(offline=True)
    games = truth_loader.load_from_cache()
    game_ids = sorted({g.game_id for g in games if int(g.game_type) == args.game_type})
    if not game_ids:
        print(f"REFUSED: no cached truth games (game_type={args.game_type}) under {truth_loader.cache_dir}", file=sys.stderr)
        return 1
    if args.limit:
        game_ids = game_ids[: args.limit]

    client = NhlWebIngestClient(rate_limit_per_sec=args.rate)
    already = sum(1 for gid in game_ids if (client.cache_dir / f"boxscore_{gid}.json").exists())
    print(f"game ids: {len(game_ids)}  already cached: {already}  to fetch: {len(game_ids) - already}")

    fetched = failed = 0
    t0 = time.time()
    for i, gid in enumerate(game_ids, 1):
        path = client.cache_dir / f"boxscore_{gid}.json"
        was_cached = path.exists() and path.stat().st_size > 0
        try:
            data = client.boxscore(gid)
        except Exception as exc:
            failed += 1
            print(f"  [{i}/{len(game_ids)}] {gid}: FAILED ({exc!r})")
            continue
        if data is None:
            failed += 1
            print(f"  [{i}/{len(game_ids)}] {gid}: no data returned")
            continue
        if not was_cached:
            fetched += 1
        if i % 100 == 0 or i == len(game_ids):
            elapsed = time.time() - t0
            print(f"  [{i}/{len(game_ids)}] fetched={fetched} failed={failed} elapsed={elapsed:.0f}s")

    print(f"\nDONE. fetched {fetched} new, {failed} failed, {already} were already cached, "
          f"{len(game_ids)} total ids.")
    if failed:
        print(f"  {failed} game(s) failed -- re-run the same command; already-cached games are skipped instantly.")
    return 1 if failed and fetched == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
