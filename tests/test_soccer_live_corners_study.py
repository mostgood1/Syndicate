# -*- coding: utf-8 -*-
"""scripts/soccer_season_audit/live_corners_study.py: the H29 arms and verdict (log/2026-09-17.md ~11:50 CT)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "soccer_season_audit"))

import live_corners_study as s  # noqa: E402


def _row(key, cutoff, so_far, final, e3=10.0, date="2026-08-01", c0=None):
    return {"key": key, "lg": "epl", "date": date, "cutoff": cutoff, "so_far": so_far, "final": final, "e3": e3,
            "c0_remaining": c0 if c0 is not None else 5.0}


def test_share_after_is_the_mean_per_match_share_and_skips_cornerless_matches():
    rows = [_row("a", 30, 2, 10), _row("b", 30, 6, 8), _row("c", 30, 0, 0)]
    assert s.share_after(rows)[30] == pytest.approx((0.8 + 0.25) / 2)


def test_c2_moves_from_the_observed_pace_to_the_pregame_pace_as_a_grows():
    e3, so_far, share = 10.0, 8.0, 0.5            # half the match's corners still to come; 8 already vs 5 expected
    pace = share * so_far / (1.0 - share)         # a -> 0: extrapolate the observed rate
    assert s.c2(e3, so_far, share, 1e-9) == pytest.approx(pace)
    assert s.c2(e3, so_far, share, 1e9) == pytest.approx(s.c1(e3, share))
    mid = s.c2(e3, so_far, share, 1.0)
    assert s.c1(e3, share) < mid < pace


def test_pick_a_takes_the_registered_grid_value_with_the_lowest_train_mae():
    # a busy first half that keeps going: observed pace wins, so the smallest a is chosen
    rows = [_row(f"m{i}", 45, 9, 18, e3=8.0) for i in range(10)]
    a, scores = s.pick_a(rows, {45: 0.5})
    assert a == s.A_GRID[0]
    assert set(scores) == set(s.A_GRID)


def test_paired_boot_clusters_by_match_and_signs_the_difference():
    rows = []
    for i in range(30):
        for cutoff in s.CUTOFFS:
            rows.append({"key": f"m{i}", "err_a": 1.0, "err_b": 2.0})
    point, (lo, hi), k = s.paired_boot(rows, "err_a", "err_b")
    assert point == pytest.approx(-1.0) and lo == pytest.approx(-1.0) and hi == pytest.approx(-1.0)
    assert k == 30


@pytest.mark.parametrize("ci,c2_vs_c1,expected", [
    ((-0.10, -0.01), -0.02, "SUPPORTED"),
    ((-0.10, 0.00), -0.02, "FALSIFIED"),        # CI must lie entirely below zero
    ((-0.10, -0.01), 0.001, "FALSIFIED"),       # and C2 no worse than C1
    ((float("nan"), float("nan")), -0.5, "FALSIFIED"),
])
def test_verdict(ci, c2_vs_c1, expected):
    assert s.verdict((-0.05, ci, 100), c2_vs_c1) == expected


def test_study_fits_on_train_and_scores_only_test():
    rows = []
    for i in range(12):
        date = "2026-08-01" if i < 6 else "2026-09-01"
        for cutoff in s.CUTOFFS:
            share = 1.0 - cutoff / 95.0
            final = 10.0
            rows.append(_row(f"m{i}", cutoff, round(final * (1 - share)), final, e3=10.0, date=date, c0=4.0))
    res = s.study(rows)
    assert res["train_matches"] == 6 and res["test_matches"] == 6
    assert set(res["per_cutoff"]) == set(s.CUTOFFS)
    assert res["verdict"] in {"SUPPORTED", "FALSIFIED"}
    assert all(r.get("err_c0") is None for r in rows if r["date"] < s.TRAIN_END)
