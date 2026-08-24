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

    for order in orders:
        if order.get("outcome"):
            already += 1
            continue
        if str(order.get("status") or "") != "filled":
            _refuse(REASON_NOT_FILLED)
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

    total = {
        "orders": sum(b["orders"] for b in by_venue.values()),
        "settled": sum(b["settled"] for b in by_venue.values()),
        "pending": sum(b["pending"] for b in by_venue.values()),
        "won": sum(b["won"] for b in by_venue.values()),
        "lost": sum(b["lost"] for b in by_venue.values()),
        "push": sum(b["push"] for b in by_venue.values()),
        "staked_dollars": round(sum(b["staked_dollars"] for b in by_venue.values()), 2),
        "pnl_dollars": round(sum(b["pnl_dollars"] for b in by_venue.values()), 2),
    }
    total["roi_pct"] = (
        round(100.0 * total["pnl_dollars"] / total["staked_dollars"], 2)
        if total["staked_dollars"] > 0
        else None
    )
    decided = total["won"] + total["lost"]
    total["win_pct"] = round(100.0 * total["won"] / decided, 2) if decided else None

    return {
        "selected_date": selected_date,
        "total": total,
        "by_venue": [by_venue[k] for k in sorted(by_venue)],
    }
