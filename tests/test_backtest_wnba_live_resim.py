"""Hermetic tests for scripts/backtest_wnba_live_resim.py and the scorer's paired native table."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

import backtest_wnba_live_resim as bt  # noqa: E402
import score_wnba_live_checkpoint_baseline as sc  # noqa: E402


def test_cover_probability_excludes_pushes():
    # home margin draws: -3 x2, +3 x1, +5 x1; spread -3 (home favoured by 3): margin+spread = -6,-6,0,+2
    dist = {"-3": 2, "3": 1, "5": 1}
    assert bt.p_win_given_no_push(dist, -3.0) == 1 / 3          # 1 win of 3 non-push
    assert bt.p_win_given_no_push(dist, None) is None and bt.p_win_given_no_push({}, -3.0) is None


def test_over_probability_uses_total_minus_line():
    dist = {"160": 1, "165": 2, "170": 1}                        # vs 165: under, push, push, over
    assert bt.p_win_given_no_push(dist, 165.0, offset_sign=-1) == 0.5


def _row(eid, cp, *, lin_total, lin_p, final_total=160, home_win=True):
    return {"event_id": eid, "checkpoint": cp, "phase": "regular",
            "linear_lens": {"total_proj": lin_total, "home_win_prob": lin_p, "home_cover_prob": 0.5,
                            "total_over_prob": 0.5, "home_spread_line": -2.5, "total_line": 158.5},
            "outcome": {"total": final_total, "margin": 6, "home_win": home_win}}


def test_paired_native_cell_counts_refusals_and_signs_diffs():
    rows = [_row("e1", "end_q1", lin_total=150, lin_p=0.6), _row("e2", "end_q1", lin_total=170, lin_p=0.6),
            _row("e3", "end_q1", lin_total=160, lin_p=0.6)]
    native = {("e1", "end_q1"): {"native": {"refusal": None, "total_mean": 158, "home_win_prob": 0.8,
                                            "home_cover_prob": 0.7, "total_over_prob": 0.6}},
              ("e2", "end_q1"): {"native": {"refusal": "no_pregame_inputs"}}}
    s = sc.score_native_cell(rows, native)
    assert s["refusals"] == {"no_pregame_inputs": 1, "not_run": 1}
    assert s["total_ae_n"] == 1 and s["total_ae_diff"] == abs(158 - 160) - abs(150 - 160)   # -8: native better
    assert abs(s["ml_diff"] - ((0.8 - 1) ** 2 - (0.6 - 1) ** 2)) < 1e-12
    assert abs(s["cover_diff"] - ((0.7 - 1) ** 2 - (0.5 - 1) ** 2)) < 1e-12              # margin 6 - 2.5 > 0
