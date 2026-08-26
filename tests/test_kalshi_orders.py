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


def test_a_resting_response_holds_NOTHING_yet(monkeypatch):
    """This test used to assert `contracts == 8` on a RESTING order — that we
    held the full requested size on something the venue had not executed. It
    encoded the phantom fill rather than catching it, and it passed the whole
    time the ledger was booking positions that did not exist.

    A resting order is accepted and unfilled: nothing is held until it trades.
    """
    monkeypatch.setattr(
        "syndicate.features.shared.kalshi_auth.signed_request",
        lambda *a, **k: {"order": {"order_id": "ord-2", "status": "resting"}},
    )
    result = orders.submit_order(_request(stake=5.0), price_dollars=0.62)
    assert result["contracts"] == 0
    assert result["status"] == "submitted"
    assert result["fill_price"] is None
    # What we ASKED for is still reported, so a later reconciliation can tell a
    # resting order from one that was never sent.
    assert result["requested_contracts"] == 8
    assert result["venue_status"] == "resting"


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


# --------------------------------------------------------------------------
# The price field: the one order-contract assumption nothing has tested
# --------------------------------------------------------------------------


def _req(**kw):
    from syndicate.features.shared.execution_ledger import OrderRequest

    base = dict(
        position_key="p", selected_date="2026-08-24", venue="kalshi", sport="mlb",
        event_id="e1", market="spreads", side="over", requested_price=150.0,
        requested_stake_dollars=5.0, line=3.5,
        venue_ticker="KXMLBSPREAD-26AUG241940TEXCWS-TEX4",
    )
    base.update(kw)
    return OrderRequest(**base)


def test_the_price_unit_is_switchable_without_a_deploy(monkeypatch):
    """Kalshi's v2 order contract has long taken `yes_price` in INTEGER CENTS;
    this module sends `yes_price_dollars`, a spelling inferred from the MARKET
    READ fields. Nothing has confirmed the write side agrees — the endpoint has
    never been reached, because both live attempts died at order build.

    An inference from a neighbouring field, never checked against the thing it
    describes, is exactly the game-date bug (`close_time` read as first pitch)
    and the title-grammar bug. So it is switchable, and one real response
    settles it.
    """
    from syndicate.features.shared.kalshi_orders import order_body

    monkeypatch.delenv("KALSHI_ORDER_PRICE_UNIT", raising=False)
    assert order_body(_req(), price_dollars=0.42)["yes_price_dollars"] == 0.42

    monkeypatch.setenv("KALSHI_ORDER_PRICE_UNIT", "cents")
    body = order_body(_req(), price_dollars=0.42)
    assert body["yes_price"] == 42
    assert "yes_price_dollars" not in body


def test_cents_are_an_integer_not_a_rounded_float(monkeypatch):
    """`42.0` and `42` are different JSON. A float where an integer is expected
    is a rejection whose message will not say so."""
    from syndicate.features.shared.kalshi_orders import order_body

    monkeypatch.setenv("KALSHI_ORDER_PRICE_UNIT", "cents")
    value = order_body(_req(), price_dollars=0.42)["yes_price"]
    assert isinstance(value, int) and not isinstance(value, bool)


def test_a_price_outside_one_contract_refuses_in_cents_too(monkeypatch):
    """A contract settles at $1, so a price outside 1-99c is not a price —
    and the cents path must not lose that check."""
    from syndicate.features.shared.kalshi_orders import OrderBuildError, order_body

    monkeypatch.setenv("KALSHI_ORDER_PRICE_UNIT", "cents")
    for bad in (0.0, 1.5):
        with pytest.raises(OrderBuildError):
            order_body(_req(), price_dollars=bad)


def test_the_side_still_decides_which_price_field_is_sent(monkeypatch):
    """An `under` is a NO buy, and the price belongs on the no field. Putting
    it on the yes field prices the opposite outcome."""
    from syndicate.features.shared.kalshi_orders import order_body

    monkeypatch.setenv("KALSHI_ORDER_PRICE_UNIT", "cents")
    body = order_body(_req(side="under"), price_dollars=0.42)
    assert body["side"] == "no"
    assert body["no_price"] == 42
    assert "yes_price" not in body


# --------------------------------------------------------------------------
# The order ROUTE: v2-in-the-path is not the same as the v2 order contract
# --------------------------------------------------------------------------


