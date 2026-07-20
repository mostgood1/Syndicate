from __future__ import annotations

import unittest

from syndicate.features.soccer.ingestion.espn_lineups import LEAGUE_ESPN_SLUGS
from syndicate.features.soccer.ingestion.espn_lineups import extract_match_player_rows


def _summary_fixture() -> dict:
    return {
        "rosters": [
            {
                "homeAway": "home",
                "team": {"displayName": "LA Galaxy"},
                "roster": [
                    {
                        "starter": True,
                        "subbedIn": False,
                        "athlete": {"id": "1", "displayName": "Home Keeper"},
                        "position": {"name": "Goalkeeper"},
                        "stats": [
                            {"name": "shotsFaced", "value": 5.0},
                            {"name": "goalsConceded", "value": 1.0},
                        ],
                    },
                    {
                        "starter": True,
                        "subbedIn": False,
                        "athlete": {"id": "2", "displayName": "Home Striker"},
                        "position": {"name": "Forward"},
                        "stats": [
                            {"name": "totalShots", "value": 4.0},
                            {"name": "shotsOnTarget", "value": 2.0},
                            {"name": "totalGoals", "value": 1.0},
                            {"name": "goalAssists", "value": 0.0},
                        ],
                    },
                    {
                        "starter": False,
                        "subbedIn": True,
                        "athlete": {"id": "3", "displayName": "Home Sub"},
                        "position": {"name": "Midfielder"},
                        "stats": [
                            {"name": "totalShots", "value": 1.0},
                            {"name": "shotsOnTarget", "value": 0.0},
                            {"name": "totalGoals", "value": 0.0},
                            {"name": "goalAssists", "value": 1.0},
                        ],
                    },
                ],
            },
            {
                "homeAway": "away",
                "team": {"displayName": "LAFC"},
                "roster": [
                    {
                        "starter": True,
                        "subbedIn": False,
                        "athlete": {"id": "4", "displayName": "Away Winger"},
                        "position": {"name": "Forward"},
                        "stats": [
                            {"name": "totalShots", "value": 3.0},
                            {"name": "shotsOnTarget", "value": 1.0},
                            {"name": "totalGoals", "value": 0.0},
                            {"name": "goalAssists", "value": 0.0},
                        ],
                    },
                ],
            },
        ]
    }


class EspnLineupsTests(unittest.TestCase):
    def test_league_slugs_cover_engine_leagues(self) -> None:
        for league in ("epl", "la_liga", "bundesliga", "serie_a", "ligue_1", "mls"):
            self.assertIn(league, LEAGUE_ESPN_SLUGS)

    def test_extract_match_player_rows_splits_sides_and_flags_starters(self) -> None:
        rows = extract_match_player_rows(_summary_fixture(), event_id="evt1")

        self.assertEqual(len(rows), 4)
        by_name = {row["player_name"]: row for row in rows}

        striker = by_name["Home Striker"]
        self.assertEqual(striker["team"], "LA Galaxy")
        self.assertEqual(striker["side"], "home")
        self.assertTrue(striker["starter"])
        self.assertFalse(striker["is_goalkeeper"])
        self.assertEqual(striker["total_shots"], 4.0)
        self.assertEqual(striker["shots_on_target"], 2.0)
        self.assertEqual(striker["total_goals"], 1.0)

        sub = by_name["Home Sub"]
        self.assertFalse(sub["starter"])
        self.assertTrue(sub["subbed_in"])
        self.assertEqual(sub["goal_assists"], 1.0)

        keeper = by_name["Home Keeper"]
        self.assertTrue(keeper["is_goalkeeper"])
        # Keeper stat block has no totalShots entry -- missing stats default
        # to 0.0 rather than raising.
        self.assertEqual(keeper["total_shots"], 0.0)

        away = by_name["Away Winger"]
        self.assertEqual(away["side"], "away")
        self.assertEqual(away["team"], "LAFC")

    def test_extract_match_player_rows_handles_missing_rosters(self) -> None:
        self.assertEqual(extract_match_player_rows({}, event_id="evt2"), [])


if __name__ == "__main__":
    unittest.main()
