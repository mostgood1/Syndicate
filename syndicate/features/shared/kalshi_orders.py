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
from collections.abc import Mapping
from typing import Any

__all__ = [
    "contracts_for_stake",
    "order_body",
    "order_body_v2",
    "build_order_body",
    "submit_order",
    "fetch_order",
    "fetch_orders",
    "venue_order_view",
    "kalshi_submitter",
    "OrderBuildError",
]

# See the docstring. Dollars, matching the market read fields.
ORDER_PRICE_UNIT = "dollars"

# Kalshi's own minimum. A single contract is the smallest thing that can be
# bought, so this is arithmetic rather than policy.
_MIN_CONTRACTS = 1

# Venue statuses that mean the trade HAPPENED. Everything else -- `resting`,
# `pending`, `canceled`, or anything unrecognised -- is not a fill, and is
# recorded as `submitted` rather than guessed into one.
_VENUE_FILLED_STATUSES = frozenset({"executed", "filled", "matched", "closed"})

# ...and the two other things a venue status can mean. Split rather than
# lumped into "not filled", because they have opposite consequences: a RESTING
# order may still trade and must stay in the ledger untouched, while a DEAD one
# never will and frees both its budget and its idempotency key.
_VENUE_RESTING_STATUSES = frozenset({"resting", "pending", "open", "queued", "accepted", "active"})
_VENUE_DEAD_STATUSES = frozenset({"canceled", "cancelled", "expired", "rejected"})


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
    # THE PRICE FIELD, AND THE ONE ASSUMPTION NOTHING HAS TESTED.
    #
    # Kalshi's v2 order contract has long taken `yes_price`/`no_price` as
    # INTEGER CENTS (1-99). This module sends `*_price_dollars`, which exists
    # in newer API surfaces -- and that spelling was inferred from the MARKET
    # READ fields, which are dollars. Nothing has ever confirmed the write side
    # agrees, because the endpoint has never been reached: both live attempts
    # so far died at `OrderBuildError` before a request was assembled.
    #
    # An inference from a neighbouring field, never checked against the thing
    # it describes, is the exact shape of the game-date bug (`close_time` read
    # as first pitch) and the title-grammar bug ("Will the X win by..." against
    # "X wins by..."). So it is switchable rather than argued about, and the
    # first real response settles it -- `submit_order` logs which form it sent.
    unit = (os.environ.get("KALSHI_ORDER_PRICE_UNIT") or ORDER_PRICE_UNIT).strip().lower()
    if unit == "cents":
        cents = int(round(price * 100))
        if not 1 <= cents <= 99:
            # A contract settles at $1, so a price outside 1-99c is not a price.
            raise OrderBuildError(f"price_out_of_range_cents: {cents}")
        body[f"{side}_price"] = cents
    else:
        body[f"{side}_price_dollars"] = round(price, 4)
    return body


# The order path, SEPARATE from the API base and overridable on its own.
#
# MEASURED 2026-08-24, the first real response this endpoint ever gave us:
#
#   http_410 https://external-api.kalshi.com/trade-api/v2/portfolio/orders
#   {"error":{"code":"deprecated_v1_order_endpoint",
#             "message":"Please switch to the V2 endpoints",
#             "details":"https://docs.kalshi.com/api-reference/orders/create-order-v2"}}
#
# `/trade-api/v2/portfolio/orders` carries `v2` in the path and Kalshi calls it
# the V1 ORDER endpoint. Those are two different versionings -- the API surface
# and the order contract -- and reading the `v2` in the URL as proof the order
# route was current was wrong.
#
# Kept overridable because the replacement path is not yet known here: the docs
# host is blocked from this environment, and inventing a route would repeat the
# mistake this comment records. One env var moves it, no deploy.
_DEFAULT_ORDER_PATH = "/portfolio/events/orders"


