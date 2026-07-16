from __future__ import annotations

import unittest

from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationInput
from syndicate.features.football.sim_engine.smartsim2.game_simulator import simulate_game


class SmartSim2GameSimulatorTests(unittest.TestCase):
    def test_game_simulation_produces_complete_state_sequence(self) -> None:
        simulation_input = SmartSim2SimulationInput(
            home_team="PHI",
            away_team="DAL",
            seed=11,
            home_offense_rating=0.12,
            home_defense_rating=0.08,
            away_offense_rating=-0.03,
            away_defense_rating=0.02,
        )

        result = simulate_game(simulation_input)

        self.assertEqual(result.simulation_kind, "smartsim2_possession")
        self.assertIn("home", result.final_score)
        self.assertIn("away", result.final_score)
        self.assertGreaterEqual(len(result.drive_log), 1)
        self.assertGreaterEqual(len(result.possession_log), 1)
        self.assertGreaterEqual(len(result.quarter_log), 1)
        self.assertIn("projected_final_score", result.compatibility_summary)
        self.assertIn("projected_spread", result.compatibility_summary)
        self.assertIn("projected_total", result.compatibility_summary)
        self.assertEqual(result.final_state["quarter"], 4 if result.final_state["quarter"] <= 4 else result.final_state["quarter"])

    def test_game_simulation_is_seed_stable(self) -> None:
        simulation_input = SmartSim2SimulationInput(home_team="PHI", away_team="DAL", seed=4)

        first = simulate_game(simulation_input).to_dict()
        second = simulate_game(simulation_input).to_dict()

        self.assertEqual(first["final_score"], second["final_score"])
        self.assertEqual(first["drive_log"], second["drive_log"])


if __name__ == "__main__":
    unittest.main()