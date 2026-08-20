from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.app import create_app


class UnknownLeagueSlugTests(unittest.TestCase):
    """A bad league slug used to serve EPL under the requested league's name.

    Every handler opened with `league = normalize_league(league)`, which maps
    anything unrecognised onto `DEFAULT_LEAGUE`. Measured on production
    2026-08-20: `/soccer/laliga/cards` (canonical: `la_liga`) returned HTTP
    200 with Arsenal and Coventry fixtures under a La Liga heading, and
    `/soccer/zzz/api/cards` returned 200 with EPL data.
    """

    def setUp(self) -> None:
        app = create_app()
        app.config.update(TESTING=True)
        self.client = app.test_client()

    def test_the_near_miss_spellings_404(self) -> None:
        """The ones a person actually types. `laliga`/`seriea`/`ligue1` are
        one underscore away from real slugs, which is why they went unnoticed
        -- they returned a plausible-looking page."""
        for path in (
            "/soccer/laliga/cards",
            "/soccer/seriea/cards",
            "/soccer/ligue1/cards",
            "/soccer/premierleague/cards",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_unknown_slugs_404_on_every_route_shape(self) -> None:
        """The gate is a `url_value_preprocessor`, so this asserts the thing
        that makes that choice worth it: page routes, api routes and routes
        with a SECOND parameter are all covered by the one rule."""
        for path in (
            "/soccer/zzz",
            "/soccer/zzz/cards",
            "/soccer/zzz/api/cards",
            "/soccer/zzz/props",
            "/soccer/zzz/api/props",
            "/soccer/zzz/live-lens",
            "/soccer/zzz/archive",
            "/soccer/zzz/market-board",
            "/soccer/zzz/game/401879301",
            "/soccer/zzz/api/game/401879301",
            "/soccer/zzz/team/5/roster",
            "/soccer/zzz/api/team/5/schedule",
            "/soccer/zzz/api/schedule",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_the_404_names_the_valid_leagues(self) -> None:
        body = self.client.get("/soccer/zzz/cards").get_data(as_text=True)
        self.assertIn("zzz", body)
        self.assertIn("la_liga", body)

    def test_every_real_league_still_serves(self) -> None:
        """REGRESSION GUARD. A gate that 404s a real league is worse than the
        bug it replaces, so this walks the full canonical set."""
        from syndicate.features.soccer.sources import LEAGUE_DISPLAY_NAMES

        for slug in sorted(LEAGUE_DISPLAY_NAMES):
            with self.subTest(slug=slug):
                self.assertEqual(self.client.get(f"/soccer/{slug}/api/cards").status_code, 200)

    def test_slugs_are_case_insensitive(self) -> None:
        """`normalize_league` lower-cased before comparing, so uppercase URLs
        worked. The gate must not quietly take that away."""
        self.assertEqual(self.client.get("/soccer/EPL/api/cards").status_code, 200)
        self.assertEqual(self.client.get("/soccer/La_Liga/api/cards").status_code, 200)

    def test_routes_with_no_league_segment_are_untouched(self) -> None:
        """Werkzeug matches these static rules ahead of `/<league>`, so the
        preprocessor sees no `league` key for them. If that ever stopped being
        true these would 404, which is exactly what this catches."""
        for path in ("/soccer/hub", "/soccer/cards", "/soccer/api/cards", "/soccer/market-board"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_normalize_league_stays_permissive_for_internal_callers(self) -> None:
        """The URL boundary is strict; the internal helper is NOT, on purpose.
        Feature modules pass leagues that came from artifacts and config rows,
        and a hard failure there would take down a page over a stray value."""
        from syndicate.features.soccer.sources import (
            DEFAULT_LEAGUE,
            is_known_league,
            normalize_league,
        )

        self.assertEqual(normalize_league("zzz"), DEFAULT_LEAGUE)
        self.assertEqual(normalize_league(None), DEFAULT_LEAGUE)
        self.assertFalse(is_known_league("zzz"))
        self.assertFalse(is_known_league(None))
        self.assertTrue(is_known_league("  EPL  "))


class SoccerBlueprintRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        app = create_app()
        app.config.update(TESTING=True)
        self.client = app.test_client()

    def test_root_redirects_to_todays_cross_league_board(self) -> None:
        """Changed 2026-08-20 (`soccer-board-mlb-parity`) from a redirect to
        EPL's matchweek board.

        The old target was measured on production: EPL matchweek 1 held ONE
        fixture, kicking off the following day, while 92 fixtures existed
        across the ten tracked leagues. Landing cold on a single league's
        matchweek answered a question nobody had asked; `/soccer/cards?date=`
        answers "what is on today", which is what every other sport's board
        does.
        """
        from syndicate.features.shared.timezone import central_today_iso

        response = self.client.get("/soccer", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        location = response.headers["Location"]
        self.assertIn("/soccer/cards", location)
        self.assertIn(f"date={central_today_iso()}", location)

    def test_the_per_league_matchweek_board_is_still_reachable(self) -> None:
        """The date board ADDS a view; it must not remove the matchweek one,
        which is still the right surface for planning a whole matchweek."""
        response = self.client.get("/soccer/epl", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/soccer/epl/cards", response.headers["Location"])

    def test_cards_route_is_not_shadowed_by_the_league_wildcard(self) -> None:
        """`/soccer/cards` and `/soccer/<league>` are both one segment deep.

        If Werkzeug ever ranked the dynamic rule first, `/soccer/cards` would
        be read as the league "cards", normalized to the default league, and
        silently 302 back to EPL -- the exact bug this lane removed, restored
        by a routing detail rather than a code change. Assert the static rule
        wins rather than trusting that it does.
        """
        with patch("syndicate.blueprints.soccer.build_date_cards_page_context", return_value={}), \
             patch("syndicate.blueprints.soccer.render_template", return_value="DATE_BOARD"):
            response = self.client.get("/soccer/cards?date=2026-08-22")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True), "DATE_BOARD")

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

    def test_unknown_league_slug_404s_and_never_reaches_the_builder(self) -> None:
        """REVERSED 2026-08-20 (`soccer-board-mlb-parity`), by user decision.

        This asserted the opposite -- 200, with the builder called for "epl".
        It arrived as incidental characterization in `570ba09f` (a rosters /
        schedules / week-nav feature landing) and carried no rationale: it
        documented what `normalize_league` happened to do, not a requirement.

        What that behaviour cost, measured on production 2026-08-20:
        `/soccer/laliga/cards` -- one underscore from the canonical `la_liga`
        -- returned 200 with Arsenal and Coventry fixtures under a La Liga
        heading. A typo did not fail; it served another league's data under
        the requested league's name.

        The `assert_not_called` is the load-bearing half. A 404 rendered
        after the page was already built would still have burned the work and
        still have read the wrong artifacts.
        """
        with patch("syndicate.blueprints.soccer.build_cards_page_context", return_value={}) as mocked_context, \
             patch("syndicate.blueprints.soccer.render_template", return_value="PAGE"):
            response = self.client.get("/soccer/not_a_real_league/cards")
        self.assertEqual(response.status_code, 404)
        mocked_context.assert_not_called()


if __name__ == "__main__":
    unittest.main()
