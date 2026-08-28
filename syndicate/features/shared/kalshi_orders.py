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
    "cancel_order",
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
from syndicate.features.shared.venue_order_states import (
    VENUE_DEAD_STATUSES,
    VENUE_FILLED_STATUSES,
    VENUE_RESTING_STATUSES,
)

# SHARED WITH EVERY OTHER VENUE. These were a private copy until 2026-08-27
# and had drifted from Polymarket's -- `complete` was a fill there and
# `unknown` here, off the same word. See `venue_order_states` for why the
# union is the safe direction and why `unknown` is not a harmless default.
_VENUE_FILLED_STATUSES = VENUE_FILLED_STATUSES

# ...and the two other things a venue status can mean. Split rather than
# lumped into "not filled", because they have opposite consequences: a RESTING
# order may still trade and must stay in the ledger untouched, while a DEAD one
# never will and frees both its budget and its idempotency key.
_VENUE_RESTING_STATUSES = VENUE_RESTING_STATUSES
_VENUE_DEAD_STATUSES = VENUE_DEAD_STATUSES


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


# Board markets whose SIDE names a TEAM rather than a direction. On these the
# contract is chosen by WHICH TICKER, not by yes/no -- see `_side_to_kalshi`.
_TEAM_SIDED_MARKETS = frozenset({"h2h", "h2h_h1", "h2h_h2", "h2h_q1", "h2h_q2",
                                 "h2h_q3", "h2h_q4", "h2h_p1", "h2h_p2", "h2h_p3"})


def _side_to_kalshi(side: Any, market: Any = None, line: Any = None) -> str:
    """Our `over`/`under`/`yes`/`no`/`home`/`away` -> Kalshi's `yes`/`no`.

    Explicit, and it REFUSES an unmapped side. Defaulting to `yes` would turn an
    unrecognised side into a real bet on the opposite outcome -- the single most
    expensive silent default available in this file.

    A MONEYLINE SIDE NAMES A TEAM, AND THE TEAM IS ALREADY IN THE TICKER.
    Confirmed by the user 2026-08-25 from Kalshi's own order URLs -- one market
    PER TEAM, each offering a BUY on both legs:

        KXMLBGAME-26AUG251840BOSMIA-BOS   op_order_side=yes  op_side=BUY
        KXMLBGAME-26AUG251840BOSMIA-MIA   op_order_side=yes  op_side=BUY

    So backing Miami is `BUY YES` on the `-MIA` contract, not a NO or an ask on
    the `-BOS` one. `kalshi_board_join` already keys a match on `board_side` and
    stamps the ticker of the team that side names, so by the time an order is
    built the contract IS our team and the leg is always YES.

    THIS IS SAFE ONLY BECAUSE THE TICKER IS PER-TEAM, which is why it is
    restricted to the moneyline family. Reading `home` as `yes` on a market
    whose ticker did NOT encode our team would buy the opponent -- so a totals
    or spread row still refuses, and `home`/`away` on anything outside
    `_TEAM_SIDED_MARKETS` raises exactly as before.
    """
    raw = str(side or "").strip().lower()
    if raw in {"yes", "over"}:
        return "yes"
    if raw in {"no", "under"}:
        return "no"
    market_key = str(market or "").strip().lower()
    if raw in {"home", "away"} and market_key in _TEAM_SIDED_MARKETS:
        return "yes"
    if raw in {"home", "away"} and market_key.startswith("spreads"):
        return _spread_side_from_line(side, market, line)
    raise OrderBuildError(f"unmappable_side: {side!r} market={market!r}")


def _spread_side_from_line(side: Any, market: Any, line: Any) -> str:
    """A SPREAD'S LEG IS DECIDED BY THE SIGN OF ITS LINE. Nothing else here can.

    A Kalshi spread market states a MARGIN -- "Texas wins by over 1.5 runs" --
    and `kalshi_board_join` pairs it with exactly two board rows, by
    construction:

        the NAMED club at -X   -> YES pays when it covers
        the OTHER club at +X   -> NO pays when it does not

    So `yes` if and only if the row's line is NEGATIVE. The sign IS the leg.

    WHY NOT READ THE TICKER. The ticker names a club, and comparing that club
    to ours needs a tri-code table -- `team_aliases.canonical_team` refuses the
    codes shared across leagues, which is exactly where this would be used. The
    sign needs no table and cannot be ambiguous.

    WHY THIS IS SAFE NOW AND WAS NOT BEFORE. Until the join's sign fix
    (2026-08-26) a `+1.5` row was stamped with the ticker of the club it was
    FADING -- 11 of 11 orders on the live book -- so `yes` on that ticker would
    have bought the opposite bet. `_side_to_kalshi` refusing `home`/`away` was
    the only thing stopping it. The refusal is lifted ONLY because the join now
    guarantees the pairing above, and `test_the_join_and_the_order_builder_agree`
    fails if that guarantee ever stops holding.

    A ZERO OR ABSENT LINE REFUSES. A spread with no number is not a pick'em, it
    is a row we cannot place, and defaulting it either way is a real bet on a
    leg nobody chose.
    """
    try:
        value = float(line)
    except (TypeError, ValueError):
        raise OrderBuildError(
            f"spread_line_missing: {line!r} side={side!r} market={market!r}"
            " -- a spread's leg comes from the sign of its line"
        ) from None
    if value < 0:
        return "yes"
    if value > 0:
        return "no"
    raise OrderBuildError(
        f"spread_line_zero: side={side!r} market={market!r}"
        " -- a zero spread names no leg"
    )


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

    side = _side_to_kalshi(getattr(request, "side", None), getattr(request, "market", None))
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

