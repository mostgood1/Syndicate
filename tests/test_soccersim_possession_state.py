from __future__ import annotations

import unittest

from syndicate.features.soccer.sim_engine.soccersim.possession_state import advance_half
from syndicate.features.soccer.sim_engine.soccersim.possession_state import advance_possession_clock
from syndicate.features.soccer.sim_engine.soccersim.possession_state import build_initial_possession_state
from syndicate.features.soccer.sim_engine.soccersim.possession_state import mirror_pitch_position
from syndicate.features.soccer.sim_engine.soccersim.possession_state import possession_owner_to_team
from syndicate.features.soccer.sim_engine.soccersim.possession_state import reset_for_next_possession


class SoccerSimPossessionStateTests(unittest.TestCase):
    def test_build_initial_state_clamps_inputs(self) -> None:
        state = build_initial_possession_state(
            home_team="ARS",
            away_team="LIV",
            owner="HOME",
            pitch_position=150,
            clock_remaining=-5,
        )
        self.assertEqual(state.possession_owner, "home")
        self.assertEqual(state.pitch_position, 99)
        self.assertEqual(state.clock_remaining, 0)

    def test_clock_never_goes_negative(self) -> None:
        state = build_initial_possession_state(home_team="ARS", away_team="LIV", clock_remaining=10)
        state = advance_possession_clock(state, 25)
        self.assertEqual(state.clock_remaining, 0)

    def test_mirror_pitch_position(self) -> None:
        self.assertEqual(mirror_pitch_position(70), 30)
        self.assertEqual(mirror_pitch_position(1), 99)
        self.assertEqual(mirror_pitch_position(120), 1)

    def test_reset_for_next_possession_increments_index(self) -> None:
        state = build_initial_possession_state(home_team="ARS", away_team="LIV")
        state = reset_for_next_possession(state, owner="away", pitch_position=30)
        self.assertEqual(state.possession_owner, "away")
        self.assertEqual(state.pitch_position, 30)
        self.assertEqual(state.possession_index, 1)
        self.assertEqual(state.phase, "open_play")

    def test_advance_half_gives_kickoff_to_away_then_home(self) -> None:
        state = build_initial_possession_state(home_team="ARS", away_team="LIV", half=1)
        second = advance_half(state, half_seconds=2700)
        self.assertEqual(second.half, 2)
        self.assertEqual(second.possession_owner, "away")
        self.assertEqual(second.pitch_position, 50)
        self.assertEqual(second.phase, "kickoff")
        self.assertEqual(second.clock_remaining, 2700)

    def test_possession_owner_to_team(self) -> None:
        state = build_initial_possession_state(home_team="ARS", away_team="LIV", owner="away")
        self.assertEqual(possession_owner_to_team(state), "LIV")


if __name__ == "__main__":
    unittest.main()
