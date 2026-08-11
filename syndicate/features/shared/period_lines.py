"""Period totals/spreads for the live lens, reduced from the CENTRAL quote log.

REPLACES A PARALLEL ROUTE (`#343`). The live lens got its Q1-Q4/H1/H2 lines from
`period_lines_<date>.csv`, written by a Bovada scrape
(`fetch_bovada_period_lines_current`) that ran alongside the real odds capture.
That route was single-book, invisible to the board, Layer 2 and CLV, and had to
be maintained separately from every other price in the system.

Since `#343` the same intervals arrive through the paid OddsAPI call and land in
`book_quotes` like everything else. Confirmed in production 2026-08-11, one tick
after deploy -- 212 interval rows on a live WNBA slate:

    q1 42   q2 17   q3 17   q4 55   h1 44   h2 37
    markets: h2h, h2h_3_way, spreads, totals, spreads_alt, totals_alt
    books:   7 on q1/h1, 3-4 on q2/q3/q4/h2

So this reads the central record and reduces it to the shape the live lens
already consumes. One capture, one record, many consumers.

THE REDUCTION IS A MEDIAN, AND THAT IS A DELIBERATE CHOICE
-----------------------------------------------------------
The live lens wants ONE number per period -- `period_totals: {"q3": 56.5}` --
while the quote log carries every book. Three rules were available:

  best price     WRONG BY CONSTRUCTION. These are LINES, not prices. "Best" is
                 meaningful for odds; the best *line* depends on which side you
                 are taking, so a single stored value cannot be best for both.
  first row      An accident of iteration order, which is exactly what `#262`
                 cost this codebase once already.
  MEDIAN         What the market thinks the line is, and robust to a single
                 book's outlier -- including the dead prices measured on
                 2026-08-10 (37 rows at +20000 or worse from one book).

Median across books, per (event, segment, market). With an even number of books
the LOWER middle value is taken rather than averaging, because averaging invents
a line no book is actually offering (56.25 when the books say 56 and 56.5).
"""

from __future__ import annotations

import statistics
from typing import Any, Iterable, Mapping

# The live lens asks for these and nothing else. `h2` included -- the Bovada CSV
# loader omitted it while the payload it fed showed one, so the old route was
# already inconsistent with itself.
_PERIODS = ("q1", "q2", "q3", "q4", "h1", "h2")


def _line_of(row: Mapping[str, Any]) -> float | None:
    try:
        value = row.get("line")
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _median_line(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    # Lower-middle, never an average: a mean of 56 and 56.5 is 56.25, a line no
    # book is offering and one that cannot be settled against.
    return ordered[(len(ordered) - 1) // 2]


def period_lines_by_matchup(
    rows: Iterable[Mapping[str, Any]],
    *,
    periods: Iterable[str] = _PERIODS,
) -> dict[tuple[str, str], dict[str, dict[str, float | None]]]:
    """(home_team, away_team) -> {"period_totals": {...}, "period_spreads": {...}}.

    Keyed on the team names exactly as the quote rows carry them; callers that
    work in tricodes convert on the way out, because the quote log is the shared
    record and should not learn one sport's identifier scheme.

    Accepts any iterable, so callers can stream a shard rather than load it --
    the MLB shard reached 217MB and `read_book_quotes` costs ~6.3x that resident.
    """
    wanted = {str(p).strip().lower() for p in periods}
    # (home, away) -> kind -> period -> [lines]
    buckets: dict[tuple[str, str], dict[str, dict[str, list[float]]]] = {}

    for row in rows or ():
        if not isinstance(row, Mapping):
            continue
        segment = str(row.get("segment") or "full").strip().lower()
        if segment not in wanted:
            continue
        market = str(row.get("market") or "").strip().lower()
        # Only the two the live lens models. `_alt` markets are deliberately
        # excluded: an alternate line is a DIFFERENT line by definition, so
        # folding it into the median would drag the consensus toward whatever
        # alt ladder a book happened to publish.
        if market == "totals":
            kind = "period_totals"
        elif market == "spreads":
            kind = "period_spreads"
        else:
            continue
        line = _line_of(row)
        if line is None:
            continue
        home = str(row.get("home_team") or "").strip()
        away = str(row.get("away_team") or "").strip()
        if not home or not away:
            continue
        # One value per BOOK, so a book that re-quotes twenty times in a live
        # game does not get twenty votes in the median.
        book = str(row.get("bookmaker") or "").strip()
        key = (home, away)
        per_kind = buckets.setdefault(key, {"period_totals": {}, "period_spreads": {}})
        seen = per_kind[kind].setdefault(segment, [])
        seen.append(line)
        # `seen` holds the latest line per book; the log is append-only and
        # ordered, so the last write for a book wins.
        per_kind.setdefault("_books", {})
        per_kind["_books"].setdefault(f"{kind}:{segment}", {})[book] = line

    out: dict[tuple[str, str], dict[str, dict[str, float | None]]] = {}
    for key, per_kind in buckets.items():
        books = per_kind.get("_books") or {}
        entry: dict[str, dict[str, float | None]] = {"period_totals": {}, "period_spreads": {}}
        for kind in ("period_totals", "period_spreads"):
            for segment in sorted(wanted):
                latest = books.get(f"{kind}:{segment}") or {}
                entry[kind][segment] = _median_line([v for v in latest.values() if v is not None])
        out[key] = entry
    return out


def period_lines_from_quote_log(sport: str, date_str: str, **kwargs: Any):
    """Convenience: stream the shard and reduce it in one call."""
    from syndicate.features.shared.odds_book_quotes import iter_book_quotes

    return period_lines_by_matchup(iter_book_quotes(sport, date_str), **kwargs)