def test_the_order_path_is_overridable_without_a_deploy(monkeypatch):
    """MEASURED 2026-08-24, the first real response this endpoint ever gave:

        http_410 .../trade-api/v2/portfolio/orders
        {"error":{"code":"deprecated_v1_order_endpoint",
                  "message":"Please switch to the V2 endpoints"}}

    The path carries `v2` and Kalshi calls it the V1 ORDER endpoint — the API
    surface and the order contract are versioned separately, and reading the
    `v2` in the URL as proof the route was current was wrong.
    """
    from syndicate.features.shared import kalshi_orders as mod

    monkeypatch.delenv("KALSHI_ORDER_URL", raising=False)
    monkeypatch.delenv("KALSHI_API_BASE", raising=False)
    monkeypatch.setenv("KALSHI_ORDER_PATH", "/portfolio/orders/v2")
    assert mod._orders_url().endswith("/trade-api/v2/portfolio/orders/v2")


def test_a_leading_slash_is_not_required(monkeypatch):
    """A path pasted out of a docs page rarely carries one."""
    from syndicate.features.shared import kalshi_orders as mod

    monkeypatch.delenv("KALSHI_ORDER_URL", raising=False)
    monkeypatch.setenv("KALSHI_ORDER_PATH", "orders")
    assert mod._orders_url().endswith("/trade-api/v2/orders")


def test_an_absolute_url_override_wins_outright(monkeypatch):
    """For a route that does not hang off the same base at all."""
    from syndicate.features.shared import kalshi_orders as mod

    monkeypatch.delenv("KALSHI_ORDER_PATH", raising=False)
    monkeypatch.setenv("KALSHI_ORDER_URL", "https://api.elections.kalshi.com/trade-api/v2/orders")
    assert mod._orders_url() == "https://api.elections.kalshi.com/trade-api/v2/orders"


def test_the_default_route_is_the_supplied_one_not_a_guess(monkeypatch):
    """Written when the replacement was unknown and the default had to stay on
    the dead route rather than a guessed one. The owner then supplied the real
    contract, so the default is now `/portfolio/events/orders` — read off a
    sample, still not inferred."""
    from syndicate.features.shared import kalshi_orders as mod

    for key in ("KALSHI_ORDER_URL", "KALSHI_ORDER_PATH", "KALSHI_API_BASE"):
        monkeypatch.delenv(key, raising=False)
    assert mod._orders_url().endswith("/trade-api/v2/portfolio/events/orders")


# --------------------------------------------------------------------------
# The v2 order contract, from the sample the owner supplied 2026-08-24
# --------------------------------------------------------------------------


def test_the_v2_body_matches_the_supplied_contract(monkeypatch):
    """Field-for-field against the sample, because every previous order-shape
    belief in this module was inferred from a neighbouring endpoint and every
    one of them was wrong."""
    from syndicate.features.shared.kalshi_orders import build_order_body

    monkeypatch.delenv("KALSHI_ORDER_CONTRACT", raising=False)
    body = build_order_body(_req(), price_dollars=0.56)

    assert body["side"] == "bid"  # `_req` is an over
    # QUOTED DECIMALS. A JSON number where a string is expected is a rejection
    # whose message will not say which field it meant.
    assert body["price"] == "0.5600"
    assert isinstance(body["count"], str) and body["count"].endswith(".00")
    assert body["time_in_force"] == "good_till_canceled"
    assert body["self_trade_prevention_type"] == "taker_at_cross"
    assert body["post_only"] is False
    assert body["reduce_only"] is False
    assert body["subaccount"] == 0
    # NOT 0 -- and the sample body is not the authority on this one field.
    # `exchange_index` is a SHARD SELECTOR: the venue's field reference says it
    # auto-routes when omitted and that -1 REQUIRES routing by ticker, so a
    # literal 0 pins every order to shard 0 and 404s `market_not_found` for
    # any market that lives elsewhere. See `_V2_EXCHANGE_INDEX_AUTO`.
    assert body["exchange_index"] == -1
    # The v1 fields are GONE, not merely unused — sending them alongside the
    # new ones is how a request gets rejected for a reason nobody can read.
    for dead in ("action", "type", "yes_price", "no_price", "yes_price_dollars"):
        assert dead not in body


def test_an_under_is_an_ask_at_the_complement(monkeypatch):
    """Kalshi quotes this endpoint entirely from the YES leg:

        "bid means buy YES, ask means sell YES. (Selling YES is economically
         equivalent to buying NO at 1 - price...)"

    So an under is not `side: no` — no such value exists — it is an ASK at the
    complement. Asserted by side AND price, because a count alone cannot tell a
    correct order from one on the opposite outcome.
    """
    from syndicate.features.shared.kalshi_orders import build_order_body

    monkeypatch.delenv("KALSHI_ORDER_CONTRACT", raising=False)
    over = build_order_body(_req(side="over"), price_dollars=0.40)
    under = build_order_body(_req(side="under"), price_dollars=0.40)

    assert over["side"] == "bid" and over["price"] == "0.4000"
    assert under["side"] == "ask" and under["price"] == "0.6000"


