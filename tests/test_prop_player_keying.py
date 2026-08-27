"""A player prop's join key must name its player, on BOTH sides of the join.

THE DEFECT THIS PINS. `venue_quote_fanin._candidate_keys` built
`<sport>|<market>|<side>|<line>` for every row. That is complete for a game
line and dangerously incomplete for a prop: every player's anytime-scorer row
collapsed to the single string `soccer|player_goal_scorer_anytime|yes`, and
every 2.5-three-pointer row to `wnba|player_threes|over|2.5`. Rows sharing a
key are indistinguishable to `apply_venue_quotes` -- the first wins, and the
quote it wins describes a different human.

`kalshi_board_join` -- the other join over the same markets -- has always keyed
props as `market|normalize_person(subject)|line`. This brings the venue fan-in
onto that shape and reuses that module's own normaliser.

AND IT IS WHAT UNBLOCKS SOCCER. Measured 2026-08-27, soccer's 15,082 unmatched
rows are ALL player props, and the OddsAPI props capture (2,720 rows, 4 books)
carries `market_key` values that are already the board's own market tokens.
Nothing needed translating; the file had no reader, and a player-blind key
could not have been given one safely.
"""

from __future__ import annotations

import csv
import os
import tempfile
from pathlib import Path

import pytest

from syndicate.features.shared.venue_quote_adapters import (
    oddsapi_props_outcome,
    prop_quote_key,
    quote_key,
)
from syndicate.features.shared.venue_quote_fanin import _candidate_keys


HEADER = [
    "league", "player", "market", "market_key", "line", "over_price",
    "under_price", "book", "event", "event_id", "game_time", "home_team", "away_team",
]


def _row(player, market_key, line="", over="", under="", book="draftkings"):
    return ["ligue_1", player, "m", market_key, line, over, under, book,
            "Strasbourg v RC Lens", "e1", "2026-08-27T19:00:00Z", "Strasbourg", "RC Lens"]


@pytest.fixture
def capture(monkeypatch):
    """A real-shaped props capture at a temp soccer root."""
    def _build(rows, stem="2026-08-27", league="ligue_1"):
        root = Path(tempfile.mkdtemp()) / "soccer_source"
        d = root / league / "props"
        d.mkdir(parents=True, exist_ok=True)
        with (d / f"{stem}.csv").open("w", encoding="utf-8", newline="") as h:
            w = csv.writer(h)
            w.writerow(HEADER)
            for r in rows:
                w.writerow(r)
        monkeypatch.setenv("SYNDICATE_SOCCER_SOURCE_ROOT", str(root))
        monkeypatch.delenv("SYNDICATE_DATA_ROOT", raising=False)
        return root
    return _build


# ---------------------------------------------------------------------------
# 1. the board side
# ---------------------------------------------------------------------------


def test_a_prop_row_keys_on_its_player():
    row = {"market": "player_goal_scorer_anytime", "side": "yes", "line": None,
           "entity": "Abdallah Sima"}

    assert _candidate_keys(row, "soccer") == ["soccer|player_goal_scorer_anytime|abdallah sima|yes"]


def test_two_players_in_the_same_market_DO_NOT_share_a_key():
    """THE DEFECT, stated as the test that would have caught it. Before this,
    both rows produced `soccer|player_goal_scorer_anytime|yes` and whichever
    was seen first took the other's quote."""
    a = {"market": "player_goal_scorer_anytime", "side": "yes", "line": None, "entity": "Abdallah Sima"}
    b = {"market": "player_goal_scorer_anytime", "side": "yes", "line": None, "entity": "Bradley Barcola"}

    assert _candidate_keys(a, "soccer") != _candidate_keys(b, "soccer")


def test_the_same_player_at_two_lines_does_not_share_a_key():
    a = {"market": "player_shots", "side": "over", "line": 1.5, "entity": "Bradley Barcola"}
    b = {"market": "player_shots", "side": "over", "line": 3.5, "entity": "Bradley Barcola"}

    assert _candidate_keys(a, "soccer") != _candidate_keys(b, "soccer")


