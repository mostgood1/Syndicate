"""Grade placed orders against what actually happened, and price the result.

WHY THIS DID NOT EXIST, WHICH IS THE WHOLE POINT. The ledger records that an
order was placed, filled, at what price, for what stake -- and then nothing.
`settled_at` on an order record is the moment the ORDER reached a terminal state
AT THE VENUE, not the moment the BET was decided; it is stamped by
`complete_order` the instant a paper fill is written, seconds after the bet is
placed and hours before the game ends. Reading it as settlement is the trap this
module is named to avoid, which is why the field here is `graded_at`.

So `settled_count` has been 0 for as long as it has been reported, and every
stake in the system is a Kelly fraction shrunk toward nothing on the strength of
that zero (`#502`). Nothing was broken. Nobody had written the grader.

--------------------------------------------------------------------------
GRADE ONLY WHAT IS DECIDED, AND GRADE IT ONCE
--------------------------------------------------------------------------

`resolve_bet_status` already knows when a bet is decided -- a final game, or a
monotone market whose value has crossed the line and cannot come back. This
grades exactly those and leaves everything else ungraded WITH A NAMED REASON,
because "we have not graded this yet" and "this lost" are the two facts a
performance number must never blur.

And it grades once. A graded order is never re-graded: a later feed read can
differ (a stat correction, or a cache miss returning nothing at all), and a
ledger that changes its mind about a settled bet is not a record of anything.
The immutability is what makes the number quotable.

--------------------------------------------------------------------------
A PUSH IS NOT A LOSS
--------------------------------------------------------------------------

`resolve_bet_status` reports a final tie as `live_tied` with `decided=True`,
which reads oddly and matters enormously: folding it into the losses would
understate every performance figure this produces. It is mapped to `push` here,
returns the stake, and is counted separately from both.

--------------------------------------------------------------------------
P&L COMES FROM THE FILL, NOT THE REQUEST
--------------------------------------------------------------------------

`requested_price` is what the plan wanted; `fill_price` is what was taken. The
difference is slippage, and grading against the request would silently credit
the strategy with a price it did not get.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

__all__ = [
    "american_profit",
    "dates_needing_settlement",
    "grade_order",
    "settle_orders",
    "settled_decisions_by_sport",
    "settlement_summary",
    "OUTCOME_WON",
    "OUTCOME_LOST",
    "OUTCOME_PUSH",
]

OUTCOME_WON = "won"
OUTCOME_LOST = "lost"
OUTCOME_PUSH = "push"

REASON_NOT_DECIDED = "not_decided_yet"
REASON_NOT_FILLED = "order_not_filled"
REASON_NO_PRICE = "no_fill_price"
REASON_ALREADY_GRADED = "already_graded"

# THE VENUE GETS FIRST REFUSAL ON A LIVE ORDER [user decision 2026-08-26].
#
# `venue_settlement.settle_from_venue` grades a live order from the venue's own
# settlement record; this module grades it from a status WE resolve. Both skip
# an order that already carries an `outcome`, and they run on DIFFERENT
# SERVICES -- this one from `intelligence_state.py` on refresh-worker, the venue
# one on live-odds-worker. So before this constant existed, whichever service
# ticked first after a game ended owned that row permanently, and which grader
# won was decided by timing rather than by policy.
#
# Deferring for a window makes the venue win in practice (both venues settle
# within minutes to hours) while keeping this module as the FALLBACK for a
# market the venue never settles -- which must still reach the ledger rather
# than sit open forever. That is the whole trade, and it is why this is a delay
# and not a refusal.
REASON_AWAITING_VENUE = "awaiting_venue"
REASON_AWAITING_VENUE_NO_AGE = "awaiting_venue_no_age"

_DEFAULT_VENUE_GRACE_HOURS = 24.0


def _venue_grace_hours() -> float:
    import os

    raw = os.environ.get("SYNDICATE_VENUE_SETTLEMENT_GRACE_HOURS")
    if raw is None or not str(raw).strip():
        return _DEFAULT_VENUE_GRACE_HOURS
    try:
        parsed = float(str(raw).strip())
    except (TypeError, ValueError):
        return _DEFAULT_VENUE_GRACE_HOURS
    # A negative window would mean "never defer", which is a policy change
    # dressed as a typo. Zero is a legitimate value -- it disables the deferral
    # deliberately -- so only negatives fall back.
    return parsed if parsed >= 0 else _DEFAULT_VENUE_GRACE_HOURS


def _order_age_hours(order: Mapping[str, Any]) -> float | None:
    """How long since we placed this, in hours. None if we cannot tell.

    `submitted_at` first because it is the precise stamp, `selected_date` as the
    fallback because every order carries one -- it is the key `settle_orders`
    already filters on. Without that fallback a single malformed stamp would
    mean an order deferred forever, which is worse than grading it late.
    """
    from datetime import date as _date

    now = datetime.now(timezone.utc)

    text = str(order.get("submitted_at") or "").strip()
    if text:
        try:
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
            return (now - moment).total_seconds() / 3600.0
        except ValueError:
            pass

    slate = str(order.get("selected_date") or "").strip()
    if slate:
        try:
            # End of the slate day, not its start: a night game on that date has
            # not finished at 00:00, and ageing from midnight would hand the
            # fallback a head start it has not earned.
            day = _date.fromisoformat(slate)
            midnight_after = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
            return (now - midnight_after).total_seconds() / 3600.0 - 24.0
        except ValueError:
            pass

    return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _as_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return None if parsed != parsed else parsed


def american_profit(price: Any) -> float | None:
    """Profit per $1 staked at American odds. +150 -> 1.5, -110 -> 0.909…

    Returns None rather than 0.0 for an unreadable price. A zero would render a
    winning bet as a break-even one, which is a wrong number that looks like a
    modest result rather than like an error.
    """
    value = _as_float(price)
    if value is None or value == 0:
        return None
    if value > 0:
        return value / 100.0
    return 100.0 / abs(value)


def contract_profit(price: Any) -> float | None:
    """Profit per $1 staked on a PROBABILITY-DOLLAR contract. 0.46 -> 1.174…

    A Kalshi contract costs $p and settles at $1, so a winner returns
    (1 - p) / p per dollar staked.
    """
    value = _as_float(price)
    if value is None or not 0.0 < value < 1.0:
        return None
    return (1.0 - value) / value


def profit_per_dollar(price: Any) -> float | None:
    """The right arithmetic for whichever unit the fill price is in.

    THE LEDGER HOLDS BOTH UNITS IN ONE COLUMN. A sportsbook fill records
    American odds (-110); a Kalshi fill records probability dollars (0.46).
    Grading 0.46 as American odds returns 0.0046 -- a winning contract booked
    at a 0.46% profit instead of 117%, a number ~250x too small that reads as a
    disappointing result rather than as an error. The same confusion rendered
    every Kalshi price on the live page as `+0`.

    The boundary is unambiguous: American odds are never strictly inside
    (-1, 1), and a probability price is always strictly inside (0, 1).
    """
    value = _as_float(price)
    if value is None:
        return None
    if 0.0 < value < 1.0:
        return contract_profit(value)
    return american_profit(value)


def grade_order(order: Mapping[str, Any], status: Mapping[str, Any]) -> dict[str, Any]:
    """One order plus its resolved status -> outcome and P&L, or a named refusal.

    Pure: no clock, no ledger, no feed. The caller supplies the status so this
    can be tested as arithmetic, which is what it is.
    """
    from syndicate.features.shared.bet_status import STATUS_LOST, STATUS_WON

    if str(order.get("status") or "") != "filled":
        # An order that never filled has no outcome to grade. Counting it as a
        # loss would charge the strategy for a bet it does not hold.
        return {"graded": False, "reason": REASON_NOT_FILLED}

    if not status.get("decided"):
        return {"graded": False, "reason": REASON_NOT_DECIDED}

    stake = _as_float(order.get("fill_stake_dollars"))
    profit_multiple = profit_per_dollar(order.get("fill_price"))
    if stake is None or profit_multiple is None:
        return {"graded": False, "reason": REASON_NO_PRICE}

    # FEES ARE PAID ON EXECUTION, WHATEVER THE OUTCOME. Kalshi took $0.02 on a
    # $1.08 fill -- ~1.9%, against edges this system will act on at 3%. Netted
    # into every branch including the push, because the money left the account
    # when the trade happened, not when it settled.
    #
    # Absent means UNKNOWN, and unknown is charged as zero here rather than
    # refused: a bet whose fee we cannot read is still a bet with a real
    # outcome, and refusing to grade it would lose the outcome to save the
    # rounding. Every venue but Kalshi reports no fee at all today.
    fees = _as_float(order.get("fees_dollars")) or 0.0

    raw = str(status.get("status") or "")
    if raw == STATUS_WON:
        outcome, pnl = OUTCOME_WON, stake * profit_multiple - fees
    elif raw == STATUS_LOST:
        outcome, pnl = OUTCOME_LOST, -stake - fees
    else:
        # A DECIDED tie is a push: the stake comes back and the bet is neither
        # won nor lost. `resolve_bet_status` calls it `live_tied`, which reads
        # oddly for a finished game -- folding it into the losses would
        # understate every figure this module produces.
        outcome, pnl = OUTCOME_PUSH, -fees

    return {
        "graded": True,
        "outcome": outcome,
        "pnl_dollars": round(pnl, 4),
        "settled_value": status.get("current_value"),
        "line": status.get("line"),
    }


def _our_verdict(
    order: Mapping[str, Any], resolver: Callable[[Mapping[str, Any]], dict[str, Any]]
) -> tuple[dict[str, Any] | None, dict[str, Any], str]:
    """Our own reading of one order: `(verdict | None, resolved, refusal)`.

    EXTRACTED SO THERE IS EXACTLY ONE OF IT. `settle_orders` grades with this,
    and `_check_venue_grade` cross-examines the venue with it. Two copies would
    eventually disagree, and the whole value of the cross-check is that the two
    readings are the SAME reading applied to different authorities.

    A refusal comes back as a NAMED string, never a bare None, because the
    caller files it into a counter that has to stay a work list.
    """
    from syndicate.features.shared.bet_status import resolve_bet_status

    try:
        resolved = resolver(order) or {}
    except Exception as exc:
        return None, {}, f"resolver_error:{type(exc).__name__}"
    if resolved.get("unavailable_reason"):
        # The feed's own vocabulary, passed through rather than flattened:
        # `no_game_pk`, `no_feed` and `no_stat` are three different jobs.
        return None, resolved, str(resolved["unavailable_reason"])

    # THE RESOLVER MAY RESTATE `side` AND `line`, and for game lines it must.
    #
    # A spread arrives on the order as `side="Texas Rangers", line=-1.5` and
    # a moneyline as `side="Levante", line=None`. Neither is expressible in
    # the grader's over/under vocabulary, which is why 80 of 171 orders on
    # 2026-08-23 refused with `unmapped_market` and always would have.
    # `game_line_bet` translates them into a value, a direction and a
    # number; the ORDER cannot be rewritten (it records what was actually
    # bet), so the translation has to arrive here.
    #
    # Falls back to the order's own fields, so every player prop is
    # untouched by this and the resolver only speaks up when it has
    # something different to say.
    status = resolve_bet_status(
        market=order.get("market"),
        side=resolved.get("side", order.get("side")),
        line=resolved.get("line", order.get("line")),
        current_value=resolved.get("current_value"),
        is_final=bool(resolved.get("is_final")),
        started=bool(resolved.get("started", True)),
    )
    if status.get("unavailable_reason"):
        return None, resolved, str(status["unavailable_reason"])

    verdict = grade_order(order, status)
    if not verdict.get("graded"):
        return None, resolved, str(verdict.get("reason"))
    return verdict, resolved, ""


def _check_venue_grade(
    order: dict[str, Any], resolver: Callable[[Mapping[str, Any]], dict[str, Any]]
) -> str | None:
    """Does the VENUE's settlement agree with the GAME? Writes `grade_check`.

    ----------------------------------------------------------------------
    THE ONLY CHECK IN THIS SYSTEM THAT CAN CATCH A WRONG-SIDE ORDER
    ----------------------------------------------------------------------

    Two authorities settle a live bet, and they are independent in exactly the
    way that matters:

      OURS    the sport resolver reads the real result and applies the order's
              own recorded `side`. It CANNOT detect a wrong side -- it grades
              the bet we MEANT to place, so it agrees with our intent by
              construction, whatever the venue actually bought.
      VENUE   `venue_settlement.grade_polymarket_resolution` reads the realized
              P&L delta on the position the venue says we held. It knows
              nothing about our `side` field.

    So a disagreement is not a tie to be broken -- it is the signature of the
    two describing DIFFERENT POSITIONS, which is what a wrong-side fill is.

    MEASURED 2026-08-28, the first time anything ran this comparison: 3 of 8
    venue-settled Polymarket moneylines disagree, against 0 of 13 on totals
    across both venues. `aec-mlb-az-sf-2026-08-27` is the clean one -- we bet
    San Francisco, San Francisco won 6-1, the venue paid us a full-stake loss,
    and its resolution row says we held the SHORT leg.

    `learnings.md 2026-08-28` records that this class "has now been caught twice
    by a human looking at a screen and zero times by a machine". This is the
    machine.

    NEVER TOUCHES `outcome` OR `pnl_dollars`. It records a disagreement; it does
    not adjudicate one. Which authority is right is a question about the venue's
    YES leg, and a cross-check that started rewriting settled money on its own
    reading would be strictly worse than the defect it exists to report -- the
    same argument `grade_polymarket_resolution` makes for refusing a zero delta
    rather than calling it a push.

    RUNS ONCE PER ORDER. `grade_check` is the memo: present means checked, so a
    re-run costs no feed lookup, exactly as `outcome` gates the grading path.
    Returns "agrees" / "conflict" / a refusal reason, or None when not eligible.
    """
    if str(order.get("settled_by") or "") != "venue":
        # Only a venue-stated outcome is independent of our `side`. Checking one
        # of OUR grades against OUR resolver would compare a reading with itself
        # and report agreement forever -- an unfed field indistinguishable from
        # a working one, which is the failure this repo names most often.
        return None
    if order.get("grade_check"):
        return None

    verdict, _resolved, refusal = _our_verdict(order, resolver)
    if verdict is None:
        # NOT a conflict. "The venue said won and the game says lost" and "the
        # venue said won and we cannot read the game" are opposite findings and
        # only the first is evidence of anything. `agrees: None` is the third
        # value, and it is why this field is not a bool.
        order["grade_check"] = {
            "agrees": None,
            "reason": refusal,
            "venue_outcome": str(order.get("outcome") or ""),
            "checked_at": _utc_now(),
        }
        return refusal

    ours = str(verdict.get("outcome") or "")
    theirs = str(order.get("outcome") or "")
    agrees = ours == theirs
    order["grade_check"] = {
        "agrees": agrees,
        "our_outcome": ours,
        "venue_outcome": theirs,
        # The scoreboard the disagreement rests on, so a person reading the row
        # does not have to go and look the game up to believe it.
        "settled_value": verdict.get("settled_value"),
        "checked_at": _utc_now(),
    }
    return "agrees" if agrees else "conflict"


def settle_orders(
    selected_date: str,
    *,
    resolver: Callable[[Mapping[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Grade every ungraded, decided order for `selected_date`. Persists.

    Idempotent by construction: an order carrying an `outcome` is skipped before
    the resolver is even asked, so re-running this cannot change a settled bet
    and cannot cost a feed lookup for one either.
    """
    from syndicate.features.shared.bet_status import resolve_bet_status
    from syndicate.features.shared.execution_ledger import _load, _persist

    normalized = str(selected_date or "").strip()
    if not normalized:
        return {"status": "skipped", "reason": "no_date"}

    if resolver is None:
        resolver = _default_resolver(normalized)

    state = _load()
    orders = [o for o in (state.get("orders") or []) if o.get("selected_date") == normalized]

    graded = 0
    already = 0
    # The cross-check's own counters, kept apart from `reasons` -- those are
    # about rows we could not GRADE, and these are about rows we could not
    # VERIFY. One counter for both would make a feed outage look like a wave of
    # settlement disagreements.
    conflicts = 0
    agreements = 0
    unchecked: dict[str, int] = {}
    # `graded` alone used to decide whether to persist. The cross-check writes
    # `grade_check` onto rows it never grades, so a slate with nothing new to
    # grade can still have something new to save.
    dirty = False
    reasons: dict[str, int] = {}
    outcomes: dict[str, int] = {}
    # WHICH markets we cannot grade, by name. The reason counter stays a stable
    # low-cardinality key (`unmapped_market`); this is the detail beside it.
    # `unmapped_market: 15` is a number nobody can act on -- the market NAMES
    # are the difference between "add five mappings" and another round of
    # guessing at which five.
    unmapped: dict[str, int] = {}

    def _refuse(reason: str, market: Any = None) -> None:
        reasons[reason] = reasons.get(reason, 0) + 1
        if market is not None:
            name = str(market or "<absent>")
            unmapped[name] = unmapped.get(name, 0) + 1

    grace_hours = _venue_grace_hours()

    for order in orders:
        if order.get("outcome"):
            already += 1
            # CROSS-EXAMINE THE VENUE'S GRADES ON THE WAY PAST. A settled row is
            # skipped for GRADING -- that idempotence is load-bearing and is not
            # touched -- but a venue-stated outcome has never been checked
            # against the actual game result, and 3 of 8 of them were wrong on
            # 2026-08-28. See `_check_venue_grade`; it writes a memo, once, and
            # never changes an outcome.
            checked = _check_venue_grade(order, resolver)
            if checked == "conflict":
                conflicts += 1
                dirty = True
                print(
                    "[paper_settlement] GRADE_CONFLICT"
                    f" date={normalized} venue={order.get('venue')}"
                    f" market={order.get('market')} side={order.get('side')}"
                    f" ticker={order.get('venue_ticker')}"
                    f" venue_said={order.get('outcome')}"
                    f" game_says={(order.get('grade_check') or {}).get('our_outcome')}"
                    f" pnl={order.get('pnl_dollars')}"
                    " -- THE VENUE AND THE SCOREBOARD DESCRIBE DIFFERENT"
                    " POSITIONS. Nothing was changed.",
                    flush=True,
                )
            elif checked == "agrees":
                agreements += 1
                dirty = True
            elif checked:
                unchecked[checked] = unchecked.get(checked, 0) + 1
                dirty = True
            continue

        if str(order.get("status") or "") != "filled":
            _refuse(REASON_NOT_FILLED)
            continue

        # THE VENUE FIRST, ON FILLED LIVE ORDERS ONLY. See REASON_AWAITING_VENUE
        # above: without this, which grader owns a row is decided by which
        # worker happened to tick first after the game ended.
        #
        # AFTER THE FILLED CHECK, DELIBERATELY. An unfilled order opened no
        # position, so no venue will ever settle it -- deferring it would swap a
        # correct `order_not_filled` refusal for a wait that can never end.
        # Ordering this before the check did exactly that, and
        # `test_an_unfilled_order_is_not_counted_as_a_loss` caught it.
        #
        # PAPER IS DELIBERATELY UNTOUCHED -- it has no venue record to wait for,
        # so deferring it would be delay in exchange for nothing.
        if str(order.get("mode") or "") == "live" and grace_hours > 0:
            age = _order_age_hours(order)
            if age is None:
                # Deferred, and NAMED. "The venue has not settled it" and "we
                # cannot tell how old it is" both end in an ungraded row, and
                # only one of them is a bug -- a shared reason string would make
                # them the same line in the counter.
                _refuse(REASON_AWAITING_VENUE_NO_AGE)
                continue
            if age < grace_hours:
                _refuse(REASON_AWAITING_VENUE)
                continue

        verdict, resolved, refusal = _our_verdict(order, resolver)
        if verdict is None:
            _refuse(
                refusal,
                order.get("market") if refusal == "unmapped_market" else None,
            )
            continue

        order["outcome"] = verdict["outcome"]
        order["pnl_dollars"] = verdict["pnl_dollars"]
        order["settled_value"] = verdict["settled_value"]
        # THE SCOREBOARD, where the resolver supplied one. `settled_value` is
        # the margin, and a margin is self-consistent under an inverted sign
        # convention -- so it can never falsify one. The two raw scores can,
        # and storing them is what makes the grade audit self-service instead
        # of a request for someone to go and look a game up.
        for field in ("home_score", "away_score", "home_name", "away_name"):
            if resolved.get(field) is not None:
                order[field] = resolved[field]
        # NOT `settled_at` -- that is the venue's clock and is already stamped.
        # See the module docstring; conflating them is the whole reason this
        # number read as zero.
        order["graded_at"] = _utc_now()
        graded += 1
        outcomes[verdict["outcome"]] = outcomes.get(verdict["outcome"], 0) + 1

    if graded:
        dirty = True
    if dirty:
        _persist(state)

    print(
        "[paper_settlement] SETTLED"
        f" date={normalized}"
        f" orders={len(orders)}"
        f" graded={graded}"
        f" already_graded={already}"
        f" outcomes={outcomes}"
        # Named, because "we have not graded this yet" and "this lost" are the
        # two facts a performance number must never blur.
        f" ungraded={reasons}"
        # THE CROSS-CHECK, ON THE SAME LINE, AND `conflicts=0` IS PRINTED EVEN
        # WHEN IT IS ZERO. A zero here is a real reading only if a non-zero
        # `verified` sits beside it -- `conflicts=0 verified=0` means nothing
        # was checked, which is the state this whole line exists to distinguish
        # from a clean book. Omitting the zero would make the two identical.
        f" verified={agreements} conflicts={conflicts}"
        f" unverifiable={unchecked}",
        flush=True,
    )
    if unmapped:
        print(
            f"[paper_settlement] UNMAPPED_MARKETS date={normalized} {dict(sorted(unmapped.items(), key=lambda kv: -kv[1]))}",
            flush=True,
        )

    # THE MONEY, BESIDE THE COUNTS.
    #
    # `SETTLED` above reports how many bets were graded and why the rest were
    # not. It has never reported what any of it WON OR LOST -- that figure
    # existed only on `/portfolio/paper`, which is a web page, and the web
    # service is unreachable from the worker that computes this. So the one
    # question the whole settlement layer exists to answer ("is this working")
    # could only be asked from a browser, by a person, one date at a time.
    #
    # MEASURED 2026-08-24T17:39Z: game-line grading landed and the slate went
    # from 71 graded to 150, `outcomes={'lost': 49, 'won': 28}` -- and there
    # was no way to turn that into dollars from the logs at all.
    #
    # Both scopes, because they answer different questions and the per-date one
    # alone cannot answer the second: the date says "how did Saturday go", the
    # all-time says "is this working". Clicking through days and adding them up
    # by eye is not the second answer, it is a chore that produces a guess.
    try:
        by_date = settlement_summary(normalized, orders=orders)
        all_time = settlement_summary(None, orders=state.get("orders") or [])
        for scope, summary in (("date=" + normalized, by_date), ("all_time", all_time)):
            total = summary.get("total") or {}
            # ROI stays ABSENT rather than 0.0 when nothing is settled -- a
            # 0.0% return on zero bets and on fifty are the same string and
            # opposite facts, which is why `settlement_summary` omits it.
            roi = total.get("roi_pct")
            win = total.get("win_pct")
            print(
                # `book=portfolio` on the line, because this number USED to span
                # both books and a reader comparing it against an older log
                # otherwise has no way to know the definition changed under them.
                f"[paper_settlement] PNL {scope} book=portfolio"
                f" settled={total.get('settled')} pending={total.get('pending')}"
                f" won={total.get('won')} lost={total.get('lost')} push={total.get('push')}"
                f" staked=${total.get('staked_dollars')} pnl=${total.get('pnl_dollars')}"
                f" roi={'n/a' if roi is None else f'{roi}%'}"
                f" win_rate={'n/a' if win is None else f'{win}%'}"
                f" venues={(summary.get('books') or {}).get('portfolio', {}).get('venues')}"
                f" by_venue={[(b.get('venue'), b.get('settled'), b.get('pnl_dollars'), b.get('roi_pct')) for b in summary.get('by_venue') or []]}",
                flush=True,
            )
            # THE SHADOW BOOKS, ON THEIR OWN LINE AND NEVER ADDED TO THE ABOVE.
            #
            # These are `paper:<venue>` -- the same board rows re-priced and
            # re-sized per venue, so their orders overlap the portfolio's one for
            # one. Printed because the comparison is what paper2 exists to
            # produce; separated because summing it was the defect.
            comparison = summary.get("comparison_total") or {}
            c_roi, c_win = comparison.get("roi_pct"), comparison.get("win_pct")
            print(
                f"[paper_settlement] PNL {scope} book=venue_comparison"
                f" settled={comparison.get('settled')} pending={comparison.get('pending')}"
                f" won={comparison.get('won')} lost={comparison.get('lost')}"
                f" staked=${comparison.get('staked_dollars')} pnl=${comparison.get('pnl_dollars')}"
                f" roi={'n/a' if c_roi is None else f'{c_roi}%'}"
                f" win_rate={'n/a' if c_win is None else f'{c_win}%'}"
                f" venues={(summary.get('books') or {}).get('venue_comparison', {}).get('venues')}"
                # SAID OUT LOUD ON THE LINE. Anyone reading two totals will try
                # to add them; this is the sentence that stops them.
                f" note=overlaps_portfolio_do_not_sum",
                flush=True,
            )
            # The two cuts that separate best-of-N EV inflation from market-mix.
            # See `settlement_summary`. Printed on their own line so the venue
            # line stays readable and so a grep for one does not drag in three.
            for cut in ("by_market_family", "by_sport", "by_venue_family"):
                rows_out = [
                    (b.get("key"), b.get("settled"), b.get("pnl_dollars"), b.get("roi_pct"), b.get("win_pct"))
                    # SETTLED ROWS ONLY. The cross is |venues| x 3 buckets and
                    # most of them are empty; a line that is mostly `(_, 0,
                    # 0.0, None, None)` buries the four numbers being compared.
                    # The other two cuts stay unfiltered -- they are small, and
                    # a family with zero settled rows is itself informative
                    # there (it is the composition claim, stated directly).
                    for b in summary.get(cut) or []
                    if cut != "by_venue_family" or b.get("settled")
                ]
                print(f"[paper_settlement] PNL_CUT {scope} {cut}={rows_out}", flush=True)
    except Exception as exc:
        # NEVER FATAL. Grading already happened and is persisted; a reporting
        # failure must not undo it or stop the next date.
        print(f"[paper_settlement] PNL_FAILED date={normalized} {type(exc).__name__}: {exc}", flush=True)

    return {
        "status": "ok",
        "date": normalized,
        "orders": len(orders),
        "graded": graded,
        "already_graded": already,
        "outcomes": outcomes,
        "ungraded": reasons,
        "unmapped_markets": dict(sorted(unmapped.items(), key=lambda kv: -kv[1])),
        # The cross-check's result, so a caller can assert on it rather than
        # grepping a log line for it. See `_check_venue_grade`.
        "verified": agreements,
        "conflicts": conflicts,
        "unverifiable": dict(unchecked),
    }


