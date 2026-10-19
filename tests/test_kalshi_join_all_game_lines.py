"""SYNDICATE_KALSHI_JOIN_ALL_GAME_LINES: the Kalshi coverage join also sees every fixture's game lines.

Lane `kalshi-join-all-game-lines` (2026-10-19). Hermetic: the shortlist, the grid artifact, the soccer
odds files and the join itself are stubbed. Off must be byte-identical; on must reach the join.
"""

from __future__ import annotations

import pytest

from pipeline import venue_odds_loop as vol

SHORTLIST = [
    {"sport": "soccer", "event_id": "e-ucl", "market": "h2h", "line": None, "side": "home", "segment": "full",
     "home_team": "Napoli", "away_team": "Real Madrid"},
]
GRID = {"nfl": {"rows": [
    {"event_id": "e-nfl", "market": "spreads", "line": -3.5, "segment": "full", "sides": ["home", "away"],
     "home_team": "Bills", "away_team": "Jets", "commence_time": "2026-10-20T00:20:00Z"},
    {"event_id": "e-nfl", "market": "player_pass_yds", "line": 250.5, "sides": ["over"], "player_name": "QB"},
]}}
SOCCER = {"ucl": [
    {"event_id": "e-ucl", "market": "h2h", "line": "", "side": "Napoli", "home_team": "Napoli", "away_team": "Real Madrid"},
    {"event_id": "e-ucl", "market": "h2h", "line": "", "side": "Draw", "home_team": "Napoli", "away_team": "Real Madrid"},
    {"event_id": "e-ucl", "market": "totals", "line": "2.5", "side": "Over", "home_team": "Napoli", "away_team": "Real Madrid"},
    {"event_id": "e-ucl", "market": "btts", "line": "", "side": "Yes", "home_team": "Napoli", "away_team": "Real Madrid"},
]}


@pytest.fixture
def stubs(monkeypatch):
    from syndicate.features.shared import book_grid_artifact
    from syndicate.features.soccer import sources

    monkeypatch.setattr(book_grid_artifact, "read_book_grid_artifact", lambda sport, day: GRID.get(sport))
    monkeypatch.setattr(sources, "game_odds_rows", lambda league: tuple(SOCCER.get(league, ())))


def test_off_is_the_shortlist_itself_and_reads_nothing(monkeypatch):
    monkeypatch.delenv("SYNDICATE_KALSHI_JOIN_ALL_GAME_LINES", raising=False)
    monkeypatch.setattr(vol, "all_game_line_rows", lambda day: pytest.fail("read while OFF"))
    rows = list(SHORTLIST)
    assert vol.kalshi_join_rows(rows, "2026-10-20") is rows


@pytest.mark.parametrize("value", ["", "0", "false", "off"])
def test_absent_or_falsy_is_off(monkeypatch, value):
    monkeypatch.setenv("SYNDICATE_KALSHI_JOIN_ALL_GAME_LINES", value)
    assert vol.kalshi_join_all_game_lines_enabled() is False


def test_on_adds_every_game_line_side_once_and_the_shortlist_row_wins(monkeypatch, stubs):
    monkeypatch.setenv("SYNDICATE_KALSHI_JOIN_ALL_GAME_LINES", "1")
    rows = vol.kalshi_join_rows(list(SHORTLIST), "2026-10-20")
    keys = [(r["event_id"], r["market"], r["line"], r["side"]) for r in rows]
    assert rows[0] is SHORTLIST[0]
    # The shortlist's own Napoli h2h home row is not duplicated; draw + totals + both NFL spread sides are added.
    assert keys.count(("e-ucl", "h2h", None, "home")) == 1
    assert ("e-ucl", "h2h", None, "draw") in keys and ("e-ucl", "totals", 2.5, "over") in keys
    assert ("e-nfl", "spreads", -3.5, "home") in keys and ("e-nfl", "spreads", -3.5, "away") in keys
    # Props and non-game-line markets never enter.
    assert not any(r["market"] in ("btts", "player_pass_yds") for r in rows)
    assert len(rows) == 1 + 2 + 2


def test_a_failing_source_degrades_to_the_other(monkeypatch, stubs, capsys):
    from syndicate.features.shared import book_grid_artifact

    monkeypatch.setenv("SYNDICATE_KALSHI_JOIN_ALL_GAME_LINES", "on")
    monkeypatch.setattr(book_grid_artifact, "read_book_grid_artifact", lambda sport, day: 1 / 0)
    rows = vol.all_game_line_rows("2026-10-20")
    assert {r["sport"] for r in rows} == {"soccer"}
    assert "ALL_GAME_LINES_GRID_FAILED" in capsys.readouterr().out


def test_reachability_the_coverage_loop_hands_the_join_more_rows_only_when_on(monkeypatch, stubs):
    """off != on through `_maybe_kalshi_board_coverage` itself, not the helper."""
    import pipeline.intelligence_state as ist
    import pipeline.kalshi_odds_refresh as kor

    seen: list[int] = []
    monkeypatch.setattr(ist, "read_layer2_shortlist", lambda day: {"rows": list(SHORTLIST)})
    monkeypatch.setattr(kor, "join_to_board", lambda markets, rows, selected_date=None: seen.append(len(rows)))
    counts = {}
    for flag in ("", "1"):
        monkeypatch.setenv("SYNDICATE_KALSHI_JOIN_ALL_GAME_LINES", flag)
        vol._LAST_KALSHI_COVERAGE_AT[0] = -1e12
        seen.clear()
        vol._maybe_kalshi_board_coverage({"markets": [{"ticker": "KX-1"}]})
        counts[flag] = list(seen)
    assert counts[""] == [1, 1, 1]          # today .. +2, shortlist only
    assert counts["1"] == [5, 5, 5]         # + 4 game-line side rows each day
    assert counts[""] != counts["1"]
