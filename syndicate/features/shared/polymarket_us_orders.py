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
from syndicate.features.shared.venue_order_states import (
    VENUE_DEAD_STATUSES,
    VENUE_FILLED_STATUSES,
    VENUE_RESTING_STATUSES,
)

# SHARED WITH EVERY OTHER VENUE -- see `venue_order_states`. Was a private
# copy until 2026-08-27 and had drifted from Kalshi's in both directions.
#: How much closer to the submitted limit one reading must be before it is
#: allowed to decide direct-vs-complement. Near a 0.5 limit the two are almost
#: equidistant and the test cannot discriminate; below this separation the
#: side label decides instead, and an unreadable side still withholds.
#: 0.10 is deliberately CONSERVATIVE and does NOT decide most recorded fills --
#: stated precisely because the first draft of this comment claimed it did:
#:
#:     limit 0.4405  separation 0.1190  DECIDED by limit -> direct
#:     limit 0.4545  separation 0.0910  falls through to the side rule
#:     limit 0.4902  separation 0.0196  falls through to the side rule
#:     limit 0.5192  separation 0.0384  falls through to the side rule
#:     limit 0.2200  separation 0.5300  DECIDED by limit -> direct  <- the blocker
#:
#: That is the intent: the side rule is right on all four historical fills, so
#: this must not override it where they are close. It fires only where the two
#: readings are far apart -- which is exactly where the side rule was wrong.
_COMPLEMENT_MARGIN = 0.10

_VENUE_FILLED_STATUSES = VENUE_FILLED_STATUSES

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
    """Which `outcomeSide` buys `outcomes[index]`, IF `outcomes[0]` is the YES
    leg -- and it is not. **This function is no longer reachable for a team
    side.** See `_resolve_outcome_side`.

    IT USED TO SAY "THE ONLY SOUND WAY TO PICK A SIDE ON THIS VENUE". That was
    wrong, and the correction is kept here rather than in a commit message
    because the sentence is exactly what made the defect survive a direct
    investigation on 2026-08-28.

    The claim underneath it is that `outcomes[position]` can be converted into
    a YES/NO by comparing `position` against a venue-wide `yes_outcome_index()`
    -- i.e. that `outcomes[0]` IS the YES leg on every market. That is an
    assumption about the array, made in the same file that documents the array
    being unreliable.

    MEASURED WRONG, 2026-08-28, on the settled live book. Every MLB game market
    cross-checked against MLB StatsAPI (`segment=full`, schedule keyed by date,
    fixtures appearing twice excluded):

        polymarket h2h,    venue-settled:  5 agree,  3 MISMATCH
        polymarket totals, venue-settled:  9 agree,  0 mismatch
        kalshi     totals, venue-settled:  4 agree,  0 mismatch

    The single decisive case, `aec-mlb-az-sf-2026-08-27`, three independent
    facts agreeing:

      * live-odds-worker 01:55:30Z -- `POLYMARKET_ARTIFACT_PRICE
        outcome_index=0 outcome='San Francisco Giants'`, then `SUBMIT
        side=OUTCOME_SIDE_YES action=BUY qty=15.45 price=0.48`. We asked for
        index 0 and this function turned that into YES.
      * StatsAPI -- **ARI 1 @ SF 6, Final.** We bet the team that won.
      * The venue graded it `lost`, `pnl_dollars=-5.871` (= 15.45 x 0.38, the
        whole cost basis), and its `positionResolution` row carries
        `side=POSITION_RESOLUTION_SIDE_SHORT`. The venue says we held the short
        leg of a market whose index 0 we had matched to San Francisco.

    So on that market the YES leg is NOT `outcomes[0]`, while on the five that
    agree it is. 3 of 8 is a coin flip, which is what a positional rule over an
    unordered array is.

    WHY TOTALS ARE IMMUNE, and why that is not luck: `_resolve_outcome_side`
    sends an over/under through `_side_to_outcome`, which maps the NAME
    (`over`->YES) and never consults the index at all. A team name carries no
    yes/no axis, so h2h had nothing to fall back on -- and fell back to this.

    Retained, not deleted, for three reasons: the over/under path still routes
    through `yes_outcome_index()`'s constant, the env override remains the
    documented way to correct the convention without a deploy, and the tests
    that pin this arithmetic are what will prove the eventual name-based rule
    is different from it.

    Measured earlier, and still true -- it is why a slug rule is not the answer
    either: `aec-atp-domstr-markru` carries `outcomes: ["Martin Krumich",
    "Dominic Stephan Stricker"]`, REVERSED relative to its own slug.
    """
    try:
        position = int(index)
    except (TypeError, ValueError):
        raise OrderBuildError(f"outcome_index_unreadable: {index!r}") from None
    if position not in (0, 1):
        raise OrderBuildError(f"outcome_index_out_of_range: {index!r}")
    return _SIDE_YES if position == yes_outcome_index() else _SIDE_NO


def _readable_index(index: Any) -> int | None:
    """`0`/`1` from whatever we were handed, or `None` -- NEVER a raise.

    A separate parser from `outcome_side_for_index`'s deliberately. That one
    RAISES, because a position it cannot read means an order it must not build.
    This one is asked "is there a usable index here at all", and the answer
    "no" is a normal branch that falls through to a NAMED refusal further down.
    Making absence raise here would report a missing `yesLegIndex` as
    `outcome_index_unreadable`, which names the wrong field.
    """
    if index is None or isinstance(index, bool):
        # `int(True) == 1`, so a bool would resolve as a real leg.
        return None
    try:
        position = int(index)
    except (TypeError, ValueError):
        return None
    if position != index and str(index).strip() != str(position):
        # NON-INTEGRAL INPUT IS JUNK, NOT A LEG. `int(1.5) == 1` truncates a
        # malformed index into a perfectly valid one, which is the silent
        # default this whole file exists to remove. Caught by a test that
        # expected None and got a tradeable answer.
        return None
    return position if position in (0, 1) else None


# The sides a club name identifies, and therefore the ones that carry no
# yes/no axis of their own. There is no sound rule for these on this venue
# today -- see `_resolve_outcome_side`.
_POSITIONAL_SIDES = frozenset({"home", "away"})

# Re-open team betting on this venue WITHOUT A DEPLOY, once the YES leg can be
# read by name. Off by default, and that default is the fix.
#
# An env switch rather than a code edit for the same reason
# `yes_outcome_index()` has one: the answer lives at the venue, and when it is
# finally read the correction should take minutes. It is also the escape hatch
# if this refusal turns out to cost more than the defect -- but note that
# turning it on restores a rule measured wrong on 3 of 8 real orders, so it is
# not a knob to reach for casually.
_ALLOW_TEAM_SIDE_ENV = "SYNDICATE_POLYMARKET_ALLOW_TEAM_SIDE"


