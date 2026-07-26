"""Regression tests for the ranking defect: computed signals never reached the order.

Three signals were fully implemented and then ignored by every ordering
decision, so a query that expressed a preference ranked exactly like one that
did not:

- `_risk_profile_score_adjustment` was DEAD CODE -- defined, never called from
  anywhere. So `score` was `edge x confidence - tier_penalty` and nothing else,
  and "highest confidence" and "highest upside" returned byte-identical
  rankings even though the risk profile parsed correctly and reached
  `preferences`.
- `_market_specific_score_adjustment` was dead in exactly the same way.
- `advanced_ready` and `source_summary_score` were computed and displayed but
  absent from the board sort, which ranked on raw `simulated_edge` -- a single
  component of `score` outvoting the composite that contained it.

Ordering is decided in two places and both matter, which is why these tests
cover both: `score_candidate` computes the composite, and
`build_intelligence_board_contract` sorts the cards that become the board. A
fix to either alone does not change what a user sees.
"""

from __future__ import annotations

from syndicate.features.intelligence import _market_context
from syndicate.features.intelligence import _risk_profile_score_adjustment
from syndicate.features.intelligence_board import build_intelligence_board_contract


JUDGE = {
    "confidence": "38%",
    "edge": "+12.8%",
    "odds": "+320",
    "market": "Hitter Home Runs",
    "pick": "Over 0.5",
    "name": "Aaron Judge Over 0.5 Home Runs",
    "candidate_type": "prop",
    "sport_slug": "mlb",
}
FREEMAN = {
    "confidence": "64%",
    "edge": "+2.5%",
    "odds": "-135",
    "market": "Hitter Total Bases",
    "pick": "Over 1.5",
    "name": "Freddie Freeman Over 1.5 Total Bases",
    "candidate_type": "prop",
    "sport_slug": "mlb",
}


def _adjust(candidate, risk_profile):
    return _risk_profile_score_adjustment(
        candidate, {"risk_profile": risk_profile}, _market_context(candidate)
    )


class TestRiskProfileAdjustment:
    """The adjustment itself. It was always correct -- it was simply never called."""

    def test_conservative_prefers_the_high_confidence_short_price(self):
        assert _adjust(FREEMAN, "conservative") > _adjust(JUDGE, "conservative")

    def test_aggressive_prefers_the_long_shot(self):
        assert _adjust(JUDGE, "aggressive") > _adjust(FREEMAN, "aggressive")

    def test_the_two_profiles_actually_disagree(self):
        """The whole defect in one assertion: these must not be the same order."""
        conservative_winner = max([JUDGE, FREEMAN], key=lambda c: _adjust(c, "conservative"))
        aggressive_winner = max([JUDGE, FREEMAN], key=lambda c: _adjust(c, "aggressive"))
        assert conservative_winner is not aggressive_winner

    def test_balanced_is_inert(self):
        """Default queries must be unaffected, or this changes every ranking."""
        assert _adjust(JUDGE, "balanced") == 0.0
        assert _adjust(FREEMAN, "balanced") == 0.0

    def test_unknown_profile_is_inert(self):
        assert _adjust(JUDGE, "") == 0.0
        assert _adjust(JUDGE, "nonsense") == 0.0

    def test_adjustment_is_large_enough_to_reorder_real_scores(self):
        """A correct sign is useless if the magnitude cannot move anything.

        Base scores here are the real ones: edge x source_strength - tier
        penalty, i.e. 12.8*0.5-0.2 = 6.2 for Judge and 2.5*0.5-0.2 = 1.05 for
        Freeman. Conservative must overturn a 5-point deficit.
        """
        judge_total = 6.2 + _adjust(JUDGE, "conservative")
        freeman_total = 1.05 + _adjust(FREEMAN, "conservative")
        assert freeman_total > judge_total