# `exchange_index` IS A SHARD SELECTOR, NOT A CONSTANT. THIS IS THE BUG.
#
# The sample body carried `"exchange_index": 0` and it was copied as if it were
# part of the contract's fixed furniture, alongside `post_only: false`. The
# field reference the owner supplied 2026-08-26 says otherwise, verbatim:
#
#   exchange_index -- Exchange shard index. If omitted, auto-routes when
#   ticker is provided; otherwise defaults to 0. Use -1 to require
#   auto-routing by ticker.
#
# So sending 0 does not mean "the default"; it PINS the order to shard 0. A
# market that lives on any other shard is not there, and the matching engine
# says so with the only words it has for a ticker it cannot see on the shard it
# was asked about: `market_not_found`.
#
# THAT IS EXACTLY THE SHAPE THAT HAS BEEN MEASURED ALL WEEK, and it is the only
# hypothesis left that survives every reading:
#
#   * GET /markets/<ticker> returns `status=active` with both legs quoted --
#     reads are not sharded, so the market genuinely exists (measured on
#     KXMLBKS, KXMLBOUTS, KXMLBHIT, KXMLBRBI, KXMLBHRR, KXMLBTOTAL).
#   * The POST 404s from the SAME host, 0.5s later (`fetch_base` ==
#     `order_base`, measured 2026-08-26T01:18:47Z) -- so it is not the host.
#   * BOTH sides fail and both sides have filled -- so it is not `bid`/`ask`.
#   * The body is byte-identical in shape to the two KXMLBKS submits that
#     SUCCEEDED on 2026-08-24 -- so it is not a field name or a unit.
#   * Successes and failures are the same market family on the same day, which
#     is what a per-market shard assignment looks like and what a code
#     regression does not.
#
# -1 rather than omitting the key: both auto-route, but -1 REQUIRES routing by
# ticker, so a future body that loses its ticker fails loudly instead of
# quietly landing on shard 0 again. Overridable without a deploy because this
# is the field the venue is most likely to keep moving.
_V2_EXCHANGE_INDEX_AUTO = -1


# `subaccount` IS THE SECOND FIELD COPIED FROM THE SAMPLE AS FURNITURE.
#
# CONFIRMED 2026-08-26: switching `exchange_index` 0 -> -1 changed the venue's
# answer, cleanly and with no exceptions either side of the deploy:
#
#   before 12:55:08Z   http_404 {"code":"market_not_found"}
#   after  12:55:08Z   http_400 {"code":"user_not_found: <account uuid>"}
#
# So `-1` DID route by ticker and the matching engine DID find the market. It
# then failed on the USER instead. The order got one layer deeper, which is
# what a correct fix to a layered failure looks like.
#
# `user_not_found` naming a UUID means the shard that owns the market has no
# record of the account the request was made for. Two things can cause that,
# and only one is ours to fix. The venue's own field reference:
#
#   subaccount -- The subaccount number to use for this order. 0 is the
#   primary subaccount. Subaccount-restricted API keys must OMIT this field
#   or pass their locked subaccount.
#
# We send a literal 0 on every order, exactly as `exchange_index` was sent.
# If this key is subaccount-restricted, 0 is not "the default" any more than
# shard 0 was -- it names a subaccount that may not exist for this key on this
# shard, which is precisely what the error says.
#
# DISPROVEN 2026-08-26, AND REVERTED TO 0. Omitting the field was deployed at
# 14:29:59Z; a real prop order reached the venue at 15:04:08Z and came back with
# the identical `user_not_found`. The field was never the problem.
#
# Back to `0` rather than left omitted, because `0` is the configuration under
# which EVERY KNOWN FILL HAPPENED and omitting it is unproven in both
# directions. On a money path, "changed nothing for the bug" is not a reason to
# keep a change; last-known-good is. `KALSHI_ORDER_SUBACCOUNT=` (empty) omits it
# again with no deploy if that is ever wanted.
_SUBACCOUNT_OMITTED = object()
_SUBACCOUNT_DEFAULT = 0


