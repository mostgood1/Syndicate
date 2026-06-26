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
from syndicate.app import create_app
import syndicate.blueprints.intelligence as intelligence_module
from syndicate.blueprints.intelligence import intelligence_bp
from syndicate.blueprints.intelligence import intelligence_portfolio_event_api
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

    def test_read_latest_response_does_not_fall_back_to_other_dates(self) -> None:
        service = IntelligenceStateService()
        snapshot = IntelligenceSnapshot(
            key=_payload_key({"question": "top edges today", "date": "2026-06-15"}),
            payload={"question": "top edges today", "date": "2026-06-15"},
            response={"ok": True, "response": {"selected_date": "2026-06-15", "recommendations": []}},
            computed_at="2026-06-10T17:31:00Z",
            source_fingerprint="fingerprint-1",
        )
        service._snapshots[snapshot.key] = snapshot
        service._latest_key = snapshot.key

        response = service.read_latest_response({"question": "top edges today", "date": "2026-06-17"})

        self.assertIsNone(response)

    def test_board_snapshot_reader_skips_mismatched_dates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir, patch.dict(
            os.environ,
            {
                "SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports"),
            },
            clear=False,
        ):
            fake_snapshot_path = Path(tmp_dir) / "reports" / "intelligence" / "board_snapshot.json"
            with patch.object(intelligence_state_module, "BOARD_SNAPSHOT_PATH", fake_snapshot_path):
                refresh_state_store.write_json_file(
                    fake_snapshot_path,
                    {
                        "latest_key": "abc",
                        "updated_at": "2026-06-10T17:31:00Z",
                        "response": {
                            "ok": True,
                            "selected_date": "2026-06-15",
                            "top_opportunities": [{"name": "Play 1"}],
                            "analysis": {"recommendations": []},
                        },
                    },
                )

                response = intelligence_state_module.read_latest_intelligence_board_snapshot_response(
                    {"question": "top edges today", "date": "2026-06-17"}
                )

        self.assertIsNone(response)

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
            "top_opportunities": [{"name": "Play 1"}, {"name": "Play 2"}],
            "by_sport": {},
            "board_contract": {"schema": "intelligence_board_v1", "lane_counts": {"live": 1, "pregame": 0}, "active_lanes": ["live"], "cards": []},
            "analysis": {"recommendations": [{"name": "Play 1"}, {"name": "Play 2"}], "picks": [], "top_live_opportunities": [], "portfolio": {}, "parlays": []},
        }

        with app.test_request_context(
            "/api/intelligence/query",
            method="POST",
            json={"question": "top edges today", "force_refresh": True},
        ):
            with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state", return_value=dict(cached_response)):
                response = intelligence_query_api()

        payload = response.get_json()
        self.assertIsNotNone(payload)
        self.assertIn("version", payload)
        self.assertIn("timestamp", payload)
        self.assertIn("response", payload)
        self.assertEqual(payload["state_last_updated"], "2026-06-11T16:00:00Z")
        self.assertEqual(payload["candidate_count"], 2)
        self.assertEqual(payload["debug_source"], "snapshot_read")
        self.assertEqual(response.headers.get("Cache-Control"), "no-cache, no-store, must-revalidate")
        self.assertEqual(response.headers.get("Pragma"), "no-cache")
        self.assertEqual(response.headers.get("Expires"), "0")
        self.assertEqual(payload["response"]["analysis"]["recommendations"], [{"name": "Play 1"}, {"name": "Play 2"}])

    def test_query_endpoint_queues_refresh_when_default_cache_is_empty(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(intelligence_bp)

        with app.test_request_context(
            "/api/intelligence/query",
            method="POST",
            json={"question": "top edges today", "force_refresh": False},
        ):
            with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state", return_value=None):
                response = intelligence_query_api()

        payload = response.get_json()
        self.assertIsNotNone(payload)
        self.assertEqual(response.status_code, 200)
        self.assertIn("version", payload)
        self.assertIn("timestamp", payload)
        self.assertIn("response", payload)
        self.assertEqual(payload["response"]["top_opportunities"], [])
        self.assertEqual(payload["response"]["analysis"]["recommendations"], [])
        self.assertEqual(payload["response"]["analysis"]["portfolio"], {})
        self.assertEqual(payload["debug_source"], "snapshot_read")

    def test_query_endpoint_returns_empty_default_response_when_default_cache_exists_but_is_empty(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(intelligence_bp)

        empty_cached_response = {
            "ok": True,
            "top_opportunities": [],
            "by_sport": {},
            "analysis": {"recommendations": [], "picks": [], "top_live_opportunities": [], "portfolio": {}, "parlays": []},
        }
        computed_response = {
            "ok": True,
            "last_updated": "2026-06-11T16:08:00Z",
            "candidate_pool": {"candidate_count": 1, "candidates": [{"name": "Play 1"}]},
            "top_opportunities": [{"name": "Play 1"}],
            "by_sport": {},
            "analysis": {"recommendations": [{"name": "Play 1"}], "picks": [], "top_live_opportunities": [], "portfolio": {}, "parlays": []},
        }

        with app.test_request_context(
            "/api/intelligence/query",
            method="POST",
            json={"question": "top edges today", "force_refresh": False},
        ):
            with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state", return_value=dict(empty_cached_response)):
                response = intelligence_query_api()

        payload = response.get_json()
        self.assertIsNotNone(payload)
        self.assertEqual(response.status_code, 200)
        self.assertIn("version", payload)
        self.assertIn("timestamp", payload)
        self.assertIn("response", payload)
        self.assertEqual(payload["response"]["top_opportunities"], [])
        self.assertEqual(payload["response"]["analysis"]["recommendations"], [])
        self.assertEqual(payload["response"]["analysis"]["portfolio"], {})
        self.assertEqual(payload["debug_source"], "snapshot_read")

    def test_run_intelligence_uses_render_refresh_profile_defaults(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(intelligence_bp)

        with app.test_request_context("/intelligence/run", method="GET"):
            with patch("syndicate.blueprints.intelligence._latest_available_intelligence_date", return_value="2026-06-22"), patch(
                "syndicate.blueprints.intelligence.launch_refresh_run"
            ) as mocked_launch, patch(
                "syndicate.blueprints.intelligence.queue_intelligence_state_refresh"
            ) as mocked_queue:
                mocked_launch.return_value = {"ok": True, "state": "pending_external"}
                response = intelligence_module.run_intelligence()

        payload = response.get_json()
        self.assertIsNotNone(payload)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["launched"])
        mocked_launch.assert_called_once()
        launch_kwargs = mocked_launch.call_args.kwargs
        self.assertIsNone(launch_kwargs["mode"])
        self.assertIsNone(launch_kwargs["phase"])
        self.assertIsNone(launch_kwargs["regions"])
        self.assertIsNone(launch_kwargs["execution_mode"])
        self.assertIsNone(launch_kwargs["skip_mirror"])
        mocked_queue.assert_called_once()

    def test_query_endpoint_exposes_line_move_tracking_fields(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(intelligence_bp)

        cached_response = {
            "ok": True,
            "candidate_pool": {
                "candidate_count": 1,
                "candidates": [
                    {
                        "name": "Play 1",
                        "movement": {"line_delta": 0.5, "trend": "up"},
                        "movement_history": [
                            {"line": 6.5, "timestamp": "2026-06-11T16:00:00Z"},
                            {"line": 7.0, "timestamp": "2026-06-11T16:05:00Z"},
                        ],
                    }
                ],
            },
            "top_opportunities": [{"name": "Play 1", "movement": {"line_delta": 0.5, "trend": "up"}}],
            "by_sport": {},
            "analysis": {"recommendations": [{"name": "Play 1", "movement": {"line_delta": 0.5, "trend": "up"}}], "picks": [], "top_live_opportunities": [], "portfolio": {}, "parlays": []},
        }

        with app.test_request_context(
            "/api/intelligence/query",
            method="POST",
            json={"question": "top edges today", "force_refresh": False},
        ):
            with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state", return_value=dict(cached_response)):
                response = intelligence_query_api()

        payload = response.get_json()
        self.assertIsNotNone(payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["line_moves_tracked"], 1)
        self.assertEqual(payload["line_move_history_count"], 2)
        self.assertEqual(payload["line_move_source_count"], 1)
        self.assertEqual(payload["debug_source"], "snapshot_read")

    def test_intelligence_state_roundtrip_persists_to_tmp_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            reports_root = Path(tmp_dir) / "reports"
            state_path = reports_root / "intelligence" / "intelligence_state.json"
            board_snapshot_path = reports_root / "intelligence" / "board_snapshot.json"
            history_path = reports_root / "intelligence" / "intelligence_state_history.jsonl"
            daily_state_path = reports_root / "intelligence" / "intelligence_state_2026_06_18.json"
            daily_board_snapshot_path = reports_root / "intelligence" / "board_snapshot_2026_06_18.json"
            daily_history_path = reports_root / "intelligence" / "intelligence_state_history_2026_06_18.jsonl"
            state_payload = {
                "ok": True,
                "top_opportunities": [{"name": "Play 1"}, {"name": "Play 2"}],
                "by_sport": {"mlb": [{"name": "Play 1"}]},
                "analysis": {"recommendations": [{"name": "Play 1"}], "picks": [], "top_live_opportunities": [], "portfolio": {}, "parlays": []},
            }

            with patch.object(intelligence_state_module, "reports_root", return_value=reports_root):
                with patch.object(intelligence_state_module, "central_today_iso", return_value="2026-06-18"):
                    with patch.object(intelligence_state_module, "INTELLIGENCE_STATE_PATH", state_path), patch.object(intelligence_state_module, "BOARD_SNAPSHOT_PATH", board_snapshot_path), patch.object(intelligence_state_module, "INTELLIGENCE_HISTORY_PATH", history_path):
                        with patch("builtins.print") as mocked_print:
                            written = intelligence_state_module.write_intelligence_state(dict(state_payload))
                            loaded = intelligence_state_module.read_intelligence_state()
                            self.assertTrue(state_path.exists())
                            self.assertTrue(board_snapshot_path.exists())
                            self.assertTrue(history_path.exists())
                            self.assertTrue(daily_state_path.exists())
                            self.assertTrue(daily_board_snapshot_path.exists())
                            self.assertTrue(daily_history_path.exists())

            self.assertIsInstance(written, dict)
            self.assertIsInstance(loaded, dict)
            self.assertEqual(int(loaded.get("candidate_count") or 0), 2)
            self.assertEqual(int(written.get("candidate_count") or 0), 2)
            self.assertEqual(history_path.read_text(encoding="utf-8").strip().count("\n") + 1, 1)
            self.assertEqual(daily_history_path.read_text(encoding="utf-8").strip().count("\n") + 1, 1)
            self.assertGreaterEqual(mocked_print.call_count, 2)

    def test_state_compute_backfills_empty_engine_recommendations_from_top_opportunities(self) -> None:
        service = IntelligenceStateService()

        candidate_pool = {
            "selected_date": "2026-06-15",
            "source_fingerprint": "fingerprint-1",
            "candidate_count": 1,
            "candidate_pools": {},
            "global_pool": [{"name": "Play 1", "sport_slug": "mlb", "market": "Hits"}],
            "candidates": [{"name": "Play 1", "sport_slug": "mlb", "market": "Hits"}],
        }
        analysis_result = {
            "ok": True,
            "headline": "The Syndicate brief",
            "recommendations": [],
            "picks": [],
            "top_live_opportunities": [],
            "portfolio": {},
            "parlays": [],
        }

        with patch.object(service, "_source_state_fingerprint", return_value="fingerprint-1"):
            with patch.object(service, "_build_candidate_pool", return_value=dict(candidate_pool)):
                with patch(
                    "pipeline.intelligence_state.rank_global_recommendations",
                    return_value=[
                        {"name": "Play 1", "sport_slug": "mlb", "market": "Hits", "score": 91.0},
                        {"name": "Play 2", "sport_slug": "nba", "market": "Points", "score": 89.0},
                        {"name": "Play 3", "sport_slug": "wnba", "market": "Assists", "score": 87.0},
                    ],
                ):
                    with patch("pipeline.intelligence_state.run_routed_intelligence_pipeline", return_value=dict(analysis_result)):
                        response = service._compute_response({"question": "top edges today", "date": "2026-06-15", "limit": 1}, force_refresh=True)

        self.assertEqual(response["top_opportunities"][0]["name"], "Play 1")
        self.assertEqual(response["analysis"]["recommendations"][0]["name"], "Play 1")
        self.assertEqual(response["analysis"]["picks"][0]["name"], "Play 1")
        self.assertEqual(response["analysis"]["top_live_opportunities"][0]["name"], "Play 1")
        self.assertEqual(response["board_contract"]["recommendation_count"], 3)
        self.assertEqual(response["board_contract"]["schema"], "intelligence_board_v1")

    def test_state_compute_persists_board_snapshot_artifact(self) -> None:
        service = IntelligenceStateService()

        candidate_pool = {
            "selected_date": "2026-06-15",
            "source_fingerprint": "fingerprint-1",
            "candidate_count": 1,
            "candidate_pools": {},
            "global_pool": [{"name": "Play 1", "sport_slug": "mlb", "market": "Hits"}],
            "candidates": [{"name": "Play 1", "sport_slug": "mlb", "market": "Hits"}],
        }
        analysis_result = {
            "ok": True,
            "headline": "The Syndicate brief",
            "recommendations": [],
            "picks": [],
            "top_live_opportunities": [],
            "portfolio": {},
            "parlays": [],
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            state_path = temp_root / "query_state_cache.json"
            board_snapshot_path = temp_root / "board_snapshot.json"
            with patch.object(intelligence_state_module, "STATE_PATH", state_path), patch.object(intelligence_state_module, "BOARD_SNAPSHOT_PATH", board_snapshot_path):
                with patch.object(service, "_source_state_fingerprint", return_value="fingerprint-1"):
                    with patch.object(service, "_build_candidate_pool", return_value=dict(candidate_pool)):
                        with patch("pipeline.intelligence_state.rank_global_recommendations", return_value=[{"name": "Play 1", "sport_slug": "mlb", "market": "Hits"}]):
                            with patch("pipeline.intelligence_state.run_routed_intelligence_pipeline", return_value=dict(analysis_result)):
                                response = service._compute_response({"question": "top edges today", "date": "2026-06-15"}, force_refresh=True)
                self.assertTrue(board_snapshot_path.exists())
                board_snapshot = json.loads(board_snapshot_path.read_text(encoding="utf-8"))
                self.assertEqual(board_snapshot["board_contract"]["schema"], "intelligence_board_v1")
                self.assertEqual(board_snapshot["response"]["board_contract"]["schema"], "intelligence_board_v1")

    def test_state_compute_promotes_candidate_pool_when_ranking_returns_empty(self) -> None:
        service = IntelligenceStateService()

        candidate_pool = {
            "selected_date": "2026-06-15",
            "source_fingerprint": "fingerprint-1",
            "candidate_count": 3,
            "candidate_pools": {},
            "global_pool": [
                {"name": "Play B", "sport_slug": "mlb", "market": "Hits", "score": 4.5, "confidence": 0.2, "updated_at": "2026-06-15T20:00:00Z"},
                {"name": "Play A", "sport_slug": "mlb", "market": "Hits", "confidence": 0.9, "updated_at": "2026-06-15T18:00:00Z"},
                {"name": "Play C", "sport_slug": "mlb", "market": "Hits", "updated_at": "2026-06-15T22:00:00Z"},
            ],
            "candidates": [
                {"name": "Play B", "sport_slug": "mlb", "market": "Hits", "score": 4.5, "confidence": 0.2, "updated_at": "2026-06-15T20:00:00Z"},
                {"name": "Play A", "sport_slug": "mlb", "market": "Hits", "confidence": 0.9, "updated_at": "2026-06-15T18:00:00Z"},
                {"name": "Play C", "sport_slug": "mlb", "market": "Hits", "updated_at": "2026-06-15T22:00:00Z"},
            ],
        }
        analysis_result = {
            "ok": True,
            "headline": "The Syndicate brief",
            "recommendations": [],
            "picks": [],
            "top_live_opportunities": [],
            "portfolio": {},
            "parlays": [],
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            state_path = temp_root / "query_state_cache.json"
            board_snapshot_path = temp_root / "board_snapshot.json"
            with patch.object(intelligence_state_module, "STATE_PATH", state_path), patch.object(intelligence_state_module, "BOARD_SNAPSHOT_PATH", board_snapshot_path):
                with patch.object(service, "_source_state_fingerprint", return_value="fingerprint-1"):
                    with patch.object(service, "_build_candidate_pool", return_value=dict(candidate_pool)):
                        with patch("pipeline.intelligence_state.rank_global_recommendations", return_value=[]):
                            with patch("pipeline.intelligence_state.run_routed_intelligence_pipeline", return_value=dict(analysis_result)):
                                response = service._compute_response({"question": "top edges today", "date": "2026-06-15"}, force_refresh=True)

                self.assertGreater(response["candidate_count"], 0)
                self.assertEqual(response["candidate_count"], 3)
                self.assertEqual([item["name"] for item in response["top_opportunities"]], ["Play B", "Play A", "Play C"])
                self.assertEqual(response["analysis"]["recommendations"][0]["name"], "Play B")
                self.assertTrue(state_path.exists())
                self.assertTrue(board_snapshot_path.exists())
                reloaded = intelligence_state_module.read_latest_intelligence_state_response({"question": "top edges today", "date": "2026-06-15"}, force_refresh=True)
                self.assertIsInstance(reloaded, dict)
                self.assertEqual(int(reloaded.get("candidate_count") or 0), 3)
                self.assertEqual([item["name"] for item in (reloaded.get("top_opportunities") or [])], ["Play B", "Play A", "Play C"])

    def test_state_compute_normalizes_wnba_alias_candidates_before_ranking(self) -> None:
        service = IntelligenceStateService()

        candidate_pool = {
            "selected_date": "2026-06-15",
            "source_fingerprint": "fingerprint-wnba-1",
            "candidate_count": 1,
            "candidate_pools": {},
            "global_pool": [
                {
                    "sport": "WNBA",
                    "candidate_type": "prop",
                    "player": "Player A",
                    "market_type": "Assists",
                    "pick": "Over 7.5",
                    "odds_current": "55.6%",
                    "score": "55.6%",
                    "updated_at": "2026-06-15T20:00:00Z",
                }
            ],
            "candidates": [
                {
                    "sport": "WNBA",
                    "candidate_type": "prop",
                    "player": "Player A",
                    "market_type": "Assists",
                    "pick": "Over 7.5",
                    "odds_current": "55.6%",
                    "score": "55.6%",
                    "updated_at": "2026-06-15T20:00:00Z",
                }
            ],
        }
        analysis_result = {
            "ok": True,
            "headline": "The Syndicate brief",
            "recommendations": [],
            "picks": [],
            "top_live_opportunities": [],
            "portfolio": {},
            "parlays": [],
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            state_path = temp_root / "query_state_cache.json"
            board_snapshot_path = temp_root / "board_snapshot.json"
            with patch.object(intelligence_state_module, "STATE_PATH", state_path), patch.object(intelligence_state_module, "BOARD_SNAPSHOT_PATH", board_snapshot_path):
                with patch.object(service, "_source_state_fingerprint", return_value="fingerprint-wnba-1"):
                    with patch.object(service, "_build_candidate_pool", return_value=dict(candidate_pool)):
                        with patch("pipeline.intelligence_state.rank_global_recommendations", return_value=[]):
                            with patch("pipeline.intelligence_state.run_routed_intelligence_pipeline", return_value=dict(analysis_result)):
                                response = service._compute_response({"question": "top edges today", "date": "2026-06-15"}, force_refresh=True)

            self.assertEqual(response["candidate_count"], 1)
            self.assertEqual(len(response["top_opportunities"]), 1)
            self.assertEqual(response["top_opportunities"][0]["sport_slug"], "wnba")
            self.assertEqual(response["top_opportunities"][0]["entity"], "Player A")
            self.assertEqual(response["top_opportunities"][0]["market"], "Assists")
            self.assertEqual(response["analysis"]["recommendations"][0]["sport_slug"], "wnba")
            self.assertTrue(state_path.exists())
            self.assertTrue(board_snapshot_path.exists())

    def test_cached_intelligence_response_stays_on_fallback_when_cache_is_empty(self) -> None:
        payload = {"question": "top edges today", "date": "2026-06-15"}
        with patch("syndicate.blueprints.intelligence.read_latest_intelligence_board_snapshot_response", return_value=None):
            with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state_response", return_value=None):
                cached_response, source = intelligence_module._cached_intelligence_response_with_source(payload)

        self.assertEqual(source, "fallback")
        self.assertIsNone(cached_response)

    def test_intelligence_home_renders_initial_board_shell(self) -> None:
        app = create_app()
        app.testing = True

        with app.test_client() as client:
            with patch("syndicate.blueprints.intelligence._cached_intelligence_response_with_source", return_value=(None, "fallback")):
                with patch("syndicate.blueprints.intelligence.queue_intelligence_state_refresh") as mocked_queue:
                    response = client.get("/intelligence")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Initial board", html)
        self.assertIn("Prompt The Syndicate", html)
        self.assertIn("Board snapshot", html)
        self.assertIn("Live and pregame lanes", html)
        self.assertIn("Decision lanes", html)
        self.assertIn("intelligence-hero", html)
        self.assertIn("intelligence-lane__intro", html)
        mocked_queue.assert_called_once()

    def test_intelligence_home_honors_explicit_date_query_param(self) -> None:
        app = create_app()
        app.testing = True

        with app.test_client() as client:
            with patch("syndicate.blueprints.intelligence._cached_intelligence_response_with_source", return_value=(None, "fallback")):
                with patch("syndicate.blueprints.intelligence.queue_intelligence_state_refresh") as mocked_queue:
                    response = client.get("/intelligence?date=2026-06-13")

        self.assertEqual(response.status_code, 200)
        mocked_queue.assert_called_once()
        queued_payload = mocked_queue.call_args.args[0]
        self.assertEqual(queued_payload["date"], "2026-06-13")

    def test_intelligence_home_queues_refresh_when_cached_board_snapshot_is_stale(self) -> None:
        app = create_app()
        app.testing = True

        stale_response = {
            "ok": True,
            "selected_date": "2026-06-16",
            "last_updated": "2026-06-16T19:13:08Z",
            "top_opportunities": [{"name": "Stale Play"}],
            "by_sport": {},
            "analysis": {"recommendations": [{"name": "Stale Play"}], "picks": [], "top_live_opportunities": [], "portfolio": {}, "parlays": []},
        }

        with app.test_client() as client:
            with patch("syndicate.blueprints.intelligence.read_latest_intelligence_board_snapshot_response", return_value=dict(stale_response)):
                with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state_response", return_value=None):
                    with patch("syndicate.blueprints.intelligence.queue_intelligence_state_refresh") as mocked_queue:
                        response = client.get("/intelligence?date=2026-06-17")

        self.assertEqual(response.status_code, 200)
        mocked_queue.assert_called_once()

    def test_intelligence_home_forces_state_reload_before_cache_selection(self) -> None:
        app = create_app()
        app.testing = True

        expected_payload = {
            "question": "top edges today",
            "date": "2026-06-17",
            "mode": "recommendation",
            "sport": "all",
            "game_state": "all",
            "timing": "all",
            "limit": 5,
            "include_props": True,
            "include_games": True,
            "force_refresh": True,
        }

        with app.test_client() as client:
            with patch("syndicate.blueprints.intelligence.read_latest_intelligence_board_snapshot_response", return_value=None) as mocked_board_snapshot:
                with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state_response", return_value=None) as mocked_state_response:
                    with patch("syndicate.blueprints.intelligence.queue_intelligence_state_refresh") as mocked_queue:
                        response = client.get("/intelligence?date=2026-06-17")

        self.assertEqual(response.status_code, 200)
        mocked_board_snapshot.assert_called_once_with(expected_payload, force_refresh=True)
        mocked_state_response.assert_called_once_with(expected_payload, force_refresh=True)
        mocked_queue.assert_called_once()

    def test_intelligence_home_computes_render_fallback_when_cache_is_missing(self) -> None:
        app = create_app()
        app.testing = True

        empty_cached_response = {
            "ok": True,
            "top_opportunities": [],
            "by_sport": {},
            "analysis": {
                "recommendations": [],
                "picks": [],
                "top_live_opportunities": [],
                "portfolio": {},
                "parlays": [],
            },
        }

        with app.test_client() as client:
            with patch.dict(os.environ, {"RENDER": "true"}, clear=False):
                with patch("syndicate.blueprints.intelligence._cached_intelligence_response_with_source", return_value=(dict(empty_cached_response), "worker")):
                    with patch("syndicate.blueprints.intelligence.queue_intelligence_state_refresh") as mocked_queue:
                        response = client.get("/intelligence?date=2026-06-17")

        self.assertEqual(response.status_code, 200)
        mocked_queue.assert_called_once()

    def test_intelligence_home_suppresses_live_snapshot_missing_hydration(self) -> None:
        app = create_app()
        app.testing = True

        stale_live_response = {
            "ok": True,
            "selected_date": "2026-06-17",
            "top_opportunities": [
                {
                    "name": "Live Play",
                    "event_id": "evt-1",
                    "is_live": True,
                    "status_display": "Live",
                    "status_context": "In Progress",
                    "movement_history": [{"timestamp": "2026-06-17T17:15:00Z"}],
                }
            ],
            "by_sport": {},
            "analysis": {
                "recommendations": [
                    {
                        "name": "Live Play",
                        "event_id": "evt-1",
                        "is_live": True,
                        "status_display": "Live",
                        "status_context": "In Progress",
                        "movement_history": [{"timestamp": "2026-06-17T17:15:00Z"}],
                    }
                ],
                "top_live_opportunities": [],
                "picks": [],
                "portfolio": {},
                "parlays": [],
            },
        }

        with app.test_client() as client:
            with patch("syndicate.blueprints.intelligence.read_latest_intelligence_board_snapshot_response", return_value=dict(stale_live_response)):
                with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state_response", return_value=None):
                    with patch("syndicate.blueprints.intelligence.queue_intelligence_state_refresh") as mocked_queue:
                        response = client.get("/intelligence?date=2026-06-17")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertNotIn("Live Play", html)
        mocked_queue.assert_called_once()

    def test_query_endpoint_returns_empty_board_when_cached_live_snapshot_is_missing_hydration(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(intelligence_bp)

        stale_live_response = {
            "ok": True,
            "selected_date": "2026-06-17",
            "top_opportunities": [
                {
                    "name": "Live Play",
                    "event_id": "evt-1",
                    "is_live": True,
                    "status_display": "Live",
                    "status_context": "In Progress",
                    "movement_history": [{"timestamp": "2026-06-17T17:15:00Z"}],
                }
            ],
            "by_sport": {},
            "analysis": {
                "recommendations": [
                    {
                        "name": "Live Play",
                        "event_id": "evt-1",
                        "is_live": True,
                        "status_display": "Live",
                        "status_context": "In Progress",
                        "movement_history": [{"timestamp": "2026-06-17T17:15:00Z"}],
                    }
                ],
                "top_live_opportunities": [],
                "picks": [],
                "portfolio": {},
                "parlays": [],
            },
        }

        with app.test_request_context(
            "/api/intelligence/query",
            method="POST",
            json={"question": "top edges today", "date": "2026-06-17"},
        ):
            with patch(
                "syndicate.blueprints.intelligence.read_latest_intelligence_state",
                return_value={
                    "ok": True,
                    "top_opportunities": [{"name": "Live Play", "movement": {"line_delta": 0.5, "trend": "up"}}],
                    "by_sport": {},
                    "analysis": {
                        "recommendations": [
                            {
                                "name": "Live Play",
                                "event_id": "evt-1",
                                "is_live": True,
                                "status_display": "Live",
                                "status_context": "In Progress",
                                "movement_history": [{"timestamp": "2026-06-17T17:15:00Z"}],
                            }
                        ],
                        "top_live_opportunities": [],
                        "picks": [],
                        "portfolio": {},
                        "parlays": [],
                    },
                },
            ):
                response = intelligence_query_api()

        payload = response.get_json()
        self.assertIsNotNone(payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(payload["response"]["top_opportunities"]), 1)
        self.assertEqual(payload["response"]["top_opportunities"][0]["name"], "Live Play")
        self.assertEqual(payload["response"]["analysis"]["recommendations"][0]["name"], "Live Play")
        self.assertEqual(payload["debug_source"], "snapshot_read")

    def test_query_endpoint_preserves_recommendation_history_from_engine_response(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(intelligence_bp)

        engine_response = {
            "ok": True,
            "headline": "The Syndicate brief",
            "selected_date": "2026-06-13",
            "board_contract": {"schema": "intelligence_board_v1", "lane_counts": {"live": 1, "pregame": 0}, "active_lanes": ["live"], "cards": []},
            "recommendation_history": {"history_status": "available", "sample_size": 4, "settled_count": 3},
            "portfolio_tracking": {"open_exposure": 0.12, "risk_level": "low", "wager_count": 1},
            "portfolio_events": {"event_count": 2, "added_count": 1, "removed_count": 1, "adjusted_count": 0},
            "portfolio_event_records": [{"portfolio_event_id": "evt_1", "record_type": "portfolio_event"}],
            "recommendations": [],
            "parlays": [],
            "top_opportunities": [{"name": "Jayson Tatum Over 28.5"}],
            "by_sport": {},
        }

        with app.test_request_context(
            "/api/intelligence/query",
            method="POST",
            json={"question": "Analyze Jayson Tatum tonight", "date": "2026-06-13"},
        ):
            with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state", return_value=dict(engine_response)):
                response = intelligence_query_api()

        payload = response.get_json()
        self.assertIsNotNone(payload)
        self.assertIn("response", payload)
        self.assertEqual(payload["response"]["recommendation_history"]["history_status"], "available")
        self.assertEqual(payload["response"]["portfolio_tracking"]["risk_level"], "low")
        self.assertEqual(payload["response"]["portfolio_events"]["event_count"], 2)
        self.assertEqual(payload["response"]["portfolio_event_records"][0]["portfolio_event_id"], "evt_1")
        self.assertEqual(payload["response"]["board_contract"]["schema"], "intelligence_board_v1")

    def test_portfolio_event_endpoint_records_manual_event_bundle(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(intelligence_bp)

        bundle = {
            "schema_version": 1,
            "prediction": {"prediction_id": "pred_123"},
            "recommendations": [],
            "artifact_metadata": {},
            "portfolio_tracking": {"open_exposure": 0.25, "risk_level": "medium", "wager_count": 1},
            "portfolio_events": {"event_count": 1, "added_count": 1, "removed_count": 0, "adjusted_count": 0},
            "portfolio_event_records": [{"portfolio_event_id": "evt_123", "prediction_id": "pred_123", "recommendation_id": "rec_123", "record_type": "portfolio_event"}],
            "history": {"history_status": "empty", "sample_size": 0},
        }

        with app.test_request_context(
            "/api/intelligence/portfolio-event",
            method="POST",
            json={
                "question": "manual add",
                "selected_date": "2026-06-13",
                "portfolio_event": {"action": "add", "status": "open", "name": "Boston Celtics", "market": "points", "prediction_id": "pred_123", "recommendation_id": "rec_123"},
            },
        ):
            with patch("syndicate.blueprints.intelligence.build_intelligence_evaluation_bundle", return_value=dict(bundle)) as mocked_build:
                response = intelligence_portfolio_event_api()

        payload = response.get_json()
        self.assertIsNotNone(payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["ok"], True)
        self.assertEqual(payload["portfolio_event"]["action"], "add")
        self.assertEqual(payload["portfolio_event"]["prediction_id"], "pred_123")
        self.assertEqual(payload["portfolio_event"]["recommendation_id"], "rec_123")
        self.assertEqual(payload["portfolio_events"]["event_count"], 1)
        self.assertEqual(payload["portfolio_event_records"][0]["portfolio_event_id"], "evt_123")
        self.assertEqual(payload["portfolio_event_records"][0]["prediction_id"], "pred_123")
        self.assertEqual(payload["portfolio_event_records"][0]["recommendation_id"], "rec_123")
        mocked_build.assert_called_once()

    def test_status_endpoint_falls_back_to_empty_status_when_snapshot_is_missing(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(intelligence_bp)

        with app.test_request_context("/api/intelligence/status?date=2026-06-10", method="GET"):
            with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state", return_value={}) as mocked_read:
                response = intelligence_status_api()

        payload = response.get_json()
        self.assertIsNotNone(payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["debug_source"], "snapshot_read")
        self.assertEqual((payload.get("status") or {}).get("board_contract", {}).get("schema"), "intelligence_board_v1")
        self.assertEqual((payload.get("status") or {}).get("top_opportunities"), [])
        mocked_read.assert_called_once_with({"date": "2026-06-10"})

    def test_status_endpoint_defaults_to_latest_available_date_when_missing(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(intelligence_bp)

        with app.test_request_context("/api/intelligence/status", method="GET"):
            with patch("syndicate.blueprints.intelligence._latest_available_intelligence_date", return_value="2026-06-15"):
                with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state", return_value={}) as mocked_read:
                    response = intelligence_status_api()

        payload = response.get_json()
        self.assertIsNotNone(payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["debug_source"], "snapshot_read")
        mocked_read.assert_called_once_with({"date": "2026-06-15"})

    def test_status_endpoint_uses_latest_board_snapshot_when_state_is_date_mismatched(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(intelligence_bp)

        latest_snapshot = {
            "ok": True,
            "top_opportunities": [{"name": "Play 1"}],
            "by_sport": {"mlb": [{"name": "Play 1"}]},
            "analysis": {
                "recommendations": [{"name": "Play 1"}],
                "picks": [{"name": "Play 1"}],
                "top_live_opportunities": [{"name": "Play 1"}],
                "portfolio": {},
                "parlays": [],
            },
            "board_contract": {"schema": "intelligence_board_v1", "top_overall": [], "by_sport": {}, "live": [], "pregame": [], "portfolio": {}, "parlays": []},
        }

        with app.test_request_context("/api/intelligence/status?date=2026-06-10", method="GET"):
            with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state", return_value={}):
                with patch("syndicate.blueprints.intelligence.read_latest_intelligence_board_snapshot_response", return_value=dict(latest_snapshot)) as mocked_snapshot:
                    response = intelligence_status_api()

        payload = response.get_json()
        self.assertIsNotNone(payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["candidate_count"], 1)
        self.assertEqual((payload.get("status") or {}).get("top_opportunities", [])[0]["name"], "Play 1")
        mocked_snapshot.assert_called_once_with({}, force_refresh=False)

    def test_status_endpoint_includes_state_debug_fields(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(intelligence_bp)

        state_response = {
            "ok": True,
            "last_updated": "2026-06-11T16:05:00Z",
            "candidate_pool": {"candidates": [{"name": "Play 1"}]},
        }
        board_response = {
            "ok": True,
            "last_updated": "2026-06-11T16:05:00Z",
            "candidate_pool": {"candidates": [{"name": "Play 1"}]},
        }

        with app.test_request_context("/api/intelligence/status?date=2026-06-10", method="GET"):
            with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state", return_value=dict(state_response)):
                    response = intelligence_status_api()

        payload = response.get_json()
        self.assertIsNotNone(payload)
        self.assertEqual(payload["state_last_updated"], "2026-06-11T16:05:00Z")
        self.assertEqual(payload["candidate_count"], 1)
        self.assertEqual(payload["debug_source"], "snapshot_read")
        self.assertEqual(response.headers.get("Cache-Control"), "no-cache, no-store, must-revalidate")
        self.assertEqual(response.headers.get("Pragma"), "no-cache")
        self.assertEqual(response.headers.get("Expires"), "0")

    def test_status_endpoint_hydrates_opportunities_from_analysis_only_state(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(intelligence_bp)

        analysis_only_state = {
            "ok": True,
            "analysis": {
                "recommendations": [{"name": "Play 1"}],
                "picks": [],
                "top_live_opportunities": [],
                "portfolio": {},
                "parlays": [],
            },
        }

        with app.test_request_context("/api/intelligence/status?date=2026-06-10", method="GET"):
            with patch("syndicate.blueprints.intelligence.read_latest_intelligence_board_snapshot_response", return_value=None):
                with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state_response", return_value=dict(analysis_only_state)):
                    response = intelligence_status_api()

        payload = response.get_json()
        self.assertIsNotNone(payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual((payload.get("status") or {}).get("top_opportunities", [])[0]["name"], "Play 1")
        self.assertEqual(payload["candidate_count"], 1)
        self.assertEqual(payload["debug_source"], "snapshot_read")

    def test_status_endpoint_forces_state_snapshot_reload(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(intelligence_bp)

        state_response = {
            "ok": True,
            "last_updated": "2026-06-11T16:05:00Z",
            "candidate_pool": {"candidates": [{"name": "Play 1"}]},
        }

        expected_payload = {
            "question": "top edges today",
            "date": "2026-06-10",
            "mode": "recommendation",
            "sport": "all",
            "game_state": "all",
            "timing": "all",
            "limit": 5,
            "include_props": True,
            "include_games": True,
            "force_refresh": True,
        }

        with app.test_request_context("/api/intelligence/status?date=2026-06-10", method="GET"):
            with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state", return_value=dict(state_response)) as mocked_state_response:
                    response = intelligence_status_api()

        payload = response.get_json()
        self.assertIsNotNone(payload)
        self.assertEqual(payload["debug_source"], "snapshot_read")
        mocked_state_response.assert_called_once_with({"date": "2026-06-10"})
        self.assertEqual(response.headers.get("Cache-Control"), "no-cache, no-store, must-revalidate")
        self.assertEqual(response.headers.get("Pragma"), "no-cache")
        self.assertEqual(response.headers.get("Expires"), "0")

    def test_status_endpoint_does_not_compute_when_snapshot_is_missing(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(intelligence_bp)

        with app.test_request_context("/api/intelligence/status?date=2026-06-10", method="GET"):
            with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state", return_value={}):
                response = intelligence_status_api()

        payload = response.get_json()
        self.assertIsNotNone(payload)
        self.assertEqual(payload["debug_source"], "snapshot_read")
        self.assertEqual((payload.get("status") or {}).get("candidate_count", 0), 0)
        self.assertEqual(response.headers.get("Cache-Control"), "no-cache, no-store, must-revalidate")
        self.assertEqual(response.headers.get("Pragma"), "no-cache")
        self.assertEqual(response.headers.get("Expires"), "0")

    def test_status_endpoint_preserves_board_trace_metadata(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(intelligence_bp)

        state_response = {
            "ok": True,
            "last_updated": "2026-06-11T16:05:00Z",
            "top_opportunities": [
                {
                    "name": "Aaron Judge Over 1.5 Hits",
                    "sport": "mlb",
                    "sport_slug": "mlb",
                    "market": "Hits",
                    "score": 91.0,
                    "provenance": {
                        "source": "reports/intelligence/query_state_cache.json",
                        "source_id": "cand_123",
                        "selected_date": "2026-06-25",
                    },
                    "sport_context": {"matchup": "NYY at BOS"},
                }
            ],
            "analysis": {"recommendations": []},
            "board_contract": {
                "schema": "intelligence_board_v1",
                "cards": [
                    {
                        "name": "Aaron Judge Over 1.5 Hits",
                        "sport": "mlb",
                        "sport_slug": "mlb",
                        "market": "Hits",
                        "trace_path": "reports/intelligence/query_state_cache.json",
                        "trace": {
                            "source": "reports/intelligence/query_state_cache.json",
                            "source_id": "cand_123",
                            "selected_date": "2026-06-25",
                            "matchup": "NYY at BOS",
                        },
                    }
                ],
            },
        }

        with app.test_request_context("/api/intelligence/status?date=2026-06-10", method="GET"):
            with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state", return_value=dict(state_response)):
                with patch("syndicate.blueprints.intelligence.read_latest_intelligence_board_snapshot_response", return_value=dict(state_response)):
                    response = intelligence_status_api()

        payload = response.get_json()
        self.assertIsNotNone(payload)
        board_contract = (payload or {}).get("status", {}).get("board_contract", {})
        self.assertEqual((board_contract.get("cards") or [])[0].get("trace_path"), "reports/intelligence/query_state_cache.json")
        self.assertEqual((board_contract.get("cards") or [])[0].get("trace", {}).get("source_id"), "cand_123")

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

    def test_compute_response_recomputes_when_cached_snapshot_is_stale(self) -> None:
        service = IntelligenceStateService()
        service._interval_seconds = 1
        payload = {"question": "top edges today", "date": "2026-06-10", "limit": 5}
        normalized = service._normalize_payload(payload)
        snapshot_key = _payload_key(normalized)

        service._snapshots[snapshot_key] = IntelligenceSnapshot(
            key=snapshot_key,
            payload=dict(normalized),
            response={"ok": True, "top_opportunities": [], "by_sport": {}, "analysis": {}},
            computed_at="2026-06-10T00:00:00Z",
            source_fingerprint="fingerprint-1",
        )
        service._latest_key = snapshot_key

        with tempfile.TemporaryDirectory() as tmp_dir:
            reports_root = Path(tmp_dir) / "reports"
            manifests_root = reports_root / "manifests"
            manifests_root.mkdir(parents=True, exist_ok=True)
            (manifests_root / "mlb.json").write_text(
                '{"sport":"mlb","last_updated":"2026-06-10T10:00:00Z","artifact_paths":["reports/intelligence/example.json"],"status":"complete"}',
                encoding="utf-8",
            )

            with patch("pipeline.intelligence_state.reports_root", return_value=reports_root):
                with patch("pipeline.intelligence_state.build_intelligence_status", return_value={"selected_date": "2026-06-10", "sports": []}):
                    with patch("pipeline.intelligence_state.collect_all_recommendations", return_value=[{"name": "Play 1", "sport": "MLB", "market": "Hits", "score": 91.0}]) as mocked_collect:
                        with patch("pipeline.intelligence_state.rank_global_recommendations", return_value=[{"name": "Play 1", "sport": "MLB", "market": "Hits", "score": 91.0}]) as mocked_rank:
                            with patch("pipeline.intelligence_state.run_routed_intelligence_pipeline", return_value={"headline": "Test", "recommendations": []}) as mocked_pipeline:
                                with patch.object(service, "_source_state_fingerprint", return_value="fingerprint-1"):
                                    with patch.object(service, "_persist_locked", return_value=None):
                                        response = service._compute_response(payload)

        self.assertTrue(response.get("ok"))
        self.assertIn("candidate_pool", response)
        self.assertGreaterEqual(mocked_collect.call_count, 1)
        self.assertGreaterEqual(mocked_rank.call_count, 1)
        self.assertGreaterEqual(mocked_pipeline.call_count, 1)

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

        service._persist_locked = lambda: None

        def fake_write_latest_intelligence_state(state: dict[str, object], logger_info) -> dict[str, object]:
            service._stop.set()
            logger_info("STATE WRITTEN", extra={"written": True, "candidate_count": 0})
            return dict(state)

        with patch("pipeline.intelligence_state.run_routed_intelligence_pipeline", return_value={"ok": True, "top_opportunities": [], "by_sport": {}, "analysis": {}}) as mocked_pipeline:
            with patch("pipeline.intelligence_state.logger.info") as mocked_logger_info:
                with patch("pipeline.intelligence_state.write_latest_intelligence_state", side_effect=lambda state: fake_write_latest_intelligence_state(state, mocked_logger_info)) as mocked_write:
                    service._background_loop()

        mocked_pipeline.assert_called_once_with(normalized)
        mocked_write.assert_called_once()
        mocked_logger_info.assert_any_call("WORKER RUN", extra={"payload_key": snapshot_key})
        mocked_logger_info.assert_any_call("STATE WRITTEN", extra={"written": True, "candidate_count": 0})

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

    def test_merge_candidate_pools_sorts_by_score_descending(self) -> None:
        merged = IntelligenceStateService._merge_candidate_pools(
            {
                "nba": [
                    {"name": "NBA Play", "sport_slug": "nba", "score": 89.0},
                ],
                "mlb": [
                    {"name": "MLB Play", "sport_slug": "mlb", "score": 91.0},
                ],
            }
        )

        self.assertEqual([item["name"] for item in merged], ["MLB Play", "NBA Play"])
