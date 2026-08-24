"""Turn a committed position into a Kalshi order, and send it.

The venue adapter `execution_ledger.place_order` calls in live mode. Everything
above it -- the plan, the caps, the kill switch, the write-ahead record -- is
venue-agnostic; this is the one file that knows Kalshi buys CONTRACTS.

--------------------------------------------------------------------------
DOLLARS ARE NOT CONTRACTS, AND THE CONVERSION MUST FLOOR
--------------------------------------------------------------------------

The portfolio decides a stake in dollars. Kalshi sells contracts that settle at
$1, so a $0.62 contract bought 8 times is $4.96 of a $5.00 stake. The remainder
is DROPPED, never rounded up: rounding to 9 contracts spends $5.58 against a cap
that said $5.00, and a cap that the sizing quietly exceeds is not a cap.

A stake too small to buy even one contract is a NAMED refusal
(`stake_below_one_contract`), not a zero-count order. Kalshi would reject a
zero-count order anyway, but it would reject it at the venue, in the one place
where a rejection is expensive to interpret -- and an adapter that sends
requests it knows are invalid is an adapter whose error log stops meaning
anything.

--------------------------------------------------------------------------
IDEMPOTENCY IS ASSERTED AT THE VENUE, NOT ONLY IN OUR LEDGER
--------------------------------------------------------------------------

`execution_ledger` refuses a duplicate it can SEE. It cannot see a submit that
reached Kalshi and whose response we lost -- the write-ahead record exists
precisely because that gap is real. So the ledger's idempotency key is sent as
Kalshi's `client_order_id`: if the lost submit did land, the retry is the venue's
duplicate to reject, which is the only place the question can actually be
answered.

--------------------------------------------------------------------------
UNVERIFIED, AND SHAPED AROUND THAT
--------------------------------------------------------------------------

The proxy 403s CONNECT to every Kalshi host, so no call in this file has ever
run. `kalshi_client`'s first live run corrected 10 of 17 field names and a 100x
price error; assume the same rate here. The order body is built in ONE place
(`order_body`) and is pure -- it is unit-tested as a dict, so when the live run
corrects a field name, the fix is one edit and the tests still mean something.

`ORDER_PRICE_UNIT` is the assumption most likely to be wrong and most expensive
if it is: Kalshi's market reads return `yes_ask_dollars`, so this sends
`yes_price_dollars`. If the order endpoint wants integer cents instead, a
0.62 sent as dollars is a 62-cent bid read as $0.0062 -- an order that never
fills, which is the SAFE direction of that error. It is the safe direction on
purpose.
"""

from __future__ import annotations

import math
import os
from typing import Any

__all__ = [
    "contracts_for_stake",
    "order_body",
    "submit_order",
    "kalshi_submitter",
    "OrderBuildError",
]

# See the docstring. Dollars, matching the market read fields.
ORDER_PRICE_UNIT = "dollars"

# Kalshi's own minimum. A single contract is the smallest thing that can be
# bought, so this is arithmetic rather than policy.
_MIN_CONTRACTS = 1


class OrderBuildError(ValueError):
    """The request cannot become a valid order. Raised BEFORE anything is sent.

    `venue_contacted = False` is the machine-readable half of that sentence,
    and `place_order` reads it to record these as REJECTED rather than FAILED.
    The docstring alone said the same thing and no code could act on it, so
    every build error was charged against the live daily budget as though it
    might have reached Kalshi.
    """

    venue_contacted = False


def contracts_for_stake(stake_dollars: float, price_dollars: float) -> int:
    """How many contracts `stake_dollars` buys at `price_dollars`. FLOORED.

    Raises rather than returning 0: a zero-count order is not a smaller bet, it
    is an invalid request, and the two must not share a return value.
    """
    if price_dollars <= 0 or price_dollars >= 1:
        # A contract settles at $1, so a price outside (0, 1) is not a price.
        raise OrderBuildError(f"price_out_of_range: {price_dollars}")
    if stake_dollars <= 0:
        raise OrderBuildError(f"non_positive_stake: {stake_dollars}")
    count = math.floor(stake_dollars / price_dollars)
    if count < _MIN_CONTRACTS:
        raise OrderBuildError(
            f"stake_below_one_contract: ${stake_dollars:.2f} at ${price_dollars:.2f}"
        )
    return int(count)