# How far back the straggler sweep will look, and how many slates it will do in
# one pass. Both bound a WORKER loop, so both are deliberately small.
#
# `#241` is the standing lesson: periodic work on the worker is never free, and
# a sweep that grows with the book would eventually cost a restart loop. This
# one is bounded on both axes and skips a date entirely when nothing on it is
# ungraded, so the steady state is zero extra resolver builds.
_STRAGGLER_MAX_AGE_DAYS = 14
_STRAGGLER_MAX_DATES = 6


def dates_needing_settlement(
    *,
    today: str,
    max_age_days: int = _STRAGGLER_MAX_AGE_DAYS,
    max_dates: int = _STRAGGLER_MAX_DATES,
) -> list[dict[str, Any]]:
    """Slates that still hold a FILLED, UNGRADED order. Newest first.

    ----------------------------------------------------------------------
    WHY THIS EXISTS: "TODAY AND YESTERDAY" IS A WINDOW A BET CAN FALL OUT OF
    ----------------------------------------------------------------------

    `intelligence_state` has always settled exactly two dates, on the sound
    argument that a night game finishes after midnight UTC and books under the
    previous slate (`#370`). What that argument does not cover is a row that is
    ungradeable ON BOTH of its two days and becomes gradeable LATER -- and every
    mechanism this repo has been adding does exactly that:

      * a resolver ships for a sport that had none. Soccer (`#547`), NFL and
        NCAAF all landed this way, and NFL landed on 2026-08-28, by which time
        2026-08-26's NFL rows were two days old and would never be asked again.
      * a boxscore or a feed backfills after the fact.
      * the venue grace (`REASON_AWAITING_VENUE`, 24h) defers a late game past
        the end of its own second day.

    MEASURED on the live book 2026-08-28T14:0xZ, which is what this fixes:
    two WNBA totals on `2026-08-26` (`Golden State Valkyries @ Connecticut Sun`,
    over and under 151.5, both FILLED) still carrying no outcome. The WNBA
    resolver exists and works; nothing had asked it about that date since
    2026-08-27, and nothing ever would have again.

    A permanently ungradeable row is worse than a wrong one: it sits in `open`
    forever, so the book's exposure reads high and its settled ROI reads over a
    population that is quietly missing its hard cases.

    ----------------------------------------------------------------------
    BOUNDED, AND CHEAP WHEN THERE IS NOTHING TO DO
    ----------------------------------------------------------------------

    Returns at most `max_dates` slates no older than `max_age_days`, and only
    ones that actually hold an ungraded filled order -- so on a healthy book it
    returns `[]` and costs one ledger read that the caller was making anyway.

    The SPORTS on each date come back with it. The caller uses them to decide
    whether a date is worth a boxscore refresh, because refreshing WNBA boxes
    for a slate with no ungraded WNBA row is exactly the free-looking periodic
    work that is not free.

    PURE: takes `today` rather than reading a clock, so a test can pin the
    window instead of arranging for one.
    """
    from datetime import date as _date

    from syndicate.features.shared.execution_ledger import _load

    try:
        floor = (_date.fromisoformat(str(today).strip()) - timedelta(days=int(max_age_days))).isoformat()
    except (TypeError, ValueError):
        # An unreadable `today` must not silently widen the window to the whole
        # book -- that is the sweep this bound exists to prevent.
        return []

    pending: dict[str, dict[str, Any]] = {}
    for order in (_load().get("orders") or []):
        if not isinstance(order, Mapping):
            continue
        if order.get("outcome"):
            continue
        if str(order.get("status") or "") != "filled":
            # Only a FILLED row can ever be graded. Anything else is refused by
            # `settle_orders` on every pass, so counting it here would keep a
            # date permanently "needing settlement" and burn the budget on it.
            continue
        slate = str(order.get("selected_date") or "").strip()
        if not slate or slate < floor or slate > str(today):
            continue
        entry = pending.setdefault(slate, {"date": slate, "orders": 0, "sports": set()})
        entry["orders"] += 1
        sport = str(order.get("sport") or "").strip().lower()
        if sport:
            entry["sports"].add(sport)

    ordered = sorted(pending.values(), key=lambda e: e["date"], reverse=True)
    return [
        {"date": e["date"], "orders": e["orders"], "sports": sorted(e["sports"])}
        for e in ordered[: max(0, int(max_dates))]
    ]


