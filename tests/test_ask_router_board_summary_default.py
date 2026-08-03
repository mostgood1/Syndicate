"""Ask-the-Syndicate routing for board-summary questions.

Reported live 2026-08-03: asking the home-page embed "Summarize today's
best opportunities across the board and what to watch for." returned
"No structured answer came back for this question -- try rephrasing it."

The board was healthy (10 cards, ok=True). The cause was routing:
`market_summary` matched only the two literal phrases "best bets" and
"top edges", so that question matched NO rule at all and fell through to
the router's default -- `bet_analysis`, which tries to match one specific
recommendation and, failing, emits an empty shell with
`relevance_matched: false`.

Two properties are pinned here: general questions route to a summary, and
the DEFAULT for an unmatched question is a summary rather than a dead end.
"""

from __future__ import annotations

import unittest

from syndicate.blueprints.ask_the_syndicate_router import SyndicateQueryRouter


class BoardSummaryRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = SyndicateQueryRouter()

    def test_the_reported_home_page_question_routes_to_summary(self) -> None:
        decision = self.router.route(
            "Summarize today's best opportunities across the board and what to watch for."
        )
        self.assertEqual(decision.intent, "market_summary")
        self.assertEqual(decision.handler_name, "handle_market_summary")

    def test_unmatched_question_defaults_to_summary_not_single_bet_analysis(self) -> None:
        # The load-bearing property: bet_analysis dead-ends when nothing
        # matches, a summary always has an answer. An unrecognised question
        # must not land on the dead end.
        decision = self.router.route("qwertyuiop nothing matches this at all")
        self.assertEqual(decision.intent, "market_summary")

    def test_common_board_summary_phrasings(self) -> None:
        for question in (
            "summarize the slate",
            "give me a rundown of tonight",
            "what should i bet tonight",
            "anything good on the board?",
            "any good player props?",
            "best opportunities today",
            "what to watch for tonight",
            "overview of today's board",
        ):
            with self.subTest(question=question):
                self.assertEqual(self.router.route(question).intent, "market_summary")

    def test_originally_supported_phrases_still_route_to_summary(self) -> None:
        for question in ("what are the best bets today?", "show me the top edges"):
            with self.subTest(question=question):
                self.assertEqual(self.router.route(question).intent, "market_summary")

    def test_specific_single_bet_questions_still_reach_bet_analysis(self) -> None:
        # Broadening the summary rule must not swallow questions that name
        # one concrete bet -- those genuinely want the analysis path.
        decision = self.router.route("what do you think of the Dodgers spread")
        self.assertEqual(decision.intent, "bet_analysis")

    def test_comparison_and_matchup_are_unaffected(self) -> None:
        self.assertEqual(self.router.route("compare Judge and Ohtani").intent, "comparison")
        self.assertEqual(self.router.route("Yankees vs Red Sox").intent, "matchup_analysis")



class BoardSummaryAnswerContentTests(unittest.TestCase):
    """The snapshot path is the product now -- the LLM narration layer is
    deliberately not in use, so a board-summary answer has to stand on its
    own without it."""

    def test_general_question_gets_an_affirmative_data_derived_summary(self) -> None:
        from syndicate.blueprints.ask_the_syndicate_adapter import _board_summary_sentence

        rows = [
            {"sport": "MLB", "edge": 0.0812},
            {"sport": "WNBA", "edge": 0.0451},
        ]
        sentence = _board_summary_sentence(rows)
        self.assertIn("top 2 opportunities", sentence)
        self.assertIn("MLB", sentence)
        self.assertIn("WNBA", sentence)
        self.assertIn("8.1%", sentence)
        # Must not lead with a negative -- that is the reported bug.
        self.assertFalse(sentence.startswith("No board opportunity"))

    def test_singular_is_not_pluralised(self) -> None:
        from syndicate.blueprints.ask_the_syndicate_adapter import _board_summary_sentence

        self.assertIn("top 1 opportunity", _board_summary_sentence([{"sport": "MLB"}]))

    def test_empty_board_says_so_plainly(self) -> None:
        from syndicate.blueprints.ask_the_syndicate_adapter import _board_summary_sentence

        self.assertEqual(_board_summary_sentence([]), "No opportunities are on the board right now.")

    def test_rows_without_edges_still_produce_a_sentence(self) -> None:
        from syndicate.blueprints.ask_the_syndicate_adapter import _board_summary_sentence

        sentence = _board_summary_sentence([{"sport": "MLB"}, {"sport": "MLB"}])
        self.assertIn("top 2 opportunities", sentence)
        self.assertNotIn("Best edge", sentence)

    def test_subject_questions_keep_the_not_matched_guard(self) -> None:
        from syndicate.blueprints.ask_the_syndicate_adapter import _is_general_board_question

        # The guard exists so a board list is never silently implied to be
        # about the asked-for subject. That must survive this change.
        self.assertFalse(_is_general_board_question("how does nikola jokic look tonight"))
        self.assertFalse(_is_general_board_question("what do you think of the Dodgers spread"))
        self.assertTrue(_is_general_board_question("summarize today's board"))


if __name__ == "__main__":
    unittest.main()
