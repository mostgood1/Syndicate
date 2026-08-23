"""How accurate is an interval-final projection, and WHEN does it get accurate?

**THE ACTIONABLE OUTPUT IS THE ERROR CURVE, NOT A SINGLE NUMBER.** A projection
of a quarter's final total is nearly worthless with 9 minutes left and nearly
exact with 30 seconds left. The question a live bettor has is where on that
curve the error drops below the market's slowness -- so error is reported
BUCKETED BY TIME REMAINING, never pooled into one figure that describes neither
end.

## THREE MODELS, BECAUSE ONE MODEL CANNOT BE JUDGED

  naive_zero    the rest of the period scores NOTHING. The floor. Any model
                that cannot beat this is measuring nothing.
  league_rate   remaining possessions x a LEAGUE-WIDE points-per-possession,
                ignoring this game entirely.
  game_pace     remaining possessions x THIS GAME's points-per-possession.

`game_pace` beating `league_rate` is the only evidence that per-game state adds
anything. If they tie, pace tracking is decoration and the simpler model wins --
which is the same discipline that just retired momentum.

Runs on the worker, reads captured dumps, no network.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from syndicate.features.shared.basketball_interval_projection import period_bounds
from syndicate.features.shared.basketball_interval_projection import project_interval
from syndicate.features.shared.basketball_momentum_artifacts import momentum_events_path

# Buckets of seconds remaining in the period. The lowest bucket is where a live
# line is most likely to be stale and the projection most likely to be right.
BUCKETS = ((0, 60), (60, 120), (120, 240), (240, 420), (420, 600))
PROBE_STEP = 30.0


def _bucket(left: float) -> tuple[int, int] | None:
    for lo, hi in BUCKETS:
        if lo <= left < hi:
            return (lo, hi)
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", default="wnba")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--data-root", default=None)
    args = parser.parse_args(argv)

    if args.data_root:
        root = Path(args.data_root)
    else:
        from syndicate.features.shared.refresh_state_store import data_root
        root = data_root()

    # Pass 1: league points-per-possession, so `league_rate` is not a guess.
    league_points = league_poss = 0.0
    per_game: list[tuple[list, list]] = []

    a, b = date.fromisoformat(args.start), date.fromisoformat(args.end)
    while a <= b:
        path = momentum_events_path(root, league_code=args.league, date_str=a.isoformat())
        a += timedelta(days=1)
        if not path.exists():
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for game in (doc.get("games") or {}).values():
            if not isinstance(game, dict):
                continue
            pressure = game.get("pressure") or []
            scoring = game.get("narrator") or []
            if not pressure or not scoring:
                continue
            per_game.append((pressure, scoring))
            league_points += sum(abs(float(r.get("weight") or 0.0)) for r in scoring)
            league_poss += max(float(r.get("possession_index") or 0.0) for r in pressure)

    if not per_game:
        print("[interval] NO GAMES -- nothing captured for this range", flush=True)
        return 3

    league_ppp = (league_points / league_poss) if league_poss > 0 else 0.0
    print(f"[interval] SEASON league={args.league} games={len(per_game)} "
          f"league_ppp={league_ppp:.4f}", flush=True)

    errors: dict[tuple, dict[str, list[float]]] = {}

    for pressure, scoring in per_game:
        last = max(float(r["clock_seconds"]) for r in pressure)
        probe = PROBE_STEP
        while probe <= last:
            row = project_interval(pressure, scoring, probe, league_code=args.league)
            probe += PROBE_STEP
            if row is None:
                continue
            left = row["state_seconds_left_in_period"]
            key = _bucket(left)
            if key is None:
                continue
            truth = row["true_rest_total"]
            bucket = errors.setdefault(key, {"naive_zero": [], "league_rate": [], "game_pace": []})
            bucket["naive_zero"].append(abs(0.0 - truth))
            bucket["league_rate"].append(abs(row["state_possessions_left_est"] * league_ppp - truth))
            bucket["game_pace"].append(abs(row["proj_rest_total"] - truth))

    print("[interval] MEDIAN ABSOLUTE ERROR in points, on the REST of the period", flush=True)
    for key in BUCKETS:
        bucket = errors.get(key)
        if not bucket or not bucket["game_pace"]:
            continue
        z = statistics.median(bucket["naive_zero"])
        l = statistics.median(bucket["league_rate"])
        g = statistics.median(bucket["game_pace"])
        n = len(bucket["game_pace"])
        best = min((z, "naive_zero"), (l, "league_rate"), (g, "game_pace"))[1]
        print(f"[interval] BUCKET left={key[0]}-{key[1]}s n={n} "
              f"naive_zero={z:.2f} league_rate={l:.2f} game_pace={g:.2f} "
              f"best={best}", flush=True)

    # **DOES THIS GAME'S PACE BEAT THE LEAGUE'S?** The only question that says
    # whether per-game state is worth tracking at all.
    all_l = [v for b in errors.values() for v in b["league_rate"]]
    all_g = [v for b in errors.values() for v in b["game_pace"]]
    if all_l and all_g:
        ml, mg = statistics.median(all_l), statistics.median(all_g)
        delta = ml - mg
        print(f"[interval] GAME_PACE_VS_LEAGUE median_league={ml:.3f} "
              f"median_game={mg:.3f} improvement={delta:+.3f} points "
              f"{'-- game pace helps' if delta > 0 else '-- game pace does NOT help'}",
              flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
