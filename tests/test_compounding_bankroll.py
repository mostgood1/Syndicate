"""Compounding, wired: the live plan's stakes and `limits()`'s caps follow the account.

REACHABILITY FIRST (`model_engine_standard`): each flag is shown to change the
output (`off != on`) on the real call path -- `commit_live_venue_plan` and
`execution_guard.limits()` / `check_order` -- before anything is asserted about
the numbers. A flag that never reaches its code reads exactly like one that does
and found nothing to change.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from syndicate.features.shared import execution_guard as guard
from syndicate.features.shared import venue_capital as vc
from syndicate.features.shared.execution_ledger import OrderRequest
from syndicate.features.shared.portfolio_settings import PortfolioSettings

_DATE = "2026-10-19"
_TICKER = "KXMLBGAME-26OCT19CLETB-TB"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "file")
    (tmp_path / "intelligence").mkdir(parents=True, exist_ok=True)
    for name in (
        vc.COMPOUNDING_MODE_ENV,
        vc.BALANCE_CAPS_ENV,
        "SYNDICATE_COMPOUNDING_BANKROLL_FRACTION",
        "SYNDICATE_COMPOUNDING_BANKROLL_MAX_DOLLARS",
        "SYNDICATE_EXECUTION_MAX_ORDER_DOLLARS",
        "SYNDICATE_EXECUTION_MAX_DAY_DOLLARS",
        "SYNDICATE_EXECUTION_MAX_DAY_DOLLARS_KALSHI",
        "SYNDICATE_EXECUTION_MAX_DAY_DOLLARS_POLYMARKET",
        "SYNDICATE_EXECUTION_MAX_DAY_DOLLARS_ALL_VENUES",
        "SYNDICATE_EXECUTION_MAX_DAY_ORDERS",
        "SYNDICATE_EXECUTION_KILL_SWITCH",
        "SYNDICATE_EXECUTION_MODE",
        "SYNDICATE_KALSHI_SHARD_BALANCE_GATE",
    ):
        monkeypatch.delenv(name, raising=False)
    yield


def _write_stamp(*, polymarket_numbers=None, recorded_at=None):
    from syndicate.features.shared.refresh_state_store import write_json_file
    from syndicate.features.shared.venue_balances import balances_path

    numbers = polymarket_numbers if polymarket_numbers is not None else {
        "buyingPower": 586.05, "depositReservation": 550.0, "displayedAvailableSoon": 550.0,
    }
    write_json_file(
        balances_path(),
        {
            "recorded_by": "test",
            "recorded_at": recorded_at or datetime.now(timezone.utc).isoformat(),
            "venues": {
                "kalshi": {
                    "status": "ok", "dollars": 485.48, "portfolio_value_dollars": 4.5,
                    "shards": {"0": 170.0, "1": 75.01, "2": 0.0, "3": 240.47}, "shards_status": "ok",
                },
                "polymarket": {
                    "status": "ok", "dollars": numbers.get("buyingPower", 586.05),
                    "buying_power_dollars": numbers.get("buyingPower", 586.05),
                    "detail": {"numbers": numbers},
                },
            },
        },
    )


# --------------------------------------------------------------------------
# Caps: limits() and check_order
# --------------------------------------------------------------------------


def test_caps_flag_off_leaves_limits_untouched_key_for_key():
    _write_stamp()
    before = guard.limits("live", venue="kalshi")
    assert "balance_caps" not in before and "dollar_ceilings" not in before


def test_caps_flag_reaches_limits_off_differs_from_on(monkeypatch):
    # A small account, so the percentages bind under the default ceilings.
    _write_stamp(polymarket_numbers={"buyingPower": 36.05, "depositReservation": 0.0})
    off = guard.limits("live", venue="polymarket")
    monkeypatch.setenv(vc.BALANCE_CAPS_ENV, "on")
    on = guard.limits("live", venue="polymarket")
    assert off != on
    # defaults: order $10, polymarket day $100, all venues $150 -- now a share
    # of $36.05: 5% = $1.80, 25% = $9.01.
    assert on["max_order_dollars"] == pytest.approx(1.80, abs=0.01)
    assert on["max_day_dollars"] == pytest.approx(9.01, abs=0.01)
    assert on["dollar_ceilings"]["max_order_dollars"] == off["max_order_dollars"]


def test_a_pending_polymarket_deposit_feeds_the_caps(monkeypatch):
    # USER DECISION 2026-10-19 (caps-revamp): the pending deposit can be used.
    # $586.05 buying power of which $550 pending: 5% = 29.30, held at the $10
    # default order ceiling; 25% = 146.51, held at the $100 day ceiling.
    _write_stamp()
    monkeypatch.setenv(vc.BALANCE_CAPS_ENV, "on")
    caps = guard.limits("live", venue="polymarket")
    assert caps["balance_caps"]["capital"]["polymarket"]["capital"] == pytest.approx(586.05, abs=0.01)
    assert caps["max_order_dollars"] == pytest.approx(10.0)
    assert caps["max_day_dollars"] == pytest.approx(100.0)


def test_caps_never_loosen_a_configured_ceiling(monkeypatch):
    _write_stamp(polymarket_numbers={"buyingPower": 100_000.0, "depositReservation": 0.0})
    monkeypatch.setenv(vc.BALANCE_CAPS_ENV, "on")
    caps = guard.limits("live", venue="polymarket")
    assert caps["max_order_dollars"] == 10.0
    assert caps["max_day_dollars"] == 100.0
    assert caps["max_day_dollars_all_venues"] == 150.0


def test_paper_is_exempt_from_balance_caps(monkeypatch):
    _write_stamp()
    monkeypatch.setenv(vc.BALANCE_CAPS_ENV, "on")
    assert "balance_caps" not in guard.limits("paper", venue="kalshi")


def _order(venue="polymarket", stake=1.0):
    return OrderRequest(
        position_key="p1", selected_date=_DATE, venue=venue, sport="mlb", event_id="e1",
        market="h2h", side="home", requested_price=-110.0, requested_stake_dollars=stake,
    )


def test_an_unknown_capital_refuses_by_name_when_caps_are_on(monkeypatch):
    _write_stamp(recorded_at="2026-01-01T00:00:00+00:00")  # stale
    allowed_off = guard.check_order(_order(), mode="live", already={"dollars": 0, "orders": 0})
    monkeypatch.setenv(vc.BALANCE_CAPS_ENV, "on")
    refused = guard.check_order(_order(), mode="live", already={"dollars": 0, "orders": 0})
    assert allowed_off["reason"] != "balance_caps_capital_unknown"
    assert refused["allowed"] is False
    assert refused["reason"] == "balance_caps_capital_unknown"
    assert refused["detail"] == "stale_reading"


def test_a_stake_over_the_balance_derived_order_cap_is_refused(monkeypatch):
    # The GUARD still refuses an over-cap stake; trimming happens before it, in
    # execute_portfolio. 5% of $36.05 = $1.80 < the $5 stake.
    _write_stamp(polymarket_numbers={"buyingPower": 36.05, "depositReservation": 0.0})
    monkeypatch.setenv(vc.BALANCE_CAPS_ENV, "on")
    result = guard.check_order(_order(stake=5.0), mode="live", already={"dollars": 0, "orders": 0})
    assert result["reason"] == "over_max_order_dollars"


def test_the_settings_form_shows_ceilings_not_the_derived_caps(monkeypatch):
    from syndicate.features.shared.execution_limits_settings import resolve_view

    _write_stamp()
    monkeypatch.setenv(vc.BALANCE_CAPS_ENV, "on")
    view = resolve_view()
    assert view["max_order_dollars"] == 10.0
    assert view["max_day_dollars_polymarket"] == 100.0


# --------------------------------------------------------------------------
# Sizing: commit_live_venue_plan
# --------------------------------------------------------------------------


def _settings(**overrides) -> PortfolioSettings:
    values = dict(
        bankroll_units=1000.0, max_slate_exposure_fraction=1.0, min_ev_pct=-100.0,
        max_positions=50, min_stake_units=1.0,
    )
    values.update(overrides)
    return PortfolioSettings(**values)


def _row(event_id, *, ticker=_TICKER, score=5.0):
    return {
        "sport": "mlb", "event_id": event_id, "kind": "game", "market": "h2h",
        "segment": "full_game", "line": None, "player_name": None,
        "home_team": "Home", "away_team": "Away", "commence_time": "2026-10-19T23:05:00Z",
        "side": "home", "quote": {"price": -110, "bookmaker": "kalshi"},
        "ev_pct": 4.5, "model_edge_pct": 3.2,
        "score": {"score": score, "price_reliability": 0.82},
        "venue": "kalshi", "price_source": "venue_feed", "venue_ticker": ticker,
    }


def _resolver(bankroll):
    def _resolve(position):
        if bankroll is None:
            return {"known": False, "reason": "stale_reading"}
        return {"known": True, "bankroll": bankroll, "capital": 489.98, "shard": 3, "shard_cash": 240.47}
    return _resolve


def _plan(**kwargs):
    from pipeline.portfolio_commit import commit_live_venue_plan

    return commit_live_venue_plan(
        [_row("g1"), _row("g2", score=4.0)], selected_date=_DATE, settings=_settings(), **kwargs
    )


def test_sizing_off_is_todays_plan_exactly():
    baseline = _plan()
    with_venue = _plan(venue="kalshi", bankroll_resolver=_resolver(100.0))
    for plan in (baseline, with_venue):
        plan.pop("generated_at", None)
    assert "compounding" not in with_venue
    assert [p["stake_dollars"] for p in with_venue["positions"]] == [
        p["stake_dollars"] for p in baseline["positions"]
    ]


def test_sizing_flag_reaches_the_plan_off_differs_from_on(monkeypatch):
    off = _plan(venue="kalshi", bankroll_resolver=_resolver(100.0))
    assert off["positions"], "fixture must commit positions or this proves nothing"
    monkeypatch.setenv(vc.COMPOUNDING_MODE_ENV, "on")
    on = _plan(venue="kalshi", bankroll_resolver=_resolver(100.0))
    off_stakes = [p["stake_dollars"] for p in off["positions"]]
    on_stakes = [p["stake_dollars"] for p in on["positions"]]
    assert off_stakes != on_stakes
    for before, after, position in zip(off_stakes, on_stakes, on["positions"]):
        assert after == pytest.approx(position["stake_fraction"] * 100.0, abs=0.01)
        assert after == pytest.approx(before / 10.0, abs=0.02)
    assert on["totals"]["staked_dollars"] == pytest.approx(sum(on_stakes), abs=0.01)


def test_shadow_stamps_the_compounded_stake_and_places_the_fixed_one(monkeypatch):
    off = _plan(venue="kalshi", bankroll_resolver=_resolver(100.0))
    monkeypatch.setenv(vc.COMPOUNDING_MODE_ENV, "shadow")
    shadow = _plan(venue="kalshi", bankroll_resolver=_resolver(100.0))
    assert [p["stake_dollars"] for p in shadow["positions"]] == [p["stake_dollars"] for p in off["positions"]]
    for position in shadow["positions"]:
        assert position["compounding"]["stake_dollars_compounded"] == pytest.approx(
            position["stake_fraction"] * 100.0, abs=0.01
        )
    assert shadow["compounding"]["mode"] == "shadow"


def test_an_unknown_bankroll_refuses_every_position_by_name(monkeypatch):
    monkeypatch.setenv(vc.COMPOUNDING_MODE_ENV, "on")
    plan = _plan(venue="kalshi", bankroll_resolver=_resolver(None))
    assert plan["positions"] == []
    assert plan["refusals"].get("compounding_bankroll_unknown") == 2
    assert plan["compounding"]["unknown_reasons"] == {"stale_reading": 2}
    # The accounting contract survives: every scoped row is a position or a refusal.
    assert sum(plan["refusals"].values()) + len(plan["positions"]) == plan["rows_in"]


def test_a_stake_shrunk_below_the_minimum_is_refused_not_rounded_up(monkeypatch):
    monkeypatch.setenv(vc.COMPOUNDING_MODE_ENV, "on")
    plan = _plan(venue="kalshi", bankroll_resolver=_resolver(1.0))
    assert plan["positions"] == []
    assert plan["refusals"].get("below_min_stake_compounded") == 2
    assert sum(plan["refusals"].values()) + len(plan["positions"]) == plan["rows_in"]


def test_the_default_resolver_reads_the_stamp_and_the_orders_shard(monkeypatch):
    """The production resolver, over a written stamp: shard 3 bounds a Kalshi row."""
    from pipeline import portfolio_commit as pc

    _write_stamp()
    monkeypatch.setattr(guard, "_kalshi_shard_of", lambda ticker: (3, None))
    resolve = pc.default_bankroll_resolver("kalshi", _settings())
    verdict = resolve({"venue_ticker": _TICKER})
    assert verdict["known"] is True
    assert verdict["bankroll"] == pytest.approx(240.47)


# ---- options (a)+(b), user 2026-10-20: today's two refused positions ------


def _live_position(key, fraction, american):
    return {"position_key": key, "sport": "nba", "market": "player_points", "stake_fraction": fraction,
            "stake_dollars": round(fraction * 1000.0, 2), "price": american, "venue_ticker": "KX-T"}


def _apply(bankroll):
    from pipeline.portfolio_commit import _apply_compounding_bankroll

    plan = {"positions": [_live_position("del", 0.00118, 117), _live_position("maxey", 0.00198, -203)], "totals": {}}
    refusals, by_market, by_sport = {}, {}, {}
    _apply_compounding_bankroll(
        plan, venue="kalshi", settings=_settings(min_stake_units=1.0),
        refusals=refusals, by_market=by_market, by_sport=by_sport, resolver=_resolver(bankroll),
    )
    return plan, refusals


def test_dollar_minimum_refuses_both_at_the_whole_account(monkeypatch):
    monkeypatch.setenv(vc.COMPOUNDING_MODE_ENV, "on")
    plan, refusals = _apply(465.37)  # (b) alone: $0.55 and $0.92, both under $1
    assert plan["positions"] == []
    assert refusals == {"below_min_stake_compounded": 2}


def test_one_contract_minimum_reaches_the_plan_off_differs_from_on(monkeypatch):
    monkeypatch.setenv(vc.COMPOUNDING_MODE_ENV, "on")
    off, _ = _apply(465.37)
    monkeypatch.setenv("SYNDICATE_COMPOUNDING_MIN_STAKE", "one_contract")
    on, refusals = _apply(465.37)  # (a)+(b): $0.55 >= $0.46, $0.92 >= $0.67
    assert off["positions"] == [] and len(on["positions"]) == 2
    stakes = {p["position_key"]: p["stake_dollars"] for p in on["positions"]}
    assert stakes == {"del": pytest.approx(0.55, abs=0.01), "maxey": pytest.approx(0.92, abs=0.01)}
    assert {p["position_key"]: p["compounding"]["contracts_compounded"] for p in on["positions"]} == {"del": 1, "maxey": 1}
    assert refusals == {}


def test_one_contract_minimum_alone_still_refuses_on_a_shard_bankroll(monkeypatch):
    monkeypatch.setenv(vc.COMPOUNDING_MODE_ENV, "on")
    monkeypatch.setenv("SYNDICATE_COMPOUNDING_MIN_STAKE", "one_contract")
    plan, refusals = _apply(170.0)  # (a) alone on shard 0: $0.20 < $0.46, $0.34 < $0.67
    assert plan["positions"] == []
    assert refusals == {"below_one_contract_compounded": 2}
    assert plan["compounding"]["refused_reasons"] == {"below_one_contract_compounded": 2}


def test_an_unpriceable_position_is_refused_not_guessed(monkeypatch):
    from pipeline.portfolio_commit import _apply_compounding_bankroll

    monkeypatch.setenv(vc.COMPOUNDING_MODE_ENV, "on")
    monkeypatch.setenv("SYNDICATE_COMPOUNDING_MIN_STAKE", "one_contract")
    plan = {"positions": [_live_position("x", 0.01, None)], "totals": {}}
    refusals = {}
    _apply_compounding_bankroll(plan, venue="kalshi", settings=_settings(), refusals=refusals,
                                by_market={}, by_sport={}, resolver=_resolver(465.37))
    assert refusals == {"no_contract_price_compounded": 1}


# ---- "(b) + floor" (user 2026-10-20): round UP to exactly one contract ------


def _apply_floor(resolver, positions=None):
    from pipeline.portfolio_commit import _apply_compounding_bankroll

    plan = {"positions": positions or [_live_position("del", 0.00118, 117), _live_position("maxey", 0.00198, -203)],
            "totals": {}}
    refusals = {}
    _apply_compounding_bankroll(plan, venue="kalshi", settings=_settings(min_stake_units=1.0), refusals=refusals,
                                by_market={}, by_sport={}, resolver=resolver)
    return plan, refusals


def _shard_resolver(bankroll, shard_cash):
    return lambda position: {"known": True, "bankroll": bankroll, "capital": 465.37, "shard": 0, "shard_cash": shard_cash}


def test_floor_reaches_the_plan_off_differs_from_on(monkeypatch):
    monkeypatch.setenv(vc.COMPOUNDING_MODE_ENV, "on")
    off, off_refusals = _apply_floor(_shard_resolver(170.0, 170.0))   # $0.20 / $0.34 on a shard bankroll
    monkeypatch.setenv("SYNDICATE_COMPOUNDING_MIN_STAKE", "floor_one_contract")
    on, on_refusals = _apply_floor(_shard_resolver(170.0, 170.0))
    assert off["positions"] == [] and off_refusals == {"below_min_stake_compounded": 2}
    assert len(on["positions"]) == 2 and on_refusals == {}
    assert on["compounding"]["floored_to_one_contract"] == 2
    for position in on["positions"]:
        assert position["compounding"]["floored_to_one_contract"] is True
        assert position["compounding"]["contracts_compounded"] == 1


def test_a_floored_stake_builds_exactly_one_kalshi_contract(monkeypatch):
    from syndicate.features.shared.kalshi_orders import contracts_for_stake

    monkeypatch.setenv(vc.COMPOUNDING_MODE_ENV, "on")
    monkeypatch.setenv("SYNDICATE_COMPOUNDING_MIN_STAKE", "floor_one_contract")
    plan, _ = _apply_floor(_shard_resolver(170.0, 170.0))
    for position in plan["positions"]:
        price = vc.one_contract_dollars(position)
        stake = position["stake_dollars"]
        assert stake > price                       # fee included, rounded up to the cent
        assert round(stake * 100) == stake * 100   # whole cents
        assert contracts_for_stake(stake, price) == 1


def test_floor_never_spends_past_the_shard(monkeypatch):
    monkeypatch.setenv(vc.COMPOUNDING_MODE_ENV, "on")
    monkeypatch.setenv("SYNDICATE_COMPOUNDING_MIN_STAKE", "floor_one_contract")
    plan, refusals = _apply_floor(_shard_resolver(170.0, 0.30))   # shard holds 30c
    assert plan["positions"] == []
    assert refusals == {"floor_exceeds_funding_cash": 2}


def test_floor_refuses_when_the_shard_is_unknown(monkeypatch):
    monkeypatch.setenv(vc.COMPOUNDING_MODE_ENV, "on")
    monkeypatch.setenv("SYNDICATE_COMPOUNDING_MIN_STAKE", "floor_one_contract")
    plan, refusals = _apply_floor(lambda position: {"known": True, "bankroll": 170.0, "capital": 465.37})
    assert refusals == {"floor_exceeds_funding_cash": 2}


def test_floor_does_not_touch_a_stake_already_over_one_contract(monkeypatch):
    monkeypatch.setenv(vc.COMPOUNDING_MODE_ENV, "on")
    monkeypatch.setenv("SYNDICATE_COMPOUNDING_MIN_STAKE", "floor_one_contract")
    plan, refusals = _apply_floor(_shard_resolver(465.37, 245.33))  # (b): $0.55 / $0.92
    stakes = {p["position_key"]: p["stake_dollars"] for p in plan["positions"]}
    assert stakes == {"del": pytest.approx(0.55, abs=0.01), "maxey": pytest.approx(0.92, abs=0.01)}
    assert plan["compounding"]["floored_to_one_contract"] == 0 and refusals == {}


def test_floor_never_rescues_an_unknown_capital(monkeypatch):
    monkeypatch.setenv(vc.COMPOUNDING_MODE_ENV, "on")
    monkeypatch.setenv("SYNDICATE_COMPOUNDING_MIN_STAKE", "floor_one_contract")
    plan, refusals = _apply_floor(_resolver(None))
    assert refusals == {"compounding_bankroll_unknown": 2}
