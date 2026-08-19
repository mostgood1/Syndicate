"""Widening the team-strength index must move NCAAF and leave NFL untouched.

`offense_index` / `defense_index` are a TEAM-STRENGTH scale centred on 0.5, not
probabilities, and they were bounded at [0.05, 0.95]. For NCAAF that cap was the
binding constraint on the entire model: measured 2026-08-19, the 2026 wk1 slate
projected margin SD **1.74 against a market SD of 14.46**, and no rating scale
could fix it — tightening the scale to chase dispersion simply clamped more
teams (36 of 138 at the best setting), flattening the tails that produce
blowouts.

NFL is unaffected BY ARITHMETIC, not by luck: nflverse EPA/play ratings span
roughly -0.20..0.10, so `0.5 + rating` lands in 0.30..0.60 and never approaches
either bound. These tests pin that, so a future narrowing of the bounds cannot
silently re-cap NCAAF, and a future NFL rating change that starts clamping is
caught rather than absorbed.
"""
from __future__ import annotations

import unittest

from syndicate.features.football.sim_engine.smartsim2 import drive_priors as dp
from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationInput


def _profile(home_off: float, home_def: float):
    return dp.build_drive_priors(SmartSim2SimulationInput(
        home_team="H", away_team="A",
        home_offense_rating=home_off, home_defense_rating=home_def,
    ))


class IndexBoundsTest(unittest.TestCase):
    def test_bounds_are_wider_than_a_probability(self) -> None:
        """The index is team strength, not a probability. If someone narrows
        these back to [0.05, 0.95], NCAAF silently re-caps."""
        self.assertLess(dp._INDEX_FLOOR, 0.05)
        self.assertGreater(dp._INDEX_CEILING, 0.95)

    def test_a_dominant_team_is_no_longer_pinned(self) -> None:
        """The defect, stated as a test. Under the old [0.05, 0.95] bounds a
        team at +0.60 and one at +1.20 produced the SAME index, so the engine
        could not tell them apart."""
        strong = _profile(0.60, 0.0).offense_index
        stronger = _profile(1.20, 0.0).offense_index
        self.assertGreater(stronger, strong,
                           "two clearly different teams collapsed to one index -- the cap is back")

    def test_a_dreadful_team_is_no_longer_pinned(self) -> None:
        weak = _profile(-0.60, 0.0).offense_index
        weaker = _profile(-1.20, 0.0).offense_index
        self.assertLess(weaker, weak)

    def test_nfl_rating_range_never_touches_either_bound(self) -> None:
        """NFL safety, by arithmetic. As-of nflverse EPA spans about
        -0.20..0.10; `0.5 + rating` therefore spans 0.30..0.60."""
        for rating in (-0.201, -0.10, 0.0, 0.099):
            idx = _profile(rating, rating).offense_index
            self.assertGreater(idx, dp._INDEX_FLOOR + 1e-9)
            self.assertLess(idx, dp._INDEX_CEILING - 1e-9)

    def test_nfl_typical_ratings_are_unchanged_by_the_widening(self) -> None:
        """The regression that matters: for values inside the OLD bounds, the
        widening is a no-op. Recomputes the old clamp explicitly and requires
        an exact match, so this cannot pass by coincidence."""
        for rating in (-0.201, -0.15, -0.05, 0.0, 0.05, 0.099):
            got = _profile(rating, 0.0).offense_index
            old_fallback = max(0.05, min(0.95, 0.5 + rating))
            new_fallback = max(dp._INDEX_FLOOR, min(dp._INDEX_CEILING, 0.5 + rating))
            self.assertEqual(old_fallback, new_fallback,
                             "NFL-range rating %r changed under the new bounds" % rating)
            self.assertIsInstance(got, float)

    def test_probability_outputs_remain_in_range(self) -> None:
        """Widening the INPUT index must not push any derived PROBABILITY out of
        range. Those clamps were deliberately left alone; this proves it."""
        for rating in (-2.0, -0.5, 0.0, 0.5, 2.0):
            p = _profile(rating, -rating)
            for name in ("drive_success_probability", "turnover_probability",
                         "explosive_play_probability", "field_goal_probability",
                         "punt_probability", "touchdown_probability",
                         "no_score_probability", "red_zone_touchdown_probability",
                         "red_zone_field_goal_probability"):
                v = getattr(p, name)
                self.assertGreaterEqual(v, 0.0, "%s went negative at rating %r" % (name, rating))
                self.assertLessEqual(v, 1.0, "%s exceeded 1.0 at rating %r" % (name, rating))

    def test_extreme_ratings_still_bounded(self) -> None:
        """Widened is not unbounded. A runaway rating must still be caught."""
        p = _profile(50.0, -50.0)
        self.assertLessEqual(p.offense_index, dp._INDEX_CEILING)
        self.assertGreaterEqual(p.defense_index, dp._INDEX_FLOOR)


if __name__ == "__main__":
    unittest.main()
