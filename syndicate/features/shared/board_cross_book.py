"""S5 / C3 — cross-book numbers computed only over prices that COEXISTED.

`opportunity_signals.arbitrage_profit_pct` has carried this warning since it was
written, and until now it had no callers at all:

    the arithmetic is the easy part and is not where arb detection goes wrong.
    Ours went wrong on PAIRING and STALENESS ... those guards belong at the
    call site.

This module is that call site. The arithmetic is delegated; what lives here is
the part that was missing.

WHY THIS IS NOT OPTIONAL. `book_quotes` is an append-only log for the whole day.
On a single production MLB h2h row, measured 2026-08-07, the eleven books'
away-side quotes were observed between **08:33Z and 18:43Z — a span of over ten
hours**. Taking the numerically best price per side across that window and
subtracting produces a number that is not merely imprecise, it describes a market
that never existed at any instant. Enforcing simultaneity is what took an
apparent 716 arbitrages to ~3 (§4e C3).

ONE OPTIMISATION SERVES BOTH BOARDS. Arb profit and hold are both strictly
monotone in the overround: profit is `1/overround - 1` and hold is
`overround - 1`. So "the best arb" and "the lowest hold" are the same search --
minimise the summed implied probability over one price per side, subject to the
prices coexisting. L2-B and L2-C are two filters over one result, which is §3's
one-row-contract rule rather than two pipelines that will disagree.

WHAT "SIMULTANEOUS" MEANS HERE, stated because it is a judgement call: quotes are
treated as coexisting if the spread between the earliest and latest observation
in the chosen set is within `max_skew_seconds`. That is a *capture* window, not a
claim that the prices were live together -- at a ~26-minute capture cadence
(§4e C1) a tighter window than the cadence would return nothing at all. The
window used is reported on every row as `skew_seconds` so a caller can tighten it
without re-deriving what it meant.
"""

from __future__ import annotations

from datetime import datetime, timezone
from itertools import product
from typing import Any, Iterable, Mapping, Sequence

from syndicate.features.shared.opportunity_signals import (
    arbitrage_profit_pct,
    hold_pct,
    implied_probability,
    overround,
)

# One capture cadence. Tighter than this and a slate captured every ~26 minutes
# yields no simultaneous set at all; looser and "simultaneous" stops meaning
# anything. Named for the job it does -- see rule 9 in the post-mortem, which
# exists because four constants were reused for jobs they were not measured for.
DEFAULT_MAX_SKEW_SECONDS = 90.0


