"""S5/C3 — cross-book numbers must be computed over prices that COEXISTED.

The test that matters most is `test_identical_prices_hours_apart_are_not_an_arb`:
the same two prices are an arbitrage when observed together and nothing at all
when observed ten hours apart. That is the entire point of the module, and it is
the measured production condition (one MLB h2h row spanned 08:33Z..18:43Z).
"""

from __future__ import annotations

from syndicate.features.shared.board_cross_book import (
    best_simultaneous_set,
    cross_book_opportunities,
    cross_book_summary,
)


def _row(cells, *, sides=("away", "home"), **extra):
    row = {
        "sport": "mlb",
        "event_id": "evt1",
        "market": "h2h",
        "segment": "full",
        "line": None,
        "sides": list(sides),
        "cells": cells,
    }
    row.update(extra)
    return row


def _cell(price, observed_at):
    return {"price": price, "observed_at": observed_at}


# Two books whose prices, taken together, are a genuine arbitrage: +230 and -200
# imply 0.303 + 0.667 = 0.970 < 1.
_ARB_AWAY = 230
_ARB_HOME = -200


def test_simultaneous_cross_book_arb_is_found():
    row = _row(
        {
            "bookA": {"away": _cell(_ARB_AWAY, "2026-08-07T18:00:00Z")},
            "bookB": {"home": _cell(_ARB_HOME, "2026-08-07T18:00:30Z")},
        }
    )
    best = best_simultaneous_set(row, max_skew_seconds=90)
    assert best is not None
    assert best["overround"] < 1.0
    assert best["skew_seconds"] == 30.0
    assert sorted(best["books"]) == ["bookA", "bookB"]

    rows = cross_book_opportunities([row], max_skew_seconds=90)
    assert len(rows) == 1
    assert rows[0]["is_arbitrage"] is True
    assert rows[0]["arb_pct"] > 0
    assert rows[0]["cross_book"] is True


def test_identical_prices_hours_apart_are_not_an_arb():
    """The measured production failure: an all-day log pairs 08:33Z with 18:43Z."""
    row = _row(
        {
            "bookA": {"away": _cell(_ARB_AWAY, "2026-08-07T08:33:00Z")},
            "bookB": {"home": _cell(_ARB_HOME, "2026-08-07T18:43:00Z")},
        }
    )
    assert best_simultaneous_set(row, max_skew_seconds=90) is None
    assert cross_book_opportunities([row], max_skew_seconds=90) == []


def test_widening_the_window_re_admits_the_stale_pair():
    """Guards the knob itself: the rejection above must be the WINDOW, not a
    parsing accident that would silently reject everything."""
    row = _row(
        {
            "bookA": {"away": _cell(_ARB_AWAY, "2026-08-07T08:33:00Z")},
            "bookB": {"home": _cell(_ARB_HOME, "2026-08-07T18:43:00Z")},
        }
    )
    best = best_simultaneous_set(row, max_skew_seconds=11 * 3600)
    assert best is not None
    assert best["skew_seconds"] == 36600.0


def test_single_book_both_sides_is_hold_not_arbitrage():
    """No book lets you bank its own overround."""
    row = _row(
        {
            "bookA": {
                "away": _cell(_ARB_AWAY, "2026-08-07T18:00:00Z"),
                "home": _cell(_ARB_HOME, "2026-08-07T18:00:05Z"),
            }
        }
    )
    rows = cross_book_opportunities([row], max_skew_seconds=90)
    assert len(rows) == 1
    assert rows[0]["cross_book"] is False
    assert rows[0]["is_arbitrage"] is False
    # The arithmetic still runs -- it is a (negative) hold, which L2-C wants.
    assert rows[0]["arb_pct"] > 0


def test_undated_quote_is_dropped_not_assumed_current():
    row = _row(
        {
            "bookA": {"away": _cell(_ARB_AWAY, None)},
            "bookB": {"home": _cell(_ARB_HOME, "2026-08-07T18:00:00Z")},
        }
    )
    assert best_simultaneous_set(row, max_skew_seconds=90) is None


def test_missing_side_yields_no_set():
    row = _row({"bookA": {"away": _cell(_ARB_AWAY, "2026-08-07T18:00:00Z")}})
    assert best_simultaneous_set(row, max_skew_seconds=90) is None


def test_best_set_prefers_the_lowest_overround_within_a_window():
    """Three books, all simultaneous: it must pick the best price per side."""
    row = _row(
        {
            "bookA": {"away": _cell(100, "2026-08-07T18:00:00Z")},
            "bookB": {"away": _cell(_ARB_AWAY, "2026-08-07T18:00:10Z")},
            "bookC": {"home": _cell(_ARB_HOME, "2026-08-07T18:00:20Z")},
        }
    )
    best = best_simultaneous_set(row, max_skew_seconds=90)
    assert best is not None
    away_leg = [leg for leg in best["legs"] if leg["side"] == "away"][0]
    assert away_leg["book"] == "bookB"
    assert away_leg["price"] == _ARB_AWAY


def test_low_hold_flag_is_independent_of_arbitrage():
    """A market can be tight without being free money -- that is L2-C."""
    row = _row(
        {
            "bookA": {"away": _cell(-105, "2026-08-07T18:00:00Z")},
            "bookB": {"home": _cell(-105, "2026-08-07T18:00:10Z")},
        }
    )
    rows = cross_book_opportunities([row], max_skew_seconds=90, low_hold_threshold_pct=3.0)
    assert len(rows) == 1
    assert rows[0]["is_arbitrage"] is False
    assert rows[0]["is_low_hold"] is True


