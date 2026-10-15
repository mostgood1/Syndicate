"""Interval history: each team's recent inning / quarter / half / period scores for a segment pick's case (user
2026-10-15: "we should fix the gaps - for example we need the interval data")."""
from __future__ import annotations

import json

from syndicate.features.shared import interval_history as ih


def _mlb_game(day, home, away, home_runs, away_runs, *, game_type="R", state="Final"):
    innings = [{"num": i + 1, "home": {"runs": h} if h is not None else {}, "away": {"runs": a}}
               for i, (h, a) in enumerate(zip(home_runs, away_runs))]
    return {"gameType": game_type, "status": {"abstractGameState": state, "codedGameState": "F" if state == "Final" else "I"},
            "teams": {"home": {"team": {"name": home}}, "away": {"team": {"name": away}}}, "linescore": {"innings": innings}}


def _espn_event(home, away, home_q, away_q, *, season_type=2, completed=True):
    side = lambda name, q, ha: {"homeAway": ha, "team": {"displayName": name},
                                "linescores": [{"value": v, "period": i + 1} for i, v in enumerate(q)]}
    return {"season": {"type": season_type}, "status": {"type": {"completed": completed, "state": "post" if completed else "in"}},
            "competitions": [{"competitors": [side(home, home_q, "home"), side(away, away_q, "away")]}]}


def test_segments_are_summed_as_the_grader_settles_them():
    assert ih.segment_sum([1, 0, 2, 0, 0, 3, 0, 0, 1], ih.SEGMENTS["mlb"]["first3"]) == 3
    assert ih.segment_sum([7, 3, 10, 0, 6], ih.SEGMENTS["nfl"]["h2"]) == 16          # q3 + q4 + overtime
    assert ih.segment_sum([7, 3, 10, 0, 6], ih.SEGMENTS["nfl"]["q4"]) == 0
    assert ih.segment_sum([1, None, 2], ih.SEGMENTS["mlb"]["first3"]) is None         # a hole is never a zero
    assert ih.segment_sum([1, 0], ih.SEGMENTS["mlb"]["first3"]) is None               # a game that never got there


def test_mlb_reads_regular_season_and_postseason_innings_and_caches_decided_past_dates(tmp_path):
    calls = []
    payload = {"dates": [
        {"date": "2026-10-13", "games": [_mlb_game("2026-10-13", "Los Angeles Dodgers", "Milwaukee Brewers",
                                                   [0, 2, 0, 1, 0], [1, 0, 0, 0, 0], game_type="L")]},
        {"date": "2026-10-12", "games": [_mlb_game("2026-10-12", "Milwaukee Brewers", "Los Angeles Dodgers",
                                                   [0, 0, 1, 0, 0], [0, 0, 1, 0, 0], game_type="L"),
                                         _mlb_game("2026-10-12", "Milwaukee Brewers", "X", [9, 9, 9], [0, 0, 0], game_type="S")]},
    ]}

    def fetch(url):
        calls.append(url)
        return payload

    h = ih.IntervalHistory(tmp_path, today="2026-10-15", fetch=fetch)
    got = h.team_results("mlb", "Milwaukee Brewers", "2026-10-16T00:00:00Z", "first3")
    assert got == [["2026-10-13", 1.0, 2.0], ["2026-10-12", 1.0, 1.0]]                # spring training left out
    assert len(calls) == 1 and "startDate=" in calls[0] and "hydrate=linescore" in calls[0]   # one call for the range
    assert json.loads((tmp_path / "mlb" / "2026-10-13.json").read_text())[0]["home"] == "Los Angeles Dodgers"
    again = ih.IntervalHistory(tmp_path, today="2026-10-15", fetch=lambda url: (_ for _ in ()).throw(AssertionError(url)))
    assert again.team_results("mlb", "Los Angeles Dodgers", "2026-10-16", "first1")[0] == ["2026-10-13", 0.0, 1.0]   # from disk
    assert h.team_results("mlb", "Milwaukee Brewers", "2026-10-16", "q1") == []        # not an MLB segment


def test_espn_sports_read_periods_skip_preseason_and_leave_an_unfinished_date_uncached(tmp_path):
    boards = {
        "20261014": {"events": [_espn_event("Toronto Maple Leafs", "Buffalo Sabres", [1, 0, 2], [0, 1, 0]),
                                _espn_event("Toronto Maple Leafs", "Ottawa Senators", [3, 0, 0], [0, 0, 0], season_type=1)]},
        "20261013": {"events": [_espn_event("Montreal Canadiens", "Toronto Maple Leafs", [0, 2, 1], [1, 1, 1], completed=False)]},
    }
    fetch = lambda url: boards.get(url.split("dates=")[1][:8], {"events": []})
    h = ih.IntervalHistory(tmp_path, today="2026-10-15", fetch=fetch)
    assert h.team_results("nhl", "Toronto Maple Leafs", "2026-10-15", "p1") == [["2026-10-14", 1.0, 0.0]]
    assert (tmp_path / "nhl" / "2026-10-14.json").is_file() and not (tmp_path / "nhl" / "2026-10-13.json").exists()
    assert h.fetches <= ih.DEFAULT_WINDOW_DAYS


def test_ncaaf_defers_to_its_local_line_scores(monkeypatch, tmp_path):
    from syndicate.features.shared import team_recent_results as trr

    monkeypatch.setattr(trr, "team_recent_results", lambda sport, team, before, n=10, *, segment="full": [["2026-10-10", 7.0, 3.0]])
    h = ih.IntervalHistory(tmp_path, today="2026-10-15", fetch=lambda url: (_ for _ in ()).throw(AssertionError(url)))
    assert h.team_results("ncaaf", "Texas State Bobcats", "2026-10-15", "h1") == [["2026-10-10", 7.0, 3.0]]
