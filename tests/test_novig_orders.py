"""Novig's order-placement body -- built against a REAL documented contract
(docs.novig.com content supplied 2026-08-24), not research alone. See
novig_orders.py's header for what's still unconfirmed (the response shape,
the cancel method, and the CASH/COIN risked-vs-to-win question).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from syndicate.features.shared.novig_orders import (
    OrderBuildError,
    backoff_seconds_from_headers,
    cash_units_for_stake,
    novig_submitter,
    order_body,
)


def _request(**overrides):
    defaults = dict(
        position_key="k1",
        selected_date="2026-08-24",
        venue="novig",
        sport="mlb",
        event_id="evt-1",
        market="moneyline",
        side="over",
        requested_price=0.62,
        requested_stake_dollars=5.0,
        venue_ticker="123e4567-e89b-12d3-a456-426614174000",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# --- cash_units_for_stake ---------------------------------------------------


@pytest.mark.parametrize("stake,expected_qty", [(5.0, 500), (1.0, 100), (0.01, 1), (12.345, 1235)])
def test_cash_units_for_stake_rounds_to_the_nearest_cent(stake, expected_qty):
    assert cash_units_for_stake(stake) == expected_qty


def test_cash_units_for_stake_refuses_non_positive():
    with pytest.raises(OrderBuildError, match="non_positive_stake"):
        cash_units_for_stake(0)
    with pytest.raises(OrderBuildError, match="non_positive_stake"):
        cash_units_for_stake(-1)


def test_cash_units_for_stake_refuses_coin_rather_than_guess_a_conversion():
    """1 Coin is a different, non-dollar unit -- this function's job is a
    dollar conversion and it must not silently repurpose itself for Coin."""
    with pytest.raises(OrderBuildError, match="cash_units_for_stake_is_CASH_only"):
        cash_units_for_stake(5.0, currency="COIN")


# --- order_body --------------------------------------------------------------


def test_order_body_matches_the_documented_contract_exactly():
    """Field names and shape from the real curl example:
    {"outcomeId": ..., "price": ..., "qty": ..., "currency": ..., "tif": ...}."""
    body = order_body(_request(), currency="CASH")
    assert body == {
        "outcomeId": "123e4567-e89b-12d3-a456-426614174000",
        "price": 0.62,
        "qty": 500,
        "currency": "CASH",
        "tif": "GTC",
    }


def test_order_body_requires_currency_with_no_default():
    """No default -- see module header. This is a TypeError (a missing
    required keyword argument), not a caught OrderBuildError, because it is a
    programming error at the call site, not a data problem with one request."""
    with pytest.raises(TypeError):
        order_body(_request())


def test_order_body_refuses_an_invalid_currency():
    with pytest.raises(OrderBuildError, match="invalid_currency"):
        order_body(_request(), currency="USD")


def test_order_body_refuses_a_missing_outcome_id():
    with pytest.raises(OrderBuildError, match="no_outcome_id"):
        order_body(_request(venue_ticker=None), currency="CASH")


def test_order_body_refuses_an_out_of_range_price():
    with pytest.raises(OrderBuildError, match="price_out_of_range"):
        order_body(_request(requested_price=1.0), currency="CASH")
    with pytest.raises(OrderBuildError, match="price_out_of_range"):
        order_body(_request(requested_price=0.0), currency="CASH")


def test_order_body_rounds_price_to_three_decimal_places():
    body = order_body(_request(requested_price=0.66666), currency="CASH")
    assert body["price"] == 0.667


def test_order_body_accepts_an_explicit_qty_for_coin_orders():
    """The path for COIN, where cash_units_for_stake refuses -- an explicit
    qty bypasses the dollar conversion entirely."""
    body = order_body(_request(), currency="COIN", qty=4200)
    assert body["qty"] == 4200
    assert body["currency"] == "COIN"


def test_order_body_refuses_gtt_without_a_ttl():
    with pytest.raises(OrderBuildError, match="gtt_requires_ttl_ms"):
        order_body(_request(), currency="CASH", tif="GTT")


def test_order_body_accepts_gtt_with_a_ttl():
    body = order_body(_request(), currency="CASH", tif="GTT", ttl_ms=2400)
    assert body["tif"] == "GTT"
    assert body["ttl"] == 2400


def test_order_body_refuses_flags_over_the_documented_length():
    with pytest.raises(OrderBuildError, match="flags_too_long"):
        order_body(_request(), currency="CASH", flags="TOO_LONG_FLAG")


def test_order_body_accepts_flags_at_the_documented_length():
    body = order_body(_request(), currency="CASH", flags="ABC12345")
    assert body["flags"] == "ABC12345"


# --- backoff_seconds_from_headers -------------------------------------------


def test_backoff_converts_milliseconds_to_seconds():
    """THE ONE THING THIS FUNCTION EXISTS FOR: Retry-After and
    X-RateLimit-Reset are documented as milliseconds. 73 means 73ms, i.e.
    0.073s -- not 73 seconds."""
    assert backoff_seconds_from_headers({"Retry-After": "73"}) == pytest.approx(0.073)
    assert backoff_seconds_from_headers({"X-RateLimit-Reset": "1000"}) == pytest.approx(1.0)


def test_backoff_prefers_retry_after_over_rate_limit_reset():
    headers = {"Retry-After": "500", "X-RateLimit-Reset": "9000"}
    assert backoff_seconds_from_headers(headers) == pytest.approx(0.5)


def test_backoff_returns_none_without_either_header():
    assert backoff_seconds_from_headers({}) is None


def test_backoff_ignores_an_unparseable_value_and_falls_through():
    assert backoff_seconds_from_headers({"Retry-After": "not_a_number", "X-RateLimit-Reset": "200"}) == pytest.approx(0.2)


# --- novig_submitter ---------------------------------------------------------


def test_novig_submitter_raises_no_live_price_without_one():
    submitter = novig_submitter(lambda request: None, currency="CASH")
    with pytest.raises(OrderBuildError, match="no_live_price"):
        submitter(_request())


def test_novig_submitter_is_not_wired_to_a_network_call_yet():
    """Deliberately unimplemented past body-building -- see module header."""
    submitter = novig_submitter(lambda request: 0.62, currency="CASH")
    with pytest.raises(NotImplementedError):
        submitter(_request())
