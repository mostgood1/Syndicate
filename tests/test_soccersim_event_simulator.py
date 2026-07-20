from __future__ import annotations

import unittest
from random import Random

from syndicate.features.soccer.sim_engine.soccersim.contracts import PossessionOutcome
from syndicate.features.soccer.sim_engine.soccersim.contracts import SoccerSimSimulationInput
from syndicate.features.soccer.sim_engine.soccersim.event_outcomes import EventOutcome
from syndicate.features.soccer.sim_engine.soccersim.event_simulator import simulate_event
from syndicate.features.soccer.sim_engine.soccersim.event_state import build_event_state_from_possession_state
from syndicate.features.soccer.sim_engine.soccersim.possession_priors import build_possession_priors
from syndicate.features.soccer.sim_engine.soccersim.possession_state import build_initial_possession_state


class SoccerSimEventSimulatorTests(unittest.TestCase):
    def _fixture(self, *, pitch_position: int = 50, phase: str = "open_play", clock_remaining: int = 2000):
        simulation_input = SoccerSimSimulationInput(home_team="ARS", away_team="LIV", seed=7)
        possession_state = build_initial_possession_state(
            home_team="ARS",
            away_team="LIV",
            pitch_position=pitch_position,
            phase=phase,
            clock_remaining=clock_remaining,
        )
        priors = build_possession_priors(simulation_input, possession_state=possession_state)
        event_state = build_event_state_from_possession_state(possession_state)
        return simulation_input, possession_state, priors, event_state

    def test_event_consumes_clock_and_advances_index(self) -> None:
        simulation_input, possession_state, priors, event_state = self._fixture()
        result = simulate_event(event_state, possession_state, simulation_input, priors=priors, rng=Random(1))

        self.assertGreaterEqual(result.clock_consumed, 3)
        self.assertEqual(result.step_index, 1)
        self.assertLess(result.end_possession_state.clock_remaining, possession_state.clock_remaining)
        self.assertIsInstance(result.outcome, EventOutcome)

    def test_no_shots_from_deep_positions(self) -> None:
        simulation_input, possession_state, priors, event_state = self._fixture(pitch_position=20)
        for seed in range(150):
            result = simulate_event(event_state, possession_state, simulation_input, priors=priors, rng=Random(seed))
            self.assertNotEqual(result.outcome, EventOutcome.SHOT)

    def test_box_events_can_produce_goals(self) -> None:
        simulation_input, possession_state, priors, event_state = self._fixture(pitch_position=90)
        seen_goal = False
        for seed in range(300):
            result = simulate_event(event_state, possession_state, simulation_input, priors=priors, rng=Random(seed))
            if result.terminal_possession_outcome in {PossessionOutcome.GOAL, PossessionOutcome.PENALTY_GOAL}:
                seen_goal = True
                self.assertEqual(result.goals_scored, 1)
                self.assertEqual(result.end_possession_state.score_home, 1)
                self.assertEqual(result.end_possession_state.possession_owner, "away")
                self.assertEqual(result.end_possession_state.pitch_position, 50)
                break
        self.assertTrue(seen_goal, "no goal observed from 300 seeded box events")

    def test_turnover_mirrors_pitch_position(self) -> None:
        simulation_input, possession_state, priors, event_state = self._fixture(pitch_position=70)
        for seed in range(200):
            result = simulate_event(event_state, possession_state, simulation_input, priors=priors, rng=Random(seed))
            if result.terminal_possession_outcome == PossessionOutcome.TURNOVER:
                self.assertEqual(result.end_possession_state.possession_owner, "away")
                self.assertLess(result.end_possession_state.pitch_position, 60)
                return
        self.fail("no turnover observed across 200 seeded events")


if __name__ == "__main__":
    unittest.main()
