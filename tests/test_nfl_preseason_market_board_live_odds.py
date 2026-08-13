"""Preseason market board: live-grid odds fallback + real game state.

THE DEFECT. Measured on production 2026-08-13, weeks 2/3/4 of the preseason:

    /nfl/api/preseason/market-board -> 16 games, 0 rows, every game
    week 1 (positive control)       ->  1 game,  6 rows   <- join is FINE

The join was never broken. `preseason_odds_{season}.csv` -- written by a
separately-scheduled `fetch_nfl_preseason_odds.py` run -- held exactly one
row, CAR @ ARI fetched 2026-08-05, while the Layer 1 book-quotes shard for
the same slate carried 8,537 rows across 11 books with quotes 1.3 minutes
old. A missing INPUT, not a broken join, which is why the week-1 control
matters: without it a zero here is unreadable.
"""

from __future__ import annotations

import pytest

from syndicate.features.nfl import preseason_cards as pc


# --------------------------------------------------------------------------
# the sign problem
# --------------------------------------------------------------------------


def _spread_row(home_line, away_line, *, home_stale=False):
    return {
        "market": "spreads",
        "line": away_line,
        "cells": {
            "draftkings": {
                "away": {"line": away_line, "stale": False},
                "home": {"line": home_line, "stale": home_stale},
            }
        },
    }


def test_home_spread_is_read_from_the_home_cell_not_the_row_line():
    """`row["line"]` does not say which side it belongs to. Reading it as the
    home line inverts the spread on half the board while looking plausible --
    the exact trap nfl_game_projections' docstring refuses to walk into."""
    row = _spread_row(-6.5, 6.5)
    assert pc._grid_side_line(row, "home") == -6.5
    assert pc._grid_side_line(row, "away") == 6.5
    # And it is NOT just echoing the ambiguous top-level value.
    assert pc._grid_side_line(row, "home") != row["line"]


def test_stale_home_cell_is_used_only_when_no_fresh_one_exists():
    row = {
        "market": "spreads",
        "line": 3.0,
        "cells": {
            "stalebook": {"home": {"line": -2.5, "stale": True}},
            "freshbook": {"home": {"line": -3.0, "stale": False}},
        },
    }
    assert pc._grid_side_line(row, "home") == -3.0

    stale_only = {"market": "spreads", "line": 3.0, "cells": {"stalebook": {"home": {"line": -2.5, "stale": True}}}}
    # A stale line is still correctly SIGNED, so it beats returning nothing.
    assert pc._grid_side_line(stale_only, "home") == -2.5


def test_missing_cells_yield_none_rather_than_a_guessed_sign():
    assert pc._grid_side_line({"market": "spreads", "line": 6.5}, "home") is None
    assert pc._grid_side_line({"market": "spreads", "line": 6.5, "cells": {}}, "home") is None


# --------------------------------------------------------------------------
# the live-grid fallback
# --------------------------------------------------------------------------


_GRID = {
    "generated_at": "2026-08-13T23:19:54Z",
    "rows": [
        {"kind": "game", "segment": "full", "market": "h2h", "home_team": "Cincinnati Bengals", "away_team": "Detroit Lions", "consensus": {"home": -282, "away": 229}},
        {"kind": "game", "segment": "full", "market": "spreads", "home_team": "Cincinnati Bengals", "away_team": "Detroit Lions", "line": 6.5,
         "cells": {"dk": {"away": {"line": 6.5, "stale": False}, "home": {"line": -6.5, "stale": False}}}},
        {"kind": "game", "segment": "full", "market": "totals", "home_team": "Cincinnati Bengals", "away_team": "Detroit Lions", "line": 37.5, "consensus": {"over": -114, "under": -105}},
        # must be ignored: a prop, and a non-full segment
        {"kind": "prop", "segment": "full", "market": "h2h", "home_team": "Cincinnati Bengals", "away_team": "Detroit Lions", "consensus": {"home": 1, "away": 1}},
        {"kind": "game", "segment": "1h", "market": "totals", "home_team": "Cincinnati Bengals", "away_team": "Detroit Lions", "line": 99.0},
    ],
}


@pytest.fixture
def patched_grid(monkeypatch):
    monkeypatch.setattr(
        pc, "nfl_game_state_index",
        lambda season, week, **kw: {"401873272": {"start_time": "2026-08-13T23:00Z", "away_abbr": "DET", "home_abbr": "CIN"}},
    )
    monkeypatch.setattr(pc, "read_book_grid_artifact", lambda sport, date_str: _GRID)


def test_live_grid_supplies_moneyline_spread_and_total(patched_grid):
    index = pc._live_grid_market_index(2026, 2)
    entry = index[("DET", "CIN")]
    assert entry["home_moneyline"] == -282
    assert entry["away_moneyline"] == 229
    assert entry["spread_home"] == -6.5
    assert entry["total_line"] == 37.5


def test_prop_and_non_full_segment_rows_are_excluded(patched_grid):
    entry = pc._live_grid_market_index(2026, 2)[("DET", "CIN")]
    # 99.0 came from the 1h row; -282 would be 1 if the prop row had won.
    assert entry["total_line"] == 37.5
    assert entry["home_moneyline"] == -282


def test_absent_artifact_yields_empty_index_not_an_exception(monkeypatch):
    monkeypatch.setattr(pc, "nfl_game_state_index", lambda season, week, **kw: {"x": {"start_time": "2026-08-13T23:00Z"}})
    monkeypatch.setattr(pc, "read_book_grid_artifact", lambda sport, date_str: None)
    assert pc._live_grid_market_index(2026, 2) == {}


def test_no_dates_means_no_reads(monkeypatch):
    monkeypatch.setattr(pc, "nfl_game_state_index", lambda season, week, **kw: {})
    called = []
    monkeypatch.setattr(pc, "read_book_grid_artifact", lambda sport, date_str: called.append(date_str))
    assert pc._live_grid_market_index(2026, 2) == {}
    assert called == [], "must not read artifacts when no game dates are known"


def test_state_index_failure_degrades_to_empty(monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("espn down")

    monkeypatch.setattr(pc, "nfl_game_state_index", _boom)
    assert pc._live_grid_market_index(2026, 2) == {}


# --------------------------------------------------------------------------
# board game state -- was the literal string "pregame"
# --------------------------------------------------------------------------


def test_board_game_state_reflects_live_and_final():
    index = {
        "401873275": {"in_progress": True, "final": False},
        "401873272": {"in_progress": False, "final": True},
        "401873273": {"in_progress": False, "final": False},
    }
    assert pc._preseason_board_game_state(index, "401873275", "GB", "PIT") == "live"
    assert pc._preseason_board_game_state(index, "401873272", "DET", "CIN") == "final"
    assert pc._preseason_board_game_state(index, "401873273", "IND", "NE") == "pregame"


def test_board_game_state_falls_back_to_team_pair():
    index = {"GB@PIT": {"in_progress": True, "final": False}}
    assert pc._preseason_board_game_state(index, "not-an-espn-id", "GB", "PIT") == "live"


def test_unknown_game_reads_pregame_which_is_the_pre_fix_behaviour():
    # Absence must not become a guess. "pregame" here is the same value the
    # board hardcoded before, so an ESPN outage is a no-op rather than a
    # regression in a new direction.
    assert pc._preseason_board_game_state({}, "999", "AAA", "BBB") == "pregame"