def test_an_unnameable_player_yields_NO_key_rather_than_a_blind_one():
    """A blind key would launder someone else's freshness onto this row. No key
    means the row goes unmatched and keeps its own age, which is honest."""
    row = {"market": "player_shots", "side": "over", "line": 1.5, "entity": "   "}

    assert _candidate_keys(row, "soccer") == []


def test_a_game_line_row_is_completely_unchanged():
    """Game markets carry no entity (`market_inventory`: "None for game
    markets"), so they must take the original path untouched."""
    row = {"market": "totals", "side": "over", "line": 2.5, "home_team": "Strasbourg",
           "away_team": "RC Lens"}

    assert _candidate_keys(row, "soccer") == [quote_key("soccer", "totals", "over", 2.5)]


def test_prop_quote_key_refuses_an_empty_player():
    assert prop_quote_key("soccer", "player_shots", "", "over", 1.5) is None
    assert prop_quote_key("soccer", "player_shots", None, "over", 1.5) is None


def test_punctuation_and_accents_do_not_split_a_player():
    """One normaliser on both sides -- `kalshi_board_join.normalize_person`."""
    assert prop_quote_key("soccer", "m", "Kylian Mbappé", "yes", None) == \
           prop_quote_key("soccer", "m", "Kylian Mbappe", "yes", None)


# ---------------------------------------------------------------------------
# 2. the venue side -- the capture that had no reader
# ---------------------------------------------------------------------------


def test_the_capture_becomes_quotes_the_board_can_meet(capture):
    capture([_row("Abdallah Sima", "player_goal_scorer_anytime", over="230")])

    out = oddsapi_props_outcome("soccer", "2026-08-27")
    keys = {q.key for q in out.quotes}

    assert out.status == "ok"
    board = _candidate_keys(
        {"market": "player_goal_scorer_anytime", "side": "yes", "line": None,
         "entity": "Abdallah Sima"}, "soccer")
    assert board[0] in keys, (board, sorted(keys))


def test_best_price_wins_across_books(capture):
    """647 of 1,529 ligue_1 selections were quoted by more than one book on
    2026-08-27. The board renders one row; it should get the best price."""
    capture([
        _row("Abdallah Sima", "player_goal_scorer_anytime", over="230", book="draftkings"),
        _row("Abdallah Sima", "player_goal_scorer_anytime", over="180", book="fanduel"),
        _row("Abdallah Sima", "player_goal_scorer_anytime", over="195", book="betmgm"),
    ])

    out = oddsapi_props_outcome("soccer", "2026-08-27")

    assert len(out.quotes) == 1
    assert out.quotes[0].american == 230


def test_a_threshold_market_publishes_both_legs(capture):
    capture([_row("Bradley Barcola", "player_shots_on_target", line="1.5", over="-110", under="120")])

    keys = {q.key for q in oddsapi_props_outcome("soccer", "2026-08-27").quotes}

    assert "soccer|player_shots_on_target|bradley barcola|over|1.5" in keys
    assert "soccer|player_shots_on_target|bradley barcola|under|1.5" in keys


def test_a_yes_priced_market_carries_no_line(capture):
    """`player_goal_scorer_anytime` has no threshold; a line here would build a
    key no board row asks for."""
    capture([_row("Abdallah Sima", "player_goal_scorer_anytime", over="230")])

    q = oddsapi_props_outcome("soccer", "2026-08-27").quotes[0]

    assert q.line is None
    assert q.side == "yes"
    assert q.key.endswith("|yes")


def test_only_the_newest_capture_per_league_is_read(capture, monkeypatch):
    """A capture is filed under the day it RAN, so the window spans days. Using
    all of them would mix a stale price into today's quotes and let
    `fetched_at` describe the newest FILE rather than the row."""
    root = capture([_row("Abdallah Sima", "player_goal_scorer_anytime", over="100")], stem="2026-08-25")
    d = root / "ligue_1" / "props"
    with (d / "2026-08-27.csv").open("w", encoding="utf-8", newline="") as h:
        w = csv.writer(h)
        w.writerow(HEADER)
        w.writerow(_row("Abdallah Sima", "player_goal_scorer_anytime", over="230"))

    out = oddsapi_props_outcome("soccer", "2026-08-27")

    assert len(out.quotes) == 1
    assert out.quotes[0].american == 230, "read the stale capture instead of the fresh one"


