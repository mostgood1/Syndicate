"""Run the projection substrate over CAPTURED season data and report what it says.

**THE LEAKAGE GUARD HAS ONLY EVER RUN ON FIXTURES.** That proved the logic, not
the feed. A real season is exactly the size of thing that embarrasses a design
which looked fine on 300 synthetic rows, so this re-runs the same truncate-and-
compare check against real games before anything is fitted.

It reports, and it does not fit. No model, no coefficients, no edge. The output
is: how many rows a season yields, whether any `state_` field moves when the
future is appended, and the pace/possession distributions a projection would
have to live inside.

Runs on the worker (ESPN is 403 from a Claude Code sandbox, and the artifacts
live on the worker's disk), reporting through the log collector.
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

from syndicate.features.shared.basketball_momentum_artifacts import momentum_events_path
from syndicate.features.shared.basketball_projection_rows import build_projection_rows
from syndicate.features.shared.basketball_projection_rows import state_columns

_REGULATION = {"wnba": 2400.0, "nba": 2880.0, "ncaab": 2400.0, "ncaabw": 2400.0}


def _dates(start: str, end: str):
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    while a <= b:
        yield a.isoformat()
        a += timedelta(days=1)


def leakage_check(pressure: list, scoring: list, regulation: float) -> tuple[int, int]:
    """(probes compared, state fields that MOVED). Zero moved is the pass.

    Truncates the game at ~60% and rebuilds. Every `state_` value at a shared
    probe must be identical to the full-feed version -- a field that changes has
    seen past its own probe, and a leaking feature makes a model look brilliant
    in backtest and lose money live.
    """
    if len(pressure) < 40:
        return (0, 0)
    cut = pressure[int(len(pressure) * 0.6)]["clock_seconds"]
    short_p = [r for r in pressure if r["clock_seconds"] <= cut]
    short_s = [r for r in scoring if r["clock_seconds"] <= cut]
    if len(short_p) < 20 or not short_s:
        return (0, 0)

    early = {r["t_seconds"]: r for r in build_projection_rows(
        short_p, short_s, event_id="X", regulation_seconds=regulation)}
    full = {r["t_seconds"]: r for r in build_projection_rows(
        pressure, scoring, event_id="X", regulation_seconds=regulation)}

    compared = moved = 0
    for t in sorted(set(early) & set(full)):
        compared += 1
        for column in state_columns([early[t]]):
            if early[t][column] != full[t][column]:
                moved += 1
    return (compared, moved)


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

    regulation = _REGULATION.get(args.league, 2400.0)
    games = rows_total = dates_seen = 0
    leak_compared = leak_moved = leak_games = 0
    paces: list[float] = []
    poss_finals: list[float] = []
    fwd600_complete = fwd600_total = 0

    for date_str in _dates(args.start, args.end):
        path = momentum_events_path(root, league_code=args.league, date_str=date_str)
        if not path.exists():
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[verify] UNREADABLE date={date_str} {type(exc).__name__}: {exc}", flush=True)
            continue
        dates_seen += 1

        for event_id, game in (doc.get("games") or {}).items():
            pressure = game.get("pressure") or []
            scoring = game.get("narrator") or []
            if not pressure or not scoring:
                continue
            games += 1

            built = build_projection_rows(pressure, scoring, event_id=str(event_id),
                                          regulation_seconds=regulation)
            rows_total += len(built)
            for row in built:
                paces.append(row["state_pace_per_min"])
                fwd600_total += 1
                if row["fwd_complete_600"]:
                    fwd600_complete += 1
            if built:
                poss_finals.append(built[-1]["state_possessions"])

            compared, moved = leakage_check(pressure, scoring, regulation)
            if compared:
                leak_games += 1
                leak_compared += compared
                leak_moved += moved

    print(f"[verify] SEASON league={args.league} {args.start}..{args.end} "
          f"dates={dates_seen} games={games} projection_rows={rows_total}", flush=True)

    # **THE HEADLINE.** Anything but 0 invalidates every fit built on this table.
    print(f"[verify] LEAKAGE games_checked={leak_games} probes_compared={leak_compared} "
          f"state_fields_that_MOVED={leak_moved} "
          f"{'PASS' if leak_moved == 0 else 'FAIL -- DO NOT FIT ON THIS'}", flush=True)

    if paces:
        paces.sort()
        print(f"[verify] PACE per_min p10={paces[len(paces)//10]:.2f} "
              f"median={statistics.median(paces):.2f} "
              f"p90={paces[len(paces)*9//10]:.2f}", flush=True)
    if poss_finals:
        print(f"[verify] POSSESSIONS_AT_END median={statistics.median(poss_finals):.1f} "
              f"n={len(poss_finals)}", flush=True)
    if fwd600_total:
        share = 100.0 * fwd600_complete / fwd600_total
        # A truncated forward window looks like a low-scoring one. If most rows
        # are incomplete, a naive fit learns "late game means low totals".
        print(f"[verify] FWD_600_COMPLETE {fwd600_complete}/{fwd600_total} "
              f"({share:.1f}%)", flush=True)

    if not games:
        return 3
    return 0 if leak_moved == 0 else 5


if __name__ == "__main__":
    raise SystemExit(main())