def _side_to_kalshi(side: Any) -> str:
    """Our `over`/`under`/`yes`/`no` -> Kalshi's `yes`/`no`.

    Explicit, and it REFUSES an unmapped side. Defaulting to `yes` would turn an
    unrecognised side into a real bet on the opposite outcome -- the single most
    expensive silent default available in this file.
    """
    raw = str(side or "").strip().lower()
    if raw in {"yes", "over"}:
        return "yes"
    if raw in {"no", "under"}:
        return "no"
    raise OrderBuildError(f"unmappable_side: {side!r}")


def order_body(request: Any, *, price_dollars: float | None = None) -> dict[str, Any]:
    """The JSON body for one order. PURE -- no clock, no network, no env.

    Pure so it can be tested as a dict and diffed against whatever the live run
    says Kalshi actually wants.
    """
    ticker = str(getattr(request, "venue_ticker", "") or "").strip()
    if not ticker:
        # The one field the venue needs that nothing else in the system does.
        # Refused by name rather than derived here: deriving it at submit time
        # means deriving it from a catalogue that may have moved since we priced.
        raise OrderBuildError("no_venue_ticker")

    side = _side_to_kalshi(getattr(request, "side", None))
    price = price_dollars
    if price is None:
        raise OrderBuildError("no_price_dollars")
    price = float(price)
    count = contracts_for_stake(float(getattr(request, "requested_stake_dollars", 0.0) or 0.0), price)

    from syndicate.features.shared.execution_ledger import idempotency_key

    body: dict[str, Any] = {
        "ticker": ticker,
        "action": "buy",
        "side": side,
        "count": count,
        # LIMIT, always. A market order on a thin exchange book is an order at
        # whatever the worst resting offer happens to be, and the whole premise
        # of this system is that we have an edge AT A PRICE.
        "type": "limit",
        # Sent so a retry after a lost response is Kalshi's duplicate to reject.
        "client_order_id": idempotency_key(request),
    }
    body[f"{side}_price_dollars"] = round(price, 4)
    return body


def _orders_url() -> str:
    from syndicate.features.shared.kalshi_client import _BASE_URLS

    base = (os.environ.get("KALSHI_API_BASE") or "").strip() or _BASE_URLS[0]
    return f"{base}/portfolio/orders"


def submit_order(request: Any, *, price_dollars: float | None = None) -> dict[str, Any]:
    """Send one order. Returns the shape `place_order` expects from an adapter.

    Raises on anything it cannot complete, which is what `place_order` needs: a
    raised submit is recorded as `failed` and KEPT for reconciliation, whereas a
    returned falsy result would be read as a fill of nothing.
    """
    from syndicate.features.shared.kalshi_auth import signed_request

    body = order_body(request, price_dollars=price_dollars)
    response = signed_request("POST", _orders_url(), body=body)
    order = response.get("order") or response

    # `count` is what we ASKED for; the fill can be partial. Reported from the
    # response where the response says so, and from the request only where it
    # does not -- a partial fill recorded as a full one is a position size we
    # believe and do not hold.
    filled = order.get("filled_count")
    contracts = int(filled) if filled is not None else int(body["count"])
    return {
        "status": str(order.get("status") or "filled"),
        "venue_order_id": order.get("order_id") or order.get("id"),
        "fill_price": price_dollars,
        "fill_stake_dollars": round(contracts * float(price_dollars or 0.0), 2),
        "contracts": contracts,
        "requested_contracts": int(body["count"]),
    }


def kalshi_submitter(price_for):
    """An adapter bound to a price resolver, for `place_order(submit=...)`.

    `price_for(request) -> float | None`. A resolver that cannot price the
    contract makes the adapter RAISE, so the order is recorded as failed rather
    than sent at a price nobody chose.
    """

    def _submit(request):
        price = price_for(request)
        if price is None:
            raise OrderBuildError(f"no_live_price: {getattr(request, 'venue_ticker', None)}")
        return submit_order(request, price_dollars=float(price))

    return _submit
