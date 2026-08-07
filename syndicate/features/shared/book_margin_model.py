"""S4: fair value for ONE-SIDED markets, from a book's own measured margin.

The gap this fills. De-vigging needs both sides, so a market the feed only ever
quotes one side of has no fair value, no hold, and no honest EV. Measured on
production 2026-08-07: ~24% of MLB grid rows are one-sided, and
`batter_home_runs` is the extreme case -- 12,409 rows, **100% `over`** across all
11 books. The other side is not in the feed and cannot be captured, so no amount
of collection fixes it.

THE MODEL. A book's price contains its margin. If we know how much margin THAT
book charges on THAT kind of market -- measured from its own two-sided markets on
the same slate -- we can remove it:

    fair = implied(price) x (1 - hold)

which is the multiplicative de-vig, applied with a hold we measured instead of a
second price we do not have.

WHY PER MARKET FAMILY, not per book. Books price props far fatter than game
lines: a 4.5% hold on a moneyline and 12% on a player prop is ordinary. Using a
book's global average would systematically under-correct props -- exactly the
markets that are one-sided -- and produce fair values that are still vigged
while claiming not to be. The profile is keyed (book, family) and only falls
back to the book's overall margin when a family has too few samples to trust.

WHAT THIS IS NOT. It is an estimate, and it is labelled one:
`fair_method: "book_margin_model"` versus `"two_sided_consensus"`. It must never
be silently mixed with a real two-sided fair value -- a modelled number wearing a
measured number's clothes is the failure #242 already caused once, when
suppressed values rendered as "0 at 0.0% hold".
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Mapping
from typing import Any

from syndicate.features.shared.opportunity_signals import (
    american_price,
    hold_pct,
    implied_probability,
)

# Below this many observed two-sided markets, a (book, family) hold is noise.
# Fall back to the book's overall margin, then to the market-wide one.
_MIN_SAMPLES_FOR_FAMILY = 5
_MIN_SAMPLES_FOR_BOOK = 8

# A hold outside this range is not a margin, it is a data error (a stale line, a
# mispriced side, or an arbitrage). Including them would drag every profile.
_PLAUSIBLE_HOLD_RANGE = (0.0, 40.0)


def market_family(market: Any) -> str:
    """Coarse family for margin purposes: books price these tiers differently.

    Not `market_keys.canonical_market_key` -- that answers "is this the same
    market", which is a different question from "does this book charge the same
    margin here". A moneyline and a run line are different markets with similar
    margins; a moneyline and a player prop are not.
    """
    text = str(market or "").strip().lower()
    if not text:
        return "other"
    if text.startswith(("batter_", "pitcher_", "player_")) or text in {
        "strikeouts", "outs", "hits_allowed", "earned_runs", "walks_allowed",
    }:
        return "player_prop"
    if text in {"h2h", "h2h_3_way", "moneyline"}:
        return "moneyline"
    if text in {"spreads", "spreads_3_way", "run_line", "puck_line", "ats"}:
        return "spread"
    if text in {"totals", "totals_3_way", "total"}:
        return "total"
    return "other"


class BookMarginProfile:
    """What each book charges, by market family, measured on this slate."""

    def __init__(self) -> None:
        self._family_holds: dict[tuple[str, str], list[float]] = {}
        self._book_holds: dict[str, list[float]] = {}
        self._all_holds: list[float] = []

    def observe(self, *, bookmaker: str, market: Any, prices: Iterable[Any]) -> None:
        price_list = [p for p in prices if p is not None]
        if len(price_list) < 2:
            return
        hold = hold_pct(price_list)
        if hold is None:
            return
        low, high = _PLAUSIBLE_HOLD_RANGE
        if not (low <= hold <= high):
            return
        family = market_family(market)
        self._family_holds.setdefault((str(bookmaker), family), []).append(hold)
        self._book_holds.setdefault(str(bookmaker), []).append(hold)
        self._all_holds.append(hold)

    def hold_for(self, *, bookmaker: str, market: Any) -> tuple[float, str] | None:
        """(hold %, basis) for a book/market, or None when nothing is measurable.

        MEDIAN, not mean -- the same reason `consensus_fair_probability` uses it:
        one stale or fat-fingered market should not move a book's profile.
        """
        family = market_family(market)
        samples = self._family_holds.get((str(bookmaker), family)) or []
        if len(samples) >= _MIN_SAMPLES_FOR_FAMILY:
            return round(statistics.median(samples), 3), f"{bookmaker}/{family}"
        book_samples = self._book_holds.get(str(bookmaker)) or []
        if len(book_samples) >= _MIN_SAMPLES_FOR_BOOK:
            return round(statistics.median(book_samples), 3), f"{bookmaker}/all_markets"
        if len(self._all_holds) >= _MIN_SAMPLES_FOR_BOOK:
            return round(statistics.median(self._all_holds), 3), "market_wide"
        return None

    def summary(self) -> dict[str, Any]:
        return {
            "books_profiled": len(self._book_holds),
            "family_profiles": len(
                [k for k, v in self._family_holds.items() if len(v) >= _MIN_SAMPLES_FOR_FAMILY]
            ),
            "observations": len(self._all_holds),
            "median_hold_pct": round(statistics.median(self._all_holds), 2) if self._all_holds else None,
            "by_family": {
                family: round(
                    statistics.median(
                        [h for (b, f), hs in self._family_holds.items() if f == family for h in hs]
                    ),
                    2,
                )
                for family in {f for (_, f) in self._family_holds}
            },
        }


def build_margin_profile(grid_rows: Iterable[Mapping[str, Any]]) -> BookMarginProfile:
    """Measure every book's margin from the TWO-SIDED markets on this slate.

    Deliberately measured per slate rather than carried as a constant: holds
    move with the book, the sport and the day, and a stale constant is the
    defect class this codebase has paid for most often.
    """
    profile = BookMarginProfile()
    for row in grid_rows or ():
        sides = list(row.get("sides") or ())
        if len(sides) < 2:
            continue
        cells = row.get("cells") or {}
        for bookmaker, sides_map in cells.items():
            prices = [
                (sides_map.get(side) or {}).get("price")
                for side in sides
                if isinstance(sides_map.get(side), Mapping)
            ]
            # Only a book quoting EVERY side of this market tells us its margin.
            if len([p for p in prices if p is not None]) != len(sides):
                continue
            profile.observe(bookmaker=bookmaker, market=row.get("market"), prices=prices)
    return profile


def apply_margin_model(
    grid_rows: list[dict[str, Any]], profile: BookMarginProfile
) -> dict[str, Any]:
    """Fill fair value on one-sided rows, labelled as modelled.

    Only touches rows that have no two-sided fair value. A row with both sides
    keeps its measured consensus -- an estimate must never displace a
    measurement.
    """
    filled = 0
    considered = 0
    for row in grid_rows:
        sides = list(row.get("sides") or ())
        if len(sides) != 1:
            continue
        considered += 1
        side = sides[0]
        best = (row.get("best") or {}).get(side) or {}
        price = best.get("price")
        bookmaker = best.get("bookmaker")
        if price is None or not bookmaker:
            continue
        measured = profile.hold_for(bookmaker=bookmaker, market=row.get("market"))
        if measured is None:
            continue
        hold, basis = measured
        implied = implied_probability(price)
        if implied is None:
            continue
        fair = implied * (1.0 - hold / 100.0)
        if not (0.0 < fair < 1.0):
            continue
        row["modelled_fair"] = {
            side: {
                "fair_probability": round(fair, 4),
                "fair_price": american_price(fair),
                "assumed_hold_pct": hold,
                "basis": basis,
                # Never confuse this with a real two-sided consensus. #242's
                # lesson: a value wearing a measurement's clothes is worse than
                # a blank, because it looks authoritative.
                "fair_method": "book_margin_model",
                "note": (
                    f"one-sided market: no opposing price exists, so fair value is "
                    f"estimated from {basis}'s measured {hold}% hold"
                ),
            }
        }
        filled += 1
    return {
        "one_sided_rows": considered,
        "rows_modelled": filled,
        "pct_modelled": round(100.0 * filled / considered, 1) if considered else 0.0,
        "profile": profile.summary(),
    }
