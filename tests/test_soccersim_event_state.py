from __future__ import annotations

import unittest

from syndicate.features.soccer.sim_engine.soccersim.event_state import advance_event_state
from syndicate.features.soccer.sim_engine.soccersim.event_state import build_event_state_from_possession_state
from syndicate.features.soccer.sim_engine.soccersim.possession_state import build_initial_possession_state


class SoccerSimEventStateTests(unittest.TestCase):
    def test_build_event_state_carries_situation_flags(self) -> None:
        possession_state = build_initial_possession_state(
            home_team="ARS", away_team="LIV", pitch_position=90, clock_remaining=1200
        )
        event_state = build_event_state_from_possession_state(possession_state)

        self.assertEqual(event_state.possession_team, "ARS")
        self.assertTrue(event_state.penalty_box)
        self.assertTrue(event_state.final_third)
        self.assertTrue(event_state.shooting_range)
        self.assertFalse(event_state.defensive_third)
        self.assertEqual(event_state.situation_label, "Penalty Box")

    def test_advance_event_state_updates_position_clock_and_index(self) -> None:
        possession_state = build_initial_possession_state(
            home_team="ARS", away_team="LIV", pitch_position=50, clock_remaining=1000
        )
        event_state = build_event_state_from_possession_state(possession_state)
        advanced = advance_event_state(event_state, pitch_progress=20, clock_consumed=15, phase="set_piece")

        self.assertEqual(advanced.pitch_position, 70)
        self.assertEqual(advanced.seconds_remaining, 985)
        self.assertEqual(advanced.event_index, 1)
        self.assertTrue(advanced.final_third)
        self.assertTrue(advanced.set_piece)

    def test_score_differential_is_owner_relative(self) -> None:
        possession_state = build_initial_possession_state(
            home_team="ARS", away_team="LIV", owner="away", score_home=2, score_away=1, clock_remaining=900, half=2
        )
        event_state = build_event_state_from_possession_state(possession_state)
        self.assertEqual(event_state.score_differential, -1)
        self.assertTrue(event_state.trailing_push)


if __name__ == "__main__":
    unittest.main()
