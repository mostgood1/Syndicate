from __future__ import annotations

import unittest

from syndicate.features.football.sim_engine.smartsim2.contracts import PossessionOutcome
from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationInput
from syndicate.features.football.sim_engine.smartsim2.drive_simulator import simulate_drive
from syndicate.features.football.sim_engine.smartsim2.possession_state import build_initial_possession_state


class SmartSim2DriveSimulatorTests(unittest.TestCase):
    def test_drive_simulation_returns_terminal_drive_result(self) -> None:
        simulation_input = SmartSim2SimulationInput(home_team="PHI", away_team="DAL", seed=7)
        state = build_initial_possession_state(home_team="PHI", away_team="DAL")

        result = simulate_drive(state, simulation_input)

        self.assertGreaterEqual(result.play_count, 1)
        self.assertIn(result.outcome, {
            PossessionOutcome.TOUCHDOWN,
            PossessionOutcome.FIELD_GOAL,
            PossessionOutcome.MISSED_FIELD_GOAL,
            PossessionOutcome.PUNT,
            PossessionOutcome.TURNOVER,
            PossessionOutcome.TURNOVER_ON_DOWNS,
            PossessionOutcome.END_OF_QUARTER_STOP,
        })
        self.assertIsNotNone(result.end_state)
        self.assertGreaterEqual(len(result.steps), 1)
        self.assertGreaterEqual(result.clock_consumed, 0)

    def test_drive_simulation_changes_possession_or_scores(self) -> None:
        simulation_input = SmartSim2SimulationInput(home_team="PHI", away_team="DAL", seed=19)
        state = build_initial_possession_state(home_team="PHI", away_team="DAL", field_position=60)

        result = simulate_drive(state, simulation_input)

        self.assertTrue(result.possession_change or result.points_scored > 0 or result.outcome == PossessionOutcome.END_OF_QUARTER_STOP)


if __name__ == "__main__":
    unittest.main()