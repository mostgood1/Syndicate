"""SGP paper-ledger grading fixes, todo #743 (lane `sgp-leg-grading`; measured in
`.syndicate/findings_2026-10-27_sgp_pjoint_calibration.md`).

(a) The calibration counts only parlays whose every leg resolved: one with a pending or void leg can be LOST but never
    WON. (b) Correlation-family legs carry no game-log id, so they are resolved by name + team when grading."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from syndicate.features.nfl import sgp_pool as nfl
from syndicate.features.nhl import sgp_pool as nhl
from syndicate.features.shared import cheat_sheets as cs

ROOT = Path(__file__).resolve().parents[1]
DAY = "2026-10-20"


def _grader():
    spec = importlib.util.spec_from_file_location("grade_sgp_paper", ROOT / "scripts" / "grade_sgp_paper.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _g(status, results, p=0.4, event="e1"):
    return {"status": status, "p_joint": p, "event_id": event, "relation": "teammate", "worth_it_odds": 150,
            "est_book_odds": 120, "legs": [{"bet": f"leg{i}", "result": r} for i, r in enumerate(results)]}


# ------------------------------------------------------------------ (a) the calibration population
def test_a_lost_parlay_with_an_unresolved_leg_leaves_the_calibration():
    g = _grader()
    graded = [_g("won", ["won", "won"]), _g("lost", ["won", "lost"], event="e2"),
              _g("lost", ["lost", "pending"], event="e3"), _g("lost", ["void", "lost"], event="e3")]
    s = g.summarize(graded)
    assert s["settled"] == 4 and s["unresolved_leg"] == 2
    assert s["hit_rate"] == pytest.approx(0.5) and s["games"] == 2        # 1 of the 2 resolved, not 1 of 4
    assert s["roi_at_worth_it_price"] == pytest.approx(2.5 / 2 - 1)
    # off != on: the as-graded count would have read 25%
    assert sum(x["status"] == "won" for x in graded) / len(graded) == pytest.approx(0.25)


def test_a_parlay_without_leg_detail_still_counts():
    s = _grader().summarize([{"status": "won", "p_joint": 0.3, "event_id": "e1"},
                             {"status": "lost", "p_joint": 0.3, "event_id": "e2"}])
    assert s["settled"] == 2 and s["unresolved_leg"] == 0 and s["hit_rate"] == pytest.approx(0.5)


# ------------------------------------------------------------------ (b) NHL: name + team through the box-score log
def _nhl_log():
    def row(pid, name, team, shots):          # the CSV's strings, as GameLog.load reads them
        return {"player_id": pid, "gamePk": "2026020101", "timeOnIce": "15:00", "date": f"{DAY}T23:30:00Z",
                "player": name, "team": team, "shots": str(shots), "goals": "0", "assists": "1", "saves": "0"}

    return nhl.GameLog([row("1", "J. Smith", "St. Louis Blues", 4), row("2", "A. Lee", "New York Islanders", 3),
                        row("3", "A. Lee", "New York Islanders", 1), row("4", "J. Smith", "Boston Bruins", 0),
                        row("5", "M. Barzal", "New York Islanders", 3)])


def _leg(player, team, market="SOG", line=2.5, side="over", **kw):
    return {"player": player, "team": team, "market": market, "side": side, "line": line,
            "bet": f"{player} {side} {line}", **kw}


def test_nhl_leg_without_an_id_is_resolved_by_canonical_team():
    log = _nhl_log()
    assert nhl.leg_player_id(log, _leg("Jordan Smith", "St Louis Blues")) == "1"     # 'St Louis' == 'St. Louis'
    assert nhl.leg_player_id(log, _leg("Anders Lee", "New York Islanders")) is None  # two A. Lees: never guess
    assert nhl.leg_player_id(log, _leg("Jordan Smith", "Seattle Kraken")) is None
    assert nhl.leg_player_id(log, _leg("Jordan Smith", None)) is None


def test_nhl_leg_actuals_grade_the_correlation_family_end_to_end():
    log = _nhl_log()
    ticket = {"sgp_id": "t", "legs": [_leg("Jordan Smith", "St Louis Blues"), _leg("Anders Lee", "New York Islanders"),
                                      _leg("Mat Barzal", "New York Islanders", player_id="5", line=1.5)]}
    acts = nhl.leg_actuals(Path("."), DAY, [ticket], log=log)
    assert acts["JORDAN SMITH|sog"] == 4.0
    assert acts["MAT BARZAL|sog"] == 3.0                    # a leg with an id still reads it
    assert not any(k.startswith("ANDERS LEE") for k in acts)
    got = cs.sgp_results([ticket], {"props": {}, "leg_actuals": acts})[0]
    assert [x["result"] for x in got["legs"]] == ["won", "pending", "won"]


# ------------------------------------------------------------------ (b) NFL: the roster, and anytime TDs
def _nfl_root(tmp_path):
    d = tmp_path / "nfl_source"
    d.mkdir()
    (d / "schedule_2026.csv").write_text("gameday,game_type,week\n2026-10-25,REG,8\n", encoding="utf-8")
    return tmp_path


def _nfl_log_roster():
    log = nfl.GameLog([{"player_id": "00-1", "game_id": "g8", "season": 2026, "week": 8, "rec_yards": 70,
                        "receptions": 6, "rush_tds": 0, "rec_tds": 1},
                       {"player_id": "00-2", "game_id": "g8", "season": 2026, "week": 8, "rec_yards": 12,
                        "rush_tds": 0, "rec_tds": 0}])
    roster = nfl.Roster([{"gsis_id": "00-1", "full_name": "Travis Kelce", "team": "KC", "week": 8},
                         {"gsis_id": "00-2", "full_name": "Noah Gray", "team": "KC", "week": 8},
                         {"gsis_id": "00-3", "full_name": "Mike Williams", "team": "PIT", "week": 8},
                         {"gsis_id": "00-4", "full_name": "Mike Williams", "team": "PIT", "week": 8}])
    return log, roster


def test_nfl_legs_without_an_id_grade_through_the_roster_including_anytime_td(tmp_path):
    root = _nfl_root(tmp_path)
    log, roster = _nfl_log_roster()
    ticket = {"sgp_id": "t", "legs": [_leg("Travis Kelce", "KC", "Receiving Yards", 55.5),
                                      _leg("Travis Kelce", "KC", "Anytime TD", None, side="yes"),
                                      _leg("Noah Gray", "KC", "Anytime TD", None, side="yes"),
                                      _leg("Mike Williams", "PIT", "Receiving Yards", 40.5)]}
    acts = nfl.leg_actuals(root, "2026-10-25", [ticket], log=log, roster=roster)
    assert acts["TRAVIS KELCE|receiving yards"] == 70.0
    assert acts["TRAVIS KELCE|anytime td"] == 1.0 and acts["NOAH GRAY|anytime td"] == 0.0
    assert not any(k.startswith("MIKE WILLIAMS") for k in acts)          # two of them: never guess
    got = cs.sgp_results([ticket], {"props": {}, "leg_actuals": acts})[0]
    assert [x["result"] for x in got["legs"]] == ["won", "won", "lost", "pending"]
    assert got["status"] == "lost"


def test_nfl_a_week_with_no_game_grades_nothing(tmp_path):
    log, roster = _nfl_log_roster()
    ticket = {"legs": [_leg("Travis Kelce", "KC", "Receiving Yards", 55.5)]}
    assert nfl.leg_actuals(_nfl_root(tmp_path), "2026-10-26", [ticket], log=log, roster=roster) == {}