def team_side_allowed() -> bool:
    import os

    return str(os.environ.get(_ALLOW_TEAM_SIDE_ENV) or "").strip() == "1"


def _resolve_outcome_side(
    side: Any,
    outcome_index: Any,
    yes_leg_index: Any = None,
    yes_leg_reason: Any = None,
) -> str:
    """Which leg to buy: by NAME where the name states it, and REFUSED where
    nothing states it.

    ------------------------------------------------------------------
    A TEAM SIDE IS NOW REFUSED. IT USED TO BE RESOLVED BY ARRAY POSITION.
    ------------------------------------------------------------------

    `over`/`under`/`yes`/`no` ARE the yes/no axis, so `_side_to_outcome` reads
    them off the name and is right by construction whatever order the market's
    `outcomes` happen to be in. Measured 9 of 9 correct on venue-settled MLB
    totals, 2026-08-28.

    `home`/`away` are not. A club name says nothing about which leg of a binary
    market it is, and this function used to answer that question with
    `outcome_side_for_index` -- a comparison of our team's POSITION in
    `outcomes` against a venue-wide constant. That is an assumption that
    `outcomes[0]` is the YES leg on every market, and it is false: measured
    wrong on 3 of 8 venue-settled Polymarket moneylines, with real money on
    both sides of the error (one full-stake loss on a bet whose team WON, and
    two recorded wins we did not earn, which overstate the book's P&L as well
    as misstating it). `outcome_side_for_index`'s docstring carries the case.

    THE SAME STOP THE SPREAD PATH ALREADY MAKES, one market over.
    `execute_portfolio._polymarket_resolve_market` refuses a spread with
    `spread_side_needs_verified_team_mapping` because "nothing in [the
    outcomes] says which TEAM is getting the points ... an assumed ordering on
    this venue has already bought the wrong team once today at a real cost".
    That is this situation exactly; the moneyline was left resolving
    positionally only because its outcomes ARE team names, which answers which
    team each entry is and not which leg either entry is.

    THE REFUSAL IS NO LONGER UNCONDITIONAL `[2026-08-30]`. It was written when
    "`_slate_row_for_storage` drops `marketSides` before the order path ever
    sees a row, so no name rule is writable today" was TRUE. It is now false:
    that function DERIVES the answer while the full venue payload is still in
    hand and persists it as `yesLegIndex` on every stored row. This function
    now READS it, and refuses only where the venue did not state it -- carrying
    `yesLegReason` so a census can separate "the venue never says" from "our
    matching is broken".

    WHAT IS NOT CLAIMED. `yesLegIndex` is the VENUE's answer, not a verified
    one. The caller is expected to corroborate it against an independent source
    and to refuse on disagreement; `_polymarket_resolve_market` does that
    against the AWAY team's position. This function does not second-guess an
    index it is handed -- one owner for that decision, not two.
    Neither field's SHAPE has ever been logged, only its key, so writing one
    now would be a guess. `learnings.md 2026-08-28` is explicit about what a
    guess costs here: flipping the constant on an unconfirmed diagnosis "would
    have inverted every future order", and on a money path the cost of a wrong
    fix is the bug itself. Refusing loses the h2h volume; guessing loses money
    and looks like it is working.

    THE THIRD BRANCH IS STILL NOT A FORMALITY. An unrecognised side (`draw`, a
    typo, an empty string) must not resolve to whatever position happened to be
    passed -- that would be a real bet on an outcome nobody named.
    `_side_to_outcome` raises for those and is still reached here.
    """
    raw = str(side or "").strip().lower()
    if raw in _POSITIONAL_SIDES:
        verified = _readable_index(yes_leg_index)
        if verified is not None:
            # THE VENUE'S OWN ANSWER, and it outranks the escape hatch. The
            # hatch restores a rule measured wrong on 3 of 8 settled
            # moneylines; a stated YES leg is strictly better evidence than
            # that, so a market carrying one is never resolved positionally
            # even when the hatch is open.
            position = _readable_index(outcome_index)
            if position is None:
                raise OrderBuildError(
                    f"outcome_index_unreadable: {outcome_index!r} -- the YES leg"
                    f" is known ({verified}) but our own position is not"
                )
            return _SIDE_YES if position == verified else _SIDE_NO
        if not team_side_allowed():
            raise OrderBuildError(
                f"team_side_needs_verified_yes_leg: {side!r} -- this venue's YES"
                " leg is not `outcomes[0]` (measured wrong on 3 of 8 settled"
                " moneylines, 2026-08-28) and the stored market row does not"
                f" name it: yesLegReason={yes_leg_reason!r}."
                f" Set {_ALLOW_TEAM_SIDE_ENV}=1 to restore the positional rule."
            )
    if raw in _POSITIONAL_SIDES and outcome_index is not None:
        return outcome_side_for_index(outcome_index)
    # Everything else lands on the NAME rule, which resolves
    # `over`/`under`/`yes`/`no` and RAISES for the rest.
    #
    # A team side with no index arrives here deliberately, so it keeps its own
    # refusal -- `side_needs_outcome_index`, which says a team must be resolved
    # against the outcomes array. Routing it to `outcome_side_for_index(None)`
    # also refuses, but as `outcome_index_unreadable`, which describes the
    # symptom and not the cause. On a money path the reason is the useful half.
    return _side_to_outcome(side)


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


