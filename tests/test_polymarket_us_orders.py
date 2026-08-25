"""Polymarket US order building — and the Kalshi traps that do NOT apply here.

Every call in the module under test is unverified: the sandbox proxy denies
CONNECT to every venue host, exactly as it did for Kalshi, whose first live run
corrected ten field names and a 100x price error. So `order_body` is pure and
tested as a dict, which is what let `kalshi_orders` survive its contract
changing underneath it.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.polymarket_us_orders import (
    OrderBuildError,
    order_body,
    quantity_for_stake,
    round_price_to_tick,
)


class _Request:
    """The fields `order_body` actually reads off an OrderRequest."""

    def __init__(self, side="over", stake=10.0, key="abc123"):
        self.side = side
        self.requested_stake_dollars = stake
        self.position_key = key
        self.selected_date = "2026-08-24"
        self.venue = "polymarket"
        self.sport = "mlb"
        self.event_id = "evt-1"
        self.market = "h2h"
        self.line = None
        self.player_name = None
        self.book = None
        self.segment = None


def _body(**kw):
    kwargs = {
        "market_slug": "yankees-vs-red-sox-yankees-win",
        "price_dollars": 0.55,
        "tick_size": 0.01,
        "minimum_trade_qty": 1,
    }
    kwargs.update(kw)
    request = kwargs.pop("request", None) or _Request()
    return order_body(request, **kwargs)


# --------------------------------------------------------------------------
# THE NO SIDE IS REAL HERE. Porting Kalshi's inversion would be a real order
# at a different price on a different leg.
# --------------------------------------------------------------------------


def test_an_under_BUYS_NO_rather_than_selling_yes():
    """Kalshi has no `no` value -- "bid means buy YES, ask means sell YES" --
    so an under there is an ASK at the complement. This venue has
    `OUTCOME_SIDE_NO` and `ORDER_ACTION_BUY`. Copying Kalshi would send
    `sell YES at 1-p` where `buy NO at p` was meant: both are real orders,
    at different prices, on different legs, and the log would look fine."""
    body = _body(request=_Request(side="under"))
    assert body["outcomeSide"] == "OUTCOME_SIDE_NO"
    assert body["action"] == "ORDER_ACTION_BUY"
    # The PRICE IS NOT COMPLEMENTED. 0.55 stays 0.55.
    assert body["price"]["value"] == "0.55"


def test_an_over_buys_yes():
    body = _body(request=_Request(side="over"))
    assert body["outcomeSide"] == "OUTCOME_SIDE_YES"
    assert body["action"] == "ORDER_ACTION_BUY"


@pytest.mark.parametrize("side", ["", None, "maybe", "draw", "yes-ish"])
def test_an_unmappable_side_is_refused_not_defaulted(side):
    """Defaulting to YES would turn an unrecognised side into a real bet on
    the opposite outcome."""
    with pytest.raises(OrderBuildError, match="unmappable_side"):
        _body(request=_Request(side=side))


# --------------------------------------------------------------------------
# Tick size and minimum quantity come from the MARKET
# --------------------------------------------------------------------------


def test_tick_size_and_minimum_quantity_are_required_arguments():
    """The docs are explicit: "Do not infer price tick size or minimum
    quantity from product type, symbol, or slug." An optional parameter with a
    plausible default is an inference wearing a keyword."""
    with pytest.raises(TypeError):
        order_body(_Request(), market_slug="s", price_dollars=0.5)


def test_a_half_cent_tick_market_is_respected():
    """`orderPriceMinTickSize: 0.005` is a documented real value. A hardcoded
    0.01 would round a legal price onto an illegal grid."""
    body = _body(price_dollars=0.555, tick_size=0.005)
    assert body["price"]["value"] == "0.555"


def test_a_fractional_minimum_quantity_is_respected():
    """`minimumTradeQty: 0.01` means 1% contract increments. Flooring to a
    whole contract would refuse a legal order, or size it 100x wrong."""
    body = _body(price_dollars=0.5, minimum_trade_qty=0.01, request=_Request(stake=0.25))
    assert body["quantity"] == pytest.approx(0.5)


def test_the_price_is_snapped_DOWN_to_the_tick():
    """Down, not nearest. For a BUY, rounding up pays more than the price the
    edge was computed against -- small per contract, systematic across a
    slate, and never the safe direction."""
    assert round_price_to_tick(0.5678, 0.01) == pytest.approx(0.56)
    assert round_price_to_tick(0.5699, 0.01) == pytest.approx(0.56)
    body = _body(price_dollars=0.5678, tick_size=0.01)
    assert body["price"]["value"] == "0.56"


def test_a_price_below_one_tick_is_refused():
    with pytest.raises(OrderBuildError, match="price_below_one_tick"):
        _body(price_dollars=0.004, tick_size=0.01)


# --------------------------------------------------------------------------
# Sizing: floored, never rounded
# --------------------------------------------------------------------------


def test_the_stake_is_floored_never_rounded_up():
    """$10 at $0.55 is 18 contracts ($9.90), not 19 ($10.45). A cap the sizing
    quietly exceeds is not a cap."""
    assert quantity_for_stake(10.0, 0.55, 1) == 18
    body = _body(request=_Request(stake=10.0), price_dollars=0.55)
    assert body["quantity"] == 18


def test_a_stake_too_small_for_one_increment_is_a_named_refusal():
    """Not a zero quantity. The venue would reject a zero anyway -- at the
    venue, in the one place a rejection is expensive to interpret."""
    with pytest.raises(OrderBuildError, match="stake_below_minimum_quantity"):
        quantity_for_stake(0.20, 0.55, 1)


def test_sizing_uses_the_SNAPPED_price_not_the_requested_one():
    """Sizing off the unsnapped price buys a quantity the order cannot afford
    at the price actually sent."""
    # $10 at a requested 0.599 snaps to 0.59 -> floor(10/0.59) = 16.
    body = _body(request=_Request(stake=10.0), price_dollars=0.599, tick_size=0.01)
    assert body["price"]["value"] == "0.59"
    assert body["quantity"] == 16
    assert body["quantity"] * 0.59 <= 10.0


# --------------------------------------------------------------------------
# Range and shape
# --------------------------------------------------------------------------


@pytest.mark.parametrize("price", [0, -0.1, 1.0, 1.5])
def test_a_price_outside_the_probability_range_is_refused(price):
    """A probability price is strictly inside (0, 1). A 1.0 is a settled
    market or a unit error, and both should stop before the venue."""
    with pytest.raises(OrderBuildError):
        _body(price_dollars=price)


def test_the_price_is_an_amount_object_not_a_bare_number():
    """The documented `Amount` shape, used for every price and cash field on
    this venue."""
    price = _body()["price"]
    assert isinstance(price, dict)
    assert price["currency"] == "USD"
    assert isinstance(price["value"], str)


def test_an_absent_slug_is_refused():
    with pytest.raises(OrderBuildError, match="no_market_slug"):
        _body(market_slug="  ")


def test_the_idempotency_key_is_sent_as_the_client_order_id():
    """A submit that landed and whose response we lost is real, and the venue
    is the only place that question can be answered."""
    from syndicate.features.shared.execution_ledger import idempotency_key

    request = _Request()
    assert _body(request=request)["clientOrderId"] == idempotency_key(request)


def test_the_order_is_a_limit_marked_automatic():
    body = _body()
    assert body["type"] == "ORDER_TYPE_LIMIT"
    assert body["tif"] == "TIME_IN_FORCE_GOOD_TILL_CANCEL"
    assert body["manualOrderIndicator"] == "MANUAL_ORDER_INDICATOR_AUTOMATIC"


# --------------------------------------------------------------------------
# Creation is not execution
# --------------------------------------------------------------------------


def test_an_order_id_with_no_status_is_SUBMITTED_not_filled(monkeypatch):
    """The documented 200 carries only an `id` -- creation, NOT execution.
    Kalshi's phantom fill was exactly this: an accepted order booked as a
    traded one, found by a person looking at the venue's own UI."""
    from syndicate.features.shared import polymarket_us_orders as mod

    monkeypatch.setattr(
        "syndicate.features.shared.polymarket_us_auth.signed_request",
        lambda *a, **k: {"id": "ord-1"},
    )
    result = mod.submit_order(
        _Request(), price_dollars=0.55, market_slug="s",
        tick_size=0.01, minimum_trade_qty=1,
    )
    assert result["status"] == "submitted"
    assert result["venue_order_id"] == "ord-1"
    assert result["contracts"] == 0
    assert result["fill_price"] is None


