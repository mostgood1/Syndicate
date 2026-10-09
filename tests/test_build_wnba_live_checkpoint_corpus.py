"""Hermetic tests for scripts/build_wnba_live_checkpoint_corpus.py (no network, no data/)."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import build_wnba_live_checkpoint_corpus as corpus  # noqa: E402

HOME, AWAY = "1", "2"
H = [f"h{i}" for i in range(6)]   # h0..h4 start, h5 bench
A = [f"a{i}" for i in range(5)]


def _play(seq, per, clock, typ, hs, as_, team=None, parts=(), **kw):
    p = {"sequenceNumber": str(seq), "id": f"p{seq}", "period": {"number": per},
         "clock": {"displayValue": clock}, "type": {"text": typ}, "text": kw.pop("text", typ),
         "homeScore": hs, "awayScore": as_, "participants": [{"athlete": {"id": x}} for x in parts]}
    if team:
        p["team"] = {"id": team}
    p.update(kw)
    return p


def _athlete(aid, starter, pts, reb=0, ast=0, pf=0, mins=10):
    return {"athlete": {"id": aid, "displayName": aid}, "starter": starter, "didNotPlay": False,
            "stats": [str(mins), str(pts), "0-0", "0-0", "0-0", str(reb), str(ast), "0", "0", "0", "0",
                      str(reb), str(pf), "0"]}


KEYS = ["minutes", "points", "fieldGoalsMade-fieldGoalsAttempted",
        "threePointFieldGoalsMade-threePointFieldGoalsAttempted", "freeThrowsMade-freeThrowsAttempted",
        "rebounds", "assists", "turnovers", "steals", "blocks", "offensiveRebounds", "defensiveRebounds",
        "fouls", "plusMinus"]


def _summary(plays, h_pts=5, a_pts=2, h0_pts=5):
    lines_h = [{"displayValue": v} for v in ("2", "0", "0", str(h_pts - 2))]
    lines_a = [{"displayValue": v} for v in ("0", "2", "0", "0")]
    home_ath = [_athlete(H[0], True, h0_pts, pf=1)] + [_athlete(x, True, 0) for x in H[1:5]] + \
        [_athlete(H[5], False, 0)]
    away_ath = [_athlete(A[0], True, 2, reb=1)] + [_athlete(x, True, 0) for x in A[1:]]
    return {
        "header": {"competitions": [{"competitors": [
            {"homeAway": "home", "team": {"id": HOME, "abbreviation": "HHH"}, "score": str(h_pts),
             "linescores": lines_h},
            {"homeAway": "away", "team": {"id": AWAY, "abbreviation": "AAA"}, "score": str(a_pts),
             "linescores": lines_a}]}]},
        "boxscore": {"players": [
            {"team": {"id": HOME}, "statistics": [{"keys": KEYS, "athletes": home_ath}]},
            {"team": {"id": AWAY}, "statistics": [{"keys": KEYS, "athletes": away_ath}]}]},
        "pickcenter": [{"spread": -3.5, "overUnder": 160.5}],
        "winprobability": [{"playId": "p3", "homeWinPercentage": 0.61}],
        "plays": plays,
    }


def _plays():
    # NOTE sequenceNumbers deliberately NOT chronological: the feed's list order is the truth.
    return [
        _play(9, 1, "9:40", "Jump Shot", 2, 0, HOME, (H[0],), shootingPlay=True, scoringPlay=True,
              scoreValue=2, pointsAttempted=2),
        _play(1, 1, "5:00", "Personal Foul", 2, 0, HOME, (H[0],)),
        _play(3, 1, "0:00", "End Period", 2, 0),
        _play(4, 2, "8:00", "Jump Shot", 2, 0, AWAY, (A[0],), shootingPlay=True, scoringPlay=False,
              scoreValue=0, pointsAttempted=3),
        _play(5, 2, "7:59", "Defensive Rebound", 2, 0, AWAY, (A[0],)),
        _play(6, 2, "7:00", "Layup Shot", 2, 2, AWAY, (A[0],), shootingPlay=True, scoringPlay=True,
              scoreValue=2, pointsAttempted=2),
        _play(2, 3, "6:00", "Substitution", 2, 2, HOME, (H[5], H[4]),
              text="h5 enters the game for h4"),
        _play(7, 4, "6:00", "Lost Ball Turnover", 2, 2, AWAY, (A[1],)),
        _play(8, 4, "1:00", "Jump Shot", 5, 2, HOME, (H[0],), shootingPlay=True, scoringPlay=True,
              scoreValue=3, pointsAttempted=3),
        _play(10, 4, "0:00", "End Game", 5, 2),
    ]


def test_checkpoints_use_list_order_and_reconcile():
    res = corpus.build_game(_summary(_plays()), {"id": "e1", "date": "2026-07-01", "season_type": 2})
    assert res["recon"]["ok"] and res["recon"]["props_ok"], res["recon"]
    rows = {r["checkpoint"]: r for r in res["rows"]}
    assert set(rows) == {"end_q1", "end_q2", "end_q3", "q4_5min"}
    q1, q2, q3, q4 = (rows[k]["state"] for k in ("end_q1", "end_q2", "end_q3", "q4_5min"))
    assert (q1["home_score"], q1["away_score"], q1["period"], q1["secs_left_period"]) == (2, 0, 1, 0.0)
    assert q1["players"][H[0]]["pf"] == 1
    assert q2["away_score"] == 2 and q2["teams"]["away"]["fga"] == 2 and q2["teams"]["away"]["fg3a"] == 1
    assert q2["secs_left_regulation"] == 1200.0
    assert H[5] in q3["teams"]["home"]["on_floor"] and H[4] not in q3["teams"]["home"]["on_floor"]
    assert q4["teams"]["away"]["tov"] == 1 and q4["home_score"] == 2 and q4["secs_left_regulation"] == 300.0
    assert rows["end_q1"]["outcome"]["total"] == 7 and rows["end_q1"]["outcome"]["home_win"]
    assert rows["end_q1"]["pregame"] == {"spread_home": -3.5, "total": 160.5}


def test_next_possession_is_first_offensive_action_after_checkpoint():
    res = corpus.build_game(_summary(_plays()), {"id": "e1", "date": "2026-07-01", "season_type": 2})
    rows = {r["checkpoint"]: r for r in res["rows"]}
    assert rows["end_q1"]["state"]["next_possession"] == "away"
    assert rows["q4_5min"]["state"]["next_possession"] == "home"


def test_score_mismatch_excludes_game():
    res = corpus.build_game(_summary(_plays(), h_pts=7), {"id": "e1", "date": "x", "season_type": 2})
    assert res["rows"] == [] and res["recon"]["reason"] == "score"


def test_stat_mismatch_keeps_game_lines_and_flags_props():
    res = corpus.build_game(_summary(_plays(), h0_pts=4), {"id": "e1", "date": "x", "season_type": 2})
    assert res["recon"]["ok"] and not res["recon"]["props_ok"]
    assert len(res["rows"]) == 4 and all(r["props_reconciled"] is False for r in res["rows"])


def test_linear_lens_uses_shipped_functions_and_anchor_precedence():
    state = {"secs_left_regulation": 1200.0, "home_score": 40.0, "away_score": 30.0}
    from syndicate.features.wnba import cards
    out = corpus.linear_lens(state, {"p_home_win": 0.6, "pred_total": 160.0}, 150.0)
    assert out["anchor_total_used"] == 160.0
    assert out["total_proj"] == cards._wnba_live_total_projection(160.0, 70.0, 20.0)
    assert out["home_win_prob"] == cards._wnba_live_margin_win_prob(0.6, 10.0, 20.0)
    assert corpus.linear_lens(state, None, 150.0)["anchor_total_used"] == 150.0
    assert corpus.linear_lens(state, None, 150.0)["home_win_prob"] is None   # no pregame p -> lens has none
