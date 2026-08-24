"""Turn a committed position into a Polymarket US order, and send it.

The venue adapter `execution_ledger.place_order` calls for `venue=polymarket`.
Everything above it -- the plan, the caps, the kill switch, the write-ahead
record -- is venue-agnostic; this is the one file that knows what
`api.polymarket.us` wants.

--------------------------------------------------------------------------
THE NO SIDE IS REAL HERE, AND COPYING KALSHI WOULD BE WRONG
--------------------------------------------------------------------------

Kalshi has no `no` value. Its docs say so outright: "for event markets this
refers to the YES leg only: bid means buy YES, ask means sell YES", so an
UNDER is an ASK at the complement of the price, and `kalshi_orders` carries a
paragraph explaining that inversion.

Polymarket US does NOT work that way. `outcomeSide` is `OUTCOME_SIDE_YES` or
`OUTCOME_SIDE_NO`, and `action` is `ORDER_ACTION_BUY` or `ORDER_ACTION_SELL`.
An under is a straightforward BUY of NO at the NO price.

Porting Kalshi's complement logic here would send `sell YES at 1-p` where
`buy NO at p` was meant. Both are "real" orders; they are different positions
at different prices, and the mistake would look entirely plausible in a log.
So the conversion is written from this venue's own vocabulary and the Kalshi
inversion is deliberately absent.

--------------------------------------------------------------------------
TICK SIZE AND MINIMUM QUANTITY COME FROM THE MARKET. NEVER INFERRED.
--------------------------------------------------------------------------

The documentation is unusually direct about this:

    "Use orderPriceMinTickSize and minimumTradeQty from the market response
     before submitting orders. Do not infer price tick size or minimum
     quantity from product type, symbol, or slug."

So `order_body` REQUIRES them and refuses without them. It does not default to
0.01 and 1 -- a market with `minimumTradeQty: 0.01` and
`orderPriceMinTickSize: 0.005` exists, and a hardcoded assumption would round
a legal order into an illegal one, or silently 100x a size.

This is the same class of error as Kalshi's `count`/`price` units, which cost
a phantom fill and a 410. The difference is that here the venue publishes the
answer, so there is no excuse for guessing it.

--------------------------------------------------------------------------
QUANTITY IS CONTRACTS, AND THE FLOOR IS TO A TICK, NOT TO AN INTEGER
--------------------------------------------------------------------------

`contracts_for_stake` in `kalshi_orders` floors to a whole contract because
Kalshi sells whole contracts. Here quantity is a `double` and markets may
accept fractions, so the floor is to `minimumTradeQty` -- and it is still a
FLOOR, never a round. A stake cap the sizing quietly exceeds is not a cap.

--------------------------------------------------------------------------
UNVERIFIED, AND SHAPED AROUND THAT
--------------------------------------------------------------------------

No call here has run: the sandbox proxy denies CONNECT to every venue host.
`order_body` is PURE -- no clock, no network, no env -- so it is unit-tested as
a dict and, when the first live run corrects something, the fix is one edit
and the tests still mean something. That is exactly how `kalshi_orders`
survived its own contract change.
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from typing import Any

__all__ = [
    "OrderBuildError",
    "quantity_for_stake",
    "round_price_to_tick",
    "order_body",
    "submit_order",
    "polymarket_us_submitter",
]


class OrderBuildError(ValueError):
    """Refused before anything was sent. Never means the venue saw it."""


# The enum values, verbatim from the documented request schema. In one place so
# a rename is one edit, and so nothing constructs them by string concatenation.
_SIDE_YES = "OUTCOME_SIDE_YES"
_SIDE_NO = "OUTCOME_SIDE_NO"
_ACTION_BUY = "ORDER_ACTION_BUY"
_TYPE_LIMIT = "ORDER_TYPE_LIMIT"
_TIF_GTC = "TIME_IN_FORCE_GOOD_TILL_CANCEL"
# Automated, and honest about it. The venue offers a manual/automatic flag and
# every order this system sends is placed by a program.
_MANUAL_INDICATOR = "MANUAL_ORDER_INDICATOR_AUTOMATIC"
_CURRENCY = "USD"

# Venue statuses that mean the trade HAPPENED. Everything else -- resting,
# pending, cancelled, or anything unrecognised -- is not a fill. Same rule
# `kalshi_orders` learned by booking a position that did not exist.
_VENUE_FILLED_STATUSES = frozenset({"filled", "executed", "matched", "closed", "complete"})

_ORDERS_PATH = "/v1/orders"


def _side_to_outcome(side: Any) -> str:
    """Our `over`/`under`/`yes`/`no` -> the venue's outcome side.

    REFUSES an unmapped side. Defaulting to YES would turn an unrecognised side
    into a real bet on the opposite outcome, which is the most expensive silent
    default available in this file.
    """
    raw = str(side or "").strip().lower()
    if raw in {"yes", "over", "home"}:
        return _SIDE_YES
    if raw in {"no", "under", "away"}:
        return _SIDE_NO
    raise OrderBuildError(f"unmappable_side: {side!r}")


def _positive_float(value: Any, name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise OrderBuildError(f"{name}_unreadable: {value!r}") from None
    if not parsed > 0 or parsed != parsed:
        raise OrderBuildError(f"{name}_not_positive: {value!r}")
    return parsed


def round_price_to_tick(price: float, tick: float) -> float:
    """Down to the nearest legal tick.

    DOWN, not nearest. For a BUY, rounding up pays more than the price the edge
    was computed against -- small per contract and systematic across a slate.
    Rounding toward the venue is never the safe direction.
    """
    tick_value = _positive_float(tick, "tick_size")
    steps = math.floor(round(price / tick_value, 9))
    snapped = steps * tick_value
    # Float division leaves 0.30000000000000004; the venue is comparing against
    # its own tick grid and a value that is one ULP off may simply be rejected.
    return round(snapped, 9)


def quantity_for_stake(stake_dollars: float, price: float, minimum_qty: float) -> float:
    """Contracts a stake buys, floored to the market's own minimum increment.

    FLOORED, never rounded. `kalshi_orders` documents why for whole contracts
    and the reasoning is identical for fractional ones: rounding up spends more
    than the cap said, and a cap the sizing quietly exceeds is not a cap.

    A stake too small for one increment is a NAMED refusal, not a zero
    quantity. The venue would reject a zero anyway -- at the venue, in the one
    place a rejection is expensive to interpret.
    """
    stake = _positive_float(stake_dollars, "stake")
    unit_price = _positive_float(price, "price")
    increment = _positive_float(minimum_qty, "minimum_trade_qty")

    raw = stake / unit_price
    steps = math.floor(round(raw / increment, 9))
    quantity = round(steps * increment, 9)
    if quantity < increment:
        raise OrderBuildError(
            f"stake_below_minimum_quantity: stake={stake} price={unit_price} min_qty={increment}"
        )
    return quantity


def order_body(
    request: Any,
    *,
    market_slug: str,
    price_dollars: float,
    tick_size: Any,
    minimum_trade_qty: Any,
) -> dict[str, Any]:
    """The JSON body for one order. PURE -- no clock, no network, no env.

    `tick_size` and `minimum_trade_qty` are REQUIRED arguments rather than
    optional ones with defaults. The documentation says not to infer them, and
    an optional parameter with a plausible default is an inference wearing a
    keyword.
    """
    slug = str(market_slug or "").strip()
    if not slug:
        raise OrderBuildError("no_market_slug")

    price = _positive_float(price_dollars, "price")
    if not price < 1.0:
        # A probability price is strictly inside (0, 1). A 1.0 is either a
        # settled market or a unit error, and both should stop here.
        raise OrderBuildError(f"price_out_of_range: {price}")

    snapped = round_price_to_tick(price, tick_size)
    if snapped <= 0:
        raise OrderBuildError(f"price_below_one_tick: price={price} tick={tick_size}")

    stake = float(getattr(request, "requested_stake_dollars", 0.0) or 0.0)
    # SIZED AGAINST THE PRICE WE WILL PAY, which is the snapped one. Sizing off
    # the unsnapped price would buy a quantity the order cannot afford at the
    # price actually sent.
    quantity = quantity_for_stake(stake, snapped, minimum_trade_qty)

    from syndicate.features.shared.execution_ledger import idempotency_key

    return {
        "marketSlug": slug,
        "type": _TYPE_LIMIT,
        # An OBJECT with a currency, not a bare number -- the documented
        # `Amount` shape, used for every price and cash field on this venue.
        "price": {"value": f"{snapped:.6f}".rstrip("0").rstrip("."), "currency": _CURRENCY},
        "quantity": quantity,
        "tif": _TIF_GTC,
        # THE NO SIDE IS REAL. See the module docstring: an under is a BUY of
        # NO, not a SELL of YES at the complement. Kalshi's inversion does not
        # belong here and its absence is deliberate.
        "outcomeSide": _side_to_outcome(getattr(request, "side", None)),
        "action": _ACTION_BUY,
        "manualOrderIndicator": _MANUAL_INDICATOR,
        # The ledger's key, sent so the venue can reject a duplicate we cannot
        # see -- the same reasoning `kalshi_orders` uses for `client_order_id`:
        # a submit that landed and whose response we lost is real, and the
        # venue is the only place that question can be answered.
        "clientOrderId": idempotency_key(request),
    }


def _orders_url() -> str:
    from syndicate.features.shared.polymarket_us_auth import BASE_URL

    base = (os.environ.get("POLYMARKET_US_API_BASE") or "").strip() or BASE_URL
    path = (os.environ.get("POLYMARKET_US_ORDER_PATH") or _ORDERS_PATH).strip()
    if not path.startswith("/"):
        path = f"/{path}"
    # An override without a deploy, because Kalshi's create route MOVED and
    # cost an `http_410` to discover. This one is documented, but "documented"
    # was also true of the route that had moved.
    return f"{base.rstrip('/')}{path}"


def submit_order(
    request: Any,
    *,
    price_dollars: float,
    market_slug: str,
    tick_size: Any,
    minimum_trade_qty: Any,
) -> dict[str, Any]:
    """Send one order. Returns the shape `place_order` expects from an adapter.

    Raises on anything it cannot complete, which is what `place_order` needs: a
    raised submit is recorded and KEPT for reconciliation, whereas a returned
    falsy result would be read as a fill of nothing.
    """
    from syndicate.features.shared.polymarket_us_auth import signed_request

    body = order_body(
        request,
        market_slug=market_slug,
        price_dollars=price_dollars,
        tick_size=tick_size,
        minimum_trade_qty=minimum_trade_qty,
    )
    url = _orders_url()
    # THE REQUEST, BEFORE THE RESPONSE. If the venue rejects the body, the
    # error alone cannot say which field it disliked. Nothing here is a
    # credential; it is a slug, a side, a size and a price.
    print(
        f"[polymarket_us_orders] SUBMIT url={url} slug={body.get('marketSlug')}"
        f" side={body.get('outcomeSide')} action={body.get('action')}"
        f" qty={body.get('quantity')} price={body.get('price')}"
        f" tif={body.get('tif')}",
        flush=True,
    )
    response = signed_request("POST", url, body=body)

    # WHAT THE VENUE ACTUALLY SAYS, never a default of `filled`. The documented
    # 200 carries only an `id` -- creation, NOT execution. Kalshi's phantom
    # fill came from exactly this: an accepted order booked as a traded one.
    # An order id with no status is `submitted`, which is precisely true.
    order = response.get("order") if isinstance(response.get("order"), Mapping) else response
    raw_status = str(order.get("status") or "").strip().lower()
    executed = raw_status in _VENUE_FILLED_STATUSES

    return {
        "status": "filled" if executed else "submitted",
        "venue_order_id": order.get("id") or order.get("orderId"),
        "venue_status": raw_status or None,
        "fill_price": price_dollars if executed else None,
        "fill_stake_dollars": (
            round(float(body["quantity"]) * float(price_dollars), 2) if executed else None
        ),
        "contracts": float(body["quantity"]) if executed else 0,
        "requested_contracts": float(body["quantity"]),
    }


def polymarket_us_submitter(resolve_market):
    """An adapter bound to a market resolver, for `place_order(submit=...)`.

    `resolve_market(request)` must return `(slug, price, tick_size, min_qty)`
    -- all four from the venue's own market response. It is injected rather
    than imported so this module stays free of the board join, and so the
    "never infer tick size" rule has one owner rather than one per caller.
    """

    def submit(request: Any) -> dict[str, Any]:
        resolved = resolve_market(request)
        if not resolved:
            raise OrderBuildError("market_unresolved_for_position")
        slug, price, tick, min_qty = resolved
        return submit_order(
            request,
            price_dollars=price,
            market_slug=slug,
            tick_size=tick,
            minimum_trade_qty=min_qty,
        )

    return submit
