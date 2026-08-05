from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import syndicate.blueprints.home as home_module
from syndicate.app import create_app
from syndicate.blueprints.home import _build_game_watch_row
from syndicate.blueprints.home import _home_prop_hero_metrics
from syndicate.blueprints.home import _build_sport_overview
from syndicate.blueprints.home import _build_prop_dashboard_row
from syndicate.blueprints.home import _load_home_pregame_prop_items
from syndicate.blueprints.home import build_home_overview
from syndicate.blueprints.home import get_active_games
from syndicate.blueprints.home import _sport_availability_reason
from syndicate.blueprints.home import _prefer_today_or_latest
from syndicate.blueprints.home import _game_bet_candidates_from_game
from syndicate.blueprints.home import _mlb_game_market_recommendation_rows
from syndicate.blueprints.home import _ncaaf_game_market_recommendation_rows
from syndicate.blueprints.home import _nfl_game_market_recommendation_rows
from syndicate.blueprints.home import _NCAAFDataProvider
from syndicate.blueprints.home import _NFLDataProvider
from syndicate.features.shared.sport_data_provider import SportContext
from syndicate.blueprints.home import _game_status_state
from syndicate.blueprints.home import _prop_item_from_rank_card
from syndicate.blueprints.home import _is_game_level_rank_card_market
from syndicate.blueprints.home import _pregame_prop_rows_from_betting_card
from syndicate.blueprints.home import _backfill_prop_row_game_id
from syndicate.blueprints.home import _team_for_side_hint
from syndicate.blueprints.home import _compact_prop_rows
from syndicate.blueprints.home import _game_sim_vs_line_reasoning
from syndicate.blueprints.home import _game_bet_narrative
from syndicate.blueprints.home import _game_bet_narrative_subject
from syndicate.blueprints.home import _game_identifier
from syndicate.blueprints.home import _board_candidate_rows


