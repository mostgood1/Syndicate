"""Split offence/defence drive-success sensitivities -- both OFF by default.

`#686`/`#687`, lane `smartsim2-total-nonlinearity`. Fitting ACTUAL totals
against the rating each generator really feeds the engine, and comparing with
what the engine applies, gives keep ratios that are near MIRROR IMAGES:

    NFL     offence 0.438   defence 0.026
    NCAAF   offence 0.112   defence 0.399

`drive_success_sensitivity` is one dial shrinking the whole spread toward an
anchor, so it applies ONE ratio to both directions and cannot satisfy either
sport. These pin the split that can.

The first test is the one that matters: at the defaults this must be an EXACT
algebraic no-op, because `smartsim2` is shared by both football sports and the
NFL profile is a frozen Production Candidate.
"""
from __future__ import annotations

import dataclasses
import unittest

from syndicate.features.football.sim_engine.smartsim2.calibration_profile import NFL_CALIBRATION_PROFILE
from syndicate.features.football.sim_engine.smartsim2.ncaaf_calibration_profile import NCAAF_CALIBRATION_PROFILE
from syndicate.features.football.sim_engine.smartsim2.drive_priors import (
    DRIVE_SUCCESS_DEFENSE_WEIGHT,
    DRIVE_SUCCESS_NEUTRAL_INDEX,
    DRIVE_SUCCESS_OFFENSE_WEIGHT,
    drive_success_team_terms,
)

CASES = ((0.80, 0.25), (0.05, 0.95), (0.5, 0.5), (0.31, 0.67), (0.95, 0.05))


class DefaultIsAnExactNoOpTests(unittest.TestCase):
    def test_both_shipped_profiles_default_to_one(self) -> None:
        for profile in (NFL_CALIBRATION_PROFILE, NCAAF_CALIBRATION_PROFILE):
            with self.subTest(profile=profile.name):
                self.assertEqual(profile.drive_success_offense_sensitivity, 1.0)
                self.assertEqual(profile.drive_success_defense_sensitivity, 1.0)

    def test_the_literal_terms_are_reproduced_exactly(self) -> None:
        """At the defaults the neutral term must CANCEL, for any index.

        If it does not, every seeded projection in both football sports moves
        the moment this lands -- which is the whole risk of touching a shared,
        calibrated engine.
        """
        for off, dfn in CASES:
            with self.subTest(offense=off, defense=dfn):
                o, d = drive_success_team_terms(off, dfn)
                self.assertAlmostEqual(o, off * DRIVE_SUCCESS_OFFENSE_WEIGHT, places=12)
                self.assertAlmostEqual(d, -dfn * DRIVE_SUCCESS_DEFENSE_WEIGHT, places=12)


class SplitShapeTests(unittest.TestCase):
    def test_offence_dial_moves_only_the_offence_term(self) -> None:
        full_o, full_d = drive_success_team_terms(0.95, 0.80)
        cut_o, cut_d = drive_success_team_terms(0.95, 0.80, offense_sensitivity=0.0)
        self.assertAlmostEqual(full_o - cut_o, (0.95 - 0.5) * DRIVE_SUCCESS_OFFENSE_WEIGHT, places=12)
        self.assertEqual(full_d, cut_d)

    def test_defence_dial_moves_only_the_defence_term(self) -> None:
        full_o, full_d = drive_success_team_terms(0.80, 0.95)
        cut_o, cut_d = drive_success_team_terms(0.80, 0.95, defense_sensitivity=0.0)
        # a STRONG defence suppresses drive success, so removing it RAISES the term
        self.assertAlmostEqual(cut_d - full_d, (0.95 - 0.5) * DRIVE_SUCCESS_DEFENSE_WEIGHT, places=12)
        self.assertEqual(full_o, cut_o)

    def test_a_neutral_team_is_unmoved_by_either_dial(self) -> None:
        """Shrinking toward neutral must not move a team that IS neutral,
        or the dial moves the league MEAN, which is already correct."""
        base = drive_success_team_terms(DRIVE_SUCCESS_NEUTRAL_INDEX, DRIVE_SUCCESS_NEUTRAL_INDEX)
        for value in (0.0, 0.25, 1.0, 2.0):
            with self.subTest(sensitivity=value):
                self.assertEqual(
                    drive_success_team_terms(DRIVE_SUCCESS_NEUTRAL_INDEX, DRIVE_SUCCESS_NEUTRAL_INDEX,
                                             offense_sensitivity=value, defense_sensitivity=value),
                    base,
                )

    def test_the_measured_per_sport_ratios_give_different_answers(self) -> None:
        """NFL 0.438/0.026 vs NCAAF 0.112/0.399 -- the mirror-image keep ratios
        that make a single shared dial unable to serve both sports."""
        nfl = drive_success_team_terms(0.9, 0.9, offense_sensitivity=0.438, defense_sensitivity=0.026)
        ncaaf = drive_success_team_terms(0.9, 0.9, offense_sensitivity=0.112, defense_sensitivity=0.399)
        self.assertNotAlmostEqual(nfl[0], ncaaf[0], places=4)
        self.assertNotAlmostEqual(nfl[1], ncaaf[1], places=4)


class ReachabilityTests(unittest.TestCase):
    def test_the_dials_reach_a_SIMULATED_total(self) -> None:
        """Present-but-not-wired is the failure `model_engine_standard.md` names."""
        import statistics

        from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationInput
        from syndicate.features.football.sim_engine.smartsim2.game_simulator import simulate_game

        def mean_total(profile):
            out = []
            for seed in range(1, 31):
                res = simulate_game(
                    SmartSim2SimulationInput(
                        feature_generation_payload={}, home_team="H", away_team="A", seed=seed,
                        home_offense_rating=0.9, home_defense_rating=0.7,
                        away_offense_rating=0.8, away_defense_rating=0.6),
                    profile=profile)
                out.append(res.final_score["home"] + res.final_score["away"])
            return statistics.fmean(out)

        flattened = dataclasses.replace(NFL_CALIBRATION_PROFILE,
                                        drive_success_offense_sensitivity=0.0,
                                        drive_success_defense_sensitivity=0.0)
        self.assertNotAlmostEqual(mean_total(flattened), mean_total(NFL_CALIBRATION_PROFILE), places=3)


if __name__ == "__main__":
    unittest.main()
