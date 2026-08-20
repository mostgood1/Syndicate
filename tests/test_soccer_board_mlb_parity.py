"""Lane `soccer-board-mlb-parity` -- the soccer card board against MLB's shape.

Every test here is anchored to a number measured against PRODUCTION on
2026-08-20 before any code changed, not to a fixture invented to match the new
code. The payloads below are real: they are the `betting` / `home.score` /
`metrics` values served by `https://syndicate-an21.onrender.com` at the time
the lane opened.

REACHABILITY FIRST, per `model_engine_standard.md`: several of these assert
`off != on` -- that the new path produces something the old path could not --
rather than only asserting the new output is well-formed. A well-formed tile
that the board never reaches is the failure mode this repo has hit four times
in one session.
"""

from __future__ import annotations

import unittest

from syndicate.features.shared import game_board_contract as contract
from syndicate.features.soccer import cards


# The real `betting` dict from `/soccer/epl/api/cards`, COV @ ARS, 2026-08-20.
PROD_BETTING = {
    "away_ml": 1400.0,
    "away_ml_ev": 0.575,
    "away_puck_line": 1.5,
    "away_spread_ev": 0.1839,
    "home_ml": -590.0,
    "home_ml_ev": -0.1609,
    "home_puck_line": -1.5,
    "home_spread": -1.5,
    "home_spread_ev": -0.2461,
    "odds": -177.5,
    "over_ev": 0.0318,
    "p_away_cover": 0.4329,
    "p_away_win": 0.0629,
    "p_home_cover": 0.6466,
    "p_home_win": 0.8069,
    "p_total_over": 0.6396,
    "p_total_under": 0.4329,
    "total": 2.5,
    "under_ev": -0.2146,
}
PROD_WIN_PROB = {"home": 0.790, "draw": 0.140, "away": 0.070}
PROD_PROJECTION = {"away_mean": 0.8, "home_mean": 2.7, "total_mean": 3.49, "margin_mean": 1.87}
PREGAME = {"final": False, "in_progress": False}


def _tiles(**overrides):
    kwargs = dict(
        away_abbr="COV",
        home_abbr="ARS",
        win_prob=PROD_WIN_PROB,
        total_distribution={"over_2_5_probability": 0.698},
        team_projection=PROD_PROJECTION,
        betting=PROD_BETTING,
        top_props=[],
        live_state_block=PREGAME,
        away_score=None,
        home_score=None,
    )
    kwargs.update(overrides)
    return cards._market_tiles(**kwargs)


class MarketTileTests(unittest.TestCase):
    def test_tiles_carry_price_model_and_market_not_a_bare_probability(self) -> None:
        """The measured defect: four tiles, each a probability, no price anywhere.

        `game_board_contract._normalize_game` derived them from `metrics[:4]`
        while every one of these prices sat unused on the same payload.
        """
        tiles = _tiles()
        ml = tiles[0]
        self.assertIn("+1400", ml["title"])
        self.assertIn("Model", ml["sub"])
        self.assertIn("Market", ml["sub"])
        self.assertIn("Edge", ml["sub"])

    def test_no_tile_repeats_the_matchup_as_its_subtitle(self) -> None:
        """The old fallback used `"COV @ ARS"` as all four sub-lines."""
        subs = [tile["sub"] for tile in _tiles()]
        self.assertNotIn("COV @ ARS", subs)
        self.assertEqual(len(subs), len(set(subs)), f"tile subtitles repeat: {subs}")

    def test_total_tile_names_a_side_and_the_line(self) -> None:
        total = _tiles()[1]
        self.assertTrue(total["title"].startswith("OVER"), total["title"])
        self.assertIn("2.5", total["title"])

    def test_handicap_tile_shows_margin_not_an_invented_cover_probability(self) -> None:
        """Lane F's rule. No model cover probability is published for soccer,
        so the tile must not print one."""
        spread = _tiles()[2]
        self.assertIn("ARS -1.5", spread["title"])
        self.assertIn("Proj margin", spread["sub"])
        self.assertNotIn("%", spread["sub"])

    def test_edge_is_model_minus_market_not_the_picks_pipeline_ev(self) -> None:
        """`away_ml_ev` is 0.575 on this payload, from a DIFFERENT model
        vintage than the 7.0% the card renders. Printing it here would put two
        models' numbers under one heading."""
        ml_sub = _tiles()[0]["sub"]
        self.assertNotIn("57.5", ml_sub)
        # model 7.0% - market 6.29% = +0.71 points
        self.assertIn("+0.7 pts", ml_sub)

    def test_market_only_absent_says_so_rather_than_dressing_model_as_market(self) -> None:
        """MLS carried `betting = {}` on the same sweep EPL carried a full book."""
        tiles = _tiles(betting={})
        self.assertIn("Model only", tiles[0]["sub"])
        self.assertNotIn("Market", tiles[0]["sub"])

    def test_a_finished_match_shows_its_result_not_four_dashes(self) -> None:
        """25 of 31 MLS cards rendered `-` in all four tiles on 2026-08-20."""
        tiles = _tiles(
            away_abbr="LA",
            home_abbr="HOU",
            win_prob={},
            total_distribution={},
            team_projection={},
            betting={},
            live_state_block={"final": True, "in_progress": False},
            away_score="0",
            home_score="1",
        )
        self.assertEqual([t["title"] for t in tiles][0], "LA 0 - HOU 1")
        self.assertNotIn("-", [t["title"] for t in tiles][1:])
        self.assertTrue(any("HOU win" in t["title"] or "HOU win" in t["sub"] for t in tiles))