class TestScorerActuallyCallsTheAdjustment:
    """The wiring, which is what was missing.

    The class above proves the adjustment computes the right thing -- it always
    did. These prove `score_candidate` now *calls* it. Without this, the entire
    fix could be reverted and every test above would still pass.
    """

    def _score(self, candidate, risk_profile):
        import copy

        from syndicate.features.intelligence import score_candidate

        scored = score_candidate(copy.deepcopy(candidate), preferences={"risk_profile": risk_profile})
        return float(scored.get("score"))

    def test_risk_profile_changes_the_score(self):
        conservative = self._score(JUDGE, "conservative")
        aggressive = self._score(JUDGE, "aggressive")
        assert conservative != aggressive

    def test_balanced_leaves_the_base_score_untouched(self):
        """Pins the base formula: edge x source_strength - tier_penalty.

        12.8 * 0.5 - 0.2 = 6.2. If this drifts, the worked examples in the
        commit message and the magnitude test above are no longer meaningful.
        """
        assert self._score(JUDGE, "balanced") == 6.2

    def test_conservative_penalises_the_long_shot_and_aggressive_rewards_it(self):
        base = self._score(JUDGE, "balanced")
        assert self._score(JUDGE, "conservative") < base
        assert self._score(JUDGE, "aggressive") > base

    def test_conservative_flips_the_pair_order_end_to_end(self):
        """The user-visible outcome, at the scorer level."""
        assert self._score(FREEMAN, "conservative") > self._score(JUDGE, "conservative")
        assert self._score(JUDGE, "aggressive") > self._score(FREEMAN, "aggressive")


def _card(**overrides):
    base = {
        "name": "Some Player Over 1.5",
        "player_name": "Some Player",
        "selection": "Over 1.5",
        "market": "points",
        "matchup": "AAA at BBB",
        "sport_slug": "nba",
        "line": 1.5,
        "lane": "pregame",
    }
    base.update(overrides)
    return base


def _order(cards):
    contract = build_intelligence_board_contract({"recommendations": cards})
    return [card.get("name") for card in contract["cards"]]


class TestBoardSortUsesTheComposite:
    def test_higher_score_ranks_first(self):
        order = _order([
            _card(name="low", score=1.0, matchup="A at B"),
            _card(name="high", score=9.0, matchup="C at D"),
        ])
        assert order[0] == "high"

    def test_score_outranks_a_single_raw_component(self):
        """The exact defect: simulated_edge was consulted, score was not.

        The lower-scoring candidate has the bigger raw edge. Before the fix it
        won; the composite has to take precedence over its own input.
        """
        order = _order([
            _card(name="big-edge-low-score", score=1.0, simulated_edge=99.0, matchup="A at B"),
            _card(name="better-score", score=9.0, simulated_edge=1.0, matchup="C at D"),
        ])
        assert order[0] == "better-score"


class TestReadinessGate:
    def test_ready_outranks_blocked_even_with_a_worse_score(self):
        """Missing model inputs must not be outvoted by a big raw number."""
        order = _order([
            _card(name="blocked", advanced_ready=False, score=50.0, matchup="A at B"),
            _card(name="ready", advanced_ready=True, score=1.0, matchup="C at D"),
        ])
        assert order[0] == "ready"

    def test_publication_priority_still_wins_over_readiness(self):
        """Readiness sits below the explicit editorial override, not above it."""
        order = _order([
            _card(name="ready", advanced_ready=True, publication_priority=0, matchup="A at B"),
            _card(name="promoted", advanced_ready=False, publication_priority=5, matchup="C at D"),
        ])
        assert order[0] == "promoted"


class TestSourceSummaryTiebreak:
    def test_breaks_a_tie_between_otherwise_identical_props(self):
        """Both candidates equal on every quantitative signal; only the
        writeup differs -- one argues for the pick, one against."""
        order = _order([
            _card(name="argues-against", sport_slug="wnba", score=5.0, confidence=60,
                  source_summary_score=-2.0, matchup="A at B"),
            _card(name="argues-for", sport_slug="wnba", score=5.0, confidence=60,
                  source_summary_score=2.0, matchup="C at D"),
        ])
        assert order[0] == "argues-for"

    def test_does_not_override_a_real_score_difference(self):
        """It is a tiebreaker. A positive writeup must not beat a better score.

        Folding this into `score` instead was tried and did exactly that,
        regressing the readiness ordering -- hence its position last.
        """
        order = _order([
            _card(name="weak-but-praised", sport_slug="wnba", score=1.0,
                  source_summary_score=3.0, matchup="A at B"),
            _card(name="strong", sport_slug="wnba", score=9.0,
                  source_summary_score=-3.0, matchup="C at D"),
        ])
        assert order[0] == "strong"