def _parse_ts(value: Any) -> datetime | None:
    """Parse an observation stamp, or None. Never raises, never guesses."""
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _quotes_for_row(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Flatten a grid row's cells into (side, book, price, observed_at) quotes.

    A quote with no parseable timestamp is DROPPED rather than treated as
    current. An undated price cannot be shown to have coexisted with anything,
    and this whole module exists to stop unprovable pairings.
    """
    sides = [str(s) for s in (row.get("sides") or []) if s]
    cells = row.get("cells") or {}
    quotes: list[dict[str, Any]] = []
    for book, by_side in cells.items():
        if not isinstance(by_side, Mapping):
            continue
        for side in sides:
            cell = by_side.get(side)
            if not isinstance(cell, Mapping):
                continue
            price = cell.get("price")
            if price is None or implied_probability(price) is None:
                continue
            observed = _parse_ts(cell.get("observed_at"))
            if observed is None:
                continue
            quotes.append(
                {
                    "side": side,
                    "book": str(book),
                    "price": price,
                    "observed_at": observed,
                    "implied": implied_probability(price),
                    # The CELL's own line, which is not always the row's line.
                    # See _complementary below -- this is the pairing guard.
                    "line": cell.get("line"),
                }
            )
    return quotes


def _as_line(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _complementary(chosen: Mapping[str, Mapping[str, Any]]) -> bool:
    """Do these legs actually cover opposite outcomes of one market?

    THIS IS THE GUARD THAT MATTERS, and it is keyed on side semantics rather
    than market names so a new market key cannot quietly bypass it.

    Measured on production 2026-08-07 (`spreads_alt`, first5): books inside a
    single grid row disagree on the SIGN of the line --

        betmgm     away -1.5 (+210)   home +1.5 (-295)
        betrivers  away +1.5 (-240)   home -1.5 (+180)

    Pairing betmgm's away with betrivers' home takes two legs that are BOTH the
    +1.5 side. They are not opposite outcomes, so "backing both" wins or loses
    together and the overround is meaningless. Without this check the module
    reported a +250.88% arbitrage, which is postmortem §2.6 committed a second
    time: *spreads are signed per side.*

    Rules:
      - over/under  -> the same total, so the lines must be EQUAL.
      - away/home   -> handicaps mirror, so the lines must SUM TO ZERO.
      - no lines at all (h2h, 3-way) -> nothing to reconcile.
    """
    lines = {side: _as_line(leg.get("line")) for side, leg in chosen.items()}
    present = [v for v in lines.values() if v is not None]
    if not present:
        return True
    if len(present) != len(lines):
        # Some legs dated, some not: unprovable, so refuse rather than guess.
        return False
    sides = set(lines)
    if sides == {"over", "under"}:
        return abs(present[0] - present[1]) < 1e-9 and len(present) == 2
    if sides == {"away", "home"} and len(present) == 2:
        return abs(present[0] + present[1]) < 1e-9
    # An unrecognised side set with lines attached is not something this rule
    # was measured against; refuse rather than extend it by assumption.
    return False


def best_simultaneous_set(
    row: Mapping[str, Any],
    *,
    max_skew_seconds: float = DEFAULT_MAX_SKEW_SECONDS,
) -> dict[str, Any] | None:
    """The coexisting, COMPLEMENTARY one-price-per-side set with the lowest overround.

    Returns None when no window holds a valid set -- the honest answer for most
    rows, and why the raw arb count collapses once this is enforced.

    Two guards, and both were needed before any number here was true:
      - simultaneity: the chosen quotes must fall inside `max_skew_seconds`.
      - complementarity: the chosen legs must cover opposite outcomes
        (`_complementary`), because books inside one row disagree on line sign.

    Search: slide a window from each quote. With no lines the best price per side
    is independently optimal, so that path stays linear. With lines present the
    sides constrain each other, so combinations are enumerated -- bounded, since
    only two-sided markets carry lines (~books^2 per window).
    """
    sides = [str(s) for s in (row.get("sides") or []) if s]
    if len(sides) < 2:
        return None

    quotes = sorted(_quotes_for_row(row), key=lambda q: q["observed_at"])
    if len(quotes) < len(sides):
        return None

    lines_present = any(_as_line(q.get("line")) is not None for q in quotes)
    best: dict[str, Any] | None = None

    for i, anchor in enumerate(quotes):
        window_end = anchor["observed_at"].timestamp() + float(max_skew_seconds)
        by_side: dict[str, list[dict[str, Any]]] = {s: [] for s in sides}
        for quote in quotes[i:]:
            if quote["observed_at"].timestamp() > window_end:
                break
            if quote["side"] in by_side:
                by_side[quote["side"]].append(quote)
        if any(not by_side[s] for s in sides):
            continue

        if lines_present:
            combos = [dict(zip(sides, picks)) for picks in product(*(by_side[s] for s in sides))]
        else:
            combos = [{s: min(by_side[s], key=lambda q: q["implied"]) for s in sides}]

        for chosen in combos:
            if not _complementary(chosen):
                continue
            prices = [chosen[s]["price"] for s in sides]
            total = overround(prices)
            if total is None:
                continue
            if best is not None and total >= best["overround"]:
                continue
            stamps = [chosen[s]["observed_at"] for s in sides]
            best = {
                "overround": total,
                "prices": prices,
                "legs": [
                    {
                        "side": s,
                        "book": chosen[s]["book"],
                        "price": chosen[s]["price"],
                        "line": chosen[s].get("line"),
                        "observed_at": chosen[s]["observed_at"].isoformat().replace("+00:00", "Z"),
                    }
                    for s in sides
                ],
                # The ACTUAL spread of the winning set, not the permitted one: a
                # caller tightening the bound needs what it really cost.
                "skew_seconds": round(
                    max(t.timestamp() for t in stamps) - min(t.timestamp() for t in stamps), 3
                ),
                "books": sorted({chosen[s]["book"] for s in sides}),
            }
    return best


def cross_book_opportunities(
    grid: Iterable[Mapping[str, Any]],
    *,
    max_skew_seconds: float = DEFAULT_MAX_SKEW_SECONDS,
    low_hold_threshold_pct: float = 2.0,
) -> list[dict[str, Any]]:
    """L2-B and L2-C rows: every market with a simultaneous cross-book set.

    Not filtered to arbs. A row that is merely low-hold belongs to L2-C, and
    filtering here would make the two boards need two passes over the same data.
    Callers select with `is_arbitrage` / `is_low_hold`.
    """
    out: list[dict[str, Any]] = []
    for row in grid:
        best = best_simultaneous_set(row, max_skew_seconds=max_skew_seconds)
        if best is None:
            continue
        prices = best["prices"]
        arb = arbitrage_profit_pct(prices)
        hold = hold_pct(prices)
        if arb is None or hold is None:
            continue
        # Cross-book only. Both legs from one book is a hold measurement, not an
        # arbitrage -- no book lets you bank its own overround.
        cross_book = len(best["books"]) > 1
        out.append(
            {
                "sport": row.get("sport"),
                "event_id": row.get("event_id"),
                "game": row.get("game"),
                "home_team": row.get("home_team"),
                "away_team": row.get("away_team"),
                "kind": row.get("kind"),
                "market": row.get("market"),
                "segment": row.get("segment"),
                "line": row.get("line"),
                "player_name": row.get("player_name"),
                "legs": best["legs"],
                "books": best["books"],
                "cross_book": cross_book,
                "overround": round(best["overround"], 6),
                "arb_pct": arb,
                "hold_pct": hold,
                "skew_seconds": best["skew_seconds"],
                "max_skew_seconds": float(max_skew_seconds),
                "is_arbitrage": bool(cross_book and arb > 0),
                "is_low_hold": bool(0.0 <= hold < float(low_hold_threshold_pct)),
            }
        )
    out.sort(key=lambda r: (-r["arb_pct"], r["hold_pct"]))
    return out


def cross_book_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Counts a caller can put next to the board without recomputing them."""
    arbs = [r for r in rows if r.get("is_arbitrage")]
    return {
        "rows": len(rows),
        "arbitrage_rows": len(arbs),
        "low_hold_rows": sum(1 for r in rows if r.get("is_low_hold")),
        "cross_book_rows": sum(1 for r in rows if r.get("cross_book")),
        "best_arb_pct": max((r["arb_pct"] for r in arbs), default=None),
        "median_skew_seconds": (
            sorted(r["skew_seconds"] for r in rows)[len(rows) // 2] if rows else None
        ),
    }
