"""Option C (user 2026-10-20): small edges stay small; the band sizes the rest.

`SYNDICATE_LIVE_SMALL_EDGE_FRACTION` does two things, and both are shown to
change the output (`off != on`) before anything is asserted about the numbers:

1. the LIVE plan stops applying the fixed $1-of-$1,000 minimum -- but only with
   compounding `on` and a one-contract minimum, so the row is sized by
   compounding's floor rather than handed to the fixed bankroll;
2. the band leaves a position under that stake fraction at its compounded stake
   instead of lifting it to $5+.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import live_stake_band as band
from syndicate.features.shared import venue_capital as vc
from syndicate.features.shared.portfolio_settings import PortfolioSettings


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in (
        band.SMALL_EDGE_ENV,
        band.MODE_ENV,
        vc.COMPOUNDING_MODE_ENV,
        "SYNDICATE_COMPOUNDING_MIN_STAKE",
        "SYNDICATE_COMPOUNDING_BASIS",
    ):
        monkeypatch.delenv(name, raising=False)
    yield


def _position(key, fraction, stake, kelly):
    return {
        "position_key": key, "sport": "ncaaf", "market": "totals",
        "stake_fraction": fraction, "stake_dollars": stake,
        "sizing": {"kelly_fraction": kelly},
        "compounding": {"known": True, "capital": 465.37, "shard_cash": 170.0},
    }


def _band(plan_positions):
    plan = {"positions": plan_positions, "totals": {}}
    refusals = {}
    band.apply_live_stake_band(plan, venue="kalshi", refusals=refusals, by_market={}, by_sport={})
    return plan, refusals


# ---- the band's line -------------------------------------------------------


def test_small_edge_line_reaches_the_band_off_differs_from_on(monkeypatch):
    monkeypatch.setenv(band.MODE_ENV, "on")
    rows = lambda: [_position("tiny", 0.0005, 0.48, 0.004), _position("ok", 0.00115, 0.54, 0.0046)]
    off, _ = _band(rows())
    monkeypatch.setenv(band.SMALL_EDGE_ENV, "0.001")
    on, refusals = _band(rows())
    off_stakes = {p["position_key"]: p["stake_dollars"] for p in off["positions"]}
    on_stakes = {p["position_key"]: p["stake_dollars"] for p in on["positions"]}
    assert off_stakes["tiny"] >= 5.0                    # without the line the band lifts it
    assert on_stakes["tiny"] == pytest.approx(0.48)     # with it, one contract stays one contract
    assert on_stakes["ok"] == off_stakes["ok"] >= 5.0   # at or over the line: unchanged
    assert on["stake_band"]["left_below_small_edge_fraction"] == 1
    assert refusals == {}


@pytest.mark.parametrize("raw", ["", "0", "-0.001", "1", "2", "abc"])
def test_an_unusable_line_is_no_line(monkeypatch, raw):
    monkeypatch.setenv(band.SMALL_EDGE_ENV, raw)
    assert band.small_edge_fraction() is None


# ---- the live plan's fixed minimum -----------------------------------------


def _settings():
    return PortfolioSettings(
        bankroll_units=1000.0, max_slate_exposure_fraction=1.0, min_ev_pct=-100.0,
        max_positions=50, min_stake_units=1.0,
    )


def _captured_min_stake(monkeypatch):
    from pipeline import portfolio_commit as pc

    seen = {}

    def _fake_commit(rows, *, selected_date, settings, settled_sample_size_by_sport=None, prefer_placeable=False):
        seen["min_stake_units"] = settings.min_stake_units
        return {"positions": [], "totals": {}, "refusals": {}, "refusals_by_market": {}, "refusals_by_sport": {}}

    monkeypatch.setattr(pc, "commit_portfolio", _fake_commit)
    plan = pc.commit_live_venue_plan([], selected_date="2026-10-20", settings=_settings(), venue="kalshi",
                                     bankroll_resolver=lambda p: {"known": False, "reason": "test"})
    return seen["min_stake_units"], plan


def test_fixed_minimum_skip_reaches_the_live_commit_off_differs_from_on(monkeypatch):
    off, _ = _captured_min_stake(monkeypatch)
    monkeypatch.setenv(band.SMALL_EDGE_ENV, "0.001")
    monkeypatch.setenv(vc.COMPOUNDING_MODE_ENV, "on")
    monkeypatch.setenv("SYNDICATE_COMPOUNDING_MIN_STAKE", "floor_one_contract")
    on, plan = _captured_min_stake(monkeypatch)
    assert off == 1.0 and on == 0.0
    assert plan["small_edge"] == {"fraction": 0.001, "fixed_min_stake_skipped": True}


@pytest.mark.parametrize(
    "env",
    [
        {band.SMALL_EDGE_ENV: "0.001"},                                            # compounding off
        {band.SMALL_EDGE_ENV: "0.001", vc.COMPOUNDING_MODE_ENV: "shadow",
         "SYNDICATE_COMPOUNDING_MIN_STAKE": "floor_one_contract"},                  # shadow places fixed stakes
        {band.SMALL_EDGE_ENV: "0.001", vc.COMPOUNDING_MODE_ENV: "on"},              # $1 dollar minimum
        {vc.COMPOUNDING_MODE_ENV: "on", "SYNDICATE_COMPOUNDING_MIN_STAKE": "floor_one_contract"},  # no key
    ],
)
def test_the_fixed_minimum_stays_unless_all_three_hold(monkeypatch, env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    min_stake, plan = _captured_min_stake(monkeypatch)
    assert min_stake == 1.0
    assert "small_edge" not in plan


# ---- the regression the dry run caught: below the line, compounding's floor still runs


def test_below_the_line_compounding_still_floors_to_one_contract(monkeypatch):
    """Band on + line set: a position under the line is FLOORED to one contract
    by compounding (the band will not size it), not left at a fraction of one.
    Dry run 2026-10-20 10:59 AM CT: two Kalshi rows went out at $0.20 / $0.19."""
    from pipeline.portfolio_commit import _apply_compounding_bankroll
    from syndicate.features.shared.kalshi_orders import contracts_for_stake

    monkeypatch.setenv(vc.COMPOUNDING_MODE_ENV, "on")
    monkeypatch.setenv("SYNDICATE_COMPOUNDING_MIN_STAKE", "floor_one_contract")
    monkeypatch.setenv(band.MODE_ENV, "on")
    monkeypatch.setenv(band.SMALL_EDGE_ENV, "0.001")
    small = {"position_key": "small", "sport": "ncaaf", "market": "spreads", "stake_fraction": 0.00042,
             "stake_dollars": 0.42, "price": 108, "venue_ticker": "KX-T", "sizing": {"kelly_fraction": 0.004}}
    big = {"position_key": "big", "sport": "ncaaf", "market": "totals", "stake_fraction": 0.00115,
           "stake_dollars": 1.15, "price": 113, "venue_ticker": "KX-U", "sizing": {"kelly_fraction": 0.0046}}
    plan = {"positions": [small, big], "totals": {}}
    refusals = {}
    resolver = lambda p: {"known": True, "bankroll": 464.96, "capital": 464.96, "shard": 0, "shard_cash": 164.64}
    _apply_compounding_bankroll(plan, venue="kalshi", settings=_settings(), refusals=refusals,
                                by_market={}, by_sport={}, resolver=resolver)
    band.apply_live_stake_band(plan, venue="kalshi", refusals=refusals, by_market={}, by_sport={})
    stakes = {p["position_key"]: p for p in plan["positions"]}
    assert refusals == {}
    floored = stakes["small"]
    assert floored["compounding"]["floored_to_one_contract"] is True
    assert floored["stake_band"]["left_below_small_edge_fraction"] is True
    assert contracts_for_stake(floored["stake_dollars"], vc.one_contract_dollars(floored)) == 1
    assert stakes["big"]["stake_dollars"] >= 5.0   # at or over the line: the band sizes it
