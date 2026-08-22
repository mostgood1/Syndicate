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

**LIKE FOR LIKE, OR NOT AT ALL** -- but the JOIN and the COMPARISON are widened
and narrowed separately, and getting that backwards was this module's first bug.

An order taken at BetMGM must be re-priced against BetMGM, never against
whichever book happens to be best now; comparing to a different book would
manufacture movement out of book disagreement and read as signal. The first
version enforced that by joining on the full opening key, bookmaker included.
It measured `LIVE_MARKS orders=21 marked=0
reasons={'book_no_longer_quoting': 21}` -- every single order, one reason.

**Twenty-one identical reasons is a broken join, not twenty-one pulled lines.**
An opening is recorded per (market, book), but a BOARD row is one row per market
carrying whichever book is best AT THAT MOMENT. The instant the best book
rotates -- which is most of the time -- a bookmaker-bearing key stops matching
its own market. So the join now runs at MARKET level (`market_key`) and the
comparison re-narrows to our own book through `quote.book_prices`, which carries
our price at every book that quoted the side. `clv_join` already resolves the
close this way for the same reason, so this follows the existing convention
rather than inventing a second one.

The two failures are now DISTINCT, which is the whole point: the market is not
on the board at all (`market_not_on_board`) versus the market is there but our
book has stopped quoting it (`book_no_longer_quoting`). Collapsed into one
reason, a broken join is indistinguishable from a quiet slate -- and reads
entirely plausible on a page, which is how it would have survived.

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
REASON_MARKET_GONE = "market_not_on_board"
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
        market_key,
        opening_key_for_position,
        opening_key_for_row,
    )

    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    marked_at = stamp.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Indexed by MARKET, not by (market, book) -- see the note above.
    by_market: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        key = market_key(opening_key_for_row(row))
        if key:
            by_market.setdefault(key, row)

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
        # Carried on every mark, including the failures: "betmgm pulled" is
        # actionable and "book pulled" is not.
        taken_book = str(order.get("book") or "").strip().lower() or None

        def _mark(reason: str, **extra: Any) -> None:
            reasons[reason] = reasons.get(reason, 0) + 1
            marks.append(
                {
                    "idempotency_key": order.get("idempotency_key"),
                    "position_key": order.get("position_key"),
                    "opening_key": key,
                    "taken_price": taken,
                    "taken_book": taken_book,
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
        row = by_market.get(market_key(key))
        if row is None:
            # The market itself is off the board -- the game started, or the
            # candidate stopped clearing whatever gate put it there.
            _mark(REASON_MARKET_GONE, current_price=None, clv_pct=None)
            continue
        quote = row.get("quote") if isinstance(row.get("quote"), Mapping) else {}
        # RE-NARROW TO OUR OWN BOOK. The row's top-level `price` is the BEST
        # book's, which is not necessarily ours; using it would reintroduce
        # precisely the best-of-N selection effect the same-book rule exists to
        # avoid. `book_prices` is keyed by book name -- lowercased here because
        # the ledger stores our book lowercased and the board does not promise
        # to.
        our_book = taken_book or ""
        book_prices = (quote or {}).get("book_prices")
        current = None
        if isinstance(book_prices, Mapping) and our_book:
            for name, price in book_prices.items():
                if str(name).strip().lower() == our_book:
                    current = _as_float(price)
                    break
        if current is None:
            # The market is on the board and our book is not quoting it. This
            # is the reason the old code reported for everything, and it is now
            # narrow enough to mean something.
            _mark(REASON_BOOK_GONE, current_price=None, clv_pct=None)
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
            current_book=our_book,
            clv_pct=clv,
        )

    marked = reasons.get(REASON_MARKED, 0)
    return {
        "marked_at": marked_at,
        "orders": len(orders),
        "board_rows": len(rows),
        "board_distinct_markets": len(by_market),
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
