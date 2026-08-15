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


def _seen_age_seconds(
    row: Mapping[str, Any], last_seen: Mapping[str, str] | None, *, now: datetime
) -> float | None:
    """Seconds since we last OBSERVED this market, or None when unknown.

    None is a real answer here and must not collapse to the movement age: dates
    whose state file predates last-seen tracking have no entry, and reporting
    the movement age in its place would recreate the exact confusion this field
    exists to end.
    """
    if not last_seen:
        return None
    try:
        from syndicate.features.shared.odds_book_quotes import quote_key
    except Exception:
        return None
    stamp = last_seen.get(quote_key(row))
    return _age_seconds(str(stamp or ""), now=now)


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


def _duration(seconds: float | None) -> str:
    """Human duration for a UI reason string. '4h 12m', not '15120.0'."""
    if seconds is None:
        return "unknown"
    total = int(seconds)
    if total < 60:
        return f"{total}s"
    if total < 3600:
        return f"{total // 60}m"
    hours, remainder = divmod(total, 3600)
    minutes = remainder // 60
    return f"{hours}h {minutes}m" if minutes else f"{hours}h"


def _better(price: int, than: int | None) -> bool:
    """True when `price` pays the bettor more.

    Comparing raw American ints gets this right in both signs -- for positives
    the larger number, for negatives the one closer to zero -- which looks like
    it should need a branch and does not.
    """
    return than is None or price > than


def _canonical_line(row: Mapping[str, Any]) -> float | None:
    """The market instance's line, stated from ONE perspective (away / over).

    #262. Spreads are signed per side, so `away +1.5` + `home -1.5` is one
    market and `away -1.5` + `home +1.5` is a DIFFERENT one. The previous anchor
    key was `abs(line)`, which gave both the same key -- so the two instances
    collapsed into a single row whose sides came from whichever quote happened to
    be freshest, and the second instance never got a row at all.

    Normalising to the away/over side makes the two distinguishable and makes the
    row's reported `line` unambiguous: it always names the away (or over) side's
    line, so a cell's own line agrees with the row's.
    """
    line = _line_value(row)
    if line is None:
        return None
    return -line if str(row.get("selection") or "").strip().lower() == "home" else line


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


