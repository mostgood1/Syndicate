"""The book rolled up by day, month, year -- and by sport and bet type.

[USER DECISION 2026-08-25] "We should be able to see a daily view (pivot on
date), a monthly view, and a yearly view."

[USER DECISION 2026-08-28] "we need to start tracking bets by sport and by bet
type (this can be part of the area below the day/month/year selection)."

--------------------------------------------------------------------------
SPORT AND MARKET ARE THE SAME ROLLUP, NOT A SECOND ONE
--------------------------------------------------------------------------

`settlement_summary` already computes a `by_sport` and a `by_market_family`,
and they were the obvious place to put this. They are deliberately NOT what
the page shows below the period tabs, because they answer a different question
over a different population: that summary is scoped to the DATE SELECTION and
counts every order including the ones that never opened a position, so its
`mlb: orders 221` cannot be reconciled against a day row reading `orders 54`
by anybody looking at one screen.

Five pivots over ONE bucket builder means the sport rows sum to the day rows
sum to the year row, exactly, with no explanation needed. A reader who cannot
add up two tables on the same page stops trusting both.

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

# The non-date pivots, keyed off a field the order already carries rather than
# anything derived. Same reason the period keys are prefixes of `selected_date`:
# a rollup is exactly where a clever derivation is least visible when it is
# wrong, because nothing about a number looks broken.
#
# `market` IS the bet type -- `h2h`, `totals`, `batter_hits` -- and is used raw.
# Folding it into families (game line / game total / player prop) would answer
# a coarser question than the one asked, and `settlement_summary.
# by_market_family` already answers that one.
DIMENSIONS = ("sport", "market")

# An order whose dimension field is empty is filed under this rather than
# dropped. A dropped row would make the sport pivot silently short against the
# day pivot beside it, which is the one property this module is buying by
# sharing a bucket builder.
UNKNOWN_KEY = "(unspecified)"


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


def dimension_key(order: Mapping[str, Any], dimension: str) -> str:
    """The sport or market bucket this order belongs to.

    NEVER "" -- see `UNKNOWN_KEY`. `period_key` may return "" because a row with
    no readable slate date genuinely cannot be placed in time and the caller
    counts it as `undated`; a row with no sport is still a bet that happened,
    and hiding it would break the arithmetic these pivots exist to preserve.
    """
    value = str(order.get(dimension) or "").strip().lower()
    return value or UNKNOWN_KEY


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
        # SENT, NEVER ANSWERED. Not open and not settled -- see `_add`. Without
        # this the Orders column does not equal Open + Settled and nothing on
        # the page says why.
        "unknown": 0,
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
        else:
            # NOT FILLED, NOT REFUSED, NOT GRADED -- the row `is_position` keeps
            # because a 5xx submit may have landed. It is counted in `orders`
            # (it consumed the day's budget) and it is neither open nor settled,
            # so `orders != pending + settled` and the difference had no name.
            #
            # `[user 2026-08-28]` "yesterday has 2 positions that were errors
            # showing as an actual position." They were the two Polymarket
            # `http_503` submits of 2026-08-27. This is the column that says so.
            bucket["unknown"] += 1
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
    dims: dict[str, dict[str, dict[str, Any]]] = {name: {} for name in DIMENSIONS}
    undated = 0
    for order in rows:
        keys = {period: period_key(order, period) for period in PERIODS}
        if not keys["day"]:
            # Dropped from EVERY period, not just the day: filing a row under a
            # month while it is missing from that month's days would make the
            # two views disagree and neither of them be wrong.
            #
            # AND FROM THE SPORT AND MARKET PIVOTS TOO, for the same reason one
            # level up: `undated` is reported once, and a row present in the
            # sport table while absent from every date table would make the two
            # disagree with nothing on the page accounting for the difference.
            undated += 1
            continue
        for period in PERIODS:
            key = keys[period]
            bucket = buckets[period].setdefault(key, _empty_bucket(key))
            _add(bucket, order)
        for name in DIMENSIONS:
            key = dimension_key(order, name)
            bucket = dims[name].setdefault(key, _empty_bucket(key))
            _add(bucket, order)

    def _rows(table: dict[str, dict[str, Any]], *, newest_first: bool) -> list[dict[str, Any]]:
        if newest_first:
            # Dates: the row a person wants is today's, and a table that opens
            # on January is a table they have to scroll.
            ordered = sorted(table.items(), reverse=True)
        else:
            # Sport and market have no chronology, so alphabetical would put
            # `batter_hits` above `totals` on volume grounds nobody holds.
            # BIGGEST FIRST -- the pivot exists to answer "where is the book",
            # and the answer is the top row.
            ordered = sorted(table.items(), key=lambda kv: (-kv[1]["orders"], kv[0]))
        return [_finalize(b) for _, b in ordered]

    return {
        "by_day": _rows(buckets["day"], newest_first=True),
        "by_month": _rows(buckets["month"], newest_first=True),
        "by_year": _rows(buckets["year"], newest_first=True),
        "by_sport": _rows(dims["sport"], newest_first=False),
        "by_market": _rows(dims["market"], newest_first=False),
        "counted_orders": len(rows) - undated,
        "undated": undated,
    }
