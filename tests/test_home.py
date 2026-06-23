from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.app import create_app
from syndicate.blueprints.home import _home_prop_hero_metrics
from syndicate.blueprints.home import _build_sport_overview
from syndicate.blueprints.home import _sport_availability_reason


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
                        "availability_reason": "NBA props are active on this slate.",
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
                        "availability_reason": "NBA props are active on this slate.",
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
        self.assertIn("NBA props are active on this slate.", html)

    def test_home_page_defaults_to_current_local_date_and_active_payload(self) -> None:
        payload = {
            "selected_date": "2026-06-21",
            "sports": [
                {
                    "slug": "nba",
                    "name": "NBA",
                    "home_anchor": "home-sport-nba",
                    "data_health": "healthy",
                    "freshness_label": "Live · Polled now",
                    "games_count": 1,
                    "props_count": 2,
                    "overview_stats": [],
                    "home_rails": {
                        "compact": {"title": "Compact game rail", "items": [], "links": [], "empty_summary": ""},
                        "pregame": {"title": "Pregame props", "items": [], "links": [], "empty_summary": ""},
                        "live": {"title": "Top Live Props", "items": [], "links": [], "empty_summary": ""},
                    },
                    "game_bar": {"opportunity_tags": []},
                    "props_bar": {"opportunity_tags": []},
                }
            ],
            "dashboard": {"summary_cards": [], "live_watch": [], "top_props": [], "top_game_bets": [], "sport_summaries": []},
            "command_center": {"schema": "home_command_center_v1"},
            "html": "<section />",
            "polled_at": 123.0,
        }

        with patch("syndicate.blueprints.home.central_today_iso", return_value="2026-06-21"):
            with patch("syndicate.blueprints.home._home_payload", return_value=payload) as mocked_payload:
                with patch("syndicate.blueprints.home.render_template", return_value="ok") as mocked_render:
                    response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True), "ok")
        mocked_payload.assert_called_once_with(selected_date="2026-06-21", force_refresh=True)
        self.assertEqual(mocked_render.call_args.kwargs["selected_home_date"], "2026-06-21")
        self.assertEqual(len(mocked_render.call_args.kwargs["sports"]), 1)
        self.assertEqual(mocked_render.call_args.kwargs["sports"][0]["name"], "NBA")
        self.assertTrue(mocked_render.call_args.kwargs["show_command_center"])

    def test_sport_availability_reason_explains_missing_mlb_and_wnba_lanes(self) -> None:
        mlb_reason = _sport_availability_reason(
            {"slug": "mlb", "name": "MLB"},
            active_today=True,
            games_count=0,
            props_count=1,
            mlb_top_prop_counts={"pitcher_count": 4, "hitter_count": 0},
        )
        wnba_reason = _sport_availability_reason(
            {"slug": "wnba", "name": "WNBA"},
            active_today=True,
            games_count=0,
            props_count=0,
        )

        self.assertIn("hitter top-props rows were not present", mlb_reason["props_availability_reason"] or "")
        self.assertIn("live-state feed returned no event IDs", wnba_reason["game_availability_reason"] or "")

    def test_wnba_overview_does_not_warn_when_games_exist_but_props_do_not(self) -> None:
        sport = {"slug": "wnba", "name": "WNBA", "primary_label": "Open WNBA cards"}
        with patch("syndicate.blueprints.home.central_today_iso", return_value="2026-06-23"), patch(
            "syndicate.blueprints.home.build_wnba_module_links",
            return_value=[{"label": "Cards", "href": "/wnba/cards?date=2026-06-23"}],
        ), patch(
            "syndicate.blueprints.home._load_home_game_items",
            return_value=([{"matchup": "TOR @ ATL", "detail": "Scheduled", "status_badge": "Scheduled", "away_label": "TOR", "home_label": "ATL", "away_score": None, "home_score": None, "has_scores": False, "score_kind": None, "is_projected_score": False, "summary": "", "signals": [], "market_chips": [], "href": "/wnba/cards?date=2026-06-23", "href_label": "Open Cards"}], 1),
        ), patch(
            "syndicate.blueprints.home._load_home_games",
            return_value=[{"event_id": "evt-1", "away": "TOR", "home": "ATL", "status": "Scheduled", "detail": "Scheduled", "shared_is_live": False}],
        ), patch(
            "syndicate.blueprints.home._load_home_prop_items",
            return_value=[],
        ), patch(
            "syndicate.blueprints.home._choose_game_bar",
            return_value={"items": []},
        ), patch(
            "syndicate.blueprints.home._choose_props_bar",
            return_value={"items": []},
        ), patch("syndicate.blueprints.home._LOGGER.warning") as warning_mock:
            overview = _build_sport_overview(sport, "2026-06-23", force_refresh=True)

        self.assertEqual(overview["games_count"], 1)
        self.assertEqual(overview["data_health"], "partial")
        self.assertEqual(warning_mock.call_count, 0)

    def test_home_prop_hero_metrics_prefers_explicit_sim_projection(self) -> None:
        live_box, sim_box = _home_prop_hero_metrics(
            {
                "market_display": "Hits",
                "actual": "1",
                "sim_projection": "2",
                "projected": "9",
                "live_projection": "7",
                "line": "0.5",
            }
        )

        self.assertEqual(live_box, "1 H")
        self.assertEqual(sim_box, "2 H")

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