class HomePageCommandCenterTests(unittest.TestCase):
    def setUp(self) -> None:
        app = create_app()
        app.testing = True
        self.client = app.test_client()

    def test_home_page_now_delegates_to_the_curated_betting_board(self) -> None:
        # Nav/IA change 2026-07-24: "/" used to render home.html's per-sport
        # dashboard directly (see the light_sports/render_template-kwargs
        # assertions this test used to make) -- it now delegates straight
        # to intelligence_home() so the curated Betting Board (Layer 2) is
        # the homepage. The old dashboard-building helpers below
        # (_build_light_home_sports, _build_home_dashboard, etc.) are
        # deliberately left in place, just unreachable from this route.
        with patch("syndicate.blueprints.intelligence.intelligence_home", return_value="ok") as mocked_intelligence_home:
            response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True), "ok")
        mocked_intelligence_home.assert_called_once()

    def test_market_board_hub_lists_every_sport_with_a_layer1_board(self) -> None:
        response = self.client.get("/market-board")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        for slug in ("mlb", "nba", "wnba"):
            self.assertIn(f"/{slug}/market-board", html)

    def test_market_board_hub_carries_date_query_param_into_tile_links(self) -> None:
        response = self.client.get("/market-board?date=2026-07-23")
        html = response.get_data(as_text=True)
        self.assertIn("/mlb/market-board?date=2026-07-23", html)

    def test_market_board_hub_includes_nfl_preseason_tile(self) -> None:
        # Item 5: this tile was previously orphaned -- /nfl/preseason/market-board
        # was a real, working route with no nav link into it anywhere.
        response = self.client.get("/market-board")
        html = response.get_data(as_text=True)
        self.assertIn("/nfl/preseason/market-board", html)
        self.assertIn("NFL Preseason", html)

    def test_home_payload_uses_light_shell_on_render_web_dyno(self) -> None:
        from syndicate.blueprints import home as home_module

        light_sports = [
            {
                "slug": "wnba",
                "name": "WNBA",
                "home_anchor": "wnba-home",
                "data_health": "partial",
                "freshness_label": "Stored slate",
                "games_count": "—",
                "props_count": "—",
                "overview_stats": [],
                "home_rails": {
                    "compact": {"title": "", "items": [], "links": [], "empty_summary": "No game rows were surfaced for this slate."},
                    "pregame": {"title": "", "items": [], "links": [], "empty_summary": "No prop rows were surfaced for this slate."},
                    "live": {"title": "", "items": [], "links": [], "empty_summary": "No live rows were surfaced for this slate.", "links": []},
                },
                "game_bar": {"opportunity_tags": []},
                "props_bar": {"opportunity_tags": []},
                "feature_links": [],
            }
        ]

        with patch("syndicate.blueprints.home._render_web_dyno", return_value=True), patch(
            "syndicate.blueprints.home._build_light_home_sports",
            return_value=light_sports,
        ) as mocked_light, patch(
            "syndicate.blueprints.home.build_home_overview",
            side_effect=AssertionError("home overview should not be built on render web dynos"),
        ), patch(
            "syndicate.blueprints.home._build_home_dashboard",
            return_value={"summary_cards": [], "live_watch": [], "top_props": [], "top_game_bets": [], "sport_summaries": []},
        ) as mocked_dashboard, patch(
            "syndicate.blueprints.home._build_home_command_center_contract",
            return_value={"schema": "home_command_center_v1", "headline": "Syndicate main page", "lede": "One hub.", "shortcuts": [], "summary_cards": [], "live_watch": [], "top_props": [], "top_game_bets": [], "sport_summaries": []},
        ) as mocked_command_center, patch(
            "syndicate.blueprints.home.render_template",
            return_value="ok",
        ):
            payload = home_module._home_payload(selected_date="2026-06-21", force_refresh=True)

        self.assertEqual(payload["sports"], light_sports)
        mocked_light.assert_called_once_with("2026-06-21")
        mocked_dashboard.assert_called_once()
        mocked_command_center.assert_called_once()

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

        with self.client.application.app_context():
            self.client.application.config["SYNDICATE_ACTIVE_SPORTS"] = ["nba", "wnba"]
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

    def test_build_sport_overview_suppresses_wnba_warning_on_no_game_day(self) -> None:
        app = create_app()
        app.testing = True

        sport = {"slug": "wnba", "name": "WNBA", "primary_label": "Open WNBA cards"}

        with app.app_context():
            with patch("syndicate.blueprints.home.central_today_iso", return_value="2026-06-29"), patch(
                "syndicate.blueprints.home.wnba_available_dates",
                return_value=["2026-06-29"],
            ), patch(
                "syndicate.blueprints.home.wnba_has_games_for_date",
                return_value=False,
            ), patch(
                "syndicate.blueprints.home.build_wnba_module_links",
                return_value=[],
            ), patch(
                "syndicate.blueprints.home._prefer_today_or_latest",
                return_value="2026-06-29",
            ), patch(
                "syndicate.blueprints.home._load_home_game_items",
                side_effect=AssertionError("WNBA home should not load game items directly"),
            ), patch(
                "syndicate.blueprints.home._load_home_games",
                side_effect=AssertionError("WNBA home should not load games directly"),
            ), patch(
                "syndicate.blueprints.home._load_home_prop_items",
                side_effect=AssertionError("WNBA home should not load prop items directly"),
            ), patch(
                "syndicate.blueprints.home._finalize_home_prop_rows",
                side_effect=AssertionError("WNBA home should not finalize prop rows directly"),
            ), patch(
                "syndicate.blueprints.home._link_lookup_any",
                return_value=(None, None),
            ), patch(
                "syndicate.blueprints.home._link_lookup",
                return_value=None,
            ), patch(
                "syndicate.blueprints.home._secondary_links",
                return_value=[],
            ), patch(
                "syndicate.blueprints.home._rail_links",
                return_value=[],
            ), patch(
                "syndicate.blueprints.home._LOGGER.warning",
            ) as mocked_warning:
                overview = _build_sport_overview(sport, "2026-06-29", force_refresh=True)

        mocked_warning.assert_not_called()
        self.assertEqual(overview.get("data_warnings"), [])
        self.assertFalse(overview.get("show_on_home"))

    def test_build_sport_overview_treats_missing_wnba_schedule_probe_as_no_games_when_no_local_dates(self) -> None:
        app = create_app()
        app.testing = True

        sport = {"slug": "wnba", "name": "WNBA", "primary_label": "Open WNBA cards"}

        with app.app_context():
            with patch("syndicate.blueprints.home.central_today_iso", return_value="2026-07-03"), patch(
                "syndicate.blueprints.home.wnba_available_dates",
                return_value=[],
            ), patch(
                "syndicate.blueprints.home.wnba_has_games_for_date",
                return_value=None,
            ), patch(
                "syndicate.blueprints.home.build_wnba_module_links",
                return_value=[],
            ), patch(
                "syndicate.blueprints.home._prefer_today_or_latest",
                return_value="2026-07-03",
            ), patch(
                "syndicate.blueprints.home._load_home_game_items",
                side_effect=AssertionError("WNBA home should not load game items directly"),
            ), patch(
                "syndicate.blueprints.home._load_home_games",
                side_effect=AssertionError("WNBA home should not load games directly"),
            ), patch(
                "syndicate.blueprints.home._load_home_prop_items",
                side_effect=AssertionError("WNBA home should not load prop items directly"),
            ), patch(
                "syndicate.blueprints.home._finalize_home_prop_rows",
                side_effect=AssertionError("WNBA home should not finalize prop rows directly"),
            ), patch(
                "syndicate.blueprints.home._link_lookup_any",
                return_value=(None, None),
            ), patch(
                "syndicate.blueprints.home._link_lookup",
                return_value=None,
            ), patch(
                "syndicate.blueprints.home._secondary_links",
                return_value=[],
            ), patch(
                "syndicate.blueprints.home._rail_links",
                return_value=[],
            ), patch(
                "syndicate.blueprints.home._LOGGER.warning",
            ) as mocked_warning:
                overview = _build_sport_overview(sport, "2026-07-03", force_refresh=True)

        mocked_warning.assert_not_called()
        self.assertEqual(overview.get("data_warnings"), [])
        self.assertFalse(overview.get("show_on_home"))

    def test_prefer_today_or_latest_uses_latest_available_date(self) -> None:
        self.assertEqual(
            _prefer_today_or_latest(["2026-06-26", "2026-06-24"], "2026-06-27"),
            "2026-06-26",
        )
        self.assertEqual(
            _prefer_today_or_latest(["2026-06-26", "2026-06-24"], "2026-06-27", preserve_requested=True),
            "2026-06-27",
        )

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

    def test_is_game_level_rank_card_market_classifies_team_bets(self) -> None:
        # ats/total/moneyline are team-level game bets, already correctly
        # represented via game_market_recommendations -- these must be
        # recognized so _pregame_prop_rows_from_betting_card can drop them
        # instead of duplicating them as fake "Betting Card" props.
        for market in ("ats", "total", "moneyline", "spread", "Total", "ATS"):
            self.assertTrue(_is_game_level_rank_card_market(market), market)
        # Real player-prop stat codes and an absent market must pass through
        # unaffected -- this filter only targets team-level game bets.
        for market in ("pts", "reb", "ast", "pra", "", None):
            self.assertFalse(_is_game_level_rank_card_market(market), market)

    def test_pregame_prop_rows_from_betting_card_drops_game_level_cards(self) -> None:
        # Confirmed live 2026-07-27: WNBA's rank_cards list mixes real
        # player props with team-level ats/total picks that are already
        # correctly represented via game_market_recommendations. Before
        # market-aware filtering, every card -- both kinds -- was forced
        # through as a "prop" labeled "Betting Card", duplicating each
        # game-level pick on the board with the team/line text standing in
        # for a player name.
        cards = [
            {"title": "Minnesota Lynx -15.5", "eyebrow": "MIN", "meta": "TOR @ MIN", "market": "ats", "metrics": []},
            {"title": "Under 184.0", "eyebrow": "Total", "meta": "TOR @ MIN", "market": "total", "metrics": []},
            {"title": "Gabby Williams OVER 1.5", "eyebrow": "MIN", "meta": "TOR @ MIN", "market": "pts", "metrics": []},
        ]
        with patch(
            "syndicate.blueprints.home._betting_card_rank_cards",
            return_value=(cards, "/wnba/season/2026/betting-card", "2026-07-27"),
        ):
            rows = _pregame_prop_rows_from_betting_card("wnba", context_label="2026-07-27")

        names = [row["name"] for row in rows]
        self.assertNotIn("Minnesota Lynx -15.5", names)
        self.assertNotIn("Under 184.0", names)
        self.assertIn("Gabby Williams OVER 1.5", names)

    def test_backfill_prop_row_game_id_matches_by_team_abbr(self) -> None:
        # #164: confirmed live -- WNBA's rank-card-sourced props
        # (_prop_item_from_rank_card) carry no game_id/gamePk/event_id at
        # all, only away_label/home_label text ("NYL"/"LVA"). Downstream,
        # _build_sport_overview's hydration step drops any pregame_prop_item
        # whose _game_identifier() doesn't match a real game id -- with no
        # id at all, every real WNBA prop for today's slate was silently
        # dropped even though the underlying picks were real.
        rows = [{"name": "Breanna Stewart OVER 21.5 PTS", "away_label": "NYL", "home_label": "LVA", "matchup": "NYL @ LVA"}]
        home_games = [{"gamePk": "401857900", "away": {"abbr": "NYL"}, "home": {"abbr": "LVA"}}]

        result = _backfill_prop_row_game_id(rows, home_games)

        self.assertEqual(result[0]["game_id"], "401857900")
        self.assertEqual(result[0]["gamePk"], "401857900")
        self.assertEqual(result[0]["event_id"], "401857900")

    def test_backfill_prop_row_game_id_leaves_existing_id_untouched(self) -> None:
        rows = [{"name": "Real prop", "game_id": "existing-id", "away_label": "NYL", "home_label": "LVA"}]
        home_games = [{"gamePk": "401857900", "away": {"abbr": "NYL"}, "home": {"abbr": "LVA"}}]

        result = _backfill_prop_row_game_id(rows, home_games)

        self.assertEqual(result[0]["game_id"], "existing-id")

    def test_backfill_prop_row_game_id_no_match_leaves_row_unchanged(self) -> None:
        rows = [{"name": "Unmatched prop", "away_label": "ZZZ", "home_label": "YYY"}]
        home_games = [{"gamePk": "401857900", "away": {"abbr": "NYL"}, "home": {"abbr": "LVA"}}]

        result = _backfill_prop_row_game_id(rows, home_games)

        self.assertNotIn("game_id", result[0])

    def test_backfill_prop_row_game_id_keeps_game_id_and_event_id_distinct(self) -> None:
        # Board-alignment audit, found live 2026-08-01 against a real live
        # WNBA game: a game dict can carry game_id (odds-pipeline hash) and
        # event_id (ESPN's numeric scoreboard id) as genuinely distinct
        # fields (wnba/cards.py's game-contract builders set both
        # independently). This used to stamp all three of
        # row["game_id"]/["gamePk"]/["event_id"] with _game_identifier()'s
        # single result, which prefers game_id over event_id -- collapsing
        # the two id spaces and breaking every live-actual lookup (keyed by
        # the real ESPN event_id) for the backfilled row.
        rows = [{"name": "Natasha Cloud OVER 13.5 PTS+REB", "away_label": "LVA", "home_label": "CHI"}]
        home_games = [
            {
                "game_id": "0d113b66ed1649d47506a6434e06bd1b6",
                "event_id": "401857105",
                "away": {"abbr": "LVA"},
                "home": {"abbr": "CHI"},
            }
        ]

        result = _backfill_prop_row_game_id(rows, home_games)

        self.assertEqual(result[0]["game_id"], "0d113b66ed1649d47506a6434e06bd1b6")
        self.assertEqual(result[0]["gamePk"], "0d113b66ed1649d47506a6434e06bd1b6")
        self.assertEqual(result[0]["event_id"], "401857105")

    def test_wnba_pregame_props_backfills_game_id_from_rank_card_rows(self) -> None:
        # End-to-end version of the above through the actual provider
        # method the home-page overview and the intelligence board both
        # call -- confirms the wiring, not just the helper in isolation.
        from syndicate.features.shared.sport_data_provider import get_sport_data_provider

        home_games = [{"gamePk": "401857900", "away": {"abbr": "NYL"}, "home": {"abbr": "LVA"}}]
        rank_card_rows = [{"name": "Breanna Stewart OVER 21.5 PTS", "away_label": "NYL", "home_label": "LVA", "matchup": "NYL @ LVA"}]
        provider = get_sport_data_provider("wnba")
        self.assertIsNotNone(provider)
        context = provider.resolve_context(requested_date="2026-07-30")

        with patch("syndicate.blueprints.home._pregame_prop_rows_from_betting_card", return_value=rank_card_rows):
            rows = provider.pregame_props(context, home_games, is_active_today=True)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["game_id"], "401857900")

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

    def test_load_home_pregame_prop_items_uses_wnba_props_recommendations_csv(self) -> None:
        home_games = [
            {
                "gamePk": 42,
                "away": {"abbr": "LAS", "name": "Las Vegas Aces"},
                "home": {"abbr": "SEA", "name": "Seattle Storm"},
                "away_tri": "LAS",
                "home_tri": "SEA",
                "detail": "7:00 PM ET",
                "status_badge": "Scheduled",
                "status": {"abstract": "Scheduled", "detailed": "Scheduled"},
            }
        ]

        csv_text = (
            "player,team,plays,ladders,sim_ladders,model,_plays_list,top_play,top_play_explain,top_play_baseline,top_play_reasons,top_play_consensus,top_play_line_adv\n"
            "Dearica Hamby,LAS,\"[]\",[],[],\"{}\",[],\"{'market': 'ast', 'side': 'OVER', 'line': 1.5, 'price': -112.0, 'edge': 0.06, 'ev': 0.12, 'ev_pct': 12.0, 'book': 'fanduel'}\",model 3.5 vs line 1.5 (+2.0),3.5,\"['EV 12.0%']\",0.0,1.0\n"
        )

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            processed = root / "data" / "processed"
            processed.mkdir(parents=True, exist_ok=True)
            (processed / "props_recommendations_2026-07-06.csv").write_text(csv_text, encoding="utf-8")

            with patch("syndicate.features.wnba.sources._source_roots", return_value=[root]), patch(
                "syndicate.blueprints.home._pregame_prop_rows_from_betting_card",
                return_value=[],
            ):
                rows = _load_home_pregame_prop_items(
                    "wnba",
                    context_label="2026-07-06",
                    home_games=home_games,
                    is_active_today=True,
                )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["team"], "LAS")
        self.assertEqual(rows[0]["market"], "AST")
        self.assertFalse(rows[0]["is_live"])
        # The props_recommendations CSV has no opponent column at all, so this
        # row's game_id backfill depends entirely on _opponent_abbr_by_team
        # deriving "home_label" from home_games -- previously never asserted
        # (game_id/gamePk/event_id were never checked here), and previously
        # never worked at all (home_label was never set, so
        # _backfill_prop_row_game_id's away|home lookup key always missed).
        self.assertEqual(rows[0]["gamePk"], "42")
        self.assertEqual(rows[0]["event_id"], "42")

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

    def test_build_sport_overview_wnba_live_props_sourced_independently_of_pregame(self) -> None:
        # Was `live_prop_items = list(pregame_prop_items)` -- a literal copy,
        # not an independently sourced live rail. Locks in that the WNBA
        # branch now calls the same lane="live" dispatcher every other sport
        # uses, instead of duplicating pregame rows.
        app = create_app()
        app.testing = True

        sport = {"slug": "wnba", "name": "WNBA", "primary_label": "Open WNBA cards"}
        home_game = {
            "game_id": "wnba-game-1",
            "away": {"abbr": "LAS", "name": "Las Vegas Aces"},
            "home": {"abbr": "SEA", "name": "Seattle Storm"},
            "status_badge": "Live",
            "status": {"abstract": "Live", "detailed": "Live"},
        }
        pregame_rows = [{"game_id": "wnba-game-1", "heading": "Pregame prop", "is_live": False}]
        live_rows = [{"game_id": "wnba-game-1", "heading": "Live prop", "is_live": True}]

        def _load_home_prop_items_side_effect(slug, **kwargs):
            self.assertEqual(slug, "wnba")
            return live_rows if kwargs.get("lane") == "live" else []

        with app.app_context():
            with patch("syndicate.blueprints.home.central_today_iso", return_value="2026-07-18"), patch(
                "syndicate.blueprints.home.wnba_available_dates",
                return_value=["2026-07-18"],
            ), patch(
                "syndicate.blueprints.home.wnba_has_games_for_date",
                return_value=True,
            ), patch(
                "syndicate.blueprints.home.build_wnba_module_links",
                return_value=[],
            ), patch(
                "syndicate.blueprints.home._prefer_today_or_latest",
                return_value="2026-07-18",
            ), patch(
                "syndicate.blueprints.home.get_wnba_overview",
                return_value={"status": "ok", "games": [home_game], "prop_rows": pregame_rows, "source_title": "WNBA cards", "source_path": ""},
            ), patch(
                "syndicate.blueprints.home._compact_game_cards",
                return_value=[home_game],
            ), patch(
                "syndicate.blueprints.home.get_active_games",
                side_effect=lambda games: games,
            ), patch(
                "syndicate.blueprints.home._finalize_home_prop_rows",
                side_effect=lambda rows, **kwargs: rows,
            ), patch(
                "syndicate.blueprints.home._load_home_prop_items",
                side_effect=_load_home_prop_items_side_effect,
            ) as mocked_load_home_prop_items, patch(
                "syndicate.blueprints.home._link_lookup_any",
                return_value=(None, None),
            ), patch(
                "syndicate.blueprints.home._link_lookup",
                return_value=None,
            ), patch(
                "syndicate.blueprints.home._secondary_links",
                return_value=[],
            ), patch(
                "syndicate.blueprints.home._rail_links",
                return_value=[],
            ):
                overview = _build_sport_overview(sport, "2026-07-18", force_refresh=True)

        mocked_load_home_prop_items.assert_any_call(
            "wnba",
            context_label="2026-07-18",
            home_games=[home_game],
            season=None,
            week=None,
            is_active_today=True,
            lane="live",
        )
        live_items = overview.get("home_rails", {}).get("live", {}).get("items")
        self.assertEqual(live_items, live_rows)
        self.assertNotEqual(live_items, pregame_rows)

    def test_apply_wnba_live_scores_ignores_projection_for_pregame_game(self) -> None:
        # cards.py's live-state row falls back to the SmartSim *projected*
        # point total for away_pts/home_pts whenever no real ESPN boxscore
        # row has matched yet -- the normal state for a game that hasn't
        # tipped off. Without the in_progress/final gate, a pregame game
        # picked up a fabricated decimal "score" (e.g. 91.81-91.17) on the
        # board's game-chip strip (#160).
        games = [
            {
                "game_id": "wnba-game-2",
                "away_tri": "NYL",
                "home_tri": "LVA",
                "away": {"abbr": "NYL"},
                "home": {"abbr": "LVA"},
                "status": {"abstract": "Scheduled"},
            }
        ]
        live_payload = {
            "games": [
                {
                    "away": "NYL",
                    "home": "LVA",
                    "away_pts": 91.81,
                    "home_pts": 91.17,
                    "in_progress": False,
                    "final": False,
                    "status": "Scheduled",
                }
            ]
        }

        with patch("syndicate.features.wnba.cards.build_live_state_payload", return_value=live_payload):
            enriched = home_module._apply_wnba_live_scores(games, "2026-07-30")

        self.assertEqual(len(enriched), 1)
        self.assertIsNone(enriched[0]["away"].get("score"))
        self.assertIsNone(enriched[0]["home"].get("score"))
        self.assertIsNone(enriched[0]["status"].get("away_score"))
        self.assertIsNone(enriched[0]["status"].get("home_score"))

    def test_apply_wnba_live_scores_keeps_real_score_for_live_game(self) -> None:
        games = [
            {
                "game_id": "wnba-game-3",
                "away_tri": "NYL",
                "home_tri": "LVA",
                "away": {"abbr": "NYL"},
                "home": {"abbr": "LVA"},
                "status": {"abstract": "Live"},
            }
        ]
        live_payload = {
            "games": [
                {
                    "away": "NYL",
                    "home": "LVA",
                    "away_pts": 61,
                    "home_pts": 58,
                    "in_progress": True,
                    "final": False,
                    "status": "Q3 4:12",
                }
            ]
        }

        with patch("syndicate.features.wnba.cards.build_live_state_payload", return_value=live_payload):
            enriched = home_module._apply_wnba_live_scores(games, "2026-07-30")

        self.assertEqual(enriched[0]["away"]["score"], 61)
        self.assertEqual(enriched[0]["home"]["score"], 58)

    def test_nfl_is_live_not_forced_false_without_live_prop_source(self) -> None:
        # NFL/NCAAF/NCAAB have no branch in _load_home_live_prop_items, so
        # live_prop_items is always []. Before the fix, _game_identity_set([])
        # produced an empty-but-real set, which _live_odds_backed_live_flag
        # treats as "confirmed nothing live" -- forcing is_live False for
        # every game of these sports even when genuinely live. The fix routes
        # sports with no live-prop source to live_odds_game_ids=None instead,
        # which _live_odds_backed_live_flag already treats as "no
        # corroboration available, trust the fallback flag."
        app = create_app()
        app.testing = True

        sport = {"slug": "nfl", "name": "NFL", "primary_label": "Open NFL cards"}
        home_game = {"game_id": "nfl-game-1", "is_live": True, "status_badge": "Live", "status": {"abstract": "Live", "detailed": "Live"}}
        game_item = {"game_id": "nfl-game-1", "is_live": True}

        with app.app_context():
            with patch("syndicate.blueprints.home.central_today_iso", return_value="2026-09-07"), patch(
                "syndicate.blueprints.home.nfl_latest_season", return_value=2026
            ), patch(
                "syndicate.blueprints.home.nfl_tracked_week", return_value={"week": 1}
            ), patch(
                "syndicate.blueprints.home.nfl_default_week", return_value=1
            ), patch(
                "syndicate.blueprints.home.build_nfl_module_links", return_value=[]
            ), patch(
                "syndicate.blueprints.home.nfl_week_summaries", return_value=[]
            ), patch(
                "syndicate.blueprints.home._is_active_today", return_value=True
            ), patch(
                "syndicate.blueprints.home._load_home_game_items",
                return_value=([game_item], 1),
            ), patch(
                "syndicate.blueprints.home._load_home_games",
                return_value=[home_game],
            ), patch(
                "syndicate.blueprints.home.get_active_games",
                side_effect=lambda games: games,
            ), patch(
                "syndicate.blueprints.home._load_home_prop_items",
                return_value=[],
            ), patch(
                "syndicate.blueprints.home._finalize_home_prop_rows",
                side_effect=lambda rows, **kwargs: rows,
            ), patch(
                "syndicate.blueprints.home._link_lookup_any",
                return_value=(None, None),
            ), patch(
                "syndicate.blueprints.home._link_lookup",
                return_value=None,
            ), patch(
                "syndicate.blueprints.home._secondary_links",
                return_value=[],
            ), patch(
                "syndicate.blueprints.home._rail_links",
                return_value=[],
            ):
                overview = _build_sport_overview(sport, "2026-09-07", force_refresh=True)

        dashboard_games = overview.get("dashboard_games") or []
        self.assertEqual(len(dashboard_games), 1)
        self.assertTrue(dashboard_games[0]["is_live"])

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

    def test_board_candidate_rows_reuses_shared_cascade(self) -> None:
        # Plan item 1F: this used to hand-roll its own worker-state ->
        # board-snapshot read sequence, a parallel path to (and so never
        # benefiting from) _cached_intelligence_response_with_source's
        # canonical-board-state-first cascade. Confirms it now delegates
        # directly instead of re-implementing the read order itself.
        response_payload = {
            "recommendations": [
                {
                    "sport": "MLB",
                    "sport_slug": "mlb",
                    "matchup": "NYY at BOS",
                    "market": "Total",
                    "pick": "Over 8.5",
                    "edge": "5.0%",
                    "confidence": "60%",
                    "is_live": False,
                }
            ]
        }
        with patch("syndicate.blueprints.intelligence._cached_intelligence_response_with_source", return_value=(response_payload, "worker")) as mocked_cascade:
            rows = _board_candidate_rows("2026-06-13", limit=5)

        mocked_cascade.assert_called_once()
        self.assertEqual(mocked_cascade.call_args.kwargs.get("force_refresh"), False)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["sport_slug"], "mlb")
        self.assertEqual(rows[0]["matchup"], "NYY at BOS")

    def test_board_candidate_rows_returns_empty_when_cascade_finds_nothing(self) -> None:
        with patch("syndicate.blueprints.intelligence._cached_intelligence_response_with_source", return_value=(None, "fallback")):
            rows = _board_candidate_rows("2026-06-13")

        self.assertEqual(rows, [])

    def test_board_candidate_rows_swallows_exceptions(self) -> None:
        with patch("syndicate.blueprints.intelligence._cached_intelligence_response_with_source", side_effect=RuntimeError("boom")):
            rows = _board_candidate_rows("2026-06-13")

        self.assertEqual(rows, [])