def test_the_count_does_NOT_invert_with_the_price(monkeypatch):
    """THE EASY THING TO GET WRONG, and the reason it has its own test.

    Buying NO at $0.40 is selling YES at $0.60, but the capital committed is
    still $0.40 per contract. Sizing off the quoted 0.60 would buy ~33% fewer
    contracts than the stake was sized for — silently, on every under, with
    nothing in the response to reveal it.
    """
    from syndicate.features.shared.kalshi_orders import build_order_body

    monkeypatch.delenv("KALSHI_ORDER_CONTRACT", raising=False)
    over = build_order_body(_req(side="over"), price_dollars=0.40)
    under = build_order_body(_req(side="under"), price_dollars=0.40)

    # Same stake, same price paid per contract, so the same size both ways.
    assert under["count"] == over["count"]
    assert float(under["count"]) == float(_req().requested_stake_dollars) // 0.40


def test_a_price_leaving_no_complement_refuses(monkeypatch):
    """A NO price so close to $1 that the YES quote rounds to zero has no
    order behind it. $0.9999 is NOT that case — its complement is $0.0001, a
    dreadful bet but a structurally valid one, and the builder is not the place
    to have opinions about value."""
    from syndicate.features.shared.kalshi_orders import OrderBuildError, build_order_body

    monkeypatch.delenv("KALSHI_ORDER_CONTRACT", raising=False)
    assert build_order_body(_req(side="under"), price_dollars=0.9999)["price"] == "0.0001"

    with pytest.raises(OrderBuildError):
        build_order_body(_req(side="under"), price_dollars=0.999999)


def test_v2_is_the_default_because_v1_is_confirmed_dead(monkeypatch):
    """v1 returns http_410 `deprecated_v1_order_endpoint`. Defaulting to it
    would be defaulting to a guaranteed failure."""
    from syndicate.features.shared.kalshi_orders import build_order_body

    monkeypatch.delenv("KALSHI_ORDER_CONTRACT", raising=False)
    assert build_order_body(_req(), price_dollars=0.56)["side"] == "bid"


def test_v1_remains_reachable_for_rollback(monkeypatch):
    """Kept only so a rollback needs no deploy."""
    from syndicate.features.shared.kalshi_orders import build_order_body

    monkeypatch.setenv("KALSHI_ORDER_CONTRACT", "v1")
    monkeypatch.delenv("KALSHI_ORDER_PRICE_UNIT", raising=False)
    body = build_order_body(_req(), price_dollars=0.56)
    assert body["side"] == "yes"
    assert body["yes_price_dollars"] == 0.56


def test_the_default_route_is_the_v2_one(monkeypatch):
    from syndicate.features.shared import kalshi_orders as mod

    for key in ("KALSHI_ORDER_URL", "KALSHI_ORDER_PATH", "KALSHI_API_BASE"):
        monkeypatch.delenv(key, raising=False)
    assert mod._orders_url().endswith("/trade-api/v2/portfolio/events/orders")


# --------------------------------------------------------------------------
# A resting order is NOT a fill — the phantom position of 2026-08-24T13:12Z
# --------------------------------------------------------------------------


def _submit_with(monkeypatch, response, price=0.54):
    from syndicate.features.shared import kalshi_auth, kalshi_orders

    monkeypatch.setattr(kalshi_auth, "signed_request", lambda *a, **k: response)
    return kalshi_orders.submit_order(_req(side="under"), price_dollars=price)


def test_a_resting_order_is_recorded_submitted_not_filled(monkeypatch):
    """THE WORST BUG OF THE RUN. Our ledger read `status=filled fill_price=0.54`
    for an order that was RESTING and unfilled on Kalshi — the owner saw it
    pending in their account while we had booked the position.

    The line was `str(order.get("status") or "filled")`. An accepted-but-
    unexecuted order returns a status we did not map, and the default booked a
    trade that never happened: settlement would grade it, P&L would count it,
    and reconciliation becomes impossible when our record and the venue's book
    disagree about whether a trade occurred.
    """
    out = _submit_with(monkeypatch, {"order": {"status": "resting", "order_id": "abc"}})
    assert out["status"] == "submitted"
    assert out["contracts"] == 0
    # A fill price on an unfilled order is a number that will be believed.
    assert out["fill_price"] is None
    assert out["fill_stake_dollars"] == 0
    # The venue's own word is kept, so reconciliation has something to match on.
    assert out["venue_status"] == "resting"