def _v2_subaccount() -> Any:
    raw = os.environ.get("KALSHI_ORDER_SUBACCOUNT")
    if raw is None:
        return _SUBACCOUNT_DEFAULT
    raw = raw.strip()
    if not raw:
        # Set-but-empty is an explicit request to OMIT. Distinguishable from
        # unset only because this reads the variable before stripping it.
        return _SUBACCOUNT_OMITTED
    try:
        return int(raw)
    except ValueError:
        return _SUBACCOUNT_DEFAULT


def _v2_exchange_index() -> int:
    raw = (os.environ.get("KALSHI_ORDER_EXCHANGE_INDEX") or "").strip()
    if not raw:
        return _V2_EXCHANGE_INDEX_AUTO
    try:
        return int(raw)
    except ValueError:
        return _V2_EXCHANGE_INDEX_AUTO


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

    # THIS CLAIM IS CONTRADICTED BY THE VENUE'S OWN UI AND IS UNDER REVIEW.
    #
    # The paragraph below said an UNDER "is not `side: no` -- there is no such
    # value", and that everything is quoted from the YES leg so an under must
    # be an ASK at the complement. The user supplied two Kalshi order URLs for
    # one market on 2026-08-25, and BOTH ARE BUYS:
    #
    #   ...KXMLBGAME-26AUG251840BOSMIA-BOS&op_order_side=yes&op_side=BUY
    #   ...KXMLBGAME-26AUG251840BOSMIA-BOS&op_order_side=no &op_side=BUY
    #
    # So buying NO is a first-class operation on this venue, not a synonym for
    # selling YES. And the order results line up with that exactly: every
    # Kalshi order that FAILED on 2026-08-25 was an under sent as `ask`
    # (`market_not_found`, twice), while the one that FILLED was an over sent
    # as `bid`.
    #
    # NOT CHANGED YET, DELIBERATELY. Those URLs carry the UI's parameters
    # (`op_order_side`, `op_side`), not the API body's field names, and the
    # only body contract this repo has ever been given is the `"side": "bid"`
    # sample from 2026-08-24. Renaming a field from a URL query string is the
    # same guess that earned `_DEFAULT_ORDER_PATH` an http_410. What closes it
    # is one NO-side body sample; `SUBMIT_FAILED_MARKET` collects the market's
    # own shape in the meantime.
    #
    # The original claim, kept verbatim so the correction is legible:
    #
    #   "bid means buy YES, ask means sell YES. (Selling YES is economically
    #    equivalent to buying NO at 1 - price, but this endpoint quotes
    #    everything from the YES side.)"
    contract_side = _side_to_kalshi(
        getattr(request, "side", None),
        getattr(request, "market", None),
        # THE SIGNED BOARD LINE. A spread's leg is not expressible without it --
        # see `_spread_side_from_line`.
        getattr(request, "line", None),
    )
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

    body: dict[str, Any] = {
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
        "exchange_index": _v2_exchange_index(),
    }
    subaccount = _v2_subaccount()
    if subaccount is not _SUBACCOUNT_OMITTED:
        body["subaccount"] = subaccount
    return body


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


def _base_of(url: str) -> str:
    """The HOST of an order URL, for a log line that has to be scannable."""
    text = str(url or "")
    parts = text.split("/", 3)
    return parts[2] if len(parts) > 2 else text


def _is_market_not_found(exc: BaseException) -> bool:
    """Kalshi's 404 for a ticker the ORDER route will not resolve.

    Matched on the error CODE in the body, not on the 404 alone: a 404 from a
    mistyped path is a different failure and must not trigger a retry that
    would just repeat it against a second host.
    """
    return "market_not_found" in str(exc)


def _retry_url_for(url: str, fetch_base: str) -> str:
    """The same order path on the host the GET resolved -- or "" for no retry.

    Empty whenever the two agree, which is the whole safety property: if the
    read and the write already talk to the same host, this is measurement only
    and nothing about the money path changes.
    """
    base = str(fetch_base or "").strip().rstrip("/")
    if not base or not url:
        return ""
    if url.startswith(base + "/"):
        return ""
    from syndicate.features.shared.kalshi_client import _BASE_URLS

    if base not in _BASE_URLS:
        # A host Kalshi never served us from is a host we do not send orders
        # to. Inventing one is what earned this file an http_410.
        return ""
    path = (os.environ.get("KALSHI_ORDER_PATH") or _DEFAULT_ORDER_PATH).strip()
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base}{path}"