def audit_game_line_grades(selected_date: str, *, limit: int = 25) -> dict[str, Any]:
    """Print the RAW FACTS behind each game-line verdict, from the LEDGER.

    MEASURED 2026-08-24T19:17Z: game lines graded -16.4% on 79 bets at a 35.44%
    win rate, while totals -- graded through the old, long-exercised path --
    returned +24.03%. Game lines began grading four hours earlier, through code
    written that day.

    A CONSISTENT SIGN INVERSION PRODUCES EXACTLY THAT PICTURE, and nothing
    already in place can detect one: the unit tests assert both directions
    against my own convention, so an inverted convention passes them
    symmetrically, and `home_away_disagree_between_sources` checks whether the
    two SOURCES agree about which team is home, not whether the convention is
    right. Both pass while every verdict is backwards.

    READS THE STORED VERDICT, NOT A RE-DERIVATION. The first version called
    `_default_resolver` to recompute the margin, and on 2026-08-24T19:29Z it
    reported `audited=0 of=79` -- every row refused, because MLB feed payloads
    live on refresh-worker's disk and this runs on live-odds-worker. Same class
    of mistake as the Kalshi series discovery that ran in the wrong process.

    Reading the ledger is better than fixing that, for a reason beyond
    convenience: `settled_value` is the margin the grader ACTUALLY USED. A
    re-derivation can disagree with what was stored, and then the audit is
    reporting a third thing rather than auditing the second.

    Read-only. It changes nothing -- an audit that writes can create the thing
    it was meant to detect.
    """
    from syndicate.features.shared.execution_ledger import _load
    from syndicate.features.shared.game_line_bet import is_game_line_market

    normalized = str(selected_date or "").strip()
    orders = [
        o
        for o in (_load().get("orders") or [])
        if o.get("selected_date") == normalized
        and o.get("outcome")
        and is_game_line_market(o.get("sport"), o.get("market"))
    ]
    if not orders:
        print(f"[paper_settlement] GRADE_AUDIT date={normalized} rows=0", flush=True)
        return {"status": "ok", "rows": 0, "candidates": 0}

    rows = 0
    # WHY A ROW WAS SKIPPED, BY NAME. The first version had a bare `continue`
    # and printed `audited=0 of=79` with no reason -- a diagnostic that refuses
    # silently, in a repo whose whole discipline is named refusals. It made the
    # audit itself unauditable.
    skipped: dict[str, int] = {}
    for order in orders[:limit]:
        margin = order.get("settled_value")
        line_used = order.get("line")
        if margin is None:
            skipped["no_settled_value"] = skipped.get("no_settled_value", 0) + 1
            continue
        if line_used is None and str(order.get("market") or "").lower().startswith("spread"):
            skipped["no_line_on_spread"] = skipped.get("no_line_on_spread", 0) + 1
            continue

        rows += 1
        # The other reading, side by side. Not a judgement -- the point is that
        # both sit on one line so a person does not have to re-derive one.
        try:
            threshold = -float(line_used) if line_used is not None else 0.0
            inverted = "won" if float(margin) < threshold else "lost"
        except (TypeError, ValueError):
            threshold, inverted = None, "?"
        # THE SCOREBOARD FIRST, where we have it. A row carrying the real
        # final score is checkable on sight; one carrying only a margin
        # requires trusting the convention under test.
        home_score, away_score = order.get("home_score"), order.get("away_score")
        score = (
            f" score={order.get('away_name') or order.get('away_team')} {away_score}"
            f" - {home_score} {order.get('home_name') or order.get('home_team')}"
            if home_score is not None and away_score is not None
            else " score=<not_recorded>"
        )
        print(
            f"[paper_settlement] GRADE_AUDIT market={order.get('market')}"
            f" bet_side={order.get('side')!r} bet_line={line_used}"
            f"{score}"
            f" margin_used={margin} must_beat={threshold}"
            f" our_verdict={order.get('outcome')} if_inverted={inverted}"
            f" pnl={order.get('pnl_dollars')}",
            flush=True,
        )

    # THE DISPLAY LIMIT, STATED. `audited=25 of=79 skipped={}` is literally
    # true and reads as "54 rows were refused without a reason" -- when in fact
    # they were never examined, because `orders[:limit]` stopped first. A bound
    # on coverage that does not announce itself makes a partial audit look like
    # a complete one, which is the same failure as an unnamed skip wearing
    # better clothes.
    not_examined = max(0, len(orders) - int(limit))
    print(
        f"[paper_settlement] GRADE_AUDIT_SUMMARY date={normalized} audited={rows}"
        f" of={len(orders)} skipped={skipped}"
        f" not_examined={not_examined}{f' (display limit={int(limit)})' if not_examined else ''}"
        " -- CHECK ONE ROW BY HAND: margin_used must be the BET TEAM's score"
        " minus its opponent's, and our_verdict must be `won` exactly when"
        " margin_used > must_beat",
        flush=True,
    )
    return {"status": "ok", "rows": rows, "candidates": len(orders), "skipped": skipped}


