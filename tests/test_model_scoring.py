"""Tests for syndicate.features.shared.model_scoring -- CRPS/Brier/
log-loss/reliability-curve/bias-dispersion math. CRPS is verified two
ways: against a known closed-form special case AND against an independent
Monte Carlo sample-based CRPS estimator, so a hand-derivation error in the
closed form can't hide behind a single self-consistent check."""

from __future__ import annotations

import math
import random
import unittest

from syndicate.features.shared import model_scoring as scoring


class CrpsNormalTests(unittest.TestCase):
    def test_perfect_forecast_at_mean_matches_known_closed_form(self) -> None:
        # CRPS(N(0, sigma), actual=mean) = sigma * (2/sqrt(2*pi) - 1/sqrt(pi)).
        sigma = 1.0
        expected = sigma * (2.0 / math.sqrt(2.0 * math.pi) - 1.0 / math.sqrt(math.pi))
        actual_result = scoring.crps_normal(0.0, 0.0, sigma)
        self.assertAlmostEqual(actual_result, expected, places=9)

    def test_scales_linearly_with_sigma_at_zero_error(self) -> None:
        base = scoring.crps_normal(0.0, 0.0, 1.0)
        doubled = scoring.crps_normal(0.0, 0.0, 2.0)
        self.assertAlmostEqual(doubled, base * 2.0, places=9)

    def test_matches_monte_carlo_sample_based_estimator(self) -> None:
        # Independent cross-check: CRPS ~= E|X - actual| - 0.5*E|X - X'|
        # for iid X, X' ~ forecast distribution (the standard unbiased
        # sample estimator) -- verifies the closed form isn't just
        # internally self-consistent but actually correct.
        random.seed(1234)
        mean, sigma, actual = 5.0, 2.5, 7.0
        n = 200_000
        samples_a = [random.gauss(mean, sigma) for _ in range(n)]
        samples_b = [random.gauss(mean, sigma) for _ in range(n)]
        term1 = sum(abs(x - actual) for x in samples_a) / n
        term2 = sum(abs(a - b) for a, b in zip(samples_a, samples_b)) / n
        monte_carlo_crps = term1 - 0.5 * term2
        closed_form = scoring.crps_normal(actual, mean, sigma)
        self.assertAlmostEqual(closed_form, monte_carlo_crps, delta=0.02)

    def test_worse_forecast_scores_higher_crps(self) -> None:
        good = scoring.crps_normal(10.0, 10.0, 2.0)
        bad = scoring.crps_normal(10.0, 2.0, 2.0)
        self.assertLess(good, bad)

    def test_invalid_inputs_return_none(self) -> None:
        self.assertIsNone(scoring.crps_normal(None, 1.0, 1.0))
        self.assertIsNone(scoring.crps_normal(1.0, None, 1.0))
        self.assertIsNone(scoring.crps_normal(1.0, 1.0, 0.0))
        self.assertIsNone(scoring.crps_normal(1.0, 1.0, -1.0))
        self.assertIsNone(scoring.crps_normal("nope", 1.0, 1.0))


class MeanCrpsTests(unittest.TestCase):
    def test_averages_across_valid_pairs_and_skips_invalid(self) -> None:
        pairs = [(1.0, 1.0, 1.0), (5.0, 1.0, 1.0), (None, 1.0, 1.0)]
        result = scoring.mean_crps(pairs)
        self.assertEqual(result["sample_size"], 2)
        expected = (scoring.crps_normal(1.0, 1.0, 1.0) + scoring.crps_normal(5.0, 1.0, 1.0)) / 2
        self.assertAlmostEqual(result["mean_crps"], expected, places=9)

    def test_empty_returns_none(self) -> None:
        self.assertEqual(scoring.mean_crps([]), {"mean_crps": None, "sample_size": 0})


class PinballLossTests(unittest.TestCase):
    def test_median_pinball_loss_is_half_absolute_error(self) -> None:
        # At quantile_level=0.5, pinball loss reduces to 0.5 * |error|.
        self.assertAlmostEqual(scoring.pinball_loss(10.0, 8.0, 0.5), 1.0)
        self.assertAlmostEqual(scoring.pinball_loss(8.0, 10.0, 0.5), 1.0)

    def test_asymmetric_penalty_for_high_quantile(self) -> None:
        # At quantile_level=0.9, underprediction (actual > predicted) is
        # penalized 9x more than overprediction of the same magnitude.
        under = scoring.pinball_loss(11.0, 10.0, 0.9)
        over = scoring.pinball_loss(9.0, 10.0, 0.9)
        self.assertAlmostEqual(under, 0.9)
        self.assertAlmostEqual(over, 0.1)

    def test_invalid_quantile_level_returns_none(self) -> None:
        self.assertIsNone(scoring.pinball_loss(1.0, 1.0, 0.0))
        self.assertIsNone(scoring.pinball_loss(1.0, 1.0, 1.0))
        self.assertIsNone(scoring.pinball_loss(1.0, 1.0, 1.5))