def test_an_explicitly_filled_order_books_the_position(monkeypatch):
    from syndicate.features.shared import polymarket_us_orders as mod

    monkeypatch.setattr(
        "syndicate.features.shared.polymarket_us_auth.signed_request",
        lambda *a, **k: {"id": "ord-2", "status": "FILLED"},
    )
    result = mod.submit_order(
        _Request(stake=10.0), price_dollars=0.55, market_slug="s",
        tick_size=0.01, minimum_trade_qty=1,
    )
    assert result["status"] == "filled"
    assert result["contracts"] == 18
    assert result["fill_stake_dollars"] == pytest.approx(9.9)


def test_an_unrecognised_status_is_not_a_fill(monkeypatch):
    from syndicate.features.shared import polymarket_us_orders as mod

    monkeypatch.setattr(
        "syndicate.features.shared.polymarket_us_auth.signed_request",
        lambda *a, **k: {"id": "ord-3", "status": "ORDER_STATE_WHO_KNOWS"},
    )
    assert mod.submit_order(
        _Request(), price_dollars=0.55, market_slug="s",
        tick_size=0.01, minimum_trade_qty=1,
    )["status"] == "submitted"


def test_the_order_route_can_be_overridden_without_a_deploy(monkeypatch):
    """Kalshi's create route MOVED and cost an http_410 to discover. This one
    is documented -- but "documented" was also true of the route that moved."""
    from syndicate.features.shared import polymarket_us_orders as mod

    assert mod._orders_url() == "https://api.polymarket.us/v1/orders"
    monkeypatch.setenv("POLYMARKET_US_ORDER_PATH", "/v2/orders")
    assert mod._orders_url() == "https://api.polymarket.us/v2/orders"


