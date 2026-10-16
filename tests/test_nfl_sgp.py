"""NFL SGP correlations (lane `nfl-sgp-builder`, 2026-10-16): the copula maths the joint price rests on."""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import numpy as np
import pytest

scipy = pytest.importorskip("scipy")
from scipy.stats import multivariate_normal  # noqa: E402

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_nfl_sgp_correlations.py"
_spec = importlib.util.spec_from_file_location("build_nfl_sgp_correlations", _PATH)
sgp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sgp)


@pytest.mark.parametrize("h,k,rho", [(0.3, -0.4, 0.5), (-1.1, 0.7, -0.3), (0.0, 0.0, 0.6), (1.5, 1.2, 0.85),
                                     (-0.2, -0.9, 0.0), (0.0, 0.8, -0.7)])
def test_bvn_lower_matches_scipy(h, k, rho):
    want = multivariate_normal(mean=[0, 0], cov=[[1, rho], [rho, 1]]).cdf([h, k])
    got = float(sgp.bvn_lower(np.array([h]), np.array([k]), rho)[0])
    assert got == pytest.approx(want, abs=1e-6)


def test_joint_over_at_the_median_is_the_closed_form():
    # P(both over) for two 50/50 legs = 1/4 + asin(rho) / (2 pi), the orthant identity.
    for rho in (-0.6, 0.0, 0.3, 0.8):
        got = float(sgp.joint_over(np.array([0.5]), np.array([0.5]), rho)[0])
        assert got == pytest.approx(0.25 + math.asin(rho) / (2 * math.pi), abs=1e-7)


def test_independence_is_the_product():
    p_a, p_b = np.array([0.31, 0.55, 0.72]), np.array([0.48, 0.66, 0.2])
    assert np.allclose(sgp.joint_over(p_a, p_b, 0.0), p_a * p_b, atol=1e-9)


def test_fit_rho_recovers_a_known_correlation_with_per_leg_marginals():
    rng = np.random.default_rng(7)
    n, rho = 40_000, 0.35
    z = rng.multivariate_normal([0, 0], [[1, rho], [rho, 1]], size=n)
    p_a = rng.uniform(0.35, 0.65, n)            # each leg has its own line, so its own marginal
    p_b = rng.uniform(0.3, 0.6, n)
    o_a = (z[:, 0] > sgp.ndtri(1 - p_a)).astype(float)
    o_b = (z[:, 1] > sgp.ndtri(1 - p_b)).astype(float)
    games = np.arange(n) // 40
    fit = sgp.fit_rho(p_a, p_b, o_a, o_b, games)
    assert abs(fit["rho"] - rho) < 3 * fit["se"] + 0.01
    assert 0 < fit["se"] < 0.05


def test_fit_rho_finds_nothing_in_independent_legs():
    rng = np.random.default_rng(11)
    n = 30_000
    p_a, p_b = np.full(n, 0.5), np.full(n, 0.45)
    o_a = (rng.uniform(size=n) < p_a).astype(float)
    o_b = (rng.uniform(size=n) < p_b).astype(float)
    fit = sgp.fit_rho(p_a, p_b, o_a, o_b, np.arange(n) // 30)
    assert abs(fit["rho"]) < 3 * fit["se"] + 0.005


def test_american_prices():
    assert sgp.american_to_prob(-110) == pytest.approx(110 / 210)
    assert sgp.american_to_prob(150) == pytest.approx(0.4)


def test_a_miscalibrated_low_probability_marginal_does_not_fake_a_correlation():
    # Two Anytime-TD-like legs, both priced above what they hit (0.25 -> 0.18, 0.30 -> 0.22), independent. Without
    # the within-cell recalibration the concordance moment reads this as rho +0.33 (measured 2026-10-16); with it, ~0.
    # (One leg at exactly 0.5 cancels the bias -- delta * (1 - 2 p_b) -- so the case needs both legs off 0.5.)
    rng = np.random.default_rng(3)
    n = 60_000
    p_a, p_b = np.full(n, 0.25), np.full(n, 0.30)
    o_a = (rng.uniform(size=n) < 0.18).astype(float)
    o_b = (rng.uniform(size=n) < 0.22).astype(float)
    fit = sgp.fit_rho(p_a, p_b, o_a, o_b, np.arange(n) // 30)
    assert abs(fit["rho"]) < 3 * fit["se"] + 0.005


def test_shrinkage_pulls_noise_to_zero_and_keeps_signal():
    cells = {"type": {f"a{i}~b~teammate": {"rho": r, "se": 0.08} for i, r in enumerate([0.1, -0.12, 0.05, -0.04, 0.09, -0.1])},
             "market": {}}
    cells["type"]["strong~b~teammate"] = {"rho": 0.45, "se": 0.02}
    sgp.shrink_cells(cells)
    noisy = [v["rho"] for k, v in cells["type"].items() if k.startswith("a")]
    assert max(abs(r) for r in noisy) < 0.1
    assert cells["type"]["strong~b~teammate"]["rho"] > 0.4
    assert all("rho_raw" in v for v in cells["type"].values())
