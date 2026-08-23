"""Does pace and efficiency actually MOVE with game situation? Measure first.

**THE FLAT PROJECTION ASSUMES THEY DO NOT, AND BASKETBALL SAYS OTHERWISE.**
`analyze_interval_projection`'s `game_pace` model multiplies remaining minutes by
a game-to-date pace and a game-to-date points-per-possession. Both are averages
over a whole game, and both are wrong in exactly the states a live bettor cares
about:

  - trailing late, a team SPEEDS UP -- more threes, deliberate fouling, and the
    clock stopping on every whistle, so possessions per minute climbs;
  - leading late, a team MILKS the clock, so it falls;
  - a blowout empties the benches, changing both pace and efficiency;
  - deliberate fouling converts possessions into free throws, which changes
    points-per-possession as well as the possession count.

A flat model is therefore not merely imprecise -- it is BIASED, and biased
hardest in close late games, which is where the interval markets are actually
traded.

## THIS MEASURES, IT DOES NOT MODEL

The output is a table of observed pace and PPP by (score margin, time left in
period). If those cells are flat, the situational layer is not worth building
and the simpler model wins. If they are not, the table says by how much and
where -- which is the input a model needs and the evidence that it should exist.

Same discipline that retired momentum: measure the effect before assuming it.

## TEAM SHOOTING PROFILE

Also emitted per team, from the same rows: three-point share of attempts, free
throw rate, and turnover rate. Team identity is the other half of the user's
point -- a team that shoots 40% of its attempts from three has a different
scoring distribution than one that shoots 25%, and the flat model treats them
identically.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from syndicate.features.shared.basketball_interval_projection import period_bounds
from syndicate.features.shared.basketball_momentum_artifacts import momentum_events_path

# |margin| buckets. "close" is what a live line is most sensitive to.
MARGIN_BUCKETS = ((0, 5), (5, 10), (10, 20), (20, 999))
# Seconds left in the period.
LEFT_BUCKETS = ((0, 120), (120, 300), (300, 600))
WINDOW = 60.0          # measure pace over a rolling minute
MIN_WINDOWS = 30       # don't report a cell thinner than this


def _pace(cell: dict[str, float]) -> float:
    """Possessions per minute, pooled over the cell's windows."""
    return cell["poss"] / max(cell["windows"], 1.0)


def _ppp(cell: dict[str, float]) -> float:
    """Points per possession, pooled -- total points over total possessions."""
    return cell["points"] / max(cell["poss"], 1e-9)


def _ft_share(cell: dict[str, float]) -> float:
    """Free throws as a share of all shooting events, pooled."""
    return cell["ft"] / max(cell["ft"] + cell["fga"], 1e-9)


