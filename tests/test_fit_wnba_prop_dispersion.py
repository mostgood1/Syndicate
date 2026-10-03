"""Tests for scripts/fit_wnba_prop_dispersion.py (lane `wnba-prop-dispersion`).

What a wrong answer would hide: k = 1 must reproduce today's ladder exactly (otherwise "k=1" is not the baseline it
claims), dilation must widen without moving the mean, the read must be the board's floor(line)+1 threshold, and the
fit must report a grid-edge k as an edge rather than as a result."""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("fit_disp", ROOT / "scripts" / "fit_wnba_prop_dispersion.py")
F = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(F)  # type: ignore[union-attr]

# a real-shaped ladder: Marina Mabrey pts, 2026-07-20 re-run (100-draw excerpt)
DIST = {3: 1, 4: 1, 5: 1, 6: 2, 7: 4, 8: 3, 9: 2, 10: 10, 11: 3, 12: 5, 13: 6, 14: 9, 15: 14, 16: 7, 17: 3, 18: 6,
        19: 3, 20: 3, 21: 5, 22: 3, 23: 2, 24: 3, 25: 2, 32: 1, 44: 1}


def _mean(d):
    t = sum(d.values())
    return sum(v * m for v, m in d.items()) / t


def _sd(d):
    t, m = sum(d.values()), _mean(d)
    return math.sqrt(sum(w * (v - m) ** 2 for v, w in d.items()) / t)


def test_k_one_is_todays_ladder():
    mu = _mean(DIST)
    assert F.dilate(DIST, mu, 1.0) == {k: float(v) for k, v in DIST.items()}
    for line in (9.5, 14.5, 15.0, 22.5):
        thr = math.floor(line) + 1
        assert F.p_over(F.dilate(DIST, mu, 1.0), line) == pytest.approx(sum(m for v, m in DIST.items() if v >= thr) / 100)


def test_dilation_widens_and_keeps_the_mean():
    mu = _mean(DIST)
    wide = F.dilate(DIST, mu, 1.4)
    assert _sd(wide) == pytest.approx(1.4 * _sd(DIST), rel=0.03)
    assert _mean(wide) == pytest.approx(mu, abs=0.1)        # only rounding moves it
    assert sum(wide.values()) == pytest.approx(100)


def test_dilation_clips_at_zero_and_moves_tail_mass_outward():
    d = {0: 30, 1: 40, 2: 20, 5: 10}
    mu = _mean(d)
    wide = F.dilate(d, mu, 2.0)
    assert min(wide) == 0 and all(v >= 0 for v in wide)
    assert F.p_over(wide, 6.5) > F.p_over(d, 6.5)           # an upper-tail line gains mass: 5 crosses 6.5 only widened
    # LOW-COUNT ASYMMETRY (a real property, reported as `mean_shift_from_dilation`): near zero, rounding and the
    # clip at 0 stop mass moving down while the tail still moves up, so widening a low-count ladder RAISES its mean.
    assert F.p_over(wide, 0.5) == F.p_over(d, 0.5)
    assert _mean(wide) > mu


def test_threshold_is_floor_plus_one():
    d = {12: 50, 13: 50}
    assert F.p_over(d, 12.5) == 0.5
    assert F.p_over(d, 12.0) == 0.5                          # over a whole 12 needs 13
    assert F.p_over(d, 11.5) == 1.0


def test_rps_is_zero_for_a_point_mass_on_the_outcome():
    assert F.rps({7: 1.0}, 7) == 0.0
    assert F.rps({7: 1.0}, 9) > 0


def test_rps_does_not_reward_width_for_its_own_sake():
    # Measured on the first version (normalised by the threshold count): for an outcome 8 away from a ladder of sd 1.4,
    # its score kept FALLING through k = 16 (0.1689 at k=8 -> 0.1488 at k=16), so every fit ran to the grid's top.
    # The plain sum has an interior minimum: k = 16 must score WORSE than k = 8. Fails on the old formula.
    base = {8: 20, 9: 20, 10: 20, 11: 20, 12: 20}
    assert F.rps(F.dilate(base, 10, 16.0), 18) > F.rps(F.dilate(base, 10, 8.0), 18)
    assert F.rps(F.dilate(base, 10, 8.0), 18) < F.rps(F.dilate(base, 10, 1.0), 18)


def test_fit_reports_a_grid_edge(monkeypatch):
    # a loss that keeps falling as k grows: the best k is the top of the grid and must be FLAGGED, not reported as a fit
    rows = [{"gid": f"g{i}"} for i in range(40)]
    ys = [i % 2 for i in range(40)]

    def fake_eval(_rows, k):
        p = min(0.5, 0.05 + 0.10 * k)                          # approaches the right answer (0.5) only past k = 4.5
        return {"ps": [p] * len(ys), "ys": ys, "gids": [r["gid"] for r in rows], "rows": rows, "rps": []}
    monkeypatch.setattr(F, "evaluate", fake_eval)
    k, curve, edge = F.fit_k(rows)
    assert edge is True and k == F.K_GRID[-1]
    assert len(curve) == len(F.K_GRID)


def test_fit_interior_minimum_is_not_an_edge(monkeypatch):
    rows = [{"gid": f"g{i}"} for i in range(40)]
    ys = [1 if i % 4 == 0 else 0 for i in range(40)]           # base rate 0.25

    def fake_eval(_rows, k):
        return {"ps": [0.25 * k / 1.4] * len(ys), "ys": ys, "gids": [r["gid"] for r in rows], "rows": rows, "rps": []}
    monkeypatch.setattr(F, "evaluate", fake_eval)
    k, _curve, edge = F.fit_k(rows)
    assert edge is False and k == pytest.approx(1.4)
