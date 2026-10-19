"""Hermetic tests for the UEFA market-anchored corrections (todo #699 follow-up). No network."""

from __future__ import annotations

import numpy as np
import pytest

from syndicate.features.soccer import uefa_league_offsets as ulo
from syndicate.features.soccer import uefa_market_anchor as uma


def _matches(n=400, seed=3, truth=None):
    """Base model rates are flat (1.4 / 1.1); the 'market' knows club S is stronger and W weaker."""
    truth = truth or {"S": (0.35, 0.25), "W": (-0.30, -0.20)}
    rng = np.random.default_rng(seed)
    clubs = ["S", "W", "A", "B", "C", "D"]
    out = []
    for _ in range(n):
        h, a = rng.choice(clubs, 2, replace=False)
        ah, dh = truth.get(h, (0.0, 0.0))
        aa, da = truth.get(a, (0.0, 0.0))
        lh, la = 1.4 * np.exp(ah - da), 1.1 * np.exp(aa - dh)
        p = uma.probs_from_rates(lh, la)
        y = int(rng.choice(3, p=p))
        out.append(uma.AnchorMatch(h, a, 1.4, 1.1, p, y))
    return out, truth


def test_probs_match_the_shared_poisson_helper():
    assert uma.probs_from_rates(1.7, 0.9) == pytest.approx(ulo.outcome_probs(1.7, 0.9))


def test_analytic_gradient_matches_finite_differences():
    lh, la = np.array([1.3, 2.1]), np.array([0.8, 1.6])
    q, dqh, dqa = uma._probs_and_grads(lh, la)
    eps = 1e-6
    qp, _, _ = uma._probs_and_grads(lh * np.exp(eps), la)
    qm, _, _ = uma._probs_and_grads(lh * np.exp(-eps), la)
    assert np.allclose(dqh, (qp - qm) / (2 * eps), atol=1e-6)
    qp, _, _ = uma._probs_and_grads(lh, la * np.exp(eps))
    qm, _, _ = uma._probs_and_grads(lh, la * np.exp(-eps))
    assert np.allclose(dqa, (qp - qm) / (2 * eps), atol=1e-6)
    assert np.allclose(q.sum(axis=1), 1.0)


def test_fit_recovers_what_the_close_knows_and_beats_the_base_model():
    ms, truth = _matches()
    fit = uma.fit_anchor(ms, tau=0.1)
    for club, (a, d) in truth.items():
        fa, fd = fit.corrections[club]
        assert abs(fa - a) < 0.08 and abs(fd - d) < 0.08, (club, fa, fd)
    base = uma.AnchorFit({}, 0.0, 0)
    assert uma.mean_outcome_log_loss(fit, ms) < uma.mean_outcome_log_loss(base, ms)


def test_huge_tau_unseen_clubs_and_zero_weights_change_nothing():
    ms, _ = _matches(n=200)
    assert all(abs(x) < 1e-3 for ad in uma.fit_anchor(ms, tau=1e6).corrections.values() for x in ad)
    fit = uma.fit_anchor(ms, tau=1.0)
    unseen = uma.AnchorMatch("NEW1", "NEW2", 1.4, 1.1, (0.4, 0.3, 0.3), 0)
    assert fit.probs(unseen) == pytest.approx(uma.probs_from_rates(1.4, 1.1))
    poison = [uma.AnchorMatch("S", "W", 1.4, 1.1, (0.0, 0.0, 1.0), 2) for _ in range(100)]
    zw = uma.fit_anchor(ms + poison, tau=1.0, weights=[1.0] * len(ms) + [0.0] * len(poison))
    assert zw.corrections["S"] == pytest.approx(fit.corrections["S"], abs=1e-4)
    with pytest.raises(ValueError):
        uma.fit_anchor(ms, tau=1.0, weights=[1.0])


def test_select_tau_returns_a_grid_value_and_recency_weights_halve():
    ms, _ = _matches(n=300)
    tau, scores = uma.select_tau(ms[:200], [1.0] * 200, ms[200:], grid=(1.0, 100.0))
    assert tau in (1.0, 100.0) and scores[f"{tau:g}"] == min(scores.values())
    assert uma.recency_weights(["2025-07-01", "2024-07-01"], "2025-07-01") == pytest.approx([1.0, 0.5], rel=1e-3)
