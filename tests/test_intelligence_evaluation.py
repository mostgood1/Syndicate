from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from syndicate.features.shared.intelligence_evaluation import build_intelligence_evaluation_bundle
from syndicate.features.shared.intelligence_evaluation import adjust_confidence
from syndicate.features.shared.intelligence_evaluation import compute_metrics
from syndicate.features.shared.intelligence_evaluation import record_prediction
from syndicate.features.shared.intelligence_evaluation import record_recommendation
from syndicate.features.shared.intelligence_evaluation import settle_result


class IntelligenceEvaluationTests(unittest.TestCase):
    def test_build_intelligence_evaluation_bundle_includes_prediction_and_recommendations(self) -> None:
        bundle = build_intelligence_evaluation_bundle(
            query={
                "question": "preview the Celtics game tonight",
                "selected_date": "2026-06-08",
                "sport": "nba",
            },
            response={
                "selected_date": "2026-06-08",
                "recommendations": [
                    {
                        "name": "Boston Celtics",
                        "pick": "Over 28.5",
                        "line": 28.5,
                        "model_probability": 0.63,
                    }
                ],
                "analysis_views": {"focus": "nba_matchups"},
            },
            persist=False,
        )

        self.assertEqual(bundle["schema_version"], 1)
        self.assertIn("prediction", bundle)
        self.assertEqual(bundle["prediction"]["prediction_id"].startswith("pred_"), True)
        self.assertEqual(len(bundle["recommendations"]), 1)
        self.assertTrue(bundle["recommendations"][0]["recommendation_id"].startswith("rec_"))
        self.assertEqual(bundle["artifact_metadata"]["sport"], "nba")

    def test_build_intelligence_evaluation_bundle_includes_line_movement_metadata(self) -> None:
        bundle = build_intelligence_evaluation_bundle(
            query={
                "question": "preview the slate",
                "selected_date": "2026-06-11",
                "sport": "nhl",
            },
            response={
                "selected_date": "2026-06-11",
                "recommendations": [
                    {
                        "name": "Home Team Over 6.5",
                        "pick": "Over 6.5",
                        "line": 6.5,
                        "movement": {"delta": 0.0, "trend": "flat", "last_updated": "2026-06-11T12:00:00Z"},
                    },
                    {
                        "name": "Away Team Under 2.5",
                        "pick": "Under 2.5",
                        "line": 2.5,
                        "movement": {"delta": -0.5, "trend": "down", "last_updated": "2026-06-11T14:30:00Z"},
                    },
                ],
            },
            persist=False,
        )

        metadata = bundle["artifact_metadata"]
        self.assertTrue(metadata["has_line_movement"])
        self.assertAlmostEqual(metadata["max_delta_detected"], 0.5)
        self.assertEqual(metadata["last_odds_update_timestamp"], "2026-06-11T14:30:00Z")

    def test_build_intelligence_evaluation_bundle_appends_only_changed_event_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            ledger_path = Path(tmp_dir) / "evaluation_ledger.jsonl"
            base_query = {
                "question": "preview the slate",
                "selected_date": "2026-06-08",
                "sport": "nba",
            }
            base_response = {
                "selected_date": "2026-06-08",
                "recommendations": [
                    {
                        "event_id": "game_1",
                        "name": "Boston Celtics",
                        "pick": "Over 28.5",
                        "line": 28.5,
                        "model_probability": 0.63,
                    },
                    {
                        "event_id": "game_2",
                        "name": "Los Angeles Lakers",
                        "pick": "Under 24.5",
                        "line": 24.5,
                        "model_probability": 0.57,
                    },
                ],
            }

            first_bundle = build_intelligence_evaluation_bundle(
                query=base_query,
                response=base_response,
                ledger_path=ledger_path,
            )
            second_bundle = build_intelligence_evaluation_bundle(
                query=base_query,
                response={
                    **base_response,
                    "recommendations": [
                        base_response["recommendations"][0],
                        {
                            "event_id": "game_2",
                            "name": "Los Angeles Lakers",
                            "pick": "Under 25.5",
                            "line": 25.5,
                            "model_probability": 0.59,
                        },
                    ],
                },
                ledger_path=ledger_path,
            )

            ledger_lines = ledger_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(ledger_lines), 4)
            self.assertEqual(first_bundle["prediction"]["prediction_id"], second_bundle["prediction"]["prediction_id"])
            self.assertEqual(first_bundle["recommendations"][0]["recommendation_id"], second_bundle["recommendations"][0]["recommendation_id"])
            self.assertNotEqual(first_bundle["recommendations"][1]["recommendation_id"], second_bundle["recommendations"][1]["recommendation_id"])

    def test_settle_result_and_compute_metrics(self) -> None:
        prediction = record_prediction(
            query={"question": "analyze Tatum tonight", "selected_date": "2026-06-08"},
            response={"selected_date": "2026-06-08", "recommendations": []},
            persist=False,
        )
        recommendation = record_recommendation(
            prediction_record=prediction,
            recommendation={"name": "Jayson Tatum Over 28.5", "pick": "Over 28.5", "line": 28.5, "model_probability": 0.63},
            persist=False,
        )
        settled = settle_result(
            record=recommendation,
            result="win",
            pnl=0.91,
            closing_line=27.5,
            implied_probability=0.63,
            persist=False,
        )

        metrics = compute_metrics(
            records=[
                settled,
                settle_result(
                    record={**recommendation, "recommendation_id": "rec_other"},
                    result="loss",
                    pnl=-1.0,
                    closing_line=29.5,
                    implied_probability=0.55,
                    persist=False,
                ),
            ]
        )

        self.assertEqual(settled["result"], "win")
        self.assertAlmostEqual(metrics["win_rate"], 0.5)
        self.assertAlmostEqual(metrics["roi"], -0.045, places=3)
        self.assertAlmostEqual(metrics["clv"], 0.0, places=3)
        self.assertAlmostEqual(metrics["calibration"]["mae"], 0.46, places=2)

    def test_adjust_confidence_penalizes_poor_calibration(self) -> None:
        adjusted, profile = adjust_confidence(
            0.72,
            records=[
                {"result": "win", "pnl": 1.0, "stake": 1.0, "implied_probability": 0.72, "artifact_metadata": {"sport": "nba"}},
                {"result": "loss", "pnl": -1.0, "stake": 1.0, "implied_probability": 0.72, "artifact_metadata": {"sport": "nba"}},
                {"result": "loss", "pnl": -1.0, "stake": 1.0, "implied_probability": 0.72, "artifact_metadata": {"sport": "nba"}},
            ],
            sport="nba",
        )

        self.assertLess(adjusted, 0.72)
        self.assertGreater(profile["calibration_error"], 0.0)
        self.assertEqual(profile["sport"], "nba")


if __name__ == "__main__":
    unittest.main()