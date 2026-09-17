# -*- coding: utf-8 -*-
"""scripts/soccer_season_audit/live_goals_study.py: the H30 arms (log/2026-09-17.md ~14:00 CT)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "soccer_season_audit"))

import live_goals_study as g  # noqa: E402


def _row(cutoff, goals_after, final_goals, xg_after, xg_total, key="m", date="2026-08-01"):
    return {"key": key, "lg": "epl", "date": date, "cutoff": cutoff, "goals_after": goals_after,
            "final_goals": final_goals, "xg_after": xg_after, "xg_total": xg_total,
            "goals_so_far": final_goals - goals_after, "xg_so_far": xg_total - xg_after,
            "sot_after": 0.0, "sot_total": 4.0, "sot_so_far": 4.0, "t_pre": 2.7, "g0_remaining": 1.0}


def test_share_is_a_ratio_of_sums_not_a_mean_of_per_match_shares():
    rows = [_row(45, 0.0, 0.0, 0.0, 1.0, key="goalless"), _row(45, 2.0, 4.0, 1.0, 2.0, key="busy")]
    # ratio of sums: 2 goals after / 4 total = 0.5; a mean of per-match shares would be undefined on the 0-0
    assert g.ratio_share_after(rows, "goals_after", "final_goals")[45] == pytest.approx(0.5)


def test_g2_moves_from_the_pregame_total_to_the_observed_xg_pace_as_a_falls():
    t_pre, sg, f_obs, k = 2.7, 0.5, 0.5, 1.0
    hot = 2.5                                     # 2.5 xG in the observed half of the match
    assert g.g2(t_pre, hot, sg, f_obs, k, 1e9) == pytest.approx(g.g1(t_pre, sg))
    assert g.g2(t_pre, hot, sg, f_obs, k, 1e-9) == pytest.approx(sg * k * hot / f_obs)
    assert g.g1(t_pre, sg) < g.g2(t_pre, hot, sg, f_obs, k, 1.0) < sg * hot / f_obs


def test_g2_falls_back_to_the_pregame_pace_when_no_share_has_elapsed():
    assert g.g2(2.7, 0.0, 0.5, 0.0, 1.0, 2.0) == pytest.approx(g.g1(2.7, 0.5))


def test_pick_a_takes_the_registered_grid_value_with_the_lowest_train_mae():
    rows = [_row(45, 2.0, 4.0, 1.2, 2.4, key=f"m{i}") for i in range(10)]
    a, scores = g.pick_a(rows, {45: 0.5}, {45: 0.5}, 1.0, "xg_so_far")
    assert a in g.A_GRID and set(scores) == set(g.A_GRID)


def test_study_splits_on_the_registered_date_and_grades_only_test():
    rows = []
    for i in range(12):
        date = "2026-08-01" if i < 6 else "2026-09-01"
        for cutoff in g.CUTOFFS:
            rows.append(_row(cutoff, 1.0, 2.0, 0.6, 1.4, key=f"m{i}", date=date))
    res = g.study(rows)
    assert res["train_matches"] == 6 and res["test_matches"] == 6
    assert res["verdict"] in {"SUPPORTED", "FALSIFIED"}
    assert set(res["per_cutoff"]) == set(g.CUTOFFS)
    assert "err_g2sot" in res["test_pooled"]      # the reported-only shots-on-target variant
