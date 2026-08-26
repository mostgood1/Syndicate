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
from datetime import datetime, timezone
from typing import Any

__all__ = [
    "american_profit",
    "grade_order",
    "settle_orders",
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

        try:
            resolved = resolver(order) or {}
        except Exception as exc:
            _refuse(f"resolver_error:{type(exc).__name__}")
            continue
        if resolved.get("unavailable_reason"):
            # The feed's own vocabulary, passed through rather than flattened:
            # `no_game_pk`, `no_feed` and `no_stat` are three different jobs.
            reason = str(resolved["unavailable_reason"])
            _refuse(reason, order.get("market") if reason == "unmapped_market" else None)
            continue

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
            _refuse(str(status["unavailable_reason"]))
            continue

        verdict = grade_order(order, status)
        if not verdict.get("graded"):
            _refuse(str(verdict.get("reason")))
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
        f" ungraded={reasons}",
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
    }


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

    rows = list(orders) if orders is not None else (_load().get("orders") or [])
    if selected_date:
        rows = [o for o in rows if o.get("selected_date") == str(selected_date)]

    by_venue: dict[str, dict[str, Any]] = {}
    for order in rows:
        venue = str(order.get("venue") or "unknown")
        bucket = by_venue.setdefault(
            venue,
            {"venue": venue, "orders": 0, "settled": 0, "won": 0, "lost": 0, "push": 0,
             "staked_dollars": 0.0, "pnl_dollars": 0.0, "pending": 0},
        )
        bucket["orders"] += 1
        outcome = str(order.get("outcome") or "")
        if not outcome:
            if str(order.get("status") or "") == "filled":
                bucket["pending"] += 1
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


def _grouped(rows: Sequence[Mapping[str, Any]], key_fn) -> list[dict[str, Any]]:
    """Settled counts and money per group, in the same shape as `by_venue`.

    Unsettled rows are counted as `pending` and contribute NO money -- the same
    rule the venue breakdown uses, so the three cuts are directly comparable
    rather than three slightly different questions.
    """
    buckets: dict[str, dict[str, Any]] = {}
    for order in rows:
        try:
            key = str(key_fn(order) or "unknown")
        except Exception:
            key = "unknown"
        bucket = buckets.setdefault(
            key,
            {"key": key, "orders": 0, "settled": 0, "won": 0, "lost": 0, "push": 0,
             "staked_dollars": 0.0, "pnl_dollars": 0.0, "pending": 0},
        )
        bucket["orders"] += 1
        outcome = str(order.get("outcome") or "")
        if not outcome:
            if str(order.get("status") or "") == "filled":
                bucket["pending"] += 1
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