class GameBetCandidateTeamAttributionTests(unittest.TestCase):
    @staticmethod
    def _sample_game(**overrides: object) -> dict[str, object]:
        game: dict[str, object] = {
            "away": {"name": "Boston Celtics"},
            "home": {"name": "New York Knicks"},
            "summary": "Test game",
            "status": "Scheduled",
        }
        game.update(overrides)
        return game

    def test_team_for_side_hint_resolves_side_keywords_and_selection_text(self) -> None:
        game = self._sample_game()
        self.assertEqual(_team_for_side_hint(game, "home"), "New York Knicks")
        self.assertEqual(_team_for_side_hint(game, "AWAY"), "Boston Celtics")
        self.assertEqual(_team_for_side_hint(game, "Boston Celtics -9.5"), "Boston Celtics")
        self.assertIsNone(_team_for_side_hint(game, "unknown"))
        self.assertIsNone(_team_for_side_hint(game, None))

    def test_moneyline_candidates_carry_team_name(self) -> None:
        game = self._sample_game(
            betting={"away_ml": -120, "home_ml": 105, "p_away_win": 0.55, "p_home_win": 0.45}
        )
        candidates = _game_bet_candidates_from_game({"slug": "nba"}, game, fallback_epoch=0.0)
        moneyline_by_pick = {c["pick"]: c["team"] for c in candidates if c["market"] == "Moneyline"}
        self.assertEqual(moneyline_by_pick.get("Away ML"), "Boston Celtics")
        self.assertEqual(moneyline_by_pick.get("Home ML"), "New York Knicks")

    def test_pitcher_matchup_metadata_summary_is_also_replaced(self) -> None:
        # Found live 2026-08-04, second round: MLB cards.py's own
        # game["summary"] is real (not the internal sentinel) but still
        # low-information -- "{starter} vs {starter} | N official
        # pick(s)" -- reported as exactly the "terse pitcher-matchup
        # metadata" that isn't real analysis either. Confirms this is also
        # replaced, not just the two exact internal placeholders.
        game = self._sample_game(
            summary="Tarik Skubal vs Javier Assad | 3 official pick(s) | +1 playable",
            betting={"away_ml": -120, "home_ml": 105, "p_away_win": 0.55, "p_home_win": 0.45},
        )
        candidates = _game_bet_candidates_from_game({"slug": "mlb"}, game, fallback_epoch=0.0)
        home_detail = next(c for c in candidates if c["market"] == "Moneyline" and c["pick"] == "Home ML")["detail"]
        self.assertNotIn("official pick", home_detail)
        self.assertIn("New York Knicks", home_detail)

    def test_narrative_subject_prefers_the_more_descriptive_string(self) -> None:
        # Found live 2026-08-04: some sports' team dicts (confirmed for
        # WNBA) carry an abbreviated code ("NYL") rather than a full name
        # in the field _game_team_label reads, producing "The model favors
        # NYL for the ats" -- picking whichever of team/pick text is
        # longer sidesteps the per-sport data gap rather than depending on
        # any one sport's naming being correct.
        self.assertEqual(_game_bet_narrative_subject(team_text="NYL", pick_text="New York Liberty -9.5"), "New York Liberty -9.5")
        self.assertEqual(_game_bet_narrative_subject(team_text="New York Knicks", pick_text="Home ML"), "New York Knicks")
        self.assertEqual(_game_bet_narrative_subject(team_text="-", pick_text="Under 181.5"), "Under 181.5")
        self.assertEqual(_game_bet_narrative_subject(team_text=None, pick_text=None), "this pick")

    def test_narrative_does_not_echo_a_placeholder_projected_score(self) -> None:
        # game_board_contract.py's shared_period_rows "main" falls back to
        # game.get("summary") when there's no real projected score -- the
        # same placeholder this whole function replaces can leak back in
        # through that second path. Found live 2026-08-04: "Model projects
        # oddsapi_consensus market snapshot."
        game = {
            "shared_period_rows": [
                {"label": "Full game", "main": "oddsapi_consensus market snapshot", "market": "-", "best_edge": "-"}
            ]
        }
        narrative = _game_bet_narrative(market="Moneyline", subject="New York Knicks", model_probability_pct=62.0, odds=-150, edge_pct=8.5, game=game)
        self.assertNotIn("oddsapi_consensus", narrative)
        self.assertNotIn("Model projects", narrative)

    def test_placeholder_detail_is_replaced_with_real_narrative_prose(self) -> None:
        # Found live 2026-08-04 verifying game-market picks (moneyline/ATS/
        # totals) through Ask the Syndicate: "detail" was frequently the
        # internal "oddsapi_consensus market snapshot" sentinel, not real
        # analysis -- dc4b9553 filtered it downstream at Ask's own read
        # layer, but the upstream candidate never carried real prose to
        # begin with. This is the actual fix: generate it here, from the
        # same real inputs (model win probability, actual posted odds,
        # edge) every consumer of these candidates already has.
        game = self._sample_game(
            summary="oddsapi_consensus market snapshot",
            betting={"away_ml": -120, "home_ml": 105, "p_away_win": 0.55, "p_home_win": 0.45},
        )
        candidates = _game_bet_candidates_from_game({"slug": "nba"}, game, fallback_epoch=0.0)
        moneyline_by_pick = {c["pick"]: c for c in candidates if c["market"] == "Moneyline"}
        home_detail = moneyline_by_pick["Home ML"]["detail"]
        self.assertNotIn("oddsapi_consensus", home_detail.lower())
        self.assertIn("New York Knicks", home_detail)
        self.assertIn("45.0%", home_detail)  # model win probability (p_home_win=0.45)
        self.assertIn("%", home_detail)  # a real market-implied probability from the -120/105 odds is present too

    def test_real_detail_text_is_left_untouched(self) -> None:
        # A genuinely real, hand-authored summary must never be replaced --
        # the fix targets the specific known placeholder, not "any detail
        # text we could theoretically improve on."
        game = self._sample_game(
            summary="Knicks are 8-2 in their last 10 home games against a spread this size.",
            betting={"away_ml": -120, "home_ml": 105, "p_away_win": 0.55, "p_home_win": 0.45},
        )
        candidates = _game_bet_candidates_from_game({"slug": "nba"}, game, fallback_epoch=0.0)
        moneyline = next(c for c in candidates if c["market"] == "Moneyline" and c["pick"] == "Home ML")
        self.assertEqual(moneyline["detail"], "Knicks are 8-2 in their last 10 home games against a spread this size.")

    def test_placeholder_detail_without_confidence_falls_back_unchanged(self) -> None:
        # Real odds but no model win probability at all -- _game_bet_narrative
        # must return None rather than fabricate a sentence with no real
        # numbers behind it, leaving the old placeholder-handling path intact.
        game = self._sample_game(
            summary="oddsapi_consensus market snapshot",
            betting={"away_ml": -120, "home_ml": 105},
        )
        candidates = _game_bet_candidates_from_game({"slug": "nba"}, game, fallback_epoch=0.0)
        moneyline = next(c for c in candidates if c["market"] == "Moneyline" and c["pick"] == "Home ML")
        # Unchanged pre-existing fallback (not this fix's concern): the raw
        # placeholder string passes through as-is when there's no real data
        # to replace it with.
        self.assertEqual(moneyline["detail"], "oddsapi_consensus market snapshot")

    def test_game_bet_narrative_returns_none_without_model_probability(self) -> None:
        self.assertIsNone(
            _game_bet_narrative(market="Moneyline", subject="New York Knicks", model_probability_pct=None, odds=-120, edge_pct=5.0, game={})
        )

    def test_game_bet_narrative_includes_market_implied_probability_from_real_odds(self) -> None:
        narrative = _game_bet_narrative(market="Moneyline", subject="New York Knicks", model_probability_pct=62.0, odds=-150, edge_pct=8.5, game={})
        self.assertIn("New York Knicks", narrative)
        self.assertIn("62.0%", narrative)
        self.assertIn("60.0%", narrative)  # implied probability of -150 american odds
        self.assertIn("8.5%", narrative)

    def test_soccer_candidates_show_league_display_instead_of_generic_sport_name(self) -> None:
        # #162: soccer covers several leagues at once (MLS, La Liga, ...);
        # game.get("league_display") -- only ever stamped by soccer's own
        # game builders (soccer/cards.py) -- should override the generic
        # "Soccer" sport family label on every game-level candidate.
        game = self._sample_game(
            league="mls",
            league_display="MLS",
            betting={"away_ml": -120, "home_ml": 105, "p_away_win": 0.55, "p_home_win": 0.45},
        )
        candidates = _game_bet_candidates_from_game({"slug": "soccer", "name": "Soccer"}, game, fallback_epoch=0.0)
        self.assertTrue(candidates)
        for candidate in candidates:
            self.assertEqual(candidate["sport"], "MLS")
            self.assertEqual(candidate["sport_slug"], "soccer")

    def test_non_soccer_candidates_are_unaffected_by_league_display_field(self) -> None:
        game = self._sample_game(
            betting={"away_ml": -120, "home_ml": 105, "p_away_win": 0.55, "p_home_win": 0.45},
        )
        candidates = _game_bet_candidates_from_game({"slug": "nba", "name": "NBA"}, game, fallback_epoch=0.0)
        self.assertTrue(candidates)
        for candidate in candidates:
            self.assertEqual(candidate["sport"], "NBA")

    def test_live_game_candidates_show_current_combined_score_as_actual_not_live_projection(self) -> None:
        # The board's Live column used to show the game's current combined
        # score for every Moneyline/Spread/Total candidate built from the
        # plain "betting" dict -- conflating real game state with a
        # projection. NBA has no live re-sim, so live_projection correctly
        # stays "-"; the combined score now surfaces honestly as "actual".
        #
        # Board-alignment audit, found live 2026-08-01: this used to assert
        # Moneyline's "actual" was the combined score (8.0) -- confirmed
        # against a real live WNBA game that this told a Moneyline/ATS
        # bettor nothing about which side was actually ahead (every
        # game-level market for the same game showed the identical
        # combined number). Moneyline/Spread/ATS now get the real
        # away-home scoreline instead; Total (below) keeps the combined
        # number, since that's the one market genuinely comparable to it.
        game = self._sample_game(
            shared_is_live=True,
            status={"in_progress": True},
            away={"name": "Boston Celtics", "score": 3},
            home={"name": "New York Knicks", "score": 5},
            betting={"away_ml": -120, "home_ml": 105, "p_away_win": 0.55, "p_home_win": 0.45, "total": 210.5, "over_ev": 0.05, "under_ev": -0.03, "p_total_over": 0.52, "p_total_under": 0.48},
        )
        candidates = _game_bet_candidates_from_game({"slug": "nba"}, game, fallback_epoch=0.0)
        moneyline_candidates = [c for c in candidates if c["market"] == "Moneyline"]
        self.assertTrue(moneyline_candidates)
        for candidate in moneyline_candidates:
            self.assertTrue(candidate["is_live"])
            self.assertEqual(candidate["live_projection"], "-")
            self.assertEqual(candidate["actual"], "3-5")
        total_candidates = [c for c in candidates if c["market"] == "Total"]
        self.assertTrue(total_candidates)
        for candidate in total_candidates:
            self.assertEqual(float(candidate["actual"]), 8.0)

    def test_pregame_candidates_leave_live_column_blank(self) -> None:
        game = self._sample_game(
            away={"name": "Boston Celtics", "score": None},
            home={"name": "New York Knicks", "score": None},
            betting={"away_ml": -120, "home_ml": 105, "p_away_win": 0.55, "p_home_win": 0.45},
        )
        candidates = _game_bet_candidates_from_game({"slug": "nba"}, game, fallback_epoch=0.0)
        moneyline_candidates = [c for c in candidates if c["market"] == "Moneyline"]
        self.assertTrue(moneyline_candidates)
        for candidate in moneyline_candidates:
            self.assertFalse(candidate["is_live"])
            self.assertEqual(candidate["live_projection"], "-")

    def test_live_game_without_scores_leaves_live_column_blank_not_zero(self) -> None:
        game = self._sample_game(
            shared_is_live=True,
            status={"in_progress": True},
            betting={"away_ml": -120, "home_ml": 105, "p_away_win": 0.55, "p_home_win": 0.45},
        )
        candidates = _game_bet_candidates_from_game({"slug": "nba"}, game, fallback_epoch=0.0)
        moneyline_candidates = [c for c in candidates if c["market"] == "Moneyline"]
        self.assertTrue(moneyline_candidates)
        for candidate in moneyline_candidates:
            self.assertTrue(candidate["is_live"])
            self.assertEqual(candidate["live_projection"], "-")
            self.assertEqual(candidate["actual"], "-")

    def test_live_player_prop_candidates_do_not_get_game_combined_score_as_live_projection(self) -> None:
        # Real regression found 2026-07-23: _game_bet_candidates_from_game's
        # game_market_recommendations loop also surfaces per-game PLAYER
        # PROP rows (market label "Hitter X"/"Pitcher X"), mixed in
        # alongside genuine game-level markets, through the SAME
        # _append_game_bet_candidate call that fills in live_projection with
        # the game's combined score when none was passed explicitly. That
        # combined score is meaningless for a player prop -- confirmed live,
        # completely different hitter props (total bases, hits, for
        # different players) for the same game all showed the identical
        # combined-score number.
        game = self._sample_game(
            shared_is_live=True,
            status={"in_progress": True},
            away={"name": "Boston Celtics", "score": 5},
            home={"name": "New York Knicks", "score": 3},
            game_market_recommendations=[
                {"market_label": "Hitter Total Bases", "selection": "Over 1.5", "line": 1.5},
                {"market_label": "Pitcher Strikeouts", "selection": "Under 7.5", "line": 7.5},
            ],
        )
        candidates = _game_bet_candidates_from_game({"slug": "mlb"}, game, fallback_epoch=0.0)
        prop_candidates = [c for c in candidates if c["market"] in ("Hitter Total Bases", "Pitcher Strikeouts")]
        self.assertEqual(len(prop_candidates), 2)
        for candidate in prop_candidates:
            self.assertTrue(candidate["is_live"])
            self.assertEqual(candidate["live_projection"], "-")
            self.assertEqual(candidate["actual"], "-")

    def test_wnba_player_prop_candidates_do_not_get_game_combined_score_as_actual(self) -> None:
        # Phase C (Layer 2 task), found live 2026-07-31: is_game_level_market
        # used to be a local "starts with Hitter /Pitcher " check -- an
        # MLB-only naming convention. WNBA player props are labeled by short
        # stat code ("PTS", "PRA", ...) or the generic "PROPS"
        # (_source_game_market_recommendations/market_label), never
        # "Hitter "/"Pitcher ", so every WNBA player prop candidate was
        # misclassified as game-level: it got the game's combined score
        # stamped onto "actual" (meaningless for an individual player's
        # points prop) exactly like the MLB bug above, just never caught for
        # this sport. Now reuses intelligence.py's real classifier, which
        # gets "PTS"/"PROPS" right.
        game = self._sample_game(
            shared_is_live=True,
            status={"in_progress": True},
            away={"name": "Golden State Valkyries", "score": 61},
            home={"name": "Indiana Fever", "score": 58},
            game_market_recommendations=[
                {"market_label": "PTS", "display_pick": "Kelsey Mitchell OVER 1.5", "selection": "OVER 1.5", "line": 1.5},
                {"market_label": "PROPS", "display_pick": "Caitlin Clark OVER 14.5", "selection": "OVER 14.5", "line": 14.5},
            ],
        )
        candidates = _game_bet_candidates_from_game({"slug": "wnba"}, game, fallback_epoch=0.0)
        prop_candidates = [c for c in candidates if c["market"] in ("PTS", "PROPS")]
        self.assertEqual(len(prop_candidates), 2)
        for candidate in prop_candidates:
            self.assertTrue(candidate["is_live"])
            self.assertEqual(candidate["actual"], "-")

    def test_wnba_player_prop_pick_text_extracts_name_first_convention(self) -> None:
        # recommendations_slate's own display_pick puts the player's name
        # FIRST ("Kelsey Mitchell OVER 1.5"), the opposite order from MLB's
        # panels ("OVER Bryce Eldridge") -- confirmed via a direct read of a
        # real recommendations_slate_*.json artifact. Player identity should
        # now resolve for this convention too, not just MLB's.
        game = self._sample_game(
            game_market_recommendations=[
                {"market_label": "PTS", "display_pick": "Kelsey Mitchell OVER 1.5", "selection": "OVER 1.5", "line": 1.5},
            ],
        )
        candidates = _game_bet_candidates_from_game({"slug": "wnba"}, game, fallback_epoch=0.0)
        prop_candidate = next(c for c in candidates if c["market"] == "PTS")
        self.assertEqual(prop_candidate["entity"], "Kelsey Mitchell")

    def test_prop_with_no_line_odds_or_projection_is_suppressed(self) -> None:
        # Board audit follow-up, found live 2026-07-31: recommendations_slate
        # picks for bench/role players with no real priced market
        # (model_probability 0.5, no OddsAPI line yet) produced a board
        # candidate reading "Courtney Vandersloot OVER -" -- name resolved
        # fine (Phase C), but market/line/odds were all genuinely absent
        # upstream. Nothing bettable to show, so this must not reach the
        # board at all rather than display as a broken row.
        game = self._sample_game(
            game_market_recommendations=[
                {"market_label": "PROP", "display_pick": "Courtney Vandersloot OVER -", "selection": "Courtney Vandersloot OVER -"},
            ],
        )
        candidates = _game_bet_candidates_from_game({"slug": "wnba"}, game, fallback_epoch=0.0)
        self.assertFalse(any(c["market"] == "PROP" for c in candidates))

    def test_prop_with_a_real_line_but_no_odds_yet_still_surfaces(self) -> None:
        # The completeness guard should only suppress a prop when line,
        # odds, AND projection are ALL absent -- a real line with odds not
        # yet posted is still informative and must not be silently dropped.
        game = self._sample_game(
            game_market_recommendations=[
                {"market_label": "PTS", "display_pick": "Kelsey Mitchell OVER 14.5", "selection": "OVER 14.5", "line": 14.5},
            ],
        )
        candidates = _game_bet_candidates_from_game({"slug": "wnba"}, game, fallback_epoch=0.0)
        self.assertTrue(any(c["market"] == "PTS" for c in candidates))

    def test_spread_candidates_get_team_projected_and_confidence(self) -> None:
        game = self._sample_game(
            betting={
                "home_puck_line": -1.5,
                "away_puck_line": 1.5,
                "home_spread": -1.5,
                "p_home_cover": 0.58,
                "p_away_cover": 0.42,
            }
        )
        candidates = _game_bet_candidates_from_game({"slug": "nhl"}, game, fallback_epoch=0.0)
        spreads = {c["pick"].split(" ")[0]: c for c in candidates if c["market"] == "Spread"}
        self.assertEqual(spreads["Away"]["team"], "Boston Celtics")
        self.assertEqual(spreads["Home"]["team"], "New York Knicks")
        # Previously these candidates never received odds, edge, confidence,
        # or a projected value from this fallback path, so
        # classify_candidate's missing_projection_or_odds gate always
        # dropped them.
        self.assertNotEqual(spreads["Away"]["projected"], "-")
        self.assertNotEqual(spreads["Home"]["projected"], "-")
        self.assertNotEqual(spreads["Away"]["confidence"], "-")
        self.assertNotEqual(spreads["Home"]["confidence"], "-")

    def test_game_market_recommendation_team_derived_from_selection_text(self) -> None:
        game = self._sample_game(
            game_market_recommendations=[
                {
                    "market_label": "Spread",
                    "display_pick": "Boston Celtics -9.5",
                    "selection": "Boston Celtics -9.5",
                    "line": -9.5,
                    "price": -110,
                    "ev_pct": 5.0,
                    "p_win": 0.6,
                }
            ]
        )
        candidates = _game_bet_candidates_from_game({"slug": "nba"}, game, fallback_epoch=0.0)
        self.assertEqual(candidates[0]["team"], "Boston Celtics")

    def test_mlb_prop_candidate_team_from_team_side(self) -> None:
        game = self._sample_game(
            markets={
                "pitcherProps": [
                    {
                        "pitcher_name": "Gerrit Cole",
                        "team_side": "home",
                        "market_label": "Outs",
                        "selection": "OVER",
                        "market_line": 15.5,
                    }
                ],
            }
        )
        candidates = _game_bet_candidates_from_game({"slug": "mlb"}, game, fallback_epoch=0.0)
        self.assertEqual(candidates[0]["team"], "New York Knicks")

    def test_mlb_markets_ml_and_totals_translate_into_game_market_recommendations(self) -> None:
        # Real gap found 2026-07-23: MLB's own cards.py builds moneyline/totals
        # picks under game["markets"]["ml"/"totals"] for its own hub-page tiles
        # -- a different shape than the game_market_recommendations list every
        # other sport's cards.py emits, and the only shape
        # _game_bet_candidates_from_game reads. Without translating this shape,
        # MLB pregame Moneyline/Total candidates never reached the board at
        # all; only in-game period-lens markets (e.g. "f7 moneyline") for a
        # currently-live game ever showed up as MLB "game" candidates.
        game = self._sample_game(
            markets={
                "ml": {"selection": "home", "model_prob": 0.57, "odds": -135},
                "totals": {"selection": "over", "market_line": 8.5, "model_prob": 0.52, "odds": -110},
            },
            predictions={"full": {"away_runs_mean": 4.268, "home_runs_mean": 4.18}},
        )
        rows = _mlb_game_market_recommendation_rows(game)
        self.assertEqual(len(rows), 2)
        game["game_market_recommendations"] = rows
        candidates = _game_bet_candidates_from_game({"slug": "mlb", "hub_href": "/mlb/hub"}, game, fallback_epoch=0.0)
        moneyline = next(c for c in candidates if c["market"] == "Moneyline")
        total = next(c for c in candidates if c["market"] == "Total")
        self.assertEqual(moneyline["pick"], "Home ML")
        self.assertEqual(moneyline["team"], "New York Knicks")
        self.assertEqual(moneyline["odds"], "-135")
        self.assertNotEqual(moneyline["confidence"], "-")
        self.assertEqual(total["pick"], "Over 8.5")
        self.assertEqual(total["line"], "8.5")
        self.assertNotEqual(total["confidence"], "-")
        # #98/#100: the row's model_prob must survive as a raw 0-1 fraction
        # under "model_probability", the field normalize_candidate's
        # projection scan actually checks -- not just as display text under
        # "confidence", which the scan never looks at.
        self.assertAlmostEqual(moneyline["model_probability"], 0.57)
        self.assertAlmostEqual(total["model_probability"], 0.52)
        # #131 follow-up, confirmed live 2026-07-29: game-level candidates
        # (MLB Moneyline/Total, same class as the WNBA prop/game fixes)
        # showed projected="-" on the board even with real sim data present.
        # Moneyline's projection IS the win probability (no separate
        # "projected line" concept exists for a moneyline); Total's real
        # model projection is the sim's own away_runs_mean + home_runs_mean,
        # already computed elsewhere in mlb/cards.py for display but never
        # threaded through this specific translation before.
        self.assertEqual(moneyline["projected"], "57.0%")
        self.assertEqual(total["projected"], "8.4")

    def test_mlb_markets_with_no_selection_produce_no_rows(self) -> None:
        game = self._sample_game(markets={"ml": {}, "totals": {"selection": "over"}})
        self.assertEqual(_mlb_game_market_recommendation_rows(game), [])

    def test_mlb_bare_odds_markets_derive_a_pick_from_sim_predictions(self) -> None:
        # #100 follow-up, 2026-07-27: confirmed in production that most
        # non-final MLB games (7 of 9 on a real slate, including every
        # genuinely pregame one) only ever carry bare book odds under
        # markets["ml"/"totals"] (away_odds/home_odds, no selection/
        # model_prob) -- the recommendation engine simply never flagged
        # them -- even though game["predictions"]["full"] already has real,
        # non-degenerate win probabilities for every one. Without this sim
        # fallback, those games produced zero game-level candidates
        # regardless of the confidence-field fix above, since
        # _mlb_game_market_recommendation_rows had no pick to translate.
        game = self._sample_game(
            markets={
                "ml": {"away_odds": "-112", "home_odds": "-108"},
                "totals": {"line": 8.5, "over_odds": "-117", "under_odds": "-103"},
            },
            predictions={
                "full": {
                    "home_win_prob": 0.579,
                    "away_win_prob": 0.421,
                    "total_runs_dist": {"7": 0.3, "8": 0.45, "9": 0.25},
                }
            },
        )
        rows = _mlb_game_market_recommendation_rows(game)
        self.assertEqual(len(rows), 2)
        moneyline = next(r for r in rows if r["market_label"] == "Moneyline")
        total = next(r for r in rows if r["market_label"] == "Total")
        # Home is favored (0.579 > 0.421), so the derived pick sides with home
        # and prices off home_odds, not the (unused) top-level odds/price key.
        self.assertEqual(moneyline["display_pick"], "Home ML")
        self.assertEqual(moneyline["odds"], "-108")
        self.assertAlmostEqual(moneyline["confidence"], 0.579)
        # total_runs_dist puts 25% of weight over 8.5, so Under is favored.
        self.assertEqual(total["display_pick"], "Under 8.5")
        self.assertEqual(total["odds"], "-103")
        self.assertAlmostEqual(total["confidence"], 0.75)

        game["game_market_recommendations"] = rows
        candidates = _game_bet_candidates_from_game({"slug": "mlb"}, game, fallback_epoch=0.0)
        candidate_moneyline = next(c for c in candidates if c["market"] == "Moneyline")
        self.assertAlmostEqual(candidate_moneyline["model_probability"], 0.579)

    def test_mlb_recommendation_shaped_markets_are_not_overridden_by_sim_fallback(self) -> None:
        # The sim fallback must only fire when the recommendation engine
        # left selection/model_prob genuinely absent -- an existing pick
        # (even one that disagrees with the sim's favored side) must win.
        game = self._sample_game(
            markets={
                "ml": {"selection": "away", "model_prob": 0.3, "odds": "+150"},
            },
            predictions={"full": {"home_win_prob": 0.9, "away_win_prob": 0.1}},
        )
        rows = _mlb_game_market_recommendation_rows(game)
        moneyline = next(r for r in rows if r["market_label"] == "Moneyline")
        self.assertEqual(moneyline["display_pick"], "Away ML")
        self.assertAlmostEqual(moneyline["confidence"], 0.3)

    def test_mlb_moneyline_derives_from_sim_even_when_markets_ml_is_entirely_absent(self) -> None:
        # #108 follow-up, confirmed live 2026-07-27: refresh-worker's own
        # dashboard_games carries markets["ml"] as entirely ABSENT for every
        # MLB game (not merely a bare-odds dict lacking selection/model_prob,
        # which the sibling test above already covers) -- production traces
        # showed has_markets_ml=False for all 12 games in a real cycle, while
        # predictions.full was reliably present with real win probabilities.
        # A moneyline pick needs no book line to exist (unlike totals, which
        # genuinely has nothing to bet against without one), so this must
        # still produce a candidate from the sim alone, with odds left absent
        # rather than the whole market silently contributing nothing.
        game = self._sample_game(
            markets={},
            predictions={"full": {"home_win_prob": 0.577, "away_win_prob": 0.423}},
        )
        rows = _mlb_game_market_recommendation_rows(game)
        moneyline = next(r for r in rows if r["market_label"] == "Moneyline")
        self.assertEqual(moneyline["display_pick"], "Home ML")
        self.assertAlmostEqual(moneyline["confidence"], 0.577)
        self.assertIsNone(moneyline["odds"])

    def test_mlb_feed_live_state_does_not_treat_warmup_as_live(self) -> None:
        # #98/#100: was abstract.lower() == "live" alone -- MLB StatsAPI
        # reports abstractGameState "Live" during warmup, before the game has
        # actually started. detailedState "Warmup" is the real signal.
        from syndicate.blueprints.home import _mlb_feed_live_state

        warmup_payload = {
            "gameData": {"status": {"abstractGameState": "Live", "detailedState": "Warmup"}},
            "liveData": {"linescore": {"teams": {}}},
        }
        with patch("syndicate.blueprints.home._mlb_feed_live_payload", return_value=warmup_payload):
            state = _mlb_feed_live_state("2026-07-27", 123456)
        self.assertIsNotNone(state)
        self.assertFalse(state["in_progress"])
        self.assertFalse(state["final"])

        in_progress_payload = {
            "gameData": {"status": {"abstractGameState": "Live", "detailedState": "In Progress"}},
            "liveData": {"linescore": {"teams": {}}},
        }
        with patch("syndicate.blueprints.home._mlb_feed_live_payload", return_value=in_progress_payload):
            state = _mlb_feed_live_state("2026-07-27", 123456)
        self.assertTrue(state["in_progress"])

    def test_mlb_actual_payload_for_game_falls_back_to_live_fetch_for_todays_game(self) -> None:
        # #168: raw_feed_live_path's cached file is only ever written by the
        # vendor daily-update's PRIOR-day reconciliation step (confirmed via
        # a direct read of vendor/mlb_bettingv2/tools/daily_update.py -- it
        # is never called for today's date), so for a currently-live game
        # this file structurally does not exist yet. This used to leave
        # _mlb_actual_payload_for_game (and therefore
        # _apply_live_state_context_to_candidates' whole correction pass)
        # silently returning None for every live game, even though
        # /mlb/api/live-lens's own status check (a real HTTP fetch) had the
        # correct answer the whole time. Now reuses _mlb_feed_live_payload,
        # which already falls back to a live fetch for today's date when the
        # cache is empty -- confirm that fallback is actually exercised.
        from syndicate.blueprints.home import _mlb_actual_payload_for_game
        from syndicate.features.shared.timezone import central_today_iso

        live_payload = {
            "gameData": {"status": {"abstractGameState": "Live", "detailedState": "In Progress"}},
            "liveData": {"linescore": {"teams": {}}},
        }
        with patch("syndicate.blueprints.home.load_json_or_gz_file", return_value=None), patch(
            "syndicate.blueprints.home._fetch_mlb_feed_live", return_value=live_payload
        ) as mock_fetch:
            payload = _mlb_actual_payload_for_game(central_today_iso(), 123456, {})
        mock_fetch.assert_called_once_with(123456)
        self.assertEqual(payload, live_payload)

    def test_mlb_actual_payload_for_game_does_not_live_fetch_for_a_past_date(self) -> None:
        # The live-fetch fallback is deliberately scoped to today's date
        # only (mirrors _mlb_feed_live_payload's own scoping) -- a past date
        # with no cached file means the game was never backfilled, not that
        # it's currently live, so there is nothing to fetch live.
        from syndicate.blueprints.home import _mlb_actual_payload_for_game

        with patch("syndicate.blueprints.home.load_json_or_gz_file", return_value=None), patch(
            "syndicate.blueprints.home._fetch_mlb_feed_live"
        ) as mock_fetch:
            payload = _mlb_actual_payload_for_game("2020-01-01", 123456, {})
        mock_fetch.assert_not_called()
        self.assertIsNone(payload)

    def test_first_present_text_treats_numeric_zero_as_present(self) -> None:
        # #100: str(value or "") is truthiness-based, so a legitimate numeric
        # 0 (a projected total of 0, a model mean of 0.0) used to fall through
        # to a lower-priority field in the scan instead of winning -- same bug
        # class #68 fixed in _candidate_value_is_present.
        from syndicate.blueprints.home import _first_present_text

        self.assertEqual(_first_present_text(0, "fallback"), "0")
        self.assertEqual(_first_present_text(0.0, "fallback"), "0.0")
        self.assertEqual(_first_present_text(None, "", "fallback"), "fallback")
        self.assertIsNone(_first_present_text(None, ""))

    def test_shared_top_play_rows_extracts_player_name_for_hitter_pitcher_markets(self) -> None:
        # Real gap found 2026-07-23: game["shared_top_play_rows"] (a generic
        # display-panel highlights list, game_board_contract.py's
        # _build_top_play_rows) has no dedicated player field at all -- the
        # panel title becomes "market" and each item's free text becomes
        # "pick". For MLB hitter/pitcher stat panels that text is
        # consistently "OVER/UNDER <Player Name>", confirmed live against
        # production: every "hitter hits"/"hitter rbi"/etc. candidate on the
        # board showed a blank entity and a blank Projected value because
        # the player name was never extracted out of the pick text.
        game = self._sample_game(
            shared_top_play_rows=[
                {"heading": "Hitter Hits", "name": "OVER Brooks Lee"},
                {"heading": "Pitcher Strikeouts", "name": "UNDER Gerrit Cole"},
            ]
        )
        candidates = _game_bet_candidates_from_game({"slug": "mlb"}, game, fallback_epoch=0.0)
        hits = next(c for c in candidates if c["market"] == "Hitter Hits")
        strikeouts = next(c for c in candidates if c["market"] == "Pitcher Strikeouts")
        self.assertEqual(hits["entity"], "Brooks Lee")
        self.assertEqual(hits["player_name"], "Brooks Lee")
        self.assertEqual(strikeouts["entity"], "Gerrit Cole")

    def test_shared_top_play_rows_leaves_entity_blank_for_game_level_markets(self) -> None:
        game = self._sample_game(shared_top_play_rows=[{"heading": "Top Plays", "name": "OVER 8.5"}])
        candidates = _game_bet_candidates_from_game({"slug": "mlb"}, game, fallback_epoch=0.0)
        self.assertIsNone(candidates[0]["entity"])

    def test_game_market_recommendation_over_line_pick_is_not_mistaken_for_a_player_name(self) -> None:
        # Regression guard: game_market_recommendations rows use the same
        # "Over <value>" pick-text convention, except the remainder is a
        # numeric line, not a player name -- must never collide with the
        # extraction added for shared_top_play_rows above.
        game = self._sample_game(
            game_market_recommendations=[{"market_label": "Hitter Total Bases", "selection": "Over 1.5", "line": 1.5}]
        )
        candidates = _game_bet_candidates_from_game({"slug": "mlb"}, game, fallback_epoch=0.0)
        self.assertIsNone(candidates[0]["entity"])

    def test_prop_item_from_rank_card_derives_team_from_matchup_labels(self) -> None:
        card = {
            "title": "Jayson Tatum Over 28.5",
            "meta": "BOS @ NYK",
            "summary": "Tatum projected for 31.2 points as a member of BOS.",
            "metrics": [{"label": "Projected", "value": "31.2"}],
        }
        item = _prop_item_from_rank_card(card, sport_slug="nba")
        self.assertEqual(item["team"], "BOS")

    def test_prop_item_from_rank_card_stamps_real_player_name_not_full_title(self) -> None:
        # Board-alignment audit, found live 2026-08-01 against a real live
        # WNBA game: this row never carried its own "player_name" -- only
        # "name" (== the full pick title, e.g. "Alyssa Thomas UNDER 8.5").
        # _prop_candidate_from_item (intelligence.py) falls back to "name"
        # when "player_name" is missing, so the pick text became the
        # dedup-merge "subject" -- a rank-card-sourced pregame duplicate
        # for the same player+market never matched its correctly-live-wired
        # twin (real subject "Alyssa Thomas") from a different pipeline, so
        # the two never merged and the pregame duplicate stayed stuck with
        # no live_projection/actual even once its game went live.
        card = {"title": "Alyssa Thomas UNDER 8.5", "meta": "NYL @ PHX", "eyebrow": "PHX"}
        item = _prop_item_from_rank_card(card, sport_slug="wnba")
        self.assertEqual(item["player_name"], "Alyssa Thomas")
        self.assertEqual(item["name"], "Alyssa Thomas UNDER 8.5")

    def test_prop_item_from_rank_card_derives_team_from_eyebrow(self) -> None:
        # wnba/picks.py and nba/picks.py's _card_from_pick() put the pick's
        # team abbreviation in "eyebrow" (falling back to the market label
        # when no team is known), never in title/badge/summary -- this is
        # the shape real rank-card-sourced WNBA/NBA props actually have.
        card = {
            "title": "Kelsey Plum OVER 2.5",
            "eyebrow": "LVA",
            "meta": "LVA @ SEA",
            "badge": "38.1% EV",
            "metrics": [{"label": "Win prob", "value": "45.5%"}],
        }
        item = _prop_item_from_rank_card(card, sport_slug="wnba")
        self.assertEqual(item["team"], "LVA")

    def test_prop_item_from_rank_card_pick_prefers_title_over_ev_badge(self) -> None:
        # Real bug found in production: wnba/nba's _card_from_pick() always
        # sets "badge" to an EV-percentage string ("20.4% EV") and never
        # labels a metric "pick"/"lean"/"selection"/"side" -- since badge is
        # always truthy, `badge or _metric_value(...)` always won, so every
        # rank-card-sourced prop's pick/selection ended up as a bare EV
        # percentage instead of the real pick (e.g. "Gabby Williams OVER
        # 1.5"). That corrupted "pick" then propagated into "selection" and
        # even "name" downstream (_attach_intelligence_response_aliases
        # recomputes name from pick), so the card's title, pick, and
        # selection all showed the same nonsensical percentage.
        card = {
            "title": "Gabby Williams OVER 1.5",
            "eyebrow": "GSV",
            "meta": "GSV @ SEA",
            "badge": "20.4% EV",
            "metrics": [
                {"label": "Win prob", "value": "58.2%"},
                {"label": "EV", "value": "20.4%"},
                {"label": "Price", "value": "+102"},
                {"label": "Score", "value": "8.1"},
            ],
        }
        item = _prop_item_from_rank_card(card, sport_slug="wnba")
        self.assertEqual(item["pick"], "Gabby Williams OVER 1.5")
        self.assertNotIn("EV", item["pick"])

    def test_prop_item_from_rank_card_surfaces_list_items_reasoning(self) -> None:
        # Rank cards carry up to 4 real reasoning bullets in "list_items"
        # (e.g. wnba/picks.py's top_play_reasons) that were never read here
        # -- only the one-line "summary" survived, so the actual evidence
        # behind a pick disappeared before it reached the Betting Board.
        card = {
            "title": "Gabby Williams OVER 1.5",
            "eyebrow": "GSV",
            "meta": "GSV @ SEA",
            "badge": "20.4% EV",
            "summary": "Model favors the over.",
            "list_items": ["Averaging 2.1 over last 10 games.", "Opponent allows high three-point volume."],
            "metrics": [{"label": "Win prob", "value": "58.2%"}],
        }
        item = _prop_item_from_rank_card(card, sport_slug="wnba")
        self.assertIn("Model favors the over.", item["detail"])
        self.assertIn("Averaging 2.1 over last 10 games.", item["detail"])
        self.assertIn("Opponent allows high three-point volume.", item["detail"])

    def test_compact_prop_rows_carries_team_from_shared_prop_rows(self) -> None:
        game = {
            "away": {"abbr": "BOS", "name": "Boston Celtics"},
            "home": {"abbr": "NYK", "name": "New York Knicks"},
            "summary": "Test game",
            "status": "Scheduled",
            "shared_prop_rows": [
                {"name": "Jayson Tatum", "detail": "Over 28.5", "value": "-", "team": "BOS"},
            ],
        }

        rows = _compact_prop_rows([game])

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["team"], "BOS")

    def test_game_sim_vs_line_reasoning_reads_full_game_period_row(self) -> None:
        # game_board_contract.py's _build_period_rows already computes a
        # sim-vs-market-line comparison (main/market/best_edge) onto the
        # same game dict _game_bet_candidates_from_game has in scope --
        # this was never read, so ATS/Total/Moneyline candidates never
        # carried the same sim-vs-line context the sport pages show.
        game = self._sample_game(
            shared_period_rows=[
                {
                    "label": "Full Game",
                    "main": "BOS 108.2 - NYK 104.5",
                    "market": "ATS NYK -3.5 | Total 210.5",
                    "best_edge": "ATS +1.2 | Total +2.1",
                }
            ]
        )
        reasoning = _game_sim_vs_line_reasoning(game)
        self.assertIn("Sim: BOS 108.2 - NYK 104.5", reasoning)
        self.assertIn("Market: ATS NYK -3.5 | Total 210.5", reasoning)
        self.assertIn("Model edge vs. line: ATS +1.2 | Total +2.1", reasoning)

    def test_game_sim_vs_line_reasoning_flows_into_moneyline_candidate_detail(self) -> None:
        game = self._sample_game(
            betting={"away_ml": -120, "home_ml": 105, "p_away_win": 0.55, "p_home_win": 0.45},
            shared_period_rows=[
                {"label": "Full Game", "main": "BOS 108.2 - NYK 104.5", "market": "ATS NYK -3.5", "best_edge": "ATS +1.2"}
            ],
        )
        candidates = _game_bet_candidates_from_game({"slug": "nba"}, game, fallback_epoch=0.0)
        moneyline = next(c for c in candidates if c["market"] == "Moneyline" and c["pick"] == "Away ML")
        self.assertIn("Model edge vs. line: ATS +1.2", moneyline["detail"])
        self.assertEqual(moneyline["sim_context"], _game_sim_vs_line_reasoning(game))

    def test_game_sim_vs_line_reasoning_returns_none_without_period_rows(self) -> None:
        game = self._sample_game()
        self.assertIsNone(_game_sim_vs_line_reasoning(game))

    def test_moneyline_candidate_is_live_when_game_is_live_even_with_no_live_prop_rows(self) -> None:
        # Real bug: live_odds_game_ids used to be built from live_prop_items
        # alone (_game_identity_set(live_prop_items)), so a genuinely live
        # game with zero live player-prop rows (an artifact gap, no active
        # props for this matchup, an event-id mismatch in that one lookup)
        # got every one of its OTHER candidates -- moneyline, spread, total,
        # nothing to do with player props -- wrongly marked not-live too,
        # because an empty identity set forces is_live=False for any game
        # not in it. The fix builds the set from the game's own reliable
        # in-progress status instead of from live-prop-row availability.
        game = self._sample_game(
            betting={"away_ml": -120, "home_ml": 105, "p_away_win": 0.55, "p_home_win": 0.45},
            game_id="401700001",
            status={"in_progress": True, "final": False},
        )
        live_odds_game_ids = {_game_identifier(game)}  # what the fixed construction now produces
        candidates = _game_bet_candidates_from_game({"slug": "wnba"}, game, fallback_epoch=0.0, live_odds_game_ids=live_odds_game_ids)
        moneyline = next(c for c in candidates if c["market"] == "Moneyline" and c["pick"] == "Away ML")
        self.assertTrue(moneyline["is_live"])

        # The old, buggy construction: an empty set because live_prop_items
        # had nothing for this game, even though the game itself is live.
        candidates_with_empty_live_odds_set = _game_bet_candidates_from_game({"slug": "wnba"}, game, fallback_epoch=0.0, live_odds_game_ids=set())
        moneyline_old = next(c for c in candidates_with_empty_live_odds_set if c["market"] == "Moneyline" and c["pick"] == "Away ML")
        self.assertFalse(moneyline_old["is_live"])

    def test_gamelens_sourced_candidate_does_not_force_live_from_decorative_label(self) -> None:
        # Real bug found in production: a WNBA game hours before tip
        # (status.in_progress=False) produced contradictory candidates for
        # the SAME game -- Spread stayed correctly pregame, but Moneyline
        # showed is_live=True. gameLens entries default their label to
        # "Live" (lens.get("label", "Live")) purely as a decorative section
        # name, even when the lens is open-but-pregame; the old fallback_live
        # heuristic treated any "live" substring in the market text as
        # real evidence, so "Live Moneyline" force-flipped is_live=True
        # while the plain "Spread" market (from the betting dict) did not.
        game = self._sample_game(
            betting={"away_ml": -120, "home_ml": 105, "p_away_win": 0.55, "p_home_win": 0.45,
                     "home_puck_line": -9.5, "away_puck_line": 9.5, "home_spread": -9.5,
                     "p_home_cover": 0.55, "p_away_cover": 0.45},
            status={"in_progress": False, "final": False, "status": "Scheduled"},
            gameLens=[
                {
                    "closed": False,
                    "markets": {"moneyline": {"pick": "Away ML", "odds": -120, "edge": 4.5, "p_win": 0.55}},
                }
            ],
        )
        candidates = _game_bet_candidates_from_game({"slug": "wnba"}, game, fallback_epoch=0.0)
        spread = next(c for c in candidates if c["market"] == "Spread" and c["pick"].startswith("Away"))
        lens_moneyline = next(c for c in candidates if c["market"] == "Live Moneyline")
        self.assertFalse(spread["is_live"])
        self.assertFalse(lens_moneyline["is_live"])

    def test_gamelens_candidates_use_segment_projection_as_live_projection_when_market_has_none(self) -> None:
        # #131 follow-up, confirmed live 2026-07-29: live MLB gameLens
        # candidates (moneyline/spread/total, every segment) showed
        # projected="-" even though mlb/live_lens.py's
        # _live_lens_segments_from_card already computes a real model
        # projection (total runs / home margin) per segment -- it just lives
        # as segment["projection"], a SIBLING of segment["markets"], which
        # this loop's scan never looked at (it only ever checked inside the
        # individual market dict, which never has these fields).
        #
        # Layer 2 projection/live-projection/live-actual follow-up: that
        # segment projection is LIVE re-sim data, never a true pregame value
        # -- it now lands in live_projection. projected stays "-" here since
        # this fixture has no preceding plain betting-dict candidate for the
        # same market+side to cross-reference (no "betting" override passed).
        game = self._sample_game(
            status={"in_progress": True, "final": False, "status": "In Progress"},
            gameLens=[
                {
                    "closed": False,
                    "label": "Full game",
                    "projection": {"total": 8.4, "homeMargin": 1.2},
                    "markets": {
                        "total": {"pick": "Over 7.5", "line": 7.5, "odds": -110, "edge": 3.1, "p_win": 0.54},
                        "spread": {"pick": "Home -1.5", "homeLine": -1.5, "odds": -105, "edge": 2.2, "p_win": 0.53},
                        "moneyline": {"pick": "Home ML", "odds": -130, "edge": 5.5, "p_win": 0.58},
                    },
                }
            ],
        )
        candidates = _game_bet_candidates_from_game({"slug": "mlb"}, game, fallback_epoch=0.0)
        total = next(c for c in candidates if c["market"] == "Full game Total")
        spread = next(c for c in candidates if c["market"] == "Full game Spread")
        moneyline = next(c for c in candidates if c["market"] == "Full game Moneyline")
        self.assertEqual(total["projected"], "-")
        self.assertEqual(total["live_projection"], "8.4")
        self.assertEqual(spread["projected"], "-")
        self.assertEqual(spread["live_projection"], "1.2")
        self.assertEqual(moneyline["projected"], "-")
        self.assertEqual(moneyline["live_projection"], "58.0%")

    def test_gamelens_candidate_prefers_a_real_market_projection_over_the_segment_fallback(self) -> None:
        # A market-level explicit override (market.get("projected")) is a
        # genuinely pregame-shaped value some market builders attach
        # directly (confirmed real: NBA/WNBA gameLens markets can carry both
        # a "projection" AND a separate "live_projection" as siblings) -- it
        # still wins for "projected" over the segment-level fallback, which
        # is always live/current-segment data and has no market-level
        # explicit override to compete with here, so it lands in
        # "live_projection" instead.
        game = self._sample_game(
            status={"in_progress": True, "final": False, "status": "In Progress"},
            gameLens=[
                {
                    "closed": False,
                    "label": "Full game",
                    "projection": {"total": 8.4, "homeMargin": 1.2},
                    "markets": {
                        "total": {"pick": "Over 7.5", "line": 7.5, "odds": -110, "projected": 9.9},
                    },
                }
            ],
        )
        candidates = _game_bet_candidates_from_game({"slug": "mlb"}, game, fallback_epoch=0.0)
        total = next(c for c in candidates if c["market"] == "Full game Total")
        self.assertEqual(total["projected"], "9.9")
        self.assertEqual(total["live_projection"], "8.4")

    def test_gamelens_candidate_cross_references_pregame_projection_from_plain_candidate(self) -> None:
        # A live game whose plain betting dict already produced a real
        # pregame Moneyline candidate ("Home ML", projected win prob) --
        # the gameLens loop's "Full game Moneyline" candidate for the same
        # side should pick up that same pregame value, since a gameLens
        # segment never carries one of its own.
        game = self._sample_game(
            status={"in_progress": True, "final": False, "status": "In Progress"},
            betting={"away_ml": -120, "home_ml": 105, "p_away_win": 0.45, "p_home_win": 0.55},
            gameLens=[
                {
                    "closed": False,
                    "label": "Full game",
                    "projection": {},
                    "markets": {
                        "moneyline": {"pick": "Home ML", "odds": -130, "edge": 5.5, "p_win": 0.58},
                    },
                }
            ],
        )
        candidates = _game_bet_candidates_from_game({"slug": "mlb"}, game, fallback_epoch=0.0)
        plain_moneyline = next(c for c in candidates if c["market"] == "Moneyline" and c["pick"] == "Home ML")
        lens_moneyline = next(c for c in candidates if c["market"] == "Full game Moneyline")
        self.assertEqual(plain_moneyline["projected"], "55.0%")
        self.assertEqual(lens_moneyline["projected"], "55.0%")
        self.assertEqual(lens_moneyline["live_projection"], "58.0%")

    def test_gamelens_candidate_actual_reads_real_box_score_segment(self) -> None:
        # lens["actualSegment"] carries the real box-score segment totals --
        # previously never read at all, so every gameLens candidate's
        # "actual" silently stayed "-".
        game = self._sample_game(
            status={"in_progress": True, "final": False, "status": "In Progress"},
            gameLens=[
                {
                    "closed": False,
                    "label": "Full game",
                    "projection": {"total": 8.4, "homeMargin": 1.2},
                    "actualSegment": {"home": 5, "away": 3},
                    "markets": {
                        "total": {"pick": "Over 7.5", "line": 7.5, "odds": -110, "edge": 3.1, "p_win": 0.54},
                        "moneyline": {"pick": "Home ML", "odds": -130, "edge": 5.5, "p_win": 0.58},
                    },
                }
            ],
        )
        candidates = _game_bet_candidates_from_game({"slug": "mlb"}, game, fallback_epoch=0.0)
        total = next(c for c in candidates if c["market"] == "Full game Total")
        moneyline = next(c for c in candidates if c["market"] == "Full game Moneyline")
        self.assertEqual(float(total["actual"]), 8.0)
        self.assertEqual(float(moneyline["actual"]), 2.0)

    def test_game_status_state_does_not_let_unrelated_text_override_known_in_progress_false(self) -> None:
        # Real bug found in production: every WNBA game carries
        # summary="Consensus market snapshot" -- "snapshot" contains "ot",
        # one of the (very loose) live-token substrings this function
        # falls back to checking. That text fallback used to run
        # unconditionally (OR'd in alongside the structured in_progress
        # check), so it silently overrode a definitive in_progress=False
        # and made every hours-from-tip game read as "live".
        game = self._sample_game(
            status={"in_progress": False, "final": False, "status": "Scheduled"},
            summary="Consensus market snapshot",
            detail="7/22 - 10:00 PM EDT",
        )
        self.assertEqual(_game_status_state(game), "scheduled")

    def test_game_status_state_still_uses_text_fallback_when_no_structured_signal(self) -> None:
        game = self._sample_game(status={}, summary="Second quarter under way", detail="")
        self.assertEqual(_game_status_state(game), "live")

    def test_shared_game_state_live_false_beats_the_shared_is_live_flag(self) -> None:
        # Reported by the user 2026-07-26 and confirmed from production: the
        # Layer 2 board published yesterday's finished MLS fixtures as LIVE
        # picks. The payload contradicted itself inside one object --
        # shared_is_live: true alongside
        # shared_game_state: {"live": false, "clock": "", "period": null} --
        # and the loose derived flag beat the structured state.
        #
        # Field shape copied from the real payload: soccer carries `status` as
        # a display STRING, which _game_status_text does not read at all, so
        # `detail` is what makes the text non-empty. Getting that wrong makes
        # this function return "" early and the test pass for the wrong reason.
        game = self._sample_game(
            status="Sat, Jul 25 · 7:30 PM CT",
            detail="2026-07-26",
            shared_is_live=True,
            shared_game_state={"live": False, "final": False, "clock": "", "period": None},
            summary="",
        )
        self.assertNotEqual(_game_status_state(game), "live")

    def test_shared_game_state_live_false_resolves_to_scheduled_not_empty(self) -> None:
        # #150. The test above only checked "not live" -- under the pre-fix
        # code this game resolved to "" (not "scheduled"), which is exactly
        # what zeroed out get_active_games() for every upcoming soccer
        # fixture: get_active_games only keeps games whose state is
        # "scheduled" or "live", so "" silently excluded them, which then
        # zeroed dashboard_games/home_rails for the whole sport in
        # _build_sport_overview (hydrated_game_ids stayed empty with no
        # live games and no wnba-style fallback). Same shape as the test
        # above (soccer's real payload: `status` is a display string,
        # `shared_game_state` explicitly says not-live/not-final, and
        # neither `detail` nor `summary` contains a "scheduled"/"preview"/
        # "pregame"/"warmup" token) -- confirmed live 2026-07-30 against a
        # real upcoming MLS fixture.
        game = self._sample_game(
            status="Fri, Jul 31 · 6:30 PM CT",
            detail="MLS",
            shared_is_live=True,
            shared_game_state={"live": False, "final": False, "clock": "", "period": None},
            summary="Projected Toronto FC 1.3 @ New York City FC 1.8 (total 3.1).",
        )
        self.assertEqual(_game_status_state(game), "scheduled")

    def test_shared_is_live_still_decides_when_nothing_contradicts_it(self) -> None:
        # The fix must only bite where a structured source actually disagrees.
        # With no in_progress and no shared_game_state, shared_is_live is still
        # the signal -- several sports rely on exactly that.
        game = self._sample_game(status="", detail="2026-07-26", shared_is_live=True, summary="")
        self.assertEqual(_game_status_state(game), "live")

    def test_shared_game_state_final_is_terminal(self) -> None:
        game = self._sample_game(
            status="Sat, Jul 25 · 7:30 PM CT",
            detail="2026-07-26",
            shared_is_live=True,
            shared_game_state={"live": False, "final": True},
            summary="",
        )
        self.assertEqual(_game_status_state(game), "final")

    def test_game_status_state_still_detects_live_from_structured_in_progress(self) -> None:
        game = self._sample_game(
            status={"in_progress": True, "final": False, "status": "In Progress"},
            summary="Consensus market snapshot",
        )
        self.assertEqual(_game_status_state(game), "live")

    def test_game_status_state_ot_token_needs_word_boundary_even_with_no_structured_status(self) -> None:
        # Real bug found in production: some game objects (odds-sourced
        # rows feeding the intelligence board) never carry a status dict
        # with in_progress at all, so the text fallback is the ONLY signal
        # for them -- and a bare "ot" substring check still matched
        # "oddsapi_consensus market snapshot" (via "snapshot") even after
        # gating the fallback on in_progress being unknown. "ot" needs a
        # word boundary, not just a missing in_progress guard.
        game = self._sample_game(status={}, summary="oddsapi_consensus market snapshot", detail="")
        self.assertNotEqual(_game_status_state(game), "live")

    def test_game_status_state_still_detects_overtime_as_a_standalone_word(self) -> None:
        game = self._sample_game(status={}, summary="Tied game headed to OT", detail="")
        self.assertEqual(_game_status_state(game), "live")


