"""In-play-hit-rate combination (`_combined_inplay_hit`) in the vendored
MLB sim engine.

Covers the investigation in todo.md part 9/10: `inplay_hit` was moved
from a flat 50/50 average to log5 (odds-ratio) combination on
2026-07-19, specifically to fix HR/extra-base-hit under-projection. That
promotion's backtest validated HR rate and total_bases_4plus/5plus, not
the *overall* hit-rate level. Diagnosed 2026-08-01: team-level total
hits are over-projected by +1.41/game (16.8% relative, n=1224
team-games, 46-date backtest) -- present even in team totals across all
pitchers, ruling out the outs/workload mechanism fixed in parts 3-7 as
the (sole) cause. `_combined_inplay_hit` adds a shrinkage-weighted blend
back toward the flat average (`inplay_hit_combine_log5_weight`), for
backtesting whether reverting some/all of the log5 promotion closes the
hits-allowed gap without reopening the HR/total-bases gap it was
promoted to fix.

Default is 1.0 (full log5), reproducing the current *promoted* behavior
exactly -- this is a diagnostic knob, not itself a behavior change.
"""

from __future__ import annotations

import unittest

from vendor.mlb_bettingv2.sim_engine.pitch_model import (
    PitchModelConfig,
    _combined,
    _combined_inplay_hit,
    _combined_log5,
    clamp01,
)

LEAGUE_INPLAY_HIT = 0.275
HIGH_BABIP_AGAINST = 0.35
LOW_BABIP_AGAINST = 0.20


class DefaultBehaviorTests(unittest.TestCase):
    """weight=1.0 (the default) must reproduce the current promoted
    (full log5) behavior exactly -- this knob must not change anything
    for callers that don't opt into a different weight."""

    def test_default_weight_matches_full_log5(self):
        cfg = PitchModelConfig()
        for batter_rate, pitcher_rate in [
            (HIGH_BABIP_AGAINST, LOW_BABIP_AGAINST),
            (LOW_BABIP_AGAINST, HIGH_BABIP_AGAINST),
            (LEAGUE_INPLAY_HIT, LEAGUE_INPLAY_HIT),
            (0.15, 0.45),
        ]:
            with self.subTest(batter_rate=batter_rate, pitcher_rate=pitcher_rate):
                expected = _combined_log5(batter_rate, pitcher_rate, LEAGUE_INPLAY_HIT)
                self.assertAlmostEqual(_combined_inplay_hit(batter_rate, pitcher_rate, cfg), expected, places=9)
                # Also matches the untouched `_combined()` path other
                # league_key-driven rates (hr) still use directly.
                self.assertAlmostEqual(
                    _combined_inplay_hit(batter_rate, pitcher_rate, cfg),
                    _combined(batter_rate, pitcher_rate, "inplay_hit"),
                    places=9,
                )

    def test_missing_field_falls_back_to_full_log5(self):
        # A config that doesn't define the new fields at all (e.g. a
        # stale override JSON from before this change) must behave
        # exactly as the already-promoted default (full log5), not
        # silently revert to flat average.
        class LegacyCfg:
            pass

        legacy = LegacyCfg()
        expected = _combined_log5(HIGH_BABIP_AGAINST, LOW_BABIP_AGAINST, LEAGUE_INPLAY_HIT)
        self.assertAlmostEqual(_combined_inplay_hit(HIGH_BABIP_AGAINST, LOW_BABIP_AGAINST, legacy), expected, places=9)


class BlendTests(unittest.TestCase):
    def test_zero_weight_matches_flat_average(self):
        cfg = PitchModelConfig(inplay_hit_combine_log5_weight=0.0)
        for batter_rate, pitcher_rate in [(HIGH_BABIP_AGAINST, LOW_BABIP_AGAINST), (0.15, 0.45)]:
            with self.subTest(batter_rate=batter_rate, pitcher_rate=pitcher_rate):
                flat = clamp01(0.5 * batter_rate + 0.5 * pitcher_rate)
                self.assertAlmostEqual(_combined_inplay_hit(batter_rate, pitcher_rate, cfg), flat, places=9)

    def test_league_average_matchup_is_weight_invariant(self):
        for weight in (0.0, 0.25, 0.5, 0.75, 1.0):
            cfg = PitchModelConfig(inplay_hit_combine_log5_weight=weight)
            self.assertAlmostEqual(
                _combined_inplay_hit(LEAGUE_INPLAY_HIT, LEAGUE_INPLAY_HIT, cfg), LEAGUE_INPLAY_HIT, places=6
            )

    def test_weight_is_clamped_to_unit_interval(self):
        cfg_over = PitchModelConfig(inplay_hit_combine_log5_weight=2.5)
        cfg_full = PitchModelConfig(inplay_hit_combine_log5_weight=1.0)
        self.assertAlmostEqual(
            _combined_inplay_hit(HIGH_BABIP_AGAINST, LOW_BABIP_AGAINST, cfg_over),
            _combined_inplay_hit(HIGH_BABIP_AGAINST, LOW_BABIP_AGAINST, cfg_full),
            places=9,
        )
        cfg_under = PitchModelConfig(inplay_hit_combine_log5_weight=-1.0)
        cfg_zero = PitchModelConfig(inplay_hit_combine_log5_weight=0.0)
        self.assertAlmostEqual(
            _combined_inplay_hit(HIGH_BABIP_AGAINST, LOW_BABIP_AGAINST, cfg_under),
            _combined_inplay_hit(HIGH_BABIP_AGAINST, LOW_BABIP_AGAINST, cfg_zero),
            places=9,
        )

    def test_result_always_in_unit_interval(self):
        for weight in (0.0, 0.5, 1.0):
            cfg = PitchModelConfig(inplay_hit_combine_log5_weight=weight)
            for batter_rate in (0.05, 0.15, 0.275, 0.40, 0.60):
                for pitcher_rate in (0.05, 0.15, 0.275, 0.40, 0.60):
                    combined = _combined_inplay_hit(batter_rate, pitcher_rate, cfg)
                    self.assertGreaterEqual(combined, 0.0)
                    self.assertLessEqual(combined, 1.0)

    def test_intermediate_weight_lies_between_flat_and_log5(self):
        cfg = PitchModelConfig(inplay_hit_combine_log5_weight=0.5)
        flat = clamp01(0.5 * HIGH_BABIP_AGAINST + 0.5 * LOW_BABIP_AGAINST)
        log5 = _combined_log5(HIGH_BABIP_AGAINST, LOW_BABIP_AGAINST, LEAGUE_INPLAY_HIT)
        combined = _combined_inplay_hit(HIGH_BABIP_AGAINST, LOW_BABIP_AGAINST, cfg)
        lo, hi = min(flat, log5), max(flat, log5)
        self.assertGreaterEqual(combined, lo - 1e-9)
        self.assertLessEqual(combined, hi + 1e-9)

    def test_custom_league_rate_is_respected(self):
        cfg_default = PitchModelConfig(inplay_hit_combine_log5_weight=1.0)
        cfg_custom = PitchModelConfig(inplay_hit_combine_log5_weight=1.0, inplay_hit_league_rate=0.30)
        combined_default = _combined_inplay_hit(HIGH_BABIP_AGAINST, LOW_BABIP_AGAINST, cfg_default)
        combined_custom = _combined_inplay_hit(HIGH_BABIP_AGAINST, LOW_BABIP_AGAINST, cfg_custom)
        self.assertNotAlmostEqual(combined_default, combined_custom, places=6)


if __name__ == "__main__":
    unittest.main()
