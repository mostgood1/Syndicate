"""Mark placed orders against the CURRENT board -- how a pick is tracking, now.

A committed position answers "what did we take". Settlement answers "did it
win", hours or days later. Between those two there is a long stretch where the
only honest question is **has the market moved toward us or away from us**, and
nothing answered it: `/portfolio/paper` showed the price we took and then
nothing until the game ended.

That middle number is not a nice-to-have. It is the same quantity Stage C
gates on -- CLV is exactly this measured against the close instead of against
the current quote -- so a live mark is a running preview of the number that
decides whether a market ever gets real money. A pick drifting the wrong way
for three hours is knowable at hour one.

**LIKE FOR LIKE, OR NOT AT ALL.** The mark joins on `clv_opening_ledger`'s key,
which includes the bookmaker, so an order taken at BetMGM is re-priced against
BetMGM's current quote and never against whichever book happens to be best now.
The board publishes the BEST book's price; comparing our BetMGM entry to a
different book's current best would manufacture movement out of book disagreement
and read as a signal. When the book we used has stopped quoting, that is
`book_no_longer_quoting` -- a named absence, not a substituted price.

**AMERICAN ODDS ARE NOT LINEAR AND ARE NEVER SUBTRACTED HERE.** -110 to -130 and
+200 to +180 are not comparable as arithmetic, and a "price moved 20" column
would be wrong in both directions at once. Every movement number goes through
`clv_pct_from_prices`, which converts to probability points and is the SAME
function the CLV path uses -- one convention for one quantity, so this page can
never disagree with the ledger it previews.

WHY THE WORKER DOES THIS. Marking needs the current board, and the web service
does not compute -- a request handler indexing ~1,200 rows per pageview is the
recompute the architecture forbids. `run_portfolio_commit` already holds those
rows, so the marks cost one pass over data already in memory, land in the plan
artifact, and refresh on the same cadence the board does.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

__all__ = ["mark_orders_to_board", "marks_report_line"]

# Named reasons a mark could not be produced. Each is a different thing being
# absent, and collapsing them would hide which one -- the whole point of
# `clv_join`'s "an unresolved row is a datum, not a silent drop".
REASON_MARKED = "marked"
REASON_UNKEYABLE = "unkeyable"
REASON_BOOK_GONE = "book_no_longer_quoting"
REASON_NO_CURRENT_PRICE = "no_current_price"
REASON_NO_TAKEN_PRICE = "no_taken_price"


def _as_float(value: Any) -> float | None:
    if isinstance(value, str):
        value = value.strip().replace("+", "")
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return None if parsed != parsed else parsed


def _taken_price(order: Mapping[str, Any]) -> float | None:
    """The price this bet actually got.

    `fill_price` wins over `requested_price` when present, because the fill is
    what we hold. On a paper fill the two are equal; on a live one they are not,
    and marking against the request would quietly credit us with slippage we did
    not get.
    """
    filled = _as_float(order.get("fill_price"))
    return filled if filled is not None else _as_float(order.get("requested_price"))


def mark_orders_to_board(
    orders: Sequence[Mapping[str, Any]],
    rows: Sequence[Mapping[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Re-price each order against the board it was taken from. Counters, then marks.

    Returns a mark per order in `marks`, keyed by `idempotency_key`, plus totals
    that summarise which way the slate as a whole is moving.
    """
    from syndicate.features.shared.clv_join import clv_pct_from_prices
    from syndicate.features.shared.clv_position_join import (
        opening_key_for_position,
        opening_key_for_row,
    )

    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    marked_at = stamp.strftime("%Y-%m-%dT%H:%M:%SZ")

    by_key: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        key = opening_key_for_row(row)
        if key:
            by_key.setdefault(key, row)

    marks: list[dict[str, Any]] = []
    reasons: dict[str, int] = {}
    moved_toward = 0
    moved_against = 0
    clv_points: list[float] = []

    for order in orders:
        # The stamped key wins; the derivation covers orders placed before
        # `opening_key` was carried on the record at all.
        key = order.get("opening_key")
        key = key if isinstance(key, str) and key else opening_key_for_position(order)
        taken = _taken_price(order)

        def _mark(reason: str, **extra: Any) -> None:
            reasons[reason] = reasons.get(reason, 0) + 1
            marks.append(
                {
                    "idempotency_key": order.get("idempotency_key"),
                    "position_key": order.get("position_key"),
                    "opening_key": key,
                    "taken_price": taken,
                    "marked_at": marked_at,
                    "reason": reason,
                    **extra,
                }
            )

        if taken is None:
            _mark(REASON_NO_TAKEN_PRICE, current_price=None, clv_pct=None)
            continue
        if key is None:
            _mark(REASON_UNKEYABLE, current_price=None, clv_pct=None)
            continue
        row = by_key.get(key)
        if row is None:
            # The exact market at the exact book is not on the board right now.
            # Usually the book pulled the line or the game started.
            _mark(REASON_BOOK_GONE, current_price=None, clv_pct=None)
            continue
        quote = row.get("quote") if isinstance(row.get("quote"), Mapping) else {}
        current = _as_float((quote or {}).get("price"))
        if current is None:
            _mark(REASON_NO_CURRENT_PRICE, current_price=None, clv_pct=None)
            continue

        clv = clv_pct_from_prices(taken, current)
        if clv is not None:
            clv_points.append(clv)
            if clv > 0:
                moved_toward += 1
            elif clv < 0:
                moved_against += 1
        _mark(
            REASON_MARKED,
            current_price=current,
            current_book=(quote or {}).get("bookmaker"),
            clv_pct=clv,
        )

    marked = reasons.get(REASON_MARKED, 0)
    return {
        "marked_at": marked_at,
        "orders": len(orders),
        "board_rows": len(rows),
        "board_distinct_keys": len(by_key),
        "marked": marked,
        "reasons": dict(sorted(reasons.items())),
        "moved_toward": moved_toward,
        "moved_against": moved_against,
        # Unweighted, and labelled as such. A stake-weighted number is the one
        # that matters for the bankroll, but this one answers "is the model
        # picking spots the market agrees with", which is the question a live
        # page is being read to answer. Stage C does the weighted version
        # against the close, where it belongs.
        "avg_clv_pct": round(sum(clv_points) / len(clv_points), 4) if clv_points else None,
        "marks": marks,
    }


def marks_report_line(report: Mapping[str, Any]) -> str:
    """One log line. `logger.info` never reaches Render's collector -- print this."""
    return (
        "[position_marks] LIVE_MARKS"
        f" marked_at={report.get('marked_at')}"
        f" orders={report.get('orders')}"
        f" marked={report.get('marked')}"
        f" toward={report.get('moved_toward')}"
        f" against={report.get('moved_against')}"
        f" avg_clv_pct={report.get('avg_clv_pct')}"
        f" reasons={report.get('reasons')}"
    )