if __name__ == "__main__":
    unittest.main()


class HomeCacheBoundingTests(unittest.TestCase):
    """The home overview/payload caches were plain dicts that were only ever
    read from and written to -- nothing removed an entry, ever.

    _HOME_OVERVIEW_TTL_SEC reads like a bound but is not one: it only decides
    whether an entry may be SERVED. Expired entries stayed resident and fresh
    ones were written alongside them, so the dicts grew for the life of the
    process, keyed by (sport, date) plus a ":skip_hydration" variant -- each
    value a fully hydrated sport overview. That is the retention shape behind
    the 2026-07-25 worker OOM: ~700MB idle early, past 1479MB later the same
    day.
    """

    def _cache(self, entries):
        return OrderedDict(entries)

    def test_expired_entries_are_reclaimed_not_just_ignored(self) -> None:
        cache = self._cache([("stale", (0.0, {"a": 1})), ("fresh", (1000.0, {"b": 2}))])
        home_module._prune_home_cache(cache, now=1000.0)
        self.assertEqual(list(cache.keys()), ["fresh"])

    def test_entry_count_is_capped(self) -> None:
        cache = self._cache([(f"k{i}", (1000.0, {"i": i})) for i in range(100)])
        home_module._prune_home_cache(cache, now=1000.0)
        self.assertEqual(len(cache), home_module._HOME_CACHE_MAX_ENTRIES)

    def test_eviction_is_oldest_first(self) -> None:
        cache = self._cache([(f"k{i}", (1000.0, {"i": i})) for i in range(40)])
        home_module._prune_home_cache(cache, now=1000.0)
        self.assertNotIn("k0", cache)
        self.assertIn("k39", cache)

    def test_a_key_that_is_never_read_again_still_gets_reclaimed(self) -> None:
        # The leak's actual shape: yesterday's date, or a sport that went out
        # of season, is never requested again -- so a read-time-only sweep
        # could never reclaim exactly the entries that leak.
        cache = self._cache([("yesterday:mlb", (0.0, {"big": "payload"}))])
        home_module._prune_home_cache(cache, now=5000.0)
        self.assertEqual(len(cache), 0)

    def test_fresh_entries_within_ttl_survive(self) -> None:
        # Bounding must not defeat the cache: entries inside the TTL stay.
        now = 1000.0
        cache = self._cache([("a", (now, {"x": 1})), ("b", (now - 1.0, {"x": 2}))])
        home_module._prune_home_cache(cache, now=now)
        self.assertEqual(sorted(cache.keys()), ["a", "b"])

    def test_player_id_index_cache_is_left_unbounded_on_purpose(self) -> None:
        # Keyed by sport slug, populated only for nba/wnba, and intentionally
        # permanent -- an ID lookup index, not hydrated game state.
        self.assertIsInstance(home_module._BASKETBALL_PLAYER_ID_CACHE, dict)
        self.assertNotIsInstance(home_module._BASKETBALL_PLAYER_ID_CACHE, OrderedDict)