# The v2 order body, from the contract the owner supplied 2026-08-24. Every
# field below appears in that sample; nothing here is inferred from a
# neighbouring endpoint, which is what produced the 410 and the price-unit
# guess before it.
#
#   POST /trade-api/v2/portfolio/events/orders
#   {"ticker": "...", "client_order_id": "...", "side": "bid",
#    "count": "10.00", "price": "0.5600",
#    "time_in_force": "good_till_canceled",
#    "self_trade_prevention_type": "taker_at_cross",
#    "post_only": false, "cancel_order_on_pause": false,
#    "reduce_only": false, "subaccount": 0, "exchange_index": 0}
#
# STRINGS, not numbers. `count` and `price` are quoted decimals in the sample,
# and a JSON number where a string is expected is a rejection whose message
# will not say which field it meant.
_V2_TIME_IN_FORCE = "good_till_canceled"
_V2_SELF_TRADE_PREVENTION = "taker_at_cross"


def order_body_v2(request: Any, *, price_dollars: float | None = None) -> dict[str, Any]:
    """The body `POST /portfolio/events/orders` takes. PURE -- no clock, no net.

    Both sides are expressible, and neither is a guess: Kalshi quotes this
    endpoint entirely from the YES leg, so an over is a `bid` at our price and
    an under is an `ask` at its complement. See the comment on `book_side`.
    """
    ticker = str(getattr(request, "venue_ticker", "") or "").strip()
    if not ticker:
        raise OrderBuildError("no_venue_ticker")

    if price_dollars is None:
        raise OrderBuildError("no_price_dollars")
    price = float(price_dollars)
    if price <= 0 or price >= 1:
        raise OrderBuildError(f"price_out_of_range: {price}")

    # EVERYTHING IS QUOTED FROM THE YES SIDE. Kalshi's contract:
    #
    #   "bid means buy YES, ask means sell YES. (Selling YES is economically
    #    equivalent to buying NO at 1 - price, but this endpoint quotes
    #    everything from the YES side.)"
    #
    # So an UNDER is not "side: no" -- there is no such value. It is an ASK at
    # the complement of the price we want to pay for NO.
    contract_side = _side_to_kalshi(getattr(request, "side", None))
    stake = float(getattr(request, "requested_stake_dollars", 0.0) or 0.0)

    if contract_side == "yes":
        book_side = "bid"
        quote_price = price
    else:
        book_side = "ask"
        quote_price = round(1.0 - price, 4)
        if quote_price <= 0 or quote_price >= 1:
            raise OrderBuildError(f"complement_out_of_range: {quote_price}")

    # THE COUNT DOES NOT INVERT, AND THIS IS THE EASY THING TO GET WRONG.
    # Buying NO at $0.40 is selling YES at $0.60, but the capital committed is
    # still $0.40 per contract -- so the size comes from the price we PAY, not
    # from the price we quote. Dividing the stake by 0.60 here would buy ~33%
    # fewer contracts than the stake was sized for, silently, on every under.
    count = contracts_for_stake(stake, price)

    from syndicate.features.shared.execution_ledger import idempotency_key

    return {
        "ticker": ticker,
        "client_order_id": idempotency_key(request),
        "side": book_side,
        # Quoted decimals, matching the sample exactly.
        "count": f"{count:.2f}",
        "price": f"{quote_price:.4f}",
        "time_in_force": _V2_TIME_IN_FORCE,
        "self_trade_prevention_type": _V2_SELF_TRADE_PREVENTION,
        "post_only": False,
        "cancel_order_on_pause": False,
        "reduce_only": False,
        "subaccount": 0,
        "exchange_index": 0,
    }


def build_order_body(request: Any, *, price_dollars: float | None = None) -> dict[str, Any]:
    """Whichever contract is selected. v2 by default -- v1 is confirmed dead.

    `KALSHI_ORDER_CONTRACT=v1` restores the old body for the old route, kept
    only so a rollback is possible without a deploy.
    """
    contract = (os.environ.get("KALSHI_ORDER_CONTRACT") or "v2").strip().lower()
    if contract == "v1":
        return order_body(request, price_dollars=price_dollars)
    return order_body_v2(request, price_dollars=price_dollars)