class BoxSectionTests(unittest.TestCase):
    def _game(self, **overrides):
        game = {
            "away": {"abbr": "LA", "name": "LA Galaxy", "score": "0"},
            "home": {"abbr": "HOU", "name": "Houston Dynamo FC", "score": "1"},
            "live_state": {"final": True, "in_progress": False},
            "status": "Final",
        }
        game.update(overrides)
        return game

    def test_a_completed_game_gets_its_real_score_not_box_score_unavailable(self) -> None:
        sections = contract._build_box_sections(self._game())
        titles = [section["title"] for section in sections]
        self.assertIn("Final score", titles)
        self.assertNotIn("Box score unavailable", titles)
        rows = sections[0]["rows"]
        self.assertEqual([row["value"] for row in rows], ["0", "1"])

    def test_a_scheduled_game_does_not_report_a_placeholder_zero_as_the_score(self) -> None:
        """A 0-0 on a not-yet-started match is absence, not a result. Lane F."""
        game = self._game(live_state={"final": False, "in_progress": False}, status="Sat, Aug 22 6:30 PM CT")
        game["away"]["score"] = "0"
        game["home"]["score"] = "0"
        sections = contract._build_box_sections(game)
        self.assertNotIn("Final score", [section["title"] for section in sections])

    def test_a_sports_own_box_sections_survive_normalization(self) -> None:
        """REACHABILITY: off != on.

        `_normalize_game` assigned `shared_box_sections` unconditionally, so
        soccer's real player stat lines were rebuilt away on every request.
        """
        own = [{"title": "Live box score", "body": "", "rows": [{"name": "X", "detail": "", "value": "1"}]}]
        normalized = contract._normalize_game(self._game(shared_box_sections=own))
        self.assertEqual(normalized["shared_box_sections"], own)

    def test_a_sport_with_no_box_sections_still_gets_the_generic_ones(self) -> None:
        normalized = contract._normalize_game(self._game())
        self.assertTrue(normalized["shared_box_sections"])


