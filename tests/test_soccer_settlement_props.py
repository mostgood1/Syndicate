"""Soccer board-pick props: did-not-appear void, first/last goalscorer, nested names (lane soccer-live-anytime-scorer, 2026-10-13).

Measured on the 10-11 board: 1,181 soccer prop picks still pending after the 11:00Z settle -- 501 first/last
goalscorer (no grader), 314 on squad players who never came on (books void them), ~138 name spellings the
fallback missed. User decisions 2026-10-13: borrow `settlement_identity.py`; own goals do not count for
first/last goalscorer.
"""
from __future__ import annotations

import csv
import json

from syndicate.features.shared import settlement_identity as si
from syndicate.features.shared import settlement_sport_rows as rows

EVENT = "401879266"
GOALS = [
    {"team": "Chelsea", "scorer": "Levi Colwill", "clock_seconds": 300.0, "own_goal": True, "penalty": False},
    {"team": "Arsenal", "scorer": "Bukayo Saka", "clock_seconds": 900.0, "own_goal": False, "penalty": False},
    {"team": "Arsenal", "scorer": "João Pedro", "clock_seconds": 4000.0, "own_goal": False, "penalty": False},
    {"team": "Arsenal", "scorer": "Gabriel Jesus", "clock_seconds": 5300.0, "own_goal": True, "penalty": False},
]


def _player(pid, name, appeared=True, goals=0.0, shots=0.0):
    return {"player_id": pid, "player_name": name, "appeared": appeared, "goals": goals, "assists": 0.0,
            "shots": shots, "shots_on_target": 0.0}


def _write(root, *, with_box=True, goals=GOALS):
    league = root / "soccer_source" / "epl"
    (league / "api" / "schedule").mkdir(parents=True)
    (league / "api" / "schedule" / "schedule_2026.json").write_text(json.dumps({"matches": [
        {"event_id": EVENT, "status_state": "post", "date": "2026-10-11T14:00:00Z",
         "home_team": "Arsenal", "away_team": "Chelsea", "home_score": "3", "away_score": "1"}]}), encoding="utf-8")
    (league / "history").mkdir(parents=True)
    with open(league / "history" / "player_match_log_2026.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["event_id", "player_id", "player_name", "team", "minutes", "goals",
                                           "assists", "shots", "shots_on_target"])
        w.writeheader()
        w.writerow({"event_id": EVENT, "player_id": "7", "player_name": "Bukayo Saka", "team": "Arsenal",
                    "minutes": 90, "goals": 1, "assists": 0, "shots": 3, "shots_on_target": 1})
    if with_box:
        (league / "api" / "live_state").mkdir(parents=True)
        players = {"home": {"team": "Arsenal", "players": [
            _player("7", "Bukayo Saka", goals=1.0, shots=3.0), _player("8", "João Pedro", goals=1.0, shots=2.0),
            _player("10", "Gabriel Jesus", shots=1.0), _player("11", "Antony", shots=1.0),
            _player("9", "Unused Sub", appeared=False)]},
            "away": {"team": "Chelsea", "players": [_player("20", "Levi Colwill")]}}
        (league / "api" / "live_state" / "live_state_2026-10-11.json").write_text(json.dumps({"match_box": {
            EVENT: {"event_id": EVENT, "final": True, "status_state": "post", "home_team": "Arsenal",
                    "away_team": "Chelsea", "players": players, "goals": goals}}}), encoding="utf-8")


def _index(monkeypatch, tmp_path, **kw):
    _write(tmp_path, **kw)
    monkeypatch.setattr(rows, "_soccer_files", lambda g: sorted((tmp_path / "soccer_source").glob(g)))
    return si.GradedRowIndex(rows.soccer_rows_for_date("2026-10-11"))


def _grade(idx, market, player, side="yes", line=None):
    rec = {"sport": "soccer", "market": market, "market_key": market, "side": side, "line": line, "kind": "prop",
           "segment": "full", "home_team": "Arsenal", "away_team": "Chelsea", "commence_time": "2026-10-11T14:00:00Z",
           "event_id": "oddsapi", "pick_id": "l2_s", "player_name": player, "selection": player}
    out = si.find_graded_row({"recommendation": rec, "result": "pending"}, idx, sport="soccer",
                             markets_compatible=lambda *a: True)
    return (out.row or {}).get("result")


def test_the_box_row_lists_the_squad_and_the_goal_order(monkeypatch, tmp_path):
    _write(tmp_path)
    monkeypatch.setattr(rows, "_soccer_files", lambda g: sorted((tmp_path / "soccer_source").glob(g)))
    box = next(r for r in rows.soccer_rows_for_date("2026-10-11") if r["market"] == rows.PLAYER_BOX_ROW_MARKET)
    assert box["source"] == "espn_match_box" and len(box["goals"]) == 4
    unused = next(p for p in box["players"] if p["name"] == "Unused Sub")
    assert unused["appeared"] is False and rows.PROP_GROUP not in unused       # absent, never zero


def test_a_squad_player_who_never_came_on_is_void(monkeypatch, tmp_path):
    idx = _index(monkeypatch, tmp_path)
    assert _grade(idx, "player_shots", "Unused Sub", side="over", line=0.5) == "push"
    assert _grade(idx, "player_first_goal_scorer", "Unused Sub") == "push"


def test_first_scorer_skips_the_own_goal_and_last_scorer_skips_the_late_one(monkeypatch, tmp_path):
    idx = _index(monkeypatch, tmp_path)
    assert _grade(idx, "player_first_goal_scorer", "Bukayo Saka") == "win"     # 5' own goal does not count
    assert _grade(idx, "player_first_goal_scorer", "Levi Colwill") == "loss"
    assert _grade(idx, "player_last_goal_scorer", "Joao Pedro") == "win"       # 88' own goal does not count
    assert _grade(idx, "player_last_goal_scorer", "Gabriel Jesus") == "loss"
    assert _grade(idx, "player_first_goal_scorer", "No Scorer") == "loss"


def test_only_own_goals_means_no_scorer_wins_and_every_player_loses(monkeypatch, tmp_path):
    idx = _index(monkeypatch, tmp_path, goals=[GOALS[0]])
    assert _grade(idx, "player_first_goal_scorer", "No Scorer") == "win"
    assert _grade(idx, "player_first_goal_scorer", "Bukayo Saka") == "loss"


def test_without_the_match_box_the_race_refuses_rather_than_guesses(monkeypatch, tmp_path):
    idx = _index(monkeypatch, tmp_path, with_box=False)
    assert _grade(idx, "player_first_goal_scorer", "Bukayo Saka") is None
    assert _grade(idx, "player_shots", "Bukayo Saka", side="over", line=2.5) == "win"   # the log still grades stats


def test_nested_names_beat_a_surname_elsewhere_in_the_match(monkeypatch, tmp_path):
    """'joao pedro junqueira de jesus' shares a surname with Gabriel Jesus; the two shared words win."""
    idx = _index(monkeypatch, tmp_path)
    assert _grade(idx, "player_shots", "Joao Pedro Junqueira de Jesus", side="over", line=1.5) == "win"
    assert _grade(idx, "player_shots", "Antony Matheus dos Santos", side="over", line=0.5) == "win"
