"""A published candidate's `line` is the handicap ITS OWN side is priced at.

Measured on `/api/board/book-grid`, mlb 2026-08-15, 525 book cells across 33
spreads rows: `cell.home.line == -row["line"]` on 525/525, and every book's own
home/away lines summed to zero. So the grid row's `line` is the AWAY handicap:
away candidates were already correct, home candidates published the away
handicap beside the home price.

Two measured consequences, both pinned here: the CLV join differenced a home
-1.5 opening against a home +1.5 close (a -29.90/+30.428 mirror pair on a market
that never moved), and the Ask headline renders `f"{side} {line}"`, so a home
spread showed the wrong handicap to a user.
"""
from __future__ import annotations

from syndicate.features.shared.layer2_board import _side_line_from_cells


def _row(cells):
    return {"market": "spreads", "line": 1.5, "cells": cells}


def _cell(home_line, away_line, home_price=168, away_price=-205):
    return {
        "home": {"line": home_line, "price": home_price},
        "away": {"line": away_line, "price": away_price},
    }


def test_home_takes_its_own_handicap_not_the_rows():
    """The production shape: row.line is +1.5 (away), home is priced at -1.5."""
    row = _row({"fanduel": _cell(-1.5, 1.5), "draftkings": _cell(-1.5, 1.5)})
    assert _side_line_from_cells(row, "home") == -1.5
    assert row["line"] == 1.5, "the row's own value is untouched"


def test_away_is_a_no_op_because_it_already_agreed():
    row = _row({"fanduel": _cell(-1.5, 1.5)})
    assert _side_line_from_cells(row, "away") == row["line"] == 1.5


def test_books_disagreeing_returns_none_rather_than_voting():
    """The 2026-08-07 `spreads_alt` condition: books disagree on the sign.

    A majority vote here would publish a confident wrong handicap. Refuse, and
    let the caller keep the row's value.
    """
    row = _row({"betmgm": _cell(-1.5, 1.5), "betrivers": _cell(1.5, -1.5)})
    assert _side_line_from_cells(row, "home") is None


def test_absent_cells_or_lines_return_none():
    assert _side_line_from_cells({"cells": {}}, "home") is None
    assert _side_line_from_cells({}, "home") is None
    assert _side_line_from_cells(_row({"fanduel": {"home": {"price": 100}}}), "home") is None


def test_unparseable_line_is_ignored_not_crashed():
    row = _row({"a": _cell("not-a-number", 1.5), "b": _cell(-1.5, 1.5)})
    assert _side_line_from_cells(row, "home") == -1.5


def test_h2h_has_no_line_and_stays_none():
    row = {"market": "h2h", "line": None, "cells": {"fanduel": {"home": {"price": -150}}}}
    assert _side_line_from_cells(row, "home") is None


def test_string_lines_are_coerced():
    row = _row({"fanduel": _cell("-1.5", "1.5")})
    assert _side_line_from_cells(row, "home") == -1.5


def test_the_no_arbitrage_invariant_the_bug_violated():
    """The check that caught this: -1.5 must be the longer price of the two.

    Before the fix a home candidate carried line=+1.5 with the -1.5 price, so a
    pair of home candidates for one event implied the harder bet was cheaper.
    """
    row = _row({"fanduel": _cell(-1.5, 1.5, home_price=168, away_price=-205)})
    home_line = _side_line_from_cells(row, "home")
    away_line = _side_line_from_cells(row, "away")
    def implied(p):
        return 100.0 / (p + 100.0) if p > 0 else abs(p) / (abs(p) + 100.0)
    # home is at -1.5 (harder) priced +168; away at +1.5 (easier) priced -205
    assert home_line == -1.5 and away_line == 1.5
    assert implied(168) < implied(-205)
