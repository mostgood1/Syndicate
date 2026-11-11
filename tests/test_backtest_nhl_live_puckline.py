"""The NHL live puck-line grading harness (lane nhl-live-puckline-grade).

Pins what the grade rests on: the state rebuilt at each cutoff, the outcome's support (shootout winner +1),
the probability graded (the board's own Agresti-Coull P(home margin > away-frame line)), the powered-bucket
headline, the skill-free baseline, and REACHABILITY -- the harness runs the SHIPPED `resim_live_game`.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from syndicate.features.nhl import live_resim as LR
from tests.test_nhl_live_resim import _StubFeatures

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "backtest_nhl_live_puckline.py"
_spec = importlib.util.spec_from_file_location("backtest_nhl_live_puckline", _PATH)
H = importlib.util.module_from_spec(_spec)
sys.modules["backtest_nhl_live_puckline"] = H
_spec.loader.exec_module(H)

PK = "2026020285"


def _row(*, state="OFF", game_type=2, home=3, away=2, last="SO", goals=None):
    goals = goals if goals is not None else [
        (1, "06:14", 0, 1, "REG"), (1, "16:41", 1, 1, "REG"), (2, "01:11", 1, 2, "REG"),
        (2, "12:12", 2, 2, "REG"), (5, "00:00", 3, 2, "SO")]
    return {
        "id": int(PK), "gameState": state, "gameType": game_type, "startTimeUTC": "2026-11-10T00:00:00Z",
        "gameOutcome": {"lastPeriodType": last},
        "homeTeam": {"abbrev": "TOR", "score": home, "name": {"default": "Maple Leafs"}},
        "awayTeam": {"abbrev": "OTT", "score": away, "name": {"default": "Senators"}},
        "goals": [{"period": p, "periodDescriptor": {"number": p, "periodType": t}, "timeInPeriod": tip,
                   "homeScore": h, "awayScore": a} for p, tip, h, a, t in goals],
    }


def test_completed_game_reads_the_official_final_with_the_shootout_goal():
    g = H.completed_game(_row())
    assert g["final_home"] - g["final_away"] == 1          # 2-2 after OT, 3-2 SO: the winner is credited one
    assert g["last_period_type"] == "SO"
    assert g["goals"][-1][:2] == (5, 0)


def test_preseason_unfinished_and_inconsistent_games_are_not_graded():
    assert H.completed_game(_row(game_type=1)) is None     # preseason: a different population
    assert H.completed_game(_row(state="LIVE")) is None
    # a goal list that does not reproduce the final cannot rebuild a true state
    assert H.completed_game(_row(home=4)) is None


def test_score_at_rebuilds_the_board_at_each_cutoff():
    goals = H.completed_game(_row())["goals"]
    assert H.score_at(goals, 1, 1200) == (0, 0)            # puck drop
    assert H.score_at(goals, 2, 1200) == (1, 1)            # end of P1
    assert H.score_at(goals, 2, 600) == (1, 2)             # P2 10:00 elapsed; the 12:12 goal is later
    assert H.score_at(goals, 3, 1200) == (2, 2)
    assert H.score_at(goals, 3, 300) == (2, 2)             # the shootout goal is never on a regulation board


def test_a_goal_at_the_cutoff_second_is_not_yet_on_the_board():
    goals = [(2, 600, 1, 0, "REG")]
    assert H.score_at(goals, 2, 600) == (0, 0)
    assert H.score_at(goals, 2, 599) == (1, 0)


def test_p_cover_is_the_boards_number_in_the_away_frame():
    hist = {-2: 10, -1: 30, 1: 40, 2: 20}                  # n = 100
    # line -1.5 = home +1.5 covers = margin >= -1
    assert H.p_cover(hist, -1.5) == pytest.approx((90 + 2) / 104)
    assert H.p_cover(hist, 1.5) == pytest.approx((20 + 2) / 104)
    assert H.p_cover(hist, 1.5, smoothed=False) == pytest.approx(0.20)


def test_worst_bucket_ignores_unpowered_cells():
    cells = [("g%d" % i, 0.85, 1) for i in range(30)] + [("x", 0.15, 1)] * 5
    cal = H.calibration(cells)
    w = H.worst_powered(cal)
    assert w["bucket"] == "0.8-0.9" and w["n"] == 30 and w["gap"] == pytest.approx(0.15)
    assert [b for b in cal if b["bucket"] == "0.1-0.2"][0]["powered"] is False


def test_skellam_baseline_is_a_distribution_and_knows_the_clock():
    lam = 3.0 / 3600
    assert H.skellam_cover(0, 3600, lam, lam, 0.5, -100.0) == pytest.approx(1.0, abs=1e-6)
    assert H.skellam_cover(0, 3600, lam, lam, 0.5, 0.0) == pytest.approx(0.5, abs=1e-6)
    # no time left: the board's margin decides it (a tie goes to OT at the given share)
    assert H.skellam_cover(2, 0, lam, lam, 0.5, 1.5) == pytest.approx(1.0)
    assert H.skellam_cover(0, 0, lam, lam, 0.6, -1.5) == pytest.approx(1.0)
    assert H.skellam_cover(0, 0, lam, lam, 0.6, 0.0) == pytest.approx(0.6)


def test_width_stats_reads_spread_and_coverage():
    rows = [{"hist": {"0": 5, "1": 90, "2": 5}, "final_margin": 1}] * 4
    w = H.width_stats(rows)
    assert w["central80_coverage"] == 1.0
    assert w["actual_rmse"] < w["model_sd"]


def test_replay_runs_the_shipped_producer_and_off_differs_from_on():
    """REACHABILITY (`model_engine_standard.md`): the harness's rows come from the real `resim_live_game`."""
    game = H.completed_game(_row())
    feats = _StubFeatures(PK, "Toronto Maple Leafs", "Ottawa Senators")
    rows = H.replay_game(feats, game, sims=20)
    assert [r["cutoff"] for r in rows] == [c[2] for c in H.CUTOFFS]
    for r in rows:
        assert "refused" not in r, r
        assert sum(r["hist"].values()) == r["sims_run"] == 20
        assert "0" not in r["hist"]                        # shootout on: never a 0 margin, as the final
        assert r["final_margin"] == 1
    assert (rows[0]["home_score"], rows[0]["away_score"]) == (0, 0)
    assert (rows[3]["home_score"], rows[3]["away_score"]) == (2, 2)

    def _refuse(features, state, **kw):
        return LR.NhlResimRefusal("no_rosters", state.game_pk)

    off = H.replay_game(feats, game, sims=20, resim=_refuse)
    assert all(r.get("refused") == "no_rosters" for r in off)


def test_grade_end_to_end_on_replayed_rows():
    game = H.completed_game(_row())
    feats = _StubFeatures(PK, "Toronto Maple Leafs", "Ottawa Senators")
    rows = H.replay_game(feats, game, sims=20)
    for r in rows:
        r["date"] = "2026-11-09"
    rep = H.grade(rows, [game])
    fam = rep["families"]["puck_line_1_5"]
    assert fam["cells"] == len(rows) * 2
    assert fam["verdict"] == "NO_POWERED_BUCKET"           # 12 cells cannot power a bucket
    assert set(rep["width_by_cutoff"]) == {c[2] for c in H.CUTOFFS}
