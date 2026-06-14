from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.app import create_app


class HomePageCommandCenterTests(unittest.TestCase):
    def setUp(self) -> None:
        app = create_app()
        app.testing = True
        self.client = app.test_client()

    def test_home_page_renders_daily_command_center(self) -> None:
        payload = {
            "selected_date": "2026-06-13",
            "sports": [],
            "dashboard": {
                "summary_cards": [
                    {"label": "Board date", "value": "2026-06-13", "meta": "Polled now"},
                    {"label": "Live sports", "value": "2", "meta": "2 game reads surfaced"},
                ],
                "live_watch": [
                    {
                        "sport": "NBA",
                        "matchup": "BOS at NYK",
                        "status": "Live",
                        "detail": "Q4 07:12",
                        "signal": "Momentum +12.3%",
                        "summary": "In-progress board read.",
                        "href": "/nba/live-lens",
                        "href_label": "Open board",
                        "is_live": True,
                    }
                ],
                "top_props": [
                    {
                        "sport": "NBA",
                        "surface": "Pregame props",
                        "market": "Points",
                        "name": "Jayson Tatum Over 28.5",
                        "matchup": "BOS at NYK",
                        "pick": "Over 28.5",
                        "signal": "Sim edge +50.5%",
                        "detail": "Projection is clearing the number.",
                        "href": "/nba/prop-ladders",
                        "href_label": "Open matchup",
                    }
                ],
                "top_game_bets": [
                    {
                        "sport": "MLB",
                        "market": "Moneyline",
                        "pick": "Home ML",
                        "matchup": "NYY at BOS",
                        "status": "Tracked",
                        "signal": "Edge +6.8%",
                        "detail": "Best side on the board.",
                        "href": "/mlb/game-center",
                        "href_label": "Open board",
                    }
                ],
                "sport_summaries": [
                    {
                        "sport": "NBA",
                        "sport_slug": "nba",
                        "context": "2026-06-13",
                        "games": 1,
                        "props": 1,
                        "top_game_bet": "Home ML",
                        "top_prop": "Jayson Tatum Over 28.5",
                        "best_signal": "Momentum +12.3%",
                        "status": "Live",
                        "hub_href": "/nba",
                    }
                ],
            },
            "command_center": {
                "schema": "home_command_center_v1",
                "headline": "Syndicate main page",
                "lede": "One hub for the day across all sports.",
                "shortcuts": [
                    {"label": "Live games", "href": "#home-live-lane"},
                    {"label": "Pregame props", "href": "#home-pregame-lane"},
                ],
                "summary_cards": [
                    {"label": "Board date", "value": "2026-06-13", "meta": "Polled now"},
                ],
                "live_watch": [
                    {
                        "sport": "NBA",
                        "matchup": "BOS at NYK",
                        "status": "Live",
                        "detail": "Q4 07:12",
                        "signal": "Momentum +12.3%",
                        "summary": "In-progress board read.",
                        "href": "/nba/live-lens",
                        "href_label": "Open board",
                        "is_live": True,
                    }
                ],
                "top_props": [
                    {
                        "sport": "NBA",
                        "surface": "Pregame props",
                        "market": "Points",
                        "name": "Jayson Tatum Over 28.5",
                        "matchup": "BOS at NYK",
                        "pick": "Over 28.5",
                        "signal": "Sim edge +50.5%",
                        "detail": "Projection is clearing the number.",
                        "href": "/nba/prop-ladders",
                        "href_label": "Open matchup",
                    }
                ],
                "top_game_bets": [
                    {
                        "sport": "MLB",
                        "market": "Moneyline",
                        "pick": "Home ML",
                        "matchup": "NYY at BOS",
                        "status": "Tracked",
                        "signal": "Edge +6.8%",
                        "detail": "Best side on the board.",
                        "href": "/mlb/game-center",
                        "href_label": "Open board",
                    }
                ],
                "sport_summaries": [
                    {
                        "sport": "NBA",
                        "sport_slug": "nba",
                        "context": "2026-06-13",
                        "games": 1,
                        "props": 1,
                        "top_game_bet": "Home ML",
                        "top_prop": "Jayson Tatum Over 28.5",
                        "best_signal": "Momentum +12.3%",
                        "status": "Live",
                        "hub_href": "/nba",
                    }
                ],
            },
        }

        with patch("syndicate.blueprints.home._home_payload", return_value=payload):
            response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Daily command center", html)
        self.assertIn("Syndicate main page", html)
        self.assertIn("Selected slate: 2026-06-13", html)
        self.assertIn("Contract: home_command_center_v1", html)
        self.assertIn("Live game updates", html)
        self.assertIn("Pregame props", html)
        self.assertIn("Game bets", html)
        self.assertIn("Open sport hub", html)

    def test_api_home_exposes_command_center_contract(self) -> None:
        payload = {
            "selected_date": "2026-06-13",
            "sports": [],
            "dashboard": {"summary_cards": [], "live_watch": [], "top_props": [], "top_game_bets": [], "sport_summaries": []},
            "command_center": {"schema": "home_command_center_v1", "headline": "Syndicate main page", "lede": "One hub.", "shortcuts": [], "summary_cards": [], "live_watch": [], "top_props": [], "top_game_bets": [], "sport_summaries": []},
            "html": "<section />",
            "polled_at": 123.0,
        }

        with patch("syndicate.blueprints.home._home_payload", return_value=payload):
            response = self.client.get("/api/home?date=2026-06-13")

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["command_center"]["schema"], "home_command_center_v1")


if __name__ == "__main__":
    unittest.main()
