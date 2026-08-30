"""The venue basis must actually REACH a board row.

`venue_basis_edge` is a pure function with its own unit tests. This file asks
the different and historically more expensive question: does the grid path call
it, on the rows that matter, with the RIGHT arguments?

This repo has four inert fixes on file from one session -- code that was
present, correct, tested, and never executed -- plus a `#603` conversion that
shipped doing nothing because a guard compared against a status string the
matcher never returns. A unit test would have passed on every one of them.

The ordering assertions are the substance here. `apply_venue_quotes_to_grid`
overwrites the book's own `age_seconds` with the venue's, and
`_reprice_live_benchmark` then removes the pregame books from `cells`. Both
destroy an input the comparison needs, so "it is called" is not enough -- it
has to be called BEFORE them.
"""

from __future__ import annotations

import time

from syndicate.features.shared.venue_quote_adapters import quote_key
from syndicate.features.shared.venue_quote_fanin import Quote, apply_venue_quotes_to_grid

# The book side: five books, quoted a minute ago, both legs near even money.
# Deliberately NOT the `test_live_benchmark_reprice` fixture, whose single book
# and two-hour age would refuse on two guards before reaching the arithmetic.
FRESH_BOOK_AGE = 60.0


def _row(state: str = "live", *, book_age: float = FRESH_BOOK_AGE, books: int = 5) -> dict:
    return {
        "sport": "mlb",
        "kind": "game",
        "market": "h2h",
        "segment": "full_game",
        "line": None,
        "sides": ["home", "away"],
        "home_team": "Cincinnati Reds",
        "away_team": "Chicago Cubs",
        "game": {"state": state},
        "books": ["fanduel", "draftkings", "betmgm", "caesars", "pointsbet"],
        "books_quoting": books,
        "age_seconds": book_age,
        "best": {
            side: {
                "price": -110,
                "consensus_vigged_price": -110,
                "bookmaker": "fanduel",
                "age_seconds": book_age,
                "books_quoting": books,
                "all_quotes_stale": False,
            }
            for side in ("home", "away")
        },
        "cells": {
            "fanduel": {
                "home": {"price": -110, "age_seconds": book_age, "stale": False},
                "away": {"price": -110, "age_seconds": book_age, "stale": False},
            }
        },
        "consensus": {"home": -110, "away": -110},
    }


def _quotes(now: float, *, home: int = 250, away: int = -300, source: str = "kalshi") -> dict:
    out = {}
    for side, price in (("home", home), ("away", away)):
        key = str(quote_key("mlb", "h2h", side, None))
        out[key] = Quote(
            key=key,
            source=source,
            sport="mlb",
            market="h2h",
            side=side,
            probability=None,
            american=price,
            line=None,
            fetched_at=now - 10.0,
        )
    return out


def _apply(grid, quotes, now):
    return apply_venue_quotes_to_grid(
        grid, "mlb", "2026-08-24", collected={"quotes": quotes}, now=now
    )


def test_the_comparison_REACHES_a_live_row():
    """Reachability, before any question of correctness.

    The venue is much cheaper on `home` here (+250 = 0.286 against a 0.524 book
    consensus), so a wired-up module has something to say and a silent one is
    caught.
    """
    now = time.time()
    row = _row()
    stats = _apply([row], _quotes(now), now)

    basis = row["best"]["home"].get("venue_basis")
    assert basis is not None, "venue_basis never reached the row -- the attach is inert"
    assert basis["basis"] == "venue"
    assert basis["displayable"] is True, basis["reason"]
    assert basis["edge_pct"] > 0
    assert basis["venue"] == "kalshi"
    assert basis["anchor_books"] == 5
    # And the counter that makes a production zero attributable.
    assert stats["venue_basis_rows"] >= 1


