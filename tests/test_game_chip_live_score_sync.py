"""A live games-rail card adds up (user 2026-10-20: "the NBA compact game cards arent adding up"). Measured that day,
BOS @ DET Q2: the card read 35-36 beside quarters 28+9 / 27+12. The score came from the worker's artifact (up to 180 s
old) and the quarters from ESPN at serve time. A live NBA / WNBA / NHL chip now takes its score from the period line it
shows."""
from __future__ import annotations

from syndicate.features.shared import game_chip_linescore as gl
from syndicate.features.shared import game_chip_scoreboard as gs


def _chip(state="live", away="35", home="36"):
    return {"sport": "nba", "state": state, "status_token": "Q2 7:40", "start_time_utc": "2026-10-20T19:00:00+00:00",
            "away": {"abbr": "BOS", "key": "boston celtics", "score": away}, "home": {"abbr": "DET", "key": "detroit pistons", "score": home}}


def _run(monkeypatch, chip, box, sport="nba"):
    monkeypatch.setattr(gl, "linescore", lambda *a, **k: box)
    monkeypatch.setattr(gl, "live_clock_token", lambda *a, **k: None)
    monkeypatch.setattr(gl, "live_bonus_text", lambda *a, **k: None)
    monkeypatch.setattr(gl, "mlb_inning_token", lambda *a, **k: None)
    chip["sport"] = sport
    gs._attach_linescore(sport, {"game_id": "401909088"}, chip, "2026-10-20")
    return chip


def test_a_live_card_shows_the_score_of_its_own_quarters(monkeypatch):
    chip = _run(monkeypatch, _chip(), {"kind": "periods", "labels": ["1", "2"], "away": [28, 9], "home": [27, 12]})
    assert (chip["away"]["score"], chip["home"]["score"], chip["leader"]) == ("37", "39", "home")


def test_a_tie_has_no_leader_and_an_incomplete_line_changes_nothing(monkeypatch):
    chip = _run(monkeypatch, _chip(), {"kind": "periods", "labels": ["1", "2"], "away": [28, 11], "home": [27, 12]})
    assert (chip["away"]["score"], chip["home"]["score"], chip["leader"]) == ("39", "39", None)
    chip = _run(monkeypatch, _chip(), {"kind": "periods", "labels": ["1", "2"], "away": [28, None], "home": [27, 12]})
    assert (chip["away"]["score"], chip["home"]["score"]) == ("35", "36")


def test_nhl_in_a_shootout_keeps_its_own_score(monkeypatch):
    box = {"kind": "periods", "labels": ["1", "2", "3", "OT", "SO"], "away": [1, 1, 1, 0, 2], "home": [1, 2, 0, 0, 1]}
    chip = _run(monkeypatch, _chip(away="4", home="3"), box, sport="nhl")
    assert (chip["away"]["score"], chip["home"]["score"]) == ("4", "3")


def test_finals_and_other_sports_are_untouched(monkeypatch):
    final = _run(monkeypatch, _chip(state="final", away="101", home="99"),
                 {"kind": "periods", "labels": ["1", "2", "3", "4"], "away": [25, 25, 25, 25], "home": [25, 25, 25, 25]})
    assert (final["away"]["score"], final["home"]["score"]) == ("101", "99")      # a final keeps its recorded score
    mlb = _run(monkeypatch, _chip(away="3", home="2"), {"kind": "rhe", "labels": ["R", "H", "E"], "away": [3, 7, 0], "home": [2, 5, 1]},
               sport="mlb")
    assert (mlb["away"]["score"], mlb["home"]["score"]) == ("3", "2")


def test_an_empty_or_suppressed_live_score_stays_as_the_worker_left_it(monkeypatch):
    box = {"kind": "periods", "labels": ["1"], "away": [20], "home": [18]}
    empty = _run(monkeypatch, _chip(away=None, home=None), box)
    assert (empty["away"]["score"], empty["home"]["score"]) == (None, None)
    hidden = _chip()
    hidden["score_suppressed"] = "pregame odds only"
    hidden = _run(monkeypatch, hidden, box)
    assert (hidden["away"]["score"], hidden["home"]["score"]) == ("35", "36")