def test_a_row_with_no_price_is_counted_not_published(capture):
    capture([_row("Abdallah Sima", "player_goal_scorer_anytime", over="")])

    out = oddsapi_props_outcome("soccer", "2026-08-27")

    assert out.quotes == []
    assert "leg_without_price" in (out.reason or "")


def test_another_sport_is_refused_BY_NAME(capture):
    """NFL props live at a different path under a different schema (keyed by
    week, not date). Extending this is real work, not a path tweak, and the
    refusal says so rather than reporting an empty feed."""
    capture([_row("Abdallah Sima", "player_goal_scorer_anytime", over="230")])

    out = oddsapi_props_outcome("nfl", "2026-08-27")

    assert out.status == "no_rows"
    assert "nfl" in (out.reason or "")


def test_no_capture_in_the_window_is_named_too(capture):
    capture([_row("Abdallah Sima", "player_goal_scorer_anytime", over="230")], stem="2026-01-01")

    out = oddsapi_props_outcome("soccer", "2026-08-27")

    assert out.status == "no_rows"
    assert out.reason == "no_props_capture_within_window"


# ---------------------------------------------------------------------------
# 3. per-sport selection attribution
# ---------------------------------------------------------------------------


def test_selections_are_attributed_per_sport():
    """`selected_by_source` is one global tally across every sport, so it cannot
    answer "is kalshi matching soccer?" -- a source carrying one sport entirely
    and contributing nothing to another reads identically. Measured 2026-08-27,
    it showed `kalshi: 2533` across five sports at once."""
    from syndicate.features.shared.venue_quote_fanin import Quote, apply_venue_quotes

    now = 1_787_000_000.0
    quotes = {
        "soccer|totals|over|2.5": Quote(
            key="soccer|totals|over|2.5", source="polymarket_us", sport="soccer",
            market="totals", side="over", probability=0.5, american=100,
            line=2.5, fetched_at=now),
        "nfl|totals|over|44.5": Quote(
            key="nfl|totals|over|44.5", source="kalshi", sport="nfl",
            market="totals", side="over", probability=0.5, american=100,
            line=44.5, fetched_at=now),
    }
    collected = {
        "soccer": {"quotes": quotes, "by_source": {}, "ceiling_seconds": 86400},
        "nfl": {"quotes": quotes, "by_source": {}, "ceiling_seconds": 21600},
    }
    rows = [
        {"sport": "soccer", "market": "totals", "side": "over", "line": 2.5},
        {"sport": "nfl", "market": "totals", "side": "over", "line": 44.5},
    ]

    result = apply_venue_quotes(rows, "2026-08-27", collected_by_sport=collected, now=now)
    by_sport = result["selected_by_source_by_sport"]

    assert by_sport["soccer"] == {"polymarket_us": 1}
    assert by_sport["nfl"] == {"kalshi": 1}
    # And the global tally still says what it always said.
    assert result["selected_by_source"] == {"polymarket_us": 1, "kalshi": 1}


def test_a_sport_that_won_nothing_is_absent_rather_than_zero_filled():
    """"produced no rows" and "every row lost" are different facts;
    `unmatched_by_sport` beside this is what tells them apart."""
    from syndicate.features.shared.venue_quote_fanin import apply_venue_quotes

    now = 1_787_000_000.0
    collected = {"soccer": {"quotes": {}, "by_source": {}, "ceiling_seconds": 86400}}
    rows = [{"sport": "soccer", "market": "totals", "side": "over", "line": 2.5}]

    result = apply_venue_quotes(rows, "2026-08-27", collected_by_sport=collected, now=now)

    assert "soccer" not in result["selected_by_source_by_sport"]
    assert result["unmatched_by_sport"]["soccer"] == 1
