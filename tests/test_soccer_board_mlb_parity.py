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

import io
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


# Two real rows from `player_props` in
# data/soccer_source/epl/api/recommendations/recommendations_2026-08-21.json.
SQUAD = [
    {
        "player_name": "Kai Havertz", "team": "Arsenal", "side": "home", "position": "F M S",
        "match_id": "401879301", "anytime_scorer_probability": 0.258,
        "expected_shots": 1.21, "expected_shots_on_target": 0.43,
        "expected_minutes_share": 0.539,
    },
    {
        "player_name": "Thomas Partey", "team": "Arsenal", "side": "home", "position": "D M S",
        "match_id": "401879301", "anytime_scorer_probability": 0.0488,
        "expected_shots": 0.6002, "expected_shots_on_target": 0.211,
        "expected_minutes_share": 0.8921,
    },
]


class SquadBoxTests(unittest.TestCase):
    def _sections(self, squad=None, picks=None):
        return cards._squad_box_sections(
            squad_props=SQUAD if squad is None else squad,
            prop_picks=picks or {},
            away_team="Coventry City", home_team="Arsenal",
            away_abbr="COV", home_abbr="ARS", live_state=None,
        )

    def test_every_published_player_reaches_the_table(self) -> None:
        """The data was one truncation away the whole time.

        `cards.py` read `match["top_props"]`, capped at 8 by the artifact
        builder; the full roster is the payload's top-level `player_props`
        (28 rows for this fixture), which the props page already read.
        """
        home = [s for s in self._sections() if s["title"].startswith("ARS")][0]
        self.assertEqual(len(home["table_rows"]), 2)
        self.assertEqual(home["columns"][0], "Player")
        self.assertEqual(len(home["columns"]), len(home["table_rows"][0]))

    def test_rows_are_ordered_by_scorer_probability(self) -> None:
        home = [s for s in self._sections() if s["title"].startswith("ARS")][0]
        self.assertEqual(home["table_rows"][0][0], "Kai Havertz")

    def test_a_side_with_no_published_players_says_so(self) -> None:
        """All 28 rows for COV@ARS are Arsenal players and none Coventry. An
        empty column that says nothing is indistinguishable from a bug."""
        away = [s for s in self._sections() if s["title"].startswith("COV")][0]
        self.assertFalse(away.get("table_rows"))
        self.assertIn("No player projections", away["body"])
        self.assertIn("Coventry City", away["body"])

    def test_captured_price_and_edge_reach_the_table(self) -> None:
        sections = self._sections(picks={"kai havertz": {"price": 150, "edge": -0.146}})
        home = [s for s in sections if s["title"].startswith("ARS")][0]
        row = home["table_rows"][0]
        self.assertEqual(row[-2], "+150")
        self.assertEqual(row[-1], "-14.6%")

    def test_a_player_without_a_price_renders_a_placeholder_not_a_number(self) -> None:
        home = [s for s in self._sections() if s["title"].startswith("ARS")][0]
        self.assertEqual(home["table_rows"][0][-2:], ["-", "-"])


class ScorelineTests(unittest.TestCase):
    # The real distribution from the same artifact.
    DIST = {"3-0": 0.14, "2-0": 0.1267, "1-0": 0.10, "3-1": 0.0933, "2-1": 0.0867,
            "1-1": 0.06, "4-1": 0.0533, "0-1": 0.04, "2-2": 0.04, "3-2": 0.04, "5-0": 0.0333}

    def test_scorelines_are_published_at_all(self) -> None:
        """`scoreline_probabilities` is on every simulated match and was read
        by NOTHING on the card -- the correct-score market, unrendered."""
        section = cards._scoreline_section(self.DIST, away_abbr="COV", home_abbr="ARS")
        self.assertIsNotNone(section)
        self.assertEqual(len(section["table_rows"]), 10)

    def test_scorelines_render_away_first_matching_the_card_header(self) -> None:
        """Artifact keys are home-away; the card header is AWAY @ HOME. If the
        table kept artifact order the same match would read in two directions
        on one card."""
        section = cards._scoreline_section(self.DIST, away_abbr="COV", home_abbr="ARS")
        # "3-0" is home 3, away 0 -> the Arsenal-favourite peak.
        self.assertEqual(section["table_rows"][0][0], "COV 0 - ARS 3")
        self.assertEqual(section["table_rows"][0][1], "14.0%")

    def test_ordered_by_probability(self) -> None:
        section = cards._scoreline_section(self.DIST, away_abbr="COV", home_abbr="ARS")
        pcts = [float(r[1].rstrip("%")) for r in section["table_rows"]]
        self.assertEqual(pcts, sorted(pcts, reverse=True))

    def test_absent_distribution_yields_no_section_rather_than_an_empty_one(self) -> None:
        self.assertIsNone(cards._scoreline_section(None, away_abbr="COV", home_abbr="ARS"))
        self.assertIsNone(cards._scoreline_section({}, away_abbr="COV", home_abbr="ARS"))


class BoxSectionSurvivalTests(unittest.TestCase):
    def test_soccer_supplied_table_sections_survive_normalization(self) -> None:
        """REACHABILITY. These are worth nothing if the shared normalizer
        rebuilds them away, which is what it did before this lane."""
        own = [{"title": "ARS squad projections", "body": "",
                "columns": ["Player", "xSh"], "table_rows": [["Kai Havertz", "1.21"]], "rows": []}]
        game = {
            "away": {"abbr": "COV", "name": "Coventry"},
            "home": {"abbr": "ARS", "name": "Arsenal"},
            "live_state": {"final": False, "in_progress": False},
            "status": "Fri, Aug 21",
            "shared_box_sections": own,
        }
        self.assertEqual(contract._normalize_game(game)["shared_box_sections"], own)


