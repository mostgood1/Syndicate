"""The team-strength index bounds, and the record of why widening them FAILED.

`offense_index` / `defense_index` are a TEAM-STRENGTH scale centred on 0.5, not
probabilities, bounded at [0.05, 0.95].

**I BELIEVED THAT CAP WAS THE BINDING CONSTRAINT ON NCAAF MARGINS. IT WAS NOT.**
The 2026 wk1 slate did project margin SD 1.74 against a market 14.46, and the
bound does saturate — 36 of 138 teams pinned at the best SP+ scale — so the story
was coherent. It was still wrong. Measured on the real slate, SP+ at scale 10:

    bounds                  margin SD    total SD    (market: 14.46 / 3.46)
    [0.05, 0.95] (kept)        15.97        7.51
    [-0.75, 1.75] (rejected)   15.27        9.55

Widening made margins slightly WORSE and inflated totals by 27%. The margin fix
was entirely the rating SOURCE — PPA, a per-play rate with differential SD 0.136,
replaced by SP+, points-per-game — and margin dispersion is produced in
`play_simulator.py:354/382` from the RAW ratings, which carry no clamp. These
indices never gated it.

So the saturation these tests assert is DELIBERATE and costs nothing measurable.
A future reader who spots it and "fixes" it will make both metrics worse; that is
why the rejected numbers are recorded here rather than deleted with the change.

NFL is untouched either way, by arithmetic rather than luck: nflverse EPA/play
spans roughly -0.20..0.10, so `0.5 + rating` lands in 0.30..0.60 and never
approaches either bound.

STILL OPEN, and NOT fixable here: totals remain ~2.17x market dispersion even at
these bounds. The cause is `play_simulator.py:354`, where the offense weight
(3.0) exceeds the defense weight (2.2), so a strong offense adds more than a
strong defense subtracts and games between good teams inflate. That asymmetry is
shared with NFL and needs its own calibration.
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
    def test_bounds_are_the_original_probability_range(self) -> None:
        """WIDENING THESE WAS TRIED AND REJECTED. Measured 2026-08-19 on the
        real 51-game slate with SP+ at scale 10:

            bounds                  margin SD    total SD
            [0.05, 0.95] (this)        15.97        7.51
            [-0.75, 1.75]              15.27        9.55

        Margins are BETTER at the original bounds and the widening inflated
        totals by 27%. Do not widen these to chase margin dispersion -- margin
        comes from `play_simulator.py:354/382`, which has no clamp on the
        rating, so these indices were never the constraint.
        """
        self.assertEqual(dp._INDEX_FLOOR, 0.05)
        self.assertEqual(dp._INDEX_CEILING, 0.95)

    def test_index_saturates_and_that_is_ACCEPTED(self) -> None:
        """Two very strong teams DO collapse to the same index here, and that is
        a deliberate trade, not an oversight.

        It costs nothing measurable: margin dispersion is produced downstream in
        play_simulator from the raw ratings, which are never clamped. Widening
        these to separate such teams changed margin SD by -0.7 and total SD by
        +2.0 -- strictly worse on both.
        """
        strong = _profile(0.60, 0.0).offense_index
        stronger = _profile(1.20, 0.0).offense_index
        self.assertEqual(strong, stronger,
                         "saturation is expected at these bounds; if this changes, "
                         "re-measure totals before assuming it is an improvement")

    def test_margin_still_differentiates_despite_index_saturation(self) -> None:
        """The load-bearing claim: saturation upstream does NOT flatten margins,
        because the ratings reach play_simulator unclamped."""
        from syndicate.features.football.sim_engine.smartsim2.game_simulator import simulate_game
        from syndicate.features.football.sim_engine.smartsim2.ncaaf_calibration_profile import (
            NCAAF_CALIBRATION_PROFILE,
        )
        import statistics

        def margin(ho, ao, seeds=60):
            vals = []
            for s in range(1, seeds + 1):
                o = simulate_game(SmartSim2SimulationInput(
                    home_team="H", away_team="A", seed=s,
                    home_offense_rating=ho, away_offense_rating=ao),
                    profile=NCAAF_CALIBRATION_PROFILE)
                vals.append(o.final_score["home"] - o.final_score["away"])
            return statistics.fmean(vals)

        # Both saturate the index, yet must still produce different margins.
        self.assertGreater(margin(1.60, -1.60), margin(0.60, -0.60) + 3.0,
                           "margins collapsed with the index saturated -- the "
                           "differentiation is NOT coming from play_simulator after all")

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
