from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.app import create_app


class SoccerBlueprintRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        app = create_app()
        app.config.update(TESTING=True)
        self.client = app.test_client()

    def test_root_redirects_to_default_league_cards(self) -> None:
        response = self.client.get("/soccer", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/soccer/epl/cards", response.headers["Location"])

    def test_league_root_redirects_to_that_leagues_cards(self) -> None:
        response = self.client.get("/soccer/mls", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/soccer/mls/cards", response.headers["Location"])

    def test_cards_route_resolves_league_week_season_and_renders(self) -> None:
        with patch("syndicate.blueprints.soccer.build_cards_page_context", return_value={}) as mocked_context, \
             patch("syndicate.blueprints.soccer.render_template", return_value="PAGE") as mocked_render:
            response = self.client.get("/soccer/epl/cards?week=3&season=2026")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True), "PAGE")
        mocked_context.assert_called_once_with("epl", 3, 2026)
        mocked_render.assert_called_once_with("shared/game_cards_board.html")

    def test_cards_api_route_returns_json(self) -> None:
        with patch("syndicate.blueprints.soccer.build_cards_page_context", return_value={"games": []}), \
             patch("syndicate.blueprints.soccer.build_game_board_api_payload", return_value={"ok": True}):
            response = self.client.get("/soccer/epl/api/cards?week=1&season=2026")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ok": True})

    def test_game_detail_route_threads_game_pk_through(self) -> None:
        with patch("syndicate.blueprints.soccer.build_game_detail_page_context", return_value={}) as mocked_context, \
             patch("syndicate.blueprints.soccer.render_template", return_value="PAGE"):
            response = self.client.get("/soccer/epl/game/12345?week=2&season=2026")
        self.assertEqual(response.status_code, 200)
        mocked_context.assert_called_once_with("epl", 2, 2026, "12345")

    def test_live_lens_route_renders_rank_board(self) -> None:
        with patch("syndicate.blueprints.soccer.build_live_lens_page_context", return_value={}), \
             patch("syndicate.blueprints.soccer.render_template", return_value="PAGE") as mocked_render:
            response = self.client.get("/soccer/mls/live-lens?week=1&season=2026")
        self.assertEqual(response.status_code, 200)
        mocked_render.assert_called_once_with("shared/rank_board.html")

    def test_props_route_forwards_query_filters(self) -> None:
        with patch("syndicate.blueprints.soccer.build_props_page_context", return_value={}) as mocked_context, \
             patch("syndicate.blueprints.soccer.render_template", return_value="PAGE"):
            response = self.client.get("/soccer/epl/props?week=1&season=2026&team=Arsenal&player=Saka&sort=expected_shots")
        self.assertEqual(response.status_code, 200)
        args, kwargs = mocked_context.call_args
        self.assertEqual(args[:3], ("epl", 1, 2026))
        self.assertEqual(kwargs["filters"], {"team": "Arsenal", "player": "Saka", "sort": "expected_shots"})

    def test_team_roster_route_renders(self) -> None:
        with patch("syndicate.blueprints.soccer.build_roster_page_context", return_value={}) as mocked_context, \
             patch("syndicate.blueprints.soccer.render_template", return_value="PAGE"):
            response = self.client.get("/soccer/epl/team/359/roster?season=2026")
        self.assertEqual(response.status_code, 200)
        mocked_context.assert_called_once_with("epl", "359", 2026)

    def test_team_schedule_route_renders(self) -> None:
        with patch("syndicate.blueprints.soccer.build_team_schedule_page_context", return_value={}) as mocked_context, \
             patch("syndicate.blueprints.soccer.render_template", return_value="PAGE"):
            response = self.client.get("/soccer/epl/team/359/schedule?season=2026")
        self.assertEqual(response.status_code, 200)
        mocked_context.assert_called_once_with("epl", "359", 2026)

    def test_hub_route_renders_without_a_league_segment(self) -> None:
        with patch("syndicate.blueprints.soccer.available_weeks", return_value=[]), \
             patch("syndicate.blueprints.soccer.render_template", return_value="PAGE") as mocked_render:
            response = self.client.get("/soccer/hub")
        self.assertEqual(response.status_code, 200)
        mocked_render.assert_called_once()
        self.assertEqual(mocked_render.call_args.args[0], "soccer/hub.html")

    def test_unknown_league_slug_normalizes_to_default_rather_than_404(self) -> None:
        with patch("syndicate.blueprints.soccer.build_cards_page_context", return_value={}) as mocked_context, \
             patch("syndicate.blueprints.soccer.render_template", return_value="PAGE"):
            response = self.client.get("/soccer/not_a_real_league/cards")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mocked_context.call_args.args[0], "epl")


if __name__ == "__main__":
    unittest.main()
