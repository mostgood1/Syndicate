"""Backtest: does the real injury-rating adjustment
(syndicate.features.nfl.injury_adjustment) improve or hurt full-season
win-accuracy against real, already-played games?

Regenerates projections for a real, completed season entirely in memory
(never writes to data/nfl_source/smartsim2_projections_*.csv -- this is an
experiment, not a production regeneration) with the adjustment on vs. off,
and compares each game's predicted winner (home_win_rate > 0.5) against the
real final score already in pbp_{season}.csv.

Usage:
  python scripts/backtest_nfl_injury_adjustment.py --season 2025
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.generate_smartsim2_nfl_projections import DATA_ROOT
from scripts.generate_smartsim2_nfl_projections import build_projection
from scripts.generate_smartsim2_nfl_projections import load_pbp_plays
from scripts.generate_smartsim2_nfl_projections import week_schedule
from syndicate.features.nfl.injury_adjustment import _injured_players_for_team
from syndicate.features.nfl.injury_adjustment import position_side


def _has_modeled_injury(season: int, week: int, team: str) -> bool:
    """True if this team has at least one real Out/Doubtful player at a
    modeled position (QB/RB/WR/TE/DL/LB/DB) this week -- if not, the
    adjustment is provably a no-op for this team, so re-simulating the
    'on' variant would just reproduce the 'off' result at real compute
    cost for zero information."""
    return any(position_side(p["position"]) is not None for p in _injured_players_for_team(season, week, team))


def real_final_scores(season: int) -> dict[str, tuple[int, int]]:
    """{game_id: (home_score, away_score)} for every real completed REG game."""
    path = DATA_ROOT / "tracking" / "nflverse" / "pbp" / f"pbp_{season}.csv"
    scores: dict[str, tuple[int, int]] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("season_type") != "REG":
                continue
            game_id = (row.get("game_id") or "").strip()
            if not game_id or game_id in scores:
                continue
            try:
                home_score = int(float(row.get("home_score") or ""))
                away_score = int(float(row.get("away_score") or ""))
            except (TypeError, ValueError):
                continue
            scores[game_id] = (home_score, away_score)
    return scores


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--seeds", type=int, default=300)
    parser.add_argument("--weeks", type=str, default=None, help="Comma-separated week list, default = all weeks 1-18")
    args = parser.parse_args()

    weeks = [int(w) for w in args.weeks.split(",")] if args.weeks else list(range(1, 19))

    current_plays = load_pbp_plays(args.season)
    prior_plays = load_pbp_plays(args.season - 1)
    final_scores = real_final_scores(args.season)

    on_correct = on_total = off_correct = off_total = 0
    push_games = 0
    disagreements = []

    for week in weeks:
        schedule_rows = week_schedule(args.season, week, current_plays)
        for row in schedule_rows:
            game_id = row["game_id"]
            real = final_scores.get(game_id)
            if real is None:
                continue
            home_score, away_score = real
            if home_score == away_score:
                push_games += 1
                continue
            real_home_won = home_score > away_score

            proj_off, _ = build_projection(
                season=args.season, week=week, home_team=row["home_team"], away_team=row["away_team"], game_id=game_id,
                current_plays=current_plays, prior_plays=prior_plays, seeds=args.seeds, apply_injury_adjustment=False,
            )
            off_pred_home_win = proj_off.home_win_rate > 0.5

            has_injury = _has_modeled_injury(args.season, week, row["home_team"]) or _has_modeled_injury(args.season, week, row["away_team"])
            if has_injury:
                proj_on, notes_on = build_projection(
                    season=args.season, week=week, home_team=row["home_team"], away_team=row["away_team"], game_id=game_id,
                    current_plays=current_plays, prior_plays=prior_plays, seeds=args.seeds, apply_injury_adjustment=True,
                )
                on_pred_home_win = proj_on.home_win_rate > 0.5
            else:
                # Provably identical to the "off" variant -- no modeled
                # injury exists for either team this week, so skip the
                # real compute cost of re-simulating an identical result.
                on_pred_home_win = off_pred_home_win
                notes_on = []

            off_total += 1
            on_total += 1
            if off_pred_home_win == real_home_won:
                off_correct += 1
            if on_pred_home_win == real_home_won:
                on_correct += 1
            if off_pred_home_win != on_pred_home_win:
                disagreements.append({"game_id": game_id, "week": week, "real_home_won": real_home_won, "off_pred": off_pred_home_win, "on_pred": on_pred_home_win, "notes": notes_on})

        print(f"week {week} done -- running: off {off_correct}/{off_total} on {on_correct}/{on_total}", flush=True)

    print("=== FINAL ===")
    print(f"games_scored={off_total} pushes_excluded={push_games}")
    print(f"adjustment_off_accuracy={off_correct}/{off_total} = {off_correct/off_total:.4f}" if off_total else "no games")
    print(f"adjustment_on_accuracy={on_correct}/{on_total} = {on_correct/on_total:.4f}" if on_total else "no games")
    print(f"games_where_prediction_flipped={len(disagreements)}")
    for d in disagreements[:15]:
        print(f"  week {d['week']} {d['game_id']}: real_home_won={d['real_home_won']} off_pred_home_win={d['off_pred']} on_pred_home_win={d['on_pred']}")


if __name__ == "__main__":
    main()
