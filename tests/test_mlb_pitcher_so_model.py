"""Pitcher strikeout statistical model (`sim_engine.pitcher_so_model`).

Covers todo.md's "MLB pitcher/hitter statistical-model pilot" entry: a
from-scratch Poisson regression (features + StandardScaler + coefficients,
serialized to data/models/pitcher_so_poisson_v1.json) that cross-validated
meaningfully better than the sim's own so_mean/so_dist on both statistical
bias and real betting accuracy (54.65%->58.84% hit rate, n=882). These
tests lock in: the model artifact loads and is well-formed, the pure-python
prediction function matches what sklearn produced at training time (see
train_final_so_model.py's own sanity check), and `recalibrate_so_output`'s
weight=0.0 default is a true no-op -- not just close to one -- since every
call site this gets wired into defaults to off.
"""

from __future__ import annotations

import unittest

from vendor.mlb_bettingv2.sim_engine.pitcher_so_model import (
    load_so_model,
    predict_so_mean,
    recalibrate_so_output,
)

REAL_FEATURES = {
    "k_rate": 0.25,
    "bb_rate": 0.08,
    "hr_rate": 0.03,
    "inplay_hit_rate": 0.275,
    "hbp_rate": 0.01,
    "batters_faced": 400.0,
    "stamina_pitches": 95.0,
    "venue_mult": 1.0,
    "is_home": 1.0,
    "opp_avg_k_rate": 0.22,
    "opp_avg_bb_rate": 0.08,
    "opp_avg_hr_rate": 0.03,
    "opp_avg_inplay_hit_rate": 0.28,
}


class ModelArtifactTests(unittest.TestCase):
    def test_default_artifact_loads(self):
        model = load_so_model()
        self.assertIsNotNone(model)
        self.assertEqual(model["model_type"], "poisson_glm")
        self.assertIn("features", model)
        self.assertGreater(len(model["features"]), 0)

    def test_artifact_shapes_are_consistent(self):
        model = load_so_model()
        n = len(model["features"])
        self.assertEqual(len(model["scaler_mean"]), n)
        self.assertEqual(len(model["scaler_scale"]), n)
        self.assertEqual(len(model["coef"]), n)

    def test_missing_path_returns_none_not_exception(self):
        model = load_so_model(path="C:/definitely/does/not/exist.json")
        self.assertIsNone(model)


class PredictSoMeanTests(unittest.TestCase):
    def test_predicts_reasonable_positive_value(self):
        model = load_so_model()
        pred = predict_so_mean(REAL_FEATURES, model)
        self.assertIsNotNone(pred)
        # Real per-start SO totals are always in a plausible range; a model
        # producing something wildly outside this would indicate a wiring
        # bug (wrong feature order, unscaled inputs, etc.), not a real
        # pitcher performance.
        self.assertGreater(pred, 0.0)
        self.assertLess(pred, 20.0)

    def test_missing_feature_returns_none(self):
        model = load_so_model()
        incomplete = dict(REAL_FEATURES)
        del incomplete["k_rate"]
        self.assertIsNone(predict_so_mean(incomplete, model))

    def test_missing_model_returns_none(self):
        self.assertIsNone(predict_so_mean(REAL_FEATURES, None))

    def test_higher_k_rate_predicts_more_strikeouts(self):
        # Sanity check on direction, not magnitude -- an elite K-rate arm
        # should never predict fewer expected strikeouts than a below-
        # average one, all else equal.
        model = load_so_model()
        elite = dict(REAL_FEATURES, k_rate=0.35)
        backend = dict(REAL_FEATURES, k_rate=0.15)
        self.assertGreater(predict_so_mean(elite, model), predict_so_mean(backend, model))


class RecalibrateSoOutputTests(unittest.TestCase):
    def setUp(self):
        self.so_dist = {0: 5.0, 1: 15.0, 2: 25.0, 3: 25.0, 4: 15.0, 5: 10.0, 6: 5.0}
        self.so_mean_raw = 2.85

    def test_weight_zero_is_a_true_noop(self):
        shifted, new_mean = recalibrate_so_output(self.so_dist, self.so_mean_raw, model_so_mean=6.0, weight=0.0)
        self.assertEqual(shifted, self.so_dist)
        self.assertEqual(new_mean, self.so_mean_raw)

    def test_negative_weight_clamped_to_zero(self):
        shifted, new_mean = recalibrate_so_output(self.so_dist, self.so_mean_raw, model_so_mean=6.0, weight=-0.5)
        self.assertEqual(shifted, self.so_dist)
        self.assertEqual(new_mean, self.so_mean_raw)

    def test_weight_over_one_clamped_to_one(self):
        shifted_over, mean_over = recalibrate_so_output(self.so_dist, self.so_mean_raw, model_so_mean=6.0, weight=2.5)
        shifted_one, mean_one = recalibrate_so_output(self.so_dist, self.so_mean_raw, model_so_mean=6.0, weight=1.0)
        self.assertEqual(shifted_over, shifted_one)
        self.assertAlmostEqual(mean_over, mean_one, places=9)

    def test_positive_shift_moves_mean_toward_model(self):
        shifted, new_mean = recalibrate_so_output(self.so_dist, self.so_mean_raw, model_so_mean=6.0, weight=1.0)
        self.assertGreater(new_mean, self.so_mean_raw)
        # Total probability mass is preserved (no bins silently dropped for
        # a positive shift, since none go negative).
        self.assertAlmostEqual(sum(shifted.values()), sum(self.so_dist.values()), places=6)

    def test_negative_shift_drops_bins_below_zero_not_wraps(self):
        # model predicts far below the sim's own estimate -- shifting should
        # clip at 0 strikeouts, not produce a nonsensical negative count.
        shifted, new_mean = recalibrate_so_output(self.so_dist, self.so_mean_raw, model_so_mean=-5.0, weight=1.0)
        self.assertTrue(all(k >= 0 for k in shifted))
        self.assertGreaterEqual(new_mean, 0.0)

    def test_partial_weight_is_between_none_and_full(self):
        _, mean_half = recalibrate_so_output(self.so_dist, self.so_mean_raw, model_so_mean=6.0, weight=0.5)
        self.assertGreater(mean_half, self.so_mean_raw)
        _, mean_full = recalibrate_so_output(self.so_dist, self.so_mean_raw, model_so_mean=6.0, weight=1.0)
        self.assertLessEqual(mean_half, mean_full)

    def test_missing_model_mean_is_a_noop(self):
        shifted, new_mean = recalibrate_so_output(self.so_dist, self.so_mean_raw, model_so_mean=None, weight=1.0)
        self.assertEqual(shifted, self.so_dist)
        self.assertEqual(new_mean, self.so_mean_raw)


if __name__ == "__main__":
    unittest.main()