# Shards this account has ever actually filled on. MEASURED 2026-08-26, n=9,
# a perfect split with no exceptions:
#
#   FILLED shard 0   KXMLBKS-26AUG242145CINSF-CINCBURNS26-7      (MLB, 08-24)
#   FILLED shard 0   KXMLBKS-26AUG241840BOSMIA-MIASALCANTARA22-5 (MLB, 08-24)
#   FILLED shard 0   KXWNBA3PT / KXWNBATOTAL / KXWNBAREB
#   FAILED shard 3   KXMLBERA / KXMLBTOTAL / KXMLBSPREAD / KXMLBKS  (all 08-26)
#
# The two MLB fills on 08-24 were shard 0. **MLB MIGRATED TO SHARD 3**, which is
# why this broke on 08-25 with no deploy of ours in between, and it retires the
# last code-regression hypothesis.
#
# ENV-OVERRIDABLE, and that is the point: the fix is the ACCOUNT HOLDER
# MOVING COLLATERAL onto that shard, not a patch and not a support ticket.
# Kalshi balances are local to an exchange instance and must be
# preallocated. Once shard 3 is funded, `KALSHI_ORDER_KNOWN_SHARDS=0,3`
# makes it legible again with no deploy.
_KNOWN_GOOD_SHARDS = (0,)


def _known_shards() -> tuple[int, ...]:
    raw = (os.environ.get("KALSHI_ORDER_KNOWN_SHARDS") or "").strip()
    if not raw:
        return _KNOWN_GOOD_SHARDS
    out: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            continue
    return tuple(out) or _KNOWN_GOOD_SHARDS


