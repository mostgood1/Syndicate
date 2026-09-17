# -*- coding: utf-8 -*-
"""scripts/soccer_season_audit/live_direction_study.py: the H31 rows, model and verdict (log ~15:50 CT)."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "soccer_season_audit"))

import live_direction_study as d  # noqa: E402


def _match(goals, shots=(), momentum=(), match_id="1", league="epl"):
    return {"match_id": match_id, "league": league, "date": "2026-03-01",
            "goals": [{"t": t, "home": home} for t, home in goals],
            "shots": [{"t": t, "xg": xg, "home": home} for t, xg, home in shots],
            "vendor_momentum": [{"t": t, "value": v} for t, v in momentum]}


def test_tilt_is_the_mean_over_the_ten_minutes_before_the_goal():
    momentum = [{"t": 600.0, "value": -50.0}, {"t": 1500.0, "value": 10.0}, {"t": 1700.0, "value": 30.0}]
    assert d.tilt_before(momentum, 1800.0) == pytest.approx(20.0)     # the -50 at 600s is outside the window
    assert d.tilt_before(momentum, 300.0) is None


def test_goal_rows_carry_the_state_BEFORE_the_goal_and_skip_early_ones():
    match = _match(goals=[(300.0, True), (1800.0, False), (3000.0, True)],
                   shots=[(200.0, 0.4, True), (1000.0, 0.2, True), (2000.0, 0.7, False)],
                   momentum=[(t, 10.0) for t in range(0, 3600, 60)])
    rows = d.goal_rows(match)
    assert len(rows) == 2                                             # the 300s goal has no tilt window
    second = rows[0]
    assert second["y"] == 0.0 and second["score"] == 1.0              # home led 1-0 before it
    assert second["xgdiff"] == pytest.approx(0.6)                     # 0.4 + 0.2 home, none away yet
    third = rows[1]
    assert third["score"] == 0.0 and third["xgdiff"] == pytest.approx(-0.1)


def test_a_match_with_no_momentum_series_yields_no_rows():
    assert d.goal_rows(_match(goals=[(1800.0, True)])) == []


def test_the_split_is_stable_and_roughly_a_third():
    ids = [str(i) for i in range(3000)]
    share = sum(1 for i in ids if d.is_test(i)) / len(ids)
    assert 0.30 < share < 0.37
    assert d.is_test("12345") == d.is_test("12345")


def test_design_puts_tilt_in_its_own_column_and_penalises_only_the_league_terms():
    rows = [{"lg": "epl", "y": 1.0, "tilt": 2.0, "score": 1.0, "xgdiff": 0.5, "match_id": "m"},
            {"lg": "mls", "y": 0.0, "tilt": -3.0, "score": 0.0, "xgdiff": -0.5, "match_id": "m2"}]
    X, y, mask = d.design(rows, ["epl", "mls"])
    assert X.shape == (2, 6) and list(y) == [1.0, 0.0]
    assert X[0, 3] == 2.0 and X[0, 4] == 2.0 and X[0, 5] == 0.0
    assert list(mask) == [0.0, 0.0, 0.0, 0.0, 1.0, 1.0]


def test_fit_recovers_a_positive_tilt_weight_when_pressure_precedes_the_goal():
    rng = np.random.default_rng(0)
    rows = []
    for i in range(800):
        tilt = float(rng.normal())
        p = 1.0 / (1.0 + np.exp(-(0.6 * tilt)))
        rows.append({"lg": "epl", "y": float(rng.random() < p), "tilt": tilt, "score": 0.0,
                     "xgdiff": 0.0, "match_id": f"m{i}"})
    X, y, mask = d.design(rows, ["epl"])
    beta = d.fit(X, y, mask, 0.0)
    assert beta[3] + beta[4] == pytest.approx(0.6, abs=0.25)


def test_the_ridge_pulls_a_league_deviation_toward_the_global_weight():
    rng = np.random.default_rng(1)
    rows = []
    for i in range(600):
        lg = "epl" if i % 2 else "mls"
        tilt = float(rng.normal())
        weight = 1.2 if lg == "epl" else -1.2
        p = 1.0 / (1.0 + np.exp(-(weight * tilt)))
        rows.append({"lg": lg, "y": float(rng.random() < p), "tilt": tilt, "score": 0.0,
                     "xgdiff": 0.0, "match_id": f"m{i}"})
    X, y, mask = d.design(rows, ["epl", "mls"])
    loose = d.fit(X, y, mask, 0.1)
    tight = d.fit(X, y, mask, 10000.0)
    assert abs(loose[4]) > abs(tight[4])
    assert abs(tight[4]) < 0.05


def test_auc_and_verdict():
    assert d.auc([(1.0, 1.0), (0.0, 0.0)]) == 1.0
    assert d.auc([(0.0, 1.0), (1.0, 0.0)]) == 0.0
    assert d.auc([(1.0, 1.0), (1.0, 0.0)]) == 0.5
    assert d.verdict((-0.01, (-0.02, -0.001), 100)) == "SUPPORTED"
    assert d.verdict((-0.01, (-0.02, 0.001), 100)) == "FALSIFIED"      # a CI touching zero is not support
