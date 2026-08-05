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


class EspnRequestsUseNoCustomHeadersTests(unittest.TestCase):
    """ESPN's public site API 403s Render's outbound IP for this repo's
    generic browser-spoof User-Agent -- confirmed for 3 other call sites
    (ded23a0d) and, live 2026-08-05, for THIS module's fetch_espn_scoreboard
    too (a 403 for ned.1/por.1's date-ranged query silently blocked
    odds_history for all of soccer, see todo.md's "ROOT CAUSED 2026-08-05"
    entry). A prior probe (81f091b7) had cleared this exact header string
    for a narrower request shape (usa.1, no date-range param) and that
    conclusion did not generalize. No custom header is the only
    confirmed-safe choice; lock it in so a future edit can't quietly
    reintroduce one.
    """

    def test_fetch_espn_scoreboard_sends_no_custom_headers(self) -> None:
        from unittest.mock import MagicMock, patch

        from syndicate.features.soccer.ingestion.espn_lineups import fetch_espn_scoreboard

        fake_response = MagicMock()
        fake_response.json.return_value = {"events": []}
        with patch("syndicate.features.soccer.ingestion.espn_lineups.requests.get", return_value=fake_response) as mocked_get:
            fetch_espn_scoreboard("mls", date_range="20260807-20260807")

        mocked_get.assert_called_once()
        self.assertNotIn("headers", mocked_get.call_args.kwargs)

    def test_fetch_match_summary_sends_no_custom_headers(self) -> None:
        from unittest.mock import MagicMock, patch

        from syndicate.features.soccer.ingestion.espn_lineups import fetch_match_summary

        fake_response = MagicMock()
        fake_response.json.return_value = {}
        with patch("syndicate.features.soccer.ingestion.espn_lineups.requests.get", return_value=fake_response) as mocked_get:
            fetch_match_summary("mls", "123")

        mocked_get.assert_called_once()
        self.assertNotIn("headers", mocked_get.call_args.kwargs)

    def test_fetch_team_roster_sends_no_custom_headers(self) -> None:
        from unittest.mock import MagicMock, patch

        from syndicate.features.soccer.ingestion.espn_teams import fetch_team_roster

        fake_response = MagicMock()
        fake_response.json.return_value = {"athletes": []}
        with patch("syndicate.features.soccer.ingestion.espn_teams.requests.get", return_value=fake_response) as mocked_get:
            fetch_team_roster("mls", "12345")

        mocked_get.assert_called_once()
        self.assertNotIn("headers", mocked_get.call_args.kwargs)
