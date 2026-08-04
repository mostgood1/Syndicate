"""Tests for intelligence_evaluation.build_segmented_reliability_profile --
the Stage 2 hierarchical (sport, market_family, confidence_tier) reliability
surface with empirical-Bayes shrinkage. Not wired into the live ranker
(build_reliability_profile is unchanged and still what filter_candidates/
rank_recommendations consume) -- these tests exercise the new function
directly with synthetic ledger-shaped records."""

from __future__ import annotations

import unittest

from syndicate.features.shared import intelligence_evaluation as ie


def _record(*, sport: str, market: str, confidence: float, result: str, recommendation_id: str, pnl: float | None = None) -> dict:
    return {
        "record_type": "recommendation",
        "recommendation_id": recommendation_id,
        "recommendation": {"sport": sport, "market": market, "confidence": confidence},
        "result": result,
        "implied_probability": confidence,
        "pnl": pnl if pnl is not None else (1.0 if result == "win" else -1.0),
    }


class SegmentedReliabilityProfileTests(unittest.TestCase):
    def test_empty_records_returns_global_with_no_segments(self) -> None:
        profile = ie.build_segmented_reliability_profile(records=[])
        self.assertEqual(profile["segments"], [])
        self.assertEqual(profile["global"]["sample_size"], 0)

    def test_segments_are_keyed_by_sport_market_and_confidence_tier(self) -> None:
        records = [
            _record(sport="mlb", market="moneyline", confidence=0.9, result="win", recommendation_id="1"),
            _record(sport="mlb", market="totals", confidence=0.6, result="loss", recommendation_id="2"),
            _record(sport="wnba", market="moneyline", confidence=0.9, result="loss", recommendation_id="3"),
        ]
        profile = ie.build_segmented_reliability_profile(records=records, shrinkage_k=1.0)
        keys = {(s["sport"], s["market_family"], s["confidence_tier"]) for s in profile["segments"]}
        self.assertIn(("mlb", "moneyline", "elite"), keys)
        self.assertIn(("mlb", "totals", "medium-low"), keys)
        self.assertIn(("wnba", "moneyline", "elite"), keys)

    def test_thin_segment_is_pulled_toward_parent_by_shrinkage(self) -> None:
        # One single MLB moneyline win (own win_rate = 1.0), but the rest of
        # MLB (all other markets) is a coin flip -- with large k, the thin
        # segment's shrunk win_rate should sit well below its own 1.0,
        # pulled toward the sport-wide rate.
        records = [_record(sport="mlb", market="moneyline", confidence=0.9, result="win", recommendation_id="thin-1")]
        for i in range(40):
            records.append(_record(sport="mlb", market="totals", confidence=0.55, result=("win" if i % 2 == 0 else "loss"), recommendation_id=f"bulk-{i}"))

        profile = ie.build_segmented_reliability_profile(records=records, shrinkage_k=20.0)
        thin_segment = next(s for s in profile["segments"] if s["market_family"] == "moneyline")
        self.assertEqual(thin_segment["win_rate"], 1.0)  # own raw rate
        self.assertLess(thin_segment["shrunk_win_rate"], 0.8)  # pulled well down from 1.0
        self.assertGreater(thin_segment["shrunk_win_rate"], 0.5)  # but still above the 0.5 parent rate

    def test_large_segment_stays_close_to_its_own_rate(self) -> None:
        records = []
        for i in range(500):
            records.append(_record(sport="mlb", market="moneyline", confidence=0.9, result=("win" if i < 400 else "loss"), recommendation_id=f"big-{i}"))
        profile = ie.build_segmented_reliability_profile(records=records, shrinkage_k=20.0)
        segment = next(s for s in profile["segments"] if s["market_family"] == "moneyline")
        self.assertAlmostEqual(segment["win_rate"], 0.8, places=2)
        self.assertAlmostEqual(segment["shrunk_win_rate"], 0.8, delta=0.02)

    def test_sport_filter_scopes_output(self) -> None:
        records = [
            _record(sport="mlb", market="moneyline", confidence=0.9, result="win", recommendation_id="1"),
            _record(sport="wnba", market="moneyline", confidence=0.9, result="loss", recommendation_id="2"),
        ]
        profile = ie.build_segmented_reliability_profile(records=records, sport="mlb")
        sports = {s["sport"] for s in profile["segments"]}
        self.assertEqual(sports, {"mlb"})

    def test_calibration_metrics_present_when_implied_probability_available(self) -> None:
        records = [
            _record(sport="mlb", market="moneyline", confidence=0.9, result="win", recommendation_id="1"),
            _record(sport="mlb", market="moneyline", confidence=0.9, result="loss", recommendation_id="2"),
        ]
        profile = ie.build_segmented_reliability_profile(records=records)
        segment = profile["segments"][0]
        self.assertIsNotNone(segment["brier_score"])
        self.assertIsNotNone(segment["shrunk_brier_score"])

    def test_pending_records_do_not_count_as_settled(self) -> None:
        records = [
            {"record_type": "recommendation", "recommendation_id": "1", "recommendation": {"sport": "mlb", "market": "moneyline", "confidence": 0.9}, "result": "pending"},
        ]
        profile = ie.build_segmented_reliability_profile(records=records)
        self.assertEqual(profile["global"]["sample_size"], 0)


if __name__ == "__main__":
    unittest.main()
