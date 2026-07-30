from __future__ import annotations

import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import syndicate.features.shared.intelligence_evaluation as intelligence_evaluation
from syndicate.app import create_app
from syndicate.features.shared.intelligence_evaluation import record_prediction
from syndicate.features.shared.intelligence_evaluation import record_recommendation
from syndicate.features.shared.intelligence_evaluation import settle_result


class OpportunityBoardRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        app = create_app()
        app.testing = True
        self.client = app.test_client()

    def test_page_renders(self) -> None:
        response = self.client.get("/intelligence/opportunity-board")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Opportunity Board", response.data)

    def test_api_against_empty_ledger_is_graceful(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            ledger_path = Path(tmp_dir) / "evaluation_ledger.jsonl"
            with patch.object(intelligence_evaluation, "DEFAULT_LEDGER_PATH", ledger_path):
                response = self.client.get(
                    "/intelligence/api/opportunity-board?since=2026-01-01&until=2026-01-31"
                )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["summary"]["publish_count"], 0)
        self.assertEqual(payload["summary"]["settled_count"], 0)
        self.assertEqual(payload["by_sport"], [])

    def test_api_reports_windowed_and_sport_filtered_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            ledger_path = Path(tmp_dir) / "evaluation_ledger.jsonl"
            with patch.object(intelligence_evaluation, "DEFAULT_LEDGER_PATH", ledger_path):
                prediction = record_prediction(
                    query={"question": "test", "selected_date": "2026-06-05", "sport": "mlb"},
                    response={"selected_date": "2026-06-05", "recommendations": []},
                    persist=True,
                )
                recommendation = record_recommendation(
                    prediction_record=prediction,
                    recommendation={"name": "pick", "pick": "Over", "line": 1.5, "sport": "mlb", "model_probability": 0.6},
                    persist=True,
                )
                settle_result(
                    record=recommendation,
                    result="win",
                    pnl=0.9,
                    closing_line=1.5,
                    persist=True,
                )

                other_prediction = record_prediction(
                    query={"question": "test", "selected_date": "2026-06-05", "sport": "wnba"},
                    response={"selected_date": "2026-06-05", "recommendations": []},
                    persist=True,
                )
                record_recommendation(
                    prediction_record=other_prediction,
                    recommendation={"name": "pick2", "pick": "Under", "line": 2.5, "sport": "wnba"},
                    persist=True,
                )

                response = self.client.get(
                    "/intelligence/api/opportunity-board?since=2026-06-01&until=2026-06-10&sport=mlb"
                )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["window"]["sport"], "mlb")
        self.assertEqual(payload["summary"]["settled_count"], 1)
        self.assertEqual(payload["summary"]["win_rate"], 1.0)
        self.assertEqual({row["bucket"] for row in payload["by_sport"]}, {"mlb"})


if __name__ == "__main__":
    unittest.main()
