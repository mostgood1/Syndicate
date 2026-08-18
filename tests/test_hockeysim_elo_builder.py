"""Unit tests for `historical_truth.elo_builder` — the producer for `HockeyTeamFeatures.elo_rating`.

`elo_rating` was CONSUMED by `projection.py`'s `_elo_win_prob` with no producer anywhere in the
codebase (`docs/ai_context/model_engine_standard.md` §0's exact alarm shape). These tests cover the
computation this module exists to get right: chronological ordering, no-lookahead pregame ratings
(the only view a backtest may legitimately score against), and the Brier-score helper used to
measure whether the mechanism carries real signal before any blend weight is turned on.
"""
from __future__ import annotations

from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.contracts import HistoricalGameRecord
from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.elo_builder import (
    DEFAULT_INITIAL_RATING,
    brier_score,
    compute_elo_progression,
    compute_elo_ratings,
)


def _game(game_id: str, date: str, home: str, away: str, home_goals: int, away_goals: int) -> HistoricalGameRecord:
    return HistoricalGameRecord(
        game_id=game_id, date=date, season="20252026", game_type=2,
        home_abbr=home, away_abbr=away, home_goals=home_goals, away_goals=away_goals,
        home_sog=30, away_sog=28,
    )


def test_unrated_teams_start_at_the_initial_rating():
    games = [_game("1", "2026-01-01", "BOS", "CHI", 3, 2)]
    final, pregame = compute_elo_progression(games)
    assert pregame[0].home_elo == DEFAULT_INITIAL_RATING
    assert pregame[0].away_elo == DEFAULT_INITIAL_RATING
    # Winner's rating rises, loser's falls, by equal and opposite amounts (zero-sum update).
    assert final["BOS"] > DEFAULT_INITIAL_RATING > final["CHI"]
    assert (final["BOS"] - DEFAULT_INITIAL_RATING) == (DEFAULT_INITIAL_RATING - final["CHI"])


def test_pregame_ratings_have_no_lookahead():
    """A team's SECOND game must see its rating AFTER the first game, not the final season rating.

    This is the property a backtest depends on -- scoring a game with the season's final rating
    (which already knows that game's own outcome) would be lookahead bias, not a measurement.
    """
    games = [
        _game("1", "2026-01-01", "BOS", "CHI", 5, 1),   # BOS blows out CHI
        _game("2", "2026-01-03", "BOS", "NYR", 2, 3),   # BOS's second game
    ]
    final, pregame = compute_elo_progression(games)
    game2 = next(e for e in pregame if e.game_id == "2")
    # BOS's rating entering game 2 must already reflect game 1's result (raised from initial)...
    assert game2.home_elo > DEFAULT_INITIAL_RATING
    # ...but must NOT equal the final rating, which additionally reflects game 2's own loss.
    assert game2.home_elo != final["BOS"]


def test_games_are_processed_in_chronological_order_regardless_of_input_order():
    in_order = [
        _game("1", "2026-01-01", "BOS", "CHI", 3, 1),
        _game("2", "2026-01-05", "BOS", "CHI", 1, 4),
    ]
    reversed_input = list(reversed(in_order))
    final_a, pregame_a = compute_elo_progression(in_order)
    final_b, pregame_b = compute_elo_progression(reversed_input)
    assert final_a == final_b
    assert [e.game_id for e in pregame_a] == [e.game_id for e in pregame_b] == ["1", "2"]


def test_compute_elo_ratings_matches_progression_final():
    games = [_game("1", "2026-01-01", "BOS", "CHI", 4, 2), _game("2", "2026-01-02", "NYR", "BOS", 2, 5)]
    final, _pregame = compute_elo_progression(games)
    assert compute_elo_ratings(games) == final


def test_brier_score_rewards_correct_confident_predictions():
    """A team rated far above its opponent, that then wins, must score BETTER than a coin flip."""
    games = [_game(str(i), f"2026-01-{i:02d}", "BOS", "CHI", 4, 1) for i in range(1, 11)]
    # After several wins BOS is well above CHI; score only the LATER games so the rating gap
    # has had a chance to form (game 1 is a coin flip by construction -- both start equal).
    _final, pregame = compute_elo_progression(games)
    later = pregame[5:]
    b = brier_score(later, scale=400.0, home_advantage=50.0)
    assert b is not None
    assert b < 0.25  # 0.25 is what a constant 50/50 guess scores


def test_brier_score_of_empty_input_is_none_not_a_lie():
    assert brier_score([], scale=400.0, home_advantage=50.0) is None