def _log_order_states(rows: Any, *, mode: str) -> None:
    """One line per order: is it UNTOUCHED, or partly filled and stuck?

    `ORDERS_READ` already printed `keys=[...]` -- the NAMES of the fields,
    never the VALUES. So the two numbers that separate the only two stories a
    resting order can tell were fetched on every poll and thrown away:

        cumQuantity   == 0  and leavesQuantity == ordered   -> NEVER TOUCHED
        cumQuantity    > 0  and leavesQuantity  > 0         -> PARTIAL, STUCK

    Those have different causes -- no resting size at our price versus not
    enough of it -- and no reading in this system could tell them apart.

    WHY THIS IS WORTH A LINE. Three separate sessions attributed Polymarket's
    unfilled orders to three different mechanisms on 2026-08-30 -- a tick-size
    floor, a stale ask, and bidding a mid -- and MEASUREMENT REFUTED ALL THREE:
    quotes are on-grid (0 of 9 off-grid), the ask was 44s old at submit, and
    `prices[]` sums to 1.005-1.030 across 8 binary markets, which is an ask
    with its overround, not a mid. Meanwhile orders at the same price on the
    same venue both fill and rest -- `sea-tor` filled 11.17 contracts at 0.435
    while `lad-det` rested at 10.66 -- so size alone does not explain it.

    The next hypothesis should be tested against a reading rather than argued
    from a mechanism. This is that reading.
    """
    for row in rows or []:
        if not isinstance(row, Mapping):
            continue
        print(
            f"[polymarket_us_orders] ORDER_STATE mode={mode}"
            f" order={row.get('id') or row.get('orderId')}"
            f" slug={str(row.get('marketSlug') or '')!r}"
            f" state={str(row.get('state') or row.get('orderStatus') or '')!r}"
            f" side={row.get('outcomeSide')} action={row.get('action')}"
            f" price={row.get('price')}"
            f" cum={row.get('cumQuantity')!r} leaves={row.get('leavesQuantity')!r}"
            f" avgPx={row.get('avgPx')!r}"
            # THE EXPIRY WE NEVER SET AND NEVER READ.
            #
            # `order_body` sends `tif=TIME_IN_FORCE_GOOD_TILL_CANCEL` and NO
            # `goodTillTime`, so whatever expiry these orders carry is the
            # venue's own default -- and the venue RETURNS it on every read.
            # `ORDERS_READ` prints the KEY NAMES only, so the value has been
            # fetched on every poll all along and thrown away.
            #
            # WHY IT IS THE FIELD THAT MATTERS, measured 2026-08-30: Polymarket
            # orders are not resting-and-not-filling, they are CANCELLED, and we
            # re-place them within THREE SECONDS of noticing (submit 01:02:05 ->
            # CANCELED 01:30:32 -> resubmit 01:30:35). Two explanations are
            # already dead -- a fixed TTL (a replacement lived 40+ min while its
            # predecessor died at ~28) and market close (one died ~15h before
            # kickoff). An expiry the venue chose for us is the next candidate
            # and cannot be tested without this value.
            #
            # `tif` alongside it because we assume the venue STORED the
            # good-till-cancel we sent. That is an assumption, not a reading,
            # and this is the line that can check it.
            f" tif={row.get('tif')!r} goodTillTime={row.get('goodTillTime')!r}"
            f" created={row.get('createTime')!r} inserted={row.get('insertTime')!r}",
            flush=True,
        )


def round_price_to_tick(price: float, tick: float, *, direction: str) -> float:
    """Snap to a legal tick, TOWARD THE SIDE THAT CAN ACTUALLY TRADE.

    `direction` is REQUIRED and keyword-only. There is no safe default: the
    same snap that makes a buy marketable makes a sell non-marketable, so a
    caller that has not stated its side has not yet made the decision this
    function encodes.

    --------------------------------------------------------------------------
    WHY THIS USED TO FLOOR, AND WHY THAT WAS WRONG FOR A BUY
    --------------------------------------------------------------------------

    The original rule was DOWN always, reasoning that "for a BUY, rounding up
    pays more than the price the edge was computed against -- small per
    contract and systematic across a slate."

    That is true and it is not the whole trade. Flooring saves at most one tick
    PER CONTRACT WHEN IT FILLS, and costs the ENTIRE POSITION when it does not.
    Those are not the same units, and the second is much larger.

    MEASURED 2026-08-30 on live-odds-worker. `tsc-mlb-lad-det-2026-08-30-7pt5`
    resolved at the venue's own quote of 0.515 on a 0.01 tick:

        POLYMARKET_ARTIFACT_PRICE slug=tsc-mlb-lad-det-2026-08-30-7pt5 price=0.515
        FILL_ABOVE_LIMIT ... submitted_limit=0.51 filled=0.0

    The floor put our bid a half-tick BELOW the price the venue was asking, so
    it rested instead of filling. Four of fifteen Polymarket orders that day
    were resting unfilled; the two whose quotes did not land on the tick grid
    are explained entirely by this line.

    Kalshi never showed this because its quotes are already whole cents on a
    0.01 tick, so the floor is a no-op there. Polymarket quotes are not: ticks
    of 0.01 and 0.005 both occur in one slate, so a 0.515 is legal in one
    market and needs snapping in the next.

    `kalshi_price_for` reached the same conclusion from the other direction on
    2026-08-24 -- "a resting order is worse than a missed one" -- because a
    standing limit at a price we no longer believe is a free option written to
    everyone else. It fills only if the market comes back to us, which is the
    market moving AGAINST the thesis.

    The overpay this admits is bounded by ONE TICK and is guarded: the caller
    checks slippage against the SNAPPED price, not the raw quote, so a snap
    that pushes past tolerance is refused rather than silently paid.
    """
    tick_value = _positive_float(tick, "tick_size")
    if direction == "up":
        steps = math.ceil(round(price / tick_value, 9))
    elif direction == "down":
        steps = math.floor(round(price / tick_value, 9))
    else:
        raise OrderBuildError(f"tick_direction_unknown: {direction!r}")
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
    yes_leg_index: Any = None,
    yes_leg_reason: Any = None,
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

    # UP, because this body is always an `ORDER_ACTION_BUY` (see `action`
    # below). Snapping a buy limit DOWN puts it under the venue's own quote,
    # which is how four Polymarket orders rested unfilled on 2026-08-30.
    if price < _positive_float(tick_size, "tick_size"):
        # A QUOTE THIS GRID CANNOT EXPRESS. Under the old DOWN snap this fell
        # out for free -- it floored to zero and was refused. Snapping UP would
        # instead turn a 0.004 quote into a 0.01 order, so the refusal is now
        # stated rather than implied. It is a refusal, not a rounding: a price
        # below one tick is not a price this market trades at.
        raise OrderBuildError(f"price_below_one_tick: price={price} tick={tick_size}")

    snapped = round_price_to_tick(price, tick_size, direction="up")
    if snapped <= 0:
        raise OrderBuildError(f"price_below_one_tick: price={price} tick={tick_size}")
    if not snapped < 1.0:
        # Snapping UP can leave the open interval that snapping DOWN could not:
        # 0.995 on a 0.01 tick becomes 1.00, which is a settled market or a unit
        # error, never a price. The pre-snap range check above cannot see this.
        raise OrderBuildError(
            f"price_out_of_range_after_snap: price={price} tick={tick_size} snapped={snapped}"
        )

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
        # WHICH READING IS AUTHORITATIVE DEPENDS ON WHETHER OUR SIDE NAME
        # CARRIES THE YES/NO AXIS. It is not "index when we have one".
        #
        # `over`/`under`/`yes`/`no` ARE the axis. `home`/`away` are not -- a
        # team name says nothing about which leg of a binary market it is, so
        # there the INDEX is the only sound source and `_side_to_outcome`
        # refuses them outright.
        #
        # THE INDEX RULE WAS APPLIED TO BOTH AND IT BOUGHT THE WRONG SIDE.
        # Measured 2026-08-26T03:06:28Z, real money:
        #
        #   POLYMARKET_ARTIFACT_PRICE our_side=over outcome_index=1
        #       outcome='Over' outcomes=['Under', 'Over']
        #   SUBMIT side=OUTCOME_SIDE_NO action=BUY qty=30.46 price=0.26
        #       our_side=over outcome_index=1 yes_index=0
        #
        # The array is REVERSED -- `Over` sits at index 1 -- so
        # `outcome_side_for_index(1)` with `yes_index=0` returned NO, and NO on
        # that market is Under. We asked for Over and bought Under, at the
        # price resolved for Over. Both halves are the same defect the
        # Texas/White Sox order hit this morning, with the polarity reversed:
        # there the SIDE was positional and the price was matched; here the
        # price was matched and the SIDE was positional.
        #
        # `yes_outcome_index()` is a VENUE-WIDE constant, and this market
        # proves the YES leg is a property of the market, not of the venue.
        # For an over/under that question does not need answering at all --
        # the outcome's own name settles it, whatever position it holds.
        #
        # The price still comes from the matched index, and is now consistent:
        # buying YES (`Over`) at `outcomePrices[1]` (Over's price) describes
        # one outcome again.
        "outcomeSide": _resolve_outcome_side(
            getattr(request, "side", None),
            outcome_index,
            yes_leg_index=yes_leg_index,
            yes_leg_reason=yes_leg_reason,
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
    yes_leg_index: Any = None,
    yes_leg_reason: Any = None,
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
        yes_leg_index=yes_leg_index,
        yes_leg_reason=yes_leg_reason,
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
        f" yes_index={yes_outcome_index()}"
        # WHICH RULE PICKED THE SIDE. `yes_leg_index` present means the venue
        # stated its YES leg and the positional constant above was NOT used --
        # without this the two are indistinguishable in the log, which is how
        # the inverted order of 2026-08-25 stayed invisible.
        f" yes_leg_index={yes_leg_index!r} yes_leg_reason={yes_leg_reason!r}",
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
        yes_leg_index = None
        yes_leg_reason = None
        # LENGTH-TOLERANT ON PURPOSE. Three resolver shapes are in the tree at
        # once and a hard unpack turns an older one into a TypeError at submit
        # time -- on the money path, at the worst moment. Each extra value is
        # additive and defaults to "not stated", which is the refusing branch.
        if len(resolved) == 6:
            slug, price, tick, min_qty, outcome_index, yes_leg = resolved
            if isinstance(yes_leg, tuple):
                yes_leg_index, yes_leg_reason = yes_leg
            else:
                yes_leg_index = yes_leg
        elif len(resolved) == 5:
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
            yes_leg_index=yes_leg_index,
            yes_leg_reason=yes_leg_reason,
        )

    return submit


