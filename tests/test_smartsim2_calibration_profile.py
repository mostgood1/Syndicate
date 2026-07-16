from __future__ import annotations

import unittest
from dataclasses import fields
from dataclasses import replace
from random import Random

from syndicate.features.football.sim_engine.smartsim2.calibration_profile import CalibrationProfile
from syndicate.features.football.sim_engine.smartsim2.calibration_profile import NFL_CALIBRATION_PROFILE
from syndicate.features.football.sim_engine.smartsim2.contracts import PossessionOutcome
from syndicate.features.football.sim_engine.smartsim2.contracts import PossessionState
from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationInput
from syndicate.features.football.sim_engine.smartsim2.drive_priors import build_drive_priors
from syndicate.features.football.sim_engine.smartsim2.drive_simulator import simulate_drive
from syndicate.features.football.sim_engine.smartsim2.game_simulator import simulate_game
from syndicate.features.football.sim_engine.smartsim2.ncaaf_calibration_profile import NCAAF_CALIBRATION_PROFILE
from syndicate.features.football.sim_engine.smartsim2.possession_state import build_initial_possession_state


class SmartSim2CalibrationProfileTests(unittest.TestCase):
    def test_nfl_profile_defaults_match_pre_profile_hardcoded_literals(self) -> None:
        self.assertEqual(NFL_CALIBRATION_PROFILE.red_zone_touchdown_weight_bonus, 0.33)
        self.assertEqual(NFL_CALIBRATION_PROFILE.red_zone_gain_stiffening, 0.80)
        self.assertEqual(NFL_CALIBRATION_PROFILE.explosive_play_multiplier, 1.0)
        self.assertEqual(NFL_CALIBRATION_PROFILE.touchdown_weight_multiplier, 1.0)
        self.assertEqual(NFL_CALIBRATION_PROFILE.field_goal_make_base, 0.98)

    def test_ncaaf_profile_shares_exactly_the_documented_fields(self) -> None:
        differing = {
            field.name
            for field in fields(CalibrationProfile)
            if field.name != "name" and getattr(NFL_CALIBRATION_PROFILE, field.name) != getattr(NCAAF_CALIBRATION_PROFILE, field.name)
        }
        self.assertEqual(
            differing,
            {
                "explosive_play_multiplier",
                "explosive_yardage_multiplier",
                "drive_yardage_multiplier",
                "field_goal_make_base",
                "field_goal_make_distance_penalty",
                "field_goal_make_floor",
                "field_goal_make_ceiling",
                "fourth_down_conversion_multiplier",
                "touchdown_weight_multiplier",
                "red_zone_touchdown_weight_bonus",
            },
        )
        # red_zone_gain_stiffening was measured and explicitly left at the
        # shared/NFL default -- confirm it stays that way, not merely unset.
        self.assertEqual(NCAAF_CALIBRATION_PROFILE.red_zone_gain_stiffening, NFL_CALIBRATION_PROFILE.red_zone_gain_stiffening)

    def test_omitting_profile_reproduces_explicit_nfl_profile(self) -> None:
        simulation_input = SmartSim2SimulationInput(home_team="PHI", away_team="DAL", seed=4)

        default_call = simulate_game(simulation_input).to_dict()
        explicit_nfl_call = simulate_game(simulation_input, profile=NFL_CALIBRATION_PROFILE).to_dict()

        self.assertEqual(default_call["final_score"], explicit_nfl_call["final_score"])
        self.assertEqual(default_call["drive_log"], explicit_nfl_call["drive_log"])

    def test_higher_red_zone_touchdown_weight_bonus_raises_red_zone_touchdown_frequency(self) -> None:
        aggressive_profile = replace(NCAAF_CALIBRATION_PROFILE, red_zone_touchdown_weight_bonus=0.90)
        conservative_profile = replace(NCAAF_CALIBRATION_PROFILE, red_zone_touchdown_weight_bonus=0.20)

        def red_zone_touchdowns(profile: CalibrationProfile, trials: int) -> int:
            touchdowns = 0
            for seed in range(1, trials + 1):
                state = build_initial_possession_state(
                    home_team="PHI",
                    away_team="DAL",
                    owner="home",
                    field_position=88,
                    down=1,
                    distance=10,
                    quarter=1,
                    clock_remaining=900,
                )
                simulation_input = SmartSim2SimulationInput(home_team="PHI", away_team="DAL", seed=seed)
                result = simulate_drive(state, simulation_input, rng=Random(seed), profile=profile)
                if result.outcome == PossessionOutcome.TOUCHDOWN:
                    touchdowns += 1
            return touchdowns

        trials = 250
        aggressive_touchdowns = red_zone_touchdowns(aggressive_profile, trials)
        conservative_touchdowns = red_zone_touchdowns(conservative_profile, trials)

        self.assertGreater(aggressive_touchdowns, conservative_touchdowns)

    def test_ncaaf_profile_field_summary_round_trips_through_to_dict(self) -> None:
        payload = NCAAF_CALIBRATION_PROFILE.to_dict()
        self.assertEqual(payload["red_zone_touchdown_weight_bonus"], 0.58)
        self.assertEqual(payload["red_zone_gain_stiffening"], 0.80)
        self.assertEqual(payload["name"], "ncaaf")


if __name__ == "__main__":
    unittest.main()
