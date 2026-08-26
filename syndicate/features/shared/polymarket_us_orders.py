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
import urllib.parse
from collections.abc import Mapping, Sequence
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
    """Refused before anything was sent. Never means the venue saw it.

    `venue_contacted = False` is the MACHINE-READABLE half of that sentence,
    and its absence here was costing real budget. `execution_ledger` reads
    `getattr(exc, "venue_contacted", True)` -- defaulting to True, because an
    unknown exception may well have reached the venue -- so every Polymarket
    build refusal was booked as a FAILED order that had been sent.

    MEASURED 2026-08-25T17:59:06Z. A spreads position refused locally, before
    any request was built:

        LIVE_ORDER status=failed venue=polymarket market=spreads
            error='OrderBuildError: market_unresolved_for_position'
        EXECUTION placed=0 spent={'dollars': 2.39, 'orders': 1}

    $2.39 and one order charged against a $40 daily cap for something that
    never left the process. Kalshi's copy has carried this attribute since its
    own version of the same incident; this one did not.
    """

    venue_contacted = False


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


# Which entry of a market's `outcomes` array the YES side buys.
#
# Overridable WITHOUT A DEPLOY, deliberately. This convention was wrong once
# already at the cost of a real inverted order (below), and the venue is the
# only place the answer lives; an env override is how it gets corrected in
# minutes rather than in a build. Same reasoning as `POLYMARKET_US_ORDER_PATH`.
_YES_OUTCOME_INDEX_DEFAULT = 0


def yes_outcome_index() -> int:
    import os

    raw = str(os.environ.get("SYNDICATE_POLYMARKET_YES_OUTCOME_INDEX") or "").strip()
    return 1 if raw == "1" else _YES_OUTCOME_INDEX_DEFAULT


def outcome_side_for_index(index: Any) -> str:
    """Which `outcomeSide` buys `outcomes[index]`.

    THE ONLY SOUND WAY TO PICK A SIDE ON THIS VENUE. Polymarket's `outcomes`
    carry bare names -- two teams, or Over/Under -- never "yes"/"no". So the
    side we want is identified by MATCHING OUR TEAM AGAINST THAT ARRAY and
    using where it landed. Anything else is a positional guess about an array
    whose order is not guaranteed.

    Measured, and this is why the guarantee cannot be assumed: slug
    `aec-atp-domstr-markru` carries `outcomes: ["Martin Krumich", "Dominic
    Stephan Stricker"]` -- REVERSED relative to its own slug. So slug order is
    not outcomes order, and a rule derived from the slug is wrong for some
    unknown fraction of the book.
    """
    try:
        position = int(index)
    except (TypeError, ValueError):
        raise OrderBuildError(f"outcome_index_unreadable: {index!r}") from None
    if position not in (0, 1):
        raise OrderBuildError(f"outcome_index_out_of_range: {index!r}")
    return _SIDE_YES if position == yes_outcome_index() else _SIDE_NO


