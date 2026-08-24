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
STILL UNCONFIRMED, AND `submit_order` IS WRITTEN AROUND THAT
--------------------------------------------------------------------------

- The cancel endpoint's HTTP method (path confirmed: `{base}/emm/orders/
  {orderId}`; DELETE assumed, not read).
- **The response shape of a successful order.** Only the 201 status code and
  "Order placed successfully" were documented -- no field names for the
  created order/wager object. The docs' OWN words make this the correct
  thing to be cautious about: "A successful response indicates that the
  order was placed in the QUEUE, but does not guarantee that it will be
  filled or placed on the order book. To reliably ensure an order has been
  executed, consume messages from the matching tape." **A 201 is therefore
  NEVER read as a fill here** -- `submit_order` reports every accepted order
  as `submitted` (the write-ahead state), the same discipline
  `kalshi_orders.submit_order`'s header describes after its own
  `filled`-by-default bug booked a position that was actually resting.
  Reconciliation (reading the matching tape / `emm/fills/all`) is a SEPARATE,
  not-yet-written concern.
- The response shape of `emm/fills/all` / `emm/orders/all` /
  `emm/transactions` (endpoint names, rate limits AND their tiered burst/
  sustained headers confirmed; field names not). `venue_order_view` -- the
  function that would map a Novig order onto this repo's `filled`/`resting`/
  `dead`/`unknown` vocabulary the way `kalshi_orders.venue_order_view` does
  -- is DELIBERATELY NOT WRITTEN here for exactly this reason.

--------------------------------------------------------------------------
`submit_order` REPORTS THE RAW RESPONSE SHAPE -- IT DOES NOT PARSE IT
--------------------------------------------------------------------------

Same discipline `kalshi_client.probe()` and `polymarket_client.probe()` use,
applied to a WRITE call rather than a read for the first time in this lane.
On a 2xx, the decoded body's top-level keys are captured
(`response_keys`) and the WHOLE decoded body is returned
(`raw_response`) rather than picked apart -- because picking specific
fields out of an unconfirmed shape is exactly how Kalshi's build defaulted
an unrecognised status to `filled`. The first real submit is the
verification step this repo's own culture requires before trusting more of
the shape: read `raw_response`'s keys, update `venue_order_view` from what
actually came back, THEN parse it.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

__all__ = [
    "cash_units_for_stake",
    "order_body",
    "backoff_seconds_from_headers",
    "submit_order",
    "novig_submitter",
    "OrderBuildError",
    "NovigOrderError",
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


class NovigOrderError(RuntimeError):
    """A submit call that reached (or tried to reach) the venue and failed.

    Distinct from `OrderBuildError`: this means `venue_contacted` is
    ambiguous or true, so `place_order` records it as `failed` and KEEPS the
    record for reconciliation -- the request may still have landed even
    though the response was lost or malformed. `OrderBuildError` means we
    never sent anything; this means we can no longer be sure.
    """


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


def _order_place_url() -> str:
    from syndicate.features.shared.novig_client import _API_BASE

    override = (os.environ.get("NOVIG_API_BASE") or "").strip()
    base = override or _API_BASE
    return f"{base.rstrip('/')}{_ORDER_PLACE_PATH}"


def submit_order(request: Any, *, price: float, currency: str, timeout: float = 10.0) -> dict[str, Any]:
    """Send ONE order. Returns the shape `place_order` expects from an
    adapter: `{"status": ..., "venue_order_id": ..., "fill_price": ...,
    "fill_stake_dollars": ..., "contracts": ..., "requested_contracts": ...}`
    -- same keys `kalshi_orders.submit_order` returns, so `place_order` does
    not need to know which venue it is talking to.

    `timeout=10.0`, not the module's usual longer default: the documented
    server-side timeout is 5 SECONDS, and a client timeout shorter than that
    would report a submit as failed while the venue was still working on
    accepting it -- ambiguous in exactly the direction `NovigOrderError`
    exists to keep out of the ledger as a false REJECTED. 10s gives the
    server's own 5s room to actually respond before this gives up.

    NEVER RETURNS `status: "filled"`. The documented contract itself says a
    201 means "placed in the queue," not executed -- see module header. Every
    successful submit here is `"submitted"`, exactly the write-ahead state
    `kalshi_orders.submit_order`'s own docstring names as the correct
    default for "the venue has it, the outcome is not known here." Deciding
    fills is reconciliation's job, and reconciliation does not exist yet
    (see `venue_order_view`'s absence, module header).

    Raises `NovigOrderError` on anything that reached the venue and did not
    return a clean 2xx -- `place_order` marks those `failed` and KEEPS the
    record, because a raised submit may still have landed.
    """
    from syndicate.features.shared.novig_client import NovigError, _fetch_token, load_credentials

    creds = load_credentials()
    if creds.get("status") != "ok":
        # Unlike a network failure, a missing credential means NOTHING was
        # sent -- OrderBuildError, not NovigOrderError, so this is recorded
        # REJECTED rather than FAILED-and-retried.
        raise OrderBuildError(f"no_credential: {creds.get('reason')}")
    try:
        token = _fetch_token(creds)
    except NovigError as exc:
        raise OrderBuildError(f"no_credential: token_fetch_failed: {exc}") from exc

    body = order_body(request, price=price, currency=currency)
    url = _order_place_url()

    # THE REQUEST, BEFORE THE RESPONSE -- and never the token. If Novig
    # rejects the body, this line is what tells us which field it disliked;
    # if the process dies before a response arrives, this is the only record
    # that anything was attempted. Same reasoning `kalshi_orders.submit_order`
    # gives for printing before sending.
    print(
        f"[novig_orders] SUBMIT url={url} outcomeId={body['outcomeId']}"
        f" price={body['price']} qty={body['qty']} currency={body['currency']}"
        f" tif={body['tif']}",
        flush=True,
    )

    payload = json.dumps(body).encode("utf-8")
    http_request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(http_request, timeout=timeout) as response:
            raw_body = response.read()
            status_code = response.status
            response_headers = response.headers
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8")[:400]
        except Exception:
            detail = "<unreadable>"
        if exc.code == 429:
            backoff = backoff_seconds_from_headers(exc.headers)
            raise NovigOrderError(f"http_429 backoff_seconds={backoff}: {detail}") from exc
        raise NovigOrderError(f"http_{exc.code}: {detail}") from exc
    except Exception as exc:
        raise NovigOrderError(f"{type(exc).__name__}: {exc}") from exc

    try:
        decoded = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except (ValueError, UnicodeDecodeError) as exc:
        raise NovigOrderError(f"undecodable_response: {exc}") from exc

    # THE SHAPE, ONCE -- reported, not parsed. Same role `kalshi_orders`'
    # `ORDERS_READ` log line played the first time it read a real order back:
    # this is the line that turns "guessed at the response" into "read it".
    response_keys = sorted(decoded.keys()) if isinstance(decoded, dict) else None
    print(
        f"[novig_orders] SUBMIT_RESPONSE http_status={status_code}"
        f" response_keys={response_keys}",
        flush=True,
    )

    return {
        # NEVER "filled" -- see docstring.
        "status": "submitted",
        "http_status": status_code,
        "venue_order_id": None,  # UNKNOWN which key holds this; see raw_response.
        "fill_price": None,
        "fill_stake_dollars": None,
        "contracts": 0,
        "requested_contracts": body["qty"],
        "raw_response": decoded,
        "response_keys": response_keys,
        "rate_limit_remaining": (
            response_headers.get("X-RateLimit-Remaining") if response_headers else None
        ),
    }


def novig_submitter(price_for, *, currency: str):
    """An adapter bound to a price resolver, matching `kalshi_submitter`'s
    shape for `place_order(submit=...)`.

    `currency` is bound at adapter-construction time, not per-request --
    the caller (wiring `_venue_submitter` in `pipeline/execute_portfolio.py`,
    not yet claimed by this lane) decides once which denomination this
    submitter trades in, rather than trusting it to be threaded correctly
    through every individual order.
    """

    def _submit(request):
        price = price_for(request)
        if price is None:
            raise OrderBuildError(f"no_live_price: {getattr(request, 'venue_ticker', None)}")
        return submit_order(request, price=float(price), currency=currency)

    return _submit
