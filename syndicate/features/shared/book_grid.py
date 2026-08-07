"""L1-A: the per-book price grid — every book as a column, not one "best" price.

S1 of `plan_layer2_north_star.md`. The reference surface is OddsJam's market
grid: one row per market instance, one COLUMN PER BOOK, best price highlighted,
with no-vig, width and an honest `updated` stamp.

**This adds no capture and no worker load.** It is a serve-time pivot over
`book_quotes`, which already holds every book. Measured 2026-08-07 on a real MLB
shard: 11 books captured, and 68.5% of selections quoted by 3+ of them — while
the board rendered a single best price and discarded the rest. That was a
presentation gap, not a data gap, which is why this is cheap.

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
It does not re-derive which prices are opposite sides of the same market.
`market_sides_for_quote` owns that rule and this calls it. The rule is not
cosmetic: spreads are SIGNED per side (home -1.5 pairs with away +1.5), h2h has
no line at all, and 3-way markets have a draw leg that must be included or the
"fair" price is wrong in the bettor's favour. Pairing on an equal line
manufactured **716 phantom arbitrages** out of bets that were not opposite sides
of anything (measured 2026-08-06; the honest count after correction was ~3).
One rule, one place.

It also does not filter by quality. This is a **Layer 1 research surface** — a
row that no strategy would ever bet still belongs here. Layer 2 is the shortlist;
this is the microscope.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

from syndicate.features.shared.odds_book_quotes import (
    _implied_probability,
    _line_value,
    market_sides_for_quote,
)

# The market instance, i.e. everything except which book quoted it and which
# side it is. Mirrors `market_sides_for_quote`'s own base tuple exactly -- if
# these two ever disagree, sides land in different grid rows and the grid
# silently under-reports book coverage.
_INSTANCE_FIELDS = ("sport", "kind", "event_id", "segment", "market", "player_name")

# How far behind the freshest quote on a market a "best" price may sit before it
# is labelled suspect. 15 minutes: long enough that ordinary pregame staggering
# between books does not trip it, short enough to catch a book that stopped
# updating hours ago and now looks like the best line on the board.
_STALE_BEST_LAG_SECONDS = 900.0


def _price(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _observed_at(row: Mapping[str, Any]) -> str:
    return str(row.get("book_updated_at") or row.get("snapshot_ts") or row.get("captured_at") or "")


def _age_seconds(stamp: str, *, now: datetime) -> float | None:
    if not stamp:
        return None
    try:
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return round(max(0.0, (now - when).total_seconds()), 1)


def _better(price: int, than: int | None) -> bool:
    """True when `price` pays the bettor more.

    Comparing raw American ints gets this right in both signs -- for positives
    the larger number, for negatives the one closer to zero -- which looks like
    it should need a branch and does not.
    """
    return than is None or price > than


def _freshest_per_book_side(rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """One quote per (book, side): the most recently observed.

    The shard is an append-only log for the whole day, so a naive pass mixes a
    pregame price with an eighth-inning one for the same book. Requiring
    simultaneity is what took a raw arbitrage count from 716 to ~3.
    """
    freshest: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        book = str(row.get("bookmaker") or "").strip()
        side = str(row.get("selection") or "").strip()
        if not book or not side or _price(row.get("price")) is None:
            continue
        key = (book, side)
        current = freshest.get(key)
        if current is None or _observed_at(row) >= _observed_at(current):
            freshest[key] = dict(row)
    return freshest


def build_book_grid(
    rows: Iterable[Mapping[str, Any]],
    *,
    now: datetime | None = None,
    max_rows: int | None = None,
) -> list[dict[str, Any]]:
    """Pivot raw `book_quotes` rows into per-market grid rows.

    Each returned row is one market instance carrying every book that quoted it
    and every side, plus the derived columns the reference surface shows.
    """
    now = now or datetime.now(timezone.utc)
    materialised = [row for row in rows or () if isinstance(row, Mapping)]

    # Group by market instance. `market_sides_for_quote` decides which LINES
    # belong together (mirrored for spreads, absent for h2h), so group only on
    # the base tuple here and let it resolve lines within the group.
    instances: dict[tuple[str, ...], list[Mapping[str, Any]]] = {}
    for row in materialised:
        if _price(row.get("price")) is None:
            continue
        key = tuple(str(row.get(field) or "") for field in _INSTANCE_FIELDS)
        instances.setdefault(key, []).append(row)

    grid: list[dict[str, Any]] = []
    for key, group in instances.items():
        # Within an instance, distinct line values can still be different market
        # instances (alternate lines). Anchor on each distinct line and let the
        # shared rule gather its sides.
        seen_anchors: set[float | None] = set()
        for anchor in group:
            line = _line_value(anchor)
            anchor_key = None if line is None else abs(line)
            if anchor_key in seen_anchors:
                continue
            seen_anchors.add(anchor_key)

            sides_rows = market_sides_for_quote(group, anchor)
            if not sides_rows:
                continue
            freshest = _freshest_per_book_side(sides_rows)
            if not freshest:
                continue

            side_names = sorted({side for _, side in freshest})
            books = sorted({book for book, _ in freshest})

            # per-book cell: {side: price}
            cells: dict[str, dict[str, Any]] = {}
            for (book, side), row in freshest.items():
                cells.setdefault(book, {})[side] = {
                    "price": _price(row.get("price")),
                    "line": row.get("line"),
                    "observed_at": _observed_at(row) or None,
                    "age_seconds": _age_seconds(_observed_at(row), now=now),
                }

            # best price per side, and the consensus it should be read against
            best: dict[str, dict[str, Any]] = {}
            consensus: dict[str, int | None] = {}
            for side in side_names:
                prices = [
                    (cells[book][side]["price"], book)
                    for book in books
                    if side in cells[book] and cells[book][side]["price"] is not None
                ]
                if not prices:
                    consensus[side] = None
                    continue
                top_price, top_book = prices[0]
                for price, book in prices[1:]:
                    if _better(price, top_price):
                        top_price, top_book = price, book
                mean_implied = sum(_implied_probability(p) for p, _ in prices) / len(prices)
                side_consensus = (
                    int(round(-100.0 * mean_implied / (1.0 - mean_implied)))
                    if mean_implied >= 0.5
                    else int(round(100.0 * (1.0 - mean_implied) / mean_implied))
                )
                consensus[side] = side_consensus

                # A best price far clear of consensus is usually a STALE line,
                # not an edge -- books stop updating at different times, so
                # freshest-per-book across an all-day log still sits a 1pm price
                # next to a 7pm one. Observed on the real 2026-07-29 shard:
                # draftkings +388 on a market whose consensus was +116.
                #
                # Layer 1 does not DROP it (this is the research surface; a
                # suspect price is a thing a researcher wants to see). It labels
                # it, so the UI can grey the cell instead of presenting a
                # six-hour-old number as the best available bet.
                best_cell = cells[top_book][side]
                best_age = best_cell.get("age_seconds")
                freshest_age = min(
                    (
                        cells[b][side]["age_seconds"]
                        for b in books
                        if side in cells[b] and cells[b][side].get("age_seconds") is not None
                    ),
                    default=None,
                )
                lag = (
                    round(best_age - freshest_age, 1)
                    if best_age is not None and freshest_age is not None
                    else None
                )
                best[side] = {
                    "price": top_price,
                    "bookmaker": top_book,
                    "books_quoting": len(prices),
                    "age_seconds": best_age,
                    "lag_behind_freshest_seconds": lag,
                    "edge_vs_consensus_pct": round(
                        (_implied_probability(side_consensus) - _implied_probability(top_price)) * 100, 2
                    ),
                    # Not "this is wrong" -- "do not read this as an edge without
                    # looking at when it was posted".
                    "suspect_stale": bool(lag is not None and lag > _STALE_BEST_LAG_SECONDS),
                }

            stamps = [c[s]["observed_at"] for c in cells.values() for s in c if c[s]["observed_at"]]
            newest = max(stamps) if stamps else None

            first = sides_rows[0]
            grid.append(
                {
                    "sport": key[0],
                    "kind": key[1],
                    "event_id": key[2],
                    "segment": key[3],
                    "market": key[4],
                    "player_name": key[5] or None,
                    "line": anchor.get("line"),
                    "home_team": first.get("home_team"),
                    "away_team": first.get("away_team"),
                    "commence_time": first.get("commence_time"),
                    "sides": side_names,
                    "books": books,
                    "books_quoting": len(books),
                    "cells": cells,
                    "best": best,
                    "consensus": consensus,
                    "updated_at": newest,
                    "age_seconds": _age_seconds(newest or "", now=now),
                }
            )

    # Widest grids first: a row quoted by eleven books is more useful than one
    # quoted by one, and it is the shape the reference surface leads with.
    grid.sort(key=lambda row: (-int(row.get("books_quoting") or 0), str(row.get("market") or "")))
    if max_rows is not None:
        return grid[: max(0, int(max_rows))]
    return grid


def book_grid_summary(grid: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Coverage of a built grid — what the board can actually show.

    Exists because "we render a grid now" is not the same claim as "the grid has
    books in it". A single-book row renders as an empty grid with one number and
    no no-vig, and that fraction is the honest measure of the surface.
    """
    rows = [row for row in grid or () if isinstance(row, Mapping)]
    widths = [int(row.get("books_quoting") or 0) for row in rows]
    books: set[str] = set()
    two_sided = 0
    suspect = 0
    for row in rows:
        books.update(str(book) for book in row.get("books") or ())
        if len(row.get("sides") or ()) >= 2:
            two_sided += 1
        if any((row.get("best") or {}).get(side, {}).get("suspect_stale") for side in row.get("sides") or ()):
            suspect += 1
    total = len(rows)
    return {
        "rows": total,
        "distinct_books": len(books),
        "books": sorted(books),
        "rows_with_3plus_books": sum(1 for width in widths if width >= 3),
        "rows_single_book": sum(1 for width in widths if width <= 1),
        "rows_two_sided": two_sided,
        "rows_with_suspect_best": suspect,
        "pct_3plus_books": round(100.0 * sum(1 for w in widths if w >= 3) / total, 1) if total else 0.0,
        "pct_two_sided": round(100.0 * two_sided / total, 1) if total else 0.0,
        "max_books_on_a_row": max(widths) if widths else 0,
        # NOTE on comparing to the 68.5% figure in plan_layer2_north_star.md 4:
        # that measured coverage per (event, market, SELECTION, line) -- one
        # entry per side. This measures it per MARKET INSTANCE, which merges
        # over/under into one row. Both are correct; they count different
        # things, and a lower number here is not a regression.
        "unit": "market_instance (sides merged), not per-selection",
    }
