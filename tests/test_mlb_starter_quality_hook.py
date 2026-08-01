"""Starter quality-aware hook adjustment in the vendored MLB sim engine.

Covers the third fix for todo.md #178: `eff_hook` (`_starter_effective_hook`)
is driven entirely by `stamina_pitches` -- a season pitches-per-start
average that reflects workload history, not pitching quality -- so real
starters with very different true talent can derive to nearly the same
eff_hook (confirmed 2026-08-01: Chris Sale [.336 K-rate] and Nick Martinez
[.116 K-rate] both derived to stamina_pitches=89 in a real slate). A live
pull-decision trace on that slate confirmed eff_hook does correctly drive
real pull timing (corr 0.51 with actual pitch-count-at-removal) -- the
mechanism works, it just has no channel for the pitcher's own quality to
matter. `_starter_matchup_hook_adjustment` already gives the *opposing*
lineup's quality this kind of influence; `_starter_quality_hook_delta` adds
an opt-in additive pitch-count adjustment (`starter_quality_hook_weight`,
default 0.0 = unchanged behavior).

Recalibrated 2026-08-01 (part 6) from a first cut that used raw K-rate
deviation from a fixed constant and was found real but badly miscalibrated
in real backtesting (overshot elite, made mid-high *worse*). The current
version uses K-rate minus BB-rate (K-BB%, a standard real quality proxy)
and the exact coefficients from an OLS fit of real per-start outs bias
against K-BB% (n=1210, from the 46-date baseline batch): zero-crossing
reference=0.307, slope=-15.29 outs per unit of (k_rate-bb_rate) deviation
(so the *correction* slope is +15.29, i.e. `starter_quality_hook_slope`
below).
"""

from __future__ import annotations

import unittest

from vendor.mlb_bettingv2.sim_engine.simulate import _starter_quality_hook_delta

# Reference point (K-BB% zero-crossing) the defaults are calibrated around.
REFERENCE = 0.307
LEAGUE_BB = 0.08  # fallback used when bb_rate is unavailable

# Clearly above/below REFERENCE once bb_rate is netted out (not just above/
# below raw K-rate), so these exercise the actual signal the function uses.
ELITE_K, ELITE_BB = 0.42, 0.03  # k - bb = 0.39 > REFERENCE (raw delta ~+1.27 at weight=1.0)
BACKEND_K, BACKEND_BB = 0.12, 0.14  # k - bb = -0.02 < REFERENCE (raw delta ~-5.0 at weight=1.0)
# k - bb exactly at REFERENCE using the LEAGUE_BB fallback.
AT_REFERENCE_K = REFERENCE + LEAGUE_BB


class _Pitcher:
    def __init__(self, k_rate: float, bb_rate: float = None):
        self.k_rate = k_rate
        if bb_rate is not None:
            self.bb_rate = bb_rate


class DefaultBehaviorTests(unittest.TestCase):
    def test_default_weight_is_a_no_op_regardless_of_quality(self):
        for k, bb in [(0.05, 0.15), (BACKEND_K, BACKEND_BB), (AT_REFERENCE_K, None), (ELITE_K, ELITE_BB), (0.60, 0.03)]:
            with self.subTest(k_rate=k, bb_rate=bb):
                self.assertEqual(_starter_quality_hook_delta(_Pitcher(k, bb), {}), 0)
                self.assertEqual(_starter_quality_hook_delta(_Pitcher(k, bb), {"starter_quality_hook_weight": 0.0}), 0)

    def test_missing_overrides_dict_is_a_no_op(self):
        self.assertEqual(_starter_quality_hook_delta(_Pitcher(ELITE_K, ELITE_BB), None), 0)

    def test_missing_k_rate_attribute_is_a_no_op(self):
        class NoRate:
            pass

        self.assertEqual(
            _starter_quality_hook_delta(NoRate(), {"starter_quality_hook_weight": 0.8}),
            0,
        )

    def test_missing_bb_rate_attribute_falls_back_to_league_average(self):
        # A pitcher with no bb_rate field at all should behave exactly like
        # one whose bb_rate is explicitly the league-average fallback.
        with_field = _starter_quality_hook_delta(_Pitcher(ELITE_K, LEAGUE_BB), {"starter_quality_hook_weight": 0.5})
        without_field = _starter_quality_hook_delta(_Pitcher(ELITE_K), {"starter_quality_hook_weight": 0.5})
        self.assertEqual(with_field, without_field)


