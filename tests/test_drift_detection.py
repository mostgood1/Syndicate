"""Tests for syndicate.features.shared.drift_detection.detect_metric_drift."""

from __future__ import annotations

import random
import unittest

from syndicate.features.shared.drift_detection import detect_metric_drift


class DetectMetricDriftTests(unittest.TestCase):
    def test_insufficient_data_does_not_flag(self) -> None:
        result = detect_metric_drift([1.0, 2.0], [1.0, 2.0, 3.0], min_sample_size=10)
        self.assertFalse(result["flagged"])
        self.assertEqual(result["reason"], "insufficient_data")

    def test_clear_shift_is_flagged(self) -> None:
        random.seed(1)
        baseline = [random.gauss(0.0, 1.0) for _ in range(200)]
        recent = [random.gauss(5.0, 1.0) for _ in range(200)]  # huge, unmistakable shift
        result = detect_metric_drift(recent, baseline)
        self.assertTrue(result["flagged"])
        self.assertGreater(abs(result["z_score"]), 2.5)

    def test_no_real_shift_usually_does_not_flag(self) -> None:
        random.seed(2)
        baseline = [random.gauss(10.0, 2.0) for _ in range(300)]
        recent = [random.gauss(10.0, 2.0) for _ in range(300)]  # same distribution
        result = detect_metric_drift(recent, baseline)
        self.assertFalse(result["flagged"])

    def test_false_positive_rate_is_reasonable_under_repeated_no_drift_trials(self) -> None:
        # Independent statistical sanity check: with z_threshold=2.5 and
        # truly identical distributions, false-positive rate should be low
        # (roughly ~1% under a normal approximation) -- run many trials and
        # assert it's nowhere near, say, 20%, which would indicate a bug in
        # the z-score math rather than expected sampling noise.
        random.seed(3)
        false_positives = 0
        trials = 200
        for _ in range(trials):
            baseline = [random.gauss(0.0, 1.0) for _ in range(30)]
            recent = [random.gauss(0.0, 1.0) for _ in range(30)]
            if detect_metric_drift(recent, baseline, min_sample_size=10)["flagged"]:
                false_positives += 1
        self.assertLess(false_positives / trials, 0.10)

    def test_small_but_real_shift_with_low_variance_is_detected(self) -> None:
        # A small delta (0.3) can still be a real, flaggable shift if both
        # windows are very low-variance/high-sample -- this is exactly the
        # case a raw fixed-delta threshold would miss but a z-score catches.
        random.seed(4)
        baseline = [random.gauss(100.0, 0.5) for _ in range(200)]
        recent = [random.gauss(100.3, 0.5) for _ in range(200)]
        result = detect_metric_drift(recent, baseline)
        self.assertTrue(result["flagged"])

    def test_identical_constant_windows_never_flag(self) -> None:
        result = detect_metric_drift([5.0] * 20, [5.0] * 20)
        self.assertFalse(result["flagged"])
        self.assertIsNone(result["z_score"])

    def test_constant_windows_with_different_values_always_flag(self) -> None:
        result = detect_metric_drift([5.0] * 20, [4.0] * 20)
        self.assertTrue(result["flagged"])

    def test_none_values_are_filtered_out(self) -> None:
        result = detect_metric_drift([1.0, None, 2.0, None, 3.0] * 4, [1.0, 2.0, 3.0] * 4, min_sample_size=5)
        self.assertEqual(result["n_recent"], 12)


if __name__ == "__main__":
    unittest.main()
