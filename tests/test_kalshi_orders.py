"""Dollars into contracts, and the refusals that happen before anything is sent."""

from __future__ import annotations

import pytest

from syndicate.features.shared import kalshi_orders as orders
from syndicate.features.shared.execution_ledger import OrderRequest


def _request(stake=5.0, side="over", ticker="KXMLBKS-26AUG24SEA-T5"):
    return OrderRequest(
        position_key="p1",
        selected_date="2026-08-24",
        venue="kalshi",
        sport="mlb",
        event_id="e1",
        market="pitcher_strikeouts",
        side=side,
        requested_price=-110.0,
        requested_stake_dollars=stake,
        venue_ticker=ticker,
    )


def test_contracts_floor_rather_than_round_up():
    # $5.00 / $0.62 = 8.06. Nine contracts is $5.58 against a $5.00 stake, and a
    # cap the sizing quietly exceeds is not a cap.
    assert orders.contracts_for_stake(5.00, 0.62) == 8


def test_an_exact_division_is_not_shortened():
    assert orders.contracts_for_stake(5.00, 0.50) == 10


def test_a_stake_too_small_for_one_contract_is_a_named_refusal():
    with pytest.raises(orders.OrderBuildError) as excinfo:
        orders.contracts_for_stake(0.40, 0.62)
    # Not a zero-count order: "a smaller bet" and "an invalid request" must not
    # share a return value.
    assert "stake_below_one_contract" in str(excinfo.value)


@pytest.mark.parametrize("price", [0.0, 1.0, 1.5, -0.2])
def test_a_price_outside_zero_to_one_is_not_a_price(price):
    with pytest.raises(orders.OrderBuildError) as excinfo:
        orders.contracts_for_stake(5.0, price)
    assert "price_out_of_range" in str(excinfo.value)


def test_the_body_names_the_ticker_side_count_and_a_limit_price():
    body = orders.order_body(_request(stake=5.0), price_dollars=0.62)
    assert body["ticker"] == "KXMLBKS-26AUG24SEA-T5"
    assert body["side"] == "yes"
    assert body["count"] == 8
    # A market order on a thin exchange book is an order at whatever the worst
    # resting offer happens to be.
    assert body["type"] == "limit"
    assert body["yes_price_dollars"] == 0.62


def test_an_under_becomes_the_no_side_and_prices_the_no_leg():
    body = orders.order_body(_request(side="under"), price_dollars=0.38)
    assert body["side"] == "no"
    assert body["no_price_dollars"] == 0.38
    assert "yes_price_dollars" not in body


def test_an_unmappable_side_refuses_rather_than_defaulting_to_yes():
    with pytest.raises(orders.OrderBuildError) as excinfo:
        orders.order_body(_request(side="middle"), price_dollars=0.5)
    # Defaulting to `yes` would turn an unrecognised side into a real bet on the
    # opposite outcome.
    assert "unmappable_side" in str(excinfo.value)


def test_no_venue_ticker_refuses_by_name():
    with pytest.raises(orders.OrderBuildError) as excinfo:
        orders.order_body(_request(ticker=None), price_dollars=0.5)
    assert "no_venue_ticker" in str(excinfo.value)


def test_no_price_refuses_before_anything_is_built():
    with pytest.raises(orders.OrderBuildError) as excinfo:
        orders.order_body(_request())
    assert "no_price_dollars" in str(excinfo.value)


def test_the_client_order_id_is_the_ledgers_idempotency_key():
    from syndicate.features.shared.execution_ledger import idempotency_key

    request = _request()
    body = orders.order_body(request, price_dollars=0.62)
    # A submit that reached Kalshi and lost its response is the venue's
    # duplicate to reject -- the only place that question can be answered.
    assert body["client_order_id"] == idempotency_key(request)


def test_the_body_is_pure(monkeypatch):
    """No clock, no env, no network -- so the live run's corrections are one edit."""
    monkeypatch.setenv("KALSHI_API_BASE", "https://should-not-be-read")
    a = orders.order_body(_request(), price_dollars=0.62)
    b = orders.order_body(_request(), price_dollars=0.62)
    assert a == b


def test_a_partial_fill_is_reported_as_partial(monkeypatch):
    monkeypatch.setattr(
        "syndicate.features.shared.kalshi_auth.signed_request",
        lambda *a, **k: {"order": {"order_id": "ord-1", "status": "filled", "filled_count": 3}},
    )
    result = orders.submit_order(_request(stake=5.0), price_dollars=0.62)
    # A partial fill recorded as a full one is a position size we believe and
    # do not hold.
    assert result["contracts"] == 3
    assert result["requested_contracts"] == 8
    assert result["fill_stake_dollars"] == 1.86


def test_a_response_without_a_fill_count_falls_back_to_what_was_asked(monkeypatch):
    monkeypatch.setattr(
        "syndicate.features.shared.kalshi_auth.signed_request",
        lambda *a, **k: {"order": {"order_id": "ord-2", "status": "resting"}},
    )
    result = orders.submit_order(_request(stake=5.0), price_dollars=0.62)
    assert result["contracts"] == 8
    assert result["status"] == "resting"


def test_an_unpriceable_contract_raises_so_the_order_is_recorded_as_failed():
    submit = orders.kalshi_submitter(lambda request: None)
    with pytest.raises(orders.OrderBuildError) as excinfo:
        submit(_request())
    assert "no_live_price" in str(excinfo.value)


def test_the_adapter_never_sends_when_the_body_cannot_be_built(monkeypatch):
    def explode(*_a, **_k):
        raise AssertionError("a request was sent for an order that could not be built")

    monkeypatch.setattr("syndicate.features.shared.kalshi_auth.signed_request", explode)
    with pytest.raises(orders.OrderBuildError):
        orders.submit_order(_request(ticker=None), price_dollars=0.62)
