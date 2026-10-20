"""The $5-$10 live stake band (lane `live-stake-band`, user 2026-10-20).

REACHABILITY FIRST (`model_engine_standard`): the flag is shown to change the
live plan (`off != on`) on the real call path, `commit_live_venue_plan`, before
anything is asserted about the numbers.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import live_stake_band as band
from syndicate.features.shared import venue_capital as vc
from syndicate.features.shared.portfolio_settings import PortfolioSettings

_DATE = "2026-10-20"
_TICKER = "KXMLBGAME-26OCT19CLETB-TB"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "file")
    (tmp_path / "intelligence").mkdir(parents=True, exist_ok=True)
    for name in (
        band.MODE_ENV,
        "SYNDICATE_LIVE_STAKE_BAND_MIN_DOLLARS",
        "SYNDICATE_LIVE_STAKE_BAND_MAX_DOLLARS",
        "SYNDICATE_LIVE_STAKE_BAND_KELLY_AT_MAX",
        vc.COMPOUNDING_MODE_ENV,
        "SYNDICATE_COMPOUNDING_MIN_STAKE",
        "SYNDICATE_COMPOUNDING_BANKROLL_FRACTION",
        "SYNDICATE_COMPOUNDING_BANKROLL_MAX_DOLLARS",
    ):
        monkeypatch.delenv(name, raising=False)
    yield


# ---- config ---------------------------------------------------------------


def test_absent_is_off():
    assert band.band_config()["on"] is False


def test_on_uses_the_users_band(monkeypatch):
    monkeypatch.setenv(band.MODE_ENV, "on")
    cfg = band.band_config()
    assert cfg["on"] is True
    assert (cfg["min_dollars"], cfg["max_dollars"], cfg["kelly_at_max"]) == (5.0, 10.0, 0.05)


@pytest.mark.parametrize(
    "env, reason",
    [
        ({"SYNDICATE_LIVE_STAKE_BAND_MIN_DOLLARS": "five"}, "unparseable_number"),
        ({"SYNDICATE_LIVE_STAKE_BAND_MAX_DOLLARS": "-1"}, "unparseable_number"),
        ({"SYNDICATE_LIVE_STAKE_BAND_MIN_DOLLARS": "12"}, "min_above_max"),
        ({"SYNDICATE_LIVE_STAKE_BAND_KELLY_AT_MAX": "2"}, "kelly_at_max_above_one"),
    ],
)
def test_an_unusable_number_turns_the_band_off_not_guessed(monkeypatch, env, reason):
    monkeypatch.setenv(band.MODE_ENV, "on")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    cfg = band.band_config()
    assert cfg["on"] is False and cfg["invalid"] == reason


def test_a_value_other_than_on_is_off(monkeypatch):
    monkeypatch.setenv(band.MODE_ENV, "yes")
    assert band.band_config()["on"] is False


# ---- the rule, on the 10-20 plan's two positions ---------------------------


@pytest.mark.parametrize(
    "full_kelly, dollars",
    [(0.0047, 5.47), (0.0317, 8.17), (0.05, 10.0), (0.09, 10.0), (0.0, 5.0)],
)
def test_stake_scales_with_full_kelly_inside_the_band(monkeypatch, full_kelly, dollars):
    monkeypatch.setenv(band.MODE_ENV, "on")
    assert band.band_stake(full_kelly, band.band_config()) == pytest.approx(dollars, abs=0.005)


# ---- on the real call path -------------------------------------------------


def _settings(**overrides) -> PortfolioSettings:
    values = dict(
        bankroll_units=1000.0, max_slate_exposure_fraction=1.0, min_ev_pct=-100.0,
        max_positions=50, min_stake_units=1.0,
    )
    values.update(overrides)
    return PortfolioSettings(**values)


def _row(event_id, *, score=5.0):
    return {
        "sport": "mlb", "event_id": event_id, "kind": "game", "market": "h2h",
        "segment": "full_game", "line": None, "player_name": None,
        "home_team": "Home", "away_team": "Away", "commence_time": "2026-10-20T23:05:00Z",
        "side": "home", "quote": {"price": -110, "bookmaker": "kalshi"},
        "ev_pct": 4.5, "model_edge_pct": 3.2,
        "score": {"score": score, "price_reliability": 0.82},
        "venue": "kalshi", "price_source": "venue_feed", "venue_ticker": _TICKER,
    }


def _resolver(bankroll, shard_cash):
    return lambda position: {"known": True, "bankroll": bankroll, "capital": 465.37, "shard": 0, "shard_cash": shard_cash}


def _plan(**kwargs):
    from pipeline.portfolio_commit import commit_live_venue_plan

    return commit_live_venue_plan(
        [_row("g1"), _row("g2", score=4.0)], selected_date=_DATE, settings=_settings(), venue="kalshi", **kwargs
    )


def test_band_reaches_the_live_plan_off_differs_from_on(monkeypatch):
    off = _plan()
    assert off["positions"], "fixture must commit positions or this proves nothing"
    monkeypatch.setenv(band.MODE_ENV, "on")
    on = _plan()
    off_stakes = [p["stake_dollars"] for p in off["positions"]]
    on_stakes = [p["stake_dollars"] for p in on["positions"]]
    assert off_stakes != on_stakes
    assert len(on_stakes) == len(off_stakes)
    for position in on["positions"]:
        assert 5.0 <= position["stake_dollars"] <= 10.0
        assert position["stake_dollars"] == pytest.approx(
            band.band_stake(position["sizing"]["kelly_fraction"], band.band_config()), abs=0.01
        )
    assert on["totals"]["staked_dollars"] == pytest.approx(sum(on_stakes), abs=0.01)
    assert sum(on["refusals"].values()) + len(on["positions"]) == on["rows_in"]
    assert on["stake_band"]["positions_out"] == len(on_stakes)


def test_band_off_leaves_the_plan_exactly_as_today():
    plan = _plan()
    assert "stake_band" not in plan


def test_band_does_not_touch_the_paper_book(monkeypatch):
    """The band lives in the LIVE plan only; `commit_portfolio` (paper2's sizer) is unchanged."""
    from syndicate.features.shared.portfolio_commit import commit_portfolio

    rows = [_row("g1"), _row("g2", score=4.0)]
    off = commit_portfolio(rows, selected_date=_DATE, settings=_settings(), prefer_placeable=True)
    monkeypatch.setenv(band.MODE_ENV, "on")
    on = commit_portfolio(rows, selected_date=_DATE, settings=_settings(), prefer_placeable=True)
    assert [p["stake_dollars"] for p in on["positions"]] == [p["stake_dollars"] for p in off["positions"]]


def test_compounding_on_plus_band_keeps_the_bets_compounding_would_refuse(monkeypatch):
    """The 10-20 failure: shard-cash compounding sized both under $1 and refused them."""
    monkeypatch.setenv(vc.COMPOUNDING_MODE_ENV, "on")
    resolver = _resolver(1.0, 170.0)   # bankroll $1 -> every compounded stake ~ $0.01
    refused = _plan(bankroll_resolver=resolver)
    assert refused["positions"] == []
    assert refused["refusals"].get("below_min_stake_compounded") == 2

    monkeypatch.setenv(band.MODE_ENV, "on")
    kept = _plan(bankroll_resolver=resolver)
    assert len(kept["positions"]) == 2
    assert "below_min_stake_compounded" not in kept["refusals"]
    for position in kept["positions"]:
        assert 5.0 <= position["stake_dollars"] <= 10.0
        assert position["stake_band"]["funding_cash"] == 170.0


def test_band_also_overrides_the_one_contract_floor(monkeypatch):
    monkeypatch.setenv(vc.COMPOUNDING_MODE_ENV, "on")
    monkeypatch.setenv("SYNDICATE_COMPOUNDING_MIN_STAKE", "floor_one_contract")
    monkeypatch.setenv(band.MODE_ENV, "on")
    plan = _plan(bankroll_resolver=_resolver(1.0, 170.0))
    assert len(plan["positions"]) == 2
    for position in plan["positions"]:
        assert 5.0 <= position["stake_dollars"] <= 10.0


def test_unknown_capital_still_refuses_with_the_band_on(monkeypatch):
    monkeypatch.setenv(vc.COMPOUNDING_MODE_ENV, "on")
    monkeypatch.setenv(band.MODE_ENV, "on")
    plan = _plan(bankroll_resolver=lambda position: {"known": False, "reason": "stale_reading"})
    assert plan["positions"] == []
    assert plan["refusals"].get("compounding_bankroll_unknown") == 2


def test_cash_under_the_floor_refuses_by_name(monkeypatch):
    monkeypatch.setenv(vc.COMPOUNDING_MODE_ENV, "on")
    monkeypatch.setenv(band.MODE_ENV, "on")
    plan = _plan(bankroll_resolver=_resolver(1.0, 3.0))   # shard holds $3, under the $5 floor
    assert plan["positions"] == []
    assert plan["refusals"].get(band.REFUSAL_EXCEEDS_FUNDING) == 2
    assert sum(plan["refusals"].values()) + len(plan["positions"]) == plan["rows_in"]


def test_cash_inside_the_band_trims_the_stake_to_the_cash(monkeypatch):
    monkeypatch.setenv(vc.COMPOUNDING_MODE_ENV, "on")
    monkeypatch.setenv(band.MODE_ENV, "on")
    monkeypatch.setenv("SYNDICATE_LIVE_STAKE_BAND_KELLY_AT_MAX", "0.0001")  # every row at $10
    plan = _plan(bankroll_resolver=_resolver(1.0, 7.0))
    assert [p["stake_dollars"] for p in plan["positions"]] == [7.0, 7.0]
    assert plan["stake_band"]["trimmed_to_funding"] == 2


def test_a_position_without_a_kelly_is_refused_not_guessed(monkeypatch):
    monkeypatch.setenv(band.MODE_ENV, "on")
    plan = {"positions": [{"position_key": "k", "sport": "nba", "market": "player_points", "stake_dollars": 1.0}],
            "totals": {}}
    refusals = {}
    band.apply_live_stake_band(plan, venue="kalshi", refusals=refusals, by_market={}, by_sport={})
    assert plan["positions"] == [] and refusals == {band.REFUSAL_NO_KELLY: 1}
    assert plan["stake_band"]["refused_keys"] == ["k"]


def test_the_10_20_positions_land_where_the_user_saw_them(monkeypatch):
    """DEL -3.5 (full Kelly 0.0047) and Maxey U24.5 (0.0317), as the fleet's plan recorded them."""
    monkeypatch.setenv(band.MODE_ENV, "on")
    positions = [
        {"position_key": "del", "sport": "ncaaf", "market": "spreads", "stake_dollars": 1.18,
         "sizing": {"kelly_fraction": 0.0047}, "compounding": {"known": True, "shard_cash": 170.0, "capital": 465.37}},
        {"position_key": "maxey", "sport": "nba", "market": "player_points", "stake_dollars": 1.98,
         "sizing": {"kelly_fraction": 0.0317}, "compounding": {"known": True, "shard_cash": 245.33, "capital": 465.37}},
    ]
    plan = {"positions": positions, "totals": {}}
    band.apply_live_stake_band(plan, venue="kalshi", refusals={}, by_market={}, by_sport={})
    assert {p["position_key"]: p["stake_dollars"] for p in plan["positions"]} == {
        "del": pytest.approx(5.47, abs=0.005), "maxey": pytest.approx(8.17, abs=0.005),
    }
