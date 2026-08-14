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
        # THE LOAD-BEARING PROPERTY, RESTATED -- read this before changing it.
        #
        # 2026-08-03 pinned "an unmatched question must not land on
        # bet_analysis", because bet_analysis dead-ends and renders as "No
        # structured answer came back". That property is unchanged and is what
        # this asserts.
        #
        # 2026-08-14 narrowed WHERE it lands. The original assertion was
        # `== "market_summary"` on a gibberish string, which conflated "not the
        # dead end" (the real property) with "a board summary" (one way of
        # satisfying it). Gibberish now routes to `out_of_scope`, which is also
        # not the dead end and is a better answer than five betting picks.
        #
        # A vague BETTING question still gets the summary -- that is the case
        # 2026-08-03 actually reported, and it is covered by
        # test_common_board_summary_phrasings and
        # test_vague_betting_questions_still_get_the_summary_default below.
        decision = self.router.route("qwertyuiop nothing matches this at all")
        self.assertNotEqual(decision.intent, "bet_analysis")
        self.assertNotEqual(decision.handler_name, "handle_bet_analysis")

    def test_vague_betting_questions_still_get_the_summary_default(self) -> None:
        # The 2026-08-03 fix, pinned directly rather than via a gibberish
        # proxy: a question that is clearly about the board but matches no
        # explicit rule must still reach the summary, not be declined.
        for question in (
            "who is favored in the late games",
            "how has the model performed over the last 30 days",
            "how is jokic looking tonight",
            "best tb targets today",
            "how many goals will arsenal score",
            "what is united's price this weekend",
        ):
            with self.subTest(question=question):
                self.assertEqual(self.router.route(question).intent, "market_summary")

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

    def test_per_pick_ask_button_context_routes_to_bet_analysis(self) -> None:
        # Reported live 2026-08-04: the board's "Ask about this pick" button
        # (ask_bar.js's wireAskButtons) always asks "What's the case for and
        # against <selection>?" -- a phrasing that matches no rule above --
        # while attaching real context (selection/candidate_id/market)
        # identifying exactly one pick. Every per-card click therefore fell
        # through to the market_summary default and never returned real
        # single-bet analysis, no matter which card was clicked.
        decision = self.router.route(
            "What's the case for and against Colorado Rockies steam move?",
            context={"sport": "mlb", "selection": "Colorado Rockies steam move", "candidate_type": "game"},
        )
        self.assertEqual(decision.intent, "bet_analysis")
        self.assertEqual(decision.handler_name, "handle_bet_analysis")

    def test_context_subject_fallback_yields_to_an_explicit_textual_match(self) -> None:
        # A stale/incidental context object (carried over from a prior
        # per-card click) must never override an EXPLICIT question the user
        # actually typed -- the textual match still wins on its own merits.
        general = self.router.route(
            "Summarize today's best opportunities across the board and what to watch for.",
            context={"selection": "Colorado Rockies steam move"},
        )
        self.assertEqual(general.intent, "market_summary")

        comparison = self.router.route("Compare the Lakers and Celtics", context={"selection": "Colorado Rockies steam move"})
        self.assertEqual(comparison.intent, "comparison")

    def test_context_without_a_subject_does_not_change_the_default(self) -> None:
        # A bare `sport` is not a subject, so the per-pick fallback must not
        # engage. Post-2026-08-14 the gibberish lands on out_of_scope rather
        # than a summary; what is pinned here is that it does not become
        # bet_analysis just because a sport rode along.
        decision = self.router.route("qwertyuiop nothing matches this at all", context={"sport": "mlb"})
        self.assertNotEqual(decision.intent, "bet_analysis")


class OutOfScopeRoutingTests(unittest.TestCase):
    """`market_summary` stopped being the answer to non-betting questions.

    Measured on production 2026-08-14: `market_summary` was the resolved intent
    on 40 of 52 regression questions, and "What is the capital of France?"
    returned five betting opportunities with a "Best edge 4.9%" summary. A
    surface that answers everything is worse than one that declines, because a
    user cannot tell the two modes apart.
    """

    def setUp(self) -> None:
        self.router = SyndicateQueryRouter()

    def test_general_knowledge_is_declined(self) -> None:
        for question in (
            "what is the capital of france?",
            "who is the president",
            "translate this to spanish",
            "what time is it",
        ):
            with self.subTest(question=question):
                decision = self.router.route(question)
                self.assertEqual(decision.intent, "out_of_scope")
                self.assertEqual(decision.matched_terms, ("no_domain_vocabulary",))

    def test_weather_is_declined_despite_naming_a_stadium(self) -> None:
        # "stadium" is sports vocabulary but not BETTING vocabulary, and the
        # gate is deliberately about the latter.
        decision = self.router.route("what is the weather at the stadium right now?")
        self.assertEqual(decision.intent, "out_of_scope")

    def test_personal_records_are_declined_even_though_they_say_betting(self) -> None:
        # This is why the personal-records rule runs BEFORE the domain gate:
        # these questions carry betting vocabulary and would otherwise pass it.
        for question in (
            "what is my account balance and betting history?",
            "show me my bets from last week",
            "what is my portfolio worth",
        ):
            with self.subTest(question=question):
                decision = self.router.route(question)
                self.assertEqual(decision.intent, "out_of_scope")
                self.assertEqual(decision.matched_terms, ("personal_records",))

    def test_an_attached_pick_still_wins_over_the_gate(self) -> None:
        # A per-card "Ask about this pick" click attaches a subject and its
        # phrasing may carry no domain noun. The context fallback runs before
        # the gate, so the click keeps working.
        decision = self.router.route(
            "What's the case for and against Colorado Rockies steam move?",
            context={"selection": "Colorado Rockies steam move"},
        )
        self.assertEqual(decision.intent, "bet_analysis")

    def test_the_gate_only_applies_when_nothing_matched(self) -> None:
        # An explicit rule match must never be overridden by the gate, even if
        # the phrasing is otherwise sparse.
        self.assertEqual(self.router.route("compare a and b").intent, "comparison")
        self.assertEqual(self.router.route("top edges").intent, "market_summary")

    def test_declining_is_not_the_bet_analysis_dead_end(self) -> None:
        # The whole point of the 2026-08-03 default. A decline must be its own
        # intent, not a fall-through to the empty single-bet shell.
        decision = self.router.route("what is the capital of france?")
        self.assertNotEqual(decision.handler_name, "handle_bet_analysis")
        self.assertEqual(decision.handler_name, "handle_out_of_scope")



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