class MLBLiveScoreFallbackTests(unittest.TestCase):
    """Confirmed live: MLB StatsAPI's linescore.teams.<side>.runs can come
    back null for one side while the other has a real number, on both live
    and final games -- _apply_mlb_live_scores only ever set a side's score
    when that value was not None, so the affected side kept no "score" key
    at all (MLB's base game dict never carries one either) and rendered as
    an ambiguous "-" on the Layer 2 mini game-card strip right next to its
    opponent's real number."""

    def _game(self):
        return {"gamePk": 1, "away": {"abbr": "KC"}, "home": {"abbr": "MIN"}, "status": {}}

    def test_missing_side_defaults_to_zero_when_live(self) -> None:
        live_states = {1: {"away_pts": 4, "home_pts": None, "in_progress": True, "final": False, "status": "Bot 8"}}
        with patch("syndicate.blueprints.home._mlb_feed_live_states", return_value=live_states):
            enriched = home_module._apply_mlb_live_scores([self._game()], "2026-07-29")
        self.assertEqual(enriched[0]["away"]["score"], 4)
        self.assertEqual(enriched[0]["home"]["score"], 0)
        self.assertEqual(enriched[0]["status"]["home_score"], 0)

    def test_missing_side_defaults_to_zero_when_final(self) -> None:
        live_states = {1: {"away_pts": None, "home_pts": 1, "in_progress": False, "final": True, "status": "Final"}}
        with patch("syndicate.blueprints.home._mlb_feed_live_states", return_value=live_states):
            enriched = home_module._apply_mlb_live_scores([self._game()], "2026-07-29")
        self.assertEqual(enriched[0]["away"]["score"], 0)
        self.assertEqual(enriched[0]["home"]["score"], 1)

    def test_no_live_state_leaves_game_untouched(self) -> None:
        with patch("syndicate.blueprints.home._mlb_feed_live_states", return_value={1: None}):
            enriched = home_module._apply_mlb_live_scores([self._game()], "2026-07-29")
        self.assertNotIn("score", enriched[0]["away"])
        self.assertNotIn("score", enriched[0]["home"])


