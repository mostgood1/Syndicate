"""Blowout damping in `smartsim2` -- OFF by default, for BOTH football sports.

`#686` / lane `smartsim2-total-nonlinearity`. The engine scores at full rate in
the fourth quarter of a 30-point game (measured: Q4/Q1 scoring ratio 1.447 in a
matched game vs 1.412 in a mismatched one, i.e. unchanged), which is why a
mismatch inflates its projected TOTAL when reality says mismatch predicts
nothing about a total (`corr(|market spread|, ACTUAL total)` 2025 = -0.032).

These pin the mechanism's SHAPE and its inertness. They deliberately do NOT
assert that arming it improves anything -- it has not been fitted, and for
NCAAF the actual-outcome total fit it would be judged against does not exist
yet.
"""
from __future__ import annotations

import dataclasses
import unittest

from syndicate.features.football.sim_engine.smartsim2.calibration_profile import NFL_CALIBRATION_PROFILE
from syndicate.features.football.sim_engine.smartsim2.ncaaf_calibration_profile import NCAAF_CALIBRATION_PROFILE
from syndicate.features.football.sim_engine.smartsim2.play_simulator import blowout_damping_factor
from syndicate.features.football.sim_engine.smartsim2.play_state import PlayState


def _state(*, lead: int, quarter: int, seconds: int) -> PlayState:
    return PlayState(
        possession_team="HOM", down=1, distance=10, yardline=50,
        quarter=quarter, seconds_remaining=seconds, score_differential=lead,
    )


ARMED = dataclasses.replace(NFL_CALIBRATION_PROFILE, blowout_damping_strength=0.5)


class DefaultIsOffTests(unittest.TestCase):
    """Both shipped profiles must be EXACTLY unaffected."""

    def test_both_sports_default_to_strength_zero(self) -> None:
        self.assertEqual(NFL_CALIBRATION_PROFILE.blowout_damping_strength, 0.0)
        self.assertEqual(NCAAF_CALIBRATION_PROFILE.blowout_damping_strength, 0.0)

    def test_default_returns_exactly_one_even_in_a_rout(self) -> None:
        # `1.0` exactly, not approximately: the multiplications in
        # `_play_outcome_weights` must be arithmetic no-ops, so that shipping
        # this disabled cannot perturb a single seeded result.
        for profile in (NFL_CALIBRATION_PROFILE, NCAAF_CALIBRATION_PROFILE):
            with self.subTest(profile=profile.__class__.__name__):
                worst = _state(lead=45, quarter=4, seconds=10)
                self.assertIs(type(blowout_damping_factor(worst, profile)), float)
                self.assertEqual(blowout_damping_factor(worst, profile), 1.0)


class ShapeTests(unittest.TestCase):
    def test_a_close_game_is_never_damped(self) -> None:
        self.assertEqual(blowout_damping_factor(_state(lead=7, quarter=4, seconds=30), ARMED), 1.0)

    def test_the_trailing_team_is_never_damped(self) -> None:
        # Garbage-time points by the loser are real; it is the LEADER easing
        # off that caps a blowout.
        self.assertEqual(blowout_damping_factor(_state(lead=-35, quarter=4, seconds=30), ARMED), 1.0)

    def test_first_half_is_never_damped_however_big_the_lead(self) -> None:
        for q in (1, 2):
            with self.subTest(quarter=q):
                self.assertEqual(blowout_damping_factor(_state(lead=40, quarter=q, seconds=1), ARMED), 1.0)

    def test_damping_strengthens_as_the_game_runs_out(self) -> None:
        early = blowout_damping_factor(_state(lead=28, quarter=3, seconds=900), ARMED)
        mid = blowout_damping_factor(_state(lead=28, quarter=4, seconds=900), ARMED)
        late = blowout_damping_factor(_state(lead=28, quarter=4, seconds=60), ARMED)
        self.assertEqual(early, 1.0)          # start of Q3 is the ramp's origin
        self.assertLess(mid, early)
        self.assertLess(late, mid)

    def test_damping_strengthens_with_the_lead(self) -> None:
        small = blowout_damping_factor(_state(lead=17, quarter=4, seconds=60), ARMED)
        big = blowout_damping_factor(_state(lead=35, quarter=4, seconds=60), ARMED)
        self.assertLess(big, small)

    def test_it_never_leaves_the_unit_interval(self) -> None:
        brutal = dataclasses.replace(NFL_CALIBRATION_PROFILE, blowout_damping_strength=10.0)
        worst = blowout_damping_factor(_state(lead=70, quarter=4, seconds=0), brutal)
        self.assertGreaterEqual(worst, 0.0)
        self.assertLessEqual(worst, 1.0)

    def test_lead_span_saturates_rather_than_running_away(self) -> None:
        at_span = blowout_damping_factor(_state(lead=28, quarter=4, seconds=0), ARMED)
        beyond = blowout_damping_factor(_state(lead=60, quarter=4, seconds=0), ARMED)
        self.assertEqual(at_span, beyond)


class ReachabilityTests(unittest.TestCase):
    """Shipping disabled must not mean shipping untestable: off != on."""

    def test_arming_it_changes_the_factor(self) -> None:
        rout = _state(lead=28, quarter=4, seconds=60)
        self.assertEqual(blowout_damping_factor(rout, NFL_CALIBRATION_PROFILE), 1.0)
        self.assertLess(blowout_damping_factor(rout, ARMED), 1.0)

    def test_arming_it_actually_lowers_a_simulated_total(self) -> None:
        """The end-to-end reachability check: the knob must reach the SCORE.

        A factor that moves while the simulated game does not would be a
        feature that is present but not wired -- the exact failure
        `model_engine_standard.md` calls out.
        """
        import statistics

        from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationInput
        from syndicate.features.football.sim_engine.smartsim2.game_simulator import simulate_game

        strong = dataclasses.replace(NFL_CALIBRATION_PROFILE, blowout_damping_strength=0.9)

        def mean_total(profile):
            totals = []
            for seed in range(1, 41):
                out = simulate_game(
                    SmartSim2SimulationInput(
                        feature_generation_payload={}, home_team="H", away_team="A", seed=seed,
                        home_offense_rating=0.8, home_defense_rating=0.8,
                        away_offense_rating=-0.8, away_defense_rating=-0.8),
                    profile=profile)
                totals.append(out.final_score["home"] + out.final_score["away"])
            return statistics.fmean(totals)

        self.assertLess(mean_total(strong), mean_total(NFL_CALIBRATION_PROFILE))


if __name__ == "__main__":
    unittest.main()