def _orders_url() -> str:
    from syndicate.features.shared.kalshi_client import _BASE_URLS

    base = (os.environ.get("KALSHI_API_BASE") or "").strip() or _BASE_URLS[0]
    path = (os.environ.get("KALSHI_ORDER_PATH") or _DEFAULT_ORDER_PATH).strip()
    if not path.startswith("/"):
        path = f"/{path}"
    # An absolute override wins outright, for a route that does not hang off
    # the same base at all.
    if path.startswith("http://") or path.startswith("https://"):
        return path
    override = (os.environ.get("KALSHI_ORDER_URL") or "").strip()
    return override or f"{base.rstrip('/')}{path}"


def submit_order(request: Any, *, price_dollars: float | None = None) -> dict[str, Any]:
    """Send one order. Returns the shape `place_order` expects from an adapter.

    Raises on anything it cannot complete, which is what `place_order` needs: a
    raised submit is recorded as `failed` and KEPT for reconciliation, whereas a
    returned falsy result would be read as a fill of nothing.
    """
    from syndicate.features.shared.kalshi_auth import signed_request

    body = build_order_body(request, price_dollars=price_dollars)
    url = _orders_url()
    # THE REQUEST, BEFORE THE RESPONSE. If Kalshi rejects the body, the error
    # alone cannot say which field it disliked -- and this is the one call in
    # the system whose contract is still inferred rather than confirmed. Price
    # and count are the fields in question; nothing here is a credential.
    print(
        f"[kalshi_orders] SUBMIT url={url}"
        f" ticker={body.get('ticker')} side={body.get('side')}"
        f" count={body.get('count')}"
        f" price={body.get('price') or [v for k, v in body.items() if 'price' in k]}"
        f" tif={body.get('time_in_force')}",
        flush=True,
    )
    response = signed_request("POST", url, body=body)
    order = response.get("order") or response

    # `count` is what we ASKED for; the fill can be partial. Reported from the
    # response where the response says so, and from the request only where it
    # does not -- a partial fill recorded as a full one is a position size we
    # believe and do not hold.
    # `count` is a QUOTED DECIMAL in the v2 body ("8.00"), so `int()` on it
    # raises -- which would turn a successful submit into a `failed` record
    # after the money had already moved, the worst possible place to throw.
    requested = int(float(body["count"]))

    # WHAT THE VENUE ACTUALLY SAYS HAPPENED -- never a default of `filled`.
    #
    # MEASURED 2026-08-24T13:12Z, and this is the worst bug of the run: our
    # ledger read `status=filled fill_price=0.54` for an order that was RESTING
    # and unfilled on Kalshi. The line was `str(order.get("status") or
    # "filled")` -- an accepted-but-unexecuted order returns a status we did not
    # map, or none, and the default booked a position that does not exist.
    #
    # A created order and an executed order are different facts. Defaulting the
    # UNKNOWN case to the most committal one is exactly backwards: settlement
    # grades a bet that never happened, P&L books it, and reconciliation against
    # the venue becomes impossible because our record and their book disagree
    # about whether a trade occurred.
    #
    # So: filled ONLY on an explicit executed/filled status, or on a positive
    # filled_count. Anything else is `submitted` -- the write-ahead state that
    # means "the venue has it, the outcome is not known here" -- which is
    # precisely true of a resting limit order.
    raw_status = str(order.get("status") or "").strip().lower()
    filled_raw = order.get("filled_count")
    try:
        filled_count = int(float(filled_raw)) if filled_raw is not None else None
    except (TypeError, ValueError):
        filled_count = None

    executed = raw_status in _VENUE_FILLED_STATUSES or bool(filled_count)
    if executed:
        contracts = filled_count if filled_count is not None else requested
        status = "filled"
        fill_price = price_dollars
    else:
        # RESTING, PENDING, or a status we have never seen. None of them is a
        # fill, and a fill_price on an unfilled order is a number that will be
        # believed.
        contracts = 0
        status = "submitted"
        fill_price = None

    return {
        "status": status,
        "venue_order_id": order.get("order_id") or order.get("id"),
        "venue_status": raw_status or None,
        "fill_price": fill_price,
        "fill_stake_dollars": round(contracts * float(price_dollars or 0.0), 2),
        "contracts": contracts,
        "requested_contracts": requested,
    }


