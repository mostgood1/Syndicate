"""The live WNBA prop feed was capped by its LINE SOURCE, not by the join.

A live prop row cannot exist without a line, so whatever supplies lines is a
hard ceiling on coverage. `_lines_from_cards` reads the card's FEATURED props --
"8-9 per slate measured" by its own docstring -- and that was the ceiling.

MEASURED IN PRODUCTION 2026-08-22 01:2xZ with two WNBA games live: the lens
published 6 live prop rows total (2 + 4) and the board's join consumed 6 of 6,
every one carrying a live probability. The join was perfect; the feed was the
constraint.
"""

from __future__ import annotations

import csv

import pytest

from syndicate.features.wnba.live_lens import _WIDE_PROP_MARKETS, _lines_from_odds_csv


def _write_csv(root, date_str, rows):
    path = root / "wnba_source" / "data" / "processed"
    path.mkdir(parents=True, exist_ok=True)
    target = path / f"oddsapi_player_props_{date_str}.csv"
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["event_id", "market", "player_name", "point", "bookmaker", "outcome_name"],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return target


@pytest.fixture()
def odds_root(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    return tmp_path


def test_it_reads_every_player_in_the_feed_not_just_the_featured_ones(odds_root):
    _write_csv(odds_root, "2026-08-21", [
        {"event_id": "E1", "market": "player_points", "player_name": "Napheesa Collier",
         "point": "19.5", "bookmaker": "fanduel", "outcome_name": "Over"},
        {"event_id": "E1", "market": "player_rebounds", "player_name": "Alanna Smith",
         "point": "6.5", "bookmaker": "fanduel", "outcome_name": "Over"},
        {"event_id": "E1", "market": "player_assists", "player_name": "Courtney Williams",
         "point": "5.5", "bookmaker": "fanduel", "outcome_name": "Over"},
        {"event_id": "E1", "market": "player_threes", "player_name": "Kayla McBride",
         "point": "2.5", "bookmaker": "fanduel", "outcome_name": "Over"},
    ])
    lines = _lines_from_odds_csv({"event_id": "E1"}, "2026-08-21")
    assert len(lines) == 4
    assert lines[("napheesa collier", "points")] == 19.5
    assert lines[("kayla mcbride", "threes")] == 2.5


def test_the_line_is_the_MODE_across_books_not_the_first_row_seen(odds_root):
    """Books disagree. First-seen would make coverage depend on CSV row order,
    which differs every capture; the mode is the market's own consensus."""
    _write_csv(odds_root, "2026-08-21", [
        {"event_id": "E1", "market": "player_points", "player_name": "Kiki Iriafen",
         "point": "21.5", "bookmaker": "bookA", "outcome_name": "Over"},
        {"event_id": "E1", "market": "player_points", "player_name": "Kiki Iriafen",
         "point": "20.5", "bookmaker": "bookB", "outcome_name": "Over"},
        {"event_id": "E1", "market": "player_points", "player_name": "Kiki Iriafen",
         "point": "20.5", "bookmaker": "bookC", "outcome_name": "Over"},
    ])
    assert _lines_from_odds_csv({"event_id": "E1"}, "2026-08-21")[("kiki iriafen", "points")] == 20.5


def test_a_tie_breaks_low_so_the_choice_is_deterministic(odds_root):
    _write_csv(odds_root, "2026-08-21", [
        {"event_id": "E1", "market": "player_points", "player_name": "A B",
         "point": "20.5", "bookmaker": "bookA", "outcome_name": "Over"},
        {"event_id": "E1", "market": "player_points", "player_name": "A B",
         "point": "19.5", "bookmaker": "bookB", "outcome_name": "Over"},
    ])
    assert _lines_from_odds_csv({"event_id": "E1"}, "2026-08-21")[("a b", "points")] == 19.5


def test_it_is_scoped_to_this_game_the_csv_holds_the_whole_slate(odds_root):
    """A player-name key alone would join across games."""
    _write_csv(odds_root, "2026-08-21", [
        {"event_id": "E1", "market": "player_points", "player_name": "Mine",
         "point": "10.5", "bookmaker": "b", "outcome_name": "Over"},
        {"event_id": "E2", "market": "player_points", "player_name": "Theirs",
         "point": "11.5", "bookmaker": "b", "outcome_name": "Over"},
    ])
    lines = _lines_from_odds_csv({"event_id": "E1"}, "2026-08-21")
    assert list(lines) == [("mine", "points")]


def test_an_unmapped_market_is_skipped_never_guessed(odds_root):
    _write_csv(odds_root, "2026-08-21", [
        {"event_id": "E1", "market": "player_double_double", "player_name": "X Y",
         "point": "0.5", "bookmaker": "b", "outcome_name": "Yes"},
    ])
    assert _lines_from_odds_csv({"event_id": "E1"}, "2026-08-21") == {}


@pytest.mark.parametrize("game,date_str", [
    ({}, "2026-08-21"),                       # no event_id
    ({"event_id": "E1"}, "1999-01-01"),       # no such file
])
def test_it_degrades_to_empty_so_the_caller_falls_back_to_cards(odds_root, game, date_str):
    """Never raises: a failure here must cost the widening, not the lens."""
    assert _lines_from_odds_csv(game, date_str) == {}


def test_the_market_map_covers_exactly_the_four_stats_the_sim_projects():
    from syndicate.features.shared.wnba_live_prop_rows import STAT_MAP

    assert set(_WIDE_PROP_MARKETS.values()) == {label for _, _, label in STAT_MAP}