def test_an_unrecognised_status_is_not_a_fill(monkeypatch):
    """Defaulting the UNKNOWN case to the most committal outcome is exactly
    backwards. A status we have never seen is not evidence of a trade."""
    for response in (
        {"order": {"order_id": "abc"}},
        {"order": {"status": "pending", "order_id": "abc"}},
        {"order": {"status": "some_new_state", "order_id": "abc"}},
    ):
        out = _submit_with(monkeypatch, response)
        assert out["status"] == "submitted", response
        assert out["fill_price"] is None


def test_an_executed_order_IS_a_fill(monkeypatch):
    """The guard must not swing so far that a real fill is missed — an unbooked
    position is its own kind of wrong."""
    out = _submit_with(
        monkeypatch,
        {"order": {"status": "executed", "order_id": "abc", "filled_count": "2"}},
    )
    assert out["status"] == "filled"
    assert out["contracts"] == 2
    assert out["fill_price"] == 0.54
    assert out["fill_stake_dollars"] == 1.08


def test_a_partial_fill_counts_what_actually_filled(monkeypatch):
    """Resting with a positive filled_count is a PARTIAL fill: we hold what
    filled. Recording the requested size would be a position we believe and do
    not hold."""
    out = _submit_with(
        monkeypatch,
        {"order": {"status": "resting", "order_id": "abc", "filled_count": "1"}},
    )
    assert out["status"] == "filled"
    assert out["contracts"] == 1
    assert out["fill_stake_dollars"] == 0.54


# --------------------------------------------------------------------------
# Reading the venue back
# --------------------------------------------------------------------------


def test_the_read_routes_hang_off_the_same_base(monkeypatch):
    """`GET /portfolio/orders` and `GET /portfolio/orders/{id}`. This shares a
    prefix with the POST that returns 410 for creation -- reading is fine
    there, only the create verb moved. Written down because guessing that
    route is how the 410 happened."""
    from syndicate.features.shared import kalshi_orders as mod

    monkeypatch.setenv("KALSHI_API_BASE", "https://example.test/trade-api/v2")
    assert mod._orders_list_url(100) == (
        "https://example.test/trade-api/v2/portfolio/orders?limit=100"
    )
    assert mod._order_read_url("abc") == (
        "https://example.test/trade-api/v2/portfolio/orders/abc"
    )


def test_a_read_failure_is_named_not_raised(monkeypatch):
    """Reconciliation runs over the whole open book; one unreadable response
    must not stop the rest, and must never look like an empty book."""
    from syndicate.features.shared import kalshi_orders as mod

    def boom(*_args, **_kwargs):
        raise RuntimeError("connection reset")

    monkeypatch.setattr("syndicate.features.shared.kalshi_auth.signed_request", boom)
    result = mod.fetch_orders()
    assert result["status"] == "error"
    assert "RuntimeError" in result["reason"]
    assert "orders" not in result


def test_a_response_without_an_orders_array_is_an_error(monkeypatch):
    from syndicate.features.shared import kalshi_orders as mod

    monkeypatch.setattr(
        "syndicate.features.shared.kalshi_auth.signed_request",
        lambda *a, **k: {"cursor": "x"},
    )
    assert mod.fetch_orders()["reason"] == "no_orders_array"


def test_a_resting_order_is_not_a_fill():
    from syndicate.features.shared.kalshi_orders import venue_order_view

    seen = venue_order_view({"status": "resting", "filled_count": 0, "order_id": "o1"})
    assert seen["state"] == "resting"
    assert not seen["filled_count"]


def test_an_unmapped_status_stays_unknown():
    """UNKNOWN IS A REAL ANSWER. Collapsing it into either 'it traded' or 'it
    didn't' is the mistake that booked a position we never held."""
    from syndicate.features.shared.kalshi_orders import venue_order_view

    assert venue_order_view({"status": "who_knows"})["state"] == "unknown"


