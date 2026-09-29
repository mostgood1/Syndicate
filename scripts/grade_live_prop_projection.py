"""Grade a live prop projection against real outcomes, for any ESPN basketball league.

WHAT THIS IS FOR. `syndicate/features/shared/live_prop_grading.py` explains why
the grader is the scarce part: four live-prop methodologies exist across the
platform and only WNBA's has ever been measured. NBA's live probability is a
Normal CDF over a HAND-SET sigma table whose own source comment
(`nba/cards.py:1687-1690`) says it is "NOT backtested against real NBA
outcomes". This produces the number that replaces it.

    py -3 scripts/grade_live_prop_projection.py --sport nba --date 2026-01-15 --reconcile-only
    py -3 scripts/grade_live_prop_projection.py --sport nba --date 2026-01-15 --date 2026-01-16
    py -3 scripts/grade_live_prop_projection.py --sport wnba --date 2026-08-19 --stat rebounds

TWO GATES, both of which can refuse to produce a number:

  1. RECONCILE. Replaying to the buzzer must reproduce the official box exactly,
     per player, for the stat being graded. A game that fails is NOT graded --
     a residual from a replay that does not reconcile is a number about a bug.
     `--reconcile-only` runs this and stops, which is the right first command
     against any new league or any date range you have not used before.

  2. ANCHOR. `project_live_player_stat` REFUSES without a pregame anchor, by
     design -- it will not fall back to the live rate. So a player with no prior
     game in the window is skipped and counted, not projected from thin air.

THE ANCHOR IS BUILT LEAK-FREE, AND THAT IS THE WHOLE REASON THIS IS HONEST.
Games are processed in DATE ORDER and each game's anchor is the player's mean
over their PRIOR games in the window only -- never including the game being
graded, and never a season total that already contains it. This is what a
pregame projection approximates; using anything computed after tip would make
every residual here optimistic and the resulting interval too narrow, which is
the specific way a backtest lies in this direction.

It is NOT production's anchor (production reads that day's published sim). The
residual measured here is therefore an UPPER bound on the projection's error
given a weaker anchor -- stated rather than discovered later. A separate run
against published sim anchors is the way to compare the two, and this script
deliberately does not pretend to be that.

SAMPLING matches production: residuals are taken at CLOCK ticks (every whole
game minute), not at the player's own events. An event-sampled residual is
measured exactly when the player's pace is most inflated, which flatters the
projection for low-count stats; production prices on a tick.
"""
from __future__ import annotations

import argparse
import collections
import json
import statistics
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared import live_prop_grading as grading  # noqa: E402
from syndicate.features.shared.wnba_live_prop_projection import (  # noqa: E402
    project_live_player_stat,
)

STATS = ("points", "rebounds", "assists", "threes")


def _regulation_minutes(spec: grading.LeagueSpec) -> float:
    return spec.regulation_periods * spec.period_minutes


def collect_games(spec: grading.LeagueSpec, dates: list[str], events: list[str]) -> list[tuple[str, dict]]:
    """(event_id, summary) in the order given -- date order for `--date`."""
    ids: list[str] = []
    for date_str in dates:
        try:
            found = grading.event_ids_for_date(spec, date_str)
        except Exception as exc:  # noqa: BLE001 - a bad date must not kill the run
            print(f"  [{date_str}] scoreboard unavailable: {type(exc).__name__}", flush=True)
            continue
        print(f"  [{date_str}] {len(found)} events", flush=True)
        ids.extend(found)
    ids.extend(events)
    out: list[tuple[str, dict]] = []
    for event_id in ids:
        try:
            out.append((event_id, grading.fetch_summary(spec, event_id)))
        except Exception as exc:  # noqa: BLE001
            print(f"  event {event_id}: summary unavailable: {type(exc).__name__}", flush=True)
    return out


