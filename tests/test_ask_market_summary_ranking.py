"""Ask's market-summary "top opportunities" must actually be the top ones.

Confirmed live 2026-08-03: the summary returned 4 negative-edge rows with
the only positive one (+16.9%) ranked LAST, under a header claiming "Best
edge 14.3%". The builder sliced `recommendations[:5]` with no sort, so the
list was whatever order the payload happened to arrive in.
"""

from __future__ import annotations

import unittest

from syndicate.blueprints.ask_the_syndicate_adapter import _market_summary_schema


def _rec(selection: str, *, edge: float | None = None, adjusted_score: float | None = None) -> dict:
    row: dict = {"selection": selection, "market": "Moneyline"}
    if edge is not None:
        row["edge"] = edge
    if adjusted_score is not None:
        row["adjusted_score"] = adjusted_score
    return row


class MarketSummaryRankingTests(unittest.TestCase):
    def test_the_positive_edge_bet_is_not_buried_last(self) -> None:
        # The exact shape observed in production.
        result = {
            "recommendations": [
                _rec("bad-1", edge=-0.3016),
                _rec("bad-2", edge=-0.0572),
                _rec("bad-3", edge=-0.1536),
                _rec("bad-4", edge=-0.0954),
                _rec("the-good-one", edge=0.1694),
            ]
        }
        schema = _market_summary_schema(result, question="summarize the board")
        self.assertEqual(schema["top_opportunities"][0]["selection"], "the-good-one")

    def test_adjusted_score_outranks_raw_edge(self) -> None:
        # adjusted_score is the board's own ranker output; a high raw edge
        # on an unreliable market should not outrank it.
        result = {
            "recommendations": [
                _rec("high-edge-low-score", edge=0.40, adjusted_score=10.0),
                _rec("lower-edge-high-score", edge=0.05, adjusted_score=90.0),
            ]
        }
        schema = _market_summary_schema(result, question="summarize the board")
        self.assertEqual(schema["top_opportunities"][0]["selection"], "lower-edge-high-score")

    def test_unscored_rows_sort_below_negative_scored_ones(self) -> None:
        # An unscored row must not land mid-pack as if it were neutral.
        result = {
            "recommendations": [
                _rec("unscored"),
                _rec("negative-but-scored", adjusted_score=-5.0),
            ]
        }
        schema = _market_summary_schema(result, question="summarize the board")
        self.assertEqual(schema["top_opportunities"][0]["selection"], "negative-but-scored")

    def test_adjusted_score_is_surfaced_so_ordering_is_inspectable(self) -> None:
        result = {"recommendations": [_rec("a", edge=0.1, adjusted_score=42.5)]}
        schema = _market_summary_schema(result, question="summarize the board")
        self.assertEqual(schema["top_opportunities"][0]["adjusted_score"], 42.5)

    def test_still_caps_at_five(self) -> None:
        result = {"recommendations": [_rec(f"r{i}", edge=i / 100.0) for i in range(12)]}
        schema = _market_summary_schema(result, question="summarize the board")
        self.assertEqual(len(schema["top_opportunities"]), 5)
        # And the cap keeps the BEST five, not the first five.
        self.assertEqual(schema["top_opportunities"][0]["selection"], "r11")

    def test_empty_recommendations_do_not_raise(self) -> None:
        schema = _market_summary_schema({"recommendations": []}, question="summarize the board")
        self.assertEqual(schema["top_opportunities"], [])


if __name__ == "__main__":
    unittest.main()
