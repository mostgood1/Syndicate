"""Where the recommendation lane is allowed to get a probability from.

Lane `recommendation-lane-correctness`, from the 2026-08-14 model audit
(`.syndicate/audit_2026-08-14_models.md` section 4, ranked fixes 3 and 4).

The defect these pin: `_fair_probability`'s chain was
`fair_probability -> model_probability -> confidence -> score/100 -> 0.5`, and
three of those five rungs are not probabilities at all. Each test below names
one rung and fails if it comes back.

Deliberately NOT a test of "the number went down". A rung that silently returns
a plausible-looking float is exactly what shipped for months; the assertion has
to be that the value is ABSENT, because absent is what makes the exclusion in
`filter_candidates` fire with a truthful reason.
"""

from __future__ import annotations

import unittest

from syndicate.features.shared.recommendation_engine import (
    _market_fair_probability,
    _model_probability_only,
    _repriced_probabilities,
    calculate_edge,
    filter_candidates,
)


class ProbabilitySourceTests(unittest.TestCase):
    """Only a model may supply P(outcome)."""

    def test_confidence_is_not_a_probability(self) -> None:
        # `confidence` comes from `score_candidate`'s `source_strength` plus
        # readiness/movement bonuses: how much we trust the INPUT, not how often
        # the bet wins. Consumed as P(outcome) it manufactured +45 points of
        # edge on a +150 price against a 0.0 threshold.
        candidate = {"odds": "+150", "confidence": 0.85}
        self.assertIsNone(_model_probability_only(candidate))
        self.assertIsNone(calculate_edge(candidate)["fair_probability"])
        self.assertIsNone(calculate_edge(candidate)["edge"])

    def test_score_is_not_a_probability(self) -> None:
        # `score` is `edge x confidence - tier_penalty` -- unbounded, routinely
        # negative. `score/100` produced fair probabilities of 0.01-0.13 and so
        # a large NEGATIVE edge, silently rejecting every model-free candidate
        # under a reason that claimed the edge had been measured.
        candidate = {"odds": "+150", "score": 4.05}
        self.assertIsNone(_model_probability_only(candidate))
        self.assertIsNone(calculate_edge(candidate)["fair_probability"])

    def test_no_coin_flip_default(self) -> None:
        # The `0.5` terminal. Unreachable in the real pipeline (every
        # `filter_candidates` call site is fed `_score_candidates` output, and
        # `score_candidate` always assigns `score`), so removing ONLY this
        # would have been an inert fix. Pinned anyway: it is reachable from any
        # caller that does not pre-score.
        self.assertIsNone(_model_probability_only({"odds": "+150"}))
        self.assertIsNone(calculate_edge({"odds": "+150"})["fair_probability"])

    def test_model_probability_is_used(self) -> None:
        candidate = {"odds": "+150", "model_probability": 0.57}
        self.assertAlmostEqual(_model_probability_only(candidate), 0.57, places=4)

    def test_simulation_payload_is_a_model_output(self) -> None:
        candidate = {"odds": "+150", "simulation": {"model_probability": 0.61}}
        self.assertAlmostEqual(_model_probability_only(candidate), 0.61, places=4)


class MarketFairProbabilityTests(unittest.TestCase):
    """The market's fair value is a different quantity from the model's."""

    def test_reads_the_nested_quote(self) -> None:
        candidate = {"quote": {"fair_probability": 0.48, "fair_method": "consensus"}}
        self.assertEqual(_market_fair_probability(candidate), (0.48, "consensus"))

    def test_ignores_the_flattened_key(self) -> None:
        # REGRESSION PIN. `quote_enrichment._FLAT_QUOTE_FIELDS` copies the
        # market's fair value to the top level under `fair_probability`, and
        # `rank_recommendations` writes the MODEL's probability to that same
        # key on its own output. Reading it here made a recommendation compare
        # a model against itself: `0.6 / 0.6 - 1 == 0`, which turned
        # `test_rank_recommendations_reprices_live_current_odds` red at
        # `expected_value 0.0`.
        candidate = {"fair_probability": 0.6, "model_probability": 0.6, "odds": "+150"}
        self.assertEqual(_market_fair_probability(candidate), (None, None))
        self.assertAlmostEqual(calculate_edge(candidate)["edge"], 0.6 - 0.4, places=4)


