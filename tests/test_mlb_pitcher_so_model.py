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


def _p_over(dist, line):
    total = sum(dist.values())
    return sum(v for k, v in dist.items() if float(k) > line) / total


class FractionalShiftTests(unittest.TestCase):
    """The sub-half-strikeout corrections that int(round(...)) used to discard.

    recalibrate_so_output originally translated bins by
    `int(round(weight * (model_so_mean - so_mean_raw)))`, so any model
    correction under 0.5 K produced no change at all. Measured over 312 real
    starts (real Monte Carlo so_dist + real OddsAPI line), one K of shift is
    worth 16.3pp of P(over) on average, so that rounding cost up to 8.2pp of
    mispricing against a ~3pp break-even edge. These lock in the fractional
    behaviour that replaced it.
    """

    def setUp(self):
        self.so_dist = {0: 5.0, 1: 15.0, 2: 25.0, 3: 25.0, 4: 15.0, 5: 10.0, 6: 5.0}
        self.dist_mean = 2.80  # sum(k*v)/sum(v) for the dist above
        self.so_mean_raw = 2.85

    def test_sub_half_delta_is_no_longer_discarded(self):
        # delta = +0.30 K. The old int(round(0.30)) == 0 made this a no-op.
        shifted, new_mean = recalibrate_so_output(
            self.so_dist, self.so_mean_raw, model_so_mean=self.so_mean_raw + 0.30, weight=1.0
        )
        self.assertNotEqual(shifted, self.so_dist)
        self.assertGreater(new_mean, self.dist_mean)

    def test_new_mean_moves_by_exactly_delta(self):
        for delta in (0.10, 0.30, 0.49, 0.75, 1.20):
            with self.subTest(delta=delta):
                _, new_mean = recalibrate_so_output(
                    self.so_dist, self.so_mean_raw, model_so_mean=self.so_mean_raw + delta, weight=1.0
                )
                self.assertAlmostEqual(new_mean, self.dist_mean + delta, places=9)

    def test_negative_delta_moves_by_exactly_delta_when_nothing_clips(self):
        # Same exactness guarantee downward, on a distribution held clear of
        # the zero floor so no mass is dropped.
        dist = {4: 10.0, 5: 30.0, 6: 40.0, 7: 20.0}
        dist_mean = sum(k * v for k, v in dist.items()) / sum(dist.values())
        for delta in (-0.10, -0.35, -0.80, -1.50):
            with self.subTest(delta=delta):
                _, new_mean = recalibrate_so_output(dist, 5.7, model_so_mean=5.7 + delta, weight=1.0)
                self.assertAlmostEqual(new_mean, dist_mean + delta, places=9)

    def test_negative_shift_past_zero_drops_mass_and_lifts_the_mean(self):
        # A strikeout count can't go below zero, so mass shifted past it is
        # dropped rather than clamped onto bin 0 (see _translate_bins). That
        # necessarily pulls the resulting mean slightly ABOVE mean + delta --
        # documented here so the exactness tests above aren't read as a
        # promise this case breaks.
        shifted, new_mean = recalibrate_so_output(
            self.so_dist, self.so_mean_raw, model_so_mean=self.so_mean_raw - 0.40, weight=1.0
        )
        self.assertTrue(all(k >= 0 for k in shifted))
        self.assertLess(sum(shifted.values()), sum(self.so_dist.values()))
        self.assertGreater(new_mean, self.dist_mean - 0.40)
        self.assertLess(new_mean, self.dist_mean)

    def test_p_over_scales_with_the_fractional_part(self):
        # The betting-relevant property: P(over) at a half-integer line must
        # respond proportionally, not in whole-K steps.
        line = 2.5
        base = _p_over(self.so_dist, line)
        full, _ = recalibrate_so_output(self.so_dist, self.so_mean_raw, self.so_mean_raw + 1.0, 1.0)
        p_full = _p_over(full, line)
        for frac in (0.25, 0.5, 0.75):
            with self.subTest(frac=frac):
                shifted, _ = recalibrate_so_output(
                    self.so_dist, self.so_mean_raw, self.so_mean_raw + frac, 1.0
                )
                self.assertAlmostEqual(_p_over(shifted, line), base + frac * (p_full - base), places=9)

    def test_p_over_is_monotonic_in_delta(self):
        line = 2.5
        probs = []
        for i in range(21):
            delta = -1.0 + 0.1 * i
            shifted, _ = recalibrate_so_output(
                self.so_dist, self.so_mean_raw, self.so_mean_raw + delta, 1.0
            )
            probs.append(_p_over(shifted, line))
        for earlier, later in zip(probs, probs[1:]):
            self.assertLessEqual(earlier, later + 1e-12)

    def test_whole_number_delta_stays_a_pure_translation(self):
        # No mixture smoothing when none is needed -- an exact 2 K shift must
        # reproduce the original bins moved by 2, counts untouched.
        shifted, _ = recalibrate_so_output(
            self.so_dist, self.so_mean_raw, model_so_mean=self.so_mean_raw + 2.0, weight=1.0
        )
        self.assertEqual(shifted, {k + 2: v for k, v in self.so_dist.items()})

    def test_total_mass_is_preserved(self):
        for delta in (0.30, 0.60, 1.40):
            with self.subTest(delta=delta):
                shifted, _ = recalibrate_so_output(
                    self.so_dist, self.so_mean_raw, model_so_mean=self.so_mean_raw + delta, weight=1.0
                )
                self.assertAlmostEqual(sum(shifted.values()), sum(self.so_dist.values()), places=9)

    def test_negligible_delta_is_still_a_true_noop(self):
        shifted, new_mean = recalibrate_so_output(
            self.so_dist, self.so_mean_raw, model_so_mean=self.so_mean_raw + 1e-12, weight=1.0
        )
        self.assertEqual(shifted, self.so_dist)
        self.assertEqual(new_mean, self.so_mean_raw)

    def test_emits_fractional_counts(self):
        # Contract check for downstream readers: so_dist bin counts are no
        # longer integers. _prob_over_line_from_dist / _mean_from_dist in
        # tools/daily_update_multi_profile.py were made float-safe for this;
        # any new consumer that does int(count) would silently truncate the
        # correction back out.
        shifted, _ = recalibrate_so_output(
            self.so_dist, self.so_mean_raw, model_so_mean=self.so_mean_raw + 0.5, weight=1.0
        )
        self.assertTrue(any(abs(v - round(v)) > 1e-9 for v in shifted.values()))

    def test_variance_penalty_of_the_mixture_is_bounded(self):
        # A non-integer lattice translation adds frac*(1-frac) of variance,
        # max 0.25 K^2 at frac=0.5. Documented and deliberate -- the sim's
        # own so_dist is underdispersed (median var/mean 0.754 over the 312
        # measured starts), so widening it slightly is far cheaper than the
        # 16.3pp-per-K centering error the rounding used to introduce.
        def variance(dist):
            total = sum(dist.values())
            mu = sum(k * v for k, v in dist.items()) / total
            return sum(v * (k - mu) ** 2 for k, v in dist.items()) / total

        base_var = variance(self.so_dist)
        shifted, _ = recalibrate_so_output(
            self.so_dist, self.so_mean_raw, model_so_mean=self.so_mean_raw + 0.5, weight=1.0
        )
        self.assertAlmostEqual(variance(shifted), base_var + 0.25, places=9)


if __name__ == "__main__":
    unittest.main()
