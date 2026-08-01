"""Pitcher K-rate combination (`_combined_k`) in the vendored MLB sim engine.

Covers the fix for todo.md #176: `_combined()` blends pitcher/batter K rate
with a flat 50/50 average, which pulls an elite pitcher's true strikeout
talent halfway toward the batter's (roughly league-average) rate on every
plate appearance -- structurally underprojecting aces' strikeout props (and,
symmetrically, overprojecting back-end starters'). `_combined_k` adds an
opt-in shrinkage-weighted log5 blend (`k_combine_log5_weight`); these tests
lock in that the default reproduces the old behavior exactly (no regression
for anyone not opting in) and that a nonzero weight moves projections in the
correct direction without violating basic probability bounds.
"""

from __future__ import annotations

import random
import unittest

from vendor.mlb_bettingv2.sim_engine.pitch_model import (
    PitchModelConfig,
    PitchType,
    _combined,
    _combined_k,
    _combined_log5,
    clamp01,
    simulate_pitch,
)

LEAGUE_K = 0.223
AVERAGE_BATTER_K = 0.223
ELITE_PITCHER_K = 0.35
BACKEND_PITCHER_K = 0.15


def _pitch_kwargs(pitcher_k_rate: float, batter_k_rate: float = AVERAGE_BATTER_K) -> dict:
    return dict(
        pitch_type=PitchType.FF,
        pitcher_whiff_mult=1.0,
        pitcher_inplay_mult=1.0,
        weather_hr_mult=1.0,
        weather_inplay_hit_mult=1.0,
        weather_xb_share_mult=1.0,
        park_hr_mult=1.0,
        park_inplay_hit_mult=1.0,
        park_xb_share_mult=1.0,
        umpire_called_strike_mult=1.0,
        count=(1, 2),
        batter_k_rate=batter_k_rate,
        batter_bb_rate=0.08,
        batter_hbp_rate=0.005,
        batter_hr_rate=0.03,
        batter_inplay_hit_rate=0.275,
        batter_xb_hit_share=0.33,
        batter_pt_mult=1.0,
        batter_pt_hr_mult=1.0,
        batter_triple_share_of_xb=0.12,
        pitcher_k_rate=pitcher_k_rate,
        pitcher_bb_rate=0.08,
        pitcher_hbp_rate=0.005,
        pitcher_hr_rate=0.03,
        pitcher_inplay_hit_rate=0.275,
    )


class CombinedKDefaultBehaviorTests(unittest.TestCase):
    """weight=0.0 (the default) must reproduce the pre-fix flat average exactly."""

    def test_default_weight_matches_flat_average(self):
        cfg = PitchModelConfig()
        for pitcher_k, batter_k in [
            (ELITE_PITCHER_K, AVERAGE_BATTER_K),
            (BACKEND_PITCHER_K, AVERAGE_BATTER_K),
            (0.223, 0.223),
            (0.05, 0.60),
        ]:
            with self.subTest(pitcher_k=pitcher_k, batter_k=batter_k):
                flat = clamp01(0.5 * batter_k + 0.5 * pitcher_k)
                self.assertAlmostEqual(_combined_k(batter_k, pitcher_k, cfg), flat, places=9)
                # Also matches the untouched `_combined()` helper other rates
                # (bb/hbp) still use directly, confirming no drift between them.
                self.assertAlmostEqual(_combined_k(batter_k, pitcher_k, cfg), _combined(batter_k, pitcher_k), places=9)

    def test_missing_field_falls_back_to_zero_weight(self):
        # A config that doesn't define the new fields at all (e.g. a stale
        # override JSON from before this change) must behave exactly as before.
        class LegacyCfg:
            pass

        legacy = LegacyCfg()
        flat = clamp01(0.5 * AVERAGE_BATTER_K + 0.5 * ELITE_PITCHER_K)
        self.assertAlmostEqual(_combined_k(AVERAGE_BATTER_K, ELITE_PITCHER_K, legacy), flat, places=9)


