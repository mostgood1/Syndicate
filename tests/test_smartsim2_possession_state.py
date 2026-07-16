from __future__ import annotations

import unittest

from syndicate.features.football.sim_engine.smartsim2.contracts import PossessionState
from syndicate.features.football.sim_engine.smartsim2.possession_state import advance_possession_clock
from syndicate.features.football.sim_engine.smartsim2.possession_state import build_initial_possession_state
from syndicate.features.football.sim_engine.smartsim2.possession_state import advance_quarter
from syndicate.features.football.sim_engine.smartsim2.possession_state import reset_for_next_possession


class SmartSim2PossessionStateTests(unittest.TestCase):
    def test_initial_state_contains_required_fields(self) -> None:
        state = build_initial_possession_state(home_team="PHI", away_team="DAL")

        self.assertIsInstance(state, PossessionState)
        self.assertEqual(state.possession_owner, "home")
        self.assertEqual(state.field_position, 25)
        self.assertEqual(state.down, 1)
        self.assertEqual(state.distance, 10)
        self.assertEqual(state.quarter, 1)
        self.assertEqual(state.clock_remaining, 900)

    def test_state_helpers_move_clock_and_possession(self) -> None:
        state = build_initial_possession_state(home_team="PHI", away_team="DAL")
        advanced = advance_possession_clock(state, 30)
        swapped = reset_for_next_possession(advanced, owner="away", field_position=75)
        next_quarter = advance_quarter(swapped)

        self.assertEqual(advanced.clock_remaining, 870)
        self.assertEqual(swapped.possession_owner, "away")
        self.assertEqual(swapped.field_position, 75)
        self.assertEqual(swapped.down, 1)
        self.assertEqual(swapped.distance, 10)
        self.assertEqual(next_quarter.quarter, 2)
        self.assertEqual(next_quarter.clock_remaining, 900)


if __name__ == "__main__":
    unittest.main()