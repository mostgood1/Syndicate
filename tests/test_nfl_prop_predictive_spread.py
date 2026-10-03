"""Unit tests for scripts/fit_nfl_prop_predictive_spread.py -- arm math and the calibration slope."""
from __future__ import annotations

import importlib.util
import math
import random
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "fit_nfl_prop_predictive_spread.py"
_spec = importlib.util.spec_from_file_location("fit_nfl_spread", _PATH)
fit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fit)  # type: ignore[union-attr]


def _synthetic(true_slope: float, n: int = 6000, seed: int = 3):
    rng = random.Random(seed)
    ps, ys = [], []
    for _ in range(n):
        z = rng.uniform(-2.5, 2.5)
        p = 1 / (1 + math.exp(-z))                      # the forecast
        q = 1 / (1 + math.exp(-true_slope * z))         # the truth
        ps.append(p)
        ys.append(1 if rng.random() < q else 0)
    return ps, ys


def test_calibration_slope_is_one_for_a_calibrated_forecast():
    a, b = fit.calibration_slope(*_synthetic(1.0))
    assert b == pytest.approx(1.0, abs=0.1) and a == pytest.approx(0.0, abs=0.1)


def test_calibration_slope_detects_overconfidence():
    # the forecast is twice as extreme as the truth: slope ~0.5 is the signature of
    # "shrinking toward the base rate would help", which is NOT a spread repair
    _a, b = fit.calibration_slope(*_synthetic(0.5))
    assert b == pytest.approx(0.5, abs=0.08)


def test_sd_arms():
    r = {"n": 4, "mean": 50.0}
    sdv = {"prod": 20.0, 6.0: 18.0}
    assert fit.sd_for({"kind": "prod"}, r, sdv) == 20.0
    assert fit.sd_for({"kind": "flat_k", "k": 2.0}, r, sdv) == 40.0
    assert fit.sd_for({"kind": "sampling"}, r, sdv) == pytest.approx(20.0 * math.sqrt(1.25))
    # drift adds rate uncertainty in quadrature, proportional to the mean, on the chosen K variant
    assert fit.sd_for({"kind": "drift", "c": 0.3}, r, sdv) == pytest.approx(math.hypot(20.0, 15.0))
    assert fit.sd_for({"kind": "drift_refit", "c": 0.0, "K": 6.0}, r, sdv) == 18.0
    assert fit.sd_for({"kind": "prod"}, r, {"prod": None}) is None


def test_mix_falls_back_to_normal_like_production():
    assert fit.mix(0.4, None, 0.7) == 0.4      # log-normal undefined -> normal, as `_nfl_prop_model_probability`
    assert fit.mix(0.4, 0.6, 0.0) == 0.4
    assert fit.mix(0.4, 0.6, 0.5) == pytest.approx(0.5)
