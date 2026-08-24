"""The market join, and the three ways a betting backtest flatters itself.

**A JOIN LIKE THIS FAILS BY LOOKING RIGHT.** Every mistake available here
produces a plausible win rate rather than an error:

  LOOKAHEAD      taking a quote captured after the probe -- the line has already
                 moved toward the truth, so the model looks prescient.
  EXTRAPOLATION  inventing a wall clock outside the observed bridge, which dates
                 the quote lookup to a moment nobody measured.
  A LOST N       reporting a win rate without the date count, when the families
                 intersect on one date.

So these tests are mostly about refusing, not computing.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.basketball_market_join import (
    clock_bridge,
    compare,
    line_as_of,
    summarise,
)


# --------------------------------------------------------------------------
# The clock bridge


def test_it_interpolates_between_observed_pairs() -> None:
    at = clock_bridge([(1000.0, 0.0), (1100.0, 100.0)])
    assert at(0.0) == pytest.approx(1000.0)
    assert at(100.0) == pytest.approx(1100.0)
    assert at(50.0) == pytest.approx(1050.0)


def test_it_refuses_to_extrapolate_past_either_edge() -> None:
    """**THE FLATTERING BUG.** Extending the nearest slope past the last capture
    gives a confident timestamp for a moment nobody observed, and the quote
    lookup it feeds then selects the wrong line -- which reads as the model
    being wrong, or right, at random."""
    at = clock_bridge([(1000.0, 0.0), (1100.0, 100.0)])
    assert at(-1.0) is None
    assert at(101.0) is None
    assert at(100.0) is not None, "the edge itself is observed and must work"


def test_pairs_may_arrive_unordered_and_duplicated() -> None:
    """Appends come from a live loop; a restart can repeat one."""
    at = clock_bridge([(1100.0, 100.0), (1000.0, 0.0), (1000.0, 0.0)])
    assert at(50.0) == pytest.approx(1050.0)


def test_a_stalled_clock_does_not_divide_by_zero() -> None:
    """Two captures at the same game second is a game clock that did not move --
    a timeout, or two polls inside one tick."""
    at = clock_bridge([(1000.0, 50.0), (1200.0, 50.0)])
    assert at(50.0) in (1000.0, 1200.0)


def test_an_empty_bridge_answers_None_rather_than_raising() -> None:
    """A date with no captures must degrade, not explode -- it is the normal
    state for 11 of the 13 dates that have game state."""
    assert clock_bridge([])(42.0) is None


# --------------------------------------------------------------------------
# The line lookup


def _q(book: str, stamp: float, line: float, segment: str = "q3",
       market: str = "totals") -> dict:
    return {"bookmaker": book, "captured_epoch": stamp, "line": line,
            "segment": segment, "market": market}


def test_it_takes_the_freshest_quote_at_or_before_the_probe() -> None:
    quotes = [_q("a", 100.0, 50.5), _q("a", 200.0, 52.5), _q("a", 300.0, 54.5)]
    assert line_as_of(quotes, segment="q3", as_of_epoch=250.0) == 52.5
    assert line_as_of(quotes, segment="q3", as_of_epoch=200.0) == 52.5, "at is allowed"


def test_a_quote_from_the_future_is_never_used(capsys) -> None:
    """**LOOKAHEAD IS THE MOST FLATTERING BUG A BACKTEST CAN HAVE.** A line
    captured one second later has already moved toward the truth."""
    quotes = [_q("a", 300.0, 54.5)]
    assert line_as_of(quotes, segment="q3", as_of_epoch=299.0) is None


def test_books_are_reduced_by_the_lower_middle_median() -> None:
    """Matches `period_lines._median_line` rather than inventing a second rule.
    Averaging 52 and 53 gives 52.5, a line no book is offering."""
    quotes = [_q("a", 100.0, 52.0), _q("b", 100.0, 53.0)]
    assert line_as_of(quotes, segment="q3", as_of_epoch=150.0) == 52.0

    quotes.append(_q("c", 100.0, 60.0))
    assert line_as_of(quotes, segment="q3", as_of_epoch=150.0) == 53.0


def test_one_book_moving_does_not_count_twice() -> None:
    """The quote log is append-only and a line move mints a NEW row, so a book
    that moved appears repeatedly. Counting both would let one book outvote the
    others by being the most active."""
    quotes = [_q("a", 100.0, 40.0), _q("a", 150.0, 60.0),
              _q("b", 100.0, 50.0), _q("c", 100.0, 51.0)]
    # a's freshest is 60.0, so the three books are {60, 50, 51} -> median 51.
    assert line_as_of(quotes, segment="q3", as_of_epoch=200.0) == 51.0


def test_freshest_per_book_is_by_TIMESTAMP_not_by_file_order() -> None:
    """**A MUTATION SURVIVED THE FIRST DRAFT OF THIS FILE.** Replacing the
    freshness comparison with "keep whatever row came last" passed everything,
    because the fixture above happens to list quotes in ascending time -- so
    last-seen and freshest coincided and the test proved nothing.

    A shard is append-only but this function takes any iterable, and a caller
    that groups or reverses would silently select a stale line. Here the
    FRESHEST row is listed FIRST, so the two rules disagree."""
    quotes = [_q("a", 900.0, 60.0), _q("a", 100.0, 40.0),
              _q("b", 100.0, 50.0), _q("c", 100.0, 51.0)]
    assert line_as_of(quotes, segment="q3", as_of_epoch=1000.0) == 51.0, (
        "a's line is 60 (t=900), not 40 (t=100) -- median of {60, 50, 51} is 51")


def test_the_wrong_segment_or_market_is_not_borrowed() -> None:
    """A q4 total is a different bet from a q3 total, and a spread is not a
    total at all. Either would join and be wrong."""
    quotes = [_q("a", 100.0, 52.5, segment="q4"),
              _q("b", 100.0, 53.5, market="spreads")]
    assert line_as_of(quotes, segment="q3", as_of_epoch=150.0) is None


# --------------------------------------------------------------------------
# Grading


def test_it_grades_the_side_the_projection_actually_took() -> None:
    assert compare(55.0, 52.5, 58.0)["outcome"] == "win"     # over, went over
    assert compare(55.0, 52.5, 50.0)["outcome"] == "loss"    # over, went under
    assert compare(50.0, 52.5, 50.0)["outcome"] == "win"     # under, went under
    assert compare(50.0, 52.5, 58.0)["outcome"] == "loss"


def test_a_push_is_its_own_outcome_not_a_loss() -> None:
    """Folding pushes into either column moves the win rate by the number of
    pushes, and a whole-number line produces them constantly."""
    graded = compare(55.0, 52.0, 52.0)
    assert graded["outcome"] == "push"
    assert graded["side"] == "over", "the side taken is still recorded"


def test_no_disagreement_is_not_a_bet() -> None:
    assert compare(52.5, 52.5, 60.0)["outcome"] == "none"


def test_edge_is_signed_toward_over() -> None:
    assert compare(55.0, 52.5, 0.0)["edge"] == pytest.approx(2.5)
    assert compare(50.0, 52.5, 0.0)["edge"] == pytest.approx(-2.5)


# --------------------------------------------------------------------------
# The summary, and the number it refuses to drop


def _row(edge: float, outcome: str) -> dict:
    return {"edge": edge, "outcome": outcome}


def test_the_summary_cannot_report_a_win_rate_without_its_dates() -> None:
    """**THE COVERAGE PROBE FOUND ONE USABLE DATE.** A win rate over a handful of
    games on a single day is noise wearing a percentage, and it must not be
    possible to print it alone."""
    out = summarise([_row(3.0, "win")], dates=["2026-08-23"])
    assert out["date_count"] == 1
    assert out["dates"] == ["2026-08-23"]


def test_pushes_and_no_bets_are_excluded_from_the_win_rate() -> None:
    rows = [_row(3.0, "win"), _row(3.0, "loss"),
            _row(3.0, "push"), _row(0.0, "none")]
    out = summarise(rows, dates=["2026-08-23"])
    assert out["rows"] == 4
    assert out["graded"] == 2
    assert out["pushes"] == 1
    assert out["buckets"][0]["n"] == 2
    assert out["buckets"][0]["win_rate"] == pytest.approx(0.5)


def test_break_even_is_reported_beside_the_win_rate() -> None:
    """52% reads as a win until the juice is next to it."""
    out = summarise([_row(3.0, "win")], dates=["2026-08-23"])
    assert out["break_even_at_minus_110"] == pytest.approx(0.5238, abs=1e-4)


def test_edge_buckets_separate_a_small_disagreement_from_a_large_one() -> None:
    """A model half a point off the line and one four points off are different
    claims; pooling them hides where any edge lives."""
    rows = [_row(0.5, "win"), _row(0.5, "loss"), _row(5.0, "win"), _row(5.0, "win")]
    out = summarise(rows, dates=["2026-08-23"])
    small = next(b for b in out["buckets"] if b["edge_lo"] == 0.0)
    large = next(b for b in out["buckets"] if b["edge_lo"] == 4.0)
    assert small["win_rate"] == pytest.approx(0.5)
    assert large["win_rate"] == pytest.approx(1.0)