def _classified(exc: BaseException, body: Mapping[str, Any], market_shard: Any) -> BaseException:
    """Give the venue's 400 a name a human can act on. Never masks the cause.

    ------------------------------------------------------------------
    `user_not_found` ON A SHARD MEANS NO COLLATERAL THERE, NOT NO ACCOUNT
    ------------------------------------------------------------------

    Two rungs of a ladder, both errors literally true, neither a bug here:

        exchange_index 0 (pinned) -> market is not on shard 0 -> market_not_found
        exchange_index -1 (auto)  -> routes to shard 3, found -> user_not_found

    CORRECTED 2026-08-26, AND THE FIRST VERSION OF THIS DOCSTRING SENT PEOPLE TO
    THE WRONG PLACE. It said the venue had to "enable this account on that
    shard" and that "no code change fixes it" -- so a reader was pointed at
    Kalshi support for something the account holder can do in about a minute.

    `GET /trade-api/v2/exchange/status` enumerates the shards, and they are
    PRODUCT shards, not separate exchange entities -- all four trading_active:

        0 Default        1 Combos        2 Crypto        3 Tennis & Baseball

    Shard 3 is where BASEBALL lives, which is the whole reason only MLB fails.
    `KXNFLGAME`, `KXNBA` and `KXWNBAPTS` are all index 0.

    Kalshi's sharding doc, verbatim:

        "Subaccount balances are local to a specific exchange instance."
        "Programmatic traders must preallocate collateral on a given exchange
         shard before order placement."

    So `user_not_found` here is consistent with HAVING NO FUNDS ON THAT SHARD,
    not with the account being unknown. **Nothing needs enabling. Money needs
    moving** -- at kalshi.com/account/exchange-indexes, or via the
    intra-account-transfer API, by the account holder.

    THE LESSON, and it is why the whole paragraph is rewritten rather than
    patched: the shard DIAGNOSIS was right and confirmed in production, and a
    REMEDY was attached to it by inference rather than by reading. A confident
    wrong remedy inside a correct diagnosis is worse than no remedy, because it
    inherits the diagnosis's credibility and nobody re-checks it.

    This does not retry, does not fall back, and does not change the request. It
    renames the failure so the ledger row says what to DO. The original
    exception is chained by the caller and nothing is swallowed.

    NO ACCOUNT IDENTIFIER IS COPIED INTO THE MESSAGE. The venue's text carries a
    user UUID; the ledger is rendered on a web page, so the shard and the ticker
    are what travel.
    """
    text = str(exc)
    if "user_not_found" not in text:
        return exc
    shards = _known_shards()
    # UNREAD IS NOT A VALUE, and printing `market_shard=None` beside
    # `known_good_shards=[0]` reads as "we compared and it did not match" when
    # nothing was compared at all. MEASURED 2026-08-26T15:32Z: exactly that,
    # because `exchange_index` was missing from `kalshi_client._MARKET_FIELDS`
    # and the normalizer dropped it. Same defect class as everything else today
    # -- a reading that looks like an answer -- so the two cases are now
    # different strings.
    shard = "UNREAD" if market_shard is None else market_shard
    return OrderBuildError(
        "venue_shard_unfunded:"
        f" market_shard={shard} funded_shards={list(shards)}"
        f" ticker={body.get('ticker')}"
        " -- Kalshi balances are PER-SHARD and must be preallocated before"
        " order placement. This is not a venue permission and not a code fault:"
        " move collateral to that shard at kalshi.com/account/exchange-indexes"
        " (or via the intra-account-transfer API), then add it to"
        " KALSHI_ORDER_KNOWN_SHARDS."
    )


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
        f" tif={body.get('time_in_force')}"
        # THE FIELD UNDER TEST. Printed on the SUBMIT and not only on the
        # failure, because the reading that settles this is a shard other than
        # 0 filling -- and a line that only appears when things break cannot
        # show that.
        f" exchange_index={body.get('exchange_index')}"
        # PRESENT OR ABSENT, on the SUBMIT. `exchange_index` had to be added to
        # this line before its fix could be read at all; this one starts there.
        f" subaccount={body.get('subaccount', '<omitted>')}",
        flush=True,
    )
    try:
        response = signed_request("POST", url, body=body)
    except Exception as exc:
        # THE MARKET'S OWN FIELDS, ON THE FAILURE, and only on the failure.
        #
        # Measured 2026-08-25/26, every real submission this endpoint has taken:
        #
        #   KXWNBAAST-...-4          side=bid  -> FILLED
        #   KXMLBTOTAL-...MINATH-10  side=ask  -> market_not_found
        #   KXMLBTOTAL-...CINSF-8    side=ask  -> market_not_found
        #   KXMLBTOTAL-...CLELAA-7   side=ask  -> market_not_found
        #   KXMLBTOTAL-...TBDET-7    side=BID  -> market_not_found
        #
        # THAT LAST ROW KILLED THE SIDE HYPOTHESIS. An over (`bid`, the exact
        # form that filled for WNBA) fails on KXMLBTOTAL too, so `ask` is not
        # what the venue is objecting to. The probe also cleared the market
        # itself: `market_type=binary status=active mve_collection=None`, with
        # BOTH asks quoted (`yes_ask=0.5700 no_ask=0.4400`). Nothing about the
        # market differs from the one that filled.
        #
        # RESOLVED 2026-08-26: IT WAS `exchange_index`. The paragraphs below
        # are the elimination that got there, kept because each one closed a
        # hypothesis that would otherwise be re-opened. The answer is in
        # `_V2_EXCHANGE_INDEX_AUTO`: a literal 0 pins the order to shard 0, and
        # `market_not_found` is what a matching engine says about a ticker that
        # is not on the shard it was asked about. Everything below correctly
        # ruled out the host, the side, the market shape and the event field --
        # it just never questioned a field copied out of the sample body.
        #
        # THE HOST -- RULED OUT. `_BASE_URLS` is a three-entry FALLBACK
        # CHAIN for reads -- `fetch_market` walks it until one answers and
        # returns which one did -- while `_orders_url()` pins `_BASE_URLS[0]`
        # unconditionally. A market served by base[1] would GET fine and POST
        # 404 to base[0], on either side, which is exactly the shape observed.
        #
        # So the base that answered is printed, and the retry below acts ONLY
        # when it actually differs. If the hypothesis is wrong the two bases
        # are equal, the retry never fires, and this stays pure measurement --
        # which is the point. Inventing a route is how this file earned an
        # http_410 (see `_DEFAULT_ORDER_PATH`); re-sending to a host Kalshi
        # itself just served this ticker from is not inventing one.
        fetch_base = ""
        market_shard: Any = None
        try:
            from syndicate.features.shared.kalshi_client import fetch_market

            probe = fetch_market(str(body.get("ticker") or ""))
            market = (probe.get("market") or {}) if isinstance(probe, dict) else {}
            fetch_base = str(probe.get("base") or "") if isinstance(probe, dict) else ""
            # THE SHARD THIS MARKET LIVES ON. Public field, no credential
            # needed, and the single most load-bearing number in this file.
            market_shard = market.get("exchange_index")
            print(
                "[kalshi_orders] SUBMIT_FAILED_MARKET"
                f" ticker={body.get('ticker')} side={body.get('side')}"
                f" fetch_status={probe.get('status') if isinstance(probe, dict) else None}"
                f" fetch_base={fetch_base or '-'} order_base={_base_of(url)}"
                # THE EVENT THIS MARKET BELONGS TO, and on an endpoint called
                # `/portfolio/events/orders` it is the first thing to check.
                # The user's own market URL 2026-08-25 shows a KXMLBTOTAL
                # market living under a KXMLBGAME event:
                #
                #   /markets/kxmlbgame/.../kxmlbgame-26aug251840tbdet
                #     ?op_market_ticker=KXMLBTOTAL-26AUG251840TBDET-7
                #
                # So the event ticker is NOT the market ticker's own prefix,
                # and our body sends no event field at all.
                # THE TICKER KALSHI ECHOES BACK, against the one we sent.
                # `fetch_market` does `GET /markets/{key}` and accepts any body
                # carrying a `ticker` -- it never checks that the ticker
                # RETURNED is the ticker ASKED FOR. A listing endpoint can
                # resolve an alias or a redirect; an order book cannot. If
                # these two strings differ, that is the whole answer, and it
                # has been one comparison away for four days.
                f" ours={body.get('ticker')!r} venue_ticker={market.get('ticker')!r}"
                f" ticker_echo_matches={str(market.get('ticker') or '') == str(body.get('ticker') or '')}"
                f" event_ticker={market.get('event_ticker')}"
                f" market_type={market.get('market_type')}"
                f" status={market.get('status')}"
                f" mve_collection={market.get('mve_collection_ticker')}"
                f" strike_type={market.get('strike_type')}"
                f" yes_ask={market.get('yes_ask_dollars')}"
                f" no_ask={market.get('no_ask_dollars')}"
                f" can_close_early={market.get('can_close_early')}"
                f" exchange_index={market_shard}",
                flush=True,
            )
            # THE EVENT'S OWN MARKET LIST, and the last question standing.
            #
            # Measured 2026-08-26T01:18:47Z: the GET and the POST went to the
            # SAME host (`fetch_base` == `order_base`), 1.9s apart, and only
            # the POST 404'd. That killed the host hypothesis -- the fourth
            # killed this week, after side, market shape and event field.
            #
            # What has never been checked is whether the ticker the MARKET
            # endpoint answers to is the ticker the ORDER BOOK knows. A
            # listing can resolve an alias; an order book cannot. Every failure
            # so far is a 3-segment KXMLBTOTAL ticker while the one FILL was a
            # 4-segment player prop, so asking the venue to spell its own
            # markets is the cheapest way to see a mismatch that would produce
            # exactly GET-ok/POST-404.
            #
            # Printed as a COMPARISON, not a dump: whether our ticker is in the
            # venue's own list is the entire finding.
            event_ticker = str(market.get("event_ticker") or "")
            if event_ticker:
                from syndicate.features.shared.kalshi_client import fetch_event_markets

                listed = fetch_event_markets(event_ticker)
                tickers = listed.get("tickers") or []
                ours = str(body.get("ticker") or "")
                print(
                    "[kalshi_orders] SUBMIT_FAILED_EVENT_MARKETS"
                    f" event={event_ticker} status={listed.get('status')}"
                    f" count={len(tickers)}"
                    f" ours_listed={ours in tickers}"
                    f" sample={tickers[:6]}"
                    # THE REASON, which this line withheld for a full day.
                    # It printed `status=error count=0` and stopped -- naming a
                    # failure while keeping the one field that says what failed.
                    # That is the exact defect this repo keeps relearning, and
                    # it was in the diagnostic written to break the deadlock.
                    f" reason={str(listed.get('reason') or '')[:400]}",
                    flush=True,
                )
        except Exception as probe_exc:  # noqa: BLE001 -- a diagnostic never masks the real error
            print(
                f"[kalshi_orders] SUBMIT_FAILED_MARKET_PROBE_ERROR"
                f" {type(probe_exc).__name__}: {probe_exc}",
                flush=True,
            )

        # ONE RETRY, on ONE error code, to ONE host -- the one that just served
        # this ticker. Bounded that tightly because it is a money path.
        #
        # Safe to re-send: `market_not_found` is a 404 from the route itself,
        # so nothing was placed, and `client_order_id` carries the idempotency
        # key regardless -- a duplicate is Kalshi's to reject, which is the
        # same protection the first send relies on.
        retry_url = _retry_url_for(url, fetch_base) if _is_market_not_found(exc) else ""
        if retry_url:
            print(
                f"[kalshi_orders] SUBMIT_RETRY_BASE ticker={body.get('ticker')}"
                f" from={_base_of(url)} to={_base_of(retry_url)}",
                flush=True,
            )
            try:
                response = signed_request("POST", retry_url, body=body)
            except Exception as retry_exc:
                print(
                    f"[kalshi_orders] SUBMIT_RETRY_BASE_FAILED"
                    f" ticker={body.get('ticker')} {type(retry_exc).__name__}: {retry_exc}",
                    flush=True,
                )
                raise retry_exc from exc
            else:
                print(
                    f"[kalshi_orders] SUBMIT_RETRY_BASE_OK ticker={body.get('ticker')}"
                    f" base={_base_of(retry_url)}",
                    flush=True,
                )
                return _order_result(request, body, response, price_dollars=price_dollars)
        raise _classified(exc, body, market_shard) from exc
    return _order_result(request, body, response, price_dollars=price_dollars)


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


