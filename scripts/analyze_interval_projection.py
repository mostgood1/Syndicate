"""How accurate is an interval-final projection, and WHEN does it get accurate?

**THE ACTIONABLE OUTPUT IS THE ERROR CURVE, NOT A SINGLE NUMBER.** A projection
of a quarter's final total is nearly worthless with 9 minutes left and nearly
exact with 30 seconds left. The question a live bettor has is where on that
curve the error drops below the market's slowness -- so error is reported
BUCKETED BY TIME REMAINING, never pooled into one figure that describes neither
end.

## FOUR MODELS, BECAUSE ONE MODEL CANNOT BE JUDGED

  naive_zero    the rest of the period scores NOTHING. The floor. Any model
                that cannot beat this is measuring nothing.
  league_rate   remaining possessions x a LEAGUE-WIDE points-per-possession,
                ignoring this game's efficiency entirely.
  game_pace     remaining possessions x THIS GAME's points-per-possession.
  league_late   league rates, but with the FINAL MINUTE of a period priced
                separately -- see below.

`game_pace` beating `league_rate` is the only evidence that per-game state adds
anything. It does not: measured -0.43 points over 282 WNBA games.

## WHY `league_late` EXISTS

`analyze_situational_pace` pooled 282 games and found the (margin x time) grid
is NOT a grid. Margin does essentially nothing -- within any time bucket, pace
varies 1.8% across margin bands. Time does exactly one thing, in one place:

    left=300-600s   pace 3.89/min   ppp 1.109   ft_share 0.201
    left=120-300s   pace 3.87/min   ppp 1.150   ft_share 0.265
    left=0-120s     pace 4.52/min   ppp 1.090   ft_share 0.306

Flat, flat, jump. The final minute runs ~17% more possessions per minute at
slightly lower efficiency, and the free-throw share rises monotonically into it
-- the clock stopping, which is the mechanism. So the situational layer is not
a twelve-cell model, it is ONE BINARY, and `league_late` is that binary.

## MECHANISM VS ESTIMATOR, AND THE SPLIT

Adding a mechanism to a calibrated model requires re-fitting the rates that
were absorbing it (`model_engine_standard.md`). So the late and normal rates are
BOTH derived here rather than hard-coded, and `pace_normal` excludes the late
windows -- it is not the blended average any more.

And the constants are fitted on a TEMPORAL TRAIN SPLIT and the error measured on
the held-out remainder. Fitting and scoring on the same 282 games would let a
model that merely memorised the season look like one that learned it. Never a
random split: a random one leaks the same games' second halves into training.

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
# The final minute of a period, which `analyze_situational_pace` measured as the
# ONLY place the situational grid actually moves.
LATE_WINDOW = 60.0


def _bucket(left: float) -> tuple[int, int] | None:
    for lo, hi in BUCKETS:
        if lo <= left < hi:
            return (lo, hi)
    return None


def _period_segments(league: str, last: float) -> list[tuple[float, float, float, float]]:
    """(normal_lo, normal_hi, late_lo, late_hi) for each period actually played.

    The LATE window is the final `LATE_WINDOW` seconds of a period; NORMAL is
    everything before it. Splitting here rather than at the call sites keeps one
    definition of "late" for the fit and for the projection.
    """
    # Period length straight from `period_bounds`' own definition: at clock 0
    # the seconds LEFT in period 1 IS the period length. Deriving it rather than
    # re-reading the rules table keeps the two from drifting apart.
    length = period_bounds(league, 0.0)[2]
    if length <= LATE_WINDOW:
        return []
    out = []
    start = 0.0
    while start < last:
        end = start + length
        # **BOTH halves clamp to `last`.** Without clamping the NORMAL half, a
        # game whose last play lands mid-period contributes the full 540s of
        # normal time and only the possessions actually played, which biases
        # `pace_normal` DOWN and would make the late lift look larger than it is.
        out.append((start, min(end - LATE_WINDOW, last),
                    end - LATE_WINDOW, min(end, last)))
        start = end
    return out


def _poss_at(pressure, t: float) -> float:
    return max((float(r.get("possession_index") or 0.0)
                for r in pressure if float(r["clock_seconds"]) <= t), default=0.0)


def _points_between(scoring, lo: float, hi: float) -> float:
    return sum(abs(float(r.get("weight") or 0.0)) for r in scoring
               if lo < float(r["clock_seconds"]) <= hi)


def _fit_rates(league: str, games) -> dict[str, float]:
    """Pooled pace and points-per-possession, INSIDE vs OUTSIDE the final minute.

    Returned separately on purpose. A single blended pace is what `league_rate`
    already uses, and blending is exactly what makes the final minute wrong.
    """
    acc = {"late_poss": 0.0, "late_pts": 0.0, "late_sec": 0.0,
           "norm_poss": 0.0, "norm_pts": 0.0, "norm_sec": 0.0,
           "all_poss": 0.0, "all_pts": 0.0}
    for pressure, scoring in games:
        last = max(float(r["clock_seconds"]) for r in pressure)
        acc["all_poss"] += _poss_at(pressure, last)
        acc["all_pts"] += _points_between(scoring, -1.0, last)
        for n_lo, n_hi, l_lo, l_hi in _period_segments(league, last):
            if n_hi > n_lo:
                acc["norm_poss"] += _poss_at(pressure, n_hi) - _poss_at(pressure, n_lo)
                acc["norm_pts"] += _points_between(scoring, n_lo, n_hi)
                acc["norm_sec"] += n_hi - n_lo
            if l_hi > l_lo:
                acc["late_poss"] += _poss_at(pressure, l_hi) - _poss_at(pressure, l_lo)
                acc["late_pts"] += _points_between(scoring, l_lo, l_hi)
                acc["late_sec"] += l_hi - l_lo
    div = lambda a, b: (a / b) if b > 0 else 0.0
    return {
        "league_ppp": div(acc["all_pts"], acc["all_poss"]),
        "pace_normal": div(acc["norm_poss"], acc["norm_sec"] / 60.0),
        "ppp_normal": div(acc["norm_pts"], acc["norm_poss"]),
        "pace_late": div(acc["late_poss"], acc["late_sec"] / 60.0),
        "ppp_late": div(acc["late_pts"], acc["late_poss"]),
    }


def _league_late_projection(left: float, rates: dict[str, float]) -> float:
    """Points in the rest of the period, pricing its final minute separately."""
    late = min(max(left, 0.0), LATE_WINDOW)
    normal = max(left - late, 0.0)
    return (rates["pace_normal"] * (normal / 60.0) * rates["ppp_normal"]
            + rates["pace_late"] * (late / 60.0) * rates["ppp_late"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", default="wnba")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--data-root", default=None)
    parser.add_argument("--train-frac", type=float, default=0.7,
                        help="fraction of DATES (earliest first) used to fit rates")
    args = parser.parse_args(argv)

    if args.data_root:
        root = Path(args.data_root)
    else:
        from syndicate.features.shared.refresh_state_store import data_root
        root = data_root()

    # Games kept WITH their date, because the split must be temporal.
    dated: list[tuple[str, list, list]] = []

    a, b = date.fromisoformat(args.start), date.fromisoformat(args.end)
    while a <= b:
        day = a.isoformat()
        path = momentum_events_path(root, league_code=args.league, date_str=day)
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
            dated.append((day, pressure, scoring))

    if not dated:
        print("[interval] NO GAMES -- nothing captured for this range", flush=True)
        return 3

    # **TEMPORAL SPLIT, BY DATE.** Splitting by game index would put two halves
    # of the same slate on both sides; splitting randomly would be worse still.
    days = sorted({d for d, _, _ in dated})
    cut = max(1, min(len(days) - 1, int(round(len(days) * args.train_frac)))) if len(days) > 1 else 1
    train_days = set(days[:cut])
    train = [(p, s) for d, p, s in dated if d in train_days]
    test = [(p, s) for d, p, s in dated if d not in train_days]
    if not train or not test:
        print(f"[interval] SPLIT_DEGENERATE days={len(days)} train={len(train)} "
              f"test={len(test)} -- reporting IN-SAMPLE, treat accordingly", flush=True)
        train = test = [(p, s) for _, p, s in dated]

    rates = _fit_rates(args.league, train)
    league_ppp = rates["league_ppp"]
    print(f"[interval] SEASON league={args.league} games={len(dated)} "
          f"train_games={len(train)} test_games={len(test)} "
          f"train_days={cut}/{len(days)} league_ppp={league_ppp:.4f}", flush=True)
    print(f"[interval] FITTED_RATES late_window={LATE_WINDOW:.0f}s "
          f"pace_normal={rates['pace_normal']:.3f} ppp_normal={rates['ppp_normal']:.4f} "
          f"pace_late={rates['pace_late']:.3f} ppp_late={rates['ppp_late']:.4f} "
          f"pace_lift={rates['pace_late']/max(rates['pace_normal'], 1e-9):.3f}x", flush=True)

    errors: dict[tuple, dict[str, list[float]]] = {}

    for pressure, scoring in test:
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
            bucket = errors.setdefault(key, {"naive_zero": [], "league_rate": [],
                                             "game_pace": [], "league_late": []})
            bucket["naive_zero"].append(abs(0.0 - truth))
            bucket["league_rate"].append(abs(row["state_possessions_left_est"] * league_ppp - truth))
            bucket["game_pace"].append(abs(row["proj_rest_total"] - truth))
            bucket["league_late"].append(abs(_league_late_projection(left, rates) - truth))

    print("[interval] MEDIAN ABSOLUTE ERROR in points, on the REST of the period", flush=True)
    for key in BUCKETS:
        bucket = errors.get(key)
        if not bucket or not bucket["game_pace"]:
            continue
        z = statistics.median(bucket["naive_zero"])
        l = statistics.median(bucket["league_rate"])
        g = statistics.median(bucket["game_pace"])
        t = statistics.median(bucket["league_late"])
        n = len(bucket["game_pace"])
        best = min((z, "naive_zero"), (l, "league_rate"),
                   (g, "game_pace"), (t, "league_late"))[1]
        print(f"[interval] BUCKET left={key[0]}-{key[1]}s n={n} "
              f"naive_zero={z:.2f} league_rate={l:.2f} game_pace={g:.2f} "
              f"league_late={t:.2f} best={best}", flush=True)

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

    # **DOES PRICING THE FINAL MINUTE SEPARATELY BEAT PRICING IT LIKE ANY OTHER?**
    # The situational table says the final minute is different. This says whether
    # knowing that is worth anything on held-out games.
    all_t = [v for b in errors.values() for v in b["league_late"]]
    if all_l and all_t:
        ml, mt = statistics.median(all_l), statistics.median(all_t)
        delta = ml - mt
        print(f"[interval] LATE_SPLIT_VS_LEAGUE median_league={ml:.3f} "
              f"median_late_split={mt:.3f} improvement={delta:+.3f} points "
              f"{'-- the final-minute split helps' if delta > 0 else '-- the final-minute split does NOT help'}",
              flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