class SoccerPropCommenceTimePropagationTests(unittest.TestCase):
    """A soccer prop candidate carried no date field of its own, so the
    shared resolve_candidate_game_date fallback (checks commence_time/
    start_time_utc/game_time_utc/game_date, in that order) always fell
    through to the board's context date instead of the fixture's real date.
    Confirmed live 2026-08-05: 3 "Anytime Goalscorer" candidates for an Aug 8
    MLS match all carried game_date Aug 5 (today), which pointed the
    odds_history join at the wrong shard -- the odds data existed, just
    under a date these candidates never asked for.

    Soccer's own dashboard game dicts (cards.py's _match_to_game/
    _unsimulated_game) DO carry the real kickoff, under "scheduled_start_utc"
    -- a key resolve_candidate_game_date does not check. _finalize_home_prop_rows
    already copies several other matched_game fields (team labels, gamePk,
    game_id, event_id) onto the prop item; this was the one field that
    pattern was missing.
    """

    def _matched_game(self, *, scheduled_start_utc: str | None = "2026-08-08T23:30:00Z") -> dict:
        return {
            "gamePk": "evt-761469",
            "event_id": "761469",
            "away": {"abbr": "HOU", "name": "Houston Dynamo"},
            "home": {"abbr": "NE", "name": "New England Revolution"},
            "scheduled_start_utc": scheduled_start_utc,
        }

    def _prop_row(self) -> dict:
        return {
            "name": "Carles Gil Anytime Goalscorer",
            "market": "Anytime Goalscorer",
            "player_name": "Carles Gil",
            "matchup": "HOU @ NE",
        }

    def test_the_matched_games_kickoff_becomes_the_props_commence_time(self) -> None:
        game_index = home_module._home_prop_game_index([self._matched_game()])
        with patch.object(home_module, "_home_prop_matched_game", return_value=self._matched_game()):
            finalized = home_module._finalize_home_prop_rows([self._prop_row()], slug="soccer")
        self.assertEqual(finalized[0].get("commence_time"), "2026-08-08T23:30:00Z")

    def test_an_existing_commence_time_on_the_row_is_never_overwritten(self) -> None:
        row = self._prop_row()
        row["commence_time"] = "2026-08-09T00:00:00Z"
        with patch.object(home_module, "_home_prop_matched_game", return_value=self._matched_game()):
            finalized = home_module._finalize_home_prop_rows([row], slug="soccer")
        self.assertEqual(finalized[0]["commence_time"], "2026-08-09T00:00:00Z")

    def test_no_matched_game_leaves_commence_time_unset(self) -> None:
        with patch.object(home_module, "_home_prop_matched_game", return_value=None):
            finalized = home_module._finalize_home_prop_rows([self._prop_row()], slug="soccer")
        self.assertNotIn("commence_time", finalized[0])

    def test_resolve_candidate_game_date_finds_it_on_finalize_rows_own_output(self) -> None:
        # NOT actually end-to-end, despite the name this test had before --
        # it stops at _finalize_home_prop_rows's own return value. That gap
        # is exactly how the real bug shipped invisibly: this assertion
        # passed while the SERVED board still showed the wrong date, because
        # _build_prop_dashboard_row (intelligence.py's actual consumer of
        # this data) reconstructs a brand new dict from `item` and dropped
        # commence_time entirely -- confirmed live 2026-08-05 via a
        # persisted diagnostic showing the match succeeding and
        # commence_time being set correctly right here, with the value gone
        # by the time it reached the board. See
        # test_commence_time_survives_all_the_way_through_the_dashboard_row
        # below for the assertion that actually would have caught it.
        from syndicate.features.shared.intelligence_contracts import resolve_candidate_game_date

        with patch.object(home_module, "_home_prop_matched_game", return_value=self._matched_game()):
            finalized = home_module._finalize_home_prop_rows([self._prop_row()], slug="soccer")
        self.assertEqual(resolve_candidate_game_date(finalized[0], fallback="2026-08-05"), "2026-08-08")

    def test_commence_time_survives_all_the_way_through_the_dashboard_row(self) -> None:
        # The real end-to-end path: _finalize_home_prop_rows's output feeds
        # _build_prop_dashboard_row (imported into intelligence.py and
        # called from there to build the actual board candidate), which
        # used to construct its returned dict from scratch and never copy
        # commence_time across. Both hops must be exercised together, or a
        # regression at either one goes undetected -- which is exactly what
        # happened here.
        from syndicate.blueprints.home import _build_prop_dashboard_row
        from syndicate.features.shared.intelligence_contracts import resolve_candidate_game_date

        with patch.object(home_module, "_home_prop_matched_game", return_value=self._matched_game()):
            finalized = home_module._finalize_home_prop_rows([self._prop_row()], slug="soccer")
        dashboard_row = _build_prop_dashboard_row(
            {"slug": "soccer", "name": "Soccer"}, finalized[0], default_surface="Pregame props"
        )
        self.assertEqual(dashboard_row.get("commence_time"), "2026-08-08T23:30:00Z")
        self.assertEqual(resolve_candidate_game_date(dashboard_row, fallback="2026-08-05"), "2026-08-08")


