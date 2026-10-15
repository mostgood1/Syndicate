"""Two in-play market-fair cells are staked; every other in-play market-fair row is still refused.

Lane `live-market-fair-cells`, user 2026-10-15: "go ahead and stake live NFL props and NCAAF totals". The cells are
the only two positive under both fairs in the 10-14 live re-grade; families are that read's own definitions.
"""
from __future__ import annotations

import pytest

from syndicate.features.shared import portfolio_commit as pc
from syndicate.features.shared.portfolio_commit import commit_portfolio
from syndicate.features.shared.portfolio_settings import PortfolioSettings


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("SYNDICATE_PORTFOLIO_FAIR_NOISE_PP", "0")
    monkeypatch.setenv("SYNDICATE_PORTFOLIO_MARKET_FAIR_SPORTS", "nfl,ncaaf,nhl,soccer")
    monkeypatch.delenv("SYNDICATE_PORTFOLIO_IN_PLAY_MARKET_FAIR", raising=False)
    monkeypatch.delenv("SYNDICATE_PORTFOLIO_IN_PLAY_MARKET_FAIR_CELLS", raising=False)


def _settings() -> PortfolioSettings:
    return PortfolioSettings(bankroll_units=1000.0, max_slate_exposure_fraction=1.0, min_ev_pct=-100.0,
                             max_positions=50, min_stake_units=0.0)


def _row(**overrides):
    row = {"sport": "ncaaf", "event_id": "e1", "kind": "game", "market": "totals", "segment": "full", "line": 51.5,
           "player_name": None, "home_team": "Purdue Boilermakers", "away_team": "Wake Forest Demon Deacons",
           "commence_time": "2026-10-17T16:00:00Z", "side": "over", "quote": {"price": 107, "bookmaker": "prophetx"},
           "ev_pct": 4.7, "model_edge_pct": None, "score": {"score": 4.28, "price_reliability": 1.0},
           "game_state": "live", "is_live": True, "market_state": "live"}
    row.update(overrides)
    return row


def _nfl_prop(**overrides):
    return _row(sport="nfl", kind="prop", market="Receptions", player_name="Tory Horton", line=3.5, side="over", **overrides)


def _plan(rows):
    return commit_portfolio(rows, selected_date="2026-10-17", settings=_settings())


def test_the_two_cells_are_staked_in_play():
    for row in (_row(), _row(segment="h1", line=24.5), _row(market="alternate_totals", line=48.5), _nfl_prop()):
        plan = _plan([row])
        assert plan["totals"]["positions"] == 1, (row["sport"], row["market"], row["segment"])
        assert "in_play_market_fair" not in plan["refusals"]


@pytest.mark.parametrize("row", [
    _row(market="spreads", line=-6.5, side="away"),                       # NCAAF spreads: negative in 3 of 3 reads
    _row(market="h2h", line=None, side="home"),
    _row(sport="nfl", market="totals"),                                   # NFL game lines stay refused
    _row(sport="nfl", market="spreads", line=-3.5),
    _row(sport="nhl", kind="prop", market="SOG", player_name="Martin Necas", line=2.5),     # props outside NFL
    _row(sport="soccer", market="alternate_totals_corners", line=9.5),    # corners are not "totals"
    _row(sport="ncaaf", kind="prop", market="Passing Yards", player_name="Somebody", line=220.5),
])
def test_every_other_in_play_market_fair_cell_is_still_refused(row):
    assert _plan([row])["refusals"] == {"in_play_market_fair": 1}


def test_pregame_and_model_edge_rows_are_untouched():
    assert _plan([_row(market="spreads", game_state="pregame", is_live=False, market_state="pregame")])["totals"]["positions"] == 1
    assert "in_play_market_fair" not in _plan([_row(market="spreads", model_edge_pct=3.2)])["refusals"]


def test_none_restores_the_full_refusal_and_an_unparseable_value_admits_nothing(monkeypatch):
    for value in ("none", "off", "nfl-prop", "nfl:props", "everything"):
        monkeypatch.setenv("SYNDICATE_PORTFOLIO_IN_PLAY_MARKET_FAIR_CELLS", value)
        assert _plan([_nfl_prop()])["refusals"] == {"in_play_market_fair": 1}, value
        assert _plan([_row()])["refusals"] == {"in_play_market_fair": 1}, value


def test_the_cells_can_be_named_explicitly(monkeypatch):
    monkeypatch.setenv("SYNDICATE_PORTFOLIO_IN_PLAY_MARKET_FAIR_CELLS", "nhl:prop")
    assert _plan([_row(sport="nhl", kind="prop", market="SOG", player_name="Martin Necas", line=2.5)])["totals"]["positions"] == 1
    assert _plan([_nfl_prop()])["refusals"] == {"in_play_market_fair": 1}


def test_family_matches_the_live_regrade_definition():
    assert pc._market_fair_family({"player_name": "X", "market": "totals"}) == "prop"
    assert pc._market_fair_family({"market": "totals_h1"}) == "totals"
    assert pc._market_fair_family({"market": "alternate_totals"}) == "totals"
    assert pc._market_fair_family({"market": "alternate_totals_corners"}) == "other_game"
    assert pc._market_fair_family({"market": "alternate_spreads"}) == "spreads"
    assert pc._market_fair_family({"market": "h2h_3_way"}) == "h2h"
    assert pc.IN_PLAY_MARKET_FAIR_CELLS == {("nfl", "prop"), ("ncaaf", "totals")}