class QualityHookDeltaTests(unittest.TestCase):
    def test_at_reference_signal_gets_no_adjustment(self):
        for weight in (0.25, 0.5, 1.0):
            with self.subTest(weight=weight):
                delta = _starter_quality_hook_delta(_Pitcher(AT_REFERENCE_K), {"starter_quality_hook_weight": weight})
                self.assertEqual(delta, 0)

    def test_elite_pitcher_gets_a_longer_leash(self):
        delta = _starter_quality_hook_delta(_Pitcher(ELITE_K, ELITE_BB), {"starter_quality_hook_weight": 0.5})
        self.assertGreater(delta, 0)

    def test_backend_pitcher_gets_a_shorter_leash(self):
        delta = _starter_quality_hook_delta(_Pitcher(BACKEND_K, BACKEND_BB), {"starter_quality_hook_weight": 0.5})
        self.assertLess(delta, 0)

    def test_higher_bb_rate_shortens_the_leash_for_the_same_k_rate(self):
        # K-BB%, not raw K-rate, drives the signal -- more walks at a fixed
        # K-rate should pull the delta down (or make it more negative).
        low_bb = _starter_quality_hook_delta(_Pitcher(0.30, 0.05), {"starter_quality_hook_weight": 0.5})
        high_bb = _starter_quality_hook_delta(_Pitcher(0.30, 0.15), {"starter_quality_hook_weight": 0.5})
        self.assertLess(high_bb, low_bb)

    def test_delta_is_monotonic_in_weight(self):
        prior_elite = None
        prior_backend = None
        for weight in (0.0, 0.25, 0.5, 0.75, 1.0):
            elite_delta = _starter_quality_hook_delta(_Pitcher(ELITE_K, ELITE_BB), {"starter_quality_hook_weight": weight})
            backend_delta = _starter_quality_hook_delta(_Pitcher(BACKEND_K, BACKEND_BB), {"starter_quality_hook_weight": weight})
            if prior_elite is not None:
                self.assertGreaterEqual(elite_delta, prior_elite - 1e-9)
            if prior_backend is not None:
                self.assertLessEqual(backend_delta, prior_backend + 1e-9)
            prior_elite, prior_backend = elite_delta, backend_delta

    def test_result_is_bounded_by_max_pitches(self):
        # Absurdly extreme K-BB% shouldn't blow the delta up past the
        # configured max_pitches ceiling.
        delta_hi = _starter_quality_hook_delta(
            _Pitcher(0.60, 0.01),
            {"starter_quality_hook_weight": 1.0, "starter_quality_hook_max_pitches": 10.0},
        )
        delta_lo = _starter_quality_hook_delta(
            _Pitcher(0.05, 0.20),
            {"starter_quality_hook_weight": 1.0, "starter_quality_hook_max_pitches": 10.0},
        )
        self.assertLessEqual(delta_hi, 10)
        self.assertGreaterEqual(delta_lo, -10)

    def test_custom_max_pitches_scales_the_result(self):
        # A signal extreme enough to exceed the smaller cap (raw delta ~+2.6).
        very_elite = _Pitcher(0.50, 0.02)
        small = _starter_quality_hook_delta(
            very_elite, {"starter_quality_hook_weight": 1.0, "starter_quality_hook_max_pitches": 2.0}
        )
        large = _starter_quality_hook_delta(
            very_elite, {"starter_quality_hook_weight": 1.0, "starter_quality_hook_max_pitches": 20.0}
        )
        self.assertGreater(large, small)

    def test_custom_reference_and_slope_are_respected(self):
        default_delta = _starter_quality_hook_delta(_Pitcher(ELITE_K, ELITE_BB), {"starter_quality_hook_weight": 0.5})
        custom_delta = _starter_quality_hook_delta(
            _Pitcher(ELITE_K, ELITE_BB),
            {"starter_quality_hook_weight": 0.5, "starter_quality_hook_reference": 0.40, "starter_quality_hook_slope": 5.0},
        )
        self.assertNotEqual(default_delta, custom_delta)

    def test_default_weight_one_approximates_uncapped_regression_correction(self):
        # At weight=1.0 and a signal well inside the cap, the delta should
        # closely track slope * (signal - reference) -- the whole point of
        # switching from a hand-picked magnitude to the fitted regression.
        k, bb = 0.32, 0.06  # signal = 0.26, a modest deviation, unlikely to hit the cap
        delta = _starter_quality_hook_delta(_Pitcher(k, bb), {"starter_quality_hook_weight": 1.0})
        expected = round(15.29 * ((k - bb) - 0.307))
        self.assertEqual(delta, expected)


if __name__ == "__main__":
    unittest.main()
