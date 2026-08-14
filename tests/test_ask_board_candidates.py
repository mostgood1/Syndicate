"""`M1` -- Ask answers aggregation questions from the whole published board.

Measured on production 2026-08-14, the funnel behind a ranking question was
14,216 opportunities considered -> 200 published -> 145 in the snapshot chat
reads -> a 12-row evidence-pack ceiling -> **5 rows returned**, and only MLB had
a ranking path at all. Separately, chat reported a top edge of 5.02% while
`/api/board/layer2-shortlist` served 13.59% at the same instant, because the two
read different pools.

Everything here runs against a SYNTHETIC shortlist payload rather than the real
artifact. That is deliberate: the local checkout has no shortlist file at all
(`read_layer2_shortlist` returns None), so a test that used the real reader
would pass by vacuously standing down and would keep passing if the ranking,
filtering or counting logic were deleted.
"""

from __future__ import annotations

import unittest
from unittest import mock

from syndicate.blueprints.ask_the_syndicate_data import (
    _board_candidates_evidence,
    _board_market_filter,
    _board_min_edge_pct,
    _board_ranking_intent,
    _fetchers_for_sport,
    _question_words,
)


def _row(sport, market, **kw):
    row = {
        "sport": sport,
        "market": market,
        "ev_pct": kw.get("ev"),
        "model_edge_pct": kw.get("edge"),
        "player_name": kw.get("player"),
        "side": kw.get("side", "over"),
        "line": kw.get("line", 1.5),
        "home_team": kw.get("home", "Home FC"),
        "away_team": kw.get("away", "Away FC"),
        "kind": kw.get("kind", "prop"),
    }
    return row


PAYLOAD = {
    "written_at": "2026-08-14T20:00:00Z",
    "opportunities_considered": 14216,
    "active_sports": ["mlb", "nfl", "soccer", "wnba"],
    "rows": [
        _row("mlb", "batter_total_bases", ev=3.1, edge=11.5, player="A Judge"),
        _row("mlb", "batter_rbis", ev=2.0, edge=4.2, player="B Witt"),
        _row("mlb", "batter_total_bases", ev=1.0, edge=6.0, player="C Ruiz"),
        _row("soccer", "player_shots", ev=5.5, edge=None, player="D Saka"),
        _row("soccer", "goal_scorer", ev=4.0, edge=None, player="E Haaland"),
        _row("wnba", "player_points", ev=-1.0, edge=None, player="F Wilson"),
        _row("nfl", "totals", ev=0.5, edge=2.0, player=None, kind="game"),
    ],
}


def _fetch(question, context=None):
    with mock.patch(
        "pipeline.intelligence_state.read_layer2_shortlist", return_value=PAYLOAD
    ):
        return _board_candidates_evidence(question, context or {"selected_date": "2026-08-14"})


class RankingIntentTests(unittest.TestCase):
    def test_aggregation_phrasings_are_recognised(self) -> None:
        for question in (
            "what are the biggest edges on the board tonight?",
            "rank today's best opportunities across every sport",
            "show me every play with an edge over 5 percent",
            "which sport has the most value today",
            "best soccer bets today",
        ):
            with self.subTest(question=question):
                self.assertTrue(_board_ranking_intent(question, _question_words(question)))

    def test_single_subject_questions_are_not_aggregations(self) -> None:
        # These must fall through to the entity fetchers, not be answered with
        # a leaderboard.
        for question in (
            "how is jokic looking tonight",
            "what do you think of the dodgers spread",
            "cubs vs cardinals projection",
        ):
            with self.subTest(question=question):
                self.assertFalse(_board_ranking_intent(question, _question_words(question)))

    def test_a_non_aggregation_question_returns_none_not_an_empty_table(self) -> None:
        # None and an empty section mean different things upstream:
        # collect_focused_evidence merges only real sections.
        self.assertIsNone(_fetch("cubs vs cardinals projection"))


class FilterParsingTests(unittest.TestCase):
    def test_edge_floor_is_parsed(self) -> None:
        self.assertEqual(_board_min_edge_pct("every play with an edge over 5 percent"), 5.0)
        self.assertEqual(_board_min_edge_pct("edges above 2.5%"), 2.5)
        self.assertEqual(_board_min_edge_pct("at least 10 pct"), 10.0)

    def test_no_floor_when_none_is_stated(self) -> None:
        self.assertIsNone(_board_min_edge_pct("what are the best edges tonight"))

    def test_market_hint_is_parsed(self) -> None:
        self.assertEqual(_board_market_filter("which total bases props have value"), "total_bases")
        self.assertEqual(_board_market_filter("best anytime scorer bets"), "goal_scorer")

    def test_no_market_hint_leaves_the_board_unfiltered(self) -> None:
        self.assertIsNone(_board_market_filter("what are the biggest edges tonight"))


