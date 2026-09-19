"""In-play rows are not sized on market fair alone (lane layer2-live-scorecard-gate).

Every production NCAAF row is `market_fair` -- its model edge is withheld by a
measured gate -- so once the sport is allowlisted, an in-play NCAAF row is sized
on the dispersion between books captured at different moments of the game.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.portfolio_commit import commit_portfolio
from syndicate.features.shared.portfolio_settings import PortfolioSettings


# THESE TESTS USE NCAAF AS A SAMPLE SPORT FOR A ROW THAT CARRIES A MODEL EDGE.
# Since 2026-09-18 NCAAF sizes on price even with a sim edge
# (`portfolio_commit._PRICE_BASIS_SPORTS_DEFAULT`, user decision "Show edges,
# size on price"); that rule has its own tests in
# `test_portfolio_price_basis_sports.py`. Cleared here so these keep testing
# the model-edge mechanics they were written for.
@pytest.fixture(autouse=True)
def _sim_sizing_legacy(monkeypatch):
    """These tests pin the sizing MECHANICS of a model that is allowed to size.
    WHETHER a model may size (only one measured to beat the market) is
    `test_portfolio_sim_skill_gate.py`'s business (lane `sim-sizing-skill-gate`)."""
    monkeypatch.setenv("SYNDICATE_PORTFOLIO_SIM_SIZING", "legacy")


@pytest.fixture(autouse=True)
def _model_edge_sizing_for_sample_sport(monkeypatch):
    monkeypatch.setenv("SYNDICATE_PORTFOLIO_PRICE_BASIS_SPORTS", "none")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("SYNDICATE_PORTFOLIO_MARKET_FAIR_SPORTS", "ncaaf")
    monkeypatch.delenv("SYNDICATE_PORTFOLIO_IN_PLAY_MARKET_FAIR", raising=False)


def _settings(**overrides) -> PortfolioSettings:
    base = {
        "bankroll_units": 1000.0,
        "max_slate_exposure_fraction": 1.0,
        "min_ev_pct": -100.0,
        "max_positions": 50,
        "min_stake_units": 0.0,
    }
    base.update(overrides)
    return PortfolioSettings(**base)


def _row(**overrides):
    # Shape of the 2026-09-12 WF @ PUR row that motivated this rule.
    row = {
        "sport": "ncaaf",
        "event_id": "5a8d98c3147d18b683d90a536e76eb64",
        "kind": "game",
        "market": "spreads",
        "segment": "full",
        "line": -6.5,
        "player_name": None,
        "home_team": "Purdue Boilermakers",
        "away_team": "Wake Forest Demon Deacons",
        "commence_time": "2026-09-12T16:00:00Z",
        "side": "away",
        "quote": {"price": 107, "bookmaker": "prophetx"},
        "ev_pct": 4.7563,
        "model_edge_pct": None,
        "score": {"score": 4.28, "price_reliability": 1.0},
        "game_state": "live",
        "is_live": True,
        "market_state": "live",
    }
    row.update(overrides)
    return row


def test_an_in_play_market_fair_row_is_refused_by_name():
    plan = commit_portfolio([_row()], selected_date="2026-09-12", settings=_settings())
    assert plan["positions"] == []
    assert plan["refusals"] == {"in_play_market_fair": 1}


def test_the_same_row_before_kickoff_is_still_sized():
    # The reachability half: without this, a rule that refused every market-fair
    # row would pass the test above.
    plan = commit_portfolio(
        [_row(game_state="pregame", is_live=False, market_state="pregame")],
        selected_date="2026-09-12",
        settings=_settings(),
    )
    assert plan["totals"]["positions"] == 1
    assert "in_play_market_fair" not in plan["refusals"]


def test_an_in_play_row_that_says_live_only_through_is_live_is_refused():
    plan = commit_portfolio(
        [_row(game_state=None, market_state=None, is_live=True)],
        selected_date="2026-09-12",
        settings=_settings(),
    )
    assert plan["refusals"].get("in_play_market_fair") == 1


def test_an_in_play_row_with_a_model_edge_is_not_this_rules_business(monkeypatch):
    plan = commit_portfolio(
        [_row(model_edge_pct=3.2)], selected_date="2026-09-12", settings=_settings()
    )
    assert "in_play_market_fair" not in plan["refusals"]


def test_a_sport_not_allowlisted_keeps_its_existing_refusal(monkeypatch):
    monkeypatch.setenv("SYNDICATE_PORTFOLIO_MARKET_FAIR_SPORTS", "")
    plan = commit_portfolio([_row()], selected_date="2026-09-12", settings=_settings())
    assert plan["refusals"] == {"no_model_edge_pct": 1}


def test_only_the_exact_word_allow_reverts(monkeypatch):
    monkeypatch.setenv("SYNDICATE_PORTFOLIO_IN_PLAY_MARKET_FAIR", "allow")
    plan = commit_portfolio([_row()], selected_date="2026-09-12", settings=_settings())
    assert plan["totals"]["positions"] == 1
    for value in ("yes", "true", "1", "ALLOW ", "admit"):
        monkeypatch.setenv("SYNDICATE_PORTFOLIO_IN_PLAY_MARKET_FAIR", value)
        plan = commit_portfolio([_row()], selected_date="2026-09-12", settings=_settings())
        expected = 1 if value.strip().lower() == "allow" else 0
        assert plan["totals"]["positions"] == expected, value
