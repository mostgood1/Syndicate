"""The WNBA live-prop grader's replay of rebounds / assists / threes, and its gate.

`[2026-09-28, lane live-props-model-probability]`. These three residual tables now
price live props in production, so the counting rules that produce them are pinned:
a team rebound credits no player, a block (two participants on a MISS) is not an
assist, a made three is a scoring play worth 3, and the box's "3-7" is 3 made.
The replay is only trusted where it reproduces the official box exactly.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import grade_wnba_live_prop_projection as g  # noqa: E402


def _ath(aid, starter=True):
    return {"id": aid, "displayName": f"P{aid}"}


def _summary(box_stats):
    keys = ["minutes", "points", "threePointFieldGoalsMade-threePointFieldGoalsAttempted", "rebounds", "assists"]
    athletes = [{"athlete": _ath(aid), "starter": True, "stats": stats} for aid, stats in box_stats.items()]
    plays = [
        # A made three by 1, assisted by 2.
        {"period": {"number": 1}, "clock": {"displayValue": "9:00"}, "type": {"text": "Jump Shot"},
         "scoringPlay": True, "scoreValue": 3,
         "participants": [{"athlete": {"id": "1"}}, {"athlete": {"id": "2"}}]},
        # A player rebound by 2, then a TEAM rebound (no participant).
        {"period": {"number": 1}, "clock": {"displayValue": "8:00"}, "type": {"text": "Defensive Rebound"},
         "participants": [{"athlete": {"id": "2"}}]},
        {"period": {"number": 1}, "clock": {"displayValue": "7:30"}, "type": {"text": "Offensive Rebound"},
         "participants": []},
        # A BLOCK: two participants on a miss -- not an assist.
        {"period": {"number": 1}, "clock": {"displayValue": "7:00"}, "type": {"text": "Driving Layup Shot"},
         "scoringPlay": False, "participants": [{"athlete": {"id": "2"}}, {"athlete": {"id": "1"}}]},
        # A made two by 2, unassisted.
        {"period": {"number": 4}, "clock": {"displayValue": "0:00"}, "type": {"text": "Layup Shot"},
         "scoringPlay": True, "scoreValue": 2, "participants": [{"athlete": {"id": "2"}}]},
    ]
    return {"boxscore": {"players": [{"statistics": [{"keys": keys, "athletes": athletes}]}]}, "plays": plays}


def test_replay_counts_by_the_structured_rules_and_reconciles():
    s = _summary({"1": ["40", "3", "1-4", "0", "0"], "2": ["40", "2", "0-1", "1", "1"]})
    state = g.replay(s)
    assert state["threes"] == {"1": 1.0, "2": 0.0}
    assert state["rebounds"] == {"1": 0.0, "2": 1.0}  # team rebound credited to nobody
    assert state["assists"] == {"1": 0.0, "2": 1.0}   # the block is not an assist
    check = g.reconcile(state)
    assert check["threes_exact"] == check["rebounds_exact"] == check["assists_exact"] == 2


def test_a_box_that_disagrees_fails_its_own_stat_only():
    """Box says player 2 had 2 rebounds; the replay saw 1. Rebounds must fail the
    gate while the other stats still reconcile -- the grader drops that game for
    rebounds only."""
    s = _summary({"1": ["40", "3", "1-4", "0", "0"], "2": ["40", "2", "0-1", "2", "1"]})
    check = g.reconcile(g.replay(s))
    assert check["rebounds_exact"] == 1 and check["assists_exact"] == 2 and check["threes_exact"] == 2
    assert check["points_exact"] == 2


def test_made_half_of_a_made_attempted_pair():
    assert g._made_at(["3-7"], 0) == 3.0
    assert g._made_at(["x"], 0) is None
    assert g._made_at([], 0) is None
