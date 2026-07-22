from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
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
from syndicate.blueprints.home import _prefer_today_or_latest
from syndicate.blueprints.home import _game_bet_candidates_from_game
from syndicate.blueprints.home import _game_status_state
from syndicate.blueprints.home import _prop_item_from_rank_card
from syndicate.blueprints.home import _team_for_side_hint
from syndicate.blueprints.home import _compact_prop_rows
from syndicate.blueprints.home import _game_sim_vs_line_reasoning
from syndicate.blueprints.home import _game_identifier
from syndicate.blueprints.home import _board_candidate_rows


class HomePageCommandCenterTests(unittest.TestCase):
    def setUp(self) -> None:
        app = create_app()
        app.testing = True
        self.client = app.test_client()

    def test_home_page_renders_daily_command_center(self) -> None:
        light_sports = [
            {
                "slug": "mlb",
                "name": "MLB",
                "home_anchor": "mlb-home",
                "data_health": "partial",
                "freshness_label": "Stored slate",
                "games_count": "4",
                "props_count": "8",
                "overview_stats": [],
                "home_rails": {
                    "compact": {"title": "Compact rail", "items": [], "links": [], "empty_summary": ""},
                    "pregame": {"title": "Pregame props", "items": [], "links": [], "empty_summary": ""},
                    "live": {"title": "Top Live Props", "items": [], "links": [], "empty_summary": "", "links": []},
                },
                "game_bar": {"opportunity_tags": []},
                "props_bar": {"opportunity_tags": []},
                "feature_links": [],
            },
            {
                "slug": "wnba",
                "name": "WNBA",
                "home_anchor": "wnba-home",
                "data_health": "partial",
                "freshness_label": "Stored slate",
                "games_count": "3",
                "props_count": "6",
                "overview_stats": [],
                "home_rails": {
                    "compact": {"title": "Compact rail", "items": [], "links": [], "empty_summary": ""},
                    "pregame": {"title": "Pregame props", "items": [], "links": [], "empty_summary": ""},
                    "live": {"title": "Top Live Props", "items": [], "links": [], "empty_summary": "", "links": []},
                },
                "game_bar": {"opportunity_tags": []},
                "props_bar": {"opportunity_tags": []},
                "feature_links": [],
            },
        ]

        with patch("syndicate.blueprints.home._build_light_home_sports", return_value=light_sports):
            response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertNotIn('<form class="home-topbar__date-form"', html)
        self.assertNotIn('<section class="home-decision-grid"', html)
        self.assertIn("home-active-strip", html)
        self.assertIn('id="mlb-home"', html)
        self.assertIn('id="wnba-home"', html)
        self.assertNotIn('id="nba-home"', html)

    def test_home_page_defaults_to_current_local_date_and_active_payload(self) -> None:
        with patch("syndicate.blueprints.home.central_today_iso", return_value="2026-06-21"):
            with patch("syndicate.blueprints.home._build_light_home_sports", return_value=[] ) as mocked_light:
                with patch("syndicate.blueprints.home.render_template", return_value="ok") as mocked_render:
                    response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True), "ok")
        mocked_light.assert_called_once_with("2026-06-21")
        self.assertEqual(mocked_render.call_args.kwargs["selected_home_date"], "2026-06-21")
        self.assertEqual(mocked_render.call_args.kwargs["sports"], [])
        self.assertFalse(mocked_render.call_args.kwargs["show_command_center"])

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

    def test_prop_item_from_rank_card_derives_team_from_matchup_labels(self) -> None:
        card = {
            "title": "Jayson Tatum Over 28.5",
            "meta": "BOS @ NYK",
            "summary": "Tatum projected for 31.2 points as a member of BOS.",
            "metrics": [{"label": "Projected", "value": "31.2"}],
        }
        item = _prop_item_from_rank_card(card, sport_slug="nba")
        self.assertEqual(item["team"], "BOS")

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

    def test_game_status_state_still_detects_live_from_structured_in_progress(self) -> None:
        game = self._sample_game(
            status={"in_progress": True, "final": False, "status": "In Progress"},
            summary="Consensus market snapshot",
        )
        self.assertEqual(_game_status_state(game), "live")


if __name__ == "__main__":
    unittest.main()
