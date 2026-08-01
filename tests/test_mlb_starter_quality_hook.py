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
default 0.0 = unchanged behavior) so elite (high-K) starters get a longer
leash and below-average starters get a shorter one, independent of their
workload history.
"""

from __future__ import annotations

import unittest

from vendor.mlb_bettingv2.sim_engine.simulate import _starter_quality_hook_delta

LEAGUE_K = 0.223
ELITE_K = 0.35
BACKEND_K = 0.15


class _Pitcher:
    def __init__(self, k_rate: float):
        self.k_rate = k_rate


class DefaultBehaviorTests(unittest.TestCase):
    def test_default_weight_is_a_no_op_regardless_of_quality(self):
        for k in (0.05, BACKEND_K, LEAGUE_K, ELITE_K, 0.60):
            with self.subTest(k_rate=k):
                self.assertEqual(_starter_quality_hook_delta(_Pitcher(k), {}), 0)
                self.assertEqual(_starter_quality_hook_delta(_Pitcher(k), {"starter_quality_hook_weight": 0.0}), 0)

    def test_missing_overrides_dict_is_a_no_op(self):
        self.assertEqual(_starter_quality_hook_delta(_Pitcher(ELITE_K), None), 0)

    def test_missing_k_rate_attribute_falls_back_to_league_average(self):
        class NoRate:
            pass

        self.assertEqual(
            _starter_quality_hook_delta(NoRate(), {"starter_quality_hook_weight": 0.8}),
            0,
        )


class QualityHookDeltaTests(unittest.TestCase):
    def test_league_average_pitcher_gets_no_adjustment(self):
        for weight in (0.25, 0.5, 1.0):
            with self.subTest(weight=weight):
                delta = _starter_quality_hook_delta(_Pitcher(LEAGUE_K), {"starter_quality_hook_weight": weight})
                self.assertEqual(delta, 0)

    def test_elite_pitcher_gets_a_longer_leash(self):
        delta = _starter_quality_hook_delta(_Pitcher(ELITE_K), {"starter_quality_hook_weight": 0.5})
        self.assertGreater(delta, 0)

    def test_backend_pitcher_gets_a_shorter_leash(self):
        delta = _starter_quality_hook_delta(_Pitcher(BACKEND_K), {"starter_quality_hook_weight": 0.5})
        self.assertLess(delta, 0)

    def test_delta_is_monotonic_in_weight(self):
        prior_elite = None
        prior_backend = None
        for weight in (0.0, 0.25, 0.5, 0.75, 1.0):
            elite_delta = _starter_quality_hook_delta(_Pitcher(ELITE_K), {"starter_quality_hook_weight": weight})
            backend_delta = _starter_quality_hook_delta(_Pitcher(BACKEND_K), {"starter_quality_hook_weight": weight})
            if prior_elite is not None:
                self.assertGreaterEqual(elite_delta, prior_elite - 1e-9)
            if prior_backend is not None:
                self.assertLessEqual(backend_delta, prior_backend + 1e-9)
            prior_elite, prior_backend = elite_delta, backend_delta

    def test_result_is_bounded_by_max_pitches(self):
        # Absurdly extreme weight/spread shouldn't blow the delta up past
        # the configured max_pitches ceiling.
        delta_hi = _starter_quality_hook_delta(
            _Pitcher(0.60),
            {"starter_quality_hook_weight": 1.0, "starter_quality_hook_spread": 0.01, "starter_quality_hook_max_pitches": 15.0},
        )
        delta_lo = _starter_quality_hook_delta(
            _Pitcher(0.05),
            {"starter_quality_hook_weight": 1.0, "starter_quality_hook_spread": 0.01, "starter_quality_hook_max_pitches": 15.0},
        )
        self.assertLessEqual(delta_hi, 15)
        self.assertGreaterEqual(delta_lo, -15)

    def test_custom_max_pitches_scales_the_result(self):
        small = _starter_quality_hook_delta(
            _Pitcher(ELITE_K), {"starter_quality_hook_weight": 1.0, "starter_quality_hook_max_pitches": 5.0}
        )
        large = _starter_quality_hook_delta(
            _Pitcher(ELITE_K), {"starter_quality_hook_weight": 1.0, "starter_quality_hook_max_pitches": 20.0}
        )
        self.assertGreater(large, small)

    def test_custom_league_rate_and_spread_are_respected(self):
        default_delta = _starter_quality_hook_delta(_Pitcher(ELITE_K), {"starter_quality_hook_weight": 0.5})
        custom_delta = _starter_quality_hook_delta(
            _Pitcher(ELITE_K),
            {"starter_quality_hook_weight": 0.5, "starter_quality_hook_league_k": 0.30, "starter_quality_hook_spread": 0.10},
        )
        self.assertNotEqual(default_delta, custom_delta)


if __name__ == "__main__":
    unittest.main()
