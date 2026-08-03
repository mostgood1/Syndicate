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


if __name__ == "__main__":
    unittest.main()
