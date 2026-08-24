"""Turn a committed position into a Novig order body.

The venue adapter this repo's `execution_ledger.place_order` would call in
live mode, matching `kalshi_orders.py`'s shape exactly -- everything above it
(the plan, the caps, the kill switch, the write-ahead record) is
venue-agnostic per `.syndicate/scope_2026-08-24_novig_order_automation.md`
§1; this is the one file that knows Novig's own order contract.

--------------------------------------------------------------------------
THE CONTRACT IS REAL DOCUMENTATION, NOT RESEARCH -- FOR ONCE
--------------------------------------------------------------------------

Every other module in this lane had to write its first draft from
WebSearch/WebFetch snippets, because the agent proxy 403s CONNECT to every
venue host. `POST /emm/orders/place`'s request body below was supplied
directly (real `docs.novig.com` page content, 2026-08-24) -- field names,
types, and one worked `curl` example. `order_body()` is still pure and still
unit-tested the way `kalshi_orders.order_body_v2` is, because a documented
contract can still be misread, but the STARTING confidence here is higher
than anywhere else this lane has built from.

--------------------------------------------------------------------------
`qty` IS MINIMAL CURRENCY UNITS. IT IS NOT A CONTRACT COUNT AND NOT DOLLARS.
--------------------------------------------------------------------------

Kalshi buys N contracts at a price, floored from a dollar stake
(`kalshi_orders.contracts_for_stake`) -- the count DEPENDS on the price.
Novig's `qty` is a currency amount directly: for `currency="CASH"`, 1 unit =
$0.01, so a $5.00 stake is `qty=500`, independent of `price`. There is no
floor-to-a-whole-unit step the way Kalshi has to floor to a whole contract;
`cash_units_for_stake` rounds to the nearest cent instead, because there is
no larger indivisible unit here to floor toward.

--------------------------------------------------------------------------
"CASH" vs "COIN" -- ONE IS REAL MONEY, THIS MODULE REFUSES TO GUESS WHICH
--------------------------------------------------------------------------

The order body requires a `currency` field, `"CASH"` or `"COIN"`. Nothing
read so far says whether `"COIN"` is play money, a promotional balance, or
something else entirely -- only that it is a SEPARATE denomination from
`"CASH"`. `order_body()` therefore takes `currency` as a REQUIRED, explicit
argument with no default. A default of `"CASH"` would silently risk real
money on a wrong assumption; a default of `"COIN"` would silently place
paper-equivalent orders on the wrong book. Neither default is safe, so there
is not one.

--------------------------------------------------------------------------
UNRESOLVED: DOES `qty` MEAN RISKED, OR TO WIN?
--------------------------------------------------------------------------

Not stated in anything read so far. This module assumes RISKED (the stake
committed, mirroring how Kalshi's `count` -> `count * price` is the amount
risked) because that is the conventional reading on a peer-to-peer exchange,
but it is an ASSUMPTION carried into `cash_units_for_stake`, not a confirmed
fact. `probe_auth`/a live order confirmation is what would settle it, and
until then this stays flagged rather than quietly trusted.

--------------------------------------------------------------------------
THE RATE LIMIT HEADERS ARE MILLISECONDS, NOT SECONDS
--------------------------------------------------------------------------

See `novig_client.py`'s `_RATE_LIMIT_HEADERS_ARE_MILLISECONDS` and its
neighbouring comment for the confirmed numbers. `backoff_seconds_from_headers`
below exists so that division happens in exactly ONE place, tested, rather
than at every call site that might otherwise assume the HTTP-typical seconds
convention -- the same class of bug as Kalshi's 100x price error.

--------------------------------------------------------------------------
STILL UNCONFIRMED
--------------------------------------------------------------------------

- The cancel endpoint's HTTP method (path confirmed: `{base}/emm/orders/
  {orderId}`; DELETE assumed, not read).
- The response shape of a successful order (only the 201 status code and
  "Order placed successfully" were documented -- no field names for the
  created order/wager object).
- The response shape of `emm/fills/all` / `emm/orders/all` /
  `emm/transactions` (endpoint names and rate limits confirmed; field names
  not). `venue_order_view` -- the function that would map a Novig order onto
  this repo's `filled`/`resting`/`dead`/`unknown` vocabulary, the way
  `kalshi_orders.venue_order_view` does -- is DELIBERATELY NOT WRITTEN here
  for exactly this reason: writing it now would mean guessing field names
  Kalshi's own build got wrong on its first three attempts, on a contract
  even less documented than Kalshi's was.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

__all__ = [
    "cash_units_for_stake",
    "order_body",
    "backoff_seconds_from_headers",
    "novig_submitter",
    "OrderBuildError",
]

# Confirmed from real docs.novig.com content, 2026-08-24. See module header.
_ORDER_PLACE_PATH = "/emm/orders/place"
_VALID_CURRENCIES = frozenset({"CASH", "COIN"})
_VALID_TIF = frozenset({"GTC", "GTT", "IOC", "FOK"})
_DEFAULT_TIF = "GTC"
_MAX_FLAGS_LENGTH = 8


class OrderBuildError(ValueError):
    """The request cannot become a valid order. Raised BEFORE anything is sent.

    `venue_contacted = False`, same contract `kalshi_orders.OrderBuildError`
    uses -- `place_order` reads this to record a build failure as REJECTED
    rather than charging it against the live daily budget as though it might
    have reached the venue.
    """

    venue_contacted = False


def cash_units_for_stake(stake_dollars: float, *, currency: str = "CASH") -> int:
    """A dollar stake -> Novig's `qty` (minimal currency units).

    For `currency="CASH"`: 1 unit = $0.01, ROUNDED (not floored) to the
    nearest cent -- unlike Kalshi's contract count, there is no larger
    indivisible unit to floor toward, so rounding is the honest operation,
    not a safety compromise.

    `currency="COIN"` is refused here rather than silently converted: 1 Coin
    is a different, non-dollar-denominated unit, and this function's whole
    job is a DOLLAR conversion. A caller with a Coin-denominated stake needs
    its own path, not this one repurposed.
    """
    if currency != "CASH":
        raise OrderBuildError(f"cash_units_for_stake_is_CASH_only: got currency={currency!r}")
    if stake_dollars <= 0:
        raise OrderBuildError(f"non_positive_stake: {stake_dollars}")
    # Decimal, parsed from the STRING representation, not `stake_dollars *
    # 100.0` directly -- binary float multiplication turns an innocent
    # $12.345 into 1234.4999999999998, which rounds to 1234 instead of 1235.
    # Money math on a raw float is exactly this failure mode; parsing via
    # `str()` sidesteps it because it reads the decimal digits as typed.
    cents = (Decimal(str(stake_dollars)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    qty = int(cents)
    if qty < 1:
        raise OrderBuildError(f"stake_below_one_unit: ${stake_dollars:.4f}")
    return qty


def order_body(
    request: Any,
    *,
    price: float | None = None,
    currency: str,
    qty: int | None = None,
    tif: str = _DEFAULT_TIF,
    ttl_ms: int | None = None,
    flags: str | None = None,
) -> dict[str, Any]:
    """The JSON body for one `POST /emm/orders/place` call. PURE -- no clock,
    no network, no env. Matches the confirmed request schema exactly:
    `outcomeId`, `price`, `qty`, `currency`, `tif`, optional `ttl`/`flags`.

    `currency` has NO DEFAULT -- see module header on why guessing between
    real money and a separate denomination is not this function's call to
    make. `qty` is computed from `request.requested_stake_dollars` via
    `cash_units_for_stake` when not supplied directly, so a caller can pass
    either a dollar-stake request (the common path) or an exact `qty` (for
    `currency="COIN"`, where `cash_units_for_stake` refuses).
    """
    outcome_id = str(getattr(request, "venue_ticker", "") or "").strip()
    if not outcome_id:
        # Reusing `venue_ticker` deliberately -- `execution_ledger.OrderRequest`
        # already carries one venue-contract-id field, and Novig's outcomeId
        # fills the identical role Kalshi's ticker does. Adding a second,
        # venue-specific id field to the shared dataclass would need a claim
        # on execution_ledger.py this lane does not hold.
        raise OrderBuildError("no_outcome_id")

    if currency not in _VALID_CURRENCIES:
        raise OrderBuildError(f"invalid_currency: {currency!r}")

    resolved_price = price if price is not None else getattr(request, "requested_price", None)
    if resolved_price is None:
        raise OrderBuildError("no_price")
    resolved_price = float(resolved_price)
    if not (0.0 < resolved_price < 1.0):
        raise OrderBuildError(f"price_out_of_range: {resolved_price}")
    # "up to 3 decimal places", per the documented contract.
    resolved_price = round(resolved_price, 3)

    if qty is None:
        stake = float(getattr(request, "requested_stake_dollars", 0.0) or 0.0)
        qty = cash_units_for_stake(stake, currency=currency)
    if not isinstance(qty, int) or qty < 1:
        raise OrderBuildError(f"invalid_qty: {qty!r}")

    resolved_tif = str(tif or _DEFAULT_TIF).strip().upper()
    if resolved_tif not in _VALID_TIF:
        raise OrderBuildError(f"invalid_tif: {tif!r}")
    if resolved_tif == "GTT" and not ttl_ms:
        # The contract's own words: "Applicable only under GTT time-in-force"
        # -- read the other direction, GTT without a ttl is an order that
        # never expires despite asking to, which is the wrong failure
        # direction for a time-bounded order.
        raise OrderBuildError("gtt_requires_ttl_ms")

    body: dict[str, Any] = {
        "outcomeId": outcome_id,
        "price": resolved_price,
        "qty": qty,
        "currency": currency,
        "tif": resolved_tif,
    }
    if ttl_ms is not None:
        body["ttl"] = int(ttl_ms)
    if flags is not None:
        flags = str(flags)
        if len(flags) > _MAX_FLAGS_LENGTH:
            raise OrderBuildError(f"flags_too_long: {len(flags)} > {_MAX_FLAGS_LENGTH}")
        body["flags"] = flags
    return body


def backoff_seconds_from_headers(headers: Any) -> float | None:
    """`Retry-After` / `X-RateLimit-Reset`, converted to SECONDS.

    Both are documented as MILLISECONDS on a Novig 429 -- see
    `novig_client._RATE_LIMIT_HEADERS_ARE_MILLISECONDS`. Division happens
    HERE, once, tested, rather than at every call site that might otherwise
    assume the HTTP-typical seconds convention. `headers` is anything with a
    `.get(name)` -- an `http.client.HTTPMessage`, a plain dict, or a mock in
    a test all satisfy this without importing a network stack here.
    """
    for name in ("Retry-After", "X-RateLimit-Reset"):
        raw = headers.get(name) if hasattr(headers, "get") else None
        if raw is None:
            continue
        try:
            millis = float(raw)
        except (TypeError, ValueError):
            continue
        if millis < 0:
            continue
        return millis / 1000.0
    return None


def novig_submitter(price_for, *, currency: str):
    """An adapter bound to a price resolver, matching `kalshi_submitter`'s
    shape for `place_order(submit=...)`.

    `currency` is bound at adapter-construction time, not per-request --
    the caller (wiring `_venue_submitter` in `pipeline/execute_portfolio.py`,
    not yet claimed by this lane) decides once which denomination this
    submitter trades in, rather than trusting it to be threaded correctly
    through every individual order.

    NOT WIRED TO A NETWORK CALL. `submit_order` (the `signed_request`-style
    POST + response handling `kalshi_orders.submit_order` implements) is
    deliberately not written yet -- see module header's "STILL UNCONFIRMED"
    section on why guessing the response shape now would repeat exactly the
    mistake this repo's own Kalshi build corrected three times over.
    """

    def _submit(request):
        price = price_for(request)
        if price is None:
            raise OrderBuildError(f"no_live_price: {getattr(request, 'venue_ticker', None)}")
        body = order_body(request, price=float(price), currency=currency)
        raise NotImplementedError(
            "novig_orders.submit_order is not implemented -- the order body "
            f"({body}) is ready, the network call is not. See module header."
        )

    return _submit