def test_the_fill_count_is_derived_when_it_is_not_given():
    """Three spellings, one fact. The response shape has never been seen live,
    and `kalshi_client`'s first live run corrected ten field names."""
    from syndicate.features.shared.kalshi_orders import venue_order_view

    assert venue_order_view({"status": "executed", "filled_count": 3})["filled_count"] == 3
    assert venue_order_view(
        {"status": "executed", "taker_fill_count": 2, "maker_fill_count": 1}
    )["filled_count"] == 3
    assert venue_order_view(
        {"status": "canceled", "initial_count": 5, "remaining_count": 4}
    )["filled_count"] == 1


def test_a_partial_fill_outranks_a_cancelled_status():
    """The cancel describes the remainder; the contracts that traded are a
    position we hold."""
    from syndicate.features.shared.kalshi_orders import venue_order_view

    seen = venue_order_view({"status": "canceled", "filled_count": 1})
    assert seen["state"] == "filled"
    assert seen["filled_count"] == 1


def test_an_executed_order_with_no_readable_count_is_still_filled():
    """Reported as filled with an unknown count rather than as zero contracts,
    which would be a lie in the direction that loses a position."""
    from syndicate.features.shared.kalshi_orders import venue_order_view

    seen = venue_order_view({"status": "executed"})
    assert seen["state"] == "filled"
    assert seen["filled_count"] is None


def test_prices_are_read_as_dollars_whichever_unit_they_arrive_in():
    """A probability price cannot exceed $1, so the boundary is unambiguous --
    and the 100x error is the one `kalshi_client` actually made."""
    from syndicate.features.shared.kalshi_orders import venue_order_view

    assert venue_order_view({"status": "executed", "filled_count": 1,
                             "average_fill_price": 46})["fill_price"] == 0.46
    assert venue_order_view({"status": "executed", "filled_count": 1,
                             "average_fill_price": 0.46})["fill_price"] == 0.46


# --------------------------------------------------------------------------
# The field names, corrected from a live response 2026-08-24T14:37:16Z
# --------------------------------------------------------------------------


def test_the_real_kalshi_field_names_are_read():
    """Not one of the three count spellings guessed beforehand was right. The
    live keys are `fill_count_fp`, `initial_count_fp`, `remaining_count_fp`,
    `taker_fees_dollars`, `taker_fill_cost_dollars`."""
    from syndicate.features.shared.kalshi_orders import venue_order_view

    seen = venue_order_view({
        "status": "executed",
        "fill_count_fp": 2,
        "taker_fill_cost_dollars": 1.08,
        "taker_fees_dollars": 0.02,
        "maker_fees_dollars": 0.0,
    })
    assert seen["state"] == "filled"
    assert seen["filled_count"] == 2
    assert seen["fill_cost_dollars"] == 1.08
    assert seen["fees_dollars"] == 0.02
    # The price becomes a DIVISION of what Kalshi billed, rather than a guess
    # about which of yes_price_dollars / no_price_dollars is our leg.
    assert seen["fill_price"] == 0.54


def test_the_fp_count_fields_drive_the_derived_count():
    from syndicate.features.shared.kalshi_orders import venue_order_view

    seen = venue_order_view({"status": "canceled", "initial_count_fp": 5,
                             "remaining_count_fp": 4})
    assert seen["filled_count"] == 1


def test_no_fee_leg_at_all_is_unknown_not_zero():
    """A sum of the PRESENT legs is the total -- an order filled entirely as a
    taker carries a real 0.0 on the maker leg. But an order carrying neither
    has told us nothing, and $0.00 of fees is a fee we would never charge."""
    from syndicate.features.shared.kalshi_orders import venue_order_view

    assert venue_order_view({"status": "resting"})["fees_dollars"] is None
    assert venue_order_view(
        {"status": "executed", "fill_count_fp": 1, "maker_fees_dollars": 0.0}
    )["fees_dollars"] == 0.0


def test_the_venue_fill_cost_outranks_our_reconstruction():
    """`count * price` was arithmetic over two numbers we parsed. The fill cost
    is the charge itself."""
    from syndicate.features.shared.kalshi_orders import venue_order_view

    seen = venue_order_view({
        "status": "executed", "fill_count_fp": 3,
        "taker_fill_cost_dollars": 1.50, "maker_fill_cost_dollars": 0.30,
    })
    assert seen["fill_cost_dollars"] == 1.80
    assert seen["fill_price"] == 0.6