class PrimaryLensRowTests(unittest.TestCase):
    """The ribbon captions the matchup with ONE line and took `lens_rows[0]`.

    On the board only the full-game row survives the gate, so it read right.
    On the GAME DETAIL page all three soccer rows render and row 0 is the
    FIRST HALF -- production `/soccer/epl/game/401879301` showed "Projected
    total 1.6" directly under a summary saying "(total 3.5)".
    """

    ROWS = [
        {"label": "1st Half", "subtitle": "Projected total 1.6", "home_pct": None},
        {"label": "2nd Half", "subtitle": "Projected total 1.8", "home_pct": None},
        {"label": "Full Game", "subtitle": "Projected total 3.5", "home_pct": 80.69},
    ]

    def test_picks_the_game_row_not_the_first_row(self) -> None:
        self.assertEqual(contract._primary_lens_row(self.ROWS)["subtitle"], "Projected total 3.5")

    def test_falls_back_to_the_label_when_no_row_carries_a_win_probability(self) -> None:
        rows = [{"label": "1st Half", "subtitle": "a"}, {"label": "Full Game", "subtitle": "b"}]
        self.assertEqual(contract._primary_lens_row(rows)["subtitle"], "b")

    def test_falls_back_to_the_last_row_for_unknown_labels(self) -> None:
        """Period rows are built chronologically with the whole-game row last."""
        rows = [{"label": "Q1", "subtitle": "x"}, {"label": "Q2", "subtitle": "y"}]
        self.assertEqual(contract._primary_lens_row(rows)["subtitle"], "y")

    def test_no_rows_yields_none_rather_than_raising(self) -> None:
        self.assertIsNone(contract._primary_lens_row([]))

    def test_a_single_row_board_card_is_unchanged(self) -> None:
        """REGRESSION GUARD: the board renders one lens row and read correctly
        before this fix. It must still resolve to that same row."""
        only = [{"label": "Full Game", "subtitle": "Projected total 3.5", "home_pct": 80.69}]
        self.assertEqual(contract._primary_lens_row(only), only[0])


class LiveScoreTests(unittest.TestCase):
    """Measured on live La Liga match 401882908 (ALA @ RAY), 2026-08-20: the
    card read status "Live" and slate context "0-0" with no score in the head.
    `away.score`/`home.score` were populated ("0"/"0") the entire time."""

    def test_detail_carries_the_league_not_the_score(self) -> None:
        """`detail` is the "Slate context" slot. Overwriting it with the score
        lost the competition label AND captioned a score as slate context."""
        src = io.open("syndicate/features/soccer/cards.py", encoding="utf-8").read()
        self.assertIn('"detail": league_display_name(league),', src)
        self.assertNotIn('"detail": score_text if score_text != "-"', src)

    def test_head_renders_a_score_element_when_live(self) -> None:
        tpl = io.open(
            "syndicate/templates/shared/_game_card_generic.html", encoding="utf-8"
        ).read()
        self.assertIn("cards-head-score", tpl)
        # 0 is a real score: the guard must test for None, not falsiness.
        self.assertIn("game.away.score is not none", tpl)
        self.assertIn("game.home.score is not none", tpl)


class FabricatedScoreTests(unittest.TestCase):
    """`live_home_score`/`live_away_score` in the recommendations artifact are
    the STRING "0" on 12 of 12 sampled matches, including `status_state ==
    "pre"` fixtures that had not kicked off. They are a placeholder the
    builder writes, not a reading -- nine consecutive 0-0 results across a
    league's completed slate is not a plausible set of soccer scores.

    Publishing them as a score put a fabricated 0-0 on every live match."""

    def test_absent_live_state_yields_no_score(self) -> None:
        self.assertIsNone(cards._real_live_score(None, "home"))
        self.assertIsNone(cards._real_live_score({}, "home"))

    def test_a_genuine_zero_from_the_poller_survives(self) -> None:
        """0-0 is a real and common soccer score. The guard must reject
        ABSENCE, not falsiness, or it would suppress a true nil-nil."""
        self.assertEqual(cards._real_live_score({"home_score": 0}, "home"), 0)

    def test_a_real_score_is_returned(self) -> None:
        self.assertEqual(cards._real_live_score({"away_score": 2}, "away"), 2)
        self.assertEqual(cards._real_live_score({"home": {"score": 3}}, "home"), 3)

    def test_non_numeric_is_rejected_rather_than_rendered(self) -> None:
        self.assertIsNone(cards._real_live_score({"home_score": "--"}, "home"))

    def test_the_artifact_placeholder_is_never_the_source(self) -> None:
        """REACHABILITY: the fix is worth nothing if the caller still reads the
        artifact field. Assert the placeholder key is not consulted."""
        src = io.open("syndicate/features/soccer/cards.py", encoding="utf-8").read()
        self.assertNotIn('match.get("live_home_score")', src)
        self.assertNotIn('match.get("live_away_score")', src)
        self.assertIn('_real_live_score(live_state, "home")', src)


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
