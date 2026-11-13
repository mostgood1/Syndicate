"""The prop fair side correction: a logit shift of the over, its complement on the under, fitted by ML and shrunk."""
from __future__ import annotations

import random

import pytest

from syndicate.features.shared import prop_fair_side as pfs


def test_off_is_the_identity_and_on_moves_the_over_down_and_the_under_up():
    for p in (0.1, 0.35, 0.5, 0.62, 0.9):
        assert pfs.adjusted(p, side="over", delta=0.0) == pytest.approx(p)
        assert pfs.adjusted(p, side="under", delta=0.0) == pytest.approx(p)
    over, under = pfs.adjusted(0.52, side="over", delta=-0.15), pfs.adjusted(0.48, side="under", delta=-0.15)
    assert over < 0.52 and under > 0.48 and over + under == pytest.approx(1.0)      # still a fair pair
    assert pfs.adjusted(0.5, side="over", delta=-0.15) == pytest.approx(0.5 - 0.0374, abs=1e-3)   # ~3.7 pts at evens
    assert pfs.adjusted(0.4, side="home", delta=-0.15) == 0.4                        # not a prop side: untouched
    assert pfs.adjusted(0.4, side="yes", delta=-0.15) < 0.4 and pfs.adjusted(0.6, side="no", delta=-0.15) > 0.6


def test_fit_recovers_a_planted_shift():
    rng = random.Random(3)
    rows = []
    for _ in range(40000):
        p = rng.uniform(0.25, 0.75)
        rows.append((p, 1.0 if rng.random() < pfs.shift(p, -0.15) else 0.0))
    fit = pfs.fit_delta(rows)
    assert fit["n"] == 40000 and abs(fit["delta"] + 0.15) < 2.5 * fit["se"]
    assert pfs.fit_delta([]) is None and pfs.fit_delta([(0.5, 0.5)]) is None       # pushes carry nothing


def test_shrinkage_pulls_a_noisy_fit_toward_zero():
    precise = {"delta": -0.15, "se": 0.01, "n": 50000}
    noisy = pfs.inflate_se(precise, design_effect=400.0)                             # se 0.2
    assert pfs.shrunk(precise) == pytest.approx(-0.15 * 0.01 / 0.0101)
    assert abs(pfs.shrunk(noisy)) < abs(pfs.shrunk(precise)) and pfs.shrunk(noisy) == pytest.approx(-0.15 * 0.01 / 0.05)
    assert pfs.shrunk(None) == 0.0 and pfs.inflate_se(precise, design_effect=0.5)["se"] == 0.01


def test_log_loss_prefers_the_corrected_fair_when_the_over_really_is_overstated():
    rng = random.Random(5)
    rows = [(0.5, 1.0 if rng.random() < 0.46 else 0.0) for _ in range(20000)]
    before = sum(pfs.log_loss(p, y) for p, y in rows)
    after = sum(pfs.log_loss(pfs.shift(p, -0.15), y) for p, y in rows)
    assert after < before
