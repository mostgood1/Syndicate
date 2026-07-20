from __future__ import annotations

import unittest

from syndicate.features.soccer.sim_engine.soccersim.contracts import SoccerSimSimulationInput
from syndicate.features.soccer.sim_engine.soccersim.possession_priors import build_possession_priors
from syndicate.features.soccer.sim_engine.soccersim.possession_priors import possession_outcome_distribution
from syndicate.features.soccer.sim_engine.soccersim.possession_state import build_initial_possession_state


class SoccerSimPossessionPriorsTests(unittest.TestCase):
    def test_neutral_priors_are_within_expected_bands(self) -> None:
        simulation_input = SoccerSimSimulationInput(home_team="ARS", away_team="LIV", seed=1)
        priors = build_possession_priors(simulation_input)

        self.assertGreaterEqual(priors.attack_index, 0.05)
        self.assertLessEqual(priors.attack_index, 0.95)
        self.assertGreaterEqual(priors.shot_generation_probability, 0.04)
        self.assertLessEqual(priors.shot_generation_probability, 0.34)
        self.assertGreaterEqual(priors.goal_conversion_probability, 0.035)
        self.assertLessEqual(priors.goal_conversion_probability, 0.22)
        self.assertGreater(priors.expected_possession_seconds, 10.0)
        self.assertLess(priors.expected_possession_seconds, 120.0)

    def test_feature_payload_moves_attack_index(self) -> None:
        base_input = SoccerSimSimulationInput(home_team="ARS", away_team="LIV", seed=1)
        strong_input = SoccerSimSimulationInput(
            home_team="ARS",
            away_team="LIV",
            seed=1,
            feature_generation_payload={
                "attacking_metrics": {"xg_for_per_match": 2.3, "shots_per_match": 18.0, "goals_per_match": 2.2},
                "defensive_metrics": {"xg_against_per_match": 0.8, "shots_allowed_per_match": 8.0},
            },
        )
        base_priors = build_possession_priors(base_input)
        strong_priors = build_possession_priors(strong_input)

        self.assertGreater(strong_priors.attack_index, base_priors.attack_index)
        self.assertGreater(strong_priors.defense_index, base_priors.defense_index)
        self.assertGreater(strong_priors.shot_generation_probability, base_priors.shot_generation_probability)

    def test_home_owner_receives_home_advantage_boost(self) -> None:
        simulation_input = SoccerSimSimulationInput(home_team="ARS", away_team="LIV", seed=1)
        home_state = build_initial_possession_state(home_team="ARS", away_team="LIV", owner="home")
        away_state = build_initial_possession_state(home_team="ARS", away_team="LIV", owner="away")

        home_priors = build_possession_priors(simulation_input, possession_state=home_state)
        away_priors = build_possession_priors(simulation_input, possession_state=away_state)

        self.assertGreater(home_priors.attack_index, away_priors.attack_index)

    def test_owner_specific_ratings_are_used(self) -> None:
        simulation_input = SoccerSimSimulationInput(
            home_team="ARS",
            away_team="LIV",
            seed=1,
            home_attack_rating=0.2,
            away_attack_rating=-0.2,
        )
        home_state = build_initial_possession_state(home_team="ARS", away_team="LIV", owner="home")
        away_state = build_initial_possession_state(home_team="ARS", away_team="LIV", owner="away")

        home_priors = build_possession_priors(simulation_input, possession_state=home_state)
        away_priors = build_possession_priors(simulation_input, possession_state=away_state)

        self.assertGreater(home_priors.attack_index - away_priors.attack_index, 0.15)

    def test_possession_outcome_distribution_normalizes(self) -> None:
        simulation_input = SoccerSimSimulationInput(home_team="ARS", away_team="LIV", seed=1)
        state = build_initial_possession_state(home_team="ARS", away_team="LIV", pitch_position=75)
        priors = build_possession_priors(simulation_input, possession_state=state)
        distribution = possession_outcome_distribution(state, priors)

        self.assertAlmostEqual(sum(distribution.values()), 1.0, places=6)
        self.assertGreater(distribution["turnover"], distribution["goal"])


if __name__ == "__main__":
    unittest.main()
