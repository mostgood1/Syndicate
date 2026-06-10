from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pipeline.performance_aggregator import build_performance_summary


class PerformanceAggregatorTests(unittest.TestCase):
    def test_build_performance_summary_aggregates_evaluation_ledger(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            evaluation_path = root / "reports" / "intelligence" / "evaluation_ledger.jsonl"
            output_path = root / "reports" / "performance_summary.json"
            compat_path = root / "reports" / "intelligence" / "performance_summary.json"
            evaluation_path.parent.mkdir(parents=True, exist_ok=True)
            evaluation_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "prediction_id": "pred-1",
                                "recommendation_id": "rec-1",
                                "result": "win",
                                "pnl": 0.9,
                                "stake": 1.0,
                                "artifact_metadata": {"sport": "nba"},
                                "recommendation": {"market": "points", "implied_probability": 0.55},
                            }
                        ),
                        json.dumps(
                            {
                                "prediction_id": "pred-2",
                                "recommendation_id": "rec-2",
                                "result": "loss",
                                "pnl": -1.0,
                                "stake": 1.0,
                                "artifact_metadata": {"sport": "nba"},
                                "recommendation": {"market": "points", "implied_probability": 0.65},
                            }
                        ),
                        json.dumps(
                            {
                                "prediction_id": "pred-3",
                                "recommendation_id": "rec-3",
                                "result": "win",
                                "pnl": 1.2,
                                "stake": 1.0,
                                "artifact_metadata": {"sport": "mlb"},
                                "recommendation": {"market": "moneyline", "implied_probability": 0.72},
                            }
                        ),
                        json.dumps(
                            {
                                "prediction_id": "pred-4",
                                "recommendation_id": "rec-4",
                                "result": "push",
                                "pnl": 0.0,
                                "stake": 1.0,
                                "artifact_metadata": {"sport": "mlb"},
                                "recommendation": {"market": "moneyline", "implied_probability": 0.62},
                            }
                        ),
                    ]
                ),
                encoding="utf-8",
            )

            summary = build_performance_summary(
                ledger_path=evaluation_path,
                output_path=output_path,
                compatibility_output_path=compat_path,
            )

            self.assertTrue(output_path.exists())
            self.assertTrue(compat_path.exists())

        self.assertEqual(summary["overall"]["total_bets"], 4)
        self.assertEqual(summary["by_sport"]["nba"]["total_bets"], 2)
        self.assertEqual(summary["by_market"]["points"]["total_bets"], 2)
        self.assertEqual(summary["by_probability_bucket"][0]["bucket"], "0.50-0.60")
        self.assertAlmostEqual(summary["by_probability_bucket"][0]["predicted_probability"], 0.55, places=2)
        self.assertAlmostEqual(summary["by_probability_bucket"][0]["actual_win_rate"], 1.0, places=2)

    def test_build_performance_summary_can_fallback_to_prediction_ledger(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            prediction_path = root / "data" / "prediction_ledger.json"
            output_path = root / "reports" / "performance_summary.json"
            prediction_path.parent.mkdir(parents=True, exist_ok=True)
            prediction_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "predictions": [
                            {
                                "id": "pred-1",
                                "sport": "nba",
                                "market": "rebounds",
                                "selection": "Over 8.5",
                                "confidence": 0.63,
                                "stake": 1.0,
                                "features_snapshot": {"selected_date": "2026-06-10"},
                            }
                        ],
                        "results": [
                            {
                                "prediction_id": "pred-1",
                                "outcome": "win",
                                "pnl": 0.88,
                                "closing_line": 8.5,
                                "implied_probability": 0.57,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            summary = build_performance_summary(
                ledger_path=root / "reports" / "intelligence" / "evaluation_ledger.jsonl",
                prediction_ledger_path=prediction_path,
                output_path=output_path,
                compatibility_output_path=root / "reports" / "intelligence" / "performance_summary.json",
            )

            self.assertTrue(output_path.exists())

        self.assertTrue(summary["prediction_ledger"]["used_as_fallback"])
        self.assertEqual(summary["overall"]["total_bets"], 1)
        self.assertEqual(summary["by_sport"]["nba"]["total_bets"], 1)
        self.assertEqual(summary["by_market"]["rebounds"]["total_bets"], 1)


if __name__ == "__main__":
    unittest.main()