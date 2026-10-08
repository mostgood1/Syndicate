"""Passing yards are priced from the QB's full STARTS only, with the blend weight re-fitted on top (0.0).

Lane `nfl-passing-yards-prop-coin`, pre-registered 2026-10-08, shipped on its rule: real 2024 quotes, identical
rows, LL 0.7341 -> 0.7074 and mean P(over) 0.428 -> 0.511 against a 0.500 over-rate.
"""
from __future__ import annotations

import pytest

from syndicate.features.nfl import player_stats as ps
from syndicate.features.nfl import props as P


def _plays(game_id, week, team, attempts, yards_each=7):
    return [{"game_id": game_id, "week": week, "posteam": team, "passer_player_id": pid, "pass_attempt": "1",
             "passing_yards": str(yards_each), "sack": "0", "two_point_attempt": "0"}
            for pid, n in attempts.items() for _ in range(n)]


# QB: relief wk1 (4 of 40 attempts, 28 yds), full starts wk2-4 (35 att, 245 yds each).
_PLAYS = tuple(
    _plays("G1", 1, "ATL", {"OTHER": 36, "QB": 4})
    + _plays("G2", 2, "ATL", {"QB": 35})
    + _plays("G3", 3, "ATL", {"QB": 35})
    + _plays("G4", 4, "ATL", {"QB": 35})
)


@pytest.fixture(autouse=True)
def _fixture(monkeypatch):
    for key in ("SYNDICATE_NFL_QB_STARTS_ONLY_RATE", "SYNDICATE_NFL_QB_STARTS_REFUSAL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(ps, "load_player_plays", lambda season: _PLAYS if season == 2026 else ())
    ps._pass_attempt_shares.cache_clear()
    yield
    ps._pass_attempt_shares.cache_clear()


def test_the_rate_ignores_relief_games():
    mean, sd, n = ps.qb_starts_only_rate(2026, 5, "QB", "passing_yards", "current_season_rolling")
    assert (mean, n) == (245.0, 3)
    assert sd > 0  # shrink_spread gives a positive sd to identical starts


def test_the_all_games_rate_is_dragged_down_by_the_relief_game():
    mean, _sd, n = ps.player_rate(2026, 5, "QB", "passing_yards")
    assert n == 4 and mean < 200


def test_blend_weight_switches_with_the_rate(monkeypatch):
    args = dict(stat="passing_yards", mean=245.0, stdev=60.0, n=3, line=230.5)
    normal = 1.0 - __import__("statistics").NormalDist(245.0, 60.0).cdf(230.5)
    assert P._nfl_prop_model_probability(**args) == pytest.approx(normal)
    monkeypatch.setenv("SYNDICATE_NFL_QB_STARTS_ONLY_RATE", "off")
    assert P._nfl_prop_model_probability(**args) != pytest.approx(normal)


def test_attempts_joined_on_its_own_read():
    """passing_attempts passed its own pre-registered read (2025): starts-only rate, blend w=0.16."""
    assert "passing_attempts" in ps.QB_STARTS_ONLY_RATE_STATS
    assert P._STARTS_ONLY_BLEND_WEIGHT == {"passing_yards": 0.0, "passing_attempts": 0.16}


def _rows(monkeypatch):
    quotes = [{"market": "Passing Yards", "player": "Some Qb", "line": 230.5, "away_team": "New Orleans Saints",
               "home_team": "Atlanta Falcons", "over_price": -110, "under_price": -110}]
    monkeypatch.setattr(P, "_best_price_player_props", lambda season, week: quotes)
    monkeypatch.setattr(P, "resolve_player_id_for_game", lambda *a: ("QB", "test"))
    monkeypatch.setattr(P, "player_team_with_prior", lambda *a: ("Atlanta Falcons", "current_season"))
    monkeypatch.setattr(P, "nfl_game_context_multiplier", lambda *a: 1.0)
    return P.nfl_props_rows_for_week(2026, 5, use_artifact=False)[1]


def test_the_row_builder_prices_from_starts(monkeypatch):
    sims = _rows(monkeypatch)
    assert sims[0]["projected_value"] == pytest.approx(245.0) and sims[0]["sample_games"] == 3


def test_off_is_not_on(monkeypatch):
    monkeypatch.setenv("SYNDICATE_NFL_QB_STARTS_ONLY_RATE", "off")
    sims = _rows(monkeypatch)
    assert sims[0]["sample_games"] == 4 and sims[0]["projected_value"] < 200