def freshest_rows_for_grid(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Collapse a change-log stream to only the rows the grid can still use.

    WHY (`#331`). `build_book_grid` retains every priced row in `instances`
    until the pivot finishes, so peak memory scales with QUOTE EVENTS rather
    than with markets. Measured 2026-08-09 (MLB, 217MB shard, 478,782 rows):
    the whole-shard pivot peaks at 1,334MB. refresh-worker plateaus at
    2.65-2.70GB of 4GB, so that spike does not fit -- and the book-grid tick
    runs every 10 minutes. `#241` is the standing reminder of what periodic
    worker work that does not fit costs (a ~3-minute restart loop).

    The reduction is lossless FOR THIS CONSUMER, which is the only claim being
    made. The grid reads each market instance through `_freshest_per_book_side`,
    which keeps exactly one row per (book, side) -- the most recently observed.
    So any strictly-older row for an identical (instance, line, book, side) is
    already discarded downstream, and dropping it here changes nothing except
    when it is dropped.

    Keyed on the RAW `line` string rather than `_canonical_line`, deliberately:
    a finer key can only ever retain more rows, so a normalisation difference
    degrades to keeping a redundant row instead of silently dropping an anchor.

    Ties resolve last-wins (`>=`), matching `_freshest_per_book_side` exactly --
    a `>` here would pick the other row of a same-timestamp pair and make the
    two paths disagree on precisely the rows this function claims are equivalent.

    Priceless rows are dropped because `build_book_grid` drops them itself.
    Rows with an empty book or side are KEPT: the grid's grouping pass does not
    filter them, and one can still be the anchor that establishes a line.

    FILE ORDER IS PART OF THE CONTRACT, and this is not a detail. `build_book_grid`
    anchors on the FIRST row of a group carrying a given canonical line, so the
    order rows arrive in selects which row anchors, which line the row reports,
    and therefore which cells and staleness flags come out. Returning rows in
    first-seen order instead of file order changed 2,006 of 5,547 grid rows at
    identical byte length when this was first written -- a permutation, silent
    in every count and every size check. The kept rows are re-sorted into their
    original positions so the reduced stream is a SUBSEQUENCE of the full one.

    ANCHORS ARE RETAINED SEPARATELY, and this is the subtle half. `build_book_grid`
    picks one anchor per distinct `_canonical_line` in a group, and passes it to
    `market_sides_for_quote`, which gathers that market's sides using THE ANCHOR'S
    own line and selection. So the anchor is not just a starting point -- it
    decides which rows count as sides. The freshest row for a cell is very often
    NOT the first row to establish that line, so keeping only freshest rows
    silently re-anchors 972 of 5,547 rows. Keeping the first-in-file row per
    (instance, canonical line) as well makes the original anchor available at its
    original position, and the anchor loop then selects exactly what it did before.
    """
    freshest: dict[tuple[str, ...], tuple[int, dict[str, Any]]] = {}
    anchors: dict[tuple[str, ...], tuple[int, dict[str, Any]]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            continue
        if _price(row.get("price")) is None:
            continue
        instance = tuple(str(row.get(field) or "") for field in _INSTANCE_FIELDS)
        materialised = row if isinstance(row, dict) else dict(row)
        key = instance + (
            str(row.get("line") or ""),
            str(row.get("bookmaker") or "").strip(),
            str(row.get("selection") or "").strip(),
        )
        current = freshest.get(key)
        if current is None or _observed_at(row) >= _observed_at(current[1]):
            freshest[key] = (index, materialised)
        anchor_key = instance + (str(_canonical_line(row)),)
        if anchor_key not in anchors:
            anchors[anchor_key] = (index, materialised)

    # Union by original position: a row that is both an anchor and a freshest
    # cell must appear once, not twice, or the grid sees a duplicate quote.
    kept: dict[int, dict[str, Any]] = {index: row for index, row in freshest.values()}
    for index, row in anchors.values():
        kept.setdefault(index, row)
    return [kept[index] for index in sorted(kept)]


def build_book_grid(
    rows: Iterable[Mapping[str, Any]],
    *,
    now: datetime | None = None,
    max_rows: int | None = None,
    last_seen: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Pivot raw `book_quotes` rows into per-market grid rows.

    Each returned row is one market instance carrying every book that quoted it
    and every side, plus the derived columns the reference surface shows.

    `last_seen` (from `read_quote_last_seen`) turns `age_seconds` from one
    number into two, and the distinction is the whole point:

        age_seconds       time since this price last MOVED
        seen_age_seconds  time since we last LOOKED at this market

    `book_quotes` is a change log -- an unchanged price writes no row -- so
    `_observed_at` can only ever answer the first. Measured 2026-08-08, all 100
    MLB rows on the served board carried ~11.9h ages inside a 1.2-minute window,
    which read as a capture outage and was in fact 100 motionless markets. Omit
    `last_seen` and `seen_age_seconds` is simply absent, which every consumer
    must treat as UNKNOWN rather than as fresh or as stale.
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
            anchor_key = _canonical_line(anchor)
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
                    "seen_age_seconds": _seen_age_seconds(row, last_seen, now=now),
                }

            # Per-cell staleness FIRST, because #S1b's best/consensus selection
            # below reads it. Each cell gets a reason string so the UI can grey
            # it WITH A CAUSE rather than either hiding it or presenting it as
            # current -- and the reason is written here, once, because a UI that
            # re-derives it drifts from the flag and the two eventually disagree.
            freshest_row_age = min(
                (
                    cells[b][s]["age_seconds"]
                    for b in cells
                    for s in cells[b]
                    if cells[b][s].get("age_seconds") is not None
                ),
                default=None,
            )
            for book_key, sides_map in cells.items():
                for side_key, cell in sides_map.items():
                    age = cell.get("age_seconds")
                    cell_lag = (
                        round(age - freshest_row_age, 1)
                        if age is not None and freshest_row_age is not None
                        else None
                    )
                    cell["lag_behind_freshest_seconds"] = cell_lag
                    if cell_lag is not None and cell_lag > _STALE_BEST_LAG_SECONDS:
                        cell["stale"] = True
                        cell["reason"] = f"{_duration(cell_lag)} behind the freshest quote on this market"
                    else:
                        cell["stale"] = False
                        cell["reason"] = None

            # best price per side, and the consensus it should be read against.
            #
            # #S1b: BOTH are selected from FRESH quotes only.
            #
            # Measured on production 2026-08-07: 1,528 of 3,246 MLB rows (47%)
            # led with a best price that lagged the market, because selection
            # took the numerically best quote regardless of age. A book that
            # stopped updating six hours ago and happened to leave a generous
            # number behind was being presented as the best available bet, and
            # every downstream figure -- EV, edge, arbitrage, low hold, the
            # Layer 2 blended score -- inherited it.
            #
            # Consensus gets the same treatment for the same reason: a
            # "consensus" that averages in six-hour-old prices is not what the
            # market currently thinks.
            #
            # Labelling was not enough. The stale quote is still shown as a
            # cell (Layer 1 hides nothing) -- it just no longer wins.
            best: dict[str, dict[str, Any]] = {}
            consensus: dict[str, int | None] = {}
            for side in side_names:
                all_prices = [
                    (cells[book][side]["price"], book)
                    for book in books
                    if side in cells[book] and cells[book][side]["price"] is not None
                ]
                if not all_prices:
                    consensus[side] = None
                    continue
                fresh_prices = [
                    (price, book)
                    for price, book in all_prices
                    if not cells[book][side].get("stale")
                ]
                # Fall back to the full set only when NOTHING is fresh -- a row
                # with no current quotes at all still has to render a number, and
                # `all_quotes_stale` says the number cannot be trusted. Silently
                # dropping the row would be the cheat the exit criterion
                # forbids: suspect-best falls only because the data vanished.
                all_stale = not fresh_prices
                prices = fresh_prices or all_prices

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
                # Staleness has ONE definition -- lag behind the freshest quote
                # on the whole market instance -- and it is computed once, per
                # cell, above. Reading the selected cell's own flag rather than
                # recomputing a per-side variant keeps `suspect_stale` and the
                # cell's own `stale` from ever disagreeing, which they did on
                # first write: a side whose quotes were all old but close
                # together looked fresh when compared only against each other.
                best_cell = cells[top_book][side]
                best_age = best_cell.get("age_seconds")
                lag = best_cell.get("lag_behind_freshest_seconds")
                # What the OLD rule would have picked, kept so the correction is
                # visible rather than silent -- and so "is the fresh best much
                # worse than the stale one" stays an answerable question.
                stale_top_price, stale_top_book = all_prices[0]
                for price, book in all_prices[1:]:
                    if _better(price, stale_top_price):
                        stale_top_price, stale_top_book = price, book

                best[side] = {
                    "price": top_price,
                    "bookmaker": top_book,
                    "books_quoting": len(prices),
                    "books_quoting_including_stale": len(all_prices),
                    "age_seconds": best_age,
                    "seen_age_seconds": best_cell.get("seen_age_seconds"),
                    "lag_behind_freshest_seconds": lag,
                    "edge_vs_consensus_pct": round(
                        (_implied_probability(side_consensus) - _implied_probability(top_price)) * 100, 2
                    ),
                    # Not "this is wrong" -- "do not read this as an edge without
                    # looking at when it was posted". After #S1b this can only be
                    # true when EVERY quote on the side is stale, because a fresh
                    # one would otherwise have won the selection.
                    "suspect_stale": bool(best_cell.get("stale")),
                    "all_quotes_stale": all_stale,
                    "best_including_stale": (
                        {"price": stale_top_price, "bookmaker": stale_top_book}
                        if stale_top_book != top_book
                        else None
                    ),
                }

            stamps = [c[s]["observed_at"] for c in cells.values() for s in c if c[s]["observed_at"]]
            newest = max(stamps) if stamps else None

            # Row-level gaps: why this row is not the full grid the reference
            # surface shows. Rendered greyed with these strings rather than
            # filtered out -- an honest empty cell says the capture needs work;
            # a filtered row makes the board look complete when it is not.
            gaps: list[str] = []
            if len(books) <= 1:
                gaps.append(f"only {len(books)} book quoting - no price shopping, no consensus")
            if len(side_names) < 2:
                gaps.append("one-sided - no-vig fair value and hold cannot be computed")
            # After #S1b a suspect best means EVERY quote on that side is stale,
            # not that a stale one won the selection -- so the wording says the
            # market has gone quiet rather than accusing the pick.
            suspect_sides = [s for s in side_names if (best.get(s) or {}).get("suspect_stale")]
            if suspect_sides:
                worst_lag = max(
                    (best[s].get("lag_behind_freshest_seconds") or 0) for s in suspect_sides
                )
                gaps.append(
                    f"every quote on {', '.join(suspect_sides)} is stale - freshest is "
                    f"{_duration(worst_lag)} behind this market; no current price exists"
                )

            first = sides_rows[0]
            # `#435`. `commence_time` is REVISED during a slate -- measured on
            # the MLB 2026-08-09 shard, 12 of 15 events carried more than one
            # value, spread up to 7 minutes. Taking it off `sides_rows[0]` meant
            # taking whichever report happened to be iterated first, which in an
            # append-only shard is the OLDEST. Same hazard the `line` comment
            # above records for `#262`, left in place for this field.
            #
            # It is not cosmetic: `closing_quotes` keeps rows with
            # `observed < commence`, so a stale-early start time DISCARDS quotes
            # that were genuinely pregame.
            #
            # FROM THE FRESHEST OBSERVATION, not the largest value. The first
            # attempt here took `max()` of the commence values and was wrong for
            # the case that matters: a start time revised EARLIER (measured
            # 18:20:00 -> 18:16:30) makes the largest value a stale one. What is
            # wanted is "what does the most recent report say", and ties break on
            # the value so the result never depends on iteration order.
            commence_time = str(
                max(
                    sides_rows,
                    key=lambda row: (
                        _observed_at(row),
                        str(row.get("commence_time") or ""),
                    ),
                ).get("commence_time")
                or ""
            ) or None
            grid.append(
                {
                    "sport": key[0],
                    "kind": key[1],
                    "event_id": key[2],
                    "segment": key[3],
                    "market": key[4],
                    "player_name": key[5] or None,
                    # Canonical (away/over perspective), not the anchor's raw
                    # line -- which side anchored is an accident of iteration
                    # order, and #262 is what that ambiguity cost.
                    "line": anchor_key,
                    "home_team": first.get("home_team"),
                    "away_team": first.get("away_team"),
                    "commence_time": commence_time,
                    # LEAGUE, carried rather than keyed (`#330`). All ten soccer
                    # leagues share the `soccer` sport slug and the
                    # `soccer_source` tree, so `sport` cannot express which
                    # competition a row belongs to. `append_book_quotes` already
                    # stamps it -- `extra={"league": ...}` in
                    # fetch_soccer_oddsapi_odds_local -- and this pivot dropped
                    # it, so every soccer row on Layer 1 read `league: None`
                    # (measured 2026-08-10: 7/7 rows on 08-10, 922/922 on 08-16).
                    #
                    # Deliberately NOT added to `_INSTANCE_FIELDS`. That tuple
                    # must mirror `market_sides_for_quote`'s base exactly or
                    # sides land in different rows and the grid under-reports
                    # book coverage -- its own comment says so. `event_id` is
                    # already globally unique, so league adds no disambiguation
                    # to the key and only risk. Carried like the team names are.
                    "league": first.get("league"),
                    "sides": side_names,
                    "books": books,
                    "books_quoting": len(books),
                    "cells": cells,
                    "best": best,
                    "consensus": consensus,
                    "updated_at": newest,
                    "age_seconds": _age_seconds(newest or "", now=now),
                    # THE SECOND CLOCK, AT ROW LEVEL (`#366`).
                    #
                    # This module has computed `seen_age_seconds` per CELL since
                    # the day it documented why the distinction matters -- and
                    # never summarised it to the row. The board renders rows, so
                    # every consumer above this line could see only
                    # `age_seconds`: time since the price last MOVED.
                    #
                    # `book_quotes` is a change log, so a motionless market looks
                    # ancient. Measured on the served board 2026-08-11, NFL rows
                    # showed a median 424 minutes and soccer 786 -- read as a
                    # capture outage, actually normal pregame markets nobody had
                    # repriced. The same confusion this docstring warns about at
                    # length was live on the board the whole time, because the
                    # answer stopped one level short of where it was needed.
                    #
                    # MIN, matching `freshest_row_age` above: the row's freshest
                    # observation, not an average that no book actually offers.
                    "seen_age_seconds": min(
                        (
                            cells[b][s]["seen_age_seconds"]
                            for b in cells
                            for s in cells[b]
                            if cells[b][s].get("seen_age_seconds") is not None
                        ),
                        default=None,
                    ),
                    "gaps": gaps,
                    "complete": not gaps,
                }
            )

    # `#411`: a line its own market has moved off is not an available bet.
    # Runs BEFORE the bound below, so a superseded line cannot consume a slot
    # that a live one needed.
    grid, superseded = drop_superseded_lines(grid)
    if superseded:
        print(f"[book_grid] SUPERSEDED_LINES_DROPPED count={superseded} kept={len(grid)}", flush=True)

    # Widest grids first: a row quoted by eleven books is more useful than one
    # quoted by one, and it is the shape the reference surface leads with.
    grid.sort(key=lambda row: (-int(row.get("books_quoting") or 0), str(row.get("market") or "")))
    if max_rows is not None:
        return grid[: max(0, int(max_rows))]
    return grid


# How far behind its own market a line may fall and still be shown (`#411`).
#
# REPORTED FROM THE BOARD: "Framber Valdez for Detroit shows o15.5, 16.5, and
# 17.5 and odds are about the same so these must be at different times."
# Measured 2026-08-13, exactly that:
#
#     outs        15.5  seen 55m  3 books
#     outs        16.5  seen 53m  1 book
#     outs        17.5  seen 17m  8 books   <- the only live one
#     strikeouts   2.5  seen 19m  1 book    <- current, line falls as he pitches
#     strikeouts   4.5  seen 79m  7 books   <- abandoned an hour ago
#
# `book_quotes` is a CHANGE LOG and the grid keys a market instance by LINE, so
# every line a book has ever offered becomes its own row and keeps its last
# price forever. Nothing marked them dead. A reader sees three "available"
# alternates at similar odds; only one can be bet.
#
# BOOK COUNT IS NOT THE DISCRIMINATOR -- `strikeouts 4.5` carries SEVEN books and
# is an hour stale, while `strikeouts 2.5` carries one and is live. Only
# `seen_age_seconds` separates them, which is why `#366` had to reach row level
# before this was fixable at all.
#
# RELATIVE, NOT ABSOLUTE, and that is the whole design. A flat "drop anything
# older than 20 minutes" would empty a thin market where every line is
# legitimately an hour old and nothing has moved. This drops a line only when
# its OWN market has a materially fresher one -- evidence the book repriced and
# left this line behind. A market whose lines are uniformly old keeps all of
# them, because there is no evidence either way and a blank board is not an
# improvement over a stale one.
_STALE_ALT_LINE_LAG_SECONDS = 15 * 60


def _line_group_key(row: Mapping[str, Any]) -> tuple[str, ...]:
    """Everything that identifies a market EXCEPT its line.

    Alternates of one market share this key, so they can be compared against
    each other. `player_name` is in it: two players' props in the same market
    are different markets and must not prune one another.
    """
    return tuple(
        str(row.get(field) or "")
        for field in ("sport", "event_id", "kind", "market", "segment", "player_name")
    )


def drop_superseded_lines(
    grid: list[dict[str, Any]],
    *,
    lag_seconds: float = _STALE_ALT_LINE_LAG_SECONDS,
) -> tuple[list[dict[str, Any]], int]:
    """Remove lines their own market has visibly moved off. Returns (kept, dropped).

    Only acts where `seen_age_seconds` is present on BOTH the row and its
    group's freshest member -- an unknown age is not evidence of staleness, and
    pruning on absence is how a capture hiccup would silently empty the board.
    """
    freshest: dict[tuple[str, ...], float] = {}
    for row in grid:
        seen = row.get("seen_age_seconds")
        if seen is None:
            continue
        key = _line_group_key(row)
        current = freshest.get(key)
        if current is None or float(seen) < current:
            freshest[key] = float(seen)

    kept: list[dict[str, Any]] = []
    dropped = 0
    for row in grid:
        seen = row.get("seen_age_seconds")
        best = freshest.get(_line_group_key(row))
        if seen is not None and best is not None and (float(seen) - best) > lag_seconds:
            dropped += 1
            continue
        kept.append(row)
    return kept, dropped


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