# --------------------------------------------------------------------------
# THE READ SIDE. Without it a submitted order can never be reconciled, and an
# unreconciled order blocks EVERY live run on EVERY venue.
# --------------------------------------------------------------------------

_VENUE_RESTING_STATUSES = VENUE_RESTING_STATUSES
_VENUE_DEAD_STATUSES = VENUE_DEAD_STATUSES

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


# THE CANCEL ROUTE IS A GUESS UNTIL A REAL CALL CONFIRMS IT, and that is why
# `cancel_order` will not fire without `execute=True`.
#
# This venue is a gRPC-gateway API -- prefixed enums (`ORDER_STATUS_CANCELED`)
# and `{"code":12}` UNIMPLEMENTED bodies. Its create route is `POST /v1/orders`
# and its read is `GET /v1/order/{id}`: sibling spellings differing by one
# character and one verb, which is exactly how the list route was guessed wrong
# once already. `DELETE /v1/order/{id}` is the convention-consistent cancel and
# is the default here, overridable by env without a deploy.
#
# IT CANNOT BE PROBED the way the list route was. `probe_order_list_routes` is
# safe only because every candidate is a GET; there is no read-only way to ask
# "would this write path work", and a blind write against a money account can
# create or destroy something. So the first real cancel IS the probe -- which is
# why this logs the exact method, URL and raw response.
_ORDER_CANCEL_PATH = "/v1/order"
_ORDER_CANCEL_METHOD = "DELETE"

#: Venue statuses meaning there is nothing left to cancel. Matched as substrings
#: because this API prefixes its enums (`ORDER_STATUS_CANCELED`, not `canceled`).
_NOT_CANCELLABLE = ("CANCELED", "CANCELLED", "FILLED", "EXECUTED", "EXPIRED", "REJECTED")


def _order_cancel_url(order_id: str) -> str:
    from syndicate.features.shared.polymarket_us_auth import BASE_URL

    base = (os.environ.get("POLYMARKET_US_API_BASE") or "").strip() or BASE_URL
    path = (os.environ.get("POLYMARKET_US_ORDER_CANCEL_PATH") or _ORDER_CANCEL_PATH).strip()
    if not path.startswith("/"):
        path = "/" + path
    return base.rstrip("/") + path.rstrip("/") + "/" + urllib.parse.quote(str(order_id), safe="")