class CombinedKBlendTests(unittest.TestCase):
    def test_full_weight_matches_pure_log5(self):
        cfg = PitchModelConfig(k_combine_log5_weight=1.0)
        for pitcher_k, batter_k in [(ELITE_PITCHER_K, AVERAGE_BATTER_K), (BACKEND_PITCHER_K, 0.30)]:
            with self.subTest(pitcher_k=pitcher_k, batter_k=batter_k):
                expected = _combined_log5(batter_k, pitcher_k, LEAGUE_K)
                self.assertAlmostEqual(_combined_k(batter_k, pitcher_k, cfg), expected, places=9)

    def test_league_average_matchup_is_weight_invariant(self):
        # When both sides sit exactly at the league rate, flat average and
        # log5 agree (both equal the league rate) -- the blend weight must
        # not matter in this case. Good sanity check that the two formulas
        # are anchored consistently.
        for weight in (0.0, 0.25, 0.5, 0.75, 1.0):
            cfg = PitchModelConfig(k_combine_log5_weight=weight)
            self.assertAlmostEqual(_combined_k(LEAGUE_K, LEAGUE_K, cfg), LEAGUE_K, places=6)

    def test_elite_pitcher_moves_toward_true_rate_as_weight_increases(self):
        # This is the actual bug fix: an elite pitcher's projected per-PA K
        # rate should climb monotonically toward his true (higher) rate as
        # more log5 character is blended in, instead of staying anchored
        # near the flat average of his rate and a league-average batter.
        prior = None
        for weight in (0.0, 0.25, 0.5, 0.75, 1.0):
            cfg = PitchModelConfig(k_combine_log5_weight=weight)
            combined = _combined_k(AVERAGE_BATTER_K, ELITE_PITCHER_K, cfg)
            if prior is not None:
                self.assertGreaterEqual(combined, prior - 1e-9)
            prior = combined
        # At weight=1.0 the combined rate should recover ~all the way to the
        # pitcher's own true rate (batter is exactly at league average).
        cfg_full = PitchModelConfig(k_combine_log5_weight=1.0)
        self.assertAlmostEqual(_combined_k(AVERAGE_BATTER_K, ELITE_PITCHER_K, cfg_full), ELITE_PITCHER_K, places=6)
        # At weight=0.0 it must still be the old, compressed flat average --
        # i.e. well below the pitcher's true rate. This is the regression
        # the fix targets.
        cfg_off = PitchModelConfig(k_combine_log5_weight=0.0)
        flat = _combined_k(AVERAGE_BATTER_K, ELITE_PITCHER_K, cfg_off)
        self.assertLess(flat, ELITE_PITCHER_K - 0.05)

    def test_backend_pitcher_moves_toward_true_rate_as_weight_increases(self):
        # Symmetric check: a below-average starter's inflated (over-)
        # projection should shrink toward his true (lower) rate too.
        prior = None
        for weight in (0.0, 0.25, 0.5, 0.75, 1.0):
            cfg = PitchModelConfig(k_combine_log5_weight=weight)
            combined = _combined_k(AVERAGE_BATTER_K, BACKEND_PITCHER_K, cfg)
            if prior is not None:
                self.assertLessEqual(combined, prior + 1e-9)
            prior = combined
        cfg_off = PitchModelConfig(k_combine_log5_weight=0.0)
        flat = _combined_k(AVERAGE_BATTER_K, BACKEND_PITCHER_K, cfg_off)
        self.assertGreater(flat, BACKEND_PITCHER_K + 0.02)

    def test_custom_league_rate_is_respected(self):
        cfg_default = PitchModelConfig(k_combine_log5_weight=1.0)
        cfg_custom = PitchModelConfig(k_combine_log5_weight=1.0, k_league_rate=0.26)
        combined_default = _combined_k(AVERAGE_BATTER_K, ELITE_PITCHER_K, cfg_default)
        combined_custom = _combined_k(AVERAGE_BATTER_K, ELITE_PITCHER_K, cfg_custom)
        self.assertNotAlmostEqual(combined_default, combined_custom, places=6)

    def test_weight_is_clamped_to_unit_interval(self):
        cfg_over = PitchModelConfig(k_combine_log5_weight=2.5)
        cfg_full = PitchModelConfig(k_combine_log5_weight=1.0)
        self.assertAlmostEqual(
            _combined_k(AVERAGE_BATTER_K, ELITE_PITCHER_K, cfg_over),
            _combined_k(AVERAGE_BATTER_K, ELITE_PITCHER_K, cfg_full),
            places=9,
        )

    def test_result_always_in_unit_interval(self):
        cfg = PitchModelConfig(k_combine_log5_weight=1.0)
        for pitcher_k in (0.05, 0.15, 0.223, 0.35, 0.60):
            for batter_k in (0.05, 0.15, 0.223, 0.35, 0.60):
                combined = _combined_k(batter_k, pitcher_k, cfg)
                self.assertGreaterEqual(combined, 0.0)
                self.assertLessEqual(combined, 1.0)


class SimulatePitchIntegrationTests(unittest.TestCase):
    """End-to-end sanity check: the blend weight should shift actual whiff
    rates produced by `simulate_pitch`, not just the internal `k_tgt` value.
    """

    def _swinging_strike_rate(self, cfg: PitchModelConfig, pitcher_k: float, n: int = 20000) -> float:
        rng = random.Random(1234)
        whiffs = 0
        kwargs = _pitch_kwargs(pitcher_k)
        for _ in range(n):
            result = simulate_pitch(rng=rng, cfg=cfg, **kwargs)
            if result.call.name == "SWINGING_STRIKE":
                whiffs += 1
        return whiffs / float(n)

    def test_elite_pitcher_whiff_rate_rises_with_log5_weight(self):
        rate_off = self._swinging_strike_rate(PitchModelConfig(k_combine_log5_weight=0.0), ELITE_PITCHER_K)
        rate_on = self._swinging_strike_rate(PitchModelConfig(k_combine_log5_weight=1.0), ELITE_PITCHER_K)
        self.assertGreater(rate_on, rate_off)

    def test_backend_pitcher_whiff_rate_falls_with_log5_weight(self):
        rate_off = self._swinging_strike_rate(PitchModelConfig(k_combine_log5_weight=0.0), BACKEND_PITCHER_K)
        rate_on = self._swinging_strike_rate(PitchModelConfig(k_combine_log5_weight=1.0), BACKEND_PITCHER_K)
        self.assertLess(rate_on, rate_off)


if __name__ == "__main__":
    unittest.main()
