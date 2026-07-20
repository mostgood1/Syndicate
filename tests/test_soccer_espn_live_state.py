from __future__ import annotations

import unittest

from syndicate.features.soccer.ingestion.espn_live_state import build_live_state


def _summary() -> dict:
    return {
        "rosters": [
            {
                "homeAway": "home",
                "team": {"displayName": "Home FC"},
                "roster": [
                    {"starter": True, "athlete": {"id": "1", "displayName": "Home Striker"}, "position": {"name": "Forward"}},
                    {"starter": True, "athlete": {"id": "2", "displayName": "Home Keeper"}, "position": {"name": "Goalkeeper"}},
                ],
            },
            {
                "homeAway": "away",
                "team": {"displayName": "Away FC"},
                "roster": [
                    {"starter": True, "athlete": {"id": "3", "displayName": "Away Striker"}, "position": {"name": "Forward"}},
                ],
            },
        ],
        "keyEvents": [
            {"type": {"text": "Kickoff", "type": "kickoff"}, "period": {"number": 1}, "clock": {"value": 0.0}, "team": {}, "participants": []},
            {
                "type": {"text": "Goal", "type": "goal"},
                "period": {"number": 1},
                "clock": {"value": 1200.0},
                "team": {"displayName": "Home FC"},
                "participants": [{"athlete": {"id": "1", "displayName": "Home Striker"}}],
            },
            {
                "type": {"text": "Goal - Volley", "type": "goal---volley"},
                "period": {"number": 2},
                "clock": {"value": 4500.0},
                "team": {"displayName": "Away FC"},
                "participants": [{"athlete": {"id": "3", "displayName": "Away Striker"}}],
            },
            {
                "type": {"text": "Red Card", "type": "red-card"},
                "period": {"number": 2},
                "clock": {"value": 4000.0},
                "team": {"displayName": "Home FC"},
                "participants": [{"athlete": {"id": "2", "displayName": "Home Keeper"}}],
            },
        ],
        "commentary": [
            {
                "play": {
                    "type": {"text": "Goal", "type": "goal"},
                    "period": {"number": 1},
                    "clock": {"value": 1200.0},
                    "team": {"displayName": "Home FC"},
                    "participants": [{"athlete": {"id": "1", "displayName": "Home Striker"}}],
                    "text": "Goal! Home Striker shot from the centre of the box.",
                }
            },
            {
                "play": {
                    "type": {"text": "Corner Awarded", "type": "corner-awarded"},
                    "period": {"number": 1},
                    "clock": {"value": 500.0},
                    "team": {"displayName": "Home FC"},
                    "participants": [],
                    "text": "Corner, Home FC.",
                }
            },
            {
                "play": {
                    "type": {"text": "Corner Awarded", "type": "corner-awarded"},
                    "period": {"number": 2},
                    "clock": {"value": 4400.0},
                    "team": {"displayName": "Away FC"},
                    "participants": [],
                    "text": "Corner, Away FC.",
                }
            },
            {
                "play": {
                    "type": {"text": "Shot Off Target", "type": "shot-off-target"},
                    "period": {"number": 2},
                    "clock": {"value": 4700.0},
                    "team": {"displayName": "Away FC"},
                    "participants": [{"athlete": {"id": "3", "displayName": "Away Striker"}}],
                    "text": "Away Striker shot from outside the box misses.",
                }
            },
        ],
    }


class BuildLiveStateTests(unittest.TestCase):
    def test_derives_team_names_from_rosters(self) -> None:
        state = build_live_state(_summary(), event_id="e1")
        self.assertEqual(state["home_team"], "Home FC")
        self.assertEqual(state["away_team"], "Away FC")

    def test_full_match_state_counts_everything(self) -> None:
        state = build_live_state(_summary(), event_id="e1")
        self.assertEqual(state["score_home"], 1)
        self.assertEqual(state["score_away"], 1)  # goal---volley must count
        self.assertEqual(state["home_red_cards"], 1)
        self.assertEqual(state["home_corners_so_far"], 1)
        self.assertEqual(state["away_corners_so_far"], 1)
        self.assertEqual(state["home_shots_so_far"], 1)
        self.assertEqual(state["away_shots_so_far"], 1)
        self.assertEqual(state["half"], 2)
        self.assertEqual(state["clock_remaining"], 0.0)

    def test_cutoff_before_second_half_events_excludes_them(self) -> None:
        state = build_live_state(_summary(), event_id="e1", as_of_seconds=1800.0)
        self.assertEqual(state["score_home"], 1)
        self.assertEqual(state["score_away"], 0)  # away goal at 4500s excluded
        self.assertEqual(state["home_red_cards"], 0)  # red card at 4000s excluded
        self.assertEqual(state["half"], 1)
        self.assertAlmostEqual(state["clock_remaining"], 900.0)  # 2700 - 1800

    def test_cutoff_in_second_half_computes_remaining_correctly(self) -> None:
        state = build_live_state(_summary(), event_id="e1", as_of_seconds=4200.0)
        self.assertEqual(state["half"], 2)
        self.assertAlmostEqual(state["clock_remaining"], 5400.0 - 4200.0)
        self.assertEqual(state["home_red_cards"], 1)  # red card at 4000s included
        self.assertEqual(state["score_away"], 0)  # away goal at 4500s still excluded

    def test_player_stats_accumulate_shots_and_goals(self) -> None:
        state = build_live_state(_summary(), event_id="e1")
        striker = state["player_stats"]["1"]
        self.assertEqual(striker["shots_so_far"], 1)
        self.assertEqual(striker["shots_on_target_so_far"], 1)
        self.assertEqual(striker["goals_so_far"], 1)

    def test_player_stats_respect_cutoff(self) -> None:
        state = build_live_state(_summary(), event_id="e1", as_of_seconds=1800.0)
        away_striker = state["player_stats"]["3"]
        self.assertEqual(away_striker["shots_so_far"], 0)  # away shot happens at 4700s


if __name__ == "__main__":
    unittest.main()