def cancel_order(
    order_id: str,
    *,
    execute: bool = False,
    expect_client_order_id: str | None = None,
    expect_market_slug: str | None = None,
) -> dict[str, Any]:
    """Cancel ONE resting order at Polymarket. DRY RUN unless `execute=True`.

    --------------------------------------------------------------------------
    WHY THIS EXISTS
    --------------------------------------------------------------------------

    Measured 2026-08-30: a restated `commence_time` minted a second
    `position_key` for a bet already placed, and ~$9.12 rested at this venue as
    two legs where one was intended. The identity defect is fixed. **Retiring
    the surplus leg was not possible in code at all** -- no cancel path existed,
    so a human had to find it on the venue's own Orders screen. A second
    duplicate pair had already FILLED before anyone looked (`pnl -3.41` and
    `-0.78` on a bet nobody intended).

    --------------------------------------------------------------------------
    READ BEFORE WRITE, BECAUSE THE HAZARD IS THE WRONG LEG
    --------------------------------------------------------------------------

    A duplicate pair is two orders on the SAME market, side and line, differing
    only in id and stake. Cancelling the wrong one keeps the unintended bet AND
    destroys the intended one -- strictly worse than doing nothing. So this
    always reads the order first and refuses when:

      * the venue says it is already filled, cancelled, expired or rejected --
        nothing to cancel, and on a FILLED order the money has already moved;
      * `expect_client_order_id` or `expect_market_slug` was given and the venue
        disagrees. **Pass them.** An id copied from a log or a screenshot is
        precisely the input that lands on the wrong row, and a mismatch means
        the caller believes something false about this order.

    **DRY RUN BY DEFAULT.** With `execute=False` it does the read and the checks
    and reports the request it WOULD send, touching the venue only with a GET.

    Nothing in this repo calls it automatically and nothing should: it is a
    capability for an operator, not a step in a loop. Choosing WHICH leg of a
    duplicate pair is the intended one is a judgement about sizing intent that
    this function deliberately does not make.
    """
    from syndicate.features.shared import polymarket_us_auth as auth

    order_id = str(order_id or "").strip()
    if not order_id:
        return {"status": "refused", "reason": "order_id_empty"}
    if not auth.credentials_present():
        return {"status": "skipped", "reason": "credentials_absent", "order_id": order_id}

    try:
        raw = auth.signed_request("GET", _order_url(order_id))
    except Exception as exc:  # noqa: BLE001
        # A FAILED READ IS NOT PERMISSION TO WRITE. Absence in a failed read is
        # not absence at the venue -- the same rule `reconcile_live_orders`
        # applies before it will modify any record.
        return {
            "status": "error",
            "reason": ("read_failed: %s: %s" % (type(exc).__name__, exc))[:200],
            "order_id": order_id,
        }

    order = raw.get("order") if isinstance(raw.get("order"), Mapping) else raw
    view = venue_order_view(order) if isinstance(order, Mapping) else {}
    venue_status = str(view.get("venue_status") or "").upper()
    client_id = str((order or {}).get("clientOrderId") or (order or {}).get("client_order_id") or "")
    slug = str((order or {}).get("marketSlug") or (order or {}).get("market_slug") or "")

    plan = {
        "order_id": order_id,
        "venue_status": venue_status or None,
        "state": view.get("state"),
        "client_order_id": client_id or None,
        "market_slug": slug or None,
        "filled_count": view.get("filled_count"),
        "method": _ORDER_CANCEL_METHOD,
        "url": _order_cancel_url(order_id),
    }

    if any(token in venue_status for token in _NOT_CANCELLABLE):
        plan.update(status="refused", reason="not_cancellable: " + (venue_status or "unknown"))
        print("[polymarket_us_orders] CANCEL_REFUSED %s" % plan, flush=True)
        return plan

    for label, expected, actual in (
        ("client_order_id", expect_client_order_id, client_id),
        ("market_slug", expect_market_slug, slug),
    ):
        if expected is None:
            continue
        if str(expected).strip() != actual:
            plan.update(
                status="refused",
                reason="%s_mismatch: expected %r, venue says %r" % (label, expected, actual),
            )
            print("[polymarket_us_orders] CANCEL_REFUSED %s" % plan, flush=True)
            return plan

    if not execute:
        plan.update(status="dry_run", reason="execute=False; nothing was sent")
        print("[polymarket_us_orders] CANCEL_DRY_RUN %s" % plan, flush=True)
        return plan

    print(
        "[polymarket_us_orders] CANCEL_SEND order_id=%r method=%s url=%r"
        " client_order_id=%r slug=%r venue_status=%r"
        % (order_id, _ORDER_CANCEL_METHOD, plan["url"], client_id, slug, venue_status),
        flush=True,
    )
    try:
        response = auth.signed_request(_ORDER_CANCEL_METHOD, plan["url"])
    except Exception as exc:  # noqa: BLE001
        plan.update(status="error", reason=("%s: %s" % (type(exc).__name__, exc))[:300])
        print("[polymarket_us_orders] CANCEL_FAILED %s" % plan, flush=True)
        return plan

    plan.update(status="sent", response=response)
    print("[polymarket_us_orders] CANCEL_SENT %s" % plan, flush=True)
    return plan


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


# PER-ORDER. `GET /v1/orders` answers `code: 12` UNIMPLEMENTED here, so one
# read sees exactly the ids it was handed and never the account. An orphan scan
# is impossible against this reader, and saying so up front is what stops a
# zero-candidate pass from making a pointless call that 501s every cycle.
ORDER_READ_COVERAGE = "per_order"


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
            _log_order_states(rows, mode="per_order")
        # PER_ORDER, AND SAYING SO IS THE POINT. This branch reads exactly the
        # ids it was handed, so the returned count can never exceed the asked
        # count and an order that exists at Polymarket but not in our ledger is
        # INVISIBLE to it -- which is precisely the case the write-ahead record
        # exists for. Reporting `book` here would let a tautology
        # (`venue_orders == candidates`) read as independent confirmation.
        return {
            "status": "ok",
            "orders": rows,
            "count": len(rows),
            "errors": errors,
            "coverage": "per_order",
        }

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
    return {"status": "ok", "orders": orders, "count": len(orders), "coverage": "book"}


# Polymarket's own name for the commission it has actually taken on an order.
#
# NEVER DERIVE THE FEE FROM `commissionsBasisPoints`. It reads `'0'` on EVERY
# order this platform has observed, and that zero is not a contradiction of the
# collected total sitting beside it -- **the fee is FLAT PER CONTRACT, so it has
# no ad-valorem component for a basis-points field to express.** Measured
# 2026-08-30 across five fills: $0.015/contract, independent of price
# (18.70 contracts -> $0.28; 3.91 -> $0.06; 2.38 -> $0.04, i.e. 0.0142-0.0168
# per contract once cent-rounding is allowed for). Expressed against the $1
# notional that happens to equal 150 bps, but the venue does not report it that
# way.
#
# THIS EXACT ZERO ALREADY CAUSED ONE WRONG ANSWER. A sibling lane concluded
# "Polymarket's fee is ZERO" and moved MLB break-even 3.38c -> 0.88c on it --
# wrong in the direction that manufactures arbs which lose on every fill.
# `bps == 0` is evidence of the fee's SHAPE, never of its ABSENCE.
#
# So the collected total is the only field read here, and an absent one yields
# None (unknown), never 0.0 (free).
_COMMISSION_FIELDS = (
    "commissionNotionalTotalCollected",
    "commission_notional_total_collected",
)


def _nonzero_bps(value: Any) -> bool:
    """True only for a basis-points figure that is present AND not zero.

    Absent is NOT non-zero: this venue omits fields freely, and a guard that
    fired on `None` would cry wolf on every order. `"0"`, `0`, `0.0` and `""`
    all mean "no rate reported", which is the state every observation so far
    has been in.
    """
    if value in (None, ""):
        return False
    try:
        return float(value) != 0.0
    except (TypeError, ValueError):
        # A rate we cannot parse is a rate we cannot dismiss.
        return True


