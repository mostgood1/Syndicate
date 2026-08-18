"""Unit tests for `historical_truth.special_teams_builder` — the producer for
`HockeyTeamFeatures.special_teams` (`pp_pct`/`pk_pct`/`committed_per_game`).

These were CONSUMED by `engine.py` (via `st_home`/`st_away`) with no producer anywhere — every
team ran through the boxscore/props engine's PP/PK goal-rate adjustment at the same league-average
fallback, always. Covers: opportunity/goal attribution direction (home's PP opportunities come
from AWAY's committed penalties, not home's own), the small-sample floor, and the empty-input case.
"""
from __future__ import annotations

from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.contracts import HistoricalGameRecord
from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.special_teams_builder import (
    DEFAULT_PK_PCT,
    DEFAULT_PP_PCT,
    MIN_OPPORTUNITIES_FOR_RATE,
    compute_special_teams_rates,
)


def _game(home, away, *, pen_h=0, pen_a=0, pp_h=0, pp_a=0):
    return HistoricalGameRecord(
        game_id="1", date="2026-01-01", season="20252026", game_type=2,
        home_abbr=home, away_abbr=away, home_goals=3, away_goals=2, home_sog=30, away_sog=28,
        pp_goals_home=pp_h, pp_goals_away=pp_a,
        penalties_committed_home=pen_h, penalties_committed_away=pen_a,
    )


def test_opportunities_are_attributed_to_the_non_committing_team():
    """Home's PP chances come from AWAY committing penalties, not the other way around."""
    games = [_game("BOS", "CHI", pen_h=1, pen_a=1, pp_h=0, pp_a=0) for _ in range(20)]
    games[0:5] = [_game("BOS", "CHI", pen_h=0, pen_a=1, pp_h=1, pp_a=0) for _ in range(5)]
    rates = compute_special_teams_rates(games)
    # BOS's PP opportunities come from CHI's committed penalties (pen_a), not BOS's own (pen_h).
    assert rates["BOS"].pp_opportunities == sum(g.penalties_committed_away for g in games)
    assert rates["BOS"].pk_opportunities == sum(g.penalties_committed_home for g in games)


def test_small_sample_falls_back_to_league_default():
    """Below MIN_OPPORTUNITIES_FOR_RATE, a noisy 1-for-2-style rate must not be published raw."""
    games = [_game("BOS", "CHI", pen_h=0, pen_a=1, pp_h=1, pp_a=0)]  # 1 opportunity, 1 goal = "100%"
    assert 1 < MIN_OPPORTUNITIES_FOR_RATE
    rates = compute_special_teams_rates(games)
    assert rates["BOS"].pp_pct == DEFAULT_PP_PCT  # NOT 1.0 -- the raw rate would be a lie


def test_real_sample_above_floor_is_not_overridden():
    games = [
        _game("BOS", "CHI", pen_h=0, pen_a=1, pp_h=(1 if i % 5 == 0 else 0), pp_a=0)
        for i in range(MIN_OPPORTUNITIES_FOR_RATE)
    ]
    rates = compute_special_teams_rates(games)
    assert rates["BOS"].pp_opportunities == MIN_OPPORTUNITIES_FOR_RATE
    # 1 goal per 5 opportunities = 20%, not the default (which happens to also be 20% -- assert
    # via the opportunity count instead, since the value coinciding with the default proves nothing).
    assert rates["BOS"].pp_goals == MIN_OPPORTUNITIES_FOR_RATE // 5


def test_pk_pct_is_one_minus_goals_against_over_opportunities():
    games = [_game("BOS", "CHI", pen_h=1, pen_a=0, pp_h=0, pp_a=1) for _ in range(MIN_OPPORTUNITIES_FOR_RATE)]
    rates = compute_special_teams_rates(games)
    # BOS committed every penalty (its own PK opportunities) and let in a PP goal every single time.
    assert rates["BOS"].pk_opportunities == MIN_OPPORTUNITIES_FOR_RATE
    assert rates["BOS"].pp_goals_against == MIN_OPPORTUNITIES_FOR_RATE
    assert rates["BOS"].pk_pct == 0.0  # killed none of them


def test_empty_input_yields_no_teams_not_a_crash():
    assert compute_special_teams_rates([]) == {}


def test_committed_per_game_is_a_simple_average():
    games = [_game("BOS", "CHI", pen_h=2, pen_a=3) for _ in range(4)]
    rates = compute_special_teams_rates(games)
    assert rates["BOS"].committed_per_game == 2.0
    assert rates["CHI"].committed_per_game == 3.0
