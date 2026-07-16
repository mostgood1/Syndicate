from __future__ import annotations

import unittest
from random import Random

from syndicate.features.football.sim_engine.smartsim2.contracts import PossessionOutcome
from syndicate.features.football.sim_engine.smartsim2.contracts import PossessionState
from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationInput
from syndicate.features.football.sim_engine.smartsim2.drive_priors import build_drive_priors
from syndicate.features.football.sim_engine.smartsim2.play_outcomes import PlayOutcome
from syndicate.features.football.sim_engine.smartsim2.play_simulator import simulate_play
from syndicate.features.football.sim_engine.smartsim2.play_state import build_play_state_from_possession_state


class SmartSim2PlaySimulatorTests(unittest.TestCase):
    def test_simulate_play_returns_stateful_play_result(self) -> None:
        simulation_input = SmartSim2SimulationInput(home_team="PHI", away_team="DAL", seed=9)
        possession_state = PossessionState(
            possession_owner="home",
            field_position=25,
            down=1,
            distance=10,
            quarter=1,
            clock_remaining=900,
            home_team="PHI",
            away_team="DAL",
        )
        play_state = build_play_state_from_possession_state(possession_state)
        priors = build_drive_priors(simulation_input, possession_state=possession_state)

        result = simulate_play(play_state, possession_state, simulation_input, priors=priors, rng=Random(9))

        self.assertEqual(result.step_index, 1)
        self.assertIn(result.outcome, set(PlayOutcome))
        self.assertLessEqual(result.end_possession_state.clock_remaining, possession_state.clock_remaining)
        self.assertGreaterEqual(result.end_state.play_index, 1)
        self.assertIsNone(result.terminal_drive_outcome)

    def test_touchdown_play_maps_to_terminal_drive_outcome(self) -> None:
        simulation_input = SmartSim2SimulationInput(home_team="PHI", away_team="DAL", seed=3)
        possession_state = PossessionState(
            possession_owner="home",
            field_position=96,
            down=1,
            distance=4,
            quarter=1,
            clock_remaining=300,
            home_team="PHI",
            away_team="DAL",
        )
        play_state = build_play_state_from_possession_state(possession_state)
        priors = build_drive_priors(simulation_input, possession_state=possession_state)

        result = simulate_play(play_state, possession_state, simulation_input, priors=priors, rng=Random(1))

        if result.outcome == PlayOutcome.TOUCHDOWN:
            self.assertEqual(result.terminal_drive_outcome, PossessionOutcome.TOUCHDOWN)
            self.assertEqual(result.points_scored, 7)

        if result.outcome == PlayOutcome.FIELD_GOAL_ATTEMPT and result.terminal_drive_outcome == PossessionOutcome.MISSED_FIELD_GOAL:
            self.assertEqual(result.points_scored, 0)
            self.assertEqual(result.end_possession_state.possession_owner, "away")


if __name__ == "__main__":
    unittest.main()