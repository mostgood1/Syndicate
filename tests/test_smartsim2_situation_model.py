from __future__ import annotations

import unittest

from syndicate.features.football.sim_engine.smartsim2.play_state import PlayState
from syndicate.features.football.sim_engine.smartsim2.situation_model import classify_situation


class SmartSim2SituationModelTests(unittest.TestCase):
    def test_classify_red_zone_and_goal_line(self) -> None:
        red_zone_state = PlayState(
            possession_team="PHI",
            down=2,
            distance=7,
            yardline=82,
            quarter=2,
            seconds_remaining=600,
            score_differential=0,
        )
        backed_up_state = PlayState(
            possession_team="PHI",
            down=2,
            distance=7,
            yardline=18,
            quarter=2,
            seconds_remaining=600,
            score_differential=0,
        )
        goal_line_state = PlayState(
            possession_team="PHI",
            down=1,
            distance=3,
            yardline=97,
            quarter=2,
            seconds_remaining=600,
            score_differential=0,
        )

        red_zone = classify_situation(red_zone_state)
        backed_up = classify_situation(backed_up_state)
        goal_line = classify_situation(goal_line_state)

        self.assertEqual(red_zone.label, "Red Zone")
        self.assertTrue(red_zone.red_zone)
        self.assertFalse(red_zone.goal_to_go)
        self.assertFalse(backed_up.red_zone)
        self.assertTrue(backed_up.backed_up_territory)
        self.assertEqual(goal_line.label, "Goal Line")
        self.assertTrue(goal_line.goal_to_go)

    def test_classify_two_minute_and_four_minute(self) -> None:
        two_minute_state = PlayState(
            possession_team="PHI",
            down=2,
            distance=6,
            yardline=50,
            quarter=4,
            seconds_remaining=98,
            score_differential=-4,
        )
        four_minute_state = PlayState(
            possession_team="PHI",
            down=1,
            distance=10,
            yardline=44,
            quarter=4,
            seconds_remaining=235,
            score_differential=7,
        )

        self.assertEqual(classify_situation(two_minute_state).label, "Two Minute Drill")
        self.assertEqual(classify_situation(four_minute_state).label, "Four Minute Offense")


if __name__ == "__main__":
    unittest.main()