class LiveTileReachabilityTests(unittest.TestCase):
    def test_live_tile_branch_is_reachable_for_a_sport_that_publishes_metrics(self) -> None:
        """The guard was `not normalized.get("market_tiles")`, but the
        setdefault above it had already filled that key from `metrics[:4]`.
        Soccer publishes six metrics, so the branch could never run.
        """
        game = {
            "away": {"abbr": "COV", "name": "Coventry"},
            "home": {"abbr": "ARS", "name": "Arsenal"},
            "live_state": {"final": False, "in_progress": True},
            "status": "2nd half",
            "metrics": [{"label": "Home win", "value": "79.0%"}],
            "sim": {"periods": {"h1": {"away_mean": 0.3, "home_mean": 1.3}}},
        }
        normalized = contract._normalize_game(game)
        self.assertFalse(normalized["has_own_market_tiles"])
        self.assertTrue(normalized["shared_is_live"])

    def test_a_sport_with_its_own_tiles_keeps_them_when_live(self) -> None:
        own = [{"label": "Best 1X2 edge", "title": "COV ML +1400", "sub": "Model 7.0%"}]
        game = {
            "away": {"abbr": "COV", "name": "Coventry"},
            "home": {"abbr": "ARS", "name": "Arsenal"},
            "live_state": {"final": False, "in_progress": True},
            "status": "2nd half",
            "market_tiles": own,
            "metrics": [{"label": "Home win", "value": "79.0%"}],
        }
        normalized = contract._normalize_game(game)
        self.assertTrue(normalized["has_own_market_tiles"])
        self.assertEqual(normalized["market_tiles"], own)


class TopPlayRowTests(unittest.TestCase):
    def test_value_column_holds_the_number_not_the_matchup_string(self) -> None:
        """Measured: three of six rows had `value == "Coventry City @ Arsenal"`."""
        rows = cards._top_play_rows(
            away_abbr="COV",
            home_abbr="ARS",
            away_team="Coventry City",
            home_team="Arsenal",
            team_projection=PROD_PROJECTION,
            betting=PROD_BETTING,
            win_prob=PROD_WIN_PROB,
            volume={"away_shots": 7.6, "home_shots": 19.9},
        )
        self.assertTrue(rows)
        for row in rows:
            self.assertNotEqual(row["value"], "Coventry City @ Arsenal")
            self.assertNotIn("@", row["value"])


class PropRowTests(unittest.TestCase):
    def test_rows_carry_the_captured_price_and_edge(self) -> None:
        """The price and edge already existed -- on `/soccer/<league>/props`,
        one page away from the prop itself."""
        rows = cards._prop_rows_with_market(
            [{"player_name": "Kai Havertz", "team": "Arsenal", "anytime_scorer_probability": 0.258}],
            {"kai havertz": {"price": 150, "edge": -0.146}},
        )
        self.assertEqual(len(rows), 1)
        self.assertIn("+150", rows[0]["detail"])
        self.assertIn("-14.6%", rows[0]["detail"])

    def test_rows_are_not_synthesized_so_the_status_table_stops_rendering_empty(self) -> None:
        """`_build_prop_status_rows` drops every `is_synthesized` row, which is
        why soccer's props-status table was empty on every card."""
        rows = cards._prop_rows_with_market(
            [{"player_name": "Kai Havertz", "team": "Arsenal", "anytime_scorer_probability": 0.258}],
            {"kai havertz": {"price": 150, "edge": -0.146}},
        )
        self.assertTrue(contract._build_prop_status_rows(rows))

    def test_the_prop_tile_leads_on_edge_not_on_probability(self) -> None:
        tiles = _tiles(
            top_props=[
                {"player_name": "High Prob", "anytime_scorer_probability": 0.40, "expected_shots": 2.0},
                {"player_name": "Best Edge", "anytime_scorer_probability": 0.20, "expected_shots": 1.0},
            ],
            prop_picks={
                "high prob": {"price": -200, "edge": -0.10},
                "best edge": {"price": 500, "edge": 0.20},
            },
        )
        self.assertIn("Best Edge", tiles[3]["title"])
        self.assertEqual(tiles[3]["label"], "Best prop edge")