def test_summary_counts_and_sort_order():
    arb = _row(
        {
            "bookA": {"away": _cell(_ARB_AWAY, "2026-08-07T18:00:00Z")},
            "bookB": {"home": _cell(_ARB_HOME, "2026-08-07T18:00:10Z")},
        },
        event_id="arb",
    )
    tight = _row(
        {
            "bookA": {"away": _cell(-105, "2026-08-07T18:00:00Z")},
            "bookB": {"home": _cell(-105, "2026-08-07T18:00:10Z")},
        },
        event_id="tight",
    )
    rows = cross_book_opportunities([tight, arb], max_skew_seconds=90)
    # Sorted by arb descending, so the real arb leads regardless of input order.
    assert rows[0]["event_id"] == "arb"
    summary = cross_book_summary(rows)
    assert summary["rows"] == 2
    assert summary["arbitrage_rows"] == 1
    assert summary["cross_book_rows"] == 2
    assert summary["best_arb_pct"] == rows[0]["arb_pct"]


# --- pairing (complementarity) ------------------------------------------------
# Measured on production 2026-08-07: books inside ONE grid row disagree on the
# sign of the line, so a naive cross-book pair takes two legs of the SAME side.
# Without this guard the module reported a +250.88% arbitrage.


def _spread_cell(price, line, observed_at):
    return {"price": price, "line": line, "observed_at": observed_at}


def test_same_sign_spread_legs_are_not_complementary():
    """betmgm away -1.5 paired with betrivers home -1.5 is both the +1.5 side."""
    row = _row(
        {
            "betmgm": {"away": _spread_cell(525, -1.5, "2026-08-07T18:43:20Z")},
            "betrivers": {"home": _spread_cell(700, -1.5, "2026-08-07T18:43:26Z")},
        },
        market="spreads_alt",
        line=1.5,
    )
    assert best_simultaneous_set(row, max_skew_seconds=90) is None
    assert cross_book_opportunities([row], max_skew_seconds=90) == []


def test_mirrored_spread_legs_are_complementary():
    row = _row(
        {
            "betmgm": {"away": _spread_cell(210, -1.5, "2026-08-07T18:43:20Z")},
            "bovada": {"home": _spread_cell(-340, 1.5, "2026-08-07T18:43:26Z")},
        },
        market="spreads_alt",
        line=1.5,
    )
    best = best_simultaneous_set(row, max_skew_seconds=90)
    assert best is not None
    # Real market: an overround above 1, i.e. no free money.
    assert best["overround"] > 1.0


def test_totals_require_the_same_line_not_a_mirrored_one():
    same = _row(
        {
            "betmgm": {"over": _spread_cell(100, 8.5, "2026-08-07T18:00:00Z")},
            "betrivers": {"under": _spread_cell(-120, 8.5, "2026-08-07T18:00:05Z")},
        },
        sides=("over", "under"),
        market="totals",
        line=8.5,
    )
    assert best_simultaneous_set(same, max_skew_seconds=90) is not None

    mismatched = _row(
        {
            "betmgm": {"over": _spread_cell(100, 8.5, "2026-08-07T18:00:00Z")},
            "betrivers": {"under": _spread_cell(-120, 9.5, "2026-08-07T18:00:05Z")},
        },
        sides=("over", "under"),
        market="totals",
        line=8.5,
    )
    assert best_simultaneous_set(mismatched, max_skew_seconds=90) is None


def test_partially_lined_legs_are_refused_rather_than_guessed():
    row = _row(
        {
            "betmgm": {"away": _spread_cell(210, -1.5, "2026-08-07T18:00:00Z")},
            "bovada": {"home": {"price": -340, "observed_at": "2026-08-07T18:00:05Z"}},
        },
        market="spreads_alt",
        line=1.5,
    )
    assert best_simultaneous_set(row, max_skew_seconds=90) is None


def test_guard_picks_a_valid_pair_when_an_invalid_one_looks_far_better():
    """The invalid same-sign pair is hugely more attractive; it must be skipped.

    Real betmgm prices. The mirrored pair is an ordinary market (overround 1.07);
    pairing betmgm's away -1.5 with betrivers' home -1.5 would imply 0.45 and read
    as a +123% arbitrage. The guard has to prefer the boring correct answer over
    the exciting wrong one, which is the whole failure mode.
    """
    row = _row(
        {
            "betmgm": {
                "away": _spread_cell(210, -1.5, "2026-08-07T18:00:00Z"),
                "home": _spread_cell(-295, 1.5, "2026-08-07T18:00:02Z"),
            },
            "betrivers": {"home": _spread_cell(700, -1.5, "2026-08-07T18:00:04Z")},
        },
        market="spreads_alt",
        line=1.5,
    )
    best = best_simultaneous_set(row, max_skew_seconds=90)
    assert best is not None
    home_leg = [leg for leg in best["legs"] if leg["side"] == "home"][0]
    assert home_leg["book"] == "betmgm"      # the mirrored one, not the +700
    assert best["overround"] > 1.0           # an ordinary market, not free money

    rows = cross_book_opportunities([row], max_skew_seconds=90)
    assert rows[0]["is_arbitrage"] is False
