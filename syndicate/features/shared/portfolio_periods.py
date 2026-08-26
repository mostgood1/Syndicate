"""The book rolled up by day, month, and year.

[USER DECISION 2026-08-25] "We should be able to see a daily view (pivot on
date), a monthly view, and a yearly view."

PURE. Takes ledger rows, returns totals. No clock, no disk, no request -- which
is what lets the page, the API, and a test all ask the same question and get
the same answer.

--------------------------------------------------------------------------
THE PERIOD KEY IS `selected_date`, NOT `submitted_at`
--------------------------------------------------------------------------

`selected_date` is the SLATE the bet belongs to, and it is already Central.
`submitted_at` is a UTC wall-clock stamp, so keying on it would put every
order placed after 7pm Central onto the NEXT day's pivot -- splitting one
evening's slate across two rows and making a Monday total that contains half
of Monday and half of Sunday.

That is the same defect the live portfolio's time column had (it rendered a
raw slice of the UTC string, five hours off), and the same one
`central_date_from_iso` documents for WNBA card filtering. A rollup is exactly
where it would be least visible: nothing looks wrong about a number.

So the month and year keys are PREFIXES of the slate date -- `2026-08-25`
gives `2026-08` and `2026` -- with no timezone arithmetic anywhere in this
module, because there is no timezone question left to get wrong.

--------------------------------------------------------------------------
A REFUSED ORDER IS NOT A ROW
--------------------------------------------------------------------------

[USER DECISION 2026-08-25] Orders that did not complete "also should not count
against the number of orders."

Excluded by the SAME predicate the live page hides on and the day-budget
declines to charge for, imported rather than restated: three places deciding
independently what "an order that happened" means is three places that will
eventually disagree about the same row.

`failed` is deliberately NOT excluded on its own. A submit that timed out may
well have landed -- that gap is why the write-ahead record exists -- so only a
failure the venue ANSWERED (a 4xx) is certainly not a position. Counting a
possible fill as nothing is the error that matters here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

# The buckets, and the ONE place their names are written. A caller asking for
# "monthly" and a template reading `by_month` is the kind of drift that shows
# up as an empty table nobody can explain.
PERIODS = ("day", "month", "year")

_PERIOD_WIDTH = {"day": 10, "month": 7, "year": 4}


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def is_position(order: Mapping[str, Any]) -> bool:
    """Did this order open, or possibly open, a real position?

    The shared rule. `execution_guard._is_venue_refusal` draws the line for the
    day's budget and the live page hides on it; this reuses it so a row that is
    hidden is exactly a row that is not counted.
    """
    from syndicate.features.shared.execution_guard import _is_venue_refusal

    if str(order.get("status") or "") == "rejected":
        return False
    return not _is_venue_refusal(order)


def period_key(order: Mapping[str, Any], period: str) -> str:
    """The bucket this order belongs to, or "" if its slate date is unreadable.

    An order with no usable date is DROPPED rather than filed under a guess --
    a row in the wrong month is worse than a row that is visibly missing, and
    the caller reports the count.
    """
    date_text = str(order.get("selected_date") or "").strip()
    width = _PERIOD_WIDTH.get(period)
    if width is None or len(date_text) < width:
        return ""
    key = date_text[:width]
    # Cheap shape check: a slate date is digits and dashes. Anything else is
    # not a date and must not become a bucket heading.
    if not all(ch.isdigit() or ch == "-" for ch in key):
        return ""
    return key


def _empty_bucket(key: str) -> dict[str, Any]:
    return {
        "key": key,
        "orders": 0,
        "filled": 0,
        "pending": 0,
        "settled": 0,
        "won": 0,
        "lost": 0,
        "push": 0,
        "staked_dollars": 0.0,
        "settled_stake_dollars": 0.0,
        "pnl_dollars": 0.0,
        "venues": {},
    }


def _add(bucket: dict[str, Any], order: Mapping[str, Any]) -> None:
    bucket["orders"] += 1
    status = str(order.get("status") or "")
    stake = _as_float(order.get("fill_stake_dollars"))
    bucket["staked_dollars"] += stake

    venue = str(order.get("venue") or "unknown")
    venue_bucket = bucket["venues"].setdefault(venue, {"orders": 0, "staked_dollars": 0.0, "pnl_dollars": 0.0})
    venue_bucket["orders"] += 1
    venue_bucket["staked_dollars"] += stake

    if status == "filled":
        bucket["filled"] += 1

    outcome = str(order.get("outcome") or "")
    if not outcome:
        # OPEN, not zero. A filled bet with no graded outcome is money at risk
        # right now; folding it into "settled with 0 P&L" would make an
        # unresolved book look like a break-even one.
        if status == "filled":
            bucket["pending"] += 1
        return

    bucket["settled"] += 1
    if outcome in {"won", "lost", "push"}:
        bucket[outcome] += 1
    pnl = _as_float(order.get("pnl_dollars"))
    bucket["pnl_dollars"] += pnl
    bucket["settled_stake_dollars"] += stake
    venue_bucket["pnl_dollars"] += pnl


def _finalize(bucket: dict[str, Any]) -> dict[str, Any]:
    for field in ("staked_dollars", "settled_stake_dollars", "pnl_dollars"):
        bucket[field] = round(bucket[field], 2)
    for venue_bucket in bucket["venues"].values():
        venue_bucket["staked_dollars"] = round(venue_bucket["staked_dollars"], 2)
        venue_bucket["pnl_dollars"] = round(venue_bucket["pnl_dollars"], 2)

    # ROI ON SETTLED STAKE ONLY, and None rather than 0.0 when nothing is
    # graded. A 0.0% ROI on zero settled bets and a 0.0% ROI on fifty are the
    # same string and opposite facts -- `settlement_summary` makes the same
    # distinction, deliberately, and this matches it.
    settled_stake = bucket["settled_stake_dollars"]
    bucket["roi_pct"] = (
        round(100.0 * bucket["pnl_dollars"] / settled_stake, 2) if settled_stake > 0 else None
    )
    decided = bucket["won"] + bucket["lost"]
    bucket["win_pct"] = round(100.0 * bucket["won"] / decided, 2) if decided else None
    bucket["venues"] = dict(sorted(bucket["venues"].items()))
    return bucket


def period_rollup(orders: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Day, month, and year totals over one book.

    Each period is a list, NEWEST FIRST -- the row a person wants is today's,
    and a table that opens on January is a table they have to scroll.

    `undated` reports rows dropped for an unreadable slate date, so a pivot
    that is quietly missing bets says so on the page instead of just being
    short.
    """
    rows = [order for order in orders if isinstance(order, Mapping) and is_position(order)]

    buckets: dict[str, dict[str, dict[str, Any]]] = {period: {} for period in PERIODS}
    undated = 0
    for order in rows:
        keys = {period: period_key(order, period) for period in PERIODS}
        if not keys["day"]:
            # Dropped from EVERY period, not just the day: filing a row under a
            # month while it is missing from that month's days would make the
            # two views disagree and neither of them be wrong.
            undated += 1
            continue
        for period in PERIODS:
            key = keys[period]
            bucket = buckets[period].setdefault(key, _empty_bucket(key))
            _add(bucket, order)

    return {
        "by_day": [_finalize(b) for _, b in sorted(buckets["day"].items(), reverse=True)],
        "by_month": [_finalize(b) for _, b in sorted(buckets["month"].items(), reverse=True)],
        "by_year": [_finalize(b) for _, b in sorted(buckets["year"].items(), reverse=True)],
        "counted_orders": len(rows) - undated,
        "undated": undated,
    }
