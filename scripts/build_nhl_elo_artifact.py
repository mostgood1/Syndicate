#!/usr/bin/env python3
"""Producer: real finished-game results -> ``team_elo_{season}.csv`` / ``team_elo_latest.csv``.

Closes the `elo_rating` gap documented in `docs/ai_context/hockeysim_engine_reference.md`:
`HockeyTeamFeatures.elo_rating` was CONSUMED by `projection.py`'s `_elo_win_prob` and had **no
producer anywhere in the codebase** (`docs/ai_context/model_engine_standard.md` §0's exact alarm
shape). This script is that producer.

Reads the same truth cache the Phase-3 baseline reads (``data/nhl_source/data/truth/raw`` by
default, or fetches live via ``NHLE_BASE_URL`` when ``--fetch`` is passed), computes a chronological
Elo rating per team (`historical_truth.elo_builder.compute_elo_ratings`), and writes it in the same
``{abbr,xgf60,xga60}``-shaped location and naming convention `load_team_xg_map` already reads, so
`build_team_features` needs only a matching `load_team_elo_map` (added alongside this script) to
wire it in -- no new artifact-location convention invented.

Usage:
  py -3 scripts/build_nhl_elo_artifact.py
  py -3 scripts/build_nhl_elo_artifact.py --season 2025-2026 --fetch
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.elo_builder import (  # noqa: E402
    DEFAULT_ELO_SCALE,
    DEFAULT_HOME_ADVANTAGE,
    DEFAULT_INITIAL_RATING,
    DEFAULT_K,
    compute_elo_progression,
)
from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.nhl_statsweb_loader import (  # noqa: E402
    NhlStatsWebTruthLoader,
)


def _nhl_source_root() -> Path:
    import os
    env = str(os.environ.get("SYNDICATE_ARTIFACT_ROOT_NHL") or "").strip()
    if env:
        p = Path(env)
        if p.exists():
            return p
    return REPO / "data" / "nhl_source"


def _write_csv(path: Path, ratings: dict) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(ratings.items())
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["abbr", "elo"])
        for abbr, elo in rows:
            w.writerow([abbr, round(float(elo), 2)])
    return len(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", default=None, help="season code, e.g. 2025-2026; defaults to inferring from the cache")
    ap.add_argument("--fetch", action="store_true", help="hit the live api-web.nhle.com feed instead of the on-disk cache only")
    ap.add_argument("--k", type=float, default=DEFAULT_K)
    ap.add_argument("--home-advantage", type=float, default=DEFAULT_HOME_ADVANTAGE)
    ap.add_argument("--scale", type=float, default=DEFAULT_ELO_SCALE)
    ap.add_argument("--initial", type=float, default=DEFAULT_INITIAL_RATING)
    ap.add_argument("--root", type=Path, default=None, help="override the nhl_source root (default: SYNDICATE_ARTIFACT_ROOT_NHL or data/nhl_source)")
    args = ap.parse_args()

    root = args.root or _nhl_source_root()
    loader = NhlStatsWebTruthLoader(offline=not args.fetch)
    games = loader.load_from_cache()
    if not games:
        print(f"REFUSED: no cached truth games under {loader.cache_dir}", file=sys.stderr)
        print("  (run with --fetch to pull from api-web.nhle.com, or populate the cache first)", file=sys.stderr)
        return 1

    regular = [g for g in games if int(g.game_type) == 2]
    if not regular:
        print("REFUSED: cache has games but none are regular-season (game_type==2)", file=sys.stderr)
        return 1

    final, pregame = compute_elo_progression(
        regular, k=args.k, scale=args.scale, home_advantage=args.home_advantage, initial=args.initial,
    )

    seasons = sorted({g.season for g in regular if g.season})
    season = args.season or (seasons[0] if len(seasons) == 1 else "")
    dates = sorted({g.date[:10] for g in regular if g.date})

    out_dir = root / "data" / "processed"
    written = []
    if season:
        p = out_dir / f"team_elo_{season}.csv"
        n = _write_csv(p, final)
        written.append((p, n))
    p_latest = out_dir / "team_elo_latest.csv"
    n_latest = _write_csv(p_latest, final)
    written.append((p_latest, n_latest))

    print(f"games: {len(regular)} regular-season ({games[0].date if games else '?'}..{dates[-1] if dates else '?'})")
    print(f"teams rated: {len(final)}")
    print(f"params: k={args.k} scale={args.scale} home_advantage={args.home_advantage} initial={args.initial}")
    for path, n in written:
        print(f"wrote {path} ({n} teams)")
    print()
    print("NOTE: writing this artifact does not turn Elo ON in the projection. "
          "ProjectionProfile.elo_blend_weight is 0.0 by default -- see the backtest section of "
          "docs/ai_context/hockeysim_engine_reference.md for why it is deliberately still off.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