def test_the_cancel_route_hangs_off_the_write_path(monkeypatch):
    """The asymmetry is real and cost a 410 to learn once already:

        POST   /portfolio/events/orders          create
        DELETE /portfolio/events/orders/{id}     cancel
        GET    /portfolio/orders                 list
        GET    /portfolio/orders/{id}            read one

    Assuming DELETE followed the READS would 404 silently while the order kept
    resting -- worse than the create 410, because nothing about the order
    changes to say so."""
    from syndicate.features.shared import kalshi_orders as mod

    monkeypatch.setenv("KALSHI_API_BASE", "https://example.test/trade-api/v2")
    assert mod._order_cancel_url("abc") == (
        "https://example.test/trade-api/v2/portfolio/events/orders/abc"
    )
    assert mod._orders_url() == "https://example.test/trade-api/v2/portfolio/events/orders"
    assert mod._order_read_url("abc") == (
        "https://example.test/trade-api/v2/portfolio/orders/abc"
    )


def test_a_failed_cancel_is_named_not_raised(monkeypatch):
    """A cancel that fails must leave the order alone: it is still resting, it
    can still fill, and recording it dead frees a key the venue still holds."""
    from syndicate.features.shared import kalshi_orders as mod

    def boom(*_args, **_kwargs):
        raise RuntimeError("http_410")

    monkeypatch.setattr("syndicate.features.shared.kalshi_auth.signed_request", boom)
    result = mod.cancel_order("abc")
    assert result["status"] == "error"
    assert "http_410" in result["reason"]


def test_cancelling_nothing_is_refused():
    from syndicate.features.shared.kalshi_orders import cancel_order

    assert cancel_order("")["reason"] == "no_order_id"


def test_both_price_legs_are_carried_through():
    """Which leg we are paying depends on our side, which the view does not
    know -- and Kalshi hands over both, so guessing is unnecessary."""
    from syndicate.features.shared.kalshi_orders import venue_order_view

    seen = venue_order_view({"status": "resting", "fill_count_fp": "0.00",
                             "yes_price_dollars": "0.4600",
                             "no_price_dollars": "0.5400"})
    assert seen["yes_price"] == 0.46
    assert seen["no_price"] == 0.54


def test_a_position_with_no_ticker_says_SO_instead_of_blaming_the_price():
    """THREE REAL ORDERS WENT TO THE LEDGER UNDER THE WRONG CAUSE.

    `_kalshi_price_for` returns None at its FIRST line when `venue_ticker` is
    empty -- before it ever asks Kalshi for a price -- so an unstamped position
    arrived here indistinguishable from a market the venue would not quote.
    Every Kalshi row in the 2026-08-25 ledger read:

        OrderBuildError: no_live_price: None

    and the trailing `None` was the ticker saying so all along:

        LIVE_ORDER status=rejected venue=kalshi ticker=None
          market=totals_alt side=over line=5.5

    `verify_order_paths` had the distinction right (`no_venue_ticker`) while
    the path with money on it did not. They point at different fixes: a missing
    id is the board join or the position cap; a missing price is the venue or
    staleness.
    """
    import dataclasses

    submit = orders.kalshi_submitter(lambda request: 0.55)
    unstamped = dataclasses.replace(_request(), venue_ticker="")
    with pytest.raises(orders.OrderBuildError) as excinfo:
        submit(unstamped)
    assert str(excinfo.value) == "no_venue_ticker", str(excinfo.value)


def test_a_real_price_failure_still_names_the_TICKER_it_could_not_price():
    """The other half stays reachable, and now carries the contract id instead
    of the `None` that made the two look alike."""
    submit = orders.kalshi_submitter(lambda request: None)
    with pytest.raises(orders.OrderBuildError) as excinfo:
        submit(_request())
    message = str(excinfo.value)
    assert message.startswith("no_live_price:"), message
    assert "None" not in message, message