def _default_resolver(selected_date: str):
    """One resolver per sport, dispatched by the order's own `sport`.

    Built lazily and cached, so a slate with no WNBA never reads a WNBA
    artifact and a slate with no MLB never touches a schedule. Each sport's
    failure is its own: an unavailable WNBA box must not stop MLB grading, which
    is why each is constructed inside its own guard.

    A sport with no resolver returns a NAMED reason rather than nothing, so the
    ungraded counts stay a work list rather than a mystery.
    """
    builders = {
        "mlb": lambda: _build("syndicate.features.shared.bet_status_mlb", "mlb_status_resolver", selected_date),
        "wnba": lambda: _build("syndicate.features.shared.bet_status_wnba", "wnba_status_resolver", selected_date),
        # `#547`. Soccer orders returned `no_resolver_for_soccer` FOREVER --
        # 0 settled all-time on 2026-08-25 while the board was ~97% soccer by
        # row count. Game lines only; the resolver's docstring states why props
        # refuse (the live-state capture is capped at 12 players per match, so
        # an absent player is not a zero).
        "soccer": lambda: _build("syndicate.features.shared.bet_status_soccer", "soccer_status_resolver", selected_date),
        # Same shape as `#547` above, one sport over. Measured 2026-08-28T02:50Z:
        # `SETTLED date=2026-08-28 orders=21 graded=0` with
        # `no_resolver_for_nfl: 6` -- 29% of the slate, and NFL was the only
        # sport producing orders with no resolver at all. Game lines and totals;
        # the resolver's docstring states why props refuse (the scoreboard
        # capture carries team scores and nothing per-player).
        "nfl": lambda: _build("syndicate.features.shared.bet_status_nfl", "nfl_status_resolver", selected_date),
        # Wired BEFORE the volume lands, which is the only time this is
        # cheap. NCAAF reaches the board today (2026-08-28T02:10Z: kalshi
        # offered 524 ncaaf quotes, 52 selected) but its orders have not
        # reached the ledger, so `no_resolver_for_ncaaf` never showed up in
        # a counter -- unlike soccer and NFL, which were each found only
        # after months of ungradeable bets. The join is registry-backed and
        # NOT `teams_match`: see `bet_status_ncaaf` on why a prefix rule
        # turns "Michigan" into "Michigan State".
        "ncaaf": lambda: _build("syndicate.features.shared.bet_status_ncaaf", "ncaaf_status_resolver", selected_date),
    }
    cache: dict[str, Any] = {}

    def resolve(order):
        sport = str(order.get("sport") or "").strip().lower()
        builder = builders.get(sport)
        if builder is None:
            return {"unavailable_reason": f"no_resolver_for_{sport or 'unknown_sport'}"}
        if sport not in cache:
            cache[sport] = builder()
        resolver = cache[sport]
        if resolver is None:
            return {"unavailable_reason": f"resolver_unavailable_for_{sport}"}
        return resolver(order)

    return resolve