class DateBoardTests(unittest.TestCase):
    def test_the_date_board_orders_live_first_and_finals_last(self) -> None:
        games = [
            {"gamePk": "f", "live_state": {"final": True}, "scheduled_start_utc": "2026-08-20T10:00Z"},
            {"gamePk": "s", "live_state": {}, "scheduled_start_utc": "2026-08-20T23:00Z"},
            {"gamePk": "l", "live_state": {"in_progress": True}, "scheduled_start_utc": "2026-08-20T20:00Z"},
        ]
        order = [game["gamePk"] for game in sorted(games, key=cards._kickoff_sort_key)]
        self.assertEqual(order, ["l", "s", "f"])

    def test_the_slate_date_is_central_not_utc(self) -> None:
        """Reported by the user and confirmed on the SERVED board 2026-08-20:
        eight MLS matches played on 08-19 Central appeared on the 08-20 board,
        already Final.

        Their real kickoffs, straight off the production payload -- 7:00 to
        9:30 PM Central on the 19th, which is 00:00Z-02:30Z on the 20th. A
        `[:10]` slice of the UTC stamp files an entire North American evening
        onto the next day. `CLAUDE.md` documents this for NCAAF; the first cut
        of the date board was written against UTC anyway.
        """
        played_on_the_19th_central = [
            "2026-08-20T00:00Z",  # STL @ SKC
            "2026-08-20T00:30Z",  # ATL @ MIN
            "2026-08-20T01:30Z",  # LAF @ COL
            "2026-08-20T01:30Z",  # DAL @ RSL
            "2026-08-20T01:30Z",  # ATX @ SEA
            "2026-08-20T02:30Z",  # SD  @ POR
            "2026-08-20T02:30Z",  # SJ  @ LA
            "2026-08-20T02:30Z",  # HOU @ VAN
        ]
        for kickoff in played_on_the_19th_central:
            self.assertEqual(cards._central_slate_date(kickoff), "2026-08-19", kickoff)
        # The one match that really was on the 20th (ALA @ RAY, 2:00 PM CT).
        self.assertEqual(cards._central_slate_date("2026-08-20T19:00Z"), "2026-08-20")

    def test_the_central_day_boundary_is_a_conversion_not_a_fixed_offset(self) -> None:
        """05:00Z is midnight Central in CDT and 11:00 PM the previous day in
        CST. A hardcoded offset passes in August and silently breaks in
        November, which is the failure this repo keeps re-learning."""
        self.assertEqual(cards._central_slate_date("2026-08-21T04:59Z"), "2026-08-20")
        self.assertEqual(cards._central_slate_date("2026-08-21T05:00Z"), "2026-08-21")
        # CST side of the year: 06:00Z is midnight Central, 05:59Z is not.
        self.assertEqual(cards._central_slate_date("2026-11-20T05:59Z"), "2026-11-19")
        self.assertEqual(cards._central_slate_date("2026-11-20T06:00Z"), "2026-11-20")

    def test_an_unparseable_kickoff_is_excluded_rather_than_defaulted_in(self) -> None:
        """`feedback_unknown_must_not_default_permissive`: an absent date must
        not land on whatever board happens to be asking."""
        self.assertIsNone(cards._central_slate_date(None))
        self.assertIsNone(cards._central_slate_date(""))
        self.assertIsNone(cards._central_slate_date("not-a-date"))

    def test_one_broken_league_does_not_blank_the_whole_board(self) -> None:
        """`learnings.md`: a per-league exception swallowed into an unreadable
        dict is how a live-lens outage stayed silent for days.

        Behavioural, not a grep: one league is forced to raise and the board
        must still return the others AND print a findable marker. The first
        version of this test asserted `X in (docstring or source)`, which the
        truthy docstring short-circuited -- it passed without reading the
        source at all. That is `feedback_confirm_the_code_ran` in miniature.
        """
        import io as _io
        from contextlib import redirect_stdout

        good = {"gamePk": "ok", "scheduled_start_utc": "2026-08-20T18:00:00Z", "live_state": {}}

        def fake_default_week(league, season, *, reference_date=None):
            if league == "epl":
                raise RuntimeError("schedule artifact missing")
            return 1

        def fake_week_games(league, week, season):
            return [dict(good, gamePk=f"{league}-1")] if league == "mls" else []

        originals = (cards.default_week, cards.week_games, cards.default_season)
        cards.default_week = fake_default_week
        cards.week_games = fake_week_games
        cards.default_season = lambda league: 2026
        try:
            buffer = _io.StringIO()
            with redirect_stdout(buffer):
                games = cards.date_games("2026-08-20")
            printed = buffer.getvalue()
        finally:
            cards.default_week, cards.week_games, cards.default_season = originals

        self.assertEqual([game["gamePk"] for game in games], ["mls-1"])
        self.assertIn("LEAGUE_FAILED", printed)
        self.assertIn("league=epl", printed)


if __name__ == "__main__":
    unittest.main()
