"""Hermetic tests for the stage-3 favourite-gap arms in scripts/soccer_team_strength_experiments.py.

Registration: .syndicate/findings_2026-10-19_soccer_favourite_gain.md. No network, no data files.
"""

from __future__ import annotations

import numpy as np
import pytest

from scripts import soccer_team_strength_experiments as tse


def _synthetic(n=6000, gamma=0.0, seed=5):
    rng = np.random.default_rng(seed)
    L = len(tse.LEAGUES)
    league = rng.integers(0, L, n)
    r = rng.normal(0.0, 0.12, (n, 4))
    gh, ga, _g, _s = tse.gap_parts(r)
    params = {"mu": np.full(L, 0.2), "eta": np.full(L, 0.25), "k": 1.6, "gamma": gamma}
    lh, la = map(np.exp, tse.gain_log_rates(league, gh, ga, params))
    hg, ag = rng.poisson(lh).astype(float), rng.poisson(la).astype(float)
    return league, r, gh, ga, hg, ag


def test_probs_from_rates_matches_predict_1x2():
    league, r, gh, ga, hg, ag = _synthetic(n=50)
    d = tse.RDesign.__new__(tse.RDesign)
    d.n, d.league, d.gap_h, d.gap_a, d.hg, d.ag = 50, league, gh, ga, hg, ag
    L = len(tse.LEAGUES)
    params = {"mu": np.full(L, 0.1), "eta": np.full(L, 0.3), "k": 1.5}
    ref = tse.predict_1x2(d, params)
    got = tse.probs_from_rates(*map(np.exp, tse.gain_log_rates(league, gh, ga, params)))
    np.testing.assert_allclose(got, ref, atol=1e-12)


def test_null_parameters_reproduce_the_reference():
    rng = np.random.default_rng(1)
    p = rng.dirichlet([3, 2, 3], 200)
    absg = np.abs(rng.normal(0, 0.3, 200))
    np.testing.assert_allclose(tse.temper(p, absg, 0.0, 0.0), p, atol=1e-12)
    np.testing.assert_allclose(tse.draw_adjust(p, absg, 0.0, 0.0), p, atol=1e-12)


def test_gain_fit_recovers_gamma_and_is_null_on_null_data():
    league, r, gh, ga, hg, ag = _synthetic(gamma=3.0)
    fitted = tse.fit_gain(league, gh, ga, hg, ag)
    assert fitted["converged"]
    assert fitted["gamma"] == pytest.approx(3.0, abs=1.5)
    league, r, gh, ga, hg, ag = _synthetic(gamma=0.0, seed=8)
    assert abs(tse.fit_gain(league, gh, ga, hg, ag)["gamma"]) < 1.5


def test_positive_gamma_stretches_big_gaps_more():
    L = len(tse.LEAGUES)
    league = np.zeros(2, dtype=int)
    gh, ga = np.array([0.05, 0.4]), np.array([-0.05, -0.4])
    base = {"mu": np.full(L, 0.2), "eta": np.zeros(L), "k": 1.0, "gamma": 0.0}
    up = {**base, "gamma": 2.0}
    p0 = tse.probs_from_rates(*map(np.exp, tse.gain_log_rates(league, gh, ga, base)))
    p1 = tse.probs_from_rates(*map(np.exp, tse.gain_log_rates(league, gh, ga, up)))
    lift = p1[:, 0] - p0[:, 0]
    assert lift[1] > lift[0] > 0


def test_draw_term_moves_mass_to_the_favourite():
    p = np.array([[0.70, 0.20, 0.10]])
    out = tse.draw_adjust(p, np.array([0.5]), 0.0, -1.0)
    assert out[0, 1] < 0.20 and out[0, 0] > 0.70
    assert out[0, 0] / out[0, 2] == pytest.approx(7.0)


def test_post_fit_finds_planted_temperature():
    rng = np.random.default_rng(4)
    n = 20000
    base = rng.dirichlet([4, 3, 4], n)
    absg = np.abs(rng.normal(0, 0.3, n))
    truth = tse.temper(base, absg, 0.1, 0.5)
    y = np.array([rng.choice(3, p=q) for q in truth])
    t0, t1 = tse.fit_post("temper", base, absg, y)
    assert t0 == pytest.approx(0.1, abs=0.08) and t1 == pytest.approx(0.5, abs=0.3)
    g0, g1 = tse.fit_post("temper", base, absg, y, global_only=True)
    assert g1 == 0.0


def test_fav_tables_calibrated_model_is_not_flagged():
    rng = np.random.default_rng(9)
    n = 20000
    p = rng.dirichlet([2, 2, 2], n)
    y = np.array([rng.choice(3, p=q) for q in p])
    out = tse.fav_tables(p, y, p, n_boot=200)
    top = out["F2_by_own"]["top"]
    assert top["actual_ci"][0] - 0.02 <= top["arm"] <= top["actual_ci"][1] + 0.02
    assert sum(row["n"] for row in out["F1_by_close"]["deciles"]) == n


def test_kl_to_close_is_zero_on_identity():
    p = np.array([[0.5, 0.3, 0.2]])
    assert tse.kl_to_close(p, p)[0] == pytest.approx(0.0, abs=1e-12)
    assert tse.kl_to_close(np.array([[0.4, 0.3, 0.3]]), p)[0] > 0
