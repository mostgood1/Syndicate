from __future__ import annotations

import unittest
import json
from unittest.mock import patch

from flask import Flask

from pipeline.intelligence_state import IntelligenceSnapshot
from pipeline.intelligence_state import IntelligenceStateService
from syndicate.blueprints.intelligence import intelligence_bp
from syndicate.blueprints.intelligence import intelligence_query_api


class IntelligenceStateTests(unittest.TestCase):
    def test_read_latest_response_does_not_enqueue_work(self) -> None:
        service = IntelligenceStateService()
        snapshot = IntelligenceSnapshot(
            key="abc",
            payload={"question": "top edges today"},
            response={"ok": True, "response": {"recommendations": []}},
            computed_at="2026-06-10T17:31:00Z",
            source_fingerprint="fingerprint-1",
        )
        service._snapshots["abc"] = snapshot
        service._latest_key = "abc"

        with patch.object(service, "_enqueue_locked") as mocked_enqueue:
            response = service.read_latest_response({"question": "top edges today"})

        self.assertEqual(response, {"ok": True, "response": {"recommendations": []}})
        mocked_enqueue.assert_not_called()

    def test_query_endpoint_reads_cached_state_only(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(intelligence_bp)

        cached_response = {
            "ok": True,
            "top_opportunities": [],
            "by_sport": {},
            "analysis": {"recommendations": [], "picks": [], "top_live_opportunities": [], "portfolio": {}, "parlays": []},
        }

        with app.test_request_context(
            "/api/intelligence/query",
            method="POST",
            json={"question": "top edges today", "force_refresh": True},
        ):
            with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state_response", return_value=dict(cached_response)) as mocked_read:
                with patch("syndicate.blueprints.intelligence.queue_intelligence_state_refresh") as mocked_queue:
                    response = intelligence_query_api()

        payload = response.get_json()
        self.assertIsNotNone(payload)
        self.assertIn("version", payload)
        self.assertIn("timestamp", payload)
        self.assertIn("response", payload)
        mocked_read.assert_called_once()
        mocked_queue.assert_not_called()
        self.assertEqual(payload["response"]["analysis"]["recommendations"], [])

    def test_compute_response_reuses_source_cache_until_state_changes(self) -> None:
        service = IntelligenceStateService()
        payload = {"question": "top edges today", "date": "2026-06-10", "limit": 5}

        base_status = {
            "selected_date": "2026-06-10",
            "tracked_summary": {"tracked_ok": 1, "tracked_total": 1},
            "advanced_summary": {"tracked_ok": 1, "tracked_total": 1},
            "readiness_gate": {"ok": True},
            "sports": [
                {
                    "slug": "mlb",
                    "name": "MLB",
                    "context_label": "2026-06-10",
                    "data_health": "ready",
                    "active_today": True,
                    "tracked_ready": True,
                    "advanced_ready": True,
                    "advanced_gate": {"ready": True},
                    "data_warnings": [],
                    "artifacts": [{"label": "Live lens report", "path": "reports/intelligence/example.json", "exists": True, "tracked": True, "inside_repo": True}],
                    "advanced_inputs": [],
                }
            ],
        }
        changed_status = {
            **base_status,
            "sports": [
                {
                    **base_status["sports"][0],
                    "context_label": "2026-06-11",
                }
            ],
        }

        with patch("pipeline.intelligence_state.build_intelligence_status", side_effect=[base_status, base_status, changed_status]):
            with patch("pipeline.intelligence_state.collect_all_recommendations", return_value=[{"name": "Play 1", "sport": "MLB", "market": "Hits", "score": 91.0}]) as mocked_collect:
                with patch("pipeline.intelligence_state.rank_global_recommendations", return_value=[{"name": "Play 1", "sport": "MLB", "market": "Hits", "score": 91.0}]) as mocked_rank:
                    with patch("pipeline.intelligence_state.run_routed_intelligence_pipeline", return_value={"headline": "Test", "recommendations": []}) as mocked_pipeline:
                        with patch("pipeline.intelligence_state.logger.info") as mocked_logger:
                            first = service._compute_response(payload)
                            second = service._compute_response(payload)
                            third = service._compute_response(payload)

        self.assertEqual(first, second)
        self.assertEqual(first["top_opportunities"], third["top_opportunities"])
        self.assertIn("candidate_pool", first)
        self.assertEqual(first["candidate_pool"]["candidate_count"], 1)
        self.assertEqual(first["candidate_pool"]["candidates"][0]["candidate_id"], second["candidate_pool"]["candidates"][0]["candidate_id"])
        self.assertEqual(first["candidate_pool"]["candidates"][0]["candidate_id"], third["candidate_pool"]["candidates"][0]["candidate_id"])
        logged_stages = []
        for call in mocked_logger.call_args_list:
            try:
                payload_log = json.loads(call.args[0])
            except Exception:
                continue
            if isinstance(payload_log, dict) and payload_log.get("stage"):
                logged_stages.append(payload_log["stage"])
        self.assertIn("data_ingestion", logged_stages)
        self.assertIn("simulation_aggregation", logged_stages)
        self.assertIn("candidate_building", logged_stages)
        self.assertIn("candidate_scoring", logged_stages)
        self.assertIn("response_building", logged_stages)
        self.assertIn("request_total", logged_stages)
        self.assertEqual(mocked_collect.call_count, 2)
        self.assertEqual(mocked_rank.call_count, 2)
        self.assertEqual(mocked_pipeline.call_count, 2)