def _build(module_name: str, factory_name: str, selected_date: str):
    """Import and construct one sport's resolver, or None. Never raises."""
    try:
        import importlib

        return getattr(importlib.import_module(module_name), factory_name)(selected_date)
    except Exception:
        return None


# THE TWO BOOKS IN THE LEDGER, AND WHY A TOTAL MAY NOT SPAN THEM.
#
# `paper2` writes its venue-restricted orders into the SAME ledger as the
# unrestricted portfolio, distinguished only by `venue`:
#
#   paper            the unrestricted portfolio -- THE book
#   paper:<venue>    the same rows scoped to one venue, RE-PRICED and RE-SIZED
#   <venue>          real money, no prefix (`execute_portfolio.PAPER_VENUE`)
#
# `portfolio_commit` builds each venue book as
# `commit_portfolio(scope_rows_to_venue(rows, venue))` -- a SUBSET of the very
# rows the unrestricted plan was built from. So one decision on one game can
# appear as up to five orders, and summing them counts the same judgement five
# times.
#
# MEASURED 2026-08-25 14:09:04Z, which is what this fixes:
#
#   PNL all_time settled=181 staked=$1078.52 pnl=$16.7 roi=1.55%
#     by_venue=[('kalshi', 2, 0.01), ('paper', 95, -26.31),
#               ('paper:kalshi', 33, 25.96), ('paper:novig', 13, 19.07),
#               ('paper:polymarket', 15, 14.88), ('paper:prophetx', 23, -16.91)]
#
# 95 unrestricted orders and 84 venue-scoped ones over the same board, summed
# into "181 settled" and "$1,078.52 staked". Neither number describes any book
# anyone could have held.
#
# `portfolio_plan_path_for_venue`'s own docstring already names this hazard as
# the reason the PLANS are separate files -- "Stage C's per-market aggregates
# would silently mix a best-book book with a Kalshi-only one" -- and then the
# summary re-merged them. `order_clv` reached the same conclusion from the CLV
# side and states the rule this now follows: "a number that does not know which
# book it is about is not a measurement."
#
# So `total` describes the PORTFOLIO book only, `comparison_total` the
# venue-scoped shadow books, and they are never added. The comparison is the
# whole point of paper2 and it survives -- it just stops being laundered into
# one headline.
BOOK_PORTFOLIO = "portfolio"
BOOK_VENUE_COMPARISON = "venue_comparison"


def book_of(order: Mapping[str, Any]) -> str:
    """Which book an order belongs to, from its venue name.

    The `paper:` prefix is `execute_portfolio`'s own marker for a scoped shadow
    book (`venue = f"{venue}:{scope}"`, paper mode only -- live mode uses the
    bare venue). Keyed on that prefix rather than on a list of venue names so a
    venue added to `paper2_venues()` is classified correctly the day it appears,
    with no second place to update.
    """
    venue = str(order.get("venue") or "")
    return BOOK_VENUE_COMPARISON if venue.startswith("paper:") else BOOK_PORTFOLIO