# ---------------------------------------------------------------------------
# READING THE VENUE. The ledger is a claim; this is the fact.
# ---------------------------------------------------------------------------
#
# MEASURED 2026-08-24T13:12Z: our ledger said `filled` for an order that was
# RESTING on Kalshi with `Filled: 0`. The submit path has been corrected so it
# never defaults to a fill again, but the correction only governs orders placed
# from now on -- and it cannot govern the interesting case at all, which is an
# order whose state CHANGES after we stop looking. A resting order that fills
# ten minutes later is a real position that our ledger will never learn about
# from the submit response, because that response was written before the fill.
#
# So the ledger has to be refreshed FROM the venue, not merely written
# carefully. These two reads are that source.


def _read_base() -> str:
    from syndicate.features.shared.kalshi_auth import _base_url

    return _base_url()


def _order_read_path() -> str:
    path = (os.environ.get("KALSHI_ORDER_READ_PATH") or "/portfolio/orders").strip()
    return path if path.startswith("/") else f"/{path}"


def _order_read_url(order_id: str) -> str:
    return f"{_read_base().rstrip('/')}{_order_read_path()}/{order_id}"


def _orders_list_url(limit: int) -> str:
    return f"{_read_base().rstrip('/')}{_order_read_path()}?limit={int(limit)}"


def _unwrap_order(payload: Any) -> dict[str, Any] | None:
    if isinstance(payload, Mapping):
        inner = payload.get("order")
        if isinstance(inner, Mapping):
            return dict(inner)
        return dict(payload)
    return None


def fetch_order(order_id: Any) -> dict[str, Any]:
    """What the VENUE says about one order.

        GET /trade-api/v2/portfolio/orders/{order_id}

    Note this shares a prefix with the POST route that returns 410 for
    creation. Reading is fine there; only the create verb moved. Learned by
    taking the 410 in production, so it is written down rather than left to be
    rediscovered.

    Returns a NAMED failure rather than raising: reconciliation runs over every
    open order, and one unreadable order must not stop the rest.
    """
    from syndicate.features.shared.kalshi_auth import signed_request

    key = str(order_id or "").strip()
    if not key:
        return {"status": "error", "reason": "no_order_id"}
    try:
        payload = signed_request("GET", _order_read_url(key))
    except Exception as exc:
        return {"status": "error", "reason": f"{type(exc).__name__}: {exc}"}
    order = _unwrap_order(payload)
    if order is None:
        return {"status": "error", "reason": f"unexpected_shape:{type(payload).__name__}"}
    return {"status": "ok", "order": order}


