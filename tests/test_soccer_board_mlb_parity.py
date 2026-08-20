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



# The real `match_box` record `poll_soccer_live_state.poll_league` wrote for
# La Liga fixture 401882908 (ALA @ RAY) on 2026-08-20 -- taken from the
# artifact the poller actually produced, not hand-written to match the code.
MATCH_BOX = {
    "event_id": "401882908",
    "teams": {
        "home": {
            "team": "Rayo Vallecano",
            "stats": {
                "Possession": "49.8%",
                "Shots": "8",
                "On target": "3",
                "Corners": "9",
                "Pass %": "80%",
            },
        },
        "away": {
            "team": "Alaves",
            "stats": {
                "Possession": "50.2%",
                "Shots": "10",
                "On target": "1",
                "Corners": "4",
                "Pass %": "80%",
            },
        },
    },
    "goals": [
        {
            "team": "Rayo Vallecano",
            "scorer": "Sergio Camello",
            "clock": "48'",
            "clock_seconds": 2839.0,
            "own_goal": False,
        }
    ],
    "final": False,
    "status_state": "in",
    "score_home": "1",
    "score_away": "0",
    "home_team": "Rayo Vallecano",
    "away_team": "Alaves",
}


def _live_match(*, status_state: str, kickoff: str) -> dict:
    """A recommendations-artifact match in the shape `_match_to_game` reads,
    carrying the REAL ESPN scores for completed Atletico Madrid v Malaga."""
    return {
        "event_id": "401874931",
        "match_id": "401874931",
        "date": "2026-08-20",
        "kickoff": kickoff,
        "status_state": status_state,
        "live_home_score": "2",
        "live_away_score": "0",
        "matchup": {"home_team": "Atletico Madrid", "away_team": "Malaga"},
        "win_probability": {"home": 0.55, "draw": 0.25, "away": 0.20},
        "team_projection": {"home_mean": 1.5, "away_mean": 1.0, "total_mean": 2.5},
        "total_distribution": {},
        "volume_projection": {},
        "periods": {},
        "top_props": [],
    }


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
    """The score must never be INVENTED -- and the earlier reading of HOW it
    was being invented was itself wrong, which is why this class is worth
    reading carefully.

    THE ORIGINAL DIAGNOSIS: `live_home_score`/`live_away_score` in the
    recommendations artifact were "the string '0' on 12 of 12 sampled matches
    including `status_state == 'pre'`", therefore "a placeholder the builder
    writes, not a reading", therefore unusable.

    WHY THAT WAS WRONG, measured 2026-08-20. `build_soccer_artifacts.py:289`
    sets both from `fetch_events`'s `home_score`/`away_score`, which is ESPN's
    own `competitors[].score`. A census of EVERY git-tracked recommendations
    artifact finds `status_state == "pre"` on ALL 57 matches in them -- the
    sample contained no started match, so it could not tell "always 0" from
    "0 until kickoff". Read straight from ESPN through that same field the
    same day: live fixture 401882908 gives '1'/'0', and completed Atletico
    Madrid v Malaga gives '2'/'0'.

    So the field is real. The defect was that the card published it UNGATED,
    so a fixture that had not kicked off rendered 0-0. The fix is the GATE,
    not the removal -- and the removal cost soccer any score at all on a
    FINAL match, which no other source covers."""

    def test_absent_live_state_yields_no_score(self) -> None:
        self.assertIsNone(cards._real_live_score(None, "home"))
        self.assertIsNone(cards._real_live_score({}, "home"))

    def test_a_genuine_zero_from_the_poller_survives(self) -> None:
        """0-0 is a real and common soccer score. The guard must reject
        ABSENCE, not falsiness, or it would suppress a true nil-nil."""
        self.assertEqual(cards._real_live_score({"score_home": 0}, "home"), 0)

    def test_a_real_score_is_returned(self) -> None:
        self.assertEqual(cards._real_live_score({"score_away": 2}, "away"), 2)
        self.assertEqual(cards._real_live_score({"home": {"score": 3}}, "home"), 3)

    def test_non_numeric_is_rejected_rather_than_rendered(self) -> None:
        self.assertIsNone(cards._real_live_score({"score_home": "--"}, "home"))

    def test_the_pollers_own_key_is_the_one_read(self) -> None:
        """THE BUG THIS CLASS EXISTS FOR, and it was a key-name mismatch.

        `poll_soccer_live_state.poll_league` writes `score_home`/`score_away`
        -- verbatim from `build_live_state`. `_real_live_score` looked only
        for `home_score`/`home_goals`/`home`, so it returned None while the
        real score sat in the file it had just read.

        Asserted against the poller's EXACT payload shape, not a hand-made
        dict that happens to match the new code."""
        poller_entry = {
            "event_id": "401882908",
            "home_team": "Rayo Vallecano",
            "away_team": "Alaves",
            "half": 2,
            "clock_remaining": 420.0,
            "score_home": 1,
            "score_away": 0,
        }
        self.assertEqual(cards._real_live_score(poller_entry, "home"), 1)
        self.assertEqual(cards._real_live_score(poller_entry, "away"), 0)

    def test_the_artifact_score_is_gated_on_state_not_removed(self) -> None:
        match = {"live_home_score": "2", "live_away_score": "0"}
        # Before kickoff it means nothing and must not reach the card.
        self.assertIsNone(cards._artifact_score(match, "home", "pre"))
        # Once the match is real it IS the score -- and for a FINAL match it
        # is the only source that exists.
        self.assertEqual(cards._artifact_score(match, "home", "post"), 2)
        self.assertEqual(cards._artifact_score(match, "away", "post"), 0)
        self.assertEqual(cards._artifact_score(match, "home", "in"), 2)

    def test_the_artifact_score_is_an_int_so_a_real_zero_survives(self) -> None:
        """The template guards on `is not none`, so the stringly-typed "0"
        must become a real int 0 and not be mistaken for absence."""
        value = cards._artifact_score({"live_away_score": "0"}, "away", "post")
        self.assertIsInstance(value, int)
        self.assertEqual(value, 0)

    def test_a_pre_fixture_publishes_no_score(self) -> None:
        """REACHABILITY, and the regression `d9a23a38` shipped: it gated the
        score STRING on `effective_state` while assigning `home_score`/
        `away_score` above it unconditionally -- and the card head reads the
        latter. Asserted through `_match_to_game`, the real caller."""
        game = cards._match_to_game(
            _live_match(status_state="pre", kickoff="2026-09-25T19:30Z"),
            league="la_liga",
            week=1,
            season=2026,
            squad_props=[],
        )
        self.assertIsNone(game["away"]["score"])
        self.assertIsNone(game["home"]["score"])

    def test_an_impossible_final_drops_the_score_with_the_badge(self) -> None:
        """`_effective_status_state` refuses a `post` whose kickoff is days
        away. The score must be refused with it -- a card that has just
        decided a match has not started cannot also show its result."""
        game = cards._match_to_game(
            _live_match(status_state="post", kickoff="2026-09-25T19:30Z"),
            league="la_liga",
            week=1,
            season=2026,
            squad_props=[],
        )
        self.assertIsNone(game["home"]["score"])
        self.assertFalse(game["live_state"]["final"])

    def test_a_finished_match_gets_a_score_with_no_live_state(self) -> None:
        """The case the removal broke. `poll_soccer_live_state` fetches
        `statuses={"in"}` for its `games` block, so a finished match has no
        entry there; without the artifact fallback its card can never show a
        result."""
        game = cards._match_to_game(
            _live_match(status_state="post", kickoff="2026-08-20T19:30Z"),
            league="la_liga",
            week=1,
            season=2026,
            squad_props=[],
        )
        self.assertEqual(game["home"]["score"], 2)
        self.assertEqual(game["away"]["score"], 0)
        self.assertTrue(game["live_state"]["final"])


