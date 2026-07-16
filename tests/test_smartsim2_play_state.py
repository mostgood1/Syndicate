from __future__ import annotations

import unittest

from syndicate.features.football.sim_engine.smartsim2.contracts import PossessionState
from syndicate.features.football.sim_engine.smartsim2.play_state import advance_down_and_distance
from syndicate.features.football.sim_engine.smartsim2.play_state import build_play_state_from_possession_state


class SmartSim2PlayStateTests(unittest.TestCase):
    def test_build_play_state_from_possession_state_maps_core_fields(self) -> None:
        possession_state = PossessionState(
            possession_owner="home",
            field_position=96,
            down=2,
            distance=3,
            quarter=4,
            clock_remaining=98,
            score_home=17,
            score_away=13,
            home_team="PHI",
            away_team="DAL",
        )

        play_state = build_play_state_from_possession_state(possession_state)

        self.assertEqual(play_state.possession_team, "PHI")
        self.assertEqual(play_state.down, 2)
        self.assertEqual(play_state.distance, 7)
        self.assertEqual(play_state.yardline, 96)
        self.assertEqual(play_state.quarter, 4)
        self.assertEqual(play_state.seconds_remaining, 98)
        self.assertEqual(play_state.score_differential, 4)
        self.assertTrue(play_state.red_zone)
        self.assertTrue(play_state.goal_to_go)
        self.assertTrue(play_state.field_goal_range)
        # Leading by 4 with 98 seconds left in Q4 is clock preservation, not hurry-up.
        self.assertEqual(play_state.urgency_state, "end_game_preservation")
        self.assertFalse(play_state.two_minute_drill)
        self.assertFalse(play_state.four_minute_offense)

    def test_negative_play_increases_distance_to_go(self) -> None:
        possession_state = PossessionState(
            possession_owner="home",
            field_position=50,
            down=2,
            distance=8,
            quarter=1,
            clock_remaining=600,
            home_team="PHI",
            away_team="DAL",
        )
        play_state = build_play_state_from_possession_state(possession_state)

        updated = advance_down_and_distance(play_state, yards_gained=-6)

        self.assertEqual(updated.down, 3)
        self.assertGreater(updated.distance, play_state.distance)


if __name__ == "__main__":
    unittest.main()