def test_a_submit_failure_asks_the_venue_what_the_market_IS(monkeypatch, capsys):
    """`market_not_found` ON A MARKET THE GET FINDS.

    Measured 2026-08-25 6:00 PM Central, three real submissions in one minute:

        KXWNBAAST-...-4          side=bid  price=0.5000  -> FILLED
        KXMLBTOTAL-...MINATH-10  side=ask  price=0.5500  -> market_not_found
        KXMLBTOTAL-...CINSF-8    side=ask  price=0.5100  -> market_not_found

    ...while `fetch_market` on that same MINATH ticker returned a live price
    TWICE in the same minute (`LIVE_PRICE ... live=0.45 drift=+0.0100`). The
    ticker is real and tradeable; the GET finds it and the POST does not.

    Two candidates remain and the error text distinguishes neither: an `ask`
    (sell YES) this endpoint refuses, or a market whose order shape differs
    (`market_type`, or an MVE collection). A 1-vs-2 sample is not enough to
    flip order semantics -- this file's own `_DEFAULT_ORDER_PATH` comment
    records inventing a route once already and earning a 410 for it. So the
    failure asks the venue what the market IS.
    """
    from syndicate.features.shared import kalshi_auth, kalshi_client

    def _boom(*_a, **_k):
        raise orders.OrderBuildError("http_404: market_not_found")

    monkeypatch.setattr(kalshi_auth, "signed_request", _boom)
    monkeypatch.setattr(
        kalshi_client, "fetch_market",
        lambda ticker: {"status": "ok", "market": {
            "market_type": "binary", "status": "active",
            "mve_collection_ticker": None, "strike_type": "greater",
            "yes_ask_dollars": 0.55, "no_ask_dollars": 0.45,
            "can_close_early": True,
        }},
    )

    with pytest.raises(orders.OrderBuildError):
        orders.submit_order(_request(), price_dollars=0.55)

    printed = capsys.readouterr().out
    assert "SUBMIT_FAILED_MARKET" in printed, printed
    # The fields that tell the two hypotheses apart.
    for field in ("market_type=", "mve_collection=", "yes_ask=", "no_ask="):
        assert field in printed, (field, printed)


def test_the_diagnostic_never_masks_the_real_error(monkeypatch):
    """A probe that raised would replace the venue's own rejection with our
    own -- losing the only message that says why the order failed."""
    from syndicate.features.shared import kalshi_auth, kalshi_client

    monkeypatch.setattr(
        kalshi_auth, "signed_request",
        lambda *_a, **_k: (_ for _ in ()).throw(orders.OrderBuildError("http_404: real_reason")),
    )
    monkeypatch.setattr(
        kalshi_client, "fetch_market",
        lambda ticker: (_ for _ in ()).throw(RuntimeError("probe exploded")),
    )

    with pytest.raises(orders.OrderBuildError) as excinfo:
        orders.submit_order(_request(), price_dollars=0.55)
    assert "real_reason" in str(excinfo.value), str(excinfo.value)


def test_a_moneyline_side_buys_YES_on_our_own_teams_contract():
    """CONFIRMED BY THE USER 2026-08-25 from Kalshi's own order URLs. One market
    PER TEAM, each offering a BUY on both legs:

        KXMLBGAME-26AUG251840BOSMIA-BOS   op_order_side=yes  op_side=BUY
        KXMLBGAME-26AUG251840BOSMIA-MIA   op_order_side=yes  op_side=BUY

    So backing Miami is BUY YES on `-MIA`, not a NO or an ask on `-BOS`. The
    join already keys a match on `board_side` and stamps the ticker of the team
    that side names, so by order-build time the contract IS our team and the
    leg is always YES.

    Before this, `home`/`away` raised `unmappable_side` and no moneyline could
    build an order at all -- untested because every h2h had already failed
    upstream on a missing ticker.
    """
    from syndicate.features.shared.kalshi_orders import _side_to_kalshi

    assert _side_to_kalshi("home", "h2h") == "yes"
    assert _side_to_kalshi("away", "h2h") == "yes"
    # The period moneylines are the same shape.
    assert _side_to_kalshi("home", "h2h_h1") == "yes"


def test_a_team_side_on_a_NON_team_ticker_still_refuses():
    """THE GUARD THAT MAKES THE ABOVE SAFE, and the reason it is restricted to
    the moneyline family.

    A totals ticker encodes a STRIKE (`KXMLBTOTAL-...-10`), not a team. Reading
    `home` as `yes` there would buy a market that has nothing to do with our
    side -- so it must keep raising. `home` on a total is a defect upstream,
    and a defect that refuses is worth far more than one that guesses.
    """
    from syndicate.features.shared.kalshi_orders import _side_to_kalshi

    for market in ("totals", "totals_alt", "spreads", "batter_hits", None, ""):
        with pytest.raises(orders.OrderBuildError, match="unmappable_side"):
            _side_to_kalshi("home", market)


def test_the_direction_sides_are_untouched_by_the_moneyline_path():
    """over/under must keep mapping exactly as before -- the moneyline rule is
    additive, not a rewrite of the leg selection every other market uses."""
    from syndicate.features.shared.kalshi_orders import _side_to_kalshi

    assert _side_to_kalshi("over", "totals") == "yes"
    assert _side_to_kalshi("under", "totals") == "no"
    assert _side_to_kalshi("over", "h2h") == "yes"
    assert _side_to_kalshi("yes", None) == "yes"
    assert _side_to_kalshi("no", None) == "no"