class NflGameMarketRecommendationRowsTests(unittest.TestCase):
    """Coverage for _nfl_game_market_recommendation_rows -- the same class
    of Layer 1 -> Layer 2 shape translation _mlb_game_market_recommendation_rows
    provides for MLB, mirrored here for NFL's build_nfl_market_board /
    build_nfl_preseason_market_board join_odds_to_sim output."""

    @staticmethod
    def _row(*, market: str, side: str, market_type: str = "game", line=None, odds=None, sim_projection=None, model_side=None, projected_value=None, join_status="matched", join_note=None, game_id="g1"):
        return {
            "game_id": game_id,
            "market": market,
            "market_type": market_type,
            "side": side,
            "line": line,
            "odds": odds,
            "sim_projection": sim_projection,
            "model_side": model_side,
            "projected_value": projected_value,
            "join_status": join_status,
            "join_note": join_note,
        }

    def test_picks_the_models_own_favored_side_per_market_not_always_home(self) -> None:
        # Moneyline favors home, Spread favors away, Total favors over --
        # proves the "pick model_side" logic, not a hardcoded home/over bias.
        board_rows = [
            self._row(market="Moneyline", side="home", odds=-150, sim_projection=0.62, model_side="home"),
            self._row(market="Moneyline", side="away", odds=130, sim_projection=0.38, model_side="home"),
            self._row(market="Spread", side="home", line=-3.5, odds=-110, sim_projection=0.45, model_side="away", projected_value=1.2),
            self._row(market="Spread", side="away", line=3.5, odds=-108, sim_projection=0.55, model_side="away", projected_value=1.2),
            self._row(market="Total", side="over", line=45.5, odds=-105, sim_projection=0.53, model_side="over", projected_value=47.0),
            self._row(market="Total", side="under", line=45.5, odds=-115, sim_projection=0.47, model_side="over", projected_value=47.0),
        ]
        rows = _nfl_game_market_recommendation_rows("g1", board_rows)
        self.assertEqual(len(rows), 3)
        moneyline = next(r for r in rows if r["market_label"] == "Moneyline")
        spread = next(r for r in rows if r["market_label"] == "Spread")
        total = next(r for r in rows if r["market_label"] == "Total")

        self.assertEqual(moneyline["display_pick"], "Home ML")
        self.assertEqual(moneyline["selection"], "home")
        self.assertEqual(moneyline["odds"], -150)
        self.assertAlmostEqual(moneyline["confidence"], 0.62)
        self.assertEqual(moneyline["projected"], "62.0%")

        self.assertEqual(spread["display_pick"], "Away 3.5")
        self.assertEqual(spread["selection"], "away")
        self.assertEqual(spread["odds"], -108)
        self.assertAlmostEqual(spread["confidence"], 0.55)
        self.assertEqual(spread["projected"], 1.2)

        self.assertEqual(total["display_pick"], "Over 45.5")
        self.assertEqual(total["selection"], "over")
        self.assertEqual(total["odds"], -105)
        self.assertAlmostEqual(total["confidence"], 0.53)
        self.assertEqual(total["projected"], 47.0)

    def test_market_with_no_odds_coverage_is_skipped_not_fabricated(self) -> None:
        # Total has a real sim projection and model_side, but neither side
        # ever got a real quoted price (a line with no book price attached)
        # -- there is nothing bettable to show, so it must be dropped
        # entirely rather than emitted with odds=None.
        board_rows = [
            self._row(market="Moneyline", side="home", odds=-150, sim_projection=0.62, model_side="home"),
            self._row(market="Moneyline", side="away", odds=130, sim_projection=0.38, model_side="home"),
            self._row(market="Total", side="over", line=45.5, odds=None, sim_projection=0.53, model_side="over", projected_value=47.0),
            self._row(market="Total", side="under", line=45.5, odds=None, sim_projection=0.47, model_side="over", projected_value=47.0),
        ]
        rows = _nfl_game_market_recommendation_rows("g1", board_rows)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["market_label"], "Moneyline")

    def test_market_with_no_sim_coverage_is_skipped(self) -> None:
        # unmatched_no_sim_coverage: real odds exist but the model never
        # priced this market -- model_side stays None on every sibling row.
        board_rows = [
            self._row(market="Spread", side="home", line=-3.5, odds=-110, sim_projection=None, model_side=None, join_status="unmatched_no_sim_coverage"),
            self._row(market="Spread", side="away", line=3.5, odds=-110, sim_projection=None, model_side=None, join_status="unmatched_no_sim_coverage"),
        ]
        self.assertEqual(_nfl_game_market_recommendation_rows("g1", board_rows), [])

    def test_prop_rows_are_ignored(self) -> None:
        board_rows = [
            {"game_id": "g1", "market": "passing_yards", "market_type": "prop", "side": "over", "line": 230.5, "odds": -110, "sim_projection": 0.55, "model_side": "over", "projected_value": 240.0},
        ]
        self.assertEqual(_nfl_game_market_recommendation_rows("g1", board_rows), [])

    def test_rows_from_a_different_game_id_are_ignored(self) -> None:
        board_rows = [
            self._row(market="Moneyline", side="home", odds=-150, sim_projection=0.62, model_side="home", game_id="other-game"),
            self._row(market="Moneyline", side="away", odds=130, sim_projection=0.38, model_side="home", game_id="other-game"),
        ]
        self.assertEqual(_nfl_game_market_recommendation_rows("g1", board_rows), [])