def _side_to_outcome(side: Any) -> str:
    """Our `over`/`under`/`yes`/`no` -> the venue's outcome side.

    REFUSES an unmapped side. Defaulting to YES would turn an unrecognised side
    into a real bet on the opposite outcome, which is the most expensive silent
    default available in this file.

    `home` AND `away` ARE REFUSED HERE, and their removal is the fix for a
    measured real-money error rather than a tidy-up. They used to map
    positionally -- `home` to YES, `away` to NO -- which is a claim about the
    ORDER of a market's `outcomes` array, not about our side. Measured
    2026-08-25T16:08:10Z on the first Polymarket order ever placed:

        ledger   side=home   Texas Rangers @ Chicago White Sox
                 slug=aec-mlb-tex-cws-2026-08-25   price=0.495   $1.42
        venue    "Buy TEX"   2.86 shares @ 49.5c   Pending

    Home is the WHITE SOX. The order bought TEXAS -- the other team -- at the
    price that had been resolved for the White Sox. Both halves of that are one
    bug: `_polymarket_resolve_market` picked the PRICE by matching our team
    against `outcomes`, then threw the index away, and this function picked the
    SIDE by position. Nothing made the two agree, so the order bought one team
    at the other team's price -- which is also why it did not fill, the limit
    being priced for a different outcome than the one it was buying.

    A game-line side must come from `outcome_side_for_index` instead, so the
    price and the side are two readings of ONE resolution. Refusing here keeps
    the positional path from being reachable again by a caller that forgets.
    """
    raw = str(side or "").strip().lower()
    if raw in {"home", "away"}:
        raise OrderBuildError(
            f"side_needs_outcome_index: {side!r} -- a team side must be resolved"
            " against the market's outcomes array, not by position"
        )
    if raw in {"yes", "over"}:
        return _SIDE_YES
    if raw in {"no", "under"}:
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
    outcome_index: Any = None,
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
        #
        # THE INDEX WINS WHEN THE RESOLVER FOUND ONE. It is the position our
        # own team occupies in this market's `outcomes` array -- the same
        # reading that selected the price -- so price and side describe one
        # outcome by construction. Falling back to the side name is for the
        # `yes`/`no`/`over`/`under` markets that name no team; `home`/`away`
        # refuse there rather than guessing positionally again.
        "outcomeSide": (
            outcome_side_for_index(outcome_index)
            if outcome_index is not None
            else _side_to_outcome(getattr(request, "side", None))
        ),
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
    outcome_index: Any = None,
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
        outcome_index=outcome_index,
    )
    url = _orders_url()
    # THE REQUEST, BEFORE THE RESPONSE. If the venue rejects the body, the
    # error alone cannot say which field it disliked. Nothing here is a
    # credential; it is a slug, a side, a size and a price.
    print(
        f"[polymarket_us_orders] SUBMIT url={url} slug={body.get('marketSlug')}"
        f" side={body.get('outcomeSide')} action={body.get('action')}"
        f" qty={body.get('quantity')} price={body.get('price')}"
        f" tif={body.get('tif')}"
        # OUR side beside the venue's, and the index that connects them. The
        # inverted order of 2026-08-25 was invisible in this line: it read
        # `side=OUTCOME_SIDE_YES` and said nothing about WHICH TEAM that buys,
        # so the log agreed with itself while the venue bought the other team.
        f" our_side={getattr(request, 'side', None)} outcome_index={outcome_index}"
        f" yes_index={yes_outcome_index()}",
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
    or, preferably, `(slug, price, tick_size, min_qty, outcome_index)` -- all
    from the venue's own market response. It is injected rather than imported
    so this module stays free of the board join, and so the "never infer tick
    size" rule has one owner rather than one per caller.

    `outcome_index` is where OUR side landed in the market's `outcomes` array.
    A resolver that has matched our team against that array already knows it,
    and passing it is what keeps the price and the side describing the same
    outcome. The four-value form stays accepted so an older resolver still
    works -- but a team side then refuses in `_side_to_outcome` rather than
    being placed positionally, which is the failure that made this argument
    necessary.
    """

    def submit(request: Any) -> dict[str, Any]:
        resolved = resolve_market(request)
        if not resolved:
            raise OrderBuildError("market_unresolved_for_position")
        outcome_index = None
        if len(resolved) == 5:
            slug, price, tick, min_qty, outcome_index = resolved
        else:
            slug, price, tick, min_qty = resolved
        return submit_order(
            request,
            price_dollars=price,
            market_slug=slug,
            tick_size=tick,
            minimum_trade_qty=min_qty,
            outcome_index=outcome_index,
        )

    return submit


# --------------------------------------------------------------------------
# THE READ SIDE. Without it a submitted order can never be reconciled, and an
# unreconciled order blocks EVERY live run on EVERY venue.
# --------------------------------------------------------------------------

_VENUE_RESTING_STATUSES = frozenset(
    {"resting", "pending", "open", "queued", "accepted", "active", "live", "new"}
)
_VENUE_DEAD_STATUSES = frozenset(
    {"canceled", "cancelled", "expired", "rejected", "failed", "voided"}
)

# THE DOCUMENTED LIST ROUTE -- and it lists OPEN orders only.
#
# That word is load-bearing and is why this is the FALLBACK rather than the
# primary read. A cancelled or filled order is simply absent from it, and
# absence is ambiguous: cancelled, filled, or merely not returned. Reconciliation
# already treats "not in the read" as `not_found` and changes nothing, which is
# correct and safe -- but it means this route ALONE can never clear a cancelled
# order, and a cancelled order left uncleared blocks live execution on every
# venue.
#
# `GET /v1/order/{orderId}` is the read that can say "dead", so it is the one
# used whenever the caller knows which orders it cares about (it always does --
# reconciliation starts from our own candidate list).
_ORDERS_LIST_PATH = "/v1/orders/open"


_ORDER_GET_PATH = "/v1/order"


def _order_url(order_id: str) -> str:
    """`GET /v1/order/{orderId}` -- the DOCUMENTED read, singular.

    Note the path is `order`, not `orders`: the create route is
    `POST /v1/orders` and the read is `GET /v1/order/{id}`. Sibling spellings
    that differ by one character and one verb, which is exactly why the list
    guess returned `code: 12` UNIMPLEMENTED rather than a 404.
    """
    from syndicate.features.shared.polymarket_us_auth import BASE_URL

    base = (os.environ.get("POLYMARKET_US_API_BASE") or "").strip() or BASE_URL
    path = (os.environ.get("POLYMARKET_US_ORDER_GET_PATH") or _ORDER_GET_PATH).strip()
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base.rstrip('/')}{path.rstrip('/')}/{urllib.parse.quote(str(order_id), safe='')}"


def _orders_list_url(limit: int) -> str:
    from syndicate.features.shared.polymarket_us_auth import BASE_URL

    base = (os.environ.get("POLYMARKET_US_API_BASE") or "").strip() or BASE_URL
    path = (os.environ.get("POLYMARKET_US_ORDERS_LIST_PATH") or _ORDERS_LIST_PATH).strip()
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base.rstrip('/')}{path}?limit={int(limit)}"


# Candidate list routes, in the order they are tried. GET ONLY -- a blind POST
# to an unknown path on a venue that holds real money could CREATE something,
# so the probe never uses a writing verb.
#
# The shapes are the ones a gRPC-gateway API takes, which is what this venue
# is: the 501 body was `{"code":12,...}` and its enums are prefixed
# (`ORDER_STATUS_CANCELED`). Code 12 is UNIMPLEMENTED -- the path exists for
# POST and simply has no GET handler, which is different from 404 and is why
# the sibling spellings below are worth asking about rather than concluding
# "this venue has no order list".
_ORDER_LIST_CANDIDATES = (
    "/v1/orders/list",
    "/v1/orders:list",
    "/v1/portfolio/orders",
    "/v1/user/orders",
    "/v1/orders/history",
    "/v1/order",
)


def probe_order_list_routes(*, limit: int = 1) -> dict[str, Any]:
    """Ask which order-list route this venue actually implements.

    READ-ONLY, and that is a safety property rather than a style choice: this
    runs against a live money account, so every candidate is a GET.

    Exists because guessing the second route after the first one 501s is the
    same mistake as guessing the first. `kalshi_client.probe` settled ten wrong
    field names this way, and `polymarket_us_markets.probe_v1_sports_routes`
    settled which `/v1` sports paths exist -- both by asking and reporting
    rather than by reasoning about what a route ought to be called.
    """
    from syndicate.features.shared import polymarket_us_auth as auth

    if not auth.credentials_present():
        return {"status": "skipped", "reason": "credentials_absent"}

    base = (os.environ.get("POLYMARKET_US_API_BASE") or "").strip() or auth.BASE_URL
    out: dict[str, Any] = {}
    for path in _ORDER_LIST_CANDIDATES:
        url = f"{base.rstrip('/')}{path}?limit={int(limit)}"
        try:
            payload = auth.signed_request("GET", url)
        except Exception as exc:
            out[path] = str(exc)[:200]
            continue
        arrays = [k for k, v in payload.items() if isinstance(v, list)]
        out[path] = {
            "ok": True,
            "payload_keys": sorted(payload.keys()),
            "arrays": arrays,
        }
    return {"status": "ok", "routes": out}


def fetch_orders(*, limit: int = 100, order_ids: Sequence[str] | None = None) -> dict[str, Any]:
    """Every recent order, one call. Same contract as `kalshi_orders.fetch_orders`.

    WHY THIS HAD TO EXIST. `execution_ledger._venue_reader` said "Only Kalshi
    has one", and `reconcile_live_orders` defaults to `venue="kalshi"` while
    `execute_portfolio` called it with no arguments. So a Polymarket order
    recorded `submitted` could never be corrected by anything -- and an
    unreconciled order blocks live mode. MEASURED 2026-08-25T16:40:00Z, from a
    single resting Polymarket order:

        BLOCKED_ON_UNRECONCILED count=1 keys=['1984a57ed28e1cd5ccad8b16']
        EXECUTION status=blocked reason=unreconciled_orders scope=kalshi
        EXECUTION status=blocked reason=unreconciled_orders scope=polymarket

    Both venues, not just the one that placed it. The live path was fully down
    and could not recover on its own, because the only thing that clears that
    state is a venue read that did not exist.

    THE ROUTE IS NOT VERIFIED. `POST /v1/orders` creates; a GET on the same
    path is the conventional list and is the default here, overridable with
    `POLYMARKET_US_ORDERS_LIST_PATH` without a deploy -- the same escape hatch
    the create path carries, and for the same reason: Kalshi's create route had
    MOVED and cost an `http_410` to discover. The payload shape is REPORTED on
    the first read rather than assumed, which is what corrected ten wrong field
    names on `kalshi_client`'s first live run.

    A FAILED READ IS AN ERROR, NEVER AN EMPTY LIST. An empty `orders` on a
    failed read would say "the venue holds nothing", and `reconcile_live_orders`
    would take that as licence to write off a live position.
    """
    from syndicate.features.shared.polymarket_us_auth import signed_request

    # PER-ORDER IS THE DOCUMENTED READ, and it is tried first when the caller
    # knows which orders it cares about. `GET /v1/order/{orderId}` is what this
    # venue publishes; there is no documented list route, which is what the
    # `code: 12` UNIMPLEMENTED on `GET /v1/orders` was telling us.
    if order_ids:
        wanted = [str(i).strip() for i in order_ids if str(i or "").strip()]
        rows: list[dict[str, Any]] = []
        errors: list[str] = []
        for order_id in wanted:
            try:
                payload = signed_request("GET", _order_url(order_id))
            except Exception as exc:
                errors.append(f"{order_id}: {type(exc).__name__}: {exc}"[:200])
                continue
            if not isinstance(payload, Mapping):
                errors.append(f"{order_id}: unexpected_shape:{type(payload).__name__}")
                continue
            row = payload.get("order") if isinstance(payload.get("order"), Mapping) else payload
            rows.append(dict(row))
        # EVERY ID FAILING IS A READ FAILURE, not an empty book. One id failing
        # is that order not being found, which reconciliation already treats as
        # "change nothing". Collapsing the first case into the second is how a
        # live position gets written off on a bad credential.
        if wanted and not rows:
            print(
                f"[polymarket_us_orders] ORDERS_READ_ALL_FAILED n={len(wanted)}"
                f" errors={errors[:3]}",
                flush=True,
            )
            return {"status": "error", "reason": f"all_order_reads_failed: {errors[:2]}"}
        if rows:
            print(
                f"[polymarket_us_orders] ORDERS_READ n={len(rows)} mode=per_order"
                f" asked={len(wanted)} keys={sorted(rows[0].keys())}"
                f" states={sorted({str(r.get('state') or '') for r in rows})}"
                f" errors={errors[:2]}",
                flush=True,
            )
        return {"status": "ok", "orders": rows, "count": len(rows), "errors": errors}

    try:
        payload = signed_request("GET", _orders_list_url(limit))
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        # UNIMPLEMENTED MEANS ASK, NOT GUESS. MEASURED 2026-08-25T16:53:54Z:
        #
        #   http_501 https://api.polymarket.us/v1/orders?limit=100
        #   {"code":12,"message":"The server was unable to process your request."}
        #
        # gRPC code 12 is UNIMPLEMENTED -- POST to that exact path creates an
        # order, so the path is real and simply has no GET handler. Not a 401,
        # which also clears the query-string question `signed_path` predicted
        # ("a 401 on every GET that carries a filter"): the signing is fine.
        #
        # Picking a second route by reasoning about what it ought to be called
        # is the same mistake as picking the first. So on an unimplemented
        # route the candidates are PROBED, read-only, and the answer is logged
        # -- the route can then be set via POLYMARKET_US_ORDERS_LIST_PATH with
        # no build, which is why that override exists.
        if "http_501" in reason or "http_404" in reason or "http_405" in reason:
            try:
                probed = probe_order_list_routes()
            except Exception as probe_exc:  # never let a probe break a reader
                probed = {"status": "error", "reason": f"{type(probe_exc).__name__}"}
            print(
                f"[polymarket_us_orders] ORDER_LIST_ROUTE_PROBE {probed}",
                flush=True,
            )
        return {"status": "error", "reason": reason}
    if not isinstance(payload, Mapping):
        return {"status": "error", "reason": f"unexpected_shape:{type(payload).__name__}"}

    raw = None
    container = None
    for key in ("orders", "data", "results", "items"):
        if isinstance(payload.get(key), list):
            raw = payload[key]
            container = key
            break
    if raw is None:
        # NAMED, and the keys reported. "No array we recognise" is a different
        # fact from "no orders", and only one of them is a bug in this file.
        print(
            f"[polymarket_us_orders] ORDERS_READ_NO_ARRAY keys={sorted(payload.keys())}",
            flush=True,
        )
        return {"status": "error", "reason": "no_orders_array"}

    orders = [dict(o) for o in raw if isinstance(o, Mapping)]
    if orders:
        # KEYS AND STATUSES ONLY. An order carries no credential, but it does
        # carry our own positions, so the log gets the shape and the status
        # vocabulary -- the two things needed to map this venue -- not values.
        print(
            f"[polymarket_us_orders] ORDERS_READ n={len(orders)} container={container}"
            f" keys={sorted(orders[0].keys())}"
            f" states={sorted({str(o.get('state') or o.get('status') or '') for o in orders})}",
            flush=True,
        )
    return {"status": "ok", "orders": orders, "count": len(orders)}


def venue_order_view(order: Mapping[str, Any]) -> dict[str, Any]:
    """One Polymarket order, reduced to the facts the ledger needs.

    `state` is our vocabulary: `filled`, `resting`, `dead`, `unknown`. UNKNOWN
    IS A REAL ANSWER -- a status this venue has never shown us must leave the
    row untouched rather than being collapsed into "traded" or "didn't".

    A PARTIAL FILL THAT WAS THEN CANCELLED IS A FILL, so the filled size is
    read FIRST and outranks the status. Same rule as `kalshi_orders`, and for
    the same reason: reading them the other way round reconciles a real
    position away to zero.
    """
    # `state`, NOT `status`. MEASURED 2026-08-25T17:05:58Z on the first real
    # per-order read, which is exactly what the shape report exists to catch:
    #
    #   ORDERS_READ n=1 mode=per_order asked=1 statuses=['']
    #     keys=['action','avgPx','cashOrderQty',...,'cumQuantity','id',
    #           'insertTime','leavesQuantity','marketSlug','outcomeSide',
    #           'price','quantity','side','state','tif','type']
    #
    # There is no `status` key at all, so the view read None, mapped it to
    # `unknown`, and left the row untouched -- correct behaviour on an unknown
    # status, and the order stayed blocking. Same class as `kalshi_client`'s
    # first live run correcting 10 of 17 field names.
    #
    # `status` is kept as a fallback rather than replaced: it costs nothing and
    # a venue that adds the field later should not need another deploy.
    raw_status = str(order.get("state") or order.get("status") or "").strip().lower()
    # The venue prefixes its enums (`ORDER_STATE_CANCELED`), so the prefix is
    # STRIPPED and the remainder matched whole.
    #
    # NOT a split on the last underscore, which was the first attempt and is
    # too loose: `ORDER_STATUS_SOMETHING_NEW` tails to `new`, a resting status,
    # so a status this venue has never shown us would be confidently read as
    # resting. An unmapped status must reach `unknown` -- that is the value
    # that makes reconciliation leave the row alone.
    tail = raw_status
    for prefix in ("order_state_", "order_status_", "state_", "status_"):
        if tail.startswith(prefix):
            tail = tail[len(prefix):]
            break

    # `cumQuantity` is the venue's cumulative filled size, from the same
    # measured key list. `leavesQuantity` is the unfilled remainder -- NOT read
    # as a fill, and named here so a future reader does not mistake it for one.
    filled = None
    for field in ("cumQuantity", "filledQuantity", "filled_quantity", "filledSize", "matchedQuantity"):
        value = order.get(field)
        if value in (None, ""):
            continue
        try:
            filled = float(value)
        except (TypeError, ValueError):
            filled = None
        else:
            break

    if filled:
        state = "filled"
    elif raw_status in _VENUE_FILLED_STATUSES or tail in _VENUE_FILLED_STATUSES:
        state = "filled"
    elif raw_status in _VENUE_RESTING_STATUSES or tail in _VENUE_RESTING_STATUSES:
        state = "resting"
    elif raw_status in _VENUE_DEAD_STATUSES or tail in _VENUE_DEAD_STATUSES:
        state = "dead"
    else:
        state = "unknown"

    price = None
    raw_price = None
    # `avgPx` is the venue's own average fill price, from the measured keys.
    for field in ("avgPx", "averageFillPrice", "average_fill_price", "avgPrice", "fillPrice"):
        raw_price = order.get(field)
        if isinstance(raw_price, Mapping):
            raw_price = raw_price.get("value")
        if raw_price in (None, ""):
            continue
        try:
            price = round(float(raw_price), 4)
        except (TypeError, ValueError):
            price = None
        else:
            break

    # --------------------------------------------------------------------
    # `avgPx` IS QUOTED ON THE YES SIDE. A NO ORDER'S FILL IS ITS COMPLEMENT.
    # --------------------------------------------------------------------
    #
    # Taking it at face value recorded the OTHER SIDE'S price on every `under`,
    # and it halted all trading on both venues on 2026-08-26T00:23:37Z:
    #
    #   RECONCILE_COUNT_IMPLAUSIBLE key=939fb90b24300f32c760b7bb
    #     venue_count=2.39 requested=2.3920000000000003
    #   EXECUTION status=blocked reason=unreconciled_orders  (x2 venues)
    #
    # `under 6.5 CLE@LAA`, +130, $1.04 -> 2.392 contracts, filled 2.39. At the
    # true NO price 0.435 that is $1.04, inside the $1.30 ceiling. At the YES
    # price 0.565 it is $1.35 -- over by 3.9%, and refused. The message printed
    # the CONTRACT pair, which looks fine, while the DOLLAR branch was what
    # actually refused.
    #
    # CONFIRMED FROM FOUR FILLS, by a property that needs no venue access: a
    # BUY cannot fill above its own limit.
    #
    #   side   requested   venue avgPx   1 - avgPx
    #   over      0.4405        0.40        0.60     direct
    #   under     0.4545        0.55        0.45     COMPLEMENT
    #   under     0.4902        0.51        0.49     COMPLEMENT
    #   over      0.5192        0.52        0.48     direct
    #
    # 0.55 against a 0.4545 limit is impossible; 1 - 0.55 = 0.45 is exact.
    #
    # THE SIDE IS READ FROM THE VENUE'S OWN ROW, never from our ledger. The
    # ledger says what we MEANT to buy; only the venue says what it filled, and
    # reconciliation exists precisely because those can differ.
    outcome_side = str(
        order.get("outcomeSide") or order.get("outcome_side") or order.get("side") or ""
    ).strip().upper()
    is_no = outcome_side.endswith("NO")
    is_yes = outcome_side.endswith("YES")

    if price is not None and 0.0 < price < 1.0 and is_no:
        price = round(1.0 - price, 4)
    elif price is not None and not (is_yes or is_no):
        # AN UNREADABLE SIDE IS A REFUSAL, NOT A COIN FLIP. Complementing a YES
        # price inverts a correct number; leaving a NO price inverts it the
        # other way. Both are wrong and neither is detectable downstream, so
        # the price is withheld and reconciliation falls back to the price we
        # asked for -- a known number rather than a guessed one.
        print(
            f"[polymarket_us_orders] FILL_PRICE_SIDE_UNREADABLE"
            f" order={order.get('id') or order.get('orderId')}"
            f" outcome_side={outcome_side!r} avgPx={raw_price!r}"
            " -- price withheld rather than guessed",
            flush=True,
        )
        price = None

    # THE RAW FIELD, LOGGED. This defect was diagnosed from a screenshot and
    # arithmetic because no log line carried `avgPx`, so the one input that
    # would have settled it in seconds was the one nobody could see.
    if raw_price not in (None, ""):
        print(
            f"[polymarket_us_orders] FILL_PRICE order={order.get('id') or order.get('orderId')}"
            f" outcome_side={outcome_side!r} avgPx={raw_price!r} recorded={price!r}",
            flush=True,
        )

    return {
        "state": state,
        "venue_status": raw_status or None,
        "filled_count": filled,
        "fill_price": price,
        "fill_cost_dollars": None,
        "fees_dollars": None,
        "order_id": order.get("id") or order.get("orderId"),
        "client_order_id": order.get("clientOrderId") or order.get("client_order_id"),
        "ticker": order.get("marketSlug") or order.get("market_slug"),
    }
