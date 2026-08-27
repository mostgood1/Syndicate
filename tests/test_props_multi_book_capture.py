"""Both prop captures must keep every book they were already paid for.

`#209` Class A, in two different disguises. NFL discarded the other books at
SELECTION (`_choose_bookmaker` picked one); soccer swept them all with
`_ordered_bookmakers` and then discarded them at DEDUPE (`seen_market_rows` had
no book term, so the first book claimed each selection). Same loss, same cost:
neither CSV could answer "who has the best price" while price shopping measured
+2.79 ROI pts on MLB game lines and +2.95 on NFL props.

These are off/on tests. Each asserts a count that is 1 under the old behaviour
and N under the new one, so a regression cannot pass them quietly.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(module_name: str):
    """Import a `scripts/` fetcher by path -- they are standalone entrypoints,
    not part of an importable package."""
    path = REPO_ROOT / "scripts" / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


nfl_fetch = _load("fetch_nfl_oddsapi_props_local")
soccer_fetch = _load("fetch_soccer_oddsapi_props_local")


# --------------------------------------------------------------------------
# NFL
# --------------------------------------------------------------------------


def _nfl_book(key, outcomes, market_key="player_anytime_td"):
    return {"key": key, "markets": [{"key": market_key, "outcomes": outcomes}]}


def _nfl_event(bookmakers):
    return {
        "away_team": "New England Patriots",
        "home_team": "Seattle Seahawks",
        "commence_time": "2026-09-10T00:15:00Z",
        "bookmakers": bookmakers,
    }


def test_nfl_keeps_every_book_not_one():
    """Production's real week-1 capture on 2026-08-27 was 294 rows and
    `{draftkings: 294}` -- one book across the entire market. Under the old
    `_choose_bookmaker` this returns 1 row; it must return 3."""
    event = _nfl_event([
        _nfl_book("draftkings", [{"description": "A.J. Brown", "name": "Yes", "price": 150}]),
        _nfl_book("betonlineag", [{"description": "A.J. Brown", "name": "Yes", "price": 230}]),
        _nfl_book("fanduel", [{"description": "A.J. Brown", "name": "Yes", "price": 120}]),
    ])

    rows = nfl_fetch.parse_events_to_rows([event])

    assert len(rows) == 3
    assert {row["book"] for row in rows} == {"draftkings", "betonlineag", "fanduel"}
    assert {row["over_price"] for row in rows} == {150, 230, 120}


def test_nfl_distinct_lines_survive_as_distinct_rows():
    """The aggregation key ignored `line`, so a market quoting one player at two
    lines kept only whichever arrived last -- silently, with no duplicate to
    notice. Returns 1 row under the old key, 2 under (player, line)."""
    event = _nfl_event([
        _nfl_book(
            "draftkings",
            [
                {"description": "Drake Maye", "name": "Over", "price": -110, "point": 250.5},
                {"description": "Drake Maye", "name": "Over", "price": 140, "point": 275.5},
            ],
            market_key="player_pass_yds",
        )
    ])

    rows = nfl_fetch.parse_events_to_rows([event])

    assert len(rows) == 2
    assert sorted(row["line"] for row in rows) == [250.5, 275.5]


def test_nfl_over_and_under_of_the_same_line_still_meet_in_one_row():
    """The line is in the key, not the side -- otherwise adding the line term
    would split a two-sided market into two half-priced rows."""
    event = _nfl_event([
        _nfl_book(
            "draftkings",
            [
                {"description": "Drake Maye", "name": "Over", "price": -110, "point": 250.5},
                {"description": "Drake Maye", "name": "Under", "price": -105, "point": 250.5},
            ],
            market_key="player_pass_yds",
        )
    ])

    rows = nfl_fetch.parse_events_to_rows([event])

    assert len(rows) == 1
    assert rows[0]["over_price"] == -110
    assert rows[0]["under_price"] == -105


# --------------------------------------------------------------------------
# Soccer
# --------------------------------------------------------------------------


def _soccer_book(key, price, market_key="player_goal_scorer_anytime"):
    return {
        "key": key,
        "markets": [{"key": market_key, "outcomes": [{"description": "Bukayo Saka", "name": "Yes", "price": price}]}],
    }


def test_soccer_keeps_every_book_not_just_the_first_preferred():
    """`_ordered_bookmakers` already swept every book; `seen_market_rows` then
    dropped all but the first because its key carried no book term. Returns 1
    row under the old key, 3 under the new one."""
    event = {
        "id": "evt-1",
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "commence_time": "2026-08-30T14:00:00Z",
        "bookmakers": [
            _soccer_book("draftkings", 175),
            _soccer_book("fanduel", 190),
            _soccer_book("betmgm", 165),
        ],
    }

    rows = soccer_fetch.parse_event_to_rows(event, league="epl")

    assert len(rows) == 3
    assert {row["book"] for row in rows} == {"draftkings", "fanduel", "betmgm"}
    assert {row["over_price"] for row in rows} == {175, 190, 165}


def test_soccer_still_collapses_a_book_that_quotes_the_same_selection_twice():
    """The dedupe must keep doing its real job -- one row per
    (book, market, player, line) -- rather than being removed outright."""
    duplicated = {
        "key": "draftkings",
        "markets": [
            {
                "key": "player_goal_scorer_anytime",
                "outcomes": [
                    {"description": "Bukayo Saka", "name": "Yes", "price": 175},
                    {"description": "Bukayo Saka", "name": "Yes", "price": 175},
                ],
            }
        ],
    }
    event = {
        "id": "evt-2",
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "commence_time": "2026-08-30T14:00:00Z",
        "bookmakers": [duplicated],
    }

    rows = soccer_fetch.parse_event_to_rows(event, league="epl")

    assert len(rows) == 1


def test_soccer_distinct_lines_from_one_book_are_distinct_rows():
    event = {
        "id": "evt-3",
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "commence_time": "2026-08-30T14:00:00Z",
        "bookmakers": [
            {
                "key": "draftkings",
                "markets": [
                    {
                        "key": "player_shots_on_target",
                        "outcomes": [
                            {"description": "Bukayo Saka", "name": "Over", "price": -110, "point": 0.5},
                            {"description": "Bukayo Saka", "name": "Over", "price": 145, "point": 1.5},
                        ],
                    }
                ],
            }
        ],
    }

    rows = soccer_fetch.parse_event_to_rows(event, league="epl")

    assert len(rows) == 2
    assert sorted(row["line"] for row in rows) == [0.5, 1.5]