class LiveClockTests(unittest.TestCase):
    """`shared_game_state` carried `clock: ""` and `period: null` on a match
    genuinely in progress (verified on La Liga 401882908 while
    `live_state.in_progress` was true). MLB's live card shows "BOTTOM 6";
    soccer showed nothing."""

    def test_build_live_state_without_a_clock_reports_no_time_remaining(self) -> None:
        """THE ROOT CAUSE, asserted directly. `build_live_state`'s default
        cutoff is nominal full time, so every live match came back as half 2
        with 0.0 seconds left -- which is what the card was reading."""
        from syndicate.features.soccer.ingestion.espn_live_state import (
            _current_half_and_clock_remaining,
        )

        self.assertEqual(_current_half_and_clock_remaining(5400.0), (2, 0.0))
        # ESPN's real clock at the 70th minute of fixture 401882908.
        self.assertEqual(_current_half_and_clock_remaining(4200.0), (2, 1200.0))

    def test_the_poller_passes_espns_clock(self) -> None:
        """REACHABILITY: the new field is worth nothing if the caller still
        omits `as_of_seconds`."""
        src = io.open("scripts/poll_soccer_live_state.py", encoding="utf-8").read()
        self.assertIn("as_of_seconds=as_of_seconds", src)
        self.assertIn('event.get("status_clock_seconds")', src)

    def test_fetch_events_reads_the_clock_off_the_outer_status_block(self) -> None:
        """The pre-existing local `status` is ESPN's `status.type`, which has
        no clock at all. Reading the clock off it returns None on a match
        that is very much in play."""
        src = io.open(
            "syndicate/features/soccer/ingestion/espn_lineups.py", encoding="utf-8"
        ).read()
        self.assertIn('"status_clock_seconds": status_block.get("clock")', src)

    def test_live_state_block_publishes_the_clock(self) -> None:
        block = cards._live_state_block(
            "in", "2026-08-20T19:30Z", {"status_display_clock": "83'", "status_period": 2}
        )
        self.assertTrue(block["in_progress"])
        self.assertEqual(block["clock"], "83'")

    def test_no_period_key_because_the_minute_already_encodes_it(self) -> None:
        """`_actual_score_section` renders "{period} {clock}"; soccer's "83'"
        cannot be in the first half, so publishing both read "2 83'"."""
        block = cards._live_state_block(
            "in", "2026-08-20T19:30Z", {"status_display_clock": "83'", "status_period": 2}
        )
        self.assertNotIn("period", block)

    def test_no_clock_is_published_for_a_match_not_in_progress(self) -> None:
        for state in ("pre", "post"):
            block = cards._live_state_block(
                state, "2026-08-20T19:30Z", {"status_display_clock": "FT"}
            )
            self.assertNotIn("clock", block, state)

    def test_no_status_string_leaks_into_the_flag_haystack(self) -> None:
        """`game_chip_scoreboard._game_flags` folds `live_state["status"]`
        into a substring search. A display string there would reintroduce the
        prose-matching `_live_state_block` was built to replace."""
        block = cards._live_state_block(
            "in", "2026-08-20T19:30Z", {"status_display_clock": "83'"}
        )
        self.assertNotIn("status", block)

    def test_the_chip_token_is_the_minute_not_a_period_prefix(self) -> None:
        from syndicate.features.shared.game_chip_scoreboard import _live_status_token

        game = {"live_state": {"in_progress": True, "final": False, "clock": "83'"}}
        self.assertEqual(_live_status_token("soccer", game), "83'")
        # The generic branch would have produced a bare period prefix.
        self.assertIsNone(_live_status_token("soccer", {"live_state": {}}))

    def test_a_period_number_renders_as_an_integer(self) -> None:
        """Cross-sport and pre-existing: `_shared_game_state` runs the period
        through `_first_number`, which returns a float, so every live card
        read "Live score -- 2.0 12:45"."""
        section = contract._actual_score_section(
            {
                "away": {"abbr": "GB", "name": "Packers", "score": 10},
                "home": {"abbr": "PIT", "name": "Steelers", "score": 7},
                "live_state": {"in_progress": True, "final": False},
                "shared_game_state": {"live": True, "period": 2.0, "clock": "12:45"},
            }
        )
        self.assertEqual(section["title"], "Live score -- 2 12:45")


