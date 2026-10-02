"""`build_recommendation_output` must survive a candidate that ranking filters out.

Measured 2026-10-02 on the fleet: 36 WNBA odds runs failed with
`IndexError: list index out of range` because `rank_recommendations` returned
`[]` for a row rejected as `no_model_probability`, and `[0]` was taken anyway.
"""

from __future__ import annotations

import unittest
from unittest import mock

from syndicate.features.shared import recommendation_engine as engine

FILTERED_ROW = {
    "sport": "wnba",
    "date": "2026-10-02",
    "market": "player_points",
    "player": "Test Player",
    "side": "over",
    "line": 18.5,
    "price": -110,
    # no model probability of any kind -> FILTER_CANDIDATES rejects it
}


class BuildRecommendationOutputTests(unittest.TestCase):
    def test_empty_ranking_returns_candidate_unchanged(self) -> None:
        with mock.patch.object(engine, "rank_recommendations", return_value=[]) as rank:
            out = engine.build_recommendation_output(FILTERED_ROW, sport="wnba")
        self.assertEqual(out, FILTERED_ROW)
        self.assertIsNot(out, FILTERED_ROW)  # a copy: the caller may mutate it
        self.assertEqual(rank.call_args.kwargs["limit"], 1)

    def test_ranked_candidate_is_still_returned(self) -> None:
        ranked = {**FILTERED_ROW, "adjusted_score": 0.7}
        with mock.patch.object(engine, "rank_recommendations", return_value=[ranked]):
            self.assertIs(engine.build_recommendation_output(FILTERED_ROW, sport="wnba"), ranked)

    def test_real_ranking_of_a_no_probability_row_does_not_raise(self) -> None:
        """Reachability: the real filter path that produced the fleet failures."""
        with mock.patch.object(engine, "_load_records_from_ledger", return_value=[], create=True):
            ranked = engine.rank_recommendations([dict(FILTERED_ROW)], sport="wnba", evaluation_records=[], limit=1)
            out = engine.build_recommendation_output(FILTERED_ROW, sport="wnba", evaluation_records=[])
        self.assertEqual(ranked, [])  # precondition: this row IS filtered, so the old [0] would raise
        self.assertEqual(out, FILTERED_ROW)


if __name__ == "__main__":
    unittest.main()