class BrierAndLogLossTests(unittest.TestCase):
    def test_brier_score_perfect_and_worst_case(self) -> None:
        self.assertAlmostEqual(scoring.brier_score(1.0, 1.0), 0.0)
        self.assertAlmostEqual(scoring.brier_score(0.0, 1.0), 1.0)
        self.assertAlmostEqual(scoring.brier_score(0.5, 1.0), 0.25)

    def test_log_loss_penalizes_confident_wrong_far_more_than_brier(self) -> None:
        confident_wrong_brier = scoring.brier_score(0.99, 0.0)
        confident_wrong_log = scoring.log_loss(0.99, 0.0)
        unsure_wrong_brier = scoring.brier_score(0.5, 0.0)
        unsure_wrong_log = scoring.log_loss(0.5, 0.0)
        # Brier is ~4x worse (0.98 vs 0.25); log-loss penalizes confident-
        # and-wrong proportionally harder still (-ln(0.01) / -ln(0.5) ~= 6.6x).
        self.assertLess(confident_wrong_brier / unsure_wrong_brier, 5.0)
        self.assertGreater(confident_wrong_log / unsure_wrong_log, confident_wrong_brier / unsure_wrong_brier)

    def test_log_loss_never_infinite_at_the_extremes(self) -> None:
        self.assertTrue(math.isfinite(scoring.log_loss(1.0, 1.0)))
        self.assertTrue(math.isfinite(scoring.log_loss(0.0, 0.0)))
        self.assertTrue(math.isfinite(scoring.log_loss(0.0, 1.0)))

    def test_invalid_probability_returns_none(self) -> None:
        self.assertIsNone(scoring.brier_score(1.5, 1.0))
        self.assertIsNone(scoring.log_loss(-0.1, 1.0))


class BinaryCalibrationMetricsTests(unittest.TestCase):
    def test_aggregates_brier_and_log_loss(self) -> None:
        pairs = [(0.7, 1), (0.3, 0), (0.9, 0)]
        result = scoring.binary_calibration_metrics(pairs)
        self.assertEqual(result["sample_size"], 3)
        expected_brier = (scoring.brier_score(0.7, 1.0) + scoring.brier_score(0.3, 0.0) + scoring.brier_score(0.9, 0.0)) / 3
        self.assertAlmostEqual(result["brier_score"], expected_brier, places=9)


class ReliabilityCurveTests(unittest.TestCase):
    def test_overconfident_model_shows_positive_calibration_gap_pattern(self) -> None:
        # 100 picks all made at 0.9 confidence, but only 60% actually hit --
        # classic overconfidence. actual_rate should land near 0.6, well
        # below predicted_mean near 0.9, and the gap should be negative
        # (actual - predicted).
        random.seed(42)
        pairs = [(0.9, 1 if random.random() < 0.6 else 0) for _ in range(500)]
        curve = scoring.reliability_curve(pairs, n_bins=10)
        self.assertEqual(len(curve), 1)
        bucket = curve[0]
        self.assertAlmostEqual(bucket["predicted_mean"], 0.9, delta=0.01)
        self.assertAlmostEqual(bucket["actual_rate"], 0.6, delta=0.06)
        self.assertLess(bucket["calibration_gap"], -0.2)

    def test_well_calibrated_model_has_near_zero_gap(self) -> None:
        random.seed(7)
        pairs = []
        for p in (0.2, 0.4, 0.6, 0.8):
            pairs.extend((p, 1 if random.random() < p else 0) for _ in range(2000))
        curve = scoring.reliability_curve(pairs, n_bins=10)
        for bucket in curve:
            self.assertLess(abs(bucket["calibration_gap"]), 0.05)

    def test_empty_bins_are_omitted(self) -> None:
        curve = scoring.reliability_curve([(0.05, 1)], n_bins=10)
        self.assertEqual(len(curve), 1)
        self.assertEqual(curve[0]["sample_size"], 1)

    def test_boundary_probability_one_lands_in_last_bucket(self) -> None:
        curve = scoring.reliability_curve([(1.0, 1)], n_bins=10)
        self.assertEqual(len(curve), 1)
        self.assertEqual(curve[0]["bucket_low"], 0.9)


class BiasDispersionDecompositionTests(unittest.TestCase):
    def test_detects_systematic_low_bias(self) -> None:
        # Sim consistently predicts 2 below actual -> mean_signed_error ~= +2.
        triples = [(actual, actual - 2.0, 1.0) for actual in range(10, 20)]
        result = scoring.bias_dispersion_decomposition(triples)
        self.assertAlmostEqual(result["mean_signed_error"], 2.0, places=6)
        self.assertAlmostEqual(result["mean_absolute_error"], 2.0, places=6)

    def test_well_calibrated_normal_dispersion_ratio_near_expected_constant(self) -> None:
        random.seed(99)
        mean, sigma = 100.0, 10.0
        triples = [(random.gauss(mean, sigma), mean, sigma) for _ in range(50_000)]
        result = scoring.bias_dispersion_decomposition(triples)
        self.assertAlmostEqual(result["dispersion_ratio"], scoring.EXPECTED_DISPERSION_RATIO, delta=0.02)

    def test_overconfident_sigma_gives_dispersion_ratio_above_expected(self) -> None:
        random.seed(99)
        true_sigma = 20.0
        claimed_sigma = 5.0  # sim claims tighter uncertainty than it actually has
        triples = [(random.gauss(100.0, true_sigma), 100.0, claimed_sigma) for _ in range(20_000)]
        result = scoring.bias_dispersion_decomposition(triples)
        self.assertGreater(result["dispersion_ratio"], scoring.EXPECTED_DISPERSION_RATIO * 2)

    def test_empty_returns_none(self) -> None:
        result = scoring.bias_dispersion_decomposition([])
        self.assertEqual(result["sample_size"], 0)
        self.assertIsNone(result["mean_signed_error"])

    def test_skips_pairs_missing_sigma_but_still_scores_bias(self) -> None:
        triples = [(5.0, 3.0, None), (5.0, 3.0, 1.0)]
        result = scoring.bias_dispersion_decomposition(triples)
        self.assertEqual(result["sample_size"], 2)
        self.assertIsNotNone(result["dispersion_ratio"])  # only the second pair contributes


if __name__ == "__main__":
    unittest.main()
