"""Backtest: does the real shrinkage-toward-league-neutral adjustment
(scripts.generate_smartsim2_nfl_preseason_projections.shrunk_rating) improve
or hurt real preseason win-accuracy against real, already-played preseason
games?

Regenerates win-rate predictions for real, completed preseason schedules
entirely in memory (never writes to
data/nfl_source/smartsim2_preseason_projections_*.csv -- this is an
experiment, not a production regeneration) with shrinkage on (the real
week-specific NONSTARTER_PARTICIPATION_SHARE) vs off (plain prior-season
rating, unshrunk), and compares each game's predicted winner against the
real final score already in schedule_preseason_{season}.csv (see
scripts/fetch_nfl_preseason_schedule.py). Same honesty discipline as
scripts/backtest_nfl_injury_adjustment.py: reports the real number, even
if shrinkage doesn't help.

Usage:
  python scripts/backtest_nfl_preseason_projection.py --seasons 2023,2024,2025
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.fetch_nfl_preseason_schedule import preseason_schedule_path
from scripts.generate_smartsim2_nfl_preseason_projections import shrunk_rating
from scripts.generate_smartsim2_nfl_projections import load_pbp_plays
from scripts.generate_smartsim2_nfl_projections import team_rating
from syndicate.features.football.sim_engine.smartsim2.calibration_profile import NFL_CALIBRATION_PROFILE
from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationInput
from syndicate.features.football.sim_engine.smartsim2.game_simulator import simulate_game
from syndicate.features.nfl.preseason_depth import NONSTARTER_PARTICIPATION_SHARE
from syndicate.features.nfl.sources import default_nfl_source_root

DATA_ROOT = default_nfl_source_root()


def real_preseason_games(season: int) -> list[dict]:
    """Every real, completed preseason game for this season -- real
    final scores already sit in schedule_preseason_{season}.csv, no
    separate pbp/box-score source needed (preseason has none, confirmed
    structural)."""
    path = preseason_schedule_path(season, source_root=DATA_ROOT)
    if not path.exists():
        return []
    games: list[dict] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                week = int(row.get("week") or 0)
            except (TypeError, ValueError):
                continue
            if week not in (1, 2, 3, 4):
                continue
            try:
                home_score = int(row.get("home_score") or "")
                away_score = int(row.get("away_score") or "")
            except (TypeError, ValueError):
                continue
            home_team = (row.get("home_team") or "").strip()
            away_team = (row.get("away_team") or "").strip()
            game_id = (row.get("game_id") or "").strip()
            if not game_id or not home_team or not away_team:
                continue
            games.append({"game_id": game_id, "week": week, "home_team": home_team, "away_team": away_team, "home_score": home_score, "away_score": away_score})
    return games


def predicted_home_win_rate(
    home_team: str,
    away_team: str,
    *,
    prior_plays: list[tuple[int, str, str, str, float]],
    nonstarter_share: float,
    seeds: int,
) -> float:
    """Real home win rate across `seeds` simulated games -- share=0.0
    reproduces the plain prior-season-only rating (no shrinkage), any
    other real week share applies the same shrunk_rating() the production
    generator uses. Only win-rate accuracy is scored here (not
    stdev/calibration) -- stdev widening never feeds back into the sim's
    own randomness, only into the reported artifact fields."""
    home_off, home_def, _ = team_rating(home_team, week=1, current_plays=[], prior_plays=prior_plays)
    away_off, away_def, _ = team_rating(away_team, week=1, current_plays=[], prior_plays=prior_plays)
    if nonstarter_share > 0.0:
        home_off, _ = shrunk_rating(home_off, nonstarter_share=nonstarter_share)
        home_def, _ = shrunk_rating(home_def, nonstarter_share=nonstarter_share)
        away_off, _ = shrunk_rating(away_off, nonstarter_share=nonstarter_share)
        away_def, _ = shrunk_rating(away_def, nonstarter_share=nonstarter_share)

    home_wins = 0
    for seed in range(1, seeds + 1):
        sim_input = SmartSim2SimulationInput(
            home_team=home_team,
            away_team=away_team,
            seed=seed,
            home_offense_rating=home_off,
            home_defense_rating=home_def,
            away_offense_rating=away_off,
            away_defense_rating=away_def,
        )
        output = simulate_game(sim_input, profile=NFL_CALIBRATION_PROFILE)
        if output.final_score["home"] > output.final_score["away"]:
            home_wins += 1
    return home_wins / seeds


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seasons", type=str, required=True, help="Comma-separated real completed seasons, e.g. 2023,2024,2025")
    parser.add_argument("--seeds", type=int, default=150)
    args = parser.parse_args()

    seasons = [int(token) for token in args.seasons.split(",") if token.strip()]

    plain_correct = plain_total = shrunk_correct = shrunk_total = 0
    push_games = 0
    disagreements: list[dict] = []

    for season in seasons:
        prior_plays = load_pbp_plays(season - 1)
        games = real_preseason_games(season)
        season_plain_correct = season_shrunk_correct = season_total = 0
        for game in games:
            if game["home_score"] == game["away_score"]:
                push_games += 1
                continue
            real_home_won = game["home_score"] > game["away_score"]
            share = NONSTARTER_PARTICIPATION_SHARE[game["week"]]

            plain_rate = predicted_home_win_rate(game["home_team"], game["away_team"], prior_plays=prior_plays, nonstarter_share=0.0, seeds=args.seeds)
            shrunk_rate = predicted_home_win_rate(game["home_team"], game["away_team"], prior_plays=prior_plays, nonstarter_share=share, seeds=args.seeds)
            plain_pred = plain_rate > 0.5
            shrunk_pred = shrunk_rate > 0.5

            plain_total += 1
            shrunk_total += 1
            season_total += 1
            if plain_pred == real_home_won:
                plain_correct += 1
                season_plain_correct += 1
            if shrunk_pred == real_home_won:
                shrunk_correct += 1
                season_shrunk_correct += 1
            if plain_pred != shrunk_pred:
                disagreements.append({"season": season, "week": game["week"], "game_id": game["game_id"], "real_home_won": real_home_won, "plain_pred": plain_pred, "shrunk_pred": shrunk_pred})

        print(f"season {season} done -- plain {season_plain_correct}/{season_total} shrunk {season_shrunk_correct}/{season_total} -- running totals: plain {plain_correct}/{plain_total} shrunk {shrunk_correct}/{shrunk_total}", flush=True)

    print("=== FINAL ===")
    print(f"games_scored={plain_total} pushes_excluded={push_games}")
    print(f"plain_prior_season_accuracy={plain_correct}/{plain_total} = {plain_correct/plain_total:.4f}" if plain_total else "no games")
    print(f"shrinkage_accuracy={shrunk_correct}/{shrunk_total} = {shrunk_correct/shrunk_total:.4f}" if shrunk_total else "no games")
    print(f"games_where_prediction_flipped={len(disagreements)}")
    for d in disagreements[:15]:
        print(f"  season {d['season']} week {d['week']} {d['game_id']}: real_home_won={d['real_home_won']} plain_pred={d['plain_pred']} shrunk_pred={d['shrunk_pred']}")


if __name__ == "__main__":
    main()
