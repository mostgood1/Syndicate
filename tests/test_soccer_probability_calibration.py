"""Tests for the soccer win-probability sharpening calibration.

The load-bearing test here is `test_fit_recovers_a_known_temperature`. Every
other test checks a property of the transform; that one checks the FITTER can
find a distortion it did not know about, which is the only claim the script
actually makes.

`test_split_is_chronological_and_never_straddles_a_day` guards the leakage rule
the whole soccer lane exists because of: a random split would leak the future
into a fitted parameter, silently, and produce an "improvement" that is the same
class of artifact as the retired `*_backtest_*.csv` files.
"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "fit_soccer_probability_calibration",
    Path(__file__).resolve().parents[1] / "scripts" / "fit_soccer_probability_calibration.py",
)
calibration = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(calibration)


def _match(date: str, model: dict[str, float], actual: str, league: str = "epl", home: str = "A") -> dict:
    return {
        "league": league,
        "date": date,
        "home_team": home,
        "away_team": "B",
        "model_home": model["home"],
        "model_draw": model["draw"],
        "model_away": model["away"],
        "market_home": 0.45,
        "market_draw": 0.27,
        "market_away": 0.28,
        "actual": actual,
    }


def test_temperature_one_is_the_identity():
    probabilities = {"home": 0.5, "draw": 0.3, "away": 0.2}
    result = calibration.sharpen(probabilities, 1.0)
    for outcome in ("home", "draw", "away"):
        assert result[outcome] == pytest.approx(probabilities[outcome])


def test_sharpening_increases_dispersion_and_flattening_reduces_it():
    probabilities = {"home": 0.5, "draw": 0.3, "away": 0.2}
    sharper = calibration.sharpen(probabilities, 0.5)
    flatter = calibration.sharpen(probabilities, 2.0)
    # The favourite gets more probable when sharpened, less when flattened.
    assert sharper["home"] > probabilities["home"] > flatter["home"]
    # And the longshot moves the other way.
    assert sharper["away"] < probabilities["away"] < flatter["away"]


def test_sharpen_always_returns_a_distribution():
    for temperature in (0.3, 0.75, 1.0, 1.6, 2.5):
        result = calibration.sharpen({"home": 0.62, "draw": 0.21, "away": 0.17}, temperature)
        assert sum(result.values()) == pytest.approx(1.0)
        assert all(value >= 0 for value in result.values())


def test_a_zero_probability_stays_zero():
    """``0 ** 0`` is 1, which would resurrect an outcome the model ruled out."""
    result = calibration.sharpen({"home": 0.7, "draw": 0.3, "away": 0.0}, 0.5)
    assert result["away"] == pytest.approx(0.0)
    assert sum(result.values()) == pytest.approx(1.0)


def test_non_positive_temperature_is_rejected():
    with pytest.raises(ValueError):
        calibration.sharpen({"home": 0.5, "draw": 0.3, "away": 0.2}, 0.0)


def test_fit_recovers_a_known_temperature():
    """Flatten a sharp truth by a known T, then check the fitter finds it.

    Outcomes are generated DETERMINISTICALLY in proportion to the true
    distribution rather than sampled, so the test asserts on the objective's
    minimum rather than on a random draw -- a sampled version would be flaky at
    this sample size and would test the RNG as much as the fitter.
    """
    truth = {"home": 0.70, "draw": 0.18, "away": 0.12}
    applied = 1.8  # the distortion the fitter must undo
    observed = calibration.sharpen(truth, applied)

    rows = []
    # 100 matches per outcome-share, dated so the split is well defined.
    for index in range(100):
        actual = "home" if index < 70 else ("draw" if index < 88 else "away")
        rows.append(_match(f"2024-01-{index % 28 + 1:02d}", observed, actual))

    recovered = calibration.fit_temperature(rows, objective="log_loss")
    # Undoing a flattening of 1.8 means fitting T ~ 1/1.8 = 0.556 relative to the
    # observed distribution.
    assert recovered == pytest.approx(1.0 / applied, abs=0.08)


def test_fitting_a_well_calibrated_model_returns_about_one():
    truth = {"home": 0.50, "draw": 0.25, "away": 0.25}
    rows = []
    for index in range(200):
        actual = "home" if index < 100 else ("draw" if index < 150 else "away")
        rows.append(_match(f"2024-02-{index % 28 + 1:02d}", truth, actual))
    assert calibration.fit_temperature(rows, objective="log_loss") == pytest.approx(1.0, abs=0.08)


def test_split_is_chronological_and_never_straddles_a_day():
    rows = [_match("2024-01-01", {"home": 0.5, "draw": 0.3, "away": 0.2}, "home", home=f"T{i}") for i in range(4)]
    rows += [_match("2024-02-01", {"home": 0.5, "draw": 0.3, "away": 0.2}, "draw", home=f"U{i}") for i in range(4)]
    rows += [_match("2024-03-01", {"home": 0.5, "draw": 0.3, "away": 0.2}, "away", home=f"V{i}") for i in range(4)]

    train, test = calibration.chronological_split(rows, 0.6)

    assert train and test
    # Every train date strictly precedes every test date.
    assert max(row["date"] for row in train) < min(row["date"] for row in test)
    # No day appears on both sides.
    assert not ({row["date"] for row in train} & {row["date"] for row in test})
    assert len(train) + len(test) == len(rows)


def test_split_does_not_reorder_away_matches():
    rows = [_match(f"2024-0{month}-01", {"home": 0.5, "draw": 0.3, "away": 0.2}, "home") for month in (3, 1, 2)]
    train, test = calibration.chronological_split(rows, 0.5)
    assert len(train) + len(test) == 3


def test_evaluate_reports_raw_and_calibrated_against_the_same_market():
    rows = [_match("2024-01-01", {"home": 0.5, "draw": 0.3, "away": 0.2}, "home") for _ in range(10)]
    result = calibration.evaluate(rows, 0.5)
    assert result["n"] == 10
    # Sharpening toward the actual outcome must improve Brier here.
    assert result["model_brier_calibrated"] < result["model_brier_raw"]
    # The market benchmark does not move with the temperature.
    assert result["gap_raw"] - result["gap_calibrated"] == pytest.approx(
        result["model_brier_raw"] - result["model_brier_calibrated"], abs=1e-4
    )


def test_calibrated_stdev_rises_when_sharpened():
    rows = [
        _match("2024-01-01", {"home": 0.7, "draw": 0.2, "away": 0.1}, "home"),
        _match("2024-01-02", {"home": 0.3, "draw": 0.3, "away": 0.4}, "away"),
    ]
    assert calibration.stdev_home(rows, 0.5) > calibration.stdev_home(rows, 1.0)


def test_log_loss_punishes_a_confident_miss_more_than_brier():
    """Why `log_loss` is the default objective: it is the one that notices."""
    confident_miss = {"home": 0.95, "draw": 0.03, "away": 0.02}
    timid_miss = {"home": 0.50, "draw": 0.30, "away": 0.20}
    brier_ratio = calibration.brier(confident_miss, "away") / calibration.brier(timid_miss, "away")
    log_loss_ratio = calibration.log_loss(confident_miss, "away") / calibration.log_loss(timid_miss, "away")
    assert log_loss_ratio > brier_ratio
    assert math.isfinite(log_loss_ratio)


def test_auc_is_invariant_to_temperature():
    """The property that makes AUC the right discrimination measure here."""
    rows = [
        _match("2024-01-01", {"home": 0.70, "draw": 0.18, "away": 0.12}, "home"),
        _match("2024-01-02", {"home": 0.55, "draw": 0.25, "away": 0.20}, "away"),
        _match("2024-01-03", {"home": 0.40, "draw": 0.30, "away": 0.30}, "home"),
        _match("2024-01-04", {"home": 0.25, "draw": 0.30, "away": 0.45}, "away"),
    ]
    labels = [row["actual"] == "home" for row in rows]
    baseline = calibration.auc([calibration._model_of(row)["home"] for row in rows], labels)
    for temperature in (0.4, 0.7, 1.0, 1.5, 2.2):
        scaled = calibration.auc(
            [calibration.sharpen(calibration._model_of(row), temperature)["home"] for row in rows], labels
        )
        assert scaled == pytest.approx(baseline)


def test_auc_is_one_for_a_perfect_ranking_and_zero_for_an_inverted_one():
    labels = [True, True, False, False]
    assert calibration.auc([0.9, 0.8, 0.2, 0.1], labels) == pytest.approx(1.0)
    assert calibration.auc([0.1, 0.2, 0.8, 0.9], labels) == pytest.approx(0.0)


def test_auc_averages_ties_to_one_half():
    assert calibration.auc([0.5, 0.5, 0.5, 0.5], [True, True, False, False]) == pytest.approx(0.5)


def test_auc_is_nan_when_a_class_is_absent():
    """Undefined must not be reported as a coin flip."""
    assert math.isnan(calibration.auc([0.6, 0.4], [True, True]))
    assert math.isnan(calibration.auc([0.6, 0.4], [False, False]))