def fetch_orders(*, limit: int = 100) -> dict[str, Any]:
    """Every recent order, one call.

        GET /trade-api/v2/portfolio/orders?limit=100

    The LIST is the primary instrument for reconciliation and the single read
    is the fallback: one call covers the whole open book, so a pass over N open
    orders costs one request rather than N. It also answers the case a
    per-order read cannot -- an order we hold no id for, because the submit
    response was lost.

    Same contract as `fetch_order`: named failure, never a raise, never an
    empty list standing in for an error. An empty `orders` on a FAILED read
    would read as "the venue holds nothing", which is the exact confusion that
    would wipe a live position out of the ledger.
    """
    from syndicate.features.shared.kalshi_auth import signed_request

    try:
        payload = signed_request("GET", _orders_list_url(limit))
    except Exception as exc:
        return {"status": "error", "reason": f"{type(exc).__name__}: {exc}"}
    if not isinstance(payload, Mapping):
        return {"status": "error", "reason": f"unexpected_shape:{type(payload).__name__}"}
    raw = payload.get("orders")
    if not isinstance(raw, list):
        return {"status": "error", "reason": "no_orders_array"}
    orders = [dict(o) for o in raw if isinstance(o, Mapping)]
    # THE SHAPE, ONCE. This response has never been seen; `kalshi_client`'s
    # first live run corrected ten field names, and the same reporting is what
    # caught them. Keys only -- an order carries no credential, but it does
    # carry our own positions, and the log is not the place for them.
    if orders:
        print(
            f"[kalshi_orders] ORDERS_READ n={len(orders)} keys={sorted(orders[0].keys())}",
            flush=True,
        )
        # THE VALUES OF THE COUNT AND MONEY FIELDS, for the first order only.
        # The keys log settled the field NAMES and immediately raised the next
        # question it could not answer: `_fp` is undocumented, and whether
        # `fill_count_fp` is 2 or 2000000 for a 2-contract fill decides whether
        # a booked position is right or six orders of magnitude wrong. One
        # production line settles it.
        #
        # These are our own order sizes and fees, not credentials. Scoped to
        # the count and money fields for that reason -- the whole order carries
        # ids and account fields that have no business in a log.
        sample = orders[0]
        watched = _COUNT_FILLED_FIELDS + _COUNT_INITIAL_FIELDS + _COUNT_REMAINING_FIELDS
        watched += _FEE_FIELDS + _FILL_COST_FIELDS + ("status", "yes_price_dollars", "no_price_dollars")
        print(
            "[kalshi_orders] COUNT_FIELDS "
            + " ".join(f"{f}={sample.get(f)!r}" for f in watched if f in sample),
            flush=True,
        )
    else:
        print("[kalshi_orders] ORDERS_READ n=0", flush=True)
    return {"status": "ok", "orders": orders}


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _price_or_none(value: Any) -> float | None:
    """A Kalshi price as PROBABILITY DOLLARS, whichever unit it arrived in.

    The order read quotes `yes_price_dollars` / `no_price_dollars`, so dollars
    is the documented unit -- but this is the fallback path for the fields that
    are NOT suffixed, where a cents quote is possible. Anything above 1 is
    therefore cents; anything at or below 1 is already dollars. The boundary is
    unambiguous because a probability price cannot exceed $1, and the 100x
    error is one the first live market read actually made.
    """
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return round(number / 100.0, 4) if number > 1 else round(number, 4)


# THE REAL FIELD NAMES, read off a live response at 2026-08-24T14:37:16Z.
#
#   ['action', 'book_side', 'client_order_id', 'created_time', 'exchange_index',
#    'fill_count_fp', 'initial_count_fp', 'last_update_time',
#    'maker_fees_dollars', 'maker_fill_cost_dollars', 'no_price_dollars',
#    'order_id', 'outcome_side', 'remaining_count_fp',
#    'self_trade_prevention_type', 'side', 'status', 'subaccount_number',
#    'taker_fees_dollars', 'taker_fill_cost_dollars', 'ticker', 'type',
#    'user_id', 'yes_price_dollars']
#
# Not one of the three count spellings guessed here beforehand was right. The
# earlier spellings are KEPT as fallbacks rather than deleted: they cost
# nothing, and this contract has now moved once.
_COUNT_FILLED_FIELDS = ("fill_count_fp", "filled_count", "fill_count")
_COUNT_INITIAL_FIELDS = ("initial_count_fp", "initial_count")
_COUNT_REMAINING_FIELDS = ("remaining_count_fp", "remaining_count")
_FEE_FIELDS = ("taker_fees_dollars", "maker_fees_dollars")
_FILL_COST_FIELDS = ("taker_fill_cost_dollars", "maker_fill_cost_dollars")


def _first_present(order: Mapping[str, Any], fields: tuple[str, ...]) -> Any:
    for field in fields:
        if order.get(field) is not None:
            return order.get(field)
    return None


def _sum_present(order: Mapping[str, Any], fields: tuple[str, ...]) -> float | None:
    """Total across fields, or None if NOT ONE of them is present.

    None and 0.0 are different answers here. Kalshi splits fees and fill cost
    across a maker and a taker leg, and an order that filled entirely as a
    taker carries a real 0.0 on the maker leg -- so a sum of the present legs
    is the total. But an order carrying NEITHER leg has told us nothing, and
    reporting that as $0.00 of fees is a fee we would then never charge.
    """
    total = 0.0
    seen = False
    for field in fields:
        value = _float_or_none(order.get(field))
        if value is None:
            continue
        seen = True
        total += value
    return round(total, 6) if seen else None