def _commission_dollars(
    order: Mapping[str, Any],
    *,
    fill_cost: float | None,
    price: float | None = None,
    filled: float | None = None,
) -> float | None:
    """What the venue CHARGED for this order, in dollars.

    ----------------------------------------------------------------------
    THIS RETURNED `None` UNCONDITIONALLY AND THE FIELD WAS ALWAYS THERE
    ----------------------------------------------------------------------

    `execution_ledger` already says it in its own words -- "FEES ARE REAL MONEY
    AND WERE MODELLED AS ZERO EVERYWHERE" -- and fixed it for Kalshi by carrying
    `taker_fees_dollars` across. Polymarket kept the hardcoded `None`, so every
    Polymarket fill in the book records a cost lower than the one the account
    paid.

    MEASURED 2026-08-29: order `C60JWBG0WKDK` filled 3.91 contracts at $0.47 =
    $1.8377, and the account moved $1.8977 (`buyingPower` 96.04765 -> 94.14995,
    `cashBalance` 118.15 -> 116.25 agreeing). **$0.06 of real money, ~3.3% of
    notional, recorded nowhere** -- against edges this system will act on at 3%.

    The field was in the read the whole time. Today's `ORDERS_READ` key list:
    `[..., 'commissionNotionalTotalCollected', 'commissionsBasisPoints', ...,
    'makerCommissionsBasisPoints', ...]`.

    THE UNIT IS AN ASSUMPTION AND IT IS NAMED, the same way `venue_balances`
    names its cents assumption -- this repo has already paid for a 100x price
    bug once. Dollars is the reading, and the guard below is what makes a wrong
    reading LOUD instead of silent: a commission cannot exceed what was spent,
    so a value that does is a unit error, not a fee, and is refused rather than
    booked. Refusing leaves `fees_dollars` None, which is the status quo -- a
    wrong fee is worse than a missing one, because a missing one is visible as
    a null.
    """
    raw = None
    for field in _COMMISSION_FIELDS:
        value = order.get(field)
        if isinstance(value, Mapping):
            value = value.get("value")
        if value not in (None, ""):
            raw = value
            break
    if raw is None:
        return None
    try:
        fee = float(raw)
    except (TypeError, ValueError):
        return None
    if fee < 0.0:
        return None
    if fee == 0.0:
        # A REAL ANSWER. A maker fill genuinely pays nothing on some venues, and
        # 0.0 is different from "we never read it" -- the same distinction
        # `fees_dollars` already draws between None and 0.0 in the resting
        # branch of reconciliation.
        return 0.0
    if fill_cost is not None and fill_cost > 0.0 and fee > fill_cost:
        print(
            f"[polymarket_us_orders] COMMISSION_IMPLAUSIBLE"
            f" order={order.get('id') or order.get('orderId')}"
            f" slug={order.get('marketSlug')!r} raw={raw!r} dollars={fee!r}"
            f" fill_cost={fill_cost!r}"
            " -- a commission cannot exceed the cost of the fill it is charged"
            " on. Assuming a unit error and WITHHOLDING the fee; check whether"
            " this venue reports commission in cents.",
            flush=True,
        )
        return None
    # THE INPUTS, LOGGED BESIDE THE ANSWER. Asked for by `venue_fees.py`, which
    # currently refuses every Polymarket arb on
    # `polymarket_fee_never_observed: fees_dollars is null on 13/13 filled` --
    # the null this function was written to remove. Modelling the rate needs
    # the DENOMINATOR as well as the charge, and it needs the venue's own
    # basis-point fields to check the derived rate against what it says it
    # charges. Recording only `fees_dollars` would replace "no number" with "a
    # number nobody can calibrate", which is the same mistake one step later.
    #
    # NOT CIRCULAR, and that has to be true or the calibration is worthless:
    # every value here comes off the venue's order read. Nothing in this repo
    # computes a Polymarket fee -- which is exactly why it was null.
    # THE ASSUMPTION, GUARDED. Every observation so far says the charge is flat
    # per contract and `commissionsBasisPoints` is 0. If the venue ever reports
    # a non-zero rate, that assumption has changed underneath every caller that
    # models the fee, and the flat $0.015/contract figure in `venue_fees` stops
    # being safe. Say so loudly once rather than let a silent schedule change
    # be discovered by a losing position.
    _bps = order.get("commissionsBasisPoints")
    _maker_bps = order.get("makerCommissionsBasisPoints")
    if _nonzero_bps(_bps) or _nonzero_bps(_maker_bps):
        print(
            f"[polymarket_us_orders] COMMISSION_RATE_APPEARED"
            f" order={order.get('id') or order.get('orderId')}"
            f" bps={_bps!r} maker_bps={_maker_bps!r} collected={raw!r}"
            " -- this venue has always reported 0 here and the fee was modelled"
            " as FLAT per contract. A non-zero rate means the fee schedule may"
            " have changed; re-measure before trusting any modelled fee.",
            flush=True,
        )
    print(
        f"[polymarket_us_orders] COMMISSION order={order.get('id') or order.get('orderId')}"
        f" slug={order.get('marketSlug')!r} raw={raw!r} dollars={fee!r}"
        f" fill_price={price!r} filled={filled!r} fill_cost={fill_cost!r}"
        f" bps={order.get('commissionsBasisPoints')!r}"
        f" maker_bps={order.get('makerCommissionsBasisPoints')!r}",
        flush=True,
    )
    return fee


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
    # Fields whose value was rejected as NOT A PRICE, kept so the reason is
    # visible rather than the price silently being absent. A zero and a 104.0
    # are different problems -- an unfilled order versus a units error -- and
    # collapsing them would hide the one that matters.
    zero_price_fields: list[str] = []
    out_of_range_fields: list[tuple[str, float]] = []
    # `avgPx` is the venue's own average fill price, from the measured keys.
    for field in ("avgPx", "averageFillPrice", "average_fill_price", "avgPrice", "fillPrice"):
        raw_price = order.get(field)
        if isinstance(raw_price, Mapping):
            raw_price = raw_price.get("value")
        if raw_price in (None, ""):
            continue
        try:
            candidate = round(float(raw_price), 4)
        except (TypeError, ValueError):
            price = None
        else:
            # A VALUE OUTSIDE (0, 1) IS NOT A PRICE. `avgPx` is `0.0000` on an
            # order the venue has not filled: that zero is ABSENCE wearing a
            # number, and treating it as a price is not cosmetic.
            #
            # MEASURED IN PRODUCTION 2026-08-30, live-odds-worker `77ca329a`:
            #
            #   * The same `avgPx='0.0000'` recorded `0.0` on one leg and `None`
            #     on another. The split was the DIRECTION check, not the side:
            #     a zero is below any limit, so it tripped the sell branch and
            #     was withheld -- the right answer reached by an argument about
            #     an impossible fill, on an order with `filled=0.0`.
            #   * `FILL_ABOVE_LIMIT` fired **36 times in one hour on orders with
            #     `filled=0.0`**. A guard that cries wolf on every resting order
            #     cannot be believed when it fires for real.
            #   * On a BUY the zero SURVIVED as `recorded=0.0`. That is the
            #     hazard: `fill_stake_dollars` is derived as `contracts x
            #     fill_price` (`execution_ledger`), so once `cumQuantity` goes
            #     positive a real position books at **$0**. Same class as the
            #     $347.36-against-a-$1.64-stake units bug, inverted -- and
            #     harder to catch, because zero reads as nothing rather than as
            #     a mistake.
            #
            # This is why the guard belongs HERE and not at the limit check:
            # the limit check can only ever catch the sell half, and by then the
            # value has already been treated as a price.
            #
            # `continue`, not `break` -- a zero in `avgPx` must not stop the
            # search, because a later field may carry a real price.
            if not (0.0 < candidate < 1.0):
                if candidate == 0.0:
                    zero_price_fields.append(field)
                else:
                    out_of_range_fields.append((field, candidate))
                continue
            price = candidate
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

    # ------------------------------------------------------------------
    # CHOOSE THE READING THE SUBMITTED LIMIT AGREES WITH, not the one the
    # side label implies. (2026-08-30)
    # ------------------------------------------------------------------
    #
    # The `is_no` rule below was inferred from four fills and is right on all
    # four. It is WRONG on the order that halted live execution for ~12 hours,
    # and the failure is silent because the guard downstream then correctly
    # refuses the nonsense it produces:
    #
    #     C65VD0R72KDG   avgPx 0.2350   submitted limit 0.22
    #     outcomeSide OUTCOME_SIDE_NO -> complement -> 0.7650
    #     0.7650 > 0.22  -> FILL_ABOVE_LIMIT -> price WITHHELD -> None
    #
    # `fill_price=None` then forced `execution_ledger` onto its contract bound,
    # which refused `13.13 > 10.8953` and blocked every live slate. The venue
    # had reported the fill price the whole time; three sessions diagnosed this
    # as "this path has no fill price". It had one, and this line discarded it.
    #
    # THE DISCRIMINATOR NEEDS NO SIDE SEMANTICS, which is what makes it safe
    # here: `order["price"]` is OUR submitted limit as the venue itself echoes
    # it, so it is quoted on the same scale as `avgPx`. A real fill sits near
    # its limit; the complement sits ~a whole unit away. So pick whichever of
    # {avgPx, 1-avgPx} is closer to the limit.
    #
    # VALIDATED ON EVERY FILL THIS FILE HAS EVER RECORDED -- the four in the
    # table above, 4/4, plus the blocking order:
    #
    #     limit   avgPx   |direct-lim|  |compl-lim|   picks       recorded
    #     0.4405  0.4000       0.0405      0.1595     direct      direct
    #     0.4545  0.5500       0.0955      0.0045     COMPLEMENT  COMPLEMENT
    #     0.4902  0.5100       0.0198      0.0002     COMPLEMENT  COMPLEMENT
    #     0.5192  0.5200       0.0008      0.0392     direct      direct
    #     0.2200  0.2350       0.0150      0.5450     direct      (was withheld)
    #
    # AMBIGUITY IS A REFUSAL, NOT A COIN FLIP. Near a 0.5 limit the two
    # readings are nearly equidistant and this cannot tell them apart, so it
    # falls through to the side rule rather than guessing -- the same choice
    # the unreadable-side branch already makes. `_COMPLEMENT_MARGIN` is the
    # separation required before the limit is allowed to decide.
    decided_by_limit = False
    if price is not None and 0.0 < price < 1.0:
        limit_hint = order.get("price")
        if isinstance(limit_hint, Mapping):
            limit_hint = limit_hint.get("value")
        try:
            limit_hint = float(limit_hint)
        except (TypeError, ValueError):
            limit_hint = None
        if limit_hint is not None and 0.0 < limit_hint < 1.0:
            direct_gap = abs(price - limit_hint)
            complement_gap = abs((1.0 - price) - limit_hint)
            if abs(direct_gap - complement_gap) >= _COMPLEMENT_MARGIN:
                decided_by_limit = True
                if complement_gap < direct_gap:
                    price = round(1.0 - price, 4)

    if decided_by_limit:
        pass
    elif price is not None and 0.0 < price < 1.0 and is_no:
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

    # --------------------------------------------------------------------
    # A BUY CANNOT COST MORE THAN ITS OWN LIMIT. CHECK THE RESULT, NOT THE RULE.
    # --------------------------------------------------------------------
    #
    # The complement above is a RULE about which side `avgPx` is quoted on.
    # Nothing verified its OUTPUT, so applying it when it should not have been
    # -- or failing to when it should -- produced a recorded price the order
    # could not possibly have filled at, and nothing said so.
    #
    # MEASURED 2026-08-26, `tsc-mlb-bos-mia-2026-08-26-8pt5`, real money:
    #
    #     submitted   limit 0.43, quantity 9.60   ($4.13 stake)
    #     venue       semi-filled 7.11 of 9.60
    #     recorded    fill_price 0.57  ->  7.11 x 0.57 = $4.05
    #     ceiling     7.11 x 0.43      =            $3.06
    #
    # $4.05 against a $3.06 ceiling is 32% over on an order that was never
    # marketable above 0.43. One of the two numbers is wrong and the ledger
    # cannot tell which -- `fill_stake_dollars` is DERIVED as
    # `contracts x fill_price` (`execution_ledger.py`), and `fill_cost_dollars`
    # is None, so NOTHING in this system independently measures what was paid.
    # That is why this checks the only thing it can prove.
    #
    # SEMANTICS-FREE, and that is the point. It makes no claim about which
    # token `OUTCOME_SIDE_NO` buys or how `avgPx` is quoted -- the two readings
    # this file has now had wrong in both directions. It only asserts that a
    # BUY does not fill above the price we ourselves sent, which is true on any
    # exchange under either reading.
    #
    # WITHHELD RATHER THAN CORRECTED. Flipping the price back would be a third
    # guess at the same convention. Withholding makes reconciliation fall back
    # to the price we ASKED for -- a known number -- exactly as the unreadable
    # side branch above already does.
    submitted_limit = order.get("price")
    if isinstance(submitted_limit, Mapping):
        submitted_limit = submitted_limit.get("value")
    try:
        submitted_limit = float(submitted_limit)
    except (TypeError, ValueError):
        submitted_limit = None

    # THE RULE IS DIRECTIONAL AND THIS READ IT ONE WAY. (2026-08-30)
    #
    # "A BUY cannot fill above its own limit" is true. The inverse is equally
    # true and was not encoded: **a SELL cannot fill BELOW its own limit**, and
    # a sell filling ABOVE it is price improvement -- the good outcome. Applying
    # the buy rule to a sell refuses exactly the fills we want.
    #
    # MEASURED on the order that halted live execution for ~12 hours:
    #
    #     C65VD0R72KDG   side ORDER_SIDE_SELL   intent ORDER_INTENT_BUY_SHORT
    #     avgPx 0.2350   submitted limit 0.22
    #     buy rule:   0.2350 > 0.22 + 0.01  -> VIOLATION -> price withheld
    #     sell rule:  0.2350 < 0.22 - 0.01  -> fine, and it is IMPROVEMENT
    #
    # So even with the complement corrected above, this line discarded the
    # price a second time. Both halves had to be wrong for the outage, and
    # fixing either alone leaves `fill_price=None`.
    #
    # `side` IS THE VENUE'S OWN ORDER DIRECTION and is a different field from
    # `outcomeSide` (which names the token). An unreadable direction keeps the
    # BUY rule -- the conservative branch, and the one this file already had.
    order_direction = str(order.get("side") or "").strip().upper()
    is_sell = order_direction.endswith("SELL")

    if (
        price is not None
        and submitted_limit is not None
        and 0.0 < submitted_limit < 1.0
        # A tick of slack: the venue snaps and rounds, and this must fire on an
        # inverted price (a whole complement away), never on a rounding step.
        and (
            price < submitted_limit - 0.01
            if is_sell
            else price > submitted_limit + 0.01
        )
    ):
        print(
            f"[polymarket_us_orders] FILL_ABOVE_LIMIT"
            f" order={order.get('id') or order.get('orderId')}"
            f" slug={order.get('marketSlug')!r} outcome_side={outcome_side!r}"
            f" avgPx={raw_price!r} recorded={price!r} submitted_limit={submitted_limit!r}"
            f" filled={filled!r} complement_of_recorded={round(1.0 - price, 4)!r}"
            f" direction={order_direction!r}"
            " -- a BUY cannot fill above its own limit (nor a SELL below it), so"
            " the recorded price is"
            " wrong. Price WITHHELD; reconciliation falls back to the requested"
            " price. Check whether the avgPx complement was applied to the wrong"
            " side for this market.",
            flush=True,
        )
        price = None

    # NOT-A-PRICE, REPORTED. A refusal nobody can read is one somebody deletes,
    # so a rejected value says which field and why -- but the two cases are
    # logged at very different volumes on purpose.
    #
    # A zero on a RESTING order is the normal case and is SILENT: it is what
    # every unfilled order looks like, and logging it is what turned
    # FILL_ABOVE_LIMIT into 36 lines an hour of noise. A zero WITH a fill is the
    # dangerous combination -- the venue says quantity moved and reports no
    # price -- and is loud. Anything outside (0,1) that is not zero is a units
    # error and says so in those words.
    if out_of_range_fields:
        print(
            f"[polymarket_us_orders] FILL_PRICE_OUT_OF_RANGE"
            f" order={order.get('id') or order.get('orderId')}"
            f" rejected={out_of_range_fields!r}"
            " -- outside (0,1), so not a probability. Price treated as ABSENT."
            " A value >= 1 is the units error this file records costing $347.36"
            " against a $1.64 stake.",
            flush=True,
        )
    elif zero_price_fields and filled:
        print(
            f"[polymarket_us_orders] FILL_PRICE_ZERO_WITH_FILL"
            f" order={order.get('id') or order.get('orderId')}"
            f" filled={filled!r} fields={zero_price_fields!r}"
            " -- venue reports a FILL with a zero price. Price treated as"
            " ABSENT; reconciliation falls back to the requested price rather"
            " than booking the position at $0.",
            flush=True,
        )

    # THE RAW FIELD, LOGGED. This defect was diagnosed from a screenshot and
    # arithmetic because no log line carried `avgPx`, so the one input that
    # would have settled it in seconds was the one nobody could see.
    if raw_price not in (None, ""):
        print(
            f"[polymarket_us_orders] FILL_PRICE order={order.get('id') or order.get('orderId')}"
            f" outcome_side={outcome_side!r} avgPx={raw_price!r} recorded={price!r}",
            flush=True,
        )

    remaining = None
    for field in ("leavesQuantity", "leaves_quantity", "remainingQuantity"):
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
        "fill_cost_dollars": None,
        # STILL WORKING AT THE VENUE, which `state` alone cannot say.
        #
        # REPORTED BY THE USER 2026-08-26 from the Polymarket Orders tab: five
        # open orders there — four Pending and one **Semi-filled** (BOS/MIA,
        # 7.11 of 9.60) — against four on our page. A partially filled order is
        # BOTH things at once: a real position for the filled part AND a live
        # order for the remainder. `state` has one slot, the fill outranks the
        # status (deliberately — reading it the other way reconciles a real
        # position away to zero), so the row books as `filled` and vanishes
        # from every count of what is still open.
        #
        # The consequences are not cosmetic: the remainder can still fill,
        # `cancel_stale_resting_orders` never sees it, and the page tells you
        # you have one fewer order working than you do.
        #
        # So the open-ness is carried SEPARATELY rather than by overloading
        # `state`. `leavesQuantity` is the venue's own word for the unfilled
        # remainder and is already in the measured key list.
        "open_at_venue": bool(remaining) or state == "resting",
        "remaining_count": remaining,
        # THE VENUE'S OWN CHARGE, no longer hardcoded to None. See
        # `_commission_dollars` -- $0.06 on a $1.84 fill was going unrecorded.
        "fees_dollars": _commission_dollars(
            order,
            fill_cost=(price * filled) if (price is not None and filled) else None,
            price=price,
            filled=filled,
        ),
        "order_id": order.get("id") or order.get("orderId"),
        "client_order_id": order.get("clientOrderId") or order.get("client_order_id"),
        "ticker": order.get("marketSlug") or order.get("market_slug"),
    }