# HOW MUCH OF THE ACCOUNT ONE READ SEES. Declared, not inferred: the
# reconciler needs to know whether an orphan scan is even possible BEFORE it
# decides whether a zero-candidate pass is worth a venue call.
ORDER_READ_COVERAGE = "book"


def fetch_orders(*, limit: int = 100, order_ids: Any = None) -> dict[str, Any]:
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

    `order_ids` IS ACCEPTED AND IGNORED, deliberately. Kalshi returns the whole
    book in one call, so it needs no hint about which orders matter -- but
    Polymarket publishes no list of settled orders and must read one at a time
    (`GET /v1/order/{orderId}`), so the reader contract carries the ids and each
    venue uses what it needs. Accepting-and-ignoring keeps one call site in
    `reconcile_live_orders` rather than a per-venue branch there.
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
    # THE ENVELOPE, and it is here to answer one open question: this read takes
    # a `limit` and has NO pagination, so if the account ever holds more orders
    # than `limit` the tail is simply invisible. Kalshi's list conventionally
    # carries a cursor, but the field name has never been observed and GUESSING
    # IT IS THE SAME MISTAKE AS GUESSING A ROUTE -- `polymarket_us_orders` paid
    # for that with an `http_501` on a reasoned-about path. So the envelope's
    # keys are reported and one production read settles the name.
    print(
        f"[kalshi_orders] ORDERS_ENVELOPE keys={sorted(payload.keys())}"
        f" n={len(orders)} limit={int(limit)}",
        flush=True,
    )
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
    # COVERAGE, DECLARED BY THE READER. Kalshi lists the WHOLE book and
    # ignores the ids it is handed, so a venue order absent from our ledger is
    # visible here and nowhere else. `reconcile_live_orders` uses this to know
    # whether `not_found=0` means "we agree with the venue" or only "we asked
    # about what we already believed" -- two very different guarantees that
    # were printing the same line.
    # A FULL PAGE IS NOT A WHOLE BOOK, AND MUST NOT SAY IT IS.
    #
    # `coverage` decides whether `reconcile_live_orders` runs an orphan scan and
    # whether `not_found=0` means "we agree with the venue" or only "we asked
    # about what we already believed". Returning `book` unconditionally made a
    # TRUNCATED read claim the stronger guarantee -- an unknown defaulting to
    # the permissive branch, with no reason emitted.
    #
    # `n == limit` cannot distinguish "exactly that many" from "more, cut off",
    # so it degrades to `page` and the orphan scan is skipped rather than run
    # against a partial book. Measured 2026-08-28T01:31Z: n=78 against
    # limit=100, so today this is `book` on the evidence and not by assumption.
    truncated = len(orders) >= int(limit)
    if truncated:
        print(
            f"[kalshi_orders] ORDERS_READ_TRUNCATED n={len(orders)} limit={int(limit)}"
            " -- coverage degraded to page; orphan scan will be skipped",
            flush=True,
        )
    return {
        "status": "ok",
        "orders": orders,
        "coverage": "page" if truncated else "book",
    }


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


