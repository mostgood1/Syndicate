"""Starter stamina_pitches shrink-to-prior (`_derive_stamina_pitches_from_season_stats`)
in the vendored MLB sim engine.

Covers the fix for todo.md #178: pitches-per-start is estimated by shrinking
a starter's own season-to-date observed rate toward a flat sp_prior=92
baseline with a fixed n0=10.0 "prior pseudo-starts" weight. Even well into a
season (gs ~15-20), that still pulls ~35-40% of the estimate toward the flat
prior for every starter regardless of true workload -- confirmed via real
roster snapshots where a workhorse and a short-outing arm derived to nearly
the same stamina_pitches value. That compression caps how deep an ace can be
projected to pitch (and how short a back-end arm gets pulled), which caps
every counting stat downstream of batters-faced.

`starter_shrink_n0` makes that weight configurable; these tests lock in that
the default (10.0) reproduces the exact prior behavior (no regression for
anyone not opting in) and that a lower n0 moves estimates toward the raw
observed rate in the correct direction for both ends of the workload
spectrum, while respecting the existing [70, 115] output clamp.
"""

from __future__ import annotations

import unittest

from vendor.mlb_bettingv2.sim_engine.data.build_roster import (
    _derive_stamina_pitches_from_season_stats,
    _shrink_to_prior,
)

SP_PRIOR = 92.0


def _starter_pstat(pitches_thrown: float, games_started: float, games_pitched: float = None) -> dict:
    return {
        "pitchesThrown": pitches_thrown,
        "gamesStarted": games_started,
        "gamesPitched": games_pitched if games_pitched is not None else games_started,
    }


class DefaultBehaviorTests(unittest.TestCase):
    """starter_shrink_n0=10.0 (the default) must reproduce the pre-fix formula exactly."""

    def test_default_n0_matches_prior_hardcoded_formula(self):
        for pitches, gs in [(1800.0, 18.0), (1350.0, 15.0), (2000.0, 20.0)]:
            with self.subTest(pitches=pitches, gs=gs):
                pstat = _starter_pstat(pitches, gs)
                expected = int(max(70, min(115, round(_shrink_to_prior(pitches / gs, SP_PRIOR, n=gs, n0=10.0)))))
                self.assertEqual(_derive_stamina_pitches_from_season_stats(pstat), expected)
                self.assertEqual(
                    _derive_stamina_pitches_from_season_stats(pstat, starter_shrink_n0=10.0),
                    expected,
                )

    def test_sparse_sample_ignores_n0_entirely(self):
        # No workload data at all, forced onto the starter path (e.g. a
        # confirmed probable pitcher with no starts logged yet this season)
        # -> flat sp_prior regardless of shrink strength, since there's no
        # observed rate to shrink toward it.
        pstat = {}
        for n0 in (0.0, 3.0, 10.0, 50.0):
            with self.subTest(n0=n0):
                self.assertEqual(
                    _derive_stamina_pitches_from_season_stats(pstat, force_starter=True, starter_shrink_n0=n0),
                    int(SP_PRIOR),
                )


class ShrinkStrengthTests(unittest.TestCase):
    def test_lower_n0_pulls_workhorse_estimate_up_toward_observed(self):
        # A real workhorse ace averaging well above the 92-pitch prior should
        # see the shrunk estimate rise (move closer to the true rate) as n0
        # drops -- this is the "elite pitchers get compressed down" half of
        # the bug.
        pstat = _starter_pstat(pitches_thrown=1980.0, games_started=18.0)  # 110 raw pitches/start
        prior_value = None
        for n0 in (10.0, 6.0, 3.0, 0.0):
            derived = _derive_stamina_pitches_from_season_stats(pstat, starter_shrink_n0=n0)
            if prior_value is not None:
                self.assertGreaterEqual(derived, prior_value)
            prior_value = derived
        # At n0=0 (no shrinkage), the estimate should recover close to the
        # raw observed 110 (clamped at 115).
        self.assertEqual(_derive_stamina_pitches_from_season_stats(pstat, starter_shrink_n0=0.0), 110)

    def test_lower_n0_pulls_short_outing_estimate_down_toward_observed(self):
        # Symmetric check: a real short-outing arm averaging well below the
        # 92-pitch prior should see the shrunk estimate fall as n0 drops --
        # the "back-end pitchers get inflated up" half of the bug.
        pstat = _starter_pstat(pitches_thrown=1440.0, games_started=18.0)  # 80 raw pitches/start
        prior_value = None
        for n0 in (10.0, 6.0, 3.0, 0.0):
            derived = _derive_stamina_pitches_from_season_stats(pstat, starter_shrink_n0=n0)
            if prior_value is not None:
                self.assertLessEqual(derived, prior_value)
            prior_value = derived
        self.assertEqual(_derive_stamina_pitches_from_season_stats(pstat, starter_shrink_n0=0.0), 80)

    def test_low_n0_widens_the_spread_between_workhorse_and_short_outing_arms(self):
        # The actual bug: at the default n0=10, two real starters with very
        # different true workloads can derive to nearly the same
        # stamina_pitches. A lower n0 must widen that spread.
        workhorse = _starter_pstat(pitches_thrown=1980.0, games_started=18.0)  # 110/start
        short_arm = _starter_pstat(pitches_thrown=1440.0, games_started=18.0)  # 80/start

        spread_default = _derive_stamina_pitches_from_season_stats(
            workhorse, starter_shrink_n0=10.0
        ) - _derive_stamina_pitches_from_season_stats(short_arm, starter_shrink_n0=10.0)
        spread_lower = _derive_stamina_pitches_from_season_stats(
            workhorse, starter_shrink_n0=3.0
        ) - _derive_stamina_pitches_from_season_stats(short_arm, starter_shrink_n0=3.0)

        self.assertGreater(spread_lower, spread_default)

    def test_output_always_respects_existing_clamp(self):
        extreme_high = _starter_pstat(pitches_thrown=3000.0, games_started=15.0)  # 200/start
        extreme_low = _starter_pstat(pitches_thrown=300.0, games_started=15.0)  # 20/start
        for n0 in (0.0, 3.0, 10.0):
            with self.subTest(n0=n0):
                self.assertLessEqual(_derive_stamina_pitches_from_season_stats(extreme_high, starter_shrink_n0=n0), 115)
                self.assertGreaterEqual(_derive_stamina_pitches_from_season_stats(extreme_low, starter_shrink_n0=n0), 70)

    def test_force_starter_path_also_respects_n0(self):
        # force_starter=True (used for the day's confirmed probable pitcher
        # without a pure-starter sample yet) takes a different branch but
        # must still thread the shrink strength through when it does have an
        # observed rate to shrink.
        pstat = _starter_pstat(pitches_thrown=1980.0, games_started=18.0)
        low_n0 = _derive_stamina_pitches_from_season_stats(pstat, force_starter=True, starter_shrink_n0=0.0)
        default_n0 = _derive_stamina_pitches_from_season_stats(pstat, force_starter=True, starter_shrink_n0=10.0)
        self.assertGreaterEqual(low_n0, default_n0)


if __name__ == "__main__":
    unittest.main()