class MatchBoxTests(unittest.TestCase):
    """MLB's box tab renders a real "Live / final box" AND a "Sim box".
    Soccer's rendered only sim squad projections, while ESPN's own team
    totals and goal list sat unused in the match summary the poller was
    already fetching."""

    def test_team_stats_and_goals_become_sections(self) -> None:
        sections = cards._match_box_sections(
            MATCH_BOX, away_abbr="ALA", home_abbr="RAY", final=True
        )
        titles = [section["title"] for section in sections]
        self.assertEqual(titles, ["Goals", "Match stats"])
        goals = sections[0]
        self.assertEqual(goals["columns"], ["Min", "Scorer", "Team"])
        self.assertEqual(goals["table_rows"][0][1], "Sergio Camello")
        stats = sections[1]
        self.assertEqual(stats["columns"], ["Stat", "ALA", "RAY"])
        self.assertIn(["Possession", "50.2%", "49.8%"], stats["table_rows"])

    def test_no_reading_yields_no_section_rather_than_a_table_of_dashes(self) -> None:
        self.assertEqual(
            cards._match_box_sections(None, away_abbr="A", home_abbr="H", final=False), []
        )
        self.assertEqual(
            cards._match_box_sections({}, away_abbr="A", home_abbr="H", final=False), []
        )

    def test_a_stat_only_one_team_reported_is_dropped_not_misaligned(self) -> None:
        """Iterating one side's dict alone would silently shift a row's
        columns, so a stat present on one side only must drop out."""
        lopsided = {
            "teams": {
                "away": {"stats": {"Shots": "10", "Offsides": "1"}},
                "home": {"stats": {"Shots": "8"}},
            },
            "goals": [],
        }
        sections = cards._match_box_sections(
            lopsided, away_abbr="A", home_abbr="H", final=True
        )
        self.assertEqual(sections[0]["table_rows"], [["Shots", "10", "8"]])

    def test_an_own_goal_is_labelled_not_dropped(self) -> None:
        """A card that silently drops an own goal disagrees with its own
        scoreline."""
        box = {
            "teams": {},
            "goals": [
                {"team": "Alaves", "scorer": "A Defender", "clock": "12'", "own_goal": True}
            ],
        }
        sections = cards._match_box_sections(box, away_abbr="A", home_abbr="H", final=True)
        self.assertEqual(sections[0]["table_rows"][0][1], "A Defender (OG)")

    def test_the_real_box_is_ordered_before_the_sim_box(self) -> None:
        src = io.open("syndicate/features/soccer/cards.py", encoding="utf-8").read()
        self.assertLess(
            src.index("*_match_box_sections("), src.index("*_squad_box_sections(")
        )

    def test_percentage_conventions_are_declared_per_stat(self) -> None:
        """ESPN mixes them in ONE list: `possessionPct` is 0-100 while
        `passPct` is a 0-1 fraction, and `value` is null on both, so nothing
        in the payload distinguishes them."""
        from syndicate.features.soccer.ingestion import espn_match_box as box

        stats = [
            {"name": "possessionPct", "displayValue": "50.3", "value": None},
            {"name": "passPct", "displayValue": "0.8", "value": None},
        ]
        self.assertEqual(box._stat_display(stats, "possessionPct", box._PCT_0_100), "50.3%")
        self.assertEqual(box._stat_display(stats, "passPct", box._PCT_FRACTION), "80%")

    def test_a_final_box_already_on_disk_is_not_refetched(self) -> None:
        """`live_lens_loop` ticks every ~60s across ten leagues. Re-deriving
        every completed fixture's box on each tick would add an ESPN call per
        finished match per minute to recompute a value that cannot change --
        the `#241` "worker periodic work is never free" failure."""
        src = io.open("scripts/poll_soccer_live_state.py", encoding="utf-8").read()
        self.assertIn(
            'if is_final and isinstance(cached, dict) and cached.get("final")', src
        )

    def test_the_box_is_a_separate_key_from_games(self) -> None:
        """`games` means "in play" -- `live_lens.py` reads it directly, and a
        finished match appearing there would present a settled result as
        live."""
        src = io.open("scripts/poll_soccer_live_state.py", encoding="utf-8").read()
        self.assertIn('"match_box": match_box', src)
        self.assertIn('statuses={"in", "post"}', src)


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