def _order_cancel_url(order_id: str) -> str:
    """DELETE hangs off the WRITE path, not the read path.

        POST   /portfolio/events/orders          -- create
        DELETE /portfolio/events/orders/{id}     -- cancel
        GET    /portfolio/orders                 -- list
        GET    /portfolio/orders/{id}            -- read one

    The asymmetry is real and is the whole reason this is derived from
    `_DEFAULT_ORDER_PATH` rather than from the read path: writes live under
    `events/orders`, reads under `orders`. Guessing that DELETE followed the
    reads would have produced the same class of failure as the create-route
    410, and the shape of it -- a cancel that silently 404s while the order
    keeps resting -- is worse, because nothing about the order changes to say
    so.
    """
    path = (os.environ.get("KALSHI_ORDER_CANCEL_PATH") or _DEFAULT_ORDER_PATH).strip()
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{_read_base().rstrip('/')}{path}/{order_id}"


def cancel_order(order_id: Any) -> dict[str, Any]:
    """Pull one resting order off the book.

        DELETE /trade-api/v2/portfolio/events/orders/{order_id}

    Note the path: the WRITE route, alongside create -- not the `/portfolio/
    orders` the reads use. The failure is still returned by NAME with the HTTP
    code intact rather than raised, so one production line says if this moves
    too. `KALSHI_ORDER_CANCEL_PATH` overrides it without a code change.

    A CANCEL THAT FAILS MUST LEAVE THE ORDER ALONE. It is still resting, it can
    still fill, and recording it as dead would free an idempotency key that the
    venue still holds -- which is how one bet becomes two.
    """
    from syndicate.features.shared.kalshi_auth import signed_request

    key = str(order_id or "").strip()
    if not key:
        return {"status": "error", "reason": "no_order_id"}
    url = _order_cancel_url(key)
    print(f"[kalshi_orders] CANCEL url={url}", flush=True)
    try:
        payload = signed_request("DELETE", url)
    except Exception as exc:
        return {"status": "error", "reason": f"{type(exc).__name__}: {exc}"}
    order = _unwrap_order(payload)
    return {"status": "ok", "order": order or {}}


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
    `_fp` IS PLAIN CONTRACTS. SETTLED BY MEASUREMENT 2026-08-28T01:25:01Z
    ------------------------------------------------------------------

    This docstring used to say the suffix was undocumented and might be a
    fixed-point scale -- in which case a 2-contract fill would read as some
    large number and booking it would claim a position orders of magnitude too
    big. The `COUNT_FIELDS` log was added to settle it, and it did. Two live
    orders, straight from the worker:

        fill_count_fp='16.00'  yes_price_dollars='0.4600'
        taker_fill_cost_dollars='7.360000'      16 * 0.46 = 7.36   exact

        fill_count_fp='3.00'   yes_price_dollars='0.5200'
        taker_fill_cost_dollars='1.560000'       3 * 0.52 = 1.56   exact

    So the scale is 1, the unit is CONTRACTS, and the wire type is a DECIMAL
    STRING with two places -- not a number, which is why every read here goes
    through `_int_or_none` rather than indexing the value directly. Fees are
    quoted separately (`taker_fees_dollars`) and are NOT inside the fill cost.

    `reconcile_live_orders` still refuses to book more contracts than the order
    requested. That invariant was written as insurance against the scale being
    something else; it is kept now for the ordinary reasons.
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

    # STILL WORKING AT THE VENUE. Same contract Polymarket's view now carries,
    # and for the same reason: a PARTIAL fill is both a real position and a
    # live order for the remainder, while `state` has one slot and the fill
    # outranks the status. `remaining_count_fp` is Kalshi's own word for the
    # unfilled part and is already in the measured key list.
    remaining = None
    for field in ("remaining_count_fp", "remaining_count"):
        value = order.get(field)
        if value in (None, ""):
            continue
        try:
            remaining = float(value)
        except (TypeError, ValueError):
            remaining = None
        else:
            break

    return {
        "state": state,
        "venue_status": raw_status or None,
        "filled_count": filled,
        "fill_price": price,
        "fill_cost_dollars": fill_cost,
        "fees_dollars": fees,
        "open_at_venue": bool(remaining) or state == "resting",
        "remaining_count": remaining,
        # BOTH LEGS, carried rather than resolved. Which one we are paying
        # depends on our side, which this function does not know -- and Kalshi
        # hands over both, so guessing is unnecessary.
        "yes_price": _price_or_none(order.get("yes_price_dollars")),
        "no_price": _price_or_none(order.get("no_price_dollars")),
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
        # NO CONTRACT ID IS NOT NO PRICE, and calling it one sent three real
        # orders to the ledger under the wrong cause on 2026-08-25.
        #
        # `_kalshi_price_for` returns None at its FIRST line when
        # `venue_ticker` is empty -- before it ever asks Kalshi for a price --
        # so an unstamped position arrived here indistinguishable from a market
        # the venue would not quote. Every Kalshi row in the day's ledger read
        # `OrderBuildError: no_live_price: None`, and the `None` on the end was
        # the ticker saying so all along:
        #
        #   LIVE_ORDER status=rejected venue=kalshi ticker=None
        #     market=totals_alt side=over line=5.5
        #     error='OrderBuildError: no_live_price: None'
        #
        # `verify_order_paths` had the distinction right (`no_venue_ticker`)
        # while the path with money on it did not. The two point at different
        # fixes: a missing id is the board join or the position cap, a missing
        # price is the venue or staleness.
        ticker = str(getattr(request, "venue_ticker", "") or "").strip()
        if not ticker:
            raise OrderBuildError("no_venue_ticker")
        price = price_for(request)
        if price is None:
            raise OrderBuildError(f"no_live_price: {ticker}")
        return submit_order(request, price_dollars=float(price))

    return _submit


def _order_result(
    request: Any, body: Mapping[str, Any], response: Mapping[str, Any], *,
    price_dollars: float | None,
) -> dict[str, Any]:
    """Read one accepted submit's response. SHARED by the first send and the
    base retry, so the two can never disagree about what a fill is."""
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
