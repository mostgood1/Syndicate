"""A LIVE row's fair value must move to the venue that priced it.

`7799abf9c` re-priced `best` from Kalshi/Polymarket before the lane gate. It
left `cells` and `consensus` on the pregame OddsAPI capture, so one row carried
two vintages: a live price scored against a pregame benchmark. Every fair value
the board computes reads the second pair -- `layer2_board._fair_by_side` from
`cells`, `prop_projections._no_vig_over_probability` from `consensus` -- and
`live_gameline_join` subtracts that pregame fair from the LIVE re-sim's win
probability. The difference is mostly the gap between two clocks, and
`_MODEL_EDGE_MAX_POINTS` correctly drops it as a units error.

These pin the four conditions on the rewrite, three of which are refusals.
"""

from __future__ import annotations

import time

from syndicate.features.shared.venue_quote_adapters import quote_key
from syndicate.features.shared.venue_quote_fanin import Quote, apply_venue_quotes_to_grid


def _row(state: str = "live", *, age: float = 7200.0) -> dict:
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
        "books": ["fanduel"],
        "books_quoting": 1,
        "age_seconds": age,
        "best": {
            "home": {"price": -120, "bookmaker": "fanduel", "age_seconds": age},
            "away": {"price": 100, "bookmaker": "fanduel", "age_seconds": age},
        },
        "cells": {
            "fanduel": {
                "home": {"price": -120, "age_seconds": age, "stale": False},
                "away": {"price": 100, "age_seconds": age, "stale": False},
            }
        },
        "consensus": {"home": -120, "away": 100},
    }


def _quotes(now: float, *, sides=("home", "away"), source: str = "polymarket_us") -> dict:
    out = {}
    prices = {"home": -900, "away": 700}
    for side in sides:
        key = str(quote_key("mlb", "h2h", side, None))
        out[key] = Quote(
            key=key,
            source=source,
            sport="mlb",
            market="h2h",
            side=side,
            probability=None,
            american=prices[side],
            line=None,
            fetched_at=now - 20.0,
        )
    return out


def _apply(grid, quotes, now):
    return apply_venue_quotes_to_grid(
        grid, "mlb", "2026-08-24", collected={"quotes": quotes}, now=now
    )


def test_a_live_row_moves_its_benchmark_with_its_price():
    now = time.time()
    row = _row()
    stats = _apply([row], _quotes(now), now)

    assert stats["repriced"] == 2
    assert stats["benchmark_rows"] == 1
    # THE POINT: not just the price. Both readers of fair value move too, and
    # they move to the SAME venue the price came from.
    assert row["best"]["home"]["price"] == -900
    assert row["consensus"] == {"home": -900, "away": 700}
    assert row["cells"]["polymarket"]["home"]["price"] == -900
    assert row["cells"]["polymarket"]["away"]["price"] == 700
    assert "polymarket" in row["books"]
    # The pregame book is MOVED ASIDE, not deleted. It lags the venue by two
    # hours, so leaving it in `cells` would put it back into the fair-value
    # median at equal weight -- half the vintage gap is still the vintage gap.
    # The observation itself survives on the row.
    assert "fanduel" not in row["cells"]
    assert row["cells_superseded"]["fanduel"]["home"]["price"] == -120
    assert row["books"] == ["polymarket"]


def test_the_devig_the_board_will_run_is_now_live_on_both_legs():
    """`_fair_by_side` needs ONE book quoting EVERY leg. That is exactly what
    the all-or-nothing rule guarantees, and it is why a partial write would be
    useless as well as wrong."""
    from syndicate.features.shared.layer2_board import _fair_by_side

    now = time.time()
    row = _row()
    _apply([row], _quotes(now), now)

    fair, method = _fair_by_side(row, ["home", "away"])
    assert method == "consensus"
    # -900 de-vigs to ~0.90 against +700's ~0.125. A live favourite, which is
    # the number the live re-sim's ~0.90 should be compared against -- the
    # pregame pair would have said ~0.545 and manufactured a 35-point edge.
    assert fair["home"] > 0.85


