"""Ask the Syndicate: game-line team trend (lane board-history-charts, 2026-10-10).

A GAME row asked from the board gets each team's last games against TODAY's
line, by the board's own rules (`intelligence.html` `teamForm`).
"""

from __future__ import annotations

import pytest

from syndicate.blueprints import ask_the_syndicate_data as ask
from syndicate.features.shared import team_recent_results as trr

# Newest first, [date, for, against] -- the shape `team_recent_results` returns.
_GAMES = {
    "Home FC": [["2026-10-05", 3, 1], ["2026-09-28", 0, 2], ["2026-09-21", 1, 1]],
    "Away FC": [["2026-10-04", 2, 0], ["2026-09-27", 1, 3]],
}


@pytest.fixture
def stub_history(monkeypatch):
    calls = []

    def fake(sport, team, before, n=10, *, segment="full"):
        calls.append((sport, team, str(before)[:10], n, segment))
        return [list(g) for g in _GAMES.get(team, [])]

    monkeypatch.setattr(trr, "team_recent_results", fake)
    return calls


def _row(**over):
    row = {"kind": "game", "sport": "soccer", "home_team": "Home FC", "away_team": "Away FC",
           "commence_time": "2026-10-10T19:00:00Z", "market": "totals", "side": "over", "line": 2.5}
    row.update(over)
    return row


def _by_team(result):
    return {c["title"].split(" — ")[0]: c for c in result["charts"]}


def test_totals_read_the_game_total_against_todays_line(stub_history):
    out = ask._team_trend_evidence("q", {"board_row": _row()})
    charts = _by_team(out)
    home = charts["Home FC"]
    # Oldest first on the chart; totals 2, 2, 4 against 2.5 -> only the newest is over.
    assert [p["y"] for p in home["points"]] == [2.0, 2.0, 4.0]
    assert [p["hit"] for p in home["points"]] == [False, False, True]
    assert home["points"][-1]["x"] == "10-05"
    assert home["marker"]["y"] == 2.5
    assert "over 2.5 1/3" in home["title"]
    assert out["evidence"]["home"]["record"] == "1/3"


def test_under_inverts_the_hit(stub_history):
    out = ask._team_trend_evidence("q", {"board_row": _row(side="under")})
    assert [p["hit"] for p in _by_team(out)["Home FC"]["points"]] == [True, True, False]


def test_spread_uses_each_teams_own_line(stub_history):
    # Home -1.5: home covers when margin - 1.5 > 0; away gets +1.5.
    out = ask._team_trend_evidence("q", {"board_row": _row(market="spreads", side="home", line=-1.5)})
    charts = _by_team(out)
    home, away = charts["Home FC"], charts["Away FC"]
    assert [p["y"] for p in home["points"]] == [0.0, -2.0, 2.0]
    assert [p["hit"] for p in home["points"]] == [False, False, True]
    assert home["marker"]["y"] == 1.5
    # Away margins oldest first: -2, +2; with +1.5 -> miss, hit.
    assert [p["hit"] for p in away["points"]] == [False, True]
    assert away["marker"]["y"] == -1.5
    assert "covered +1.5" in away["title"]


def test_moneyline_is_won_with_an_even_marker(stub_history):
    out = ask._team_trend_evidence("q", {"board_row": _row(market="h2h", side="away", line=None)})
    away = _by_team(out)["Away FC"]
    assert [p["hit"] for p in away["points"]] == [False, True]
    assert away["marker"] == {"y": 0.0, "label": "Even"}


def test_passes_the_rows_segment_and_date(stub_history):
    ask._team_trend_evidence("q", {"board_row": _row(sport="ncaaf", segment="h1")})
    assert {c[4] for c in stub_history} == {"h1"}
    assert {c[2] for c in stub_history} == {"2026-10-10"}
    assert {c[0] for c in stub_history} == {"ncaaf"}


@pytest.mark.parametrize("row", [
    None,
    {"kind": "prop", "player_name": "X", "market": "player_points"},
    _row(market="btts"),                 # no rule for this market
    _row(line=None),                     # a total with no line
    _row(market="spreads", side="draw"),  # a spread with no team side
])
def test_answers_only_a_gradable_game_row(stub_history, row):
    assert ask._team_trend_evidence("q", {"board_row": row} if row else {}) is None


def test_no_history_is_no_section(monkeypatch):
    monkeypatch.setattr(trr, "team_recent_results", lambda *a, **k: [])
    assert ask._team_trend_evidence("q", {"board_row": _row()}) is None


def test_reachable_through_collect_focused_evidence(stub_history, monkeypatch):
    # Reachability before correctness: the fetcher must run on the real entry
    # point for a game row and its charts must survive the MAX_CHARTS cut.
    for name in ("_soccer_match_evidence",):
        monkeypatch.setattr(ask, name, lambda q, c: None)
    out = ask.collect_focused_evidence("What about the over?", {"sport": "soccer"}, board_row=_row())
    titles = [c["title"] for c in out["charts"]]
    assert any(t.startswith("Home FC — game total") for t in titles)
    assert any(t.startswith("Away FC — game total") for t in titles)
    assert all(c.get("marker") for c in out["charts"] if "game total" in c["title"])


def test_corners_total_gets_no_goal_history(stub_history):
    assert ask._team_trend_evidence("q", {"board_row": _row(market="alternate_totals_corners", line=10.5)}) is None
