from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.app import create_app
from syndicate.blueprints.home import _is_active_today
from syndicate.blueprints.home import _load_home_games
from syndicate.blueprints.home import _load_home_live_prop_items
from syndicate.blueprints.home import _load_home_pregame_prop_items
from syndicate.features.shared.sport_data_provider import get_sport_data_provider


class RegistryUnregisteredSportTests(unittest.TestCase):
    """An unregistered sport must be an explicit empty/None from every
    dispatch point -- never a silent fallthrough that happens to look like
    "checked, nothing here" (the bug that made soccer disappear)."""

    def test_get_sport_data_provider_returns_none_for_unregistered_slug(self) -> None:
        self.assertIsNone(get_sport_data_provider("xfl"))
        self.assertIsNone(get_sport_data_provider(""))

    def test_dispatch_points_return_empty_for_unregistered_slug(self) -> None:
        self.assertFalse(_is_active_today("xfl", "2026-07-22", "2026-07-22"))
        self.assertEqual(_load_home_games("xfl", context_label="2026-07-22", is_active_today=True), [])
        self.assertEqual(
            _load_home_pregame_prop_items("xfl", context_label="2026-07-22", home_games=[], is_active_today=True),
            [],
        )
        self.assertEqual(
            _load_home_live_prop_items("xfl", context_label="2026-07-22", home_games=[], is_active_today=True),
            [],
        )

    def test_all_eight_sports_registered(self) -> None:
        for slug in ("mlb", "nba", "wnba", "nhl", "nfl", "ncaaf", "ncaab", "soccer"):
            self.assertIsNotNone(get_sport_data_provider(slug), f"{slug} should be registered")


class SoccerDataProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        app = create_app()
        app.testing = True
        self.app_context = app.app_context()
        self.app_context.push()
        self.provider = get_sport_data_provider("soccer")

    def tearDown(self) -> None:
        self.app_context.pop()

    def test_is_active_reflects_calendar_active_leagues(self) -> None:
        with patch("syndicate.features.soccer.sources.active_leagues_for_date", return_value=["mls"]):
            self.assertTrue(self.provider.is_active(today_value="2026-07-22", context_label="2026-07-22"))
        with patch("syndicate.features.soccer.sources.active_leagues_for_date", return_value=[]):
            self.assertFalse(self.provider.is_active(today_value="2026-01-15", context_label="2026-01-15"))

    def test_resolve_context_prefers_mls_when_active(self) -> None:
        with patch("syndicate.features.soccer.sources.active_leagues_for_date", return_value=["epl", "mls"]), patch(
            "syndicate.features.soccer.sources.default_season", return_value=2026
        ), patch("syndicate.features.soccer.sources.default_week", return_value=17):
            context = self.provider.resolve_context(requested_date="2026-07-22")
        self.assertEqual(context.league, "mls")
        self.assertEqual(context.season, 2026)
        self.assertEqual(context.week, 17)
        self.assertEqual(context.slug, "soccer")

    def test_resolve_context_falls_back_to_first_active_league_when_mls_inactive(self) -> None:
        with patch("syndicate.features.soccer.sources.active_leagues_for_date", return_value=["epl", "la_liga"]), patch(
            "syndicate.features.soccer.sources.default_season", return_value=2026
        ), patch("syndicate.features.soccer.sources.default_week", return_value=3):
            context = self.provider.resolve_context(requested_date="2026-09-01")
        self.assertEqual(context.league, "epl")

    def test_games_delegates_to_soccer_cards_page_context(self) -> None:
        from syndicate.features.shared.sport_data_provider import SportContext

        context = SportContext(slug="soccer", context_label="MLS 2026 Week 17", season=2026, week=17, league="mls")
        fake_games = [{"gamePk": "1", "away": {"abbr": "A"}, "home": {"abbr": "B"}}]
        with patch(
            "syndicate.features.soccer.sources.active_leagues_for_date", return_value=["mls"]
        ), patch(
            "syndicate.features.soccer.cards.build_cards_page_context",
            return_value={"games": fake_games},
        ) as mocked:
            games = self.provider.games(context, is_active_today=True)
        mocked.assert_called_once_with("mls", 17, 2026)
        self.assertEqual(games, fake_games)
        self.assertEqual(games[0]["league"], "mls")

    def test_games_fan_out_across_all_active_leagues(self) -> None:
        # 2026-08-14+: European leagues come back and several are active at
        # once -- every active league must reach the board, not just the
        # context's primary league.
        from syndicate.features.shared.sport_data_provider import SportContext

        context = SportContext(slug="soccer", context_label="MLS 2026 Week 17", season=2026, week=17, league="mls")

        def fake_cards(league, week, season):
            return {"games": [{"gamePk": f"{league}-1"}]}

        with patch(
            "syndicate.features.soccer.sources.active_leagues_for_date", return_value=["epl", "mls"]
        ), patch(
            "syndicate.features.soccer.sources.default_season", return_value=2026
        ), patch(
            "syndicate.features.soccer.sources.default_week", return_value=1
        ), patch(
            "syndicate.features.soccer.cards.build_cards_page_context", side_effect=fake_cards
        ) as mocked:
            games = self.provider.games(context, is_active_today=True)
        called_leagues = sorted(call.args[0] for call in mocked.call_args_list)
        self.assertEqual(called_leagues, ["epl", "mls"])
        self.assertEqual(sorted(game["league"] for game in games), ["epl", "mls"])
        # MLS keeps the context's own season/week; other leagues resolve
        # their own.
        mls_call = next(call for call in mocked.call_args_list if call.args[0] == "mls")
        self.assertEqual(mls_call.args[1:], (17, 2026))
        epl_call = next(call for call in mocked.call_args_list if call.args[0] == "epl")
        self.assertEqual(epl_call.args[1:], (1, 2026))

    def test_games_one_broken_league_does_not_empty_the_sport(self) -> None:
        from syndicate.features.shared.sport_data_provider import SportContext

        context = SportContext(slug="soccer", context_label="MLS 2026 Week 17", season=2026, week=17, league="mls")

        def fake_cards(league, week, season):
            if league == "epl":
                raise RuntimeError("schedule artifact missing")
            return {"games": [{"gamePk": f"{league}-1"}]}

        with patch(
            "syndicate.features.soccer.sources.active_leagues_for_date", return_value=["mls", "epl"]
        ), patch(
            "syndicate.features.soccer.sources.default_season", return_value=2026
        ), patch(
            "syndicate.features.soccer.sources.default_week", return_value=1
        ), patch(
            "syndicate.features.soccer.cards.build_cards_page_context", side_effect=fake_cards
        ):
            games = self.provider.games(context, is_active_today=True)
        self.assertEqual([game["gamePk"] for game in games], ["mls-1"])

    def test_pregame_props_attaches_game_id_from_match_id(self) -> None:
        from syndicate.features.shared.sport_data_provider import SportContext

        context = SportContext(slug="soccer", context_label="MLS 2026 Week 17", season=2026, week=17, league="mls")
        rank_cards = [
            {
                "title": "Some Player",
                "eyebrow": "Columbus Crew (home)",
                "meta": "MLS",
                "match_id": "761668",
                "metrics": [],
            }
        ]
        with patch(
            "syndicate.features.soccer.sources.active_leagues_for_date", return_value=["mls"]
        ), patch(
            "syndicate.features.soccer.props.build_props_page_context",
            return_value={"rank_cards": rank_cards},
        ):
            rows = self.provider.pregame_props(context, [], is_active_today=True)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["gamePk"], "761668")
        self.assertEqual(rows[0]["game_id"], "761668")
        self.assertEqual(rows[0]["league"], "mls")

    def test_pregame_props_fan_out_across_all_active_leagues(self) -> None:
        from syndicate.features.shared.sport_data_provider import SportContext

        context = SportContext(slug="soccer", context_label="MLS 2026 Week 17", season=2026, week=17, league="mls")

        def fake_props(league, week, season):
            return {"rank_cards": [{"title": f"{league} player", "eyebrow": "x", "meta": league, "match_id": f"{league}-9", "metrics": []}]}

        with patch(
            "syndicate.features.soccer.sources.active_leagues_for_date", return_value=["mls", "epl"]
        ), patch(
            "syndicate.features.soccer.sources.default_season", return_value=2026
        ), patch(
            "syndicate.features.soccer.sources.default_week", return_value=1
        ), patch(
            "syndicate.features.soccer.props.build_props_page_context", side_effect=fake_props
        ):
            rows = self.provider.pregame_props(context, [], is_active_today=True)
        self.assertEqual(sorted(row["league"] for row in rows), ["epl", "mls"])

    def test_pregame_props_falls_back_to_compact_rows_when_no_rank_cards(self) -> None:
        from syndicate.features.shared.sport_data_provider import SportContext

        context = SportContext(slug="soccer", context_label="MLS 2026 Week 17", season=2026, week=17, league="mls")
        home_games = [
            {
                "gamePk": "1",
                "away": {"abbr": "A", "name": "A"},
                "home": {"abbr": "B", "name": "B"},
                "shared_prop_rows": [
                    {"name": "Anytime scorer", "detail": "Compact fallback", "value": "Yes", "pick": "Over", "market": "Goals"}
                ],
            }
        ]
        with patch(
            "syndicate.features.soccer.sources.active_leagues_for_date", return_value=["mls"]
        ), patch("syndicate.features.soccer.props.build_props_page_context", return_value={"rank_cards": []}):
            rows = self.provider.pregame_props(context, home_games, is_active_today=True)
        self.assertEqual(len(rows), 1)

    def test_live_props_always_empty(self) -> None:
        from syndicate.features.shared.sport_data_provider import SportContext

        context = SportContext(slug="soccer", context_label="MLS 2026 Week 17", season=2026, week=17, league="mls")
        self.assertEqual(self.provider.live_props(context, [], is_active_today=True), [])

    def test_data_sources_reports_manifest_and_league(self) -> None:
        from syndicate.features.shared.sport_data_provider import SportContext

        context = SportContext(slug="soccer", context_label="MLS 2026 Week 17", season=2026, week=17, league="mls")
        sources = self.provider.data_sources(context)
        self.assertIn("manifest", sources)
        self.assertEqual(sources["league"], "mls")


if __name__ == "__main__":
    unittest.main()