def test_a_moneyline_order_body_is_a_BID_not_an_ask():
    """END TO END: the whole point of the workaround. An `ask` is what every
    failed Kalshi order today was (`market_not_found`, twice); a moneyline must
    never take that path."""
    import dataclasses

    request = dataclasses.replace(
        _request(), market="h2h", side="home", line=None,
        venue_ticker="KXMLBGAME-26AUG251840BOSMIA-MIA",
    )
    body = orders.order_body_v2(request, price_dollars=0.55)
    assert body["side"] == "bid", body
    assert body["ticker"] == "KXMLBGAME-26AUG251840BOSMIA-MIA"


# ---------------------------------------------------------------------------
# THE ORDER HOST. `_BASE_URLS` is a fallback CHAIN for reads and a PIN for
# writes, and that asymmetry is the leading explanation for the only failure
# this endpoint produces: `market_not_found` on a POST to base[0] for a ticker
# `fetch_market` resolved somewhere else. Measured 2026-08-25/26 -- four
# KXMLBTOTAL orders, on BOTH sides, all 404, while the probe reported the
# market active with both asks quoted.
# ---------------------------------------------------------------------------


def test_no_retry_when_the_order_host_already_served_the_read():
    """THE SAFETY PROPERTY. If the hypothesis is wrong the two hosts agree and
    nothing about the money path changes -- this stays pure measurement."""
    from syndicate.features.shared.kalshi_client import _BASE_URLS

    assert orders._retry_url_for(f"{_BASE_URLS[0]}/portfolio/events/orders", _BASE_URLS[0]) == ""


def test_retry_targets_the_host_that_resolved_the_ticker():
    from syndicate.features.shared.kalshi_client import _BASE_URLS

    url = orders._retry_url_for(f"{_BASE_URLS[0]}/portfolio/events/orders", _BASE_URLS[1])
    assert url == f"{_BASE_URLS[1]}/portfolio/events/orders"


def test_never_retries_against_a_host_kalshi_has_not_served():
    """Inventing a route is what earned this file an http_410."""
    assert orders._retry_url_for(
        "https://external-api.kalshi.com/trade-api/v2/portfolio/events/orders",
        "https://orders.kalshi.example/trade-api/v2",
    ) == ""


def test_only_market_not_found_retries():
    """A 404 from a mistyped PATH is a different failure, and retrying it
    against a second host would just repeat it."""
    assert orders._is_market_not_found(
        RuntimeError('http_404: {"error":{"code":"market_not_found"}}')
    )
    assert not orders._is_market_not_found(
        RuntimeError('http_404: {"error":{"code":"not_found","message":"path"}}')
    )
    assert not orders._is_market_not_found(RuntimeError("http_401: unauthorized"))


def test_the_order_body_auto_routes_by_ticker_instead_of_pinning_shard_zero(monkeypatch):
    """The regression that produced a week of `market_not_found`.

    A GET on those tickers returned `status=active` with both legs quoted, from
    the SAME host the POST 404'd on, 0.5s apart -- so the market existed and
    only the ORDER could not see it. `exchange_index: 0` is why: it is a shard
    selector, not furniture, and pinning shard 0 hides every market on another
    shard behind the only error a matching engine has for that.
    """
    from syndicate.features.shared.kalshi_orders import build_order_body

    monkeypatch.delenv("KALSHI_ORDER_CONTRACT", raising=False)
    monkeypatch.delenv("KALSHI_ORDER_EXCHANGE_INDEX", raising=False)
    body = build_order_body(_req(), price_dollars=0.56)
    assert body["exchange_index"] == -1
    # The ticker is what -1 routes BY, so it must be present and non-empty --
    # -1 with no ticker is the one combination the venue rejects outright.
    assert body["ticker"]


def test_the_shard_index_is_overridable_without_a_deploy(monkeypatch):
    """Rollback path. This field is the venue's to move, not ours to freeze."""
    from syndicate.features.shared.kalshi_orders import build_order_body

    monkeypatch.delenv("KALSHI_ORDER_CONTRACT", raising=False)
    monkeypatch.setenv("KALSHI_ORDER_EXCHANGE_INDEX", "0")
    assert build_order_body(_req(), price_dollars=0.56)["exchange_index"] == 0

    # Garbage falls back to auto-routing rather than to 0. An unreadable
    # override is not a request for the setting that broke this.
    monkeypatch.setenv("KALSHI_ORDER_EXCHANGE_INDEX", "auto")
    assert build_order_body(_req(), price_dollars=0.56)["exchange_index"] == -1
