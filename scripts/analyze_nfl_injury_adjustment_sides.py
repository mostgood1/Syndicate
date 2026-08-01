"""Investigation: the full-season backtest (backtest_nfl_injury_adjustment.py)
showed the injury adjustment slightly UNDERPERFORMS baseline (57.93% vs
59.04% win accuracy on real 2025 games). This isolates whether the offense
adjustment (per-play EPA exclusion/backup-substitution) or the defense
adjustment (sparser credited-splash-play signal) is driving the net
negative, by backtesting each side independently against the same real
games. Never writes to production artifacts -- in-memory only, same as
backtest_nfl_injury_adjustment.py.

Usage:
  python scripts/analyze_nfl_injury_adjustment_sides.py --season 2025
"""
from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.football.sim_engine.smartsim2.calibration_profile import NFL_CALIBRATION_PROFILE
from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationInput
from syndicate.features.football.sim_engine.smartsim2.game_simulator import simulate_game
from syndicate.features.nfl.injury_adjustment import adjust_team_rating_for_injuries
from syndicate.features.nfl.injury_adjustment import position_side
from syndicate.features.nfl.injury_adjustment import _injured_players_for_team
from scripts.generate_smartsim2_nfl_projections import load_pbp_plays
from scripts.generate_smartsim2_nfl_projections import team_rating
from scripts.generate_smartsim2_nfl_projections import week_schedule
from scripts.backtest_nfl_injury_adjustment import real_final_scores


def _adjusted_rating(season, week, team, side, base_rating, *, sides_enabled):
    if side not in sides_enabled:
        return base_rating
    rating, _notes = adjust_team_rating_for_injuries(season=season, week=week, team=team, side=side, base_rating=base_rating)
    return rating


def home_win_rate_for_variant(*, season, week, home_team, away_team, current_plays, prior_plays, seeds, sides_enabled):
    home_off, home_def, _ = team_rating(home_team, week=week, current_plays=current_plays, prior_plays=prior_plays)
    away_off, away_def, _ = team_rating(away_team, week=week, current_plays=current_plays, prior_plays=prior_plays)

    home_off = _adjusted_rating(season, week, home_team, "offense", home_off, sides_enabled=sides_enabled)
    home_def = _adjusted_rating(season, week, home_team, "defense", home_def, sides_enabled=sides_enabled)
    away_off = _adjusted_rating(season, week, away_team, "offense", away_off, sides_enabled=sides_enabled)
    away_def = _adjusted_rating(season, week, away_team, "defense", away_def, sides_enabled=sides_enabled)

    home_wins = 0
    for seed in range(1, seeds + 1):
        sim_input = SmartSim2SimulationInput(
            home_team=home_team, away_team=away_team, seed=seed,
            home_offense_rating=home_off, home_defense_rating=home_def,
            away_offense_rating=away_off, away_defense_rating=away_def,
        )
        output = simulate_game(sim_input, profile=NFL_CALIBRATION_PROFILE)
        if output.final_score["home"] > output.final_score["away"]:
            home_wins += 1
    return home_wins / seeds


def _has_modeled_injury(season, week, team):
    return any(position_side(p["position"]) is not None for p in _injured_players_for_team(season, week, team))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--seeds", type=int, default=150)
    args = parser.parse_args()

    current_plays = load_pbp_plays(args.season)
    prior_plays = load_pbp_plays(args.season - 1)
    final_scores = real_final_scores(args.season)

    variants = {
        "off": frozenset(),
        "offense_only": frozenset({"offense"}),
        "defense_only": frozenset({"defense"}),
        "both": frozenset({"offense", "defense"}),
    }
    correct = {name: 0 for name in variants}
    total = {name: 0 for name in variants}
    games_analyzed = 0

    for week in range(1, 19):
        schedule_rows = week_schedule(args.season, week, current_plays)
        for row in schedule_rows:
            game_id = row["game_id"]
            real = final_scores.get(game_id)
            if real is None:
                continue
            home_score, away_score = real
            if home_score == away_score:
                continue
            real_home_won = home_score > away_score

            has_injury = _has_modeled_injury(args.season, week, row["home_team"]) or _has_modeled_injury(args.season, week, row["away_team"])
            if not has_injury:
                continue
            games_analyzed += 1

            for name, sides_enabled in variants.items():
                win_rate = home_win_rate_for_variant(
                    season=args.season, week=week, home_team=row["home_team"], away_team=row["away_team"],
                    current_plays=current_plays, prior_plays=prior_plays, seeds=args.seeds, sides_enabled=sides_enabled,
                )
                pred_home_win = win_rate > 0.5
                total[name] += 1
                if pred_home_win == real_home_won:
                    correct[name] += 1

        print(f"week {week} done -- games_analyzed_so_far={games_analyzed}", flush=True)

    print("=== FINAL (games with at least one modeled injury only) ===")
    print(f"games_analyzed={games_analyzed}")
    for name in variants:
        if total[name]:
            print(f"{name}: {correct[name]}/{total[name]} = {correct[name]/total[name]:.4f}")


if __name__ == "__main__":
    main()