def venue_order_view(order: Mapping[str, Any]) -> dict[str, Any]:
    """One Kalshi order, reduced to the facts the ledger needs.

    `state` is our vocabulary, not Kalshi's: `filled`, `resting`, `dead`, or
    `unknown`. UNKNOWN IS A REAL ANSWER and is why this returns a state rather
    than a boolean -- a status we have never seen must not be collapsed into
    either "it traded" or "it didn't", and reconciliation leaves those rows
    exactly as they are.

    A PARTIAL FILL THAT WAS THEN CANCELLED IS A FILL. The cancelled status
    describes the remainder; the contracts that traded are a position we hold.
    So the fill count is read first and outranks the status -- reading them the
    other way round is how a real position gets reconciled away to zero.

    ------------------------------------------------------------------
    WHAT `_fp` MEANS IS NOT KNOWN, AND IS NOT GUESSED
    ------------------------------------------------------------------

    `fill_count_fp` and friends are the real field names, but the suffix is
    undocumented here -- plausibly "floating point", plausibly a fixed-point
    integer with a scale. If it is a scale, a 2-contract fill reads as some
    large number, and booking it would claim a position orders of magnitude
    larger than anything we could have bought.

    Two things make that safe without knowing the answer. The raw values are
    logged (`COUNT_FIELDS`), so one production read settles it. And
    `reconcile_live_orders` refuses to book more contracts than the order
    requested -- an invariant that holds regardless of the scale, and which is
    worth having even once the scale is known.
    """
    raw_status = str(order.get("status") or "").strip().lower()

    filled = _int_or_none(_first_present(order, _COUNT_FILLED_FIELDS))
    if filled is None:
        taker = _int_or_none(order.get("taker_fill_count")) or 0
        maker = _int_or_none(order.get("maker_fill_count")) or 0
        if taker or maker:
            filled = taker + maker
    if filled is None:
        initial = _int_or_none(_first_present(order, _COUNT_INITIAL_FIELDS))
        remaining = _int_or_none(_first_present(order, _COUNT_REMAINING_FIELDS))
        if initial is not None and remaining is not None:
            filled = max(initial - remaining, 0)

    if filled:
        state = "filled"
    elif raw_status in _VENUE_FILLED_STATUSES:
        # Executed with no count we could read -- the trade happened, the size
        # did not survive the parse. Reported as filled with an unknown count
        # rather than as zero contracts, which would be a lie in the direction
        # that loses a position.
        state = "filled"
    elif raw_status in _VENUE_RESTING_STATUSES:
        state = "resting"
    elif raw_status in _VENUE_DEAD_STATUSES:
        state = "dead"
    else:
        state = "unknown"

    # WHAT WE ACTUALLY PAID, from the venue's own arithmetic rather than ours.
    # `count * price` was always a reconstruction; this is the number Kalshi
    # billed. It also makes the fill price a division rather than a guess about
    # which of `yes_price_dollars` / `no_price_dollars` is our leg.
    fill_cost = _sum_present(order, _FILL_COST_FIELDS)
    fees = _sum_present(order, _FEE_FIELDS)

    price = None
    if fill_cost is not None and filled:
        price = round(fill_cost / filled, 4)
    if price is None:
        for field in ("average_fill_price", "avg_fill_price", "fill_price"):
            price = _price_or_none(order.get(field))
            if price is not None:
                break

    return {
        "state": state,
        "venue_status": raw_status or None,
        "filled_count": filled,
        "fill_price": price,
        "fill_cost_dollars": fill_cost,
        "fees_dollars": fees,
        "order_id": order.get("order_id") or order.get("id"),
        "client_order_id": order.get("client_order_id"),
        "ticker": order.get("ticker"),
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