def grade(spec: grading.LeagueSpec, games: list[tuple[str, dict]], stat: str) -> dict[str, Any]:
    """Replay every game, gate on reconcile, and residual the projection."""
    # player id -> [(stat_total, minutes), ...] over games ALREADY processed.
    history: dict[str, list[tuple[float, float]]] = collections.defaultdict(list)
    residuals: list[dict[str, Any]] = []
    counts = collections.Counter()
    per_game: list[dict[str, Any]] = []
    regulation = _regulation_minutes(spec)

    for event_id, summary in games:
        state = grading.replay(summary, spec)
        report = grading.reconcile(state)
        reconciled = grading.stat_reconciles(report, stat)
        per_game.append({
            "event": event_id, "players": report["players"],
            f"{stat}_exact": report.get(f"{stat}_exact"),
            "minutes_within": report["minutes_within_tolerance"],
            "reconciled": reconciled,
        })
        if not reconciled:
            counts["games_failed_reconcile"] += 1
            # Still record history: the FINAL box is official regardless of
            # whether the play-by-play replay of it reconciled.
            for aid, row in state["box"].items():
                value = row.get(stat)
                if value is not None:
                    history[aid].append((float(value), float(row.get("minutes") or 0.0)))
            continue
        counts["games_graded"] += 1

        finals = {aid: float(row.get(stat) or 0.0) for aid, row in state["box"].items()}
        end = float(state["end_elapsed"] or regulation) or regulation

        for sample in state["clock_samples"]:
            aid = sample["athlete_id"]
            prior = history.get(aid) or []
            if not prior:
                counts["samples_no_anchor"] += 1
                continue
            anchor_stat = statistics.fmean([p[0] for p in prior])
            anchor_minutes = statistics.fmean([p[1] for p in prior])
            projection = project_live_player_stat(
                current_stat=sample.get(stat),
                minutes_played=sample.get("minutes"),
                pregame_stat=anchor_stat,
                pregame_minutes=anchor_minutes,
                game_minutes_remaining=max(0.0, end - float(sample["elapsed"])),
            )
            projected = projection.get("projected")
            if projected is None:
                counts[f"refused::{projection.get('unavailable_reason')}"] += 1
                continue
            counts["samples_graded"] += 1
            residuals.append({
                "event": event_id,
                "athlete_id": aid,
                "elapsed": sample["elapsed"],
                "minutes_left": max(0.0, end - float(sample["elapsed"])),
                "projected": float(projected),
                "actual_final": finals.get(aid, 0.0),
                "residual": float(projected) - finals.get(aid, 0.0),
                "anchor_games": len(prior),
            })

        for aid, row in state["box"].items():
            value = row.get(stat)
            if value is not None:
                history[aid].append((float(value), float(row.get("minutes") or 0.0)))

    return {"residuals": residuals, "counts": dict(counts), "per_game": per_game}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sport", default="wnba", help=f"one of {sorted(grading.LEAGUES)}")
    parser.add_argument("--date", action="append", default=[], help="YYYY-MM-DD (repeatable, date order)")
    parser.add_argument("--events", default="", help="comma-separated ESPN event ids")
    parser.add_argument("--stat", default="points", choices=STATS)
    parser.add_argument("--reconcile-only", action="store_true",
                        help="run the integrity gate and stop -- no residual")
    parser.add_argument("--min-n", type=int, default=30, help="bucket floor before statistics are shown")
    parser.add_argument("--json-out", default="", help="write the full result here")
    args = parser.parse_args(argv)

    try:
        spec = grading.league(args.sport)
    except KeyError as exc:
        print(exc)
        return 2

    events = [e.strip() for e in args.events.split(",") if e.strip()]
    if not args.date and not events:
        print("nothing to do: pass --date and/or --events")
        return 2

    print(f"league {spec.sport} ({spec.espn_path}, {spec.period_minutes:g}-minute periods)")
    games = collect_games(spec, args.date, events)
    print(f"fetched {len(games)} game summaries\n")
    if not games:
        print("no games fetched -- nothing measured (this is NOT evidence about the projection)")
        return 1

    if args.reconcile_only:
        print(f"{'event':>12} {'players':>8} {'points':>7} {'reb':>5} {'ast':>5} {'3s':>5} {'min':>5}")
        clean = 0
        for event_id, summary in games:
            state = grading.replay(summary, spec)
            report = grading.reconcile(state)
            ok = all(grading.stat_reconciles(report, s) for s in STATS)
            clean += ok
            print(f"{event_id:>12} {report['players']:>8} {report['points_exact']:>7} "
                  f"{report['rebounds_exact']:>5} {report['assists_exact']:>5} "
                  f"{report['threes_exact']:>5} {report['minutes_within_tolerance']:>5}"
                  f"{'' if ok else '   <-- FAILS GATE'}")
        print(f"\ngames reconciling on ALL FOUR stats: {clean}/{len(games)}")
        return 0 if clean else 1

    result = grade(spec, games, args.stat)
    residuals = result["residuals"]
    print(f"=== {spec.sport.upper()} live projection residual -- stat={args.stat} ===")
    print(f"games graded {result['counts'].get('games_graded', 0)}, "
          f"failed reconcile {result['counts'].get('games_failed_reconcile', 0)}, "
          f"samples {len(residuals)}")
    for key in sorted(result["counts"]):
        if key.startswith("refused::") or key == "samples_no_anchor":
            print(f"    {key}: {result['counts'][key]}")
    if not residuals:
        print("\nNO SAMPLES GRADED -- this measures nothing. Widen --date, or run "
              "--reconcile-only to see whether the gate or the anchor is the blocker.")
        return 1

    buckets = grading.residual_by_bucket(residuals, min_n=args.min_n)
    print(f"\n{'minutes left':>14} {'n':>7} {'mean':>9} {'stdev':>9} {'mean|err|':>10}")
    for entry in buckets:
        if "stdev_residual" in entry:
            print(f"{entry['bucket']:>14} {entry['n']:>7} {entry['mean_residual']:>+9.4f} "
                  f"{entry['stdev_residual']:>9.4f} {entry['mean_abs_residual']:>10.4f}")
        else:
            print(f"{entry['bucket']:>14} {entry['n']:>7}   {entry.get('status')}")

    errs = [r["residual"] for r in residuals]
    print(f"\n  pooled: n={len(errs)} mean={statistics.fmean(errs):+.4f} "
          f"stdev={statistics.pstdev(errs):.4f} "
          f"mean|err|={statistics.fmean([abs(e) for e in errs]):.4f}")
    print("\n  NOTE: anchored on PRIOR GAMES IN THIS WINDOW, not on production's "
          "published sim. Treat this spread as an upper bound on the projection's "
          "error, not as production's interval.")

    if args.json_out:
        dest = Path(args.json_out)
        dest.write_text(json.dumps({
            "sport": spec.sport, "stat": args.stat, "counts": result["counts"],
            "buckets": buckets, "per_game": result["per_game"],
            "pooled": {"n": len(errs), "mean": statistics.fmean(errs),
                       "stdev": statistics.pstdev(errs)},
        }, indent=2), encoding="utf-8")
        print(f"\nwrote {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
