"""Todo #844 -- a grid row's newest observation is chosen by TIME, not by TEXT.

`book_grid` took a row's `updated_at` / `age_seconds` from `max(stamps)` over the cells'
`observed_at` strings. College sportsbooks stamp `2026-11-18 20:58:05+00:00` (a space) and
Kalshi / Polymarket `2026-11-18T20:55:57Z` (a `T`); `T` sorts above a space, so the venue's
stamp won whatever its time and the live gate (`quote_age_verdict`, 120 s for NCAAB) refused
rows a sportsbook had just moved. Measured on the fleet's NCAAB moneylines 11-17/18: 68.6% of
the fresh live minutes read stale. These tests fail on the text max.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from syndicate.features.shared import book_grid
from syndicate.features.shared.book_grid import build_book_grid
from syndicate.features.shared.live_gameline_join import quote_age_verdict

NOW = datetime(2026, 11, 18, 20, 58, 20, tzinfo=timezone.utc)
ENV = "SYNDICATE_BOOK_GRID_NEWEST_BY_TIME"

BOOK_STAMP = "2026-11-18 20:58:05+00:00"  # college sportsbook spelling, 15 s before NOW
VENUE_STAMP = "2026-11-18T20:55:57Z"  # Kalshi spelling, 143 s before NOW


def _quote(**overrides):
    row = {
        "sport": "ncaab",
        "kind": "game",
        "event_id": "evt-844",
        "segment": "full",
        "market": "h2h",
        "player_name": "",
        "selection": "home",
        "line": None,
        "price": -810,
        "bookmaker": "fanduel",
        "home_team": "Notre Dame Fighting Irish",
        "away_team": "Rutgers Scarlet Knights",
        "commence_time": "2026-11-18T19:00:00Z",
    }
    row.update(overrides)
    return row


def _moneyline(book_stamp, venue_stamp, venue="kalshi"):
    return [
        _quote(selection="home", price=-810, bookmaker="fanduel", book_updated_at=book_stamp),
        _quote(selection="away", price=+500, bookmaker="fanduel", book_updated_at=book_stamp),
        _quote(selection="home", price=-700, bookmaker=venue, book_updated_at=venue_stamp),
        _quote(selection="away", price=+450, bookmaker=venue, book_updated_at=venue_stamp),
    ]


@pytest.fixture(autouse=True)
def _switch_on(monkeypatch):
    # Default OFF on main (betting-change window rule 2); these tests exercise it switched ON.
    monkeypatch.setenv(ENV, "on")


def _only_row(rows):
    grid = build_book_grid(rows, now=NOW)
    assert len(grid) == 1, grid
    return grid[0]


def test_a_fresher_sportsbook_stamp_beats_an_older_venue_stamp():
    row = _only_row(_moneyline(BOOK_STAMP, VENUE_STAMP))
    # The text max would pick the venue's `T` stamp (143 s old); the newest by time is the book's.
    assert row["updated_at"] == BOOK_STAMP
    assert row["age_seconds"] == 15.0


def test_the_live_gate_prices_the_row_a_sportsbook_just_moved():
    row = _only_row(_moneyline(BOOK_STAMP, VENUE_STAMP))
    assert quote_age_verdict(row["age_seconds"], sport="ncaab") is None


def test_a_newer_venue_stamp_still_wins():
    row = _only_row(_moneyline("2026-11-18 20:55:57+00:00", "2026-11-18T20:58:05Z"))
    assert row["updated_at"] == "2026-11-18T20:58:05Z"
    assert row["age_seconds"] == 15.0


def test_off_differs_from_on_on_the_same_input(monkeypatch):
    # Reachability: off != on.
    monkeypatch.setenv(ENV, "off")
    off = _only_row(_moneyline(BOOK_STAMP, VENUE_STAMP))
    monkeypatch.setenv(ENV, "on")
    on = _only_row(_moneyline(BOOK_STAMP, VENUE_STAMP))
    assert off["updated_at"] == VENUE_STAMP and off["age_seconds"] == 143.0
    assert on["updated_at"] == BOOK_STAMP and on["age_seconds"] == 15.0


@pytest.mark.parametrize("value", [None, "", "off", "0", "false", "maybe"])
def test_absent_or_anything_but_on_keeps_the_old_text_max(monkeypatch, value):
    # DEFAULT OFF: a fleet ff before the window must not change the grid.
    if value is None:
        monkeypatch.delenv(ENV, raising=False)
    else:
        monkeypatch.setenv(ENV, value)
    row = _only_row(_moneyline(BOOK_STAMP, VENUE_STAMP))
    assert row["updated_at"] == VENUE_STAMP and row["age_seconds"] == 143.0


@pytest.mark.parametrize("value", ["on", "1", "true", "yes", " ON "])
def test_on_spellings_enable_it(monkeypatch, value):
    monkeypatch.setenv(ENV, value)
    assert _only_row(_moneyline(BOOK_STAMP, VENUE_STAMP))["updated_at"] == BOOK_STAMP


@pytest.mark.parametrize(
    "stamps",
    [
        ["2026-11-18T20:41:51Z", "2026-11-18T20:58:05Z", "2026-11-18T20:55:57Z"],
        ["2026-11-18 20:41:51+00:00", "2026-11-18 20:58:05+00:00"],
        ["2026-11-18T20:58:05.120000+00:00", "2026-11-18T20:58:05.900000+00:00"],
    ],
)
def test_one_spelling_gives_the_same_answer_as_before(stamps):
    # NBA / NHL shape: every stamp shares one spelling, so text order is time order and the
    # grid must not change.
    assert book_grid._newest_stamp(list(stamps)) == max(stamps)


def test_offsets_are_compared_as_instants():
    # 14:58:05-06:00 is 20:58:05Z, newer than 20:57:00Z, though it sorts lower as text.
    stamps = ["2026-11-18T20:57:00Z", "2026-11-18T14:58:05-06:00"]
    assert max(stamps) == "2026-11-18T20:57:00Z"
    assert book_grid._newest_stamp(stamps) == "2026-11-18T14:58:05-06:00"


def test_equal_instants_keep_the_text_max():
    stamps = ["2026-11-18 20:58:05+00:00", "2026-11-18T20:58:05Z"]
    assert book_grid._newest_stamp(stamps) == max(stamps)


def test_an_unparseable_stamp_is_skipped_when_another_parses():
    stamps = ["not-a-time", "2026-11-18 20:58:05+00:00"]
    assert max(stamps) == "not-a-time"
    assert book_grid._newest_stamp(stamps) == "2026-11-18 20:58:05+00:00"


def test_no_stamp_parses_keeps_the_text_max():
    stamps = ["zz", "aa"]
    assert book_grid._newest_stamp(stamps) == "zz"


def test_empty_is_none():
    assert book_grid._newest_stamp([]) is None
