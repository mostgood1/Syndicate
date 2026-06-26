from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.app import create_app
from syndicate.blueprints.home import _build_game_watch_row
from syndicate.blueprints.home import _home_prop_hero_metrics
from syndicate.blueprints.home import _build_sport_overview
from syndicate.blueprints.home import _build_prop_dashboard_row
from syndicate.blueprints.home import _load_home_pregame_prop_items
from syndicate.blueprints.home import build_home_overview
from syndicate.blueprints.home import get_active_games
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

    def test_get_active_games_only_keeps_scheduled_and_live_rows(self) -> None:
        games = [
            {"gamePk": "1", "status": {"detailed": "Scheduled"}},
            {"gamePk": "2", "status": {"detailed": "Live"}},
            {"gamePk": "3", "status": {"detailed": "Final"}},
        ]

        active_games = get_active_games(games)

        self.assertEqual([game["gamePk"] for game in active_games], ["1", "2"])

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

    def test_build_home_overview_keeps_only_hydrated_sports(self) -> None:
        sports = [
            {"slug": "nba", "name": "NBA"},
            {"slug": "wnba", "name": "WNBA"},
        ]

        with patch(
            "syndicate.blueprints.home._build_sport_overview",
            side_effect=[
                {"slug": "nba", "show_on_home": True, "active_game_count": 1, "hydrated_game_count": 1},
                {"slug": "wnba", "show_on_home": False, "active_game_count": 1, "hydrated_game_count": 0},
            ],
        ):
            overview = build_home_overview(sports, selected_date="2026-06-23", force_refresh=True)

        self.assertEqual([sport["slug"] for sport in overview], ["nba"])

    def test_build_home_overview_filters_inactive_sports(self) -> None:
        app = create_app()
        app.testing = True
        app.config["SYNDICATE_ACTIVE_SPORTS"] = ["mlb", "wnba"]

        sports = [
            {"slug": "mlb", "name": "MLB"},
            {"slug": "nhl", "name": "NHL"},
        ]

        with app.app_context():
            with patch(
                "syndicate.blueprints.home._build_sport_overview",
                return_value={"slug": "mlb", "show_on_home": True, "active_game_count": 1, "hydrated_game_count": 1},
            ) as mocked_build:
                overview = build_home_overview(sports, selected_date="2026-06-23", force_refresh=True)

        mocked_build.assert_called_once()
        self.assertEqual([sport["slug"] for sport in overview], ["mlb"])

    def test_build_sport_overview_keeps_today_games_when_props_are_missing(self) -> None:
        app = create_app()
        app.testing = True

        sport = {"slug": "mlb", "name": "MLB", "primary_label": "Open MLB cards"}
        games = [{"gamePk": 1, "status": {"status": "Scheduled"}}]
        game_items = [{"gamePk": 1, "title": "MLB game card"}]

        with app.app_context():
            with patch("syndicate.blueprints.home.central_today_iso", return_value="2026-06-26"), patch(
                "syndicate.blueprints.home._active_sport_slugs",
                return_value=["mlb"],
            ), patch(
                "syndicate.blueprints.home.build_mlb_module_links",
                return_value=[],
            ), patch(
                "syndicate.blueprints.home._load_home_games",
                return_value=games,
            ), patch(
                "syndicate.blueprints.home._load_home_game_items",
                return_value=(game_items, len(game_items)),
            ), patch(
                "syndicate.blueprints.home._load_home_prop_items",
                return_value=[],
            ), patch(
                "syndicate.blueprints.home._finalize_home_prop_rows",
                side_effect=lambda rows, **_: rows,
            ), patch(
                "syndicate.blueprints.home.get_active_games",
                return_value=games,
            ), patch(
                "syndicate.blueprints.home._game_identity_set",
                side_effect=lambda items: {str((item or {}).get("gamePk") or "") for item in items if str((item or {}).get("gamePk") or "")},
            ), patch(
                "syndicate.blueprints.home._game_identifier",
                side_effect=lambda item: str((item or {}).get("gamePk") or "") or None,
            ), patch(
                "syndicate.blueprints.home._choose_game_bar",
                side_effect=lambda links, **kwargs: {"items": list(game_items), "title": "Game cards"},
            ), patch(
                "syndicate.blueprints.home._choose_props_bar",
                side_effect=lambda links, **kwargs: {"items": [], "title": "Props"},
            ), patch(
                "syndicate.blueprints.home._dashboard_prop_count",
                return_value=0,
            ), patch(
                "syndicate.blueprints.home._game_bet_candidates_from_game",
                return_value=[{"sport_slug": "mlb", "pick": "MLB game bet", "score": 1.0}],
            ), patch(
                "syndicate.blueprints.home._build_game_watch_row",
                side_effect=lambda sport_obj, item: {"sport_slug": "mlb", "score": 1.0, "pick": "MLB game bet"},
            ), patch(
                "syndicate.blueprints.home._build_prop_dashboard_row",
                side_effect=lambda sport_obj, item, default_surface: {"sport_slug": "mlb", "score": 1.0, "name": "MLB prop"},
            ), patch(
                "syndicate.blueprints.home._mlb_top_prop_lane_counts",
                return_value={"pitcher_count": 0, "hitter_count": 0},
            ):
                overview = _build_sport_overview(sport, "2026-06-26", force_refresh=True)

        self.assertEqual(overview["games_count"], 1)
        self.assertEqual(overview["active_game_count"], 1)
        self.assertTrue(overview["show_on_home"])
        self.assertEqual(len(overview["dashboard_games"]), 1)

    def test_load_home_pregame_prop_items_falls_back_to_compact_game_props(self) -> None:
        home_games = [
            {
                "gamePk": 1,
                "away": {"abbr": "AWY", "name": "Away"},
                "home": {"abbr": "HME", "name": "Home"},
                "shared_prop_rows": [
                    {
                        "name": "Player points",
                        "detail": "Compact fallback",
                        "value": "O 20.5",
                        "pick": "Over",
                        "market": "Points",
                    }
                ],
            }
        ]

        with patch(
            "syndicate.blueprints.home._pregame_prop_rows_from_betting_card",
            return_value=[],
        ), patch(
            "syndicate.blueprints.home._prop_rows_from_props_recommendations_csv",
            return_value=[],
        ):
            rows = _load_home_pregame_prop_items(
                "ncaab",
                context_label="2026-06-26",
                home_games=home_games,
                is_active_today=True,
            )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Player points")
        self.assertEqual(rows[0]["matchup"], "AWY @ HME")

    def test_load_home_pregame_prop_items_uses_mlb_top_props_when_betting_card_is_empty(self) -> None:
        home_games = [{"gamePk": 1, "away": {"abbr": "AWY"}, "home": {"abbr": "HME"}}]

        with patch(
            "syndicate.blueprints.home._pregame_prop_rows_from_betting_card",
            return_value=[],
        ), patch(
            "syndicate.blueprints.home._load_mlb_home_top_prop_items",
            return_value=[
                {
                    "game_pk": 1,
                    "matchup": "Away @ Home",
                    "name": "MLB top prop",
                    "value": "+120",
                    "pick": "Over",
                }
            ],
        ):
            rows = _load_home_pregame_prop_items(
                "mlb",
                context_label="2026-06-26",
                home_games=home_games,
                is_active_today=True,
            )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "MLB top prop")

    def test_live_rows_require_live_odds_backing(self) -> None:
        game = {
            "game_id": "game-1",
            "status_badge": "Live",
            "detail": "Q4 07:12",
            "signals": ["Momentum +12.3%"],
            "market_chips": ["Live"],
        }
        prop = {
            "game_id": "game-1",
            "heading": "Live props",
            "detail": "In-game prop lane",
            "is_live": True,
        }

        game_row = _build_game_watch_row({"slug": "mlb", "name": "MLB"}, game, live_odds_game_ids=set())
        prop_row = _build_prop_dashboard_row({"slug": "mlb", "name": "MLB"}, prop, default_surface="Live props", live_odds_game_ids=set())
        game_row_live = _build_game_watch_row({"slug": "mlb", "name": "MLB"}, game, live_odds_game_ids={"game-1"})
        prop_row_live = _build_prop_dashboard_row({"slug": "mlb", "name": "MLB"}, prop, default_surface="Live props", live_odds_game_ids={"game-1"})

        self.assertFalse(game_row["is_live"])
        self.assertFalse(prop_row["is_live"])
        self.assertTrue(game_row_live["is_live"])
        self.assertTrue(prop_row_live["is_live"])

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