class NflDataProviderGamesTests(unittest.TestCase):
    """Coverage for _NFLDataProvider.games() -- the regular-season/
    preseason phase gate plus game_market_recommendations stamping."""

    @staticmethod
    def _board(*, game_id: str) -> dict:
        rows = [
            {"game_id": game_id, "market": "Moneyline", "market_type": "game", "side": "home", "line": None, "odds": -150, "sim_projection": 0.62, "model_side": "home", "projected_value": None, "join_status": "matched", "join_note": "Model favors the home side."},
            {"game_id": game_id, "market": "Moneyline", "market_type": "game", "side": "away", "line": None, "odds": 130, "sim_projection": 0.38, "model_side": "home", "projected_value": None, "join_status": "matched", "join_note": None},
        ]
        return {"season": 2026, "week": 1, "games": [{"gamePk": game_id, "rows": rows}]}

    def test_regular_season_games_carry_game_market_recommendations(self) -> None:
        context = SportContext(slug="nfl", context_label="2026 Week 1", season=2026, week=1)
        cards_payload = {"games": [{"gamePk": "g1", "away": {"name": "Away Team"}, "home": {"name": "Home Team"}}]}
        with patch("syndicate.features.nfl.cards.build_cards_page_context", return_value=cards_payload), patch(
            "syndicate.features.nfl.cards.build_nfl_market_board", return_value=self._board(game_id="g1")
        ):
            games = _NFLDataProvider().games(context, is_active_today=True)
        self.assertEqual(len(games), 1)
        self.assertTrue(games[0].get("game_market_recommendations"))
        self.assertEqual(games[0]["game_market_recommendations"][0]["market_label"], "Moneyline")

    def test_regular_season_game_that_already_has_recommendations_is_not_overwritten(self) -> None:
        context = SportContext(slug="nfl", context_label="2026 Week 1", season=2026, week=1)
        existing = [{"market_label": "Existing", "display_pick": "Keep me"}]
        cards_payload = {"games": [{"gamePk": "g1", "game_market_recommendations": existing}]}
        with patch("syndicate.features.nfl.cards.build_cards_page_context", return_value=cards_payload), patch(
            "syndicate.features.nfl.cards.build_nfl_market_board", return_value=self._board(game_id="g1")
        ):
            games = _NFLDataProvider().games(context, is_active_today=True)
        self.assertEqual(games[0]["game_market_recommendations"], existing)

    def test_preseason_games_carry_game_market_recommendations_when_a_target_week_exists(self) -> None:
        context = SportContext(slug="nfl", context_label="2026 Preseason", season=2026, week=None)
        preseason_payload = {"games": [{"gamePk": "g1", "away": {"name": "Away Team"}, "home": {"name": "Home Team"}}]}
        with patch("syndicate.features.nfl.sources.preseason_target_week", return_value=1), patch(
            "syndicate.features.nfl.preseason_cards.build_preseason_cards_page_context", return_value=preseason_payload
        ), patch("syndicate.features.nfl.preseason_cards.build_nfl_preseason_market_board", return_value=self._board(game_id="g1")):
            games = _NFLDataProvider().games(context, is_active_today=True)
        self.assertEqual(len(games), 1)
        self.assertTrue(games[0].get("game_market_recommendations"))

    def test_no_week_and_no_preseason_target_week_returns_empty(self) -> None:
        context = SportContext(slug="nfl", context_label="2026 Off-season", season=2026, week=None)
        with patch("syndicate.features.nfl.sources.preseason_target_week", return_value=None):
            games = _NFLDataProvider().games(context, is_active_today=True)
        self.assertEqual(games, [])


class NflGameMarketRecommendationsEndToEndTests(unittest.TestCase):
    """Regression guard: the translator's rows must actually flow through
    _game_bet_candidates_from_game and produce real board candidates, not
    just look right in isolation."""

    def test_translated_rows_produce_real_candidates(self) -> None:
        board_rows = [
            {"game_id": "g1", "market": "Moneyline", "market_type": "game", "side": "home", "line": None, "odds": -150, "sim_projection": 0.62, "model_side": "home", "projected_value": None, "join_status": "matched", "join_note": None},
            {"game_id": "g1", "market": "Moneyline", "market_type": "game", "side": "away", "line": None, "odds": 130, "sim_projection": 0.38, "model_side": "home", "projected_value": None, "join_status": "matched", "join_note": None},
            {"game_id": "g1", "market": "Total", "market_type": "game", "side": "over", "line": 45.5, "odds": -105, "sim_projection": 0.53, "model_side": "over", "projected_value": 47.0, "join_status": "matched", "join_note": None},
            {"game_id": "g1", "market": "Total", "market_type": "game", "side": "under", "line": 45.5, "odds": -115, "sim_projection": 0.47, "model_side": "over", "projected_value": 47.0, "join_status": "matched", "join_note": None},
        ]
        recommendations = _nfl_game_market_recommendation_rows("g1", board_rows)
        self.assertTrue(recommendations)
        game = {
            "gamePk": "g1",
            "away": {"name": "Arizona Cardinals", "abbr": "ARI"},
            "home": {"name": "Seattle Seahawks", "abbr": "SEA"},
            "summary": "Test game",
            "status": "Scheduled",
            "game_market_recommendations": recommendations,
        }
        candidates = _game_bet_candidates_from_game({"slug": "nfl", "name": "NFL"}, game, fallback_epoch=0.0)
        self.assertTrue(candidates)
        moneyline = next((c for c in candidates if c["market"] == "Moneyline"), None)
        total = next((c for c in candidates if c["market"] == "Total"), None)
        self.assertIsNotNone(moneyline)
        self.assertIsNotNone(total)
        self.assertEqual(moneyline["pick"], "Home ML")
        self.assertTrue(moneyline["team"])
        self.assertEqual(total["pick"], "Over 45.5")


class NcaafGameMarketRecommendationRowsTests(unittest.TestCase):
    """Coverage for _ncaaf_game_market_recommendation_rows -- mirrors
    NflGameMarketRecommendationRowsTests exactly, plus the NCAAF-specific
    real-data caveat: CFBD spread/total carry no per-side price today, so
    only Moneyline ever has real odds coverage to recommend."""

    @staticmethod
    def _row(*, market: str, side: str, market_type: str = "game", line=None, odds=None, sim_projection=None, model_side=None, projected_value=None, join_status="matched", join_note=None, game_id="g1"):
        return {
            "game_id": game_id,
            "market": market,
            "market_type": market_type,
            "side": side,
            "line": line,
            "odds": odds,
            "sim_projection": sim_projection,
            "model_side": model_side,
            "projected_value": projected_value,
            "join_status": join_status,
            "join_note": join_note,
        }

    def test_moneyline_recommendation_picks_the_models_favored_side(self) -> None:
        board_rows = [
            self._row(market="Moneyline", side="home", odds=-150, sim_projection=0.62, model_side="home"),
            self._row(market="Moneyline", side="away", odds=130, sim_projection=0.38, model_side="home"),
        ]
        rows = _ncaaf_game_market_recommendation_rows("g1", board_rows)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["market_label"], "Moneyline")
        self.assertEqual(rows[0]["display_pick"], "Home ML")
        self.assertEqual(rows[0]["odds"], -150)
        self.assertEqual(rows[0]["projected"], "62.0%")

    def test_spread_and_total_with_no_real_odds_price_are_skipped(self) -> None:
        # Real CFBD data shape: _ncaaf_market_board_rows_for_game only ever
        # attaches a "line" for Spread/Total, never an "odds" price.
        board_rows = [
            self._row(market="Moneyline", side="home", odds=-150, sim_projection=0.62, model_side="home"),
            self._row(market="Moneyline", side="away", odds=130, sim_projection=0.38, model_side="home"),
            self._row(market="Spread", side="home", line=-3.5, odds=None, sim_projection=0.55, model_side="home", projected_value=2.1),
            self._row(market="Total", side="over", line=51.5, odds=None, sim_projection=0.52, model_side="over", projected_value=53.0),
        ]
        rows = _ncaaf_game_market_recommendation_rows("g1", board_rows)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["market_label"], "Moneyline")

    def test_market_with_no_sim_coverage_is_skipped(self) -> None:
        board_rows = [
            self._row(market="Moneyline", side="home", odds=-150, sim_projection=None, model_side=None, join_status="unmatched_no_sim_coverage"),
            self._row(market="Moneyline", side="away", odds=130, sim_projection=None, model_side=None, join_status="unmatched_no_sim_coverage"),
        ]
        self.assertEqual(_ncaaf_game_market_recommendation_rows("g1", board_rows), [])

    def test_rows_from_a_different_game_id_are_ignored(self) -> None:
        board_rows = [
            self._row(market="Moneyline", side="home", odds=-150, sim_projection=0.62, model_side="home", game_id="other-game"),
            self._row(market="Moneyline", side="away", odds=130, sim_projection=0.38, model_side="home", game_id="other-game"),
        ]
        self.assertEqual(_ncaaf_game_market_recommendation_rows("g1", board_rows), [])


class NcaafDataProviderGamesTests(unittest.TestCase):
    """Coverage for _NCAAFDataProvider.games()'s Item 3 fix: switched from
    the stale build_cards_page_context snapshot path to
    build_smartsim_cards_page_context (the real current-slate path
    /ncaaf/cards itself renders through), plus game_market_recommendations
    stamping from build_ncaaf_market_board -- both keyed by the SAME
    gamePk, unlike the old snapshot source."""

    @staticmethod
    def _board(*, game_id: str) -> dict:
        rows = [
            {"game_id": game_id, "market": "Moneyline", "market_type": "game", "side": "home", "line": None, "odds": -150, "sim_projection": 0.62, "model_side": "home", "projected_value": None, "join_status": "matched", "join_note": "Model favors the home side."},
            {"game_id": game_id, "market": "Moneyline", "market_type": "game", "side": "away", "line": None, "odds": 130, "sim_projection": 0.38, "model_side": "home", "projected_value": None, "join_status": "matched", "join_note": None},
        ]
        return {"season": 2026, "week": 1, "games": [{"gamePk": game_id, "rows": rows}]}

    def test_no_week_returns_empty(self) -> None:
        context = SportContext(slug="ncaaf", context_label="2026 Week 1", season=2026, week=None)
        games = _NCAAFDataProvider().games(context, is_active_today=True)
        self.assertEqual(games, [])

    def test_games_come_from_the_real_current_slate_path_not_the_stale_snapshot(self) -> None:
        context = SportContext(slug="ncaaf", context_label="2026 Week 1", season=2026, week=1)
        smartsim_payload = {"games": [{"gamePk": "g1", "away": {"name": "Away Team"}, "home": {"name": "Home Team"}}]}
        with patch("syndicate.features.ncaaf.cards.build_smartsim_cards_page_context", return_value=smartsim_payload) as mocked_smartsim, patch(
            "syndicate.features.ncaaf.cards.build_cards_page_context"
        ) as mocked_stale, patch("syndicate.features.ncaaf.cards.build_ncaaf_market_board", return_value=self._board(game_id="g1")):
            games = _NCAAFDataProvider().games(context, is_active_today=True)
        mocked_smartsim.assert_called_once_with(1)
        mocked_stale.assert_not_called()
        self.assertEqual(len(games), 1)
        self.assertTrue(games[0].get("game_market_recommendations"))
        self.assertEqual(games[0]["game_market_recommendations"][0]["market_label"], "Moneyline")

    def test_game_that_already_has_recommendations_is_not_overwritten(self) -> None:
        context = SportContext(slug="ncaaf", context_label="2026 Week 1", season=2026, week=1)
        existing = [{"market_label": "Existing", "display_pick": "Keep me"}]
        smartsim_payload = {"games": [{"gamePk": "g1", "game_market_recommendations": existing}]}
        with patch("syndicate.features.ncaaf.cards.build_smartsim_cards_page_context", return_value=smartsim_payload), patch(
            "syndicate.features.ncaaf.cards.build_ncaaf_market_board", return_value=self._board(game_id="g1")
        ):
            games = _NCAAFDataProvider().games(context, is_active_today=True)
        self.assertEqual(games[0]["game_market_recommendations"], existing)

    def test_market_board_failure_does_not_break_games(self) -> None:
        context = SportContext(slug="ncaaf", context_label="2026 Week 1", season=2026, week=1)
        smartsim_payload = {"games": [{"gamePk": "g1", "away": {"name": "Away Team"}, "home": {"name": "Home Team"}}]}
        with patch("syndicate.features.ncaaf.cards.build_smartsim_cards_page_context", return_value=smartsim_payload), patch(
            "syndicate.features.ncaaf.cards.build_ncaaf_market_board", side_effect=Exception("boom")
        ):
            games = _NCAAFDataProvider().games(context, is_active_today=True)
        self.assertEqual(len(games), 1)
        self.assertNotIn("game_market_recommendations", games[0])