# --------------------------------------------------------------------------
# The inverted order of 2026-08-25: side must follow the outcomes array
# --------------------------------------------------------------------------


def test_a_team_side_REFUSES_to_be_mapped_positionally():
    """`home`/`away` carry no information about a market's outcome ORDER.

    They used to map straight to YES/NO. Measured 2026-08-25T16:08:10Z, on the
    first Polymarket order ever placed: a `side=home` row for Texas Rangers @
    Chicago White Sox (home = White Sox) was sent as OUTCOME_SIDE_YES and the
    venue booked "Buy TEX" -- the away team, at the price resolved for the
    home one. Refusing is what keeps that path from being reachable by a
    caller that forgets to pass an index.
    """
    from syndicate.features.shared.polymarket_us_orders import (
        OrderBuildError,
        _side_to_outcome,
    )

    for side in ("home", "away"):
        with pytest.raises(OrderBuildError) as excinfo:
            _side_to_outcome(side)
        assert "side_needs_outcome_index" in str(excinfo.value)


def test_the_outcome_index_decides_the_side_not_the_home_away_role():
    """Our team's POSITION in `outcomes` is the only thing that names a side.

    Both cases below are `side=home`; they differ only in where the home team
    sits in the array. A positional rule gives them the same answer, which is
    how one of them became a bet on the other team.
    """
    from syndicate.features.shared.polymarket_us_orders import outcome_side_for_index

    assert outcome_side_for_index(0) == "OUTCOME_SIDE_YES"
    assert outcome_side_for_index(1) == "OUTCOME_SIDE_NO"


def test_the_yes_index_is_correctable_without_a_deploy(monkeypatch):
    """The YES-to-index convention is the one thing here the venue alone can
    settle, and it was wrong once at the cost of a real order. An env override
    turns a second correction into minutes rather than a build."""
    from syndicate.features.shared import polymarket_us_orders as mod

    monkeypatch.setenv("SYNDICATE_POLYMARKET_YES_OUTCOME_INDEX", "1")
    assert mod.outcome_side_for_index(1) == "OUTCOME_SIDE_YES"
    assert mod.outcome_side_for_index(0) == "OUTCOME_SIDE_NO"


def test_an_unusable_outcome_index_refuses_rather_than_defaulting():
    from syndicate.features.shared.polymarket_us_orders import (
        OrderBuildError,
        outcome_side_for_index,
    )

    for bad in (2, -1, "x", None):
        with pytest.raises(OrderBuildError):
            outcome_side_for_index(bad)


def test_order_body_uses_the_index_over_the_side_name():
    """The end the money comes out of. A `side=home` body must be able to send
    OUTCOME_SIDE_NO -- which the old code could not express at all."""
    from syndicate.features.shared.polymarket_us_orders import order_body

    request = _Request(side="home")
    body = order_body(
        request,
        market_slug="aec-mlb-tex-cws-2026-08-25",
        price_dollars=0.495,
        tick_size=0.005,
        minimum_trade_qty=0.01,
        outcome_index=1,
    )
    assert body["outcomeSide"] == "OUTCOME_SIDE_NO"

    flipped = order_body(
        request,
        market_slug="aec-mlb-tex-cws-2026-08-25",
        price_dollars=0.495,
        tick_size=0.005,
        minimum_trade_qty=0.01,
        outcome_index=0,
    )
    assert flipped["outcomeSide"] == "OUTCOME_SIDE_YES"
