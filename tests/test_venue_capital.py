"""`venue_capital`: what each venue holds, as a sizing basis -- and when it is unknown.

The fixture is the real 2026-10-19T18:13Z fleet reading (numbers only): Kalshi
$485.48 cash across shards {0: 170, 1: 75.01, 2: 0, 3: 240.47} plus one $4.50
open position; Polymarket buyingPower $586.05 of which $550 is a PENDING
DEPOSIT (`depositReservation`), $36.05 settled.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.shared import venue_capital as vc

_NOW = datetime(2026, 10, 19, 18, 15, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in (
        vc.COMPOUNDING_MODE_ENV,
        vc.BALANCE_CAPS_ENV,
        "SYNDICATE_COMPOUNDING_BANKROLL_FRACTION",
        "SYNDICATE_COMPOUNDING_BANKROLL_MAX_DOLLARS",
        "SYNDICATE_EXECUTION_BALANCE_DAY_PCT",
        "SYNDICATE_EXECUTION_BALANCE_ORDER_PCT",
        "SYNDICATE_COMPOUNDING_MAX_STAMP_AGE_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    yield


def _stamp(*, age_minutes: float = 2.0, polymarket_numbers=None, kalshi=None) -> dict:
    numbers = {
        "availableToWithdraw": 36.0453,
        "balanceReservation": 550.0,
        "buyingPower": 586.0453,
        "currentBalance": 586.0453,
        "depositReservation": 550.0,
        "displayedAvailableSoon": 550.0,
        "displayedCash": 36.0453,
    }
    if polymarket_numbers is not None:
        numbers = polymarket_numbers
    kalshi_row = {
        "status": "ok",
        "dollars": 485.48,
        "portfolio_value_dollars": 4.5,
        "shards": {"0": 170.0, "1": 75.01, "2": 0.0, "3": 240.47},
        "shards_status": "ok",
    }
    kalshi_row.update(kalshi or {})
    return {
        "recorded_at": (_NOW - timedelta(minutes=age_minutes)).isoformat(),
        "venues": {
            "kalshi": kalshi_row,
            "polymarket": {
                "status": "ok",
                "dollars": numbers.get("buyingPower", 586.05),
                "buying_power_dollars": numbers.get("buyingPower", 586.05),
                "detail": {"numbers": numbers},
            },
        },
    }


def _shard_of(mapping):
    return lambda ticker: (mapping.get(ticker), None if ticker in mapping else "unknown_ticker")


# ---- capital -------------------------------------------------------------


def test_kalshi_capital_is_cash_plus_open_positions():
    reading = vc.venue_capital("kalshi", _stamp(), now=_NOW)
    assert reading["known"] is True
    assert reading["capital"] == pytest.approx(489.98)
    assert reading["basis"] == "cash_plus_positions"


def test_kalshi_without_a_positions_figure_falls_back_to_cash_only():
    reading = vc.venue_capital("kalshi", _stamp(kalshi={"portfolio_value_dollars": None}), now=_NOW)
    assert reading["capital"] == pytest.approx(485.48)
    assert reading["basis"] == "cash_only"


def test_a_pending_polymarket_deposit_is_not_capital():
    # MEASURED 2026-10-19: buyingPower counted a $550 deposit not yet cleared.
    reading = vc.venue_capital("polymarket", _stamp(), now=_NOW)
    assert reading["known"] is True
    assert reading["capital"] == pytest.approx(36.05, abs=0.01)
    assert reading["pending_deposit_dollars"] == pytest.approx(550.0)


def test_a_cleared_deposit_counts_in_full():
    numbers = {"buyingPower": 586.05, "depositReservation": 0.0, "displayedAvailableSoon": 0.0}
    reading = vc.venue_capital("polymarket", _stamp(polymarket_numbers=numbers), now=_NOW)
    assert reading["capital"] == pytest.approx(586.05)


def test_polymarket_without_deposit_fields_is_unknown_not_clear():
    # The venue did not say whether a deposit is pending: fail closed.
    reading = vc.venue_capital("polymarket", _stamp(polymarket_numbers={"buyingPower": 586.05}), now=_NOW)
    assert reading == {**reading, "known": False, "reason": "pending_deposit_unreadable"}


@pytest.mark.parametrize(
    "stamp, reason",
    [
        (None, "never_recorded"),
        ({}, "never_recorded"),
        (_stamp(age_minutes=61), "stale_reading"),
        ({"recorded_at": None, "venues": {}}, "unstamped_reading"),
        ({"recorded_at": _NOW.isoformat(), "venues": {}}, "venue_absent_from_stamp"),
        ({"recorded_at": _NOW.isoformat(), "venues": {"kalshi": {"status": "auth_error"}}}, "balance_auth_error"),
        ({"recorded_at": _NOW.isoformat(), "venues": {"kalshi": {"status": "ok", "dollars": "x"}}}, "unusable_balance_value"),
    ],
)
def test_every_absence_is_unknown_with_its_own_reason(stamp, reason):
    reading = vc.venue_capital("kalshi", stamp, now=_NOW)
    assert reading["known"] is False
    assert reading["reason"] == reason


# ---- sizing bankroll -----------------------------------------------------


def test_kalshi_bankroll_is_bounded_by_the_orders_own_shard():
    result = vc.sizing_bankroll(
        "kalshi", fixed_bankroll=1000.0, ticker="KXMLB-X", stamp=_stamp(),
        shard_of=_shard_of({"KXMLB-X": 3}), now=_NOW,
    )
    assert result["known"] is True
    assert result["shard"] == 3
    # min(1.0 x 489.98, ceiling 1000, shard 3 cash 240.47)
    assert result["bankroll"] == pytest.approx(240.47)


def test_an_empty_shard_sizes_nothing():
    result = vc.sizing_bankroll(
        "kalshi", fixed_bankroll=1000.0, ticker="T", stamp=_stamp(),
        shard_of=_shard_of({"T": 2}), now=_NOW,
    )
    assert result["known"] is True and result["bankroll"] == 0.0


def test_an_unresolvable_shard_is_unknown():
    result = vc.sizing_bankroll(
        "kalshi", fixed_bankroll=1000.0, ticker="NOPE", stamp=_stamp(),
        shard_of=_shard_of({}), now=_NOW,
    )
    assert result["known"] is False
    assert result["reason"].startswith("shard_unresolved")


def test_the_ceiling_defaults_to_the_fixed_bankroll_so_on_never_sizes_above_today(monkeypatch):
    numbers = {"buyingPower": 5000.0, "depositReservation": 0.0}
    result = vc.sizing_bankroll(
        "polymarket", fixed_bankroll=1000.0, stamp=_stamp(polymarket_numbers=numbers), now=_NOW,
    )
    assert result["bankroll"] == pytest.approx(1000.0)
    monkeypatch.setenv("SYNDICATE_COMPOUNDING_BANKROLL_MAX_DOLLARS", "2500")
    raised = vc.sizing_bankroll(
        "polymarket", fixed_bankroll=1000.0, stamp=_stamp(polymarket_numbers=numbers), now=_NOW,
    )
    assert raised["bankroll"] == pytest.approx(2500.0)


def test_the_fraction_scales_capital(monkeypatch):
    monkeypatch.setenv("SYNDICATE_COMPOUNDING_BANKROLL_FRACTION", "0.5")
    result = vc.sizing_bankroll("polymarket", fixed_bankroll=1000.0, stamp=_stamp(), now=_NOW)
    assert result["bankroll"] == pytest.approx(18.02, abs=0.01)


@pytest.mark.parametrize("raw", ["", "0", "-1", "2", "abc"])
def test_an_unusable_fraction_is_the_default_not_zero_or_more_than_all(monkeypatch, raw):
    monkeypatch.setenv("SYNDICATE_COMPOUNDING_BANKROLL_FRACTION", raw)
    assert vc.compounding_config()["fraction"] == 1.0


@pytest.mark.parametrize("raw, mode", [(None, "off"), ("", "off"), ("bogus", "off"), ("shadow", "shadow"), ("on", "on")])
def test_mode_absent_or_unrecognised_is_off(monkeypatch, raw, mode):
    if raw is not None:
        monkeypatch.setenv(vc.COMPOUNDING_MODE_ENV, raw)
    assert vc.compounding_mode() == mode


# ---- balance caps --------------------------------------------------------

_CEILINGS = {
    "max_order_dollars": 25.0,
    "max_day_dollars_kalshi": 200.0,
    "max_day_dollars_polymarket": 100.0,
    "max_day_dollars_all_venues": 150.0,
}


def test_caps_are_a_share_of_capital_bounded_by_the_dollar_ceilings():
    caps = vc.balance_caps(_CEILINGS, stamp=_stamp(), now=_NOW)
    assert caps["fail_closed"] == {}
    # kalshi: 25% x 489.98 = 122.50 < 200; 5% = 24.50 < 25
    assert caps["max_day_dollars_by_venue"]["kalshi"] == pytest.approx(122.5, abs=0.01)
    assert caps["max_order_dollars_by_venue"]["kalshi"] == pytest.approx(24.5, abs=0.01)
    # polymarket on SETTLED money only: 25% x 36.05 = 9.01; 5% = 1.80
    assert caps["max_day_dollars_by_venue"]["polymarket"] == pytest.approx(9.01, abs=0.01)
    assert caps["max_order_dollars_by_venue"]["polymarket"] == pytest.approx(1.80, abs=0.01)
    # all venues: 25% x 526.03 = 131.51 < 150
    assert caps["max_day_dollars_all_venues"] == pytest.approx(131.51, abs=0.01)


def test_a_rich_account_is_held_at_the_ceiling():
    numbers = {"buyingPower": 5000.0, "depositReservation": 0.0}
    caps = vc.balance_caps(_CEILINGS, stamp=_stamp(polymarket_numbers=numbers), now=_NOW)
    assert caps["max_day_dollars_by_venue"]["polymarket"] == 100.0
    assert caps["max_order_dollars_by_venue"]["polymarket"] == 25.0
    assert caps["max_day_dollars_all_venues"] == 150.0


def test_an_unknown_venue_is_closed_and_the_other_still_trades():
    caps = vc.balance_caps(_CEILINGS, stamp=_stamp(polymarket_numbers={}), now=_NOW)
    assert caps["fail_closed"] == {"polymarket": "pending_deposit_unreadable"}
    assert caps["max_day_dollars_by_venue"]["polymarket"] == 0.0
    assert caps["max_day_dollars_by_venue"]["kalshi"] > 0
