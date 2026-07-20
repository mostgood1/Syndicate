from __future__ import annotations

import unittest
from random import Random

from syndicate.features.soccer.sim_engine.soccersim.contracts import PossessionOutcome
from syndicate.features.soccer.sim_engine.soccersim.contracts import SoccerSimSimulationInput
from syndicate.features.soccer.sim_engine.soccersim.possession_simulator import simulate_possession
from syndicate.features.soccer.sim_engine.soccersim.possession_state import build_initial_possession_state

_TERMINAL_OUTCOMES = {
    PossessionOutcome.GOAL,
    PossessionOutcome.PENALTY_GOAL,
    PossessionOutcome.PENALTY_MISSED,
    PossessionOutcome.SHOT_SAVED,
    PossessionOutcome.SHOT_OFF_TARGET,
    PossessionOutcome.SHOT_BLOCKED,
    PossessionOutcome.TURNOVER,
    PossessionOutcome.OFFSIDE,
    PossessionOutcome.END_OF_HALF_STOP,
    PossessionOutcome.END_OF_MATCH_STOP,
}


class SoccerSimPossessionSimulatorTests(unittest.TestCase):
    def _simulation_input(self, seed: int = 5) -> SoccerSimSimulationInput:
        return SoccerSimSimulationInput(home_team="ARS", away_team="LIV", seed=seed)

    def test_possession_ends_in_terminal_outcome(self) -> None:
        state = build_initial_possession_state(home_team="ARS", away_team="LIV", clock_remaining=2700)
        result = simulate_possession(state, self._simulation_input(), rng=Random(3))

        self.assertIn(result.outcome, _TERMINAL_OUTCOMES)
        self.assertGreaterEqual(result.event_count, 1)
        self.assertEqual(len(result.steps), result.event_count)
        self.assertGreater(result.clock_consumed, 0)

    def test_goal_updates_score_and_flips_possession(self) -> None:
        state = build_initial_possession_state(home_team="ARS", away_team="LIV", clock_remaining=2700)
        for seed in range(200):
            result = simulate_possession(state, self._simulation_input(seed), rng=Random(seed))
            if result.outcome in {PossessionOutcome.GOAL, PossessionOutcome.PENALTY_GOAL}:
                self.assertEqual(result.goals_scored, 1)
                self.assertEqual(result.end_state.score_home, 1)
                self.assertEqual(result.end_state.possession_owner, "away")
                self.assertTrue(result.possession_change)
                self.assertTrue(result.shot_taken)
                return
        self.fail("no goal observed across 200 seeded possessions")

    def test_exhausted_clock_ends_half(self) -> None:
        state = build_initial_possession_state(home_team="ARS", away_team="LIV", half=1, clock_remaining=0)
        result = simulate_possession(state, self._simulation_input(), rng=Random(9))
        self.assertEqual(result.outcome, PossessionOutcome.END_OF_HALF_STOP)

        second_half_state = build_initial_possession_state(home_team="ARS", away_team="LIV", half=2, clock_remaining=0)
        result = simulate_possession(second_half_state, self._simulation_input(), rng=Random(9))
        self.assertEqual(result.outcome, PossessionOutcome.END_OF_MATCH_STOP)

    def test_possession_is_seed_stable(self) -> None:
        state = build_initial_possession_state(home_team="ARS", away_team="LIV", clock_remaining=2700)
        first = simulate_possession(state, self._simulation_input(), rng=Random(21)).to_dict()
        second = simulate_possession(state, self._simulation_input(), rng=Random(21)).to_dict()
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