def _bucket(value: float, buckets) -> tuple[int, int] | None:
    for lo, hi in buckets:
        if lo <= value < hi:
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

    # (margin bucket, left bucket) -> POOLED totals.
    #
    # **NOT a median of per-window ratios.** A 60s window holds ~4 possessions,
    # so points/poss lands on a coarse lattice (4/4, 5/4, ...) and its median
    # snaps to a lattice point -- three unrelated cells reported ppp=1.031 and
    # every late cell reported ft_share=0.286 (=2/7) in the first run, which
    # reads as a measured agreement and is an artifact of the statistic. Free
    # throws are worse: most windows have zero, so the median is 0.000 until
    # the zero share crosses one half and then jumps discontinuously.
    #
    # Pooling totals across the cell gives the ratio estimator a model would
    # actually use, and removes both failure modes.
    cells: dict[tuple, dict[str, float]] = defaultdict(
        lambda: {"windows": 0.0, "poss": 0.0, "points": 0.0, "ft": 0.0, "fga": 0.0})
    # **WHICH seconds-left values actually land in each bucket.** Windows are
    # 60s and non-overlapping from t=0, and a WNBA period is 600s, so exactly
    # ONE window per period has left < 120 -- the final minute. The bucket is
    # honestly labelled `0-120s` and is sampled at a single point inside it.
    # Printing the set stops that label being read as a range that was swept.
    cell_lefts: dict[tuple, set] = defaultdict(set)
    team_shots: dict[str, dict[str, float]] = defaultdict(
        lambda: {"fg2": 0.0, "fg3": 0.0, "ft": 0.0, "tov": 0.0, "poss": 0.0})
    games = 0

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
            games += 1
            home_tri = str(game.get("home_tri") or "")
            away_tri = str(game.get("away_tri") or "")

            for row in pressure:
                team = str(row.get("team") or "")
                if not team:
                    continue
                kind = str(row.get("type") or "")
                bucket = team_shots[team]
                if kind == "shot_attempt_3":
                    bucket["fg3"] += 1
                elif kind == "shot_attempt_2":
                    bucket["fg2"] += 1
                elif kind == "free_throw":
                    bucket["ft"] += 1
                elif kind == "turnover":
                    bucket["tov"] += 1
            if pressure:
                team_shots[home_tri]["poss"] += max(
                    float(r.get("possession_index") or 0.0) for r in pressure) / 2.0
                team_shots[away_tri]["poss"] += max(
                    float(r.get("possession_index") or 0.0) for r in pressure) / 2.0

            # Rolling windows: pace and PPP measured over the next WINDOW
            # seconds, labelled by the situation at the START of the window.
            last = max(float(r["clock_seconds"]) for r in pressure)
            t = WINDOW
            while t + WINDOW <= last:
                margin = sum(float(r.get("sign") or 0.0) * float(r.get("weight") or 0.0)
                             for r in scoring if float(r["clock_seconds"]) <= t)
                _, _, left = period_bounds(args.league, t)
                mkey = _bucket(abs(margin), MARGIN_BUCKETS)
                lkey = _bucket(left, LEFT_BUCKETS)
                if mkey is None or lkey is None:
                    t += WINDOW
                    continue

                window_rows = [r for r in pressure if t < float(r["clock_seconds"]) <= t + WINDOW]
                poss_start = max((float(r.get("possession_index") or 0.0)
                                  for r in pressure if float(r["clock_seconds"]) <= t), default=0.0)
                poss_end = max((float(r.get("possession_index") or 0.0)
                                for r in pressure if float(r["clock_seconds"]) <= t + WINDOW),
                               default=poss_start)
                poss = poss_end - poss_start
                points = sum(abs(float(r.get("weight") or 0.0)) for r in scoring
                             if t < float(r["clock_seconds"]) <= t + WINDOW)

                if poss > 0:
                    cell = cells[(mkey, lkey)]
                    cell["windows"] += 1.0
                    cell["poss"] += poss
                    cell["points"] += points
                    cell["ft"] += sum(1 for r in window_rows
                                      if str(r.get("type")) == "free_throw")
                    cell["fga"] += sum(1 for r in window_rows
                                       if str(r.get("type")) in ("shot_attempt_2",
                                                                 "shot_attempt_3"))
                    cell_lefts[(mkey, lkey)].add(int(left))
                t += WINDOW

    if not games:
        print("[situational] NO GAMES", flush=True)
        return 3

    print(f"[situational] SEASON league={args.league} games={games}", flush=True)
    print("[situational] PACE (possessions/min) and PPP by |margin| x seconds-left", flush=True)
    for mkey in MARGIN_BUCKETS:
        for lkey in LEFT_BUCKETS:
            cell = cells.get((mkey, lkey))
            if not cell or cell["windows"] < MIN_WINDOWS:
                continue
            print(f"[situational] CELL margin={mkey[0]}-{mkey[1]} left={lkey[0]}-{lkey[1]}s "
                  f"n={int(cell['windows'])} "
                  f"pace={_pace(cell):.2f} "
                  f"ppp={_ppp(cell):.3f} "
                  f"ft_share={_ft_share(cell):.3f} "
                  f"left_vals={sorted(cell_lefts[(mkey, lkey)])}",
                  flush=True)

    # **THE HEADLINE: does the situation move pace at all?** If the spread
    # across cells is trivial, the flat model is fine and this layer is not
    # worth building.
    paces = [_pace(c) for c in cells.values() if c["windows"] >= MIN_WINDOWS]
    ppps = [_ppp(c) for c in cells.values() if c["windows"] >= MIN_WINDOWS]
    if paces:
        print(f"[situational] PACE_SPREAD min={min(paces):.2f} max={max(paces):.2f} "
              f"ratio={max(paces)/max(min(paces), 1e-6):.2f}x", flush=True)
    if ppps:
        print(f"[situational] PPP_SPREAD min={min(ppps):.3f} max={max(ppps):.3f} "
              f"ratio={max(ppps)/max(min(ppps), 1e-6):.2f}x", flush=True)

    print("[situational] TEAM SHOOTING PROFILE (3PA share of FGA, FT per 100 poss, TOV per 100)",
          flush=True)
    for team, s in sorted(team_shots.items()):
        fga = s["fg2"] + s["fg3"]
        if fga < 200 or s["poss"] <= 0:
            continue
        print(f"[situational] TEAM {team} fga={int(fga)} "
              f"three_share={s['fg3']/fga:.3f} "
              f"ft_per100={100*s['ft']/s['poss']:.1f} "
              f"tov_per100={100*s['tov']/s['poss']:.1f}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
