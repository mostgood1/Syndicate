"""Coverage for the new /nfl/preseason route family in
syndicate/blueprints/nfl.py -- Flask test client against a mocked
context builder, same pattern as test_archives.py's WNBA route tests
(create_app() + TESTING + patch the blueprint-imported function
directly, never touch real disk data for a route-shape test).
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.app import create_app


_FAKE_CONTEXT = {
    "date": "2026 Hall of Fame Weekend",
    "requested_date": "2026 Preseason Week 1",
    "prev_date": "1",
    "next_date": "2",
    "control_action": "/nfl/preseason/cards",
    "controls_prev_href": "/nfl/preseason/cards?season=2026&week=1",
    "controls_next_href": "/nfl/preseason/cards?season=2026&week=2",
    "control_label": "Preseason week",
    "control_type": "number",
    "control_name": "week",
    "control_value": "1",
    "hidden_fields": [{"name": "season", "value": "2026"}],
    "module_links": [],
    "games": [
        {
            "gamePk": "g1",
            "card_variant": "shared_default",
            "away": {"abbr": "CAR", "name": "Carolina Panthers", "logo_url": "https://a.espncdn.com/i/teamlogos/nfl/500/car.png", "primary_color": "#0085ca", "secondary_color": "#000000"},
            "home": {"abbr": "ARI", "name": "Arizona Cardinals", "logo_url": "https://a.espncdn.com/i/teamlogos/nfl/500/ari.png", "primary_color": "#a40227", "secondary_color": "#ffffff"},
            "href": "/nfl/game/g1?season=2026&week=1",
            "href_label": "Open NFL game detail",
            "status": "Hall of Fame Weekend",
            "detail": "SmartSim 2.0 (preseason)",
            "summary": "shrunk toward league-neutral",
            "metrics": [],
            "market_tiles": [],
            "shared_top_play_rows": [],
            "panels": [],
        }
    ],
    "scoreboard_items": [],
    "source_path": "smartsim2_preseason_projections_2026_wk1.csv",
    "source_title": "NFL SmartSim 2.0 preseason projections",
    "empty_state": None,
    "using_sample_data": False,
    "route_path": "/nfl/preseason/cards",
    "intro_title": "NFL Preseason Cards",
    "intro_body": "real preseason schedule",
    "cards_control_links": [],
    "header_stats": [],
    "cards_stylesheet": None,
    "cards_grid_class": "cards-grid",
    "show_source_summary": True,
    "show_intro": True,
    "active_sport_name": "NFL",
    "board_contract": {"schema": "game_board_v1", "sport": "nfl", "module": "preseason_cards", "source_kind": "local_artifact", "surface": "shared_default", "live_lens_integrated": False},
}


class PreseasonRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app()
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()

    def test_preseason_cards_page_renders(self) -> None:
        with patch("syndicate.blueprints.nfl.build_preseason_cards_page_context", return_value=dict(_FAKE_CONTEXT)):
            response = self.client.get("/nfl/preseason/cards?season=2026&week=1")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Arizona Cardinals", response.data)

    def test_preseason_hub_redirects_to_cards(self) -> None:
        with patch("syndicate.blueprints.nfl.build_preseason_cards_page_context", return_value=dict(_FAKE_CONTEXT)):
            response = self.client.get("/nfl/preseason")
        self.assertEqual(response.status_code, 200)

    def test_api_preseason_cards_returns_json_with_real_shape(self) -> None:
        with patch("syndicate.blueprints.nfl.build_preseason_cards_page_context", return_value=dict(_FAKE_CONTEXT)):
            response = self.client.get("/nfl/api/preseason/cards?season=2026&week=1")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(len(payload["games"]), 1)
        self.assertEqual(payload["games"][0]["away"]["abbr"], "CAR")
        self.assertIn("logo_url", payload["games"][0]["away"])

    def test_week_query_param_is_forwarded(self) -> None:
        captured = {}

        def fake_builder(week, *, season=None):
            captured["week"] = week
            captured["season"] = season
            return dict(_FAKE_CONTEXT)

        with patch("syndicate.blueprints.nfl.build_preseason_cards_page_context", side_effect=fake_builder):
            self.client.get("/nfl/preseason/cards?season=2026&week=3")
        self.assertEqual(captured["week"], 3)
        self.assertEqual(captured["season"], 2026)

    def test_invalid_week_falls_back_to_target_week_not_regular_season_default(self) -> None:
        captured = {}

        def fake_builder(week, *, season=None):
            captured["week"] = week
            return dict(_FAKE_CONTEXT)

        with patch("syndicate.blueprints.nfl.build_preseason_cards_page_context", side_effect=fake_builder), patch(
            "syndicate.blueprints.nfl.preseason_target_week", return_value=2
        ):
            self.client.get("/nfl/preseason/cards?season=2026&week=99")
        self.assertEqual(captured["week"], 2)


_FAKE_MARKET_BOARD = {
    "season": 2026,
    "week": 1,
    "available_weeks": [1, 2],
    "games": [
        {
            "gamePk": "g1",
            "matchup": "CAR @ ARI",
            "away_abbr": "CAR",
            "home_abbr": "ARI",
            "away_logo": "https://a.espncdn.com/i/teamlogos/nfl/500/car.png",
            "home_logo": "https://a.espncdn.com/i/teamlogos/nfl/500/ari.png",
            "game_state": "pregame",
            "rows": [
                {"market": "Moneyline", "side": "home", "odds": -125.0, "market_type": "game", "sim_projection": 0.55},
            ],
        }
    ],
    "using_sample_data": False,
    "source_path": "smartsim2_preseason_projections_2026_wk1.csv",
    "route_path": "/nfl/preseason/market-board",
    "uncertainty_note": "Preseason projections are shrunk toward league-neutral.",
}


class PreseasonMarketBoardRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app()
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()

    def test_preseason_market_board_page_renders(self) -> None:
        with patch("syndicate.blueprints.nfl.build_nfl_preseason_market_board", return_value=dict(_FAKE_MARKET_BOARD)):
            response = self.client.get("/nfl/preseason/market-board?season=2026&week=1")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Preseason", response.data)

    def test_preseason_market_board_page_surfaces_uncertainty_note(self) -> None:
        with patch("syndicate.blueprints.nfl.build_nfl_preseason_market_board", return_value=dict(_FAKE_MARKET_BOARD)):
            response = self.client.get("/nfl/preseason/market-board?season=2026&week=1")
        self.assertIn(b"shrunk toward league-neutral", response.data)

    def test_api_preseason_market_board_returns_json_with_real_shape(self) -> None:
        with patch("syndicate.blueprints.nfl.build_nfl_preseason_market_board", return_value=dict(_FAKE_MARKET_BOARD)):
            response = self.client.get("/nfl/api/preseason/market-board?season=2026&week=1")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(len(payload["games"]), 1)
        self.assertEqual(payload["games"][0]["matchup"], "CAR @ ARI")
        self.assertEqual(payload["route_path"], "/nfl/preseason/market-board")

    def test_week_query_param_is_forwarded_to_builder(self) -> None:
        captured = {}

        def fake_builder(season, week):
            captured["season"] = season
            captured["week"] = week
            return dict(_FAKE_MARKET_BOARD)

        with patch("syndicate.blueprints.nfl.build_nfl_preseason_market_board", side_effect=fake_builder):
            self.client.get("/nfl/preseason/market-board?season=2026&week=3")
        self.assertEqual(captured["season"], 2026)
        self.assertEqual(captured["week"], 3)

    def test_invalid_week_falls_back_to_target_week(self) -> None:
        captured = {}

        def fake_builder(season, week):
            captured["week"] = week
            return dict(_FAKE_MARKET_BOARD)

        with patch("syndicate.blueprints.nfl.build_nfl_preseason_market_board", side_effect=fake_builder), patch(
            "syndicate.blueprints.nfl.preseason_target_week", return_value=2
        ):
            self.client.get("/nfl/preseason/market-board?season=2026&week=99")
        self.assertEqual(captured["week"], 2)


if __name__ == "__main__":
    unittest.main()
