from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import time

from flask import Flask

import pipeline.intelligence_state as intelligence_state_module
from syndicate.features.shared import refresh_state_store
from pipeline.intelligence_state import IntelligenceSnapshot
from pipeline.intelligence_state import IntelligenceStateService
from pipeline.intelligence_state import _payload_key
from syndicate.blueprints.intelligence import intelligence_bp
from syndicate.blueprints.intelligence import intelligence_status_api
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

    def test_read_latest_response_syncs_shared_backend_state(self) -> None:
        service = IntelligenceStateService()
        cached_response = {"ok": True, "response": {"recommendations": [{"name": "Play 1"}]}}

        with tempfile.TemporaryDirectory() as tmp_dir, patch.dict(
            os.environ,
            {
                "SYNDICATE_REFRESH_STATE_BACKEND": "keyvalue",
                "SYNDICATE_REFRESH_STATE_URL": "redis://example",
                "SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports"),
            },
            clear=False,
        ):
            fake_state_path = Path(tmp_dir) / "reports" / "intelligence" / "query_state_cache.json"
            with patch.object(intelligence_state_module, "STATE_PATH", fake_state_path):
                with patch("syndicate.features.shared.refresh_state_store._get_keyvalue_client") as mocked_client_factory:
                    fake_client = type(
                        "FakeClient",
                        (),
                        {
                            "store": {},
                            "get": lambda self, key: self.store.get(key),
                            "set": lambda self, key, value: self.store.__setitem__(key, str(value)) or True,
                            "exists": lambda self, key: 1 if key in self.store else 0,
                        },
                    )()
                    mocked_client_factory.return_value = fake_client
                    refresh_state_store.write_json_file(
                        fake_state_path,
                        {
                            "latest_key": "abc",
                            "snapshots": {
                                "abc": {
                                    "key": "abc",
                                    "payload": {"question": "top edges today"},
                                    "response": cached_response,
                                    "computed_at": "2026-06-10T17:31:00Z",
                                    "source_fingerprint": "fingerprint-1",
                                }
                            },
                        },
                    )

                    response = service.read_latest_response({"question": "top edges today"})

        self.assertEqual(response, cached_response)

    def test_query_endpoint_reads_cached_state_only(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(intelligence_bp)

        cached_response = {
            "ok": True,
            "last_updated": "2026-06-11T16:00:00Z",
            "candidate_pool": {"candidates": [{"name": "Play 1"}, {"name": "Play 2"}]},
            "top_opportunities": [],
            "by_sport": {},
            "analysis": {"recommendations": [], "picks": [], "top_live_opportunities": [], "portfolio": {}, "parlays": []},
        }

        with app.test_request_context(
            "/api/intelligence/query",
            method="POST",
            json={"question": "top edges today", "force_refresh": True},
        ):
            with patch("builtins.print") as mocked_print:
                with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state_response", return_value=dict(cached_response)) as mocked_read:
                    with patch("syndicate.blueprints.intelligence.queue_intelligence_state_refresh") as mocked_queue:
                        response = intelligence_query_api()

        payload = response.get_json()
        self.assertIsNotNone(payload)
        self.assertIn("version", payload)
        self.assertIn("timestamp", payload)
        self.assertIn("response", payload)
        self.assertEqual(payload["state_last_updated"], "2026-06-11T16:00:00Z")
        self.assertEqual(payload["candidate_count"], 2)
        self.assertEqual(payload["debug_source"], "worker")
        self.assertEqual(response.headers.get("Cache-Control"), "no-cache, no-store, must-revalidate")
        self.assertEqual(response.headers.get("Pragma"), "no-cache")
        self.assertEqual(response.headers.get("Expires"), "0")
        mocked_read.assert_called_once()
        mocked_queue.assert_not_called()
        mocked_print.assert_called_once()
        self.assertEqual(mocked_print.call_args.args[0], "[API READ]")
        self.assertEqual(mocked_print.call_args.args[1]["candidate_count"], 0)
        self.assertEqual(payload["response"]["analysis"]["recommendations"], [])

    def test_status_endpoint_falls_back_to_cached_state_when_live_build_fails(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(intelligence_bp)

        with app.test_request_context("/api/intelligence/status?date=2026-06-10", method="GET"):
            with patch("builtins.print") as mocked_print:
                with patch("syndicate.blueprints.intelligence.build_intelligence_status", side_effect=RuntimeError("boom")):
                    response = intelligence_status_api()

        if isinstance(response, tuple):
            response_obj, status_code = response
        else:
            response_obj, status_code = response, response.status_code

        payload = response_obj.get_json()
        self.assertIsNotNone(payload)
        self.assertEqual(status_code, 500)
        self.assertEqual(payload["error"], "boom")
        self.assertEqual(response_obj.headers.get("Cache-Control"), "no-cache, no-store, must-revalidate")
        self.assertEqual(response_obj.headers.get("Pragma"), "no-cache")
        self.assertEqual(response_obj.headers.get("Expires"), "0")
        mocked_print.assert_called_once()
        self.assertEqual(mocked_print.call_args.args[0], "[API ERROR]")
        self.assertEqual(mocked_print.call_args.args[1], "boom")

    def test_status_endpoint_includes_state_debug_fields(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(intelligence_bp)

        state_response = {
            "ok": True,
            "last_updated": "2026-06-11T16:05:00Z",
            "candidate_pool": {"candidates": [{"name": "Play 1"}]},
        }

        with app.test_request_context("/api/intelligence/status?date=2026-06-10", method="GET"):
            with patch("syndicate.blueprints.intelligence.build_intelligence_status", return_value={"ok": True, "threadAlive": True}):
                with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state_response", return_value=dict(state_response)):
                    response = intelligence_status_api()

        payload = response.get_json()
        self.assertIsNotNone(payload)
        self.assertEqual(payload["state_last_updated"], "2026-06-11T16:05:00Z")
        self.assertEqual(payload["candidate_count"], 1)
        self.assertEqual(payload["debug_source"], "worker")
        self.assertEqual(response.headers.get("Cache-Control"), "no-cache, no-store, must-revalidate")
        self.assertEqual(response.headers.get("Pragma"), "no-cache")
        self.assertEqual(response.headers.get("Expires"), "0")

    def test_status_exposes_freshness_sla_fields(self) -> None:
        service = IntelligenceStateService()
        service._interval_seconds = 30
        current_timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        snapshot = IntelligenceSnapshot(
            key="abc",
            payload={"question": "top edges today"},
            response={"ok": True},
            computed_at=current_timestamp,
            source_fingerprint="fingerprint-1",
        )
        service._snapshots[snapshot.key] = snapshot
        service._latest_key = snapshot.key

        with patch.object(service, "_sync_persisted_state_locked") as mocked_sync:
            status = service.status()

        mocked_sync.assert_called_once()
        self.assertIn("latestSnapshotAgeSeconds", status)
        self.assertIn("freshnessSlaSeconds", status)
        self.assertIn("freshnessStatus", status)
        self.assertIn("isFresh", status)
        self.assertEqual(status["freshnessSlaSeconds"], 30)
        self.assertEqual(status["freshnessStatus"], "fresh")
        self.assertTrue(status["isFresh"])

    def test_status_page_redirects_to_api_status(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(intelligence_bp)

        with app.test_request_context("/intelligence/status?date=2026-06-10", method="GET"):
            response = app.view_functions["syndicate_intelligence.intelligence_status_page"]()

        self.assertEqual(response.status_code, 302)
        self.assertIn("/api/intelligence/status?date=2026-06-10", response.location)

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

        with tempfile.TemporaryDirectory() as tmp_dir:
            reports_root = Path(tmp_dir) / "reports"
            manifests_root = reports_root / "manifests"
            manifests_root.mkdir(parents=True, exist_ok=True)
            manifest_path = manifests_root / "mlb.json"
            manifest_path.write_text(
                '{"sport":"mlb","last_updated":"2026-06-10T10:00:00Z","artifact_paths":["reports/intelligence/example.json"],"status":"complete"}',
                encoding="utf-8",
            )

            with patch("pipeline.intelligence_state.reports_root", return_value=reports_root):
                with patch("pipeline.intelligence_state.build_intelligence_status", return_value=base_status):
                    with patch("pipeline.intelligence_state.collect_all_recommendations", return_value=[{"name": "Play 1", "sport": "MLB", "market": "Hits", "score": 91.0}]) as mocked_collect:
                        with patch("pipeline.intelligence_state.rank_global_recommendations", return_value=[{"name": "Play 1", "sport": "MLB", "market": "Hits", "score": 91.0}]) as mocked_rank:
                            with patch("pipeline.intelligence_state.run_routed_intelligence_pipeline", return_value={"headline": "Test", "recommendations": []}) as mocked_pipeline:
                                with patch("pipeline.intelligence_state.logger.info") as mocked_logger:
                                    first = service._compute_response(payload)
                                    second = service._compute_response(payload)
                                    manifest_path.write_text(
                                        '{"sport":"mlb","last_updated":"2026-06-10T10:05:00Z","artifact_paths":["reports/intelligence/example.json","reports/intelligence/extra.json"],"status":"complete"}',
                                        encoding="utf-8",
                                    )
                                    third = service._compute_response(payload)

        self.assertEqual(first, second)
        self.assertEqual(first["top_opportunities"], third["top_opportunities"])
        self.assertIn("candidate_pool", first)
        self.assertEqual(first["candidate_pool"]["candidate_count"], 1)
        self.assertEqual(set(first["candidate_pool"]["candidate_pools"].keys()), {"mlb"})
        self.assertEqual(first["candidate_pool"]["global_pool"], first["candidate_pool"]["candidates"])
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

    def test_background_refresh_recomputes_when_snapshot_fingerprint_matches(self) -> None:
        service = IntelligenceStateService()
        service._interval_seconds = 0
        payload = {"question": "top edges today", "date": "2026-06-10", "limit": 5}
        normalized = service._normalize_payload(payload)
        snapshot_key = _payload_key(normalized)

        service._pending_keys[snapshot_key] = normalized
        service._snapshots[snapshot_key] = IntelligenceSnapshot(
            key=snapshot_key,
            payload=dict(normalized),
            response={"ok": True},
            computed_at="2026-06-10T00:00:00Z",
            source_fingerprint="fingerprint-1",
        )
        service._latest_key = snapshot_key

        calls = {"count": 0}

        def fake_source_fingerprint(selected_date: str | None) -> str:
            return "fingerprint-1"

        def fake_build_candidate_pool(selected_date: str | None, source_fingerprint: str) -> dict[str, object]:
            return {"candidates": [{"name": "Play 1"}, {"name": "Play 2"}]}

        def fake_compute_response(request_payload: dict[str, object]) -> dict[str, object]:
            calls["count"] += 1
            service._stop.set()
            return {"ok": True}

        service._source_state_fingerprint = fake_source_fingerprint
        service._build_candidate_pool = fake_build_candidate_pool
        service._compute_response = fake_compute_response
        service._persist_locked = lambda: None

        with patch("builtins.print") as mocked_print:
            service._background_loop()

        self.assertEqual(calls["count"], 1)
        mocked_print.assert_called_once()
        printed_args = mocked_print.call_args.args
        self.assertEqual(printed_args[0], "[WORKER WRITE]")
        self.assertEqual(printed_args[1]["candidate_count"], 2)

    def test_build_candidate_pool_skips_sports_without_manifests(self) -> None:
        service = IntelligenceStateService()
        status = {
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
                    "artifacts": [],
                    "advanced_inputs": [],
                },
                {
                    "slug": "nba",
                    "name": "NBA",
                    "context_label": "2026-06-10",
                    "data_health": "ready",
                    "active_today": True,
                    "tracked_ready": True,
                    "advanced_ready": True,
                    "advanced_gate": {"ready": True},
                    "data_warnings": [],
                    "artifacts": [],
                    "advanced_inputs": [],
                },
            ],
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            reports_root = Path(tmp_dir) / "reports"
            manifests_root = reports_root / "manifests"
            manifests_root.mkdir(parents=True, exist_ok=True)
            (manifests_root / "mlb.json").write_text(
                '{"sport":"mlb","last_updated":"2026-06-10T10:00:00Z","artifact_paths":["reports/intelligence/mlb.json"],"status":"complete"}',
                encoding="utf-8",
            )

            with patch("pipeline.intelligence_state.reports_root", return_value=reports_root):
                with patch("pipeline.intelligence_state.build_intelligence_status", return_value=status):
                    with patch(
                        "pipeline.intelligence_state.collect_all_recommendations",
                        return_value=[
                            {"name": "MLB Play", "sport": "MLB", "market": "Hits", "score": 91.0},
                            {"name": "NBA Play", "sport": "NBA", "market": "Points", "score": 89.0},
                        ],
                    ):
                        pool = service._build_candidate_pool("2026-06-10", "fingerprint-1")

        self.assertEqual(pool["candidate_count"], 1)
        self.assertEqual(set(pool["candidate_pools"].keys()), {"mlb"})
        self.assertEqual(pool["candidate_pools"]["mlb"]["last_updated"], "2026-06-10T10:00:00Z")
        self.assertEqual(pool["global_pool"][0]["name"], "MLB Play")
        self.assertEqual(pool["candidates"], pool["global_pool"])