def _aggregate(buckets: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Sum a set of per-venue buckets into one book's numbers.

    Extracted so the portfolio total and the comparison total cannot drift into
    two slightly different definitions of ROI -- which is how the pooled number
    survived review in the first place.
    """
    out = {
        "orders": sum(int(b.get("orders") or 0) for b in buckets),
        "settled": sum(int(b.get("settled") or 0) for b in buckets),
        "pending": sum(int(b.get("pending") or 0) for b in buckets),
        "unknown": sum(int(b.get("unknown") or 0) for b in buckets),
        "won": sum(int(b.get("won") or 0) for b in buckets),
        "lost": sum(int(b.get("lost") or 0) for b in buckets),
        "push": sum(int(b.get("push") or 0) for b in buckets),
        "staked_dollars": round(sum(float(b.get("staked_dollars") or 0.0) for b in buckets), 2),
        "pnl_dollars": round(sum(float(b.get("pnl_dollars") or 0.0) for b in buckets), 2),
    }
    out["roi_pct"] = (
        round(100.0 * out["pnl_dollars"] / out["staked_dollars"], 2)
        if out["staked_dollars"] > 0
        else None
    )
    decided = out["won"] + out["lost"]
    out["win_pct"] = round(100.0 * out["won"] / decided, 2) if decided else None
    return out


def settlement_summary(
    selected_date: str | None = None, *, orders: Sequence[Mapping[str, Any]] | None = None
) -> dict[str, Any]:
    """How the book actually did, per venue and overall.

    Percentages are omitted rather than shown as 0 when nothing is graded: a
    0.0% ROI on zero settled bets and a 0.0% ROI on fifty are the same string
    and opposite facts.
    """
    from syndicate.features.shared.execution_ledger import _load
    from syndicate.features.shared.execution_guard import is_non_position

    rows = list(orders) if orders is not None else (_load().get("orders") or [])
    if selected_date:
        rows = [o for o in rows if o.get("selected_date") == str(selected_date)]

    by_venue: dict[str, dict[str, Any]] = {}
    for order in rows:
        venue = str(order.get("venue") or "unknown")
        bucket = by_venue.setdefault(
            venue,
            {"venue": venue, "orders": 0, "settled": 0, "won": 0, "lost": 0, "push": 0,
             "staked_dollars": 0.0, "pnl_dollars": 0.0, "pending": 0, "unknown": 0},
        )
        bucket["orders"] += 1
        outcome = str(order.get("outcome") or "")
        if not outcome:
            # THREE STATES, NOT TWO, AND THE THIRD USED TO VANISH.
            #
            # `pending` counted only `status == "filled"`, so an undecided row
            # that is NOT filled fell out of both buckets and out of the tile.
            # Measured on the live book 2026-08-28T02:1xZ: 89 positions, but
            # 31W + 33L + 7P + 16 pending = 87. The missing two were Polymarket
            # orders with `status=failed` -- a submit that ERRORED without the
            # venue answering, which may well have landed.
            #
            # Neither existing bucket is honest about those. Calling them
            # `pending` asserts we hold a position; dropping them asserts we do
            # not; and they are exactly the rows a person must check at the
            # venue before placing anything else. So they get their own counter
            # and the page states it.
            #
            # THE REFUSAL RULE IS THE SHARED ONE. `execution_guard.
            # _is_venue_refusal` is what the page and the day-budget already use
            # to decide "never a position" -- a fourth definition here is how
            # these totals drift apart again. A row the VENUE answered with a
            # 4xx is genuinely not a position and stays counted in `orders`
            # only.
            if str(order.get("status") or "") == "filled":
                bucket["pending"] += 1
            elif not is_non_position(order):
                bucket["unknown"] += 1
            continue
        bucket["settled"] += 1
        bucket[outcome] = bucket.get(outcome, 0) + 1
        bucket["staked_dollars"] += _as_float(order.get("fill_stake_dollars")) or 0.0
        bucket["pnl_dollars"] += _as_float(order.get("pnl_dollars")) or 0.0

    for bucket in by_venue.values():
        bucket["staked_dollars"] = round(bucket["staked_dollars"], 2)
        bucket["pnl_dollars"] = round(bucket["pnl_dollars"], 2)
        # ROI on SETTLED stake only. Including pending stake would dilute the
        # number with bets that have not happened yet.
        bucket["roi_pct"] = (
            round(100.0 * bucket["pnl_dollars"] / bucket["staked_dollars"], 2)
            if bucket["staked_dollars"] > 0
            else None
        )
        decided = bucket["won"] + bucket["lost"]
        bucket["win_pct"] = round(100.0 * bucket["won"] / decided, 2) if decided else None

    # ONE BOOK PER TOTAL. See `book_of` above for the measurement that forced
    # this: summing `paper` with `paper:kalshi` and friends counted the same
    # decision up to five times and reported it as one portfolio.
    portfolio_rows = [o for o in rows if book_of(o) == BOOK_PORTFOLIO]
    comparison_rows = [o for o in rows if book_of(o) == BOOK_VENUE_COMPARISON]
    portfolio_venues = {str(o.get("venue") or "unknown") for o in portfolio_rows}
    total = _aggregate([b for v, b in by_venue.items() if v in portfolio_venues])
    comparison_total = _aggregate(
        [b for v, b in by_venue.items() if v not in portfolio_venues]
    )

    return {
        "selected_date": selected_date,
        # THE PORTFOLIO BOOK, and nothing else. `paper` plus any real-money
        # venue -- the bets a person could actually have held.
        "total": total,
        # The venue-scoped shadow books, reported BESIDE the portfolio and never
        # added to it. This is paper2's comparison and it is still here; it just
        # no longer contributes to a headline that would double-count it.
        "comparison_total": comparison_total,
        # Named counts, so a reader can see the overlap that used to be summed
        # rather than having to derive it from two totals.
        "books": {
            BOOK_PORTFOLIO: {"orders": len(portfolio_rows),
                             "venues": sorted(portfolio_venues)},
            BOOK_VENUE_COMPARISON: {"orders": len(comparison_rows),
                                    "venues": sorted(
                                        {str(o.get("venue") or "unknown") for o in comparison_rows}
                                    )},
        },
        "by_venue": [by_venue[k] for k in sorted(by_venue)],
        # TWO MORE CUTS, because `by_venue` alone cannot answer the question it
        # raises. MEASURED 2026-08-24: the unrestricted `paper` book returned
        # -4.25% while four of five venue-scoped books were positive -- and a
        # venue label cannot distinguish the two explanations for that:
        #
        #   A. BEST-OF-N EV INFLATION. The unrestricted board prices at the
        #      best book across N and computes `ev_pct` against it, so a single
        #      stale or erroneous quote inflates the edge and admits a row whose
        #      true edge is ~0. `venue_scope` REPRICES at the venue's own quote
        #      and re-runs the same min-EV gate, so those rows never enter a
        #      venue book. That would make the loss a selection artefact.
        #
        #   B. COMPOSITION. The automatable venues quote mostly moneyline,
        #      spread and total on major games, while the props the sim is
        #      built around are largely absent from them (`venue_scope`'s own
        #      docstring, and 95.5% of the OddsAPI spend). So the unrestricted
        #      book is prop-heavy and the venue books are game-line-heavy, and
        #      "the unrestricted book loses" could simply be "props lose"
        #      wearing a venue label.
        #
        # A and B need opposite fixes -- tighten the price gate, or stop betting
        # a market family -- so guessing between them is expensive. Splitting by
        # market family and by sport separates them in one reading.
        #
        # NOTE the price cannot be the cause either way: the unrestricted book
        # is PAID at the best-book price it was sized against, and a better
        # price cannot lose money on a wager it wins. Whatever is happening is
        # about WHICH bets are taken, not what they were booked at.
        # PORTFOLIO ROWS ONLY. These two cuts key on market and sport with no
        # venue in the key, so over the full ledger they pooled the unrestricted
        # book with its own venue-scoped copies -- the same double-count as the
        # old `total`, one level down and harder to see. `by_venue_family` below
        # carries the venue IN its key and is therefore safe over everything,
        # which is exactly why it stays unscoped and these two do not.
        "by_market_family": _grouped(portfolio_rows, _market_family),
        "by_sport": _grouped(portfolio_rows, lambda o: str(o.get("sport") or "unknown")),
        # THE CROSS, which is the cut that actually decides between A and B.
        # `by_market_family` alone cannot: if the unrestricted book is
        # prop-heavy and the venue books are game-line-heavy, then a bad
        # `player_prop` number is consistent with BOTH explanations -- with A
        # if props are where the best-of-N inflation lands, and with B if props
        # are simply a losing family everywhere. Holding the family fixed and
        # varying the venue separates them in one reading:
        #
        #   paper/game_line vs kalshi/game_line differing  -> A (repricing)
        #   both game_line books agreeing, props differing -> B (composition)
        #
        # Same bucket shape as the other cuts, so the numbers are directly
        # comparable rather than three slightly different questions.
        "by_venue_family": _grouped(rows, _venue_family),
        # WHO DECIDED THE OUTCOME. Portfolio rows only, for the same reason
        # `by_market_family` and `by_sport` are: this key carries no venue, so
        # over the full ledger it would pool the unrestricted book with its own
        # venue-scoped copies.
        #
        # `total` deliberately still covers the whole book -- it is the honest
        # answer to "how has this done" and removing it would be a different
        # lie. What changes is that the blend is no longer the ONLY number
        # available, so a reader can attribute it. See `_settlement_authority`.
        "by_settled_by": _grouped(portfolio_rows, _settlement_authority),
    }


# ---------------------------------------------------------------------------
# HOW MUCH SETTLED EVIDENCE, WHICH IS NOT HOW MANY SETTLED ORDER ROWS
# ---------------------------------------------------------------------------


def settled_decisions_by_sport(
    orders: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, int]:
    """Distinct settled DECISIONS per sport. The credibility sample size.

    THE POPULATION, stated because two numbers in this system are both called
    "settled by sport" and they are not the same number:

        every mode (paper AND live), every venue in the PORTFOLIO book,
        every date, counted once per DECISION -- not once per order row.

    `settlement_summary(...)["by_sport"]` is the other one. It is a row count,
    which is right for a P&L page and wrong here, and on `/portfolio/paper` it
    is additionally scoped to paper-mode rows by that page's own live-order
    filter. Reading it as this number is what this function exists to stop.
    Both facts are pinned by `tests/test_settled_sample_credibility.py`.

    -----------------------------------------------------------------------
    WHY ROWS ARE THE WRONG UNIT, MEASURED
    -----------------------------------------------------------------------

    `_sample_credibility` asks "how much settled evidence do we have about this
    sport's edge" and divides by 50. Evidence means independent trials. The
    same bet placed at Kalshi AND at Polymarket is TWO ORDER ROWS and ONE
    Bernoulli trial -- the game resolves once, so the two rows cannot disagree.

    Measured on the production ledger 2026-09-04, 979 settled portfolio-book
    rows, all dates:

        sport    settled rows    distinct decisions
        mlb      865             684
        wnba      66              59
        soccer    30              28
        nfl       18              12   <- 6 pairs, every pair identical W/L

    NFL is why this matters and it is not a rounding argument: 18 rows put
    credibility at 0.36, and 12 decisions put it at the 0.25 FLOOR (12/50 =
    0.24). The row count was buying a 44% larger NFL stake with duplicates.

    This is the same doctrine `book_of` already encodes one level up -- summing
    `paper` with `paper:kalshi` and friends "counted the same decision up to
    five times and reported it as one portfolio". The venue-scoped shadow books
    were the visible case; two live venues quoting one market is the same error
    inside the portfolio book, and no venue label separates them.

    -----------------------------------------------------------------------
    THE IDENTITY IS BORROWED, NOT REBUILT
    -----------------------------------------------------------------------

    `clv_position_join.market_key` already strips the bookmaker component off
    an `opening_key`, and its own comment gives the reason to reuse it: "a
    hand-rebuilt market key is how you get two functions that agree on every
    row you tested and disagree on the one you did not." So the decision
    identity here IS that key -- `event_id|market|player|segment|side|line`.

    A row with no `opening_key` is re-derived through `opening_key_for_position`
    rather than dropped. A row that cannot be keyed AT ALL falls back to its own
    `idempotency_key`, i.e. it counts as its own decision: an unkeyable row is
    evidence we cannot dedupe, and dropping it would UNDERSTATE the sample,
    which is the direction that silently re-floors a sport.

    -----------------------------------------------------------------------
    SUMMED ON COLLISION, NEVER OVERWRITTEN
    -----------------------------------------------------------------------

    Sport labels are lowercased to match the consumption site
    (`str(row.get("sport")).strip().lower()`). Every ledger row measured
    2026-09-04 was already lowercase (596 live + 1,847 paper), so this is
    latent rather than live -- but the previous implementation assigned rather
    than merged, so a future `"NFL"` beside an `"nfl"` would have silently
    DISCARDED one of them. A sport is free text; it will happen eventually.

    `unknown` is excluded: it is a failed sport join, not a sport, and letting
    it collect rows would credential nothing at all.
    """
    from syndicate.features.shared.clv_position_join import (
        market_key,
        opening_key_for_position,
    )
    from syndicate.features.shared.execution_ledger import _load

    rows = list(orders) if orders is not None else (_load().get("orders") or [])

    def _decision(order: Mapping[str, Any]) -> str:
        raw = order.get("opening_key")
        if not (isinstance(raw, str) and raw.strip()):
            try:
                raw = opening_key_for_position(order)
            except Exception:  # noqa: BLE001
                raw = None
        key = market_key(raw) if raw else None
        if key:
            return key
        # Unkeyable. Its own identity, so it counts once and is never merged
        # with an unrelated row that is also unkeyable.
        return "idempotency_key=%s" % str(order.get("idempotency_key") or id(order))

    seen: dict[str, set[str]] = {}
    for order in rows:
        if not isinstance(order, Mapping):
            continue
        if book_of(order) != BOOK_PORTFOLIO:
            continue
        if not str(order.get("outcome") or ""):
            continue
        sport = str(order.get("sport") or "").strip().lower()
        if not sport or sport == "unknown":
            continue
        seen.setdefault(sport, set()).add(_decision(order))
    return {sport: len(keys) for sport, keys in seen.items() if keys}


# ---------------------------------------------------------------------------
# ROI BY THE SIM'S OWN VERDICT
# ---------------------------------------------------------------------------

# An order placed before `cb223b62`, which is when `sim_view` began being
# recorded. DISTINCT FROM `"none"`, which is the sim being ASKED and having no
# view -- collapsing the two would silently pool every pre-2026-09-03 bet into a
# verdict bucket and report the result as a finding about the sim. The
# parentheses guarantee no collision: every real verdict is a bare identifier.
SIM_VIEW_UNRECORDED = "(unrecorded)"

# WHICH VERDICTS CAN REACH AN ORDER AT ALL. Measured 2026-09-03 by running
# `commit_portfolio` over one row per verdict at ev_pct 1/5/20/100 (lane
# `order-sim-view`). This is a property of the COMMIT GATE, not of this module,
# and it is published in the response because a reader who does not know it will
# read four permanently-absent buckets as a broken join.
#
# These four are exactly the verdicts computed in the branch where
# `model_edge_pct is None`, and `sizing_inputs_from_row` refuses that row by name
# (`no_model_edge_pct`) before anything is sized, at every EV. So the
# `contradicts`-vs-`agrees` split that `layer2-sim-disagrees` pre-registered has
# a denominator that is structurally zero and stays zero however long this runs.
SIM_VIEW_UNREACHABLE = ("contradicts", "live_contradicts", "unpriced", "none")

# Placeable, but ONLY when the EV outruns the disagreement: the stake gates
# refuse `below_min_stake` and then `zero_kelly_stake` as the sim's probability
# falls under the price's implied. Measured at -110: ev_pct 5 admits
# model_edge_pct -0.5, ev 10 admits -2.0, ev 20 admits -5.0, ev 40 admits -10.0.
# So these buckets are a BIASED SAMPLE -- systematically high-EV against the
# `agrees` buckets -- and a comparison that does not hold `ev_pct` fixed measures
# the EV gap and reports it as a sim effect. Said in the payload, because a
# number that needs a caveat and does not carry one gets quoted without it.
SIM_VIEW_EV_CONDITIONED = ("disagrees", "live_disagrees")


def sim_view_roi_summary(
    *,
    selected_dates=None,
    mode=None,
    orders=None,
):
    """Settled ROI split by the SIM'S VERDICT, within sport x market family.

    THE QUESTION THIS EXISTS FOR, pre-registered by `layer2-sim-disagrees`: does
    a row the sim CONTRADICTS settle worse than one it agrees with, held within
    a sport and a market family, with denominators reported? The book's own
    split (`game_line` +13.28% n=296 vs `game_total` -1.78% n=351) cannot answer
    it, because it is not decomposed by what the sim said.

    NO NEW ARITHMETIC. Buckets come from `_grouped`, the same function behind
    `by_market_family`, `by_sport` and `by_venue_family` -- so ROI here is the
    same ROI, `pnl / settled stake`, with the same three-way treatment of
    unsettled rows and the same `execution_guard.is_non_position` rule. This
    module already records what a second definition costs; a cut that cannot be
    compared to the cuts beside it is worth less than no cut.

    PORTFOLIO ROWS ONLY, AND THAT IS NOT OPTIONAL. This key carries NO VENUE, so
    over the full ledger it would pool the unrestricted book with its own
    venue-scoped shadow copies -- the double-count `by_market_family` and
    `by_sport` are already restricted for, one level down and harder to see.

    PERCENTAGES ARE `None`, NEVER `0.0`, WHEN NOTHING IS SETTLED. Inherited from
    `_grouped`: a 0.0% ROI on zero settled bets and a 0.0% ROI on fifty are the
    same string and opposite facts.
    """
    from syndicate.features.shared.execution_ledger import _load

    rows = list(orders) if orders is not None else (_load().get("orders") or [])
    if selected_dates is not None:
        keep = {str(d) for d in selected_dates}
        rows = [o for o in rows if str(o.get("selected_date") or "") in keep]
    if mode:
        want = str(mode).strip().lower()
        rows = [o for o in rows if str(o.get("mode") or "").strip().lower() == want]
    rows = [o for o in rows if book_of(o) == BOOK_PORTFOLIO]

    # The triple is captured AS the key is built rather than parsed back out of
    # it. A sport is free text, and a separator that "cannot appear" in one is a
    # bet this file does not need to take.
    labels = {}

    def _key(order):
        sport = str(order.get("sport") or "unknown").strip().lower() or "unknown"
        family = _market_family(order)
        raw = order.get("sim_view")
        verdict = str(raw).strip() if raw is not None and str(raw).strip() else SIM_VIEW_UNRECORDED
        key = f"{sport} | {family} | {verdict}"
        labels[key] = {"sport": sport, "market_family": family, "sim_view": verdict}
        return key

    buckets = _grouped(rows, _key)
    for bucket in buckets:
        bucket.update(labels.get(bucket["key"], {}))

    # THE SAME ROWS POOLED BY VERDICT ALONE. Offered BESIDE the cross and never
    # instead of it: pooling across sports and families is exactly the confound
    # the pre-registered measurement says to hold fixed, so this is an index,
    # not the answer. `_aggregate` is the shared roll-up, so these totals cannot
    # drift from the buckets they summarise.
    by_verdict = {}
    for bucket in buckets:
        by_verdict.setdefault(bucket.get("sim_view") or "unknown", []).append(bucket)
    pooled = []
    for verdict in sorted(by_verdict):
        rolled = _aggregate(by_verdict[verdict])
        rolled["sim_view"] = verdict
        rolled["ev_conditioned"] = verdict in SIM_VIEW_EV_CONDITIONED
        pooled.append(rolled)

    return {
        # THE CUT THE MEASUREMENT ASKED FOR: sport and family held fixed.
        "by_sport_family_verdict": buckets,
        # An index across them. Read the cross before quoting this.
        "by_verdict": pooled,
        # WHAT THE BUCKETS CANNOT SAY ABOUT THEMSELVES, and would be misread
        # without. Four verdicts are absent BY CONSTRUCTION rather than for want
        # of data, and one pair is present but selected on EV. A permanently
        # empty bucket and a not-yet-populated one look identical.
        "verdict_reachability": {
            "unreachable": list(SIM_VIEW_UNREACHABLE),
            "unreachable_reason": (
                "computed where model_edge_pct is None, which "
                "portfolio_commit.sizing_inputs_from_row refuses by name "
                "(no_model_edge_pct) before sizing, at every ev_pct. These "
                "buckets are structurally empty and stay empty; the "
                "contradicts-vs-agrees ROI split cannot be taken from this book."
            ),
            "ev_conditioned": list(SIM_VIEW_EV_CONDITIONED),
            "ev_conditioned_reason": (
                "placeable only when ev_pct outruns the disagreement (at -110: "
                "ev 5 admits model_edge_pct -0.5, ev 20 admits -5.0), so these "
                "buckets are systematically high-EV. Hold ev_pct fixed, or the "
                "comparison measures the EV gap rather than the sim."
            ),
            "unrecorded_bucket": SIM_VIEW_UNRECORDED,
            "unrecorded_reason": (
                "placed before sim_view was recorded (cb223b62). NOT the same "
                "as the verdict 'none', which is the sim answering."
            ),
        },
    }


def _venue_family(order: Mapping[str, Any]) -> str:
    """`<venue>/<market_family>` -- the cross, as one key.

    Slash-joined rather than a nested dict because `_grouped` is the thing that
    has already been checked against `by_venue`, and a second aggregation path
    would be a second place for the pending/settled rule to drift.
    """
    return f"{str(order.get('venue') or 'unknown')}/{_market_family(order)}"


def _market_family(order: Mapping[str, Any]) -> str:
    """`game_line`, `game_total` or `player_prop`.

    Three rather than two: a total is a scoreboard bet like a spread, but it
    needs no team resolution and is modelled completely differently, so folding
    it into either neighbour would blur the comparison this exists to make.
    """
    from syndicate.features.shared.game_line_bet import is_game_line_market

    sport = order.get("sport")
    market = str(order.get("market") or "").strip().lower()
    if is_game_line_market(sport, market):
        return "game_line"
    if market.startswith("totals") or market in {"total", "team_totals"}:
        return "game_total"
    return "player_prop"


def _settlement_authority(order: Mapping[str, Any]) -> str:
    """Who decided this outcome: the VENUE, or our own inference.

    `venue_settlement` stamps `settled_by: "venue"` on a row it grades from the
    venue's own settlement record. `paper_settlement` stamps nothing, so an
    absent field means this module graded it -- from a status WE resolved, via
    the boxscore feed, the team aliases and the over/under vocabulary.

    THESE ARE NOT THE SAME KIND OF NUMBER AND MUST NOT SHARE AN ROI.
    Measured 2026-08-26, the first evening both existed:

        venue      3 bets   -$1.45   ROI  -11.88%
        inferred  12 bets  +$15.05   ROI  +51.07%
        BLENDED   15 bets  +$13.60   ROI  +32.60%

    and +32.60% is the figure the page showed. n=3 proves nothing about which
    is right -- that is exactly why they have to be reported apart rather than
    averaged into a headline nobody can attribute. An evaluation pass that
    cannot tell an authoritative outcome from an inferred one is one that will
    eventually average them, which is what this key exists to prevent.
    """
    return "venue" if str(order.get("settled_by") or "") == "venue" else "inferred"


def _grouped(rows: Sequence[Mapping[str, Any]], key_fn) -> list[dict[str, Any]]:
    """Settled counts and money per group, in the same shape as `by_venue`.

    Unsettled rows are counted as `pending` and contribute NO money -- the same
    rule the venue breakdown uses, so the three cuts are directly comparable
    rather than three slightly different questions.
    """
    from syndicate.features.shared.execution_guard import is_non_position

    buckets: dict[str, dict[str, Any]] = {}
    for order in rows:
        try:
            key = str(key_fn(order) or "unknown")
        except Exception:
            key = "unknown"
        bucket = buckets.setdefault(
            key,
            {"key": key, "orders": 0, "settled": 0, "won": 0, "lost": 0, "push": 0,
             "staked_dollars": 0.0, "pnl_dollars": 0.0, "pending": 0, "unknown": 0},
        )
        bucket["orders"] += 1
        outcome = str(order.get("outcome") or "")
        if not outcome:
            # SAME THREE-WAY SPLIT AS `settlement_summary`, deliberately -- this
            # function's own docstring promises "the same rule the venue
            # breakdown uses, so the three cuts are directly comparable". See
            # there for why an unconfirmed submit is neither pending nor gone.
            if str(order.get("status") or "") == "filled":
                bucket["pending"] += 1
            elif not is_non_position(order):
                bucket["unknown"] += 1
            continue
        bucket["settled"] += 1
        bucket[outcome] = bucket.get(outcome, 0) + 1
        bucket["staked_dollars"] += _as_float(order.get("fill_stake_dollars")) or 0.0
        bucket["pnl_dollars"] += _as_float(order.get("pnl_dollars")) or 0.0

    for bucket in buckets.values():
        bucket["staked_dollars"] = round(bucket["staked_dollars"], 2)
        bucket["pnl_dollars"] = round(bucket["pnl_dollars"], 2)
        bucket["roi_pct"] = (
            round(100.0 * bucket["pnl_dollars"] / bucket["staked_dollars"], 2)
            if bucket["staked_dollars"] > 0
            else None
        )
        decided = bucket["won"] + bucket["lost"]
        bucket["win_pct"] = round(100.0 * bucket["won"] / decided, 2) if decided else None
    return [buckets[k] for k in sorted(buckets)]