def test_a_pregame_row_keeps_its_multi_book_consensus():
    """Refusal 1. Before first pitch the pregame books ARE the current market,
    and replacing a median across books with one venue throws away the
    protection `#384` added."""
    now = time.time()
    row = _row(state="pre")
    stats = _apply([row], _quotes(now), now)

    assert stats["benchmark_rows"] == 0
    assert stats["benchmark_skipped"] == {"not_live": 1}
    assert row["consensus"] == {"home": -120, "away": 100}
    assert "polymarket" not in row["cells"]
    # The PRICE still moves -- that behaviour is unchanged and is not what this
    # rule is about.
    assert row["best"]["home"]["price"] == -900


def test_one_venue_side_is_not_enough():
    """Refusal 2. A de-vig pairing a live home price with a pregame away price
    spans two vintages, which is worse than the stale pair it replaces."""
    now = time.time()
    row = _row()
    stats = _apply([row], _quotes(now, sides=("home",)), now)

    assert stats["benchmark_rows"] == 0
    assert stats["benchmark_skipped"] == {"venue_did_not_price_every_side": 1}
    assert row["consensus"] == {"home": -120, "away": 100}


def test_two_venues_across_two_sides_is_refused():
    """Refusal 3. The best home at one venue and the best away at another sum
    to less than a market; normalising that to 1.0 launders a line-shopping
    edge into the fair price. `_fair_by_side` says so at length."""
    now = time.time()
    row = _row()
    quotes = _quotes(now)
    away_key = str(quote_key("mlb", "h2h", "away", None))
    quotes[away_key] = Quote(
        key=away_key,
        source="kalshi",
        sport="mlb",
        market="h2h",
        side="away",
        probability=None,
        american=700,
        line=None,
        fetched_at=now - 20.0,
    )
    stats = _apply([row], quotes, now)

    assert stats["benchmark_rows"] == 0
    assert stats["benchmark_skipped"] == {"sides_from_different_venues": 1}
    assert row["consensus"] == {"home": -120, "away": 100}


def test_a_fresher_existing_benchmark_is_never_aged_up():
    """Refusal 4. Same rule the price re-price already applies -- this can only
    ever make a row fresher."""
    now = time.time()
    row = _row(age=2.0)
    stats = _apply([row], _quotes(now), now)

    assert stats["benchmark_rows"] == 0
    assert stats["benchmark_skipped"] == {"existing_benchmark_is_fresher": 1}
    assert row["consensus"] == {"home": -120, "away": 100}


def test_a_book_still_quoting_the_live_market_stays_a_peer():
    """The rule is about VINTAGE, not about preferring the venue. A sportsbook
    inside `LIVE_MARKET_MAX_AGE_SECONDS` of the venue is a real second opinion
    on the same live market and belongs in the median."""
    now = time.time()
    row = _row(age=60.0)
    row["cells"]["fanduel"]["home"]["age_seconds"] = 60.0
    row["cells"]["fanduel"]["away"]["age_seconds"] = 60.0
    stats = _apply([row], _quotes(now), now)

    assert stats["benchmark_rows"] == 1
    assert "fanduel" in row["cells"]
    assert "cells_superseded" not in row
    assert sorted(row["books"]) == ["fanduel", "polymarket"]


def test_a_book_with_no_clock_is_superseded_rather_than_trusted():
    """An unstamped age is UNKNOWN, not fresh. Keeping it would let a book
    nobody can date sit in a live median at equal weight."""
    now = time.time()
    row = _row()
    row["cells"]["fanduel"]["home"].pop("age_seconds")
    stats = _apply([row], _quotes(now), now)

    assert stats["benchmark_rows"] == 1
    assert "fanduel" not in row["cells"]
    assert "fanduel" in row["cells_superseded"]