class BoardCandidatesTests(unittest.TestCase):
    def test_the_whole_board_is_ranked_not_a_prefix(self) -> None:
        result = _fetch("what are the biggest edges on the board tonight?")
        self.assertIsNotNone(result)
        evidence = result["evidence"]
        self.assertEqual(evidence["total_published"], 7)
        self.assertEqual(evidence["matched"], 7)
        # The denominator travels with the answer -- that is what makes it an
        # aggregation rather than a sample.
        self.assertEqual(evidence["opportunities_considered"], 14216)

    def test_the_top_edge_is_the_boards_top_edge(self) -> None:
        # The divergence case: chat said 5.02% while the board served 13.59%.
        result = _fetch("what are the biggest edges on the board tonight?")
        self.assertAlmostEqual(result["evidence"]["top"][0]["model_edge_pct"], 11.5)

    def test_rows_without_a_model_are_ranked_below_but_not_dropped(self) -> None:
        # Only 57 of 200 published rows carry model_edge_pct; ranking on it
        # alone would silently drop soccer and WNBA entirely.
        result = _fetch("rank every opportunity on the board")
        sports = {row["sport"] for row in result["evidence"]["top"]}
        self.assertIn("soccer", sports)
        self.assertIn("wnba", sports)
        modelled = [r for r in result["evidence"]["top"] if r.get("model_edge_pct") is not None]
        unmodelled = [r for r in result["evidence"]["top"] if r.get("model_edge_pct") is None]
        self.assertTrue(modelled and unmodelled)
        last_modelled = result["evidence"]["top"].index(modelled[-1])
        first_unmodelled = result["evidence"]["top"].index(unmodelled[0])
        self.assertLess(last_modelled, first_unmodelled)

    def test_a_row_without_a_model_says_so_rather_than_showing_a_number(self) -> None:
        result = _fetch("rank every opportunity on the board")
        cells = [row[4] for row in result["tables"][0]["rows"]]
        self.assertIn("no model", cells)

    def test_sport_scoping_is_exact_not_substring(self) -> None:
        # `"nba" in "wnba"` is True -- the bug this avoids.
        result = _fetch("best bets today", {"sport": "nba", "selected_date": "2026-08-14"})
        self.assertEqual(result["evidence"]["matched"], 0)
        self.assertEqual(result["tables"], [])
        self.assertIn("no", result["evidence"]["note"])

    def test_an_empty_sport_result_is_reported_not_widened(self) -> None:
        # Showing MLB rows for an NHL question would be worse than saying there
        # are none.
        result = _fetch("best bets today", {"sport": "nhl", "selected_date": "2026-08-14"})
        self.assertEqual(result["evidence"]["matched"], 0)
        self.assertEqual(result["evidence"]["filters"], ["sport=nhl"])

    def test_sport_scoping_keeps_only_that_sport(self) -> None:
        result = _fetch("best bets today", {"sport": "soccer", "selected_date": "2026-08-14"})
        self.assertEqual(result["evidence"]["matched"], 2)
        self.assertEqual({row["sport"] for row in result["evidence"]["top"]}, {"soccer"})

    def test_edge_floor_filters_and_reports_the_denominator(self) -> None:
        result = _fetch("show me every play with an edge over 5 percent")
        self.assertEqual(result["evidence"]["matched"], 2)  # 11.5 and 6.0
        self.assertEqual(result["evidence"]["total_published"], 7)
        self.assertIn("model_edge>=5.0%", result["evidence"]["filters"])

    def test_market_filter_narrows_when_it_matches(self) -> None:
        result = _fetch("which total bases props have the most value")
        self.assertEqual(result["evidence"]["matched"], 2)
        self.assertTrue(all("total_bases" in r["market"] for r in result["evidence"]["top"]))

    def test_market_filter_falls_back_rather_than_returning_nothing(self) -> None:
        # A market hint is guessed from prose, unlike the sport which comes
        # from context -- so a miss must not empty the board.
        result = _fetch("best rebounds props today", {"sport": "mlb", "selected_date": "2026-08-14"})
        self.assertEqual(result["evidence"]["matched"], 3)
        self.assertNotIn("market~player_rebounds", result["evidence"]["filters"])

    def test_as_of_comes_from_the_artifact_not_the_clock(self) -> None:
        result = _fetch("best edges tonight")
        self.assertEqual(result["evidence"]["as_of"], "2026-08-14T20:00:00Z")

    def test_no_chart_when_no_row_carries_a_model_number(self) -> None:
        # An empty bar chart implies we had nothing to say; the table already
        # says "no model" per row.
        result = _fetch("best bets today", {"sport": "soccer", "selected_date": "2026-08-14"})
        self.assertEqual(result["charts"], [])

    def test_missing_artifact_stands_down(self) -> None:
        with mock.patch("pipeline.intelligence_state.read_layer2_shortlist", return_value=None):
            self.assertIsNone(_board_candidates_evidence("best edges tonight", {}))

    def test_empty_artifact_stands_down(self) -> None:
        with mock.patch("pipeline.intelligence_state.read_layer2_shortlist", return_value={"rows": []}):
            self.assertIsNone(_board_candidates_evidence("best edges tonight", {}))


class RegistrationTests(unittest.TestCase):
    def test_every_sport_gets_the_board_fetcher_first(self) -> None:
        for sport in ("mlb", "wnba", "nba", "nhl", "ncaaf", "nfl", "soccer", "ncaab", ""):
            with self.subTest(sport=sport):
                fetchers = _fetchers_for_sport(sport, "best edges today")
                self.assertTrue(fetchers)
                self.assertEqual(fetchers[0].__name__, "_board_candidates_evidence")

    def test_soccer_and_ncaab_are_no_longer_empty(self) -> None:
        # Both returned `[]` before M1 -- a correctly-routed soccer question got
        # no evidence at all, and soccer is half the published board.
        for sport in ("soccer", "ncaab"):
            with self.subTest(sport=sport):
                self.assertEqual(len(_fetchers_for_sport(sport, "best edges today")), 1)

    def test_the_mlb_ranking_branch_still_takes_precedence_for_its_own_markets(self) -> None:
        # M1 must not displace the MLB leaderboard for a question that names an
        # MLB prop market -- both run, board first.
        fetchers = _fetchers_for_sport("mlb", "best home run targets today")
        names = [f.__name__ for f in fetchers]
        self.assertEqual(names[0], "_board_candidates_evidence")
        self.assertIn("_mlb_top_candidates_evidence", names)


if __name__ == "__main__":
    unittest.main()