def test_it_is_computed_BEFORE_the_price_overwrites_the_BOOKS_OWN_AGE():
    """ORDERING, GUARD 5. The failure this would hide is silent.

    The reprice below sets `side_best["age_seconds"]` to the VENUE's age. Read
    after it, the anchor-vintage guard is handed 10s -- the venue's freshness --
    for a book consensus captured two hours before first pitch, and the guard
    written to catch exactly that passes it.

    So: a row whose books are two hours stale must REFUSE, even though after
    the reprice the row's own `age_seconds` reads fresh. If this test fails the
    attach has drifted below the write.
    """
    now = time.time()
    row = _row(book_age=7200.0)
    _apply([row], _quotes(now), now)

    basis = row["best"]["home"]["venue_basis"]
    assert basis["edge_pct"] is None, (
        "a pregame book consensus was compared to a live venue price -- "
        "the attach is reading the venue's age as the book's"
    )
    assert "two clocks" in basis["reason"]
    # PROVE THE ORDERING IS WHAT SAVED IT: after the call the row really does
    # read fresh, so a later attach would have seen 10s and allowed it.
    assert row["best"]["home"]["age_seconds"] < 60.0
    # And prove the fixture COULD have produced the fiction -- same row, fresh
    # books, and the number is enormous.
    fresh = _row(book_age=FRESH_BOOK_AGE)
    _apply([fresh], _quotes(now), now)
    assert abs(fresh["best"]["home"]["venue_basis"]["edge_pct"]) > 20


def test_it_is_computed_BEFORE_the_benchmark_rewrite_removes_THE_BOOKS():
    """ORDERING, the anchor itself.

    `_reprice_live_benchmark` deliberately moves superseded pregame books out of
    `cells`/`consensus` so the venue is not median-averaged with them. On the
    rows where it succeeds there is afterwards no independent book consensus
    left -- the comparison would be the venue against itself, which is 0.00 and
    reads as agreement.
    """
    now = time.time()
    row = _row()
    stats = _apply([row], _quotes(now), now)

    # The rewrite really did run and really did take the books' consensus with it.
    assert stats["benchmark_rows"] == 1
    assert row["consensus"]["home"] == 250, "fixture no longer exercises the rewrite"
    # Yet the verdict on the row still holds the BOOK number, not the venue's.
    basis = row["best"]["home"]["venue_basis"]
    assert basis["consensus_probability"] < 0.6, (
        f"anchor {basis['consensus_probability']} looks like the venue's own price -- "
        "the comparison ran after the benchmark rewrite"
    )


def test_a_PREGAME_row_gets_a_refusal_not_a_number():
    now = time.time()
    row = _row(state="pregame")
    _apply([row], _quotes(now), now)
    basis = row["best"]["home"]["venue_basis"]
    assert basis["edge_pct"] is None
    assert "market_basis_edge" in basis["reason"]


def test_the_venue_NAME_is_translated_not_passed_through():
    """Quotes say `polymarket_us`; the fee model and `IN_PLAY_VENUES` say
    `polymarket`. Untranslated, every Polymarket row refuses as an unknown
    venue -- which on a board reads identically to 'no edge found'."""
    now = time.time()
    row = _row()
    _apply([row], _quotes(now, source="polymarket_us"), now)
    basis = row["best"]["home"]["venue_basis"]
    assert basis["venue"] == "polymarket"
    assert basis["displayable"] is True, basis["reason"]
    # Polymarket's fee is measured, so nothing is bounded here.
    assert basis["fee_is_upper_bound"] is False


def test_kalshi_rows_are_stamped_as_a_FEE_UPPER_BOUND():
    """Nothing writes the series multiplier yet, so the full rate is assumed.
    The row must say so rather than present the bound as the fee."""
    now = time.time()
    row = _row()
    _apply([row], _quotes(now, source="kalshi"), now)
    assert row["best"]["home"]["venue_basis"]["fee_is_upper_bound"] is True


def test_a_row_with_no_venue_quote_carries_NO_verdict_at_all():
    """Absent must not be rendered as a refusal, and a refusal must not be
    rendered as agreement. Three states, kept distinct."""
    now = time.time()
    row = _row()
    _apply([row], {}, now)
    assert "venue_basis" not in row["best"]["home"]