class EdgePricedAgainstTests(unittest.TestCase):
    """`#238`: a model compared to a vigged price is wrong by ~half the hold."""

    def test_prices_against_no_vig_fair_and_says_so(self) -> None:
        candidate = {
            "odds": "-110",
            "model_probability": 0.55,
            "quote": {"fair_probability": 0.50, "fair_method": "consensus"},
        }
        result = calculate_edge(candidate)
        self.assertEqual(result["edge_priced_against"], "no_vig_fair")
        self.assertAlmostEqual(result["market_fair_probability"], 0.50, places=4)
        self.assertAlmostEqual(result["edge"], 0.05, places=4)

    def test_modelled_fair_is_labelled_apart_from_a_measured_one(self) -> None:
        # `book_margin_model`'s docstring: an estimate must never be silently
        # mixed with a measurement.
        candidate = {
            "odds": "+10000",
            "model_probability": 0.02,
            "quote": {"fair_probability": 0.0092, "fair_method": "book_margin_model"},
        }
        self.assertEqual(calculate_edge(candidate)["edge_priced_against"], "modelled_no_vig_fair")

    def test_no_opposing_side_keeps_the_vigged_price_but_labels_it(self) -> None:
        candidate = {"odds": "-110", "model_probability": 0.55}
        result = calculate_edge(candidate)
        self.assertEqual(result["edge_priced_against"], "vigged_current_price")
        self.assertIsNone(result["market_fair_probability"])

    def test_the_vig_error_has_the_size_238_measured(self) -> None:
        # A -110/-110 market: each side implies 0.5238, the pair holds 4.76%,
        # the no-vig fair is 0.5000. Pricing a model against the raw price
        # understates edge by half the hold -- the whole point of `#238`.
        vigged = calculate_edge({"odds": "-110", "model_probability": 0.55})
        fair = calculate_edge(
            {
                "odds": "-110",
                "model_probability": 0.55,
                "quote": {"fair_probability": 0.50, "fair_method": "consensus"},
            }
        )
        self.assertAlmostEqual(fair["edge"] - vigged["edge"], 0.0238, places=3)

    def test_repriced_probabilities_uses_the_same_rule(self) -> None:
        # The second of the two sites. `_repriced_probabilities` overrode
        # whatever the candidate carried with a raw `_parse_american_odds`.
        candidate = {
            "odds": "-110",
            "current_odds": "-110",
            "model_probability": 0.55,
            "quote": {"fair_probability": 0.50, "fair_method": "consensus"},
        }
        result = _repriced_probabilities(candidate)
        self.assertEqual(result["edge_priced_against"], "no_vig_fair")
        self.assertAlmostEqual(result["edge"], 0.05, places=4)
        self.assertAlmostEqual(result["expected_value"], 0.10, places=4)

    def test_repriced_probabilities_refuses_confidence(self) -> None:
        candidate = {"odds": "+150", "current_odds": "+150", "confidence": 0.85}
        result = _repriced_probabilities(candidate)
        self.assertIsNone(result["edge"])
        self.assertIsNone(result["expected_value"])


class ModelFreeExclusionTests(unittest.TestCase):
    """A candidate with no model is excluded BY NAME, not by arithmetic."""

    def _candidate(self, **overrides: object) -> dict[str, object]:
        candidate = {
            "name": "Test Selection",
            "pick": "Test Selection",
            "sport_slug": "mlb",
            "market": "h2h",
            "odds": "+150",
            "score": 4.05,
        }
        candidate.update(overrides)
        return candidate

    def test_model_free_candidate_is_rejected_with_a_truthful_reason(self) -> None:
        sink: list[dict[str, object]] = []
        kept = filter_candidates(
            [self._candidate()], sport="mlb", evaluation_records=[], rejected_sink=sink
        )
        self.assertEqual(kept, [])
        self.assertEqual(len(sink), 1)
        # The reason is the assertion. Before this lane the row was dropped as
        # `edge_below_threshold`, which claimed an edge had been measured when
        # no model had ever run.
        self.assertEqual(sink[0]["_shadow_rejection_reason"], "no_model_probability")

    def test_a_candidate_with_a_model_still_survives(self) -> None:
        # The exclusion must not be a board-emptying change dressed as a fix.
        sink: list[dict[str, object]] = []
        kept = filter_candidates(
            [self._candidate(model_probability=0.62)],
            sport="mlb",
            evaluation_records=[],
            rejected_sink=sink,
        )
        self.assertEqual(len(kept), 1)
        self.assertEqual(sink, [])


if __name__ == "__main__":
    unittest.main()


def test_the_instrument_emits_even_when_nothing_is_rejected(capsys):
    """A zero must be printable, or it cannot be told from "never ran".

    Written after `if rejected:` cost a real measurement: the A1/A2 deploy went
    live, the line did not appear, and silence was consistent with BOTH "the
    rule passed everything" and "the cycle never executed".
    """
    from syndicate.features.shared.recommendation_engine import filter_candidates

    # One candidate that passes cleanly, so `rejected` is empty.
    candidate = {
        "sport": "mlb",
        "market": "totals",
        "model_probability": 0.62,
        "odds": 150,
        "score": 30.0,
        "confidence": 55.0,
    }
    filter_candidates([candidate])
    out = capsys.readouterr().out
    assert "FILTER_CANDIDATES" in out, "instrument stayed silent on an empty rejection set"
    assert "rejected={}" in out, f"expected an explicit empty map, got: {out!r}"
