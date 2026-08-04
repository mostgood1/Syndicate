"""Tests for intelligence_evaluation.build_accuracy_summary -- the Stage 5
combined accuracy view (metrics + segmented reliability + day-bucketed
drift), verified via its CLI wrapper's importability and directly."""

from __future__ import annotations

import unittest

from syndicate.features.shared import intelligence_evaluation as ie


def _record(*, date: str, sport: str, result: str, recommendation_id: str, confidence: float = 0.6) -> dict:
    return {
        "record_type": "recommendation",
        "recommendation_id": recommendation_id,
        "query": {"selected_date": date, "sport": sport},
        "recommendation": {"sport": sport, "market": "moneyline", "confidence": confidence},
        "result": result,
        "implied_probability": confidence,
        "pnl": 1.0 if result == "win" else -1.0,
    }


class BuildAccuracySummaryTests(unittest.TestCase):
    def test_empty_records_returns_a_well_formed_zero_summary(self) -> None:
        summary = ie.build_accuracy_summary(records=[], sport="mlb")
        self.assertEqual(summary["sport"], "mlb")
        self.assertEqual(summary["settled_count"], 0)
        self.assertEqual(summary["drift"]["win_rate"]["reason"], "insufficient_data")
        self.assertIn("segmented_reliability", summary)

    def test_buckets_records_by_date_and_scopes_metrics_to_sport(self) -> None:
        records = [
            _record(date="2026-08-01", sport="mlb", result="win", recommendation_id="1"),
            _record(date="2026-08-01", sport="wnba", result="loss", recommendation_id="2"),
        ]
        summary = ie.build_accuracy_summary(records=records, sport="mlb")
        self.assertEqual(summary["metrics"]["settled_count"], 1)
        self.assertEqual(summary["metrics"]["win_rate"], 1.0)

    def test_detects_a_real_drop_in_win_rate_between_baseline_and_recent_windows(self) -> None:
        records = []
        # Baseline: 14 days, mostly wins (~90%).
        for day in range(1, 15):
            date = f"2026-07-{day:02d}"
            for i in range(10):
                result = "win" if i < 9 else "loss"
                records.append(_record(date=date, sport="mlb", result=result, recommendation_id=f"base-{day}-{i}"))
        # Recent: 7 days, mostly losses (~20% win rate) -- a real skill drop.
        for day in range(15, 22):
            date = f"2026-07-{day:02d}"
            for i in range(10):
                result = "win" if i < 2 else "loss"
                records.append(_record(date=date, sport="mlb", result=result, recommendation_id=f"recent-{day}-{i}"))

        summary = ie.build_accuracy_summary(records=records, sport="mlb", recent_days=7, baseline_days=14)
        self.assertTrue(summary["drift"]["win_rate"]["flagged"])
        self.assertLess(summary["drift"]["win_rate"]["recent_mean"], summary["drift"]["win_rate"]["baseline_mean"])

    def test_stable_win_rate_across_windows_does_not_flag(self) -> None:
        records = []
        for day in range(1, 22):
            date = f"2026-07-{day:02d}"
            for i in range(10):
                result = "win" if i < 7 else "loss"  # steady 70% every day
                records.append(_record(date=date, sport="mlb", result=result, recommendation_id=f"{day}-{i}"))
        summary = ie.build_accuracy_summary(records=records, sport="mlb", recent_days=7, baseline_days=14)
        self.assertFalse(summary["drift"]["win_rate"]["flagged"])


if __name__ == "__main__":
    unittest.main()
