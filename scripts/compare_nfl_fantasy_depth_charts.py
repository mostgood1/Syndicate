"""What did training camp actually change?

Rebuilds the draft board twice from two different depth-chart snapshots and
diffs them. The point is to make "the depth chart is stale" a MEASURABLE claim
rather than a worry: if a three-week-old chart and today's produce the same
board, the staleness did not matter; if they do not, this says exactly which
players moved and by how much.

    python scripts/compare_nfl_fantasy_depth_charts.py --before 2026-08-02

``--before`` / ``--after`` are EXCLUSIVE upper bounds, matching
``latest_depth_chart``'s cutoff semantics: the newest snapshot strictly before
the given date is used.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from syndicate.features.nfl.fantasy_draft_board import DEFAULT_LEAGUE  # noqa: E402
from syndicate.features.nfl.fantasy_draft_board import build_draft_board  # noqa: E402
from syndicate.features.nfl.fantasy_players import latest_depth_chart  # noqa: E402
from syndicate.features.nfl.fantasy_players import load_fantasy_players  # noqa: E402
from syndicate.features.nfl.fantasy_projection import DEFAULT_CONFIG  # noqa: E402
from syndicate.features.nfl.fantasy_projection import _history_seasons  # noqa: E402
from syndicate.features.nfl.fantasy_projection import league_rates  # noqa: E402
from syndicate.features.nfl.fantasy_projection import project_team  # noqa: E402
from syndicate.features.nfl.fantasy_scoring import resolve_scoring  # noqa: E402


def board_for(season: int, scoring, cutoff: str | None):
    """Project the whole league with the depth chart as it stood at *cutoff*."""
    league = league_rates(_history_seasons(season, len(DEFAULT_CONFIG.season_recency_weights)))
    players = load_fantasy_players(season, depth_chart_as_of=cutoff)
    teams = sorted({player.team for player in players if player.team})
    projections = []
    for team in teams:
        projections.extend(
            project_team(season, team, scoring, league, DEFAULT_CONFIG, None, None, cutoff)
        )
    projections.sort(key=lambda entry: -entry.fantasy_points)
    return build_draft_board(projections, DEFAULT_LEAGUE)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--scoring", default="ppr")
    parser.add_argument("--before", required=True, help="exclusive ISO bound, e.g. 2026-08-02")
    parser.add_argument("--after", default=None, help="exclusive ISO bound; default = current cutoff")
    parser.add_argument("--top", type=int, default=200, help="report players inside this rank in either board")
    parser.add_argument("--out", default="reports/nfl_fantasy_depth_chart_diff.json")
    args = parser.parse_args()

    scoring = resolve_scoring(args.scoring)

    _, before_stamp = latest_depth_chart(args.season, args.before)
    _, after_stamp = latest_depth_chart(args.season, args.after)
    if before_stamp == after_stamp:
        print(f"Both cutoffs resolve to the SAME snapshot ({before_stamp}) -- nothing to compare.")
        return 1

    before = {row.player_id: row for row in board_for(args.season, scoring, args.before)}
    after = {row.player_id: row for row in board_for(args.season, scoring, args.after)}

    print(f"=== depth chart {before_stamp}  ->  {after_stamp} ===")
    print(f"{scoring.label}, {DEFAULT_LEAGUE.label}")
    print()

    moves = []
    for player_id, row in after.items():
        old = before.get(player_id)
        if old is None:
            if row.rank <= args.top:
                moves.append((-999, row, None))
            continue
        if row.rank > args.top and old.rank > args.top:
            continue
        if row.rank != old.rank or abs(row.fantasy_points - old.fantasy_points) > 1.0:
            moves.append((row.rank - old.rank, row, old))

    gone = [old for player_id, old in before.items() if player_id not in after and old.rank <= args.top]

    risers = sorted((m for m in moves if m[2] and m[0] < 0), key=lambda m: m[0])
    fallers = sorted((m for m in moves if m[2] and m[0] > 0), key=lambda m: -m[0])
    fresh = [m for m in moves if m[2] is None]

    def show(label, rows, limit=15):
        if not rows:
            print(f"-- {label}: none --\n")
            return
        print(f"-- {label} ({len(rows)}) --")
        for delta, row, old in rows[:limit]:
            if old is None:
                print(
                    f"   NEW    {row.position:<4}{row.name:<24}{row.team:<4} "
                    f"rank {row.rank:<4} proj {row.fantasy_points}"
                )
            else:
                print(
                    f"   {delta:+5d}  {row.position:<4}{row.name:<24}{row.team:<4} "
                    f"rank {old.rank:<4}-> {row.rank:<4} "
                    f"proj {old.fantasy_points:>6} -> {row.fantasy_points:<6} "
                    f"(depth {old.basis.get('depth_rank')} -> {row.basis.get('depth_rank')})"
                )
        print()

    show("RISERS", risers)
    show("FALLERS", fallers)
    show("NEW to the board", fresh)
    if gone:
        print(f"-- DROPPED off the board ({len(gone)}) --")
        for old in sorted(gone, key=lambda entry: entry.rank)[:10]:
            print(f"   {old.position:<4}{old.name:<24}{old.team:<4} was rank {old.rank}")
        print()

    print(f"{len(moves)} players moved inside the top {args.top}.")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "season": args.season,
                "scoring": scoring.key,
                "before_snapshot": before_stamp,
                "after_snapshot": after_stamp,
                "top": args.top,
                "moves": [
                    {
                        "player_id": row.player_id,
                        "name": row.name,
                        "team": row.team,
                        "position": row.position,
                        "rank_before": old.rank if old else None,
                        "rank_after": row.rank,
                        "points_before": old.fantasy_points if old else None,
                        "points_after": row.fantasy_points,
                        "depth_before": old.basis.get("depth_rank") if old else None,
                        "depth_after": row.basis.get("depth_rank"),
                    }
                    for _, row, old in moves
                ],
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
