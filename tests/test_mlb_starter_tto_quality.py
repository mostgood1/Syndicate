"""Starter TTO3 (times-through-order) penalty quality-scaling in the vendored
MLB sim engine.

Covers the second fix for todo.md #176/#177: `pull_starter_third_time_penalty`
(the manager-level penalty applied once a starter faces a lineup a third
time) and its two consumers -- the pull-probability logit in
`_select_pitcher_v2` and the K/BB/HR/inplay rate degradation in
`_adjust_pitcher_day_rates_v2` -- previously applied the exact same penalty
to every starter regardless of quality, unlike `_starter_matchup_hook_adjustment`,
which already scales by the *opposing* lineup's quality. `_starter_tto_quality_mult`
adds an opt-in scaling knob (`starter_tto_quality_scaling`, default 0.0 =
unchanged behavior) so elite (high-K) starters get a softer TTO3 penalty and
below-average starters get a steeper one.
"""

from __future__ import annotations

import unittest

from vendor.mlb_bettingv2.sim_engine.simulate import _starter_tto_quality_mult

LEAGUE_K = 0.223
ELITE_K = 0.35
BACKEND_K = 0.15


class _Pitcher:
    def __init__(self, k_rate: float):
        self.k_rate = k_rate


class DefaultBehaviorTests(unittest.TestCase):
    def test_default_scaling_is_a_no_op_regardless_of_quality(self):
        for k in (0.05, BACKEND_K, LEAGUE_K, ELITE_K, 0.60):
            with self.subTest(k_rate=k):
                self.assertEqual(_starter_tto_quality_mult(_Pitcher(k), {}), 1.0)
                self.assertEqual(_starter_tto_quality_mult(_Pitcher(k), {"starter_tto_quality_scaling": 0.0}), 1.0)

    def test_missing_overrides_dict_is_a_no_op(self):
        self.assertEqual(_starter_tto_quality_mult(_Pitcher(ELITE_K), None), 1.0)

    def test_missing_k_rate_attribute_falls_back_to_league_average(self):
        class NoRate:
            pass

        self.assertAlmostEqual(
            _starter_tto_quality_mult(NoRate(), {"starter_tto_quality_scaling": 0.8}),
            1.0,
            places=6,
        )


class QualityScalingTests(unittest.TestCase):
    def test_league_average_pitcher_is_unaffected_by_scaling(self):
        for scaling in (0.25, 0.5, 1.0):
            with self.subTest(scaling=scaling):
                mult = _starter_tto_quality_mult(_Pitcher(LEAGUE_K), {"starter_tto_quality_scaling": scaling})
                self.assertAlmostEqual(mult, 1.0, places=6)

    def test_elite_pitcher_gets_a_softer_penalty(self):
        mult = _starter_tto_quality_mult(_Pitcher(ELITE_K), {"starter_tto_quality_scaling": 0.5})
        self.assertLess(mult, 1.0)

    def test_backend_pitcher_gets_a_steeper_penalty(self):
        mult = _starter_tto_quality_mult(_Pitcher(BACKEND_K), {"starter_tto_quality_scaling": 0.5})
        self.assertGreater(mult, 1.0)

    def test_scaling_is_monotonic_in_magnitude(self):
        prior_elite = None
        prior_backend = None
        for scaling in (0.0, 0.25, 0.5, 0.75, 1.0):
            elite_mult = _starter_tto_quality_mult(_Pitcher(ELITE_K), {"starter_tto_quality_scaling": scaling})
            backend_mult = _starter_tto_quality_mult(_Pitcher(BACKEND_K), {"starter_tto_quality_scaling": scaling})
            if prior_elite is not None:
                self.assertLessEqual(elite_mult, prior_elite + 1e-9)
            if prior_backend is not None:
                self.assertGreaterEqual(backend_mult, prior_backend - 1e-9)
            prior_elite, prior_backend = elite_mult, backend_mult

    def test_result_is_clamped(self):
        # Absurdly extreme scaling/spread shouldn't blow the multiplier up
        # past the documented [0.3, 1.6] band.
        mult_hi = _starter_tto_quality_mult(
            _Pitcher(0.60), {"starter_tto_quality_scaling": 1.0, "starter_tto_quality_spread": 0.01}
        )
        mult_lo = _starter_tto_quality_mult(
            _Pitcher(0.05), {"starter_tto_quality_scaling": 1.0, "starter_tto_quality_spread": 0.01}
        )
        self.assertGreaterEqual(mult_hi, 0.3)
        self.assertLessEqual(mult_lo, 1.6)

    def test_custom_league_rate_and_spread_are_respected(self):
        default_mult = _starter_tto_quality_mult(_Pitcher(ELITE_K), {"starter_tto_quality_scaling": 0.5})
        custom_mult = _starter_tto_quality_mult(
            _Pitcher(ELITE_K),
            {"starter_tto_quality_scaling": 0.5, "starter_tto_quality_league_k": 0.30, "starter_tto_quality_spread": 0.10},
        )
        self.assertNotAlmostEqual(default_mult, custom_mult, places=6)


if __name__ == "__main__":
    unittest.main()
