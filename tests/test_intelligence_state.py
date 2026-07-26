from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import time

from flask import Flask

import pipeline.intelligence_state as intelligence_state_module
from syndicate.features.shared import refresh_state_store
from pipeline.intelligence_state import IntelligenceSnapshot
from pipeline.intelligence_state import IntelligenceStateService
from pipeline.intelligence_state import _payload_key
from syndicate.features.intelligence import candidate_identity_key
from syndicate.features.intelligence import collect_candidates_with_fallback_merge
from pipeline.intelligence_state import read_intelligence_board_state
from pipeline.intelligence_state import read_latest_intelligence_board_state
from pipeline.intelligence_state import write_intelligence_board_state
from pipeline.intelligence_state import slice_intelligence_board_state_for_request
from syndicate.app import create_app
import syndicate.blueprints.intelligence as intelligence_module
from syndicate.blueprints.intelligence import intelligence_bp
from syndicate.blueprints.intelligence import intelligence_portfolio_event_api
from syndicate.blueprints.intelligence import intelligence_status_api
from syndicate.blueprints.intelligence import intelligence_query_api


class IntelligenceStateTests(unittest.TestCase):
    def test_start_queues_default_payload_when_persisted_snapshot_is_stale(self) -> None:
        service = IntelligenceStateService()
        stale_snapshot = IntelligenceSnapshot(
            key=_payload_key({"question": "top edges today", "date": "2026-06-29"}),
            payload={"question": "top edges today", "date": "2026-06-29"},
            response={"ok": True, "response": {"selected_date": "2026-06-29"}},
            computed_at="2026-06-29T12:00:00Z",
            source_fingerprint="fingerprint-1",
        )
        service._snapshots[stale_snapshot.key] = stale_snapshot
        service._latest_key = stale_snapshot.key

        with patch.object(service, "_load_persisted_state_locked") as mocked_load, patch.object(
            service,
            "_background_loop",
            return_value=None,
        ), patch.object(service, "_enqueue_locked") as mocked_enqueue, patch.object(
            intelligence_state_module,
            "central_today_iso",
            return_value="2026-07-04",
        ):
            started = service.start()

        self.assertTrue(started)
        mocked_load.assert_called_once()
        mocked_enqueue.assert_called_once()
        self.assertEqual(mocked_enqueue.call_args.args[0]["date"], "2026-07-04")

    def test_read_latest_response_does_not_enqueue_work(self) -> None:
        service = IntelligenceStateService()
        snapshot = IntelligenceSnapshot(
            key="abc",
            payload={"question": "top edges today"},
            response={"ok": True, "response": {"recommendations": []}},
            # Fresh (not stale): this test is about the cache-hit path skipping
            # _enqueue_locked, not about staleness -- see
            # test_start_queues_default_payload_when_persisted_snapshot_is_stale
            # for that behavior.
            computed_at=intelligence_state_module._utc_now(),
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
            # Fresh: this test is about date-mismatch rejection, not staleness
            # -- a stale snapshot would fall through to a real (unmocked) sync
            # attempt below instead of hitting the date check being tested.
            computed_at=intelligence_state_module._utc_now(),
            source_fingerprint="fingerprint-1",
        )
        service._snapshots[snapshot.key] = snapshot
        service._latest_key = snapshot.key

        response = service.read_latest_response({"question": "top edges today", "date": "2026-06-17"})

        self.assertIsNone(response)

    def test_read_latest_response_does_not_fall_back_to_other_sport(self) -> None:
        service = IntelligenceStateService()
        mlb_payload = {
            "question": "top edges today",
            "date": "2026-07-07",
            "mode": "recommendation",
            "sport": "mlb",
            "game_state": "all",
            "timing": "all",
            "limit": 5,
            "include_props": True,
            "include_games": True,
        }
        snapshot = IntelligenceSnapshot(
            key=_payload_key(mlb_payload),
            payload=dict(mlb_payload),
            response={
                "ok": True,
                "selected_date": "2026-07-07",
                "recommendations": [{"sport": "MLB", "name": "Play 1"}],
                "top_opportunities": [{"sport": "MLB", "name": "Play 1"}],
                "board_contract": {"cards": [{"sport": "mlb", "name": "Play 1"}]},
            },
            computed_at="2026-07-07T00:00:00Z",
            source_fingerprint="fingerprint-1",
        )
        service._snapshots[snapshot.key] = snapshot
        service._latest_key = snapshot.key

        response = service.read_latest_response(
            {
                "question": "top edges today",
                "date": "2026-07-07",
                "mode": "recommendation",
                "sport": "wnba",
                "game_state": "all",
                "timing": "all",
                "limit": 5,
                "include_props": True,
                "include_games": True,
            },
            force_refresh=False,
            allow_latest_fallback=False,
        )

        self.assertIsNone(response)

    def test_read_latest_response_can_opt_into_latest_fallback(self) -> None:
        service = IntelligenceStateService()
        snapshot = {
            "key": _payload_key({"question": "top edges today", "date": "2026-06-15"}),
            "payload": {"question": "top edges today", "date": "2026-06-15"},
            "response": {
                "ok": True,
                "selected_date": "2026-06-15",
                "response": {"selected_date": "2026-06-15", "recommendations": [{"name": "Play 1"}]},
            },
            "computed_at": "2026-06-10T17:31:00Z",
            "source_fingerprint": "fingerprint-1",
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            state_path = Path(tmp_dir) / "reports" / "intelligence" / "query_state_cache.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            refresh_state_store.write_json_file(
                state_path,
                {
                    "latest_key": snapshot["key"],
                    "updated_at": "2026-06-10T17:31:00Z",
                    "snapshots": {snapshot["key"]: snapshot},
                },
            )

            with patch.object(intelligence_state_module, "STATE_PATH", state_path):
                response = service.read_latest_response(
                    {"question": "top edges today", "date": "2026-06-17"},
                    allow_latest_fallback=True,
                )

        self.assertIsNotNone(response)
        self.assertEqual(response.get("selected_date"), "2026-06-15")
        self.assertEqual(len(response.get("response", {}).get("recommendations", [])), 1)

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

    def test_board_snapshot_reader_falls_back_to_latest_non_empty_daily_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir, patch.dict(
            os.environ,
            {
                "SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports"),
            },
            clear=False,
        ):
            reports_root = Path(tmp_dir) / "reports"
            current_snapshot_path = reports_root / "intelligence" / "board_snapshot.json"
            daily_snapshot_path = reports_root / "intelligence" / "board_snapshot_2026_07_04.json"
            refresh_state_store.write_json_file(
                current_snapshot_path,
                {
                    "latest_key": "today-key",
                    "updated_at": "2026-07-05T17:00:00Z",
                    "response": {
                        "ok": True,
                        "selected_date": "2026-07-05",
                        "top_opportunities": [],
                        "analysis": {"recommendations": []},
                    },
                },
            )
            refresh_state_store.write_json_file(
                daily_snapshot_path,
                {
                    "latest_key": "yesterday-key",
                    "updated_at": "2026-07-04T20:45:39Z",
                    "response": {
                        "ok": True,
                        "selected_date": "2026-07-04",
                        "top_opportunities": [{"name": "Play 1"}],
                        "analysis": {"recommendations": [{"name": "Play 1"}]},
                    },
                },
            )

            with patch.object(intelligence_state_module, "BOARD_SNAPSHOT_PATH", current_snapshot_path):
                with patch.object(intelligence_state_module, "reports_root", return_value=reports_root):
                    response = intelligence_module.read_latest_intelligence_state({"question": "top edges today", "date": "2026-07-05"})

        self.assertIsNotNone(response)
        self.assertGreaterEqual(len(response.get("top_opportunities") or []), 1)
        self.assertEqual(int(response.get("candidate_count") or 0), 1)
        self.assertEqual(response.get("state_last_updated"), "2026-07-04T20:45:39Z")

    def test_board_snapshot_reader_accepts_recommendations_only_daily_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir, patch.dict(
            os.environ,
            {
                "SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports"),
            },
            clear=False,
        ):
            reports_root = Path(tmp_dir) / "reports"
            current_snapshot_path = reports_root / "intelligence" / "board_snapshot.json"
            daily_snapshot_path = reports_root / "intelligence" / "board_snapshot_2026_07_04.json"
            refresh_state_store.write_json_file(
                current_snapshot_path,
                {
                    "latest_key": "today-key",
                    "updated_at": "2026-07-05T17:00:00Z",
                    "response": {
                        "ok": True,
                        "selected_date": "2026-07-05",
                        "top_opportunities": [],
                        "analysis": {"recommendations": []},
                    },
                },
            )
            refresh_state_store.write_json_file(
                daily_snapshot_path,
                {
                    "latest_key": "yesterday-key",
                    "updated_at": "2026-07-04T20:45:39Z",
                    "response": {
                        "ok": True,
                        "selected_date": "2026-07-04",
                        "top_opportunities": [],
                        "recommendations": [{"name": "Play 1"}],
                        "analysis": {"recommendations": [{"name": "Play 1"}]},
                    },
                },
            )

            with patch.object(intelligence_state_module, "BOARD_SNAPSHOT_PATH", current_snapshot_path):
                with patch.object(intelligence_state_module, "reports_root", return_value=reports_root):
                    response = intelligence_module.read_latest_intelligence_state({"question": "top edges today", "date": "2026-07-05"})

        self.assertIsNotNone(response)
        self.assertGreaterEqual(len(response.get("top_opportunities") or []), 1)
        self.assertEqual(int(response.get("candidate_count") or 0), 1)
        self.assertEqual(response.get("state_last_updated"), "2026-07-04T20:45:39Z")

    def test_read_intelligence_state_prefers_daily_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir, patch.dict(
            os.environ,
            {
                "SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports"),
            },
            clear=False,
        ):
            reports_root = Path(tmp_dir) / "reports"
            legacy_state_path = reports_root / "intelligence" / "intelligence_state.json"
            daily_state_path = reports_root / "intelligence" / "intelligence_state_2026_06_18.json"
            refresh_state_store.write_json_file(
                legacy_state_path,
                {"candidate_count": 1, "top_opportunities": [{"name": "Legacy Play"}]},
            )
            refresh_state_store.write_json_file(
                daily_state_path,
                {"candidate_count": 2, "top_opportunities": [{"name": "Daily Play 1"}, {"name": "Daily Play 2"}]},
            )

            with patch.object(intelligence_state_module, "INTELLIGENCE_STATE_PATH", legacy_state_path):
                with patch.object(intelligence_state_module, "reports_root", return_value=reports_root):
                    response = intelligence_state_module.read_intelligence_state()

        self.assertIsNotNone(response)
        self.assertEqual(int(response.get("candidate_count") or 0), 2)
        self.assertEqual(response.get("top_opportunities", [])[0]["name"], "Daily Play 1")

    def test_source_state_fingerprint_changes_when_odds_history_updates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            reports_root = Path(tmp_dir) / "reports"
            manifest_path = reports_root / "manifests" / "mlb.json"
            odds_history_path = reports_root / "odds_control_plane" / "odds_history" / "mlb" / "2026-07-03.json"
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            odds_history_path.parent.mkdir(parents=True, exist_ok=True)

            refresh_state_store.write_json_file(
                manifest_path,
                {
                    "sport": "mlb",
                    "last_updated": "2026-07-03T18:00:00Z",
                    "status": "ready",
                    "artifact_paths": [],
                },
            )
            refresh_state_store.write_json_file(
                odds_history_path,
                {
                    "sport": "mlb",
                    "date": "2026-07-03",
                    "updated_at": "2026-07-03T18:00:00Z",
                    "markets": {
                        "market-1": {
                            "last_line": 7.0,
                            "last_odds": -110,
                            "history": [{"current_line": 7.0, "last_odds": -110, "captured_at": "2026-07-03T18:00:00Z"}],
                        }
                    },
                },
            )

            status_payload = {
                "selected_date": "2026-07-03",
                "sports": [{"slug": "mlb", "name": "MLB", "active_today": True}],
            }

            with patch.object(intelligence_state_module, "reports_root", return_value=reports_root):
                with patch("syndicate.features.shared.odds_control_plane.reports_root", return_value=reports_root):
                    with patch("pipeline.intelligence_state.build_intelligence_status", return_value=status_payload):
                        first_service = IntelligenceStateService()
                        first_fingerprint = first_service._source_state_fingerprint("2026-07-03")

            refresh_state_store.write_json_file(
                odds_history_path,
                {
                    "sport": "mlb",
                    "date": "2026-07-03",
                    "updated_at": "2026-07-03T19:00:00Z",
                    "markets": {
                        "market-1": {
                            "last_line": 7.5,
                            "last_odds": -108,
                            "history": [{"current_line": 7.5, "last_odds": -108, "captured_at": "2026-07-03T19:00:00Z"}],
                        }
                    },
                },
            )

            with patch.object(intelligence_state_module, "reports_root", return_value=reports_root):
                with patch("syndicate.features.shared.odds_control_plane.reports_root", return_value=reports_root):
                    with patch("pipeline.intelligence_state.build_intelligence_status", return_value=status_payload):
                        second_service = IntelligenceStateService()
                        second_fingerprint = second_service._source_state_fingerprint("2026-07-03")

        self.assertNotEqual(first_fingerprint, second_fingerprint)

    def test_latest_available_intelligence_date_prefers_daily_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir, patch.dict(
            os.environ,
            {
                "SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports"),
            },
            clear=False,
        ):
            reports_root = Path(tmp_dir) / "reports"
            daily_snapshot_path = reports_root / "intelligence" / "board_snapshot_2026_07_03.json"
            daily_snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            refresh_state_store.write_json_file(
                daily_snapshot_path,
                {
                    "selected_date": "2026-07-03",
                    "response": {"selected_date": "2026-07-03"},
                },
            )

            with patch.object(intelligence_module, "reports_root", return_value=reports_root):
                with patch.object(intelligence_module, "load_artifact_manifests", return_value=[]):
                    latest_date = intelligence_module._latest_available_intelligence_date()

        self.assertEqual(latest_date, "2026-07-03")

    def test_latest_available_intelligence_date_prefers_worker_snapshot_metadata_over_manifest_dates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir, patch.dict(
            os.environ,
            {
                "SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports"),
            },
            clear=False,
        ):
            reports_root = Path(tmp_dir) / "reports"
            board_snapshot_path = reports_root / "intelligence" / "board_snapshot.json"
            board_snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            refresh_state_store.write_json_file(
                board_snapshot_path,
                {
                    "updated_at": "2026-07-03T21:30:22-05:00",
                    "response": {
                        "top_opportunities": [{"name": "Fresh Play"}],
                    },
                },
            )

            fake_manifest = type(
                "FakeManifest",
                (),
                {
                    "predictions": (),
                    "edges": (),
                    "recommendations": (),
                    "live_data": (),
                },
            )()

            with patch.object(intelligence_module, "reports_root", return_value=reports_root):
                with patch.object(intelligence_module, "load_artifact_manifests", return_value=[fake_manifest]):
                    latest_date = intelligence_module._latest_available_intelligence_date()

        self.assertEqual(latest_date, "2026-07-03")

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

    def test_read_latest_response_avoids_forced_sync_when_force_refresh_is_false(self) -> None:
        service = IntelligenceStateService()

        with patch.object(service, "_sync_persisted_state_locked") as mocked_sync:
            response = service.read_latest_response({"question": "top edges today"}, force_refresh=False)

        self.assertIsNone(response)
        mocked_sync.assert_called_once_with(force=False)

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
            # force_refresh=True only "reads cached state only" on the
            # Render-hosted branch (queues a background refresh, serves
            # cache immediately) -- on the non-hosted branch it triggers a
            # real synchronous recompute instead. Mock hosted=True so this
            # test actually exercises what its name says, instead of
            # accidentally running the full (very slow) live pipeline.
            with patch("syndicate.blueprints.intelligence._render_hosted_request", return_value=True), patch(
                "syndicate.blueprints.intelligence._safe_queue_intelligence_state_refresh"
            ), patch("syndicate.blueprints.intelligence.read_latest_intelligence_state", return_value=dict(cached_response)), patch(
                "syndicate.blueprints.intelligence._cached_intelligence_response_with_source",
                return_value=(dict(cached_response), "snapshot_read"),
            ):
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

    def test_status_endpoint_refreshes_stale_snapshot_for_requested_date(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(intelligence_bp)

        stale_response = {
            "ok": True,
            "analysis": {
                "recommendations": [{"name": "Stale Play"}],
                "evaluation_record": {
                    "artifact_metadata": {
                        "manifest_summary": {"selected_date": "2026-06-29", "sport": "all"},
                        "selected_date": "2026-06-29",
                    }
                },
            },
            "top_opportunities": [{"name": "Stale Play"}],
        }
        fresh_response = {
            "ok": True,
            "selected_date": "2026-07-04",
            "analysis": {"recommendations": [{"name": "Fresh Play"}]},
            "top_opportunities": [{"name": "Fresh Play"}],
        }

        with app.test_request_context("/api/intelligence/status?date=2026-07-04", method="GET"):
            with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state", side_effect=[dict(stale_response), dict(fresh_response)]), patch(
                "syndicate.blueprints.intelligence.queue_intelligence_state_refresh"
            ) as mocked_queue:
                response = intelligence_status_api()

        payload = response.get_json()
        self.assertIsNotNone(payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"]["selected_date"], "2026-07-04")
        self.assertEqual(payload["top_opportunities"][0]["name"], "Fresh Play")
        mocked_queue.assert_called_once()

    def test_status_endpoint_uses_default_board_payload_shape(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(intelligence_bp)

        captured_payloads: list[dict[str, object]] = []

        def _fake_read_latest_intelligence_state(payload: dict[str, object] | None = None) -> dict[str, object]:
            captured_payloads.append(dict(payload or {}))
            return {
                "ok": True,
                "selected_date": "2026-07-05",
                "candidate_count": 1,
                "top_opportunities": [{"name": "Fresh Play"}],
                "analysis": {"recommendations": [{"name": "Fresh Play"}], "picks": [], "top_live_opportunities": [], "portfolio": {}, "parlays": []},
            }

        with app.test_request_context("/api/intelligence/status?date=2026-07-05", method="GET"):
            with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state", side_effect=_fake_read_latest_intelligence_state):
                with patch("syndicate.blueprints.intelligence.queue_intelligence_state_refresh") as mocked_queue:
                    response = intelligence_status_api()

        payload = response.get_json()
        self.assertIsNotNone(payload)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(captured_payloads)
        self.assertEqual(captured_payloads[0].get("question"), "top edges today")
        self.assertEqual(captured_payloads[0].get("mode"), "recommendation")
        self.assertEqual(payload["status"]["top_opportunities"][0]["name"], "Fresh Play")
        mocked_queue.assert_not_called()

    def test_response_selected_date_reads_nested_evaluation_metadata(self) -> None:
        payload = {
            "analysis": {
                "evaluation_record": {
                    "artifact_metadata": {
                        "manifest_summary": {"selected_date": "2026-06-29"},
                    }
                }
            }
        }

        self.assertEqual(intelligence_module._response_selected_date(payload), "2026-06-29")

    def test_query_endpoint_queues_refresh_when_default_cache_is_empty(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(intelligence_bp)

        computed_response = {
            "ok": True,
            "candidate_count": 5,
            "state_last_updated": "2026-07-04T20:37:13Z",
            "top_opportunities": [{"name": "Computed Play"}],
            "by_sport": {"mlb": [{"name": "Computed Play"}]},
            "analysis": {
                "recommendations": [{"name": "Computed Play"}],
                "picks": [{"name": "Computed Play"}],
                "top_live_opportunities": [],
                "portfolio": {},
                "parlays": [],
            },
        }

        with app.test_request_context(
            "/api/intelligence/query",
            method="POST",
            json={"question": "top edges today", "force_refresh": False},
        ):
            with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state", return_value=None):
                with patch("syndicate.blueprints.intelligence.launch_refresh_run") as mocked_launch:
                    with patch("syndicate.blueprints.intelligence.queue_intelligence_state_refresh") as mocked_queue:
                        response = intelligence_query_api()

        payload = response.get_json()
        self.assertIsNotNone(payload)
        self.assertEqual(response.status_code, 200)
        # A completely empty cache legitimately triggers more than one
        # internal queue attempt (initial-compute path + empty-response
        # fallback path) -- what matters is that a refresh gets queued at
        # all, not the exact call count.
        self.assertGreaterEqual(mocked_queue.call_count, 1)
        mocked_launch.assert_not_called()
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

        computed_response = {
            "ok": True,
            "candidate_count": 5,
            "state_last_updated": "2026-07-04T20:37:13Z",
            "top_opportunities": [{"name": "Computed Play"}],
            "by_sport": {"mlb": [{"name": "Computed Play"}]},
            "analysis": {
                "recommendations": [{"name": "Computed Play"}],
                "picks": [{"name": "Computed Play"}],
                "top_live_opportunities": [],
                "portfolio": {},
                "parlays": [],
            },
        }

        with app.test_request_context(
            "/api/intelligence/query",
            method="POST",
            json={"question": "top edges today", "force_refresh": False},
        ):
            with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state", return_value=dict({"ok": True, "top_opportunities": [], "by_sport": {}, "analysis": {"recommendations": [], "picks": [], "top_live_opportunities": [], "portfolio": {}, "parlays": []}})):
                with patch("syndicate.blueprints.intelligence.launch_refresh_run") as mocked_launch:
                    with patch("syndicate.blueprints.intelligence.queue_intelligence_state_refresh") as mocked_queue:
                        response = intelligence_query_api()

        payload = response.get_json()
        self.assertIsNotNone(payload)
        self.assertEqual(response.status_code, 200)
        # A completely empty cache legitimately triggers more than one
        # internal queue attempt (initial-compute path + empty-response
        # fallback path) -- what matters is that a refresh gets queued at
        # all, not the exact call count.
        self.assertGreaterEqual(mocked_queue.call_count, 1)
        mocked_launch.assert_not_called()
        self.assertIn("version", payload)
        self.assertIn("timestamp", payload)
        self.assertIn("response", payload)
        self.assertEqual(payload["response"]["top_opportunities"], [])
        self.assertEqual(payload["response"]["analysis"]["recommendations"], [])
        self.assertEqual(payload["response"]["analysis"]["portfolio"], {})
        self.assertEqual(payload["debug_source"], "snapshot_read")

    def test_query_endpoint_returns_queued_response_when_default_cache_is_empty(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(intelligence_bp)

        computed_response = {
            "ok": True,
            "candidate_count": 5,
            "state_last_updated": "2026-07-04T20:37:13Z",
            "top_opportunities": [{"name": "Computed Play"}],
            "by_sport": {"mlb": [{"name": "Computed Play"}]},
            "analysis": {
                "recommendations": [{"name": "Computed Play"}],
                "picks": [{"name": "Computed Play"}],
                "top_live_opportunities": [],
                "portfolio": {},
                "parlays": [],
            },
        }

        with app.test_request_context(
            "/api/intelligence/query",
            method="POST",
            json={"question": "top edges today", "force_refresh": False},
        ):
            with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state", return_value=dict({"ok": True, "top_opportunities": [], "by_sport": {}, "analysis": {"recommendations": [], "picks": [], "top_live_opportunities": [], "portfolio": {}, "parlays": []}})):
                with patch("syndicate.blueprints.intelligence.launch_refresh_run") as mocked_launch:
                    with patch("syndicate.blueprints.intelligence.queue_intelligence_state_refresh") as mocked_queue:
                        response = intelligence_query_api()

        payload = response.get_json()
        self.assertIsNotNone(payload)
        self.assertEqual(response.status_code, 200)
        # See test_query_endpoint_queues_refresh_when_default_cache_is_empty:
        # an empty-content cache legitimately triggers more than one internal
        # queue attempt -- what matters is that a refresh gets queued at all.
        self.assertGreaterEqual(mocked_queue.call_count, 1)
        mocked_launch.assert_not_called()
        self.assertEqual(payload["response"]["top_opportunities"], [])
        self.assertEqual(payload["response"]["analysis"]["recommendations"], [])
        self.assertTrue(payload["response"].get("queued"))
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
                with patch("syndicate.blueprints.intelligence.queue_intelligence_state_refresh") as mocked_queue:
                    response = intelligence_query_api()

        payload = response.get_json()
        self.assertIsNotNone(payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["line_moves_tracked"], 1)
        mocked_queue.assert_not_called()
        self.assertEqual(payload["line_move_history_count"], 2)
        self.assertEqual(payload["line_move_source_count"], 1)
        self.assertEqual(payload["debug_source"], "snapshot_read")
        self.assertEqual(payload["response"]["top_opportunities"][0]["name"], "Play 1")
        self.assertEqual(payload["response"]["analysis"]["recommendations"][0]["name"], "Play 1")
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
                    "pipeline.intelligence_state._balanced_recommendation_order",
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
                        with patch("pipeline.intelligence_state._balanced_recommendation_order", return_value=[{"name": "Play 1", "sport_slug": "mlb", "market": "Hits"}]):
                            with patch("pipeline.intelligence_state.run_routed_intelligence_pipeline", return_value=dict(analysis_result)):
                                response = service._compute_response({"question": "top edges today", "date": "2026-06-15"}, force_refresh=True)
                self.assertTrue(board_snapshot_path.exists())
                board_snapshot = json.loads(board_snapshot_path.read_text(encoding="utf-8"))
                self.assertEqual(board_snapshot["board_contract"]["schema"], "intelligence_board_v1")
                self.assertEqual(board_snapshot["response"]["board_contract"]["schema"], "intelligence_board_v1")

    def test_state_compute_persists_freshness_metadata_on_board_snapshot(self) -> None:
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
                        with patch("pipeline.intelligence_state._balanced_recommendation_order", return_value=[{"name": "Play 1", "sport_slug": "mlb", "market": "Hits"}]):
                            with patch("pipeline.intelligence_state.run_routed_intelligence_pipeline", return_value=dict(analysis_result)):
                                service._compute_response({"question": "top edges today", "date": "2026-06-15"}, force_refresh=True)

                board_snapshot = json.loads(board_snapshot_path.read_text(encoding="utf-8"))
                self.assertIn("state_meta", board_snapshot)
                self.assertEqual(board_snapshot["state_meta"]["freshness_status"], "fresh")
                self.assertEqual(board_snapshot["response"]["state_meta"]["freshness_status"], "fresh")

                legacy_snapshot_path = temp_root / "legacy_board_snapshot.json"
                refresh_state_store.write_json_file(
                    legacy_snapshot_path,
                    {
                        "latest_key": "legacy-key",
                        "updated_at": "2026-06-15T20:00:00Z",
                        "response": {
                            "ok": True,
                            "selected_date": "2026-06-15",
                            "top_opportunities": [{"name": "Play 1"}],
                            "analysis": {"recommendations": []},
                        },
                    },
                )

                # read_latest_intelligence_board_snapshot_response resolves its
                # read path via _intelligence_state_read_path, which also globs
                # today's REAL daily-suffixed snapshots under reports_root() --
                # unpatched, that leaks this sandbox's actual accumulated
                # reports/intelligence/ data ahead of the legacy fixture below.
                # Point reports_root at the temp dir too so only the legacy
                # fixture we just wrote is visible.
                with patch.object(intelligence_state_module, "BOARD_SNAPSHOT_PATH", legacy_snapshot_path), patch.object(intelligence_state_module, "reports_root", return_value=temp_root):
                    legacy_response = intelligence_state_module.read_latest_intelligence_board_snapshot_response({"question": "top edges today", "date": "2026-06-15"})

        self.assertIsNotNone(legacy_response)
        self.assertIn("state_meta", legacy_response)
        self.assertEqual(legacy_response["state_meta"]["freshness_status"], "fresh")
        self.assertEqual(legacy_response["state_last_updated"], "2026-06-15T20:00:00Z")

    def test_queue_refresh_persists_pending_payloads_for_worker_reload(self) -> None:
        service = IntelligenceStateService()

        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            state_path = temp_root / "query_state_cache.json"
            board_snapshot_path = temp_root / "board_snapshot.json"
            with patch.object(intelligence_state_module, "STATE_PATH", state_path), patch.object(intelligence_state_module, "BOARD_SNAPSHOT_PATH", board_snapshot_path):
                queued_key = service.queue_refresh({"question": "top edges today", "date": "2026-06-15", "sport": "mlb"})
                persisted_payload = json.loads(state_path.read_text(encoding="utf-8"))

                self.assertIn("watched_payloads", persisted_payload)
                self.assertIn("pending_keys", persisted_payload)
                self.assertIn(queued_key, persisted_payload["watched_payloads"])
                self.assertIn(queued_key, persisted_payload["pending_keys"])

                reloaded_service = IntelligenceStateService()
                with patch.object(intelligence_state_module, "STATE_PATH", state_path):
                    reloaded_service._load_persisted_state_locked(force=True)

                self.assertIn(queued_key, reloaded_service._watched_payloads)
                self.assertIn(queued_key, reloaded_service._pending_keys)

    def test_queue_board_state_refresh_persists_for_cross_process_pickup(self) -> None:
        # Confirmed live 2026-07-22: web (which queues on real requests) and
        # refresh-worker (whose _background_loop actually drains and writes)
        # are separate processes with separate IntelligenceStateService
        # instances -- queuing in one process's memory never reached the
        # other's until this was persisted through the same shared
        # STATE_PATH store _sync_persisted_queue_locked already re-reads
        # every iteration, mirroring queue_refresh's existing behavior above.
        service = IntelligenceStateService()

        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            state_path = temp_root / "query_state_cache.json"
            board_snapshot_path = temp_root / "board_snapshot.json"
            with patch.object(intelligence_state_module, "STATE_PATH", state_path), patch.object(intelligence_state_module, "BOARD_SNAPSHOT_PATH", board_snapshot_path):
                queued_date = service.queue_board_state_refresh("2026-06-15")
                persisted_payload = json.loads(state_path.read_text(encoding="utf-8"))

                self.assertIn("watched_board_dates", persisted_payload)
                self.assertEqual(persisted_payload["watched_board_dates"].get(queued_date), queued_date)

                # A second, independent instance (standing in for the other
                # process) must pick this up via a plain reload, exactly
                # like the payload-keyed queue already does.
                other_process_service = IntelligenceStateService()
                with patch.object(intelligence_state_module, "STATE_PATH", state_path):
                    other_process_service._load_persisted_state_locked(force=True)

                self.assertIn(queued_date, other_process_service._watched_board_dates)

    def test_sync_persisted_queue_locked_picks_up_board_dates_queued_by_another_process(self) -> None:
        service = IntelligenceStateService()

        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            state_path = temp_root / "query_state_cache.json"
            board_snapshot_path = temp_root / "board_snapshot.json"
            with patch.object(intelligence_state_module, "STATE_PATH", state_path), patch.object(intelligence_state_module, "BOARD_SNAPSHOT_PATH", board_snapshot_path):
                other_process_service = IntelligenceStateService()
                other_process_service.queue_board_state_refresh("2026-06-20")

                self.assertEqual(list(service._watched_board_dates), [])
                service._sync_persisted_queue_locked()

                self.assertIn("2026-06-20", service._watched_board_dates)

    def test_drain_one_watched_board_date_persists_pop_to_avoid_resurrection(self) -> None:
        # Without this, the next _sync_persisted_queue_locked() call (top of
        # every _background_loop iteration) would re-read the still-stale
        # persisted copy and put the just-drained date right back, redraining
        # the same date forever.
        service = IntelligenceStateService()

        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            state_path = temp_root / "query_state_cache.json"
            board_snapshot_path = temp_root / "board_snapshot.json"
            with patch.object(intelligence_state_module, "STATE_PATH", state_path), patch.object(intelligence_state_module, "BOARD_SNAPSHOT_PATH", board_snapshot_path):
                service.queue_board_state_refresh("2026-06-15")
                with patch.object(service, "_build_intelligence_board_state", return_value={"selected_date": "2026-06-15", "candidate_count": 0, "covered_sports": [], "by_sport": {}, "ranked_all": []}):
                    with patch("pipeline.intelligence_state.write_intelligence_board_state"):
                        service._drain_one_watched_board_date()

                self.assertEqual(list(service._watched_board_dates), [])
                persisted_payload = json.loads(state_path.read_text(encoding="utf-8"))
                self.assertEqual(persisted_payload.get("watched_board_dates"), {})

    def test_drain_one_watched_board_date_async_runs_sync_version_off_the_main_thread(self) -> None:
        # Confirmed live 2026-07-22: _build_intelligence_board_state
        # (sport="all", no limit) ran past 10 minutes for a single date.
        # Calling it inline in _background_loop blocked that same loop's
        # legacy queue processing -- the thing that keeps the real,
        # currently-served board fresh -- for that whole duration. This
        # must run off the main thread so no duration, however long, can
        # ever block anything else.
        service = IntelligenceStateService()
        call_completed = threading.Event()

        def fake_drain() -> None:
            call_completed.set()

        with patch.object(service, "_drain_one_watched_board_date", side_effect=fake_drain) as mocked_drain:
            main_thread = threading.current_thread()
            service._drain_one_watched_board_date_async()
            self.assertTrue(call_completed.wait(timeout=2.0), "async drain never ran")

        mocked_drain.assert_called_once()
        self.assertIsNotNone(service._board_state_drain_thread)
        self.assertNotEqual(service._board_state_drain_thread, main_thread)

    def test_drain_one_watched_board_date_async_skips_when_already_running(self) -> None:
        service = IntelligenceStateService()
        drain_may_finish = threading.Event()
        drain_started = threading.Event()

        def slow_drain() -> None:
            drain_started.set()
            drain_may_finish.wait(timeout=2.0)

        with patch.object(service, "_drain_one_watched_board_date", side_effect=slow_drain) as mocked_drain:
            service._drain_one_watched_board_date_async()
            self.assertTrue(drain_started.wait(timeout=2.0), "first drain never started")
            # A second call while the first is still running (blocked on
            # drain_may_finish) must not launch a second thread -- only one
            # canonical build should ever be in flight at a time.
            service._drain_one_watched_board_date_async()
            drain_may_finish.set()
            service._board_state_drain_thread.join(timeout=2.0)

        mocked_drain.assert_called_once()

    def test_board_publication_response_skips_full_intelligence_pipeline(self) -> None:
        service = IntelligenceStateService()

        candidate_pool = {
            "selected_date": "2026-06-15",
            "source_fingerprint": "fingerprint-1",
            "candidate_count": 2,
            "candidate_pools": {},
            "global_pool": [
                {"name": "Play B", "sport_slug": "mlb", "market": "Hits", "score": 4.5, "confidence": 0.2, "updated_at": "2026-06-15T20:00:00Z"},
                {"name": "Play A", "sport_slug": "mlb", "market": "Hits", "score": 6.2, "confidence": 0.9, "updated_at": "2026-06-15T18:00:00Z"},
            ],
            "candidates": [
                {"name": "Play B", "sport_slug": "mlb", "market": "Hits", "score": 4.5, "confidence": 0.2, "updated_at": "2026-06-15T20:00:00Z"},
                {"name": "Play A", "sport_slug": "mlb", "market": "Hits", "score": 6.2, "confidence": 0.9, "updated_at": "2026-06-15T18:00:00Z"},
            ],
        }

        with patch.object(service, "_source_state_fingerprint", return_value="fingerprint-1"):
            with patch.object(service, "_build_candidate_pool", return_value=dict(candidate_pool)):
                response = service._compute_board_publication_response({"question": "top edges today", "date": "2026-06-15", "limit": 1})

        self.assertTrue(response["ok"])
        self.assertEqual(response["candidate_count"], 2)
        self.assertEqual(len(response["top_opportunities"]), 1)
        self.assertEqual(response["top_opportunities"][0]["name"], "Play A")
        self.assertEqual(response["recommendations"][0]["name"], "Play A")
        self.assertIsNone(response["analysis"])
        self.assertIn("board_contract", response)
        self.assertEqual(response["board_contract"]["schema"], "intelligence_board_v1")
        self.assertTrue(response["state_last_updated"])
        self.assertEqual(response["state_last_updated"], response["snapshot_generated_at"])

    def test_board_publication_does_not_roll_over_when_next_day_is_also_empty(self) -> None:
        # A transient zero for today (e.g. an artifact-pull hiccup on one
        # cycle) must not permanently pin the published board to tomorrow's
        # date when tomorrow is *also* empty -- tomorrow is guaranteed to be
        # empty for most of today, since it hasn't started yet, and nothing
        # ever re-checks today once rolled over. Confirmed in production:
        # today had real games the whole time; a single zero reading rolled
        # the board over to a permanently-empty tomorrow.
        service = IntelligenceStateService()
        today = "2026-06-15"
        tomorrow = "2026-06-16"

        def fake_build_pool(selected_date: str, source_fingerprint: str) -> dict:
            return {
                "selected_date": selected_date,
                "source_fingerprint": source_fingerprint,
                "candidate_count": 0,
                "candidate_pools": {},
                "global_pool": [],
                "candidates": [],
            }

        with patch.object(intelligence_state_module, "central_today_iso", return_value=today):
            with patch.object(intelligence_state_module, "_next_supported_intelligence_date", return_value=tomorrow):
                with patch.object(service, "_source_state_fingerprint", return_value="fingerprint-1"):
                    with patch.object(service, "_build_candidate_pool", side_effect=fake_build_pool) as mocked_pool:
                        response = service._compute_board_publication_response({"question": "top edges today", "date": today, "limit": 5})

        self.assertEqual(response["candidate_count"], 0)
        self.assertEqual(response["selected_date"], today)
        called_dates = [call.args[0] for call in mocked_pool.call_args_list]
        self.assertIn(tomorrow, called_dates)

    def test_board_publication_rolls_over_when_next_day_has_more_candidates(self) -> None:
        service = IntelligenceStateService()
        today = "2026-06-15"
        tomorrow = "2026-06-16"

        def fake_build_pool(selected_date: str, source_fingerprint: str) -> dict:
            count = 0 if selected_date == today else 3
            candidates = [
                {"name": f"Play {i}", "sport_slug": "mlb", "market": "Hits", "score": 5.0, "confidence": 0.5, "updated_at": "2026-06-16T12:00:00Z"}
                for i in range(count)
            ]
            return {
                "selected_date": selected_date,
                "source_fingerprint": source_fingerprint,
                "candidate_count": count,
                "candidate_pools": {},
                "global_pool": candidates,
                "candidates": candidates,
            }

        with patch.object(intelligence_state_module, "central_today_iso", return_value=today):
            with patch.object(intelligence_state_module, "_next_supported_intelligence_date", return_value=tomorrow):
                with patch.object(service, "_source_state_fingerprint", return_value="fingerprint-1"):
                    with patch.object(service, "_build_candidate_pool", side_effect=fake_build_pool):
                        response = service._compute_board_publication_response({"question": "top edges today", "date": today, "limit": 5})

        self.assertEqual(response["candidate_count"], 3)
        self.assertEqual(response["selected_date"], tomorrow)

    def test_background_loop_consumes_persisted_queue_payloads(self) -> None:
        service = IntelligenceStateService()
        service._interval_seconds = 0

        payload = {"question": "top edges today", "date": "2026-06-15", "sport": "mlb"}
        normalized = service._normalize_payload(payload)
        queued_key = _payload_key(normalized)

        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_root = Path(tmp_dir)
            state_path = temp_root / "query_state_cache.json"
            board_snapshot_path = temp_root / "board_snapshot.json"
            persisted_state = {
                "latest_key": None,
                "updated_at": "2026-06-15T20:00:00Z",
                "watched_payloads": {queued_key: normalized},
                "pending_keys": {queued_key: normalized},
                "snapshots": {},
            }
            refresh_state_store.write_json_file(state_path, persisted_state)

            with patch.object(intelligence_state_module, "STATE_PATH", state_path), patch.object(intelligence_state_module, "BOARD_SNAPSHOT_PATH", board_snapshot_path):
                board_state = {
                    "ok": True,
                    "top_opportunities": [{"name": "Play 1"}],
                    "recommendations": [{"name": "Play 1"}],
                    "by_sport": {"mlb": [{"name": "Play 1"}]},
                    "board_contract": {"schema": "intelligence_board_v1", "cards": [{"name": "Play 1"}]},
                    "analysis": None,
                    "portfolio": {},
                    "parlays": [],
                    "selected_date": "2026-06-15",
                    "state_last_updated": "2026-06-15T20:00:00Z",
                    "last_updated": "2026-06-15T20:00:00Z",
                    "snapshot_generated_at": "2026-06-15T20:00:00Z",
                    "candidate_count": 1,
                }

                def fake_write_latest_intelligence_state(state: dict[str, object]) -> dict[str, object]:
                    service._stop.set()
                    return dict(state)

                with patch.object(service, "_compute_board_publication_response", return_value=dict(board_state)) as mocked_board_publish:
                    with patch("pipeline.intelligence_state.run_intelligence_pipeline", side_effect=AssertionError("full intelligence pipeline should not run during board-only publication")) as mocked_pipeline:
                        with patch("pipeline.intelligence_state.write_latest_intelligence_state", side_effect=fake_write_latest_intelligence_state) as mocked_write:
                            service._background_loop()

        mocked_board_publish.assert_called_once_with(normalized)
        mocked_pipeline.assert_not_called()
        mocked_write.assert_called_once()
        self.assertIn(queued_key, service._snapshots)
        self.assertEqual(service._latest_key, queued_key)

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
                        with patch("pipeline.intelligence_state._balanced_recommendation_order", return_value=[]):
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
                        with patch("pipeline.intelligence_state._balanced_recommendation_order", return_value=[]):
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

    def test_cached_intelligence_response_prefers_worker_state_over_board_snapshot(self) -> None:
        payload = {"question": "top edges today", "date": "2026-07-04"}
        worker_response = {
            "ok": True,
            "selected_date": "2026-07-04",
            "last_updated": "2026-07-04T18:40:54Z",
            "top_opportunities": [{"name": "Fresh Play"}],
            "analysis": {"recommendations": [{"name": "Fresh Play"}], "picks": [], "top_live_opportunities": [], "portfolio": {}, "parlays": []},
        }
        board_snapshot_response = {
            "ok": True,
            "selected_date": "2026-06-29",
            "last_updated": "2026-06-29T20:40:54Z",
            "top_opportunities": [{"name": "Stale Play"}],
            "analysis": {"recommendations": [{"name": "Stale Play"}], "picks": [], "top_live_opportunities": [], "portfolio": {}, "parlays": []},
        }

        with patch("syndicate.blueprints.intelligence._response_needs_refresh", return_value=False):
            with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state_response", return_value=dict(worker_response)):
                with patch("syndicate.blueprints.intelligence.read_latest_intelligence_board_snapshot_response", return_value=dict(board_snapshot_response)):
                    cached_response, source = intelligence_module._cached_intelligence_response_with_source(payload)

        self.assertEqual(source, "worker")
        self.assertEqual(cached_response.get("selected_date"), "2026-07-04")
        self.assertEqual(cached_response.get("top_opportunities", [])[0]["name"], "Fresh Play")

    def test_read_latest_intelligence_state_prefers_worker_state_over_board_snapshot(self) -> None:
        worker_response = {
            "ok": True,
            "selected_date": "2026-07-04",
            "last_updated": "2026-07-04T18:40:54Z",
            "top_opportunities": [{"name": "Fresh Play"}],
            "analysis": {"recommendations": [{"name": "Fresh Play"}], "picks": [], "top_live_opportunities": [], "portfolio": {}, "parlays": []},
        }
        board_snapshot_response = {
            "ok": True,
            "selected_date": "2026-06-29",
            "last_updated": "2026-06-29T20:40:54Z",
            "top_opportunities": [{"name": "Stale Play"}],
            "analysis": {"recommendations": [{"name": "Stale Play"}], "picks": [], "top_live_opportunities": [], "portfolio": {}, "parlays": []},
        }

        with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state_response", return_value=dict(worker_response)):
            with patch("syndicate.blueprints.intelligence.read_latest_intelligence_board_snapshot_response", return_value=dict(board_snapshot_response)):
                response = intelligence_module.read_latest_intelligence_state({"date": "2026-07-04"})

        self.assertEqual(response.get("selected_date"), "2026-07-04")
        self.assertEqual(response.get("top_opportunities", [])[0]["name"], "Fresh Play")

    def test_intelligence_home_renders_initial_board_shell(self) -> None:
        app = create_app()
        app.testing = True

        with app.test_client() as client:
            with patch("syndicate.blueprints.intelligence._cached_intelligence_response_with_source", return_value=(None, "fallback")):
                with patch("syndicate.blueprints.intelligence.queue_intelligence_state_refresh") as mocked_queue:
                    response = client.get("/intelligence")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        # Markers updated for the rewritten Betting Board UI (command bar /
        # filters / blotter / portfolio page) -- the old card-shell copy
        # ("Initial board", "Decision lanes", intelligence-hero/-lane__intro
        # classes) no longer exists in this template.
        self.assertIn("Betting Board", html)
        self.assertIn("Board snapshot", html)
        self.assertIn("board-toolbar", html)
        self.assertIn("board-empty", html)
        self.assertIn("/api/intelligence/query", html)
        self.assertNotIn("/api/syndicate/query", html)
        self.assertNotIn("/syndicate?question=", html)
        self.assertNotIn("powers Ask", html)
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

    def test_intelligence_home_shows_last_good_board_while_stale_same_date_refresh_queues(self) -> None:
        # A same-date pregame board that's simply old (e.g. a redeploy's
        # cold-start compute hasn't finished yet) should still render --
        # showing nothing while that catches up is worse UX than a slightly
        # stale board, and a refresh is queued regardless.
        aged_last_updated = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat().replace("+00:00", "Z")
        aged_response = {
            "ok": True,
            "selected_date": "2026-06-17",
            "last_updated": aged_last_updated,
            "top_opportunities": [{"name": "Aged But Real Play"}],
            "by_sport": {},
            "analysis": {"recommendations": [{"name": "Aged But Real Play"}], "picks": [], "top_live_opportunities": [], "portfolio": {}, "parlays": []},
        }

        app = create_app()
        app.testing = True

        with app.test_client() as client:
            with patch("syndicate.blueprints.intelligence.read_latest_intelligence_board_snapshot_response", return_value=dict(aged_response)):
                with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state_response", return_value=None):
                    with patch("syndicate.blueprints.intelligence.queue_intelligence_state_refresh") as mocked_queue:
                        response = client.get("/intelligence?date=2026-06-17")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Aged But Real Play", html)
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
        # The plain state-cache read deliberately does NOT force reload or
        # fall back to a stale latest snapshot here -- only the board
        # snapshot read (checked first, above) is forced; this read is a
        # cheap secondary check against the in-memory cache only.
        mocked_state_response.assert_called_once_with(expected_payload, force_refresh=False, allow_latest_fallback=False)
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
                with patch("syndicate.blueprints.intelligence.read_latest_intelligence_board_snapshot_response", return_value=None):
                    response = intelligence_status_api()

        payload = response.get_json()
        self.assertIsNotNone(payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["debug_source"], "snapshot_read")
        self.assertEqual((payload.get("status") or {}).get("board_contract", {}).get("schema"), "intelligence_board_v1")
        self.assertEqual((payload.get("status") or {}).get("top_opportunities"), [])
        self.assertGreaterEqual(mocked_read.call_count, 2)
        first_payload = mocked_read.call_args_list[0].args[0]
        self.assertEqual(first_payload.get("question"), "top edges today")
        self.assertEqual(first_payload.get("mode"), "recommendation")
        self.assertEqual(first_payload.get("date"), "2026-06-10")

    def test_status_endpoint_defaults_to_today_when_missing(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(intelligence_bp)

        with app.test_request_context("/api/intelligence/status", method="GET"):
            with patch("syndicate.blueprints.intelligence.central_today_iso", return_value="2026-07-04"):
                with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state", return_value={}) as mocked_read:
                    response = intelligence_status_api()

        payload = response.get_json()
        self.assertIsNotNone(payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["debug_source"], "snapshot_read")
        # An empty read_latest_intelligence_state combined with a real
        # (unmocked) board-snapshot read that also has no board content for
        # this fixture drives intelligence_status_api() into its final
        # fallback branch, which re-reads read_latest_intelligence_state a
        # third time -- 2 is the minimum, not an exact count. Matches the
        # assertGreaterEqual pattern already used by the sibling test above.
        self.assertGreaterEqual(mocked_read.call_count, 2)
        first_payload = mocked_read.call_args_list[0].args[0]
        self.assertEqual(first_payload.get("question"), "top edges today")
        self.assertEqual(first_payload.get("mode"), "recommendation")
        self.assertEqual(first_payload.get("date"), "2026-07-04")

    def test_status_endpoint_uses_latest_board_snapshot_when_state_is_date_mismatched(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(intelligence_bp)

        latest_snapshot = {
            "ok": True,
            "top_opportunities": [{"name": "Play 1"}],
            "by_sport": {"mlb": [{"name": "Play 1"}]},
            "analysis": {
                "recommendations": [{"name": "Play 1"}],
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
        mocked_snapshot.assert_called_once()

    def test_status_endpoint_prefers_board_snapshot_when_state_is_empty(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(intelligence_bp)

        empty_state = {
            "ok": True,
            "candidate_count": 0,
            "top_opportunities": [],
            "analysis": {
                "recommendations": [],
                "top_live_opportunities": [],
                "portfolio": {},
                "parlays": [],
                "movement": {},
            },
            "board_contract": {"schema": "intelligence_board_v1", "top_overall": [], "by_sport": {}, "live": [], "pregame": [], "portfolio": {}, "parlays": []},
        }
        board_snapshot = {
            "ok": True,
            "candidate_count": 19,
            "top_opportunities": [{"name": f"Play {index}"} for index in range(1, 20)],
            "recommendations": [{"name": f"Play {index}"} for index in range(1, 20)],
            "analysis": {
                "recommendations": [{"name": f"Play {index}"} for index in range(1, 20)],
                "top_live_opportunities": [{"name": f"Play {index}"} for index in range(1, 20)],
                "portfolio": {},
                "parlays": [],
            },
            "board_contract": {"schema": "intelligence_board_v1", "top_overall": [{"name": "Play 1"}], "by_sport": {}, "live": [], "pregame": [], "portfolio": {}, "parlays": []},
        }

        with app.test_request_context("/api/intelligence/status?date=2026-06-10", method="GET"):
            with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state", side_effect=[dict(empty_state), dict(empty_state)]):
                with patch("syndicate.blueprints.intelligence.read_latest_intelligence_board_snapshot_response", return_value=dict(board_snapshot)):
                    response = intelligence_status_api()

        payload = response.get_json()
        self.assertIsNotNone(payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["candidate_count"], 19)
        self.assertEqual(len((payload.get("status") or {}).get("top_opportunities", [])), 19)
        self.assertEqual((payload.get("status") or {}).get("top_opportunities", [])[0]["name"], "Play 1")

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
                with patch("syndicate.blueprints.intelligence.read_latest_intelligence_board_snapshot_response", return_value=None):
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

        with app.test_request_context("/api/intelligence/status?date=2026-06-10", method="GET"):
            with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state", return_value=dict(state_response)) as mocked_state_response:
                response = intelligence_status_api()

        payload = response.get_json()
        self.assertIsNotNone(payload)
        self.assertEqual(payload["debug_source"], "snapshot_read")
        self.assertGreaterEqual(mocked_state_response.call_count, 2)
        first_payload = mocked_state_response.call_args_list[0].args[0]
        self.assertEqual(first_payload.get("question"), "top edges today")
        self.assertEqual(first_payload.get("mode"), "recommendation")
        self.assertEqual(first_payload.get("date"), "2026-06-10")
        self.assertEqual(response.headers.get("Cache-Control"), "no-cache, no-store, must-revalidate")
        self.assertEqual(response.headers.get("Pragma"), "no-cache")
        self.assertEqual(response.headers.get("Expires"), "0")

    def test_status_endpoint_does_not_compute_when_snapshot_is_missing(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(intelligence_bp)

        with app.test_request_context("/api/intelligence/status?date=2026-06-10", method="GET"):
            with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state", return_value={}):
                with patch("syndicate.blueprints.intelligence.read_latest_intelligence_board_snapshot_response", return_value=None):
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

    def test_board_snapshot_promotes_board_contract_cards_into_visible_opportunities(self) -> None:
        snapshot = {
            "updated_at": "2026-06-11T16:05:00Z",
            "response": {
                "board_contract": {
                    "schema": "intelligence_board_v1",
                    "cards": [
                        {
                            "name": "Live Play",
                            "sport": "nba",
                            "sport_slug": "nba",
                            "market": "points",
                            "line": 28.5,
                            "odds": "-110",
                            "projected": 30.1,
                            "live_projection": 31.2,
                            "is_live": True,
                            "status_display": "Live",
                            "status_context": "In Progress",
                        },
                        {
                            "name": "Pregame Play",
                            "sport": "wnba",
                            "sport_slug": "wnba",
                            "market": "assists",
                            "line": 5.5,
                            "odds": "+104",
                            "projected": 6.1,
                            "is_live": False,
                            "status_display": "7:10 PM CT",
                            "status_context": "Scheduled",
                        },
                    ],
                    "lane_counts": {"live": 1, "pregame": 1, "archived": 0},
                    "active_lanes": ["live", "pregame"],
                }
            },
        }

        with patch("pipeline.intelligence_state.read_json_file", return_value=dict(snapshot)):
            promoted = intelligence_state_module.read_latest_intelligence_board_snapshot_response({"date": "2026-06-11"})

        self.assertIsNotNone(promoted)
        self.assertEqual(len(promoted.get("top_opportunities") or []), 2)
        self.assertEqual((promoted.get("top_opportunities") or [])[0].get("name"), "Live Play")
        self.assertEqual(len(promoted.get("recommendations") or []), 2)
        self.assertEqual(len(promoted.get("top_live_opportunities") or []), 1)
        self.assertEqual((promoted.get("top_live_opportunities") or [])[0].get("name"), "Live Play")
        self.assertEqual(sorted(promoted.get("by_sport") or {}), ["nba", "wnba"])

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

    def test_debug_state_fields_prefers_worker_state_meta_timestamp(self) -> None:
        payload = {
            "last_updated": "2026-06-29T20:40:54-05:00",
            "state_meta": {"computed_at": "2026-07-04T21:00:00Z"},
            "candidate_count": 38,
        }

        fields = intelligence_module._debug_state_fields(payload, source="snapshot_read")

        self.assertEqual(fields["state_last_updated"], "2026-07-04T21:00:00Z")
        self.assertEqual(fields["debug_source"], "snapshot_read")

    def test_status_page_redirects_to_api_status(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(intelligence_bp)

        with app.test_request_context("/intelligence/status?date=2026-06-10", method="GET"):
            response = app.view_functions["syndicate_intelligence.intelligence_status_page"]()

        self.assertEqual(response.status_code, 302)
        self.assertIn("/api/intelligence/status?date=2026-06-10", response.location)

    def test_default_intelligence_query_does_not_use_stale_latest_board_snapshot_fallback(self) -> None:
        response_payload = {
            "ok": True,
            "selected_date": "2026-07-02",
            "top_opportunities": [{"name": "Fallback Play", "sport_slug": "mlb", "market": "Hits"}],
            "by_sport": {"mlb": [{"name": "Fallback Play", "sport_slug": "mlb", "market": "Hits"}]},
            "analysis": {"recommendations": [{"name": "Fallback Play"}], "picks": [], "top_live_opportunities": [], "portfolio": {}, "parlays": []},
            "board_contract": {"schema": "intelligence_board_v1", "cards": [{"name": "Fallback Play"}]},
        }

        with patch("syndicate.blueprints.intelligence.read_latest_intelligence_board_snapshot_response", side_effect=[None, dict(response_payload)]):
            with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state_response", return_value=None):
                cached_response, source = intelligence_module._cached_intelligence_response_with_source(
                    {"question": "top edges today", "date": "2026-07-03"},
                    force_refresh=False,
                )

        self.assertIsNone(cached_response)
        self.assertEqual(source, "fallback")

    def test_compute_response_reuses_source_cache_until_state_changes(self) -> None:
        service = IntelligenceStateService()
        payload = {"question": "top edges today", "date": "2026-06-10", "limit": 5}
        app = Flask(__name__)

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

            with app.app_context():
                with patch("pipeline.intelligence_state.reports_root", return_value=reports_root):
                    with patch("pipeline.intelligence_state.build_intelligence_status", return_value=base_status):
                        with patch.object(service, "_build_candidate_pool", return_value={"candidate_count": 1, "candidate_pools": {"mlb": [{"candidate_id": "cand-1", "name": "Play 1", "sport": "MLB", "market": "Hits", "score": 91.0}]}, "global_pool": [{"candidate_id": "cand-1", "name": "Play 1", "sport": "MLB", "market": "Hits", "score": 91.0}], "candidates": [{"candidate_id": "cand-1", "name": "Play 1", "sport": "MLB", "market": "Hits", "score": 91.0}]}):
                            with patch("pipeline.intelligence_state._balanced_recommendation_order", return_value=[{"name": "Play 1", "sport": "MLB", "market": "Hits", "score": 91.0}]) as mocked_rank:
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
        self.assertIn("candidate_scoring", logged_stages)
        self.assertIn("response_building", logged_stages)
        self.assertIn("request_total", logged_stages)
        self.assertEqual(mocked_pipeline.call_count, 2)

    def test_persist_locked_writes_dated_board_snapshot_for_wnba_only_response(self) -> None:
        service = IntelligenceStateService()

        response = {
            "ok": True,
            "selected_date": "2026-07-12",
            "state_last_updated": "2026-07-12T20:00:00Z",
            "last_updated": "2026-07-12T20:00:00Z",
            "snapshot_generated_at": "2026-07-12T20:00:00Z",
            "candidate_count": 6,
            "top_opportunities": [
                {"name": f"WNBA Play {index}", "sport": "wnba", "sport_slug": "wnba"}
                for index in range(1, 7)
            ],
            "recommendations": [
                {"name": f"WNBA Play {index}", "sport": "wnba", "sport_slug": "wnba"}
                for index in range(1, 7)
            ],
            "by_sport": {
                "wnba": [
                    {"name": f"WNBA Play {index}", "sport": "wnba", "sport_slug": "wnba"}
                    for index in range(1, 7)
                ]
            },
            "analysis": {
                "recommendations": [
                    {"name": f"WNBA Play {index}", "sport": "wnba", "sport_slug": "wnba"}
                    for index in range(1, 7)
                ],
                "picks": [],
                "top_live_opportunities": [],
                "portfolio": {},
                "parlays": [],
            },
            "board_contract": {
                "schema": "intelligence_board_v1",
                "cards": [
                    {"name": f"WNBA Play {index}", "sport": "wnba", "sport_slug": "wnba"}
                    for index in range(1, 7)
                ],
            },
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            reports_root = Path(tmp_dir) / "reports"
            state_path = reports_root / "intelligence" / "query_state_cache.json"
            board_snapshot_path = reports_root / "intelligence" / "board_snapshot.json"
            daily_board_snapshot_path = reports_root / "intelligence" / "board_snapshot_2026_07_12.json"
            service._snapshots["wnba-key"] = IntelligenceSnapshot(
                key="wnba-key",
                payload={"question": "top edges today", "date": "2026-07-12"},
                response=dict(response),
                computed_at="2026-07-12T20:00:00Z",
                source_fingerprint="fingerprint-wnba-1",
            )
            service._latest_key = "wnba-key"

            with patch("pipeline.intelligence_state.reports_root", return_value=reports_root):
                with patch.object(intelligence_state_module, "STATE_PATH", state_path):
                    with patch.object(intelligence_state_module, "BOARD_SNAPSHOT_PATH", board_snapshot_path):
                        # The daily-suffixed filename is keyed off the actual
                        # current day (_intelligence_state_daily_suffix ->
                        # central_today_iso()), not the response's own
                        # selected_date -- it's a rotation boundary, not a
                        # per-response label. Mock it to match so the dated
                        # path below is deterministic.
                        with patch.object(intelligence_state_module, "central_today_iso", return_value="2026-07-12"):
                            service._persist_locked()

            self.assertTrue(state_path.exists())
            self.assertTrue(board_snapshot_path.exists())
            self.assertTrue(daily_board_snapshot_path.exists())

            written_daily_snapshot = refresh_state_store.read_json_file(daily_board_snapshot_path)
            self.assertIsInstance(written_daily_snapshot, dict)
            self.assertEqual(written_daily_snapshot.get("selected_date"), "2026-07-12")
            self.assertEqual(int(written_daily_snapshot.get("candidate_count") or 0), 6)
            self.assertEqual(int((written_daily_snapshot.get("response") or {}).get("candidate_count") or 0), 6)
            self.assertEqual(sorted((written_daily_snapshot.get("response") or {}).get("by_sport") or {}), ["wnba"])

    def test_persist_locked_does_not_clobber_shared_state_when_local_snapshots_empty(self) -> None:
        # A freshly booted process (a deploy, or gunicorn respawning a
        # crashed/timed-out worker) starts with empty self._snapshots and
        # calls _persist_locked() as part of start()'s boot-time enqueue.
        # Confirmed in production: this wiped a perfectly good board the
        # instant any worker restarted, because the write unconditionally
        # serialized this process's own (empty) view over the shared
        # STATE_PATH another process (refresh-worker) had just populated.
        service = IntelligenceStateService()
        # This process has nothing locally -- the scenario under test.
        self.assertEqual(service._snapshots, {})
        service._latest_key = None

        existing_response = {
            "ok": True,
            "selected_date": "2026-07-24",
            "candidate_count": 161,
            "top_opportunities": [{"name": "Real Play", "sport": "mlb", "sport_slug": "mlb"}],
            "by_sport": {"mlb": [{"name": "Real Play", "sport": "mlb", "sport_slug": "mlb"}]},
            "analysis": {"recommendations": [], "picks": [], "top_live_opportunities": [], "portfolio": {}, "parlays": []},
        }
        existing_state_payload = {
            "latest_key": "mlb-key",
            "updated_at": "2026-07-24T20:11:59Z",
            "watched_payloads": {},
            "pending_keys": {},
            "watched_board_dates": {},
            "snapshots": {
                "mlb-key": {
                    "key": "mlb-key",
                    "payload": {"question": "top edges today", "date": "2026-07-24"},
                    "response": existing_response,
                    "computed_at": "2026-07-24T20:11:59Z",
                    "source_fingerprint": "fingerprint-mlb-1",
                }
            },
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            reports_root = Path(tmp_dir) / "reports"
            state_path = reports_root / "intelligence" / "query_state_cache.json"
            board_snapshot_path = reports_root / "intelligence" / "board_snapshot.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps(existing_state_payload), encoding="utf-8")

            with patch("pipeline.intelligence_state.reports_root", return_value=reports_root):
                with patch.object(intelligence_state_module, "STATE_PATH", state_path):
                    with patch.object(intelligence_state_module, "BOARD_SNAPSHOT_PATH", board_snapshot_path):
                        service._persist_locked()

            written_state = refresh_state_store.read_json_file(state_path)
            self.assertIsInstance(written_state, dict)
            self.assertEqual(written_state.get("latest_key"), "mlb-key")
            self.assertIn("mlb-key", written_state.get("snapshots") or {})
            self.assertEqual(
                (written_state.get("snapshots") or {}).get("mlb-key", {}).get("response", {}).get("candidate_count"),
                161,
            )

            # The preserved snapshot should also still make it through to
            # the board_snapshot pointer file -- not just STATE_PATH.
            written_board_snapshot = refresh_state_store.read_json_file(board_snapshot_path)
            self.assertIsInstance(written_board_snapshot, dict)
            self.assertEqual(written_board_snapshot.get("latest_key"), "mlb-key")

    def test_available_sport_manifests_reads_shared_manifest_without_local_file(self) -> None:
        service = IntelligenceStateService()
        status = {
            "sports": [
                {
                    "slug": "mlb",
                    "name": "MLB",
                    "context_label": "2026-07-04",
                    "data_health": "ready",
                    "active_today": True,
                    "tracked_ready": True,
                    "advanced_ready": True,
                    "advanced_gate": {"ready": True},
                    "data_warnings": [],
                    "artifacts": [],
                    "advanced_inputs": [],
                }
            ]
        }
        manifest = {
            "sport": "mlb",
            "last_updated": "2026-07-04T00:00:00Z",
            "artifact_paths": ["reports/manifests/mlb.json"],
            "status": "complete",
        }

        with patch("pipeline.intelligence_state.build_intelligence_status", return_value=status):
            with patch("pipeline.intelligence_state.read_json_file", return_value=dict(manifest)):
                with patch.object(service, "_artifact_signature", return_value={"path": "reports/manifests/mlb.json", "exists": False, "size": None, "mtime_ns": None}):
                    manifests = service._available_sport_manifests("2026-07-04")

        self.assertIn("mlb", manifests)
        self.assertEqual(manifests["mlb"]["sport"], "mlb")

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
                    with patch("syndicate.features.intelligence.collect_all_recommendations", return_value=[{"name": "Play 1", "sport": "MLB", "market": "Hits", "score": 91.0}]) as mocked_collect:
                        with patch("pipeline.intelligence_state._balanced_recommendation_order", return_value=[{"name": "Play 1", "sport": "MLB", "market": "Hits", "score": 91.0}]) as mocked_rank:
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

        # _background_loop calls _compute_board_publication_response, not
        # run_routed_intelligence_pipeline directly (that's only reachable
        # via _compute_response's synchronous/query path) -- mocking it here
        # keeps this test focused on the loop's queue/persist mechanics
        # rather than candidate-building internals, which are covered
        # separately.
        board_response = {"ok": True, "top_opportunities": [], "by_sport": {}, "analysis": None}
        with patch.object(service, "_compute_board_publication_response", return_value=board_response) as mocked_compute:
            with patch.object(service, "_sync_persisted_queue_locked"):
                with patch("pipeline.intelligence_state.logger.info") as mocked_logger_info:
                    with patch("pipeline.intelligence_state.write_latest_intelligence_state", side_effect=lambda state: fake_write_latest_intelligence_state(state, mocked_logger_info)) as mocked_write:
                        service._background_loop()

        mocked_compute.assert_called_once_with(normalized)
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
                # _build_candidate_pool's overview fallback now calls
                # build_intelligence_overview directly instead of
                # build_intelligence_status (only .get("sports") was ever
                # read from the latter -- see the comment at that call site).
                with patch("pipeline.intelligence_state.build_intelligence_overview", return_value=status["sports"]):
                    with patch(
                        "syndicate.features.intelligence.collect_all_recommendations",
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

    def test_build_candidate_pool_aborts_early_when_memory_critical(self) -> None:
        # Production confirmed: this background thread's memory can spike
        # 350-450MB within a single stage transition, fast enough that the
        # container hits its 2GB OOM limit before print-based diagnostics
        # even reach the log collector. The guard checks real cgroup
        # headroom before each expensive stage and bails to an empty (never
        # cached) pool the moment it's unsafe, rather than letting the OS
        # kill the whole process.
        service = IntelligenceStateService()
        with patch(
            "syndicate.features.shared.memory_observability.memory_headroom_snapshot",
            return_value={"current_mb": 1700.0, "max_mb": 2048.0, "headroom_mb": 348.0, "min_required_mb": 900.0, "sufficient": False},
        ), patch("syndicate.features.shared.artifact_publisher.pull_hot_artifacts") as mocked_pull:
            pool = service._build_candidate_pool("2026-06-10", "fingerprint-1")

        self.assertEqual(pool["candidate_count"], 0)
        self.assertEqual(pool["candidate_pools"], {})
        self.assertEqual(pool["global_pool"], [])
        # Aborted at the very first checkpoint, before any real work started.
        mocked_pull.assert_not_called()
        # Never cached -- a later, healthier cycle must not be poisoned by this one.
        cache_key = service._candidate_pool_key("2026-06-10", "fingerprint-1")
        self.assertNotIn(cache_key, service._candidate_pools)

    def test_build_candidate_pool_does_not_embed_full_odds_history_payload(self) -> None:
        # Confirmed in production as the dominant memory driver once
        # odds-history grew ~100x: this used to load AND embed the entire
        # sport odds-history payload a THIRD time per sport purely to stash
        # it wholesale on the pool -- nothing downstream ever read it back.
        # The other two loads are still legitimate and distinct: one feeds
        # odds_history_by_sport into candidate generation
        # (_odds_history_payloads_by_sport, keyed off context_label), the
        # other attaches small per-candidate odds_history slices after
        # candidates exist (keyed off the manifest/selected_date shard) --
        # so 2 calls per sport is the correct post-fix count, not 1.
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
                # See the matching comment in
                # test_build_candidate_pool_skips_sports_without_manifests --
                # _build_candidate_pool's overview fallback now calls
                # build_intelligence_overview directly.
                with patch("pipeline.intelligence_state.build_intelligence_overview", return_value=status["sports"]):
                    with patch(
                        "syndicate.features.intelligence.collect_all_recommendations",
                        return_value=[{"name": "MLB Play", "sport": "MLB", "market": "Hits", "score": 91.0}],
                    ):
                        with patch(
                            "pipeline.intelligence_state.load_odds_history_payload_for_sport",
                            return_value={"markets": {}},
                        ) as mocked_loader:
                            pool = service._build_candidate_pool("2026-06-10", "fingerprint-1")

        self.assertEqual(mocked_loader.call_count, 2)
        mlb_pool = pool["candidate_pools"]["mlb"]
        self.assertNotIn("odds_history", mlb_pool)
        self.assertIn("odds_history_shard_key", mlb_pool)

    def test_every_configured_sport_ships_a_committed_baseline_manifest(self) -> None:
        # Real bug found in production: reports/manifests/soccer.json was
        # never committed (unlike the other 6 sport manifests), so on a
        # fresh checkout/redeploy it simply didn't exist until the first
        # fully-successful soccer refresh recreated it. Meanwhile
        # _available_sport_manifests (see
        # test_build_candidate_pool_skips_sports_without_manifests above)
        # silently drops any sport whose manifest file doesn't exist --
        # so soccer produced real candidates internally but they never
        # survived into the published board, with no error anywhere.
        # A committed baseline (however stale) means this gate always has
        # something to read, even before the first refresh completes.
        repo_root = Path(__file__).resolve().parents[1]
        app = create_app()
        configured_sports = app.config.get("SYNDICATE_SPORTS", [])
        slugs = sorted({str(sport.get("slug") or "").strip().lower() for sport in configured_sports if isinstance(sport, dict) and sport.get("slug")})
        self.assertIn("soccer", slugs)
        for slug in slugs:
            manifest_path = repo_root / "reports" / "manifests" / f"{slug}.json"
            with self.subTest(slug=slug):
                self.assertTrue(manifest_path.exists(), f"missing committed baseline manifest: {manifest_path}")
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                self.assertEqual(payload.get("sport"), slug)

    def test_collect_candidates_with_fallback_merge_falls_back_on_empty_pool(self) -> None:
        # Fallback result has >= 20 rows so it isn't itself "thin" and
        # doesn't trigger the separate thin-pool merge check below --
        # keeps this test focused on the empty-pool fallback specifically.
        richer_pool = [{"name": f"Richer Play {i}", "sport": "mlb"} for i in range(20)]
        with patch("syndicate.features.intelligence.collect_candidates", return_value=[]), patch(
            "syndicate.features.intelligence.collect_all_recommendations",
            return_value=richer_pool,
        ) as mocked_richer:
            result = collect_candidates_with_fallback_merge(
                overview=[], preferences={}, odds_history_by_sport={}, selected_date="2026-06-10"
            )

        mocked_richer.assert_called_once_with(selected_date="2026-06-10", force_refresh=True, log_pipeline=False, overview=[])
        self.assertEqual(result, richer_pool)

    def test_collect_candidates_with_fallback_merge_unions_thin_pool_with_richer_pool(self) -> None:
        # A non-empty but thin primary pool (< 20) must not permanently skip
        # the richer fallback -- confirmed live 2026-07-21 that a thin
        # result can hide much richer coverage the fallback pipeline finds.
        primary = [{"name": "Primary MLB", "sport": "mlb", "candidate_type": "prop"}]
        richer = [
            {"name": "Primary MLB", "sport": "mlb", "candidate_type": "prop"},
            {"name": "Richer WNBA", "sport": "wnba", "candidate_type": "prop"},
        ]
        with patch("syndicate.features.intelligence.collect_candidates", return_value=primary), patch(
            "syndicate.features.intelligence.collect_all_recommendations", return_value=richer
        ):
            result = collect_candidates_with_fallback_merge(
                overview=[],
                preferences={},
                odds_history_by_sport={},
                selected_date="2026-06-10",
                apply_edge_filter=False,
            )

        names = {candidate["name"] for candidate in result}
        self.assertEqual(names, {"Primary MLB", "Richer WNBA"})
        # Union by identity, not concatenation -- the candidate present in
        # both pools must survive exactly once.
        self.assertEqual(len(result), 2)

    def test_collect_candidates_with_fallback_merge_skips_edge_filter_when_disabled(self) -> None:
        # run_intelligence_query already runs its own _score_candidates()/
        # filter_candidates() downstream -- apply_edge_filter=False must not
        # double-gate by also running them here.
        primary = [{"name": f"Play {i}", "sport": "mlb"} for i in range(25)]
        with patch("syndicate.features.intelligence.collect_candidates", return_value=primary), patch(
            "syndicate.features.intelligence._score_candidates"
        ) as mocked_score, patch("syndicate.features.intelligence.filter_candidates") as mocked_filter:
            result = collect_candidates_with_fallback_merge(
                overview=[], preferences={}, odds_history_by_sport={}, selected_date="2026-06-10", apply_edge_filter=False
            )

        mocked_score.assert_not_called()
        mocked_filter.assert_not_called()
        self.assertEqual(len(result), 25)

    def test_candidate_identity_key_matches_service_delegate(self) -> None:
        candidate = {"sport_slug": "mlb", "candidate_type": "prop", "market_key": "hits", "selection": "over"}
        self.assertEqual(IntelligenceStateService()._candidate_id(candidate), candidate_identity_key(candidate))

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

    def test_intelligence_board_state_round_trip_by_date(self) -> None:
        state = {
            "selected_date": "2026-06-10",
            "source_fingerprint": "fingerprint-1",
            "candidate_count": 1,
            "covered_sports": ["mlb"],
            "by_sport": {"mlb": [{"name": "Play 1"}]},
            "ranked_all": [{"name": "Play 1"}],
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.object(intelligence_state_module, "reports_root", return_value=Path(tmp_dir)):
                written = write_intelligence_board_state(dict(state))
                self.assertEqual(written, state)

                by_date = read_intelligence_board_state("2026-06-10")
                self.assertEqual(by_date, state)

                latest = read_latest_intelligence_board_state()
                self.assertEqual(latest, state)

    def test_read_latest_intelligence_board_state_falls_back_to_today_without_pointer(self) -> None:
        state = {"selected_date": "2026-07-04", "candidate_count": 0, "covered_sports": [], "by_sport": {}, "ranked_all": []}

        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.object(intelligence_state_module, "reports_root", return_value=Path(tmp_dir)):
                # Write the dated file directly, skipping write_intelligence_board_state
                # so the pointer file never gets created -- simulates a
                # pointer that's missing/lost while the dated artifact itself
                # still exists.
                daily_path = intelligence_state_module._intelligence_board_state_path("2026-07-04")
                daily_path.parent.mkdir(parents=True, exist_ok=True)
                refresh_state_store.write_json_file(daily_path, state)

                with patch.object(intelligence_state_module, "central_today_iso", return_value="2026-07-04"):
                    latest = read_latest_intelligence_board_state()

        self.assertEqual(latest, state)

    def test_slice_intelligence_board_state_for_request_scopes_by_sport_and_limit(self) -> None:
        state = {
            "selected_date": "2026-06-10",
            "by_sport": {
                "mlb": [{"name": "MLB Play 1"}, {"name": "MLB Play 2"}],
                "wnba": [{"name": "WNBA Play 1"}],
            },
            "ranked_all": [{"name": "MLB Play 1"}, {"name": "WNBA Play 1"}, {"name": "MLB Play 2"}],
        }

        sliced_all = slice_intelligence_board_state_for_request(state, sport="all", limit=None)
        self.assertEqual([item["name"] for item in sliced_all["top_opportunities"]], ["MLB Play 1", "WNBA Play 1", "MLB Play 2"])

        sliced_mlb_limited = slice_intelligence_board_state_for_request(state, sport="mlb", limit=1)
        self.assertEqual([item["name"] for item in sliced_mlb_limited["top_opportunities"]], ["MLB Play 1"])
        # The canonical state itself (by_sport/ranked_all) must survive
        # unsliced in the returned dict -- only top_opportunities/
        # recommendations are the request-scoped view.
        self.assertEqual(sliced_mlb_limited["by_sport"], state["by_sport"])

        sliced_missing_sport = slice_intelligence_board_state_for_request(state, sport="nhl", limit=None)
        self.assertEqual(sliced_missing_sport["top_opportunities"], [])

    def test_build_intelligence_board_state_widens_by_sport_to_zero_candidate_sports(self) -> None:
        service = IntelligenceStateService()
        base_response = {
            "selected_date": "2026-06-10",
            "candidate_count": 1,
            "by_sport": {"mlb": [{"name": "MLB Play"}]},
            "top_opportunities": [{"name": "MLB Play"}],
            "board_contract": {"schema": "intelligence_board_v1"},
            "live_pipeline": {},
            "state_meta": {"freshness_status": "fresh"},
        }

        with patch.object(service, "_compute_board_publication_response", return_value=base_response):
            with patch.object(service, "_available_sport_manifests", return_value={"mlb": {}, "wnba": {}}):
                with patch.object(service, "_source_state_fingerprint", return_value="fingerprint-1"):
                    state = service._build_intelligence_board_state("2026-06-10")

        self.assertEqual(state["covered_sports"], ["mlb", "wnba"])
        self.assertEqual(state["by_sport"]["mlb"], [{"name": "MLB Play"}])
        # wnba produced zero candidates but must still be present as an
        # explicit empty list -- the whole point of covered_sports/by_sport
        # widening is to stop callers from having to guess whether an absent
        # key means "zero candidates" or "this sport wasn't considered at all".
        self.assertEqual(state["by_sport"]["wnba"], [])
        self.assertEqual(state["ranked_all"], [{"name": "MLB Play"}])
        self.assertEqual(state["candidate_count"], 1)

    def test_queue_board_state_refresh_collapses_repeated_calls_for_same_date(self) -> None:
        service = IntelligenceStateService()

        first_key = service.queue_board_state_refresh("2026-06-10")
        second_key = service.queue_board_state_refresh("2026-06-10")

        self.assertEqual(first_key, "2026-06-10")
        self.assertEqual(second_key, "2026-06-10")
        self.assertEqual(list(service._watched_board_dates), ["2026-06-10"])

    def test_queue_board_state_refresh_defaults_to_today_when_date_missing(self) -> None:
        service = IntelligenceStateService()

        with patch.object(intelligence_state_module, "central_today_iso", return_value="2026-07-04"):
            queued = service.queue_board_state_refresh(None)

        self.assertEqual(queued, "2026-07-04")
        self.assertEqual(list(service._watched_board_dates), ["2026-07-04"])

    def test_drain_one_watched_board_date_writes_state_and_empties_queue(self) -> None:
        service = IntelligenceStateService()
        service.queue_board_state_refresh("2026-06-10")
        built_state = {"selected_date": "2026-06-10", "candidate_count": 2, "covered_sports": ["mlb"], "by_sport": {"mlb": []}, "ranked_all": []}

        with patch.object(service, "_build_intelligence_board_state", return_value=built_state) as mocked_build:
            with patch("pipeline.intelligence_state.write_intelligence_board_state") as mocked_write:
                service._drain_one_watched_board_date()

        mocked_build.assert_called_once_with("2026-06-10")
        mocked_write.assert_called_once_with(built_state)
        self.assertEqual(list(service._watched_board_dates), [])

    def test_drain_one_watched_board_date_is_noop_when_queue_empty(self) -> None:
        service = IntelligenceStateService()

        with patch.object(service, "_build_intelligence_board_state") as mocked_build:
            service._drain_one_watched_board_date()

        mocked_build.assert_not_called()

    def test_drain_one_watched_board_date_swallows_build_failures(self) -> None:
        service = IntelligenceStateService()
        service.queue_board_state_refresh("2026-06-10")

        with patch.object(service, "_build_intelligence_board_state", side_effect=RuntimeError("boom")):
            # Must not raise -- the background loop calls this every
            # iteration and a bad cycle should just be retried later, not
            # crash the whole worker thread.
            service._drain_one_watched_board_date()

        self.assertEqual(list(service._watched_board_dates), [])

    def test_background_loop_drains_board_dates_when_canonical_flag_enabled(self) -> None:
        service = IntelligenceStateService()
        service._interval_seconds = 0

        def stop_after_one_iteration(*args: object, **kwargs: object) -> None:
            service._stop.set()

        with patch.object(intelligence_state_module, "canonical_board_state_enabled", return_value=True):
            with patch.object(service, "_drain_one_watched_board_date_async") as mocked_drain:
                with patch.object(service, "_sync_persisted_queue_locked", side_effect=stop_after_one_iteration):
                    service._background_loop()

        mocked_drain.assert_called_once()

    def test_background_loop_drains_board_dates_when_only_shadow_compare_enabled(self) -> None:
        # Confirmed live 2026-07-22: with only shadow-compare on (not the
        # full serving flag), dates were queued (the queue side already
        # checked either flag) but never drained here, since this gate used
        # to check only the serving flag -- shadow-compare could never see
        # anything but "canonical_miss" as a result.
        service = IntelligenceStateService()
        service._interval_seconds = 0

        def stop_after_one_iteration(*args: object, **kwargs: object) -> None:
            service._stop.set()

        with patch.object(intelligence_state_module, "canonical_board_state_enabled", return_value=False):
            with patch.object(intelligence_state_module, "canonical_board_state_shadow_compare_enabled", return_value=True):
                with patch.object(service, "_drain_one_watched_board_date_async") as mocked_drain:
                    with patch.object(service, "_sync_persisted_queue_locked", side_effect=stop_after_one_iteration):
                        service._background_loop()

        mocked_drain.assert_called_once()

    def test_background_loop_skips_board_date_drain_when_flag_disabled(self) -> None:
        service = IntelligenceStateService()
        service._interval_seconds = 0

        def stop_after_one_iteration(*args: object, **kwargs: object) -> None:
            service._stop.set()

        with patch.object(intelligence_state_module, "canonical_board_state_enabled", return_value=False):
            with patch.object(intelligence_state_module, "canonical_board_state_shadow_compare_enabled", return_value=False):
                with patch.object(service, "_drain_one_watched_board_date_async") as mocked_drain:
                    with patch.object(service, "_sync_persisted_queue_locked", side_effect=stop_after_one_iteration):
                        service._background_loop()

        mocked_drain.assert_not_called()

    def test_load_canonical_board_response_returns_none_when_flag_disabled(self) -> None:
        with patch("syndicate.blueprints.intelligence.canonical_board_state_enabled", return_value=False):
            with patch("syndicate.blueprints.intelligence.read_intelligence_board_state") as mocked_read:
                response, source = intelligence_module._load_canonical_board_response({"date": "2026-06-10"})

        self.assertIsNone(response)
        self.assertEqual(source, "canonical_disabled")
        mocked_read.assert_not_called()

    def test_load_canonical_board_response_misses_when_state_absent(self) -> None:
        with patch("syndicate.blueprints.intelligence.canonical_board_state_enabled", return_value=True):
            with patch("syndicate.blueprints.intelligence.read_intelligence_board_state", return_value=None):
                response, source = intelligence_module._load_canonical_board_response({"date": "2026-06-10"})

        self.assertIsNone(response)
        self.assertEqual(source, "canonical_miss")

    def test_load_canonical_board_response_misses_when_sport_not_covered(self) -> None:
        state = {
            "selected_date": "2026-06-10",
            "candidate_count": 3,
            "covered_sports": ["mlb"],
            "by_sport": {"mlb": [{"name": "MLB Play"}]},
            "ranked_all": [{"name": "MLB Play"}],
        }
        with patch("syndicate.blueprints.intelligence.canonical_board_state_enabled", return_value=True):
            with patch("syndicate.blueprints.intelligence.read_intelligence_board_state", return_value=state):
                response, source = intelligence_module._load_canonical_board_response({"date": "2026-06-10", "sport": "wnba"})

        self.assertIsNone(response)
        self.assertEqual(source, "canonical_miss")

    def test_load_canonical_board_response_returns_sliced_response_for_covered_sport(self) -> None:
        state = {
            "selected_date": "2026-06-10",
            "candidate_count": 2,
            "covered_sports": ["mlb", "wnba"],
            "by_sport": {
                "mlb": [{"name": "MLB Play"}],
                "wnba": [{"name": "WNBA Play"}],
            },
            "ranked_all": [{"name": "MLB Play"}, {"name": "WNBA Play"}],
            "board_contract": {"schema": "intelligence_board_v1"},
        }
        with patch("syndicate.blueprints.intelligence.canonical_board_state_enabled", return_value=True):
            with patch("syndicate.blueprints.intelligence.read_intelligence_board_state", return_value=state):
                response, source = intelligence_module._load_canonical_board_response({"date": "2026-06-10", "sport": "wnba"})

        self.assertEqual(source, "canonical_board_state")
        self.assertIsNotNone(response)
        self.assertEqual(response.get("selected_date"), "2026-06-10")
        self.assertEqual([item["name"] for item in response.get("top_opportunities", [])], ["WNBA Play"])

    def test_load_canonical_board_response_uses_latest_state_when_no_date_requested(self) -> None:
        state = {
            "selected_date": "2026-06-10",
            "candidate_count": 1,
            "covered_sports": ["mlb"],
            "by_sport": {"mlb": [{"name": "MLB Play"}]},
            "ranked_all": [{"name": "MLB Play"}],
        }
        with patch("syndicate.blueprints.intelligence.canonical_board_state_enabled", return_value=True):
            with patch("syndicate.blueprints.intelligence.read_intelligence_board_state") as mocked_read_dated:
                with patch("syndicate.blueprints.intelligence.read_latest_intelligence_board_state", return_value=state) as mocked_read_latest:
                    response, source = intelligence_module._load_canonical_board_response({"question": "top edges today"})

        mocked_read_dated.assert_not_called()
        mocked_read_latest.assert_called_once()
        self.assertEqual(source, "canonical_board_state")
        self.assertEqual(response.get("selected_date"), "2026-06-10")

    def test_cached_intelligence_response_prefers_fresh_canonical_state_over_legacy_cascade(self) -> None:
        payload = {"question": "top edges today", "date": "2026-06-10", "sport": "mlb"}
        canonical_state = {
            "selected_date": "2026-06-10",
            "candidate_count": 1,
            "covered_sports": ["mlb"],
            "by_sport": {"mlb": [{"name": "Canonical MLB Play"}]},
            "ranked_all": [{"name": "Canonical MLB Play"}],
        }

        with patch("syndicate.blueprints.intelligence.canonical_board_state_enabled", return_value=True):
            with patch("syndicate.blueprints.intelligence.read_intelligence_board_state", return_value=canonical_state):
                with patch("syndicate.blueprints.intelligence._response_needs_refresh", return_value=False):
                    with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state_response") as mocked_legacy_state:
                        with patch("syndicate.blueprints.intelligence.read_latest_intelligence_board_snapshot_response") as mocked_legacy_snapshot:
                            cached_response, source = intelligence_module._cached_intelligence_response_with_source(payload)

        self.assertEqual(source, "canonical_board_state")
        self.assertEqual(cached_response.get("top_opportunities", [])[0]["name"], "Canonical MLB Play")
        # A fresh canonical hit must short-circuit before ever touching the
        # legacy cascade's own reads.
        mocked_legacy_state.assert_not_called()
        mocked_legacy_snapshot.assert_not_called()

    def test_cached_intelligence_response_falls_back_to_legacy_cascade_when_canonical_is_stale(self) -> None:
        payload = {"question": "top edges today", "date": "2026-06-10", "sport": "mlb"}
        canonical_state = {
            "selected_date": "2026-06-10",
            "candidate_count": 1,
            "covered_sports": ["mlb"],
            "by_sport": {"mlb": [{"name": "Stale Canonical MLB Play"}]},
            "ranked_all": [{"name": "Stale Canonical MLB Play"}],
        }
        legacy_worker_response = {
            "ok": True,
            "selected_date": "2026-06-10",
            "last_updated": "2026-06-10T18:40:54Z",
            "top_opportunities": [{"name": "Legacy Fresh Play"}],
            "analysis": {"recommendations": [{"name": "Legacy Fresh Play"}], "picks": [], "top_live_opportunities": [], "portfolio": {}, "parlays": []},
        }

        def needs_refresh_side_effect(request_payload: dict[str, object], response_payload: dict[str, object] | None) -> bool:
            # Only the canonical response (identified by its distinct play
            # name) is treated as stale -- the legacy worker response below
            # should be accepted as fresh once the fallback reaches it.
            top_opportunities = (response_payload or {}).get("top_opportunities") or []
            names = {item.get("name") for item in top_opportunities if isinstance(item, dict)}
            return "Stale Canonical MLB Play" in names

        with patch("syndicate.blueprints.intelligence.canonical_board_state_enabled", return_value=True):
            with patch("syndicate.blueprints.intelligence.read_intelligence_board_state", return_value=canonical_state):
                with patch("syndicate.blueprints.intelligence._response_needs_refresh", side_effect=needs_refresh_side_effect):
                    with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state_response", return_value=dict(legacy_worker_response)):
                        with patch("syndicate.blueprints.intelligence.read_latest_intelligence_board_snapshot_response", return_value=None):
                            cached_response, source = intelligence_module._cached_intelligence_response_with_source(payload)

        self.assertEqual(source, "worker")
        self.assertEqual(cached_response.get("top_opportunities", [])[0]["name"], "Legacy Fresh Play")

    def test_safe_queue_intelligence_state_refresh_also_queues_board_state_when_canonical_enabled(self) -> None:
        # Without this, _background_loop's canonical-state drain never has
        # anything queued to write -- _watched_board_dates would stay empty
        # forever regardless of the serving/shadow-compare flags, since
        # nothing else in the codebase calls queue_board_state_refresh.
        with patch("syndicate.blueprints.intelligence.canonical_board_state_enabled", return_value=True):
            with patch("syndicate.blueprints.intelligence.queue_intelligence_state_refresh"):
                with patch("syndicate.blueprints.intelligence.queue_board_state_refresh") as mocked_queue_board_state:
                    intelligence_module._safe_queue_intelligence_state_refresh({"date": "2026-06-10", "question": "top edges today"})

        mocked_queue_board_state.assert_called_once_with("2026-06-10")

    def test_safe_queue_intelligence_state_refresh_skips_board_state_when_both_flags_disabled(self) -> None:
        with patch("syndicate.blueprints.intelligence.canonical_board_state_enabled", return_value=False):
            with patch("syndicate.blueprints.intelligence.canonical_board_state_shadow_compare_enabled", return_value=False):
                with patch("syndicate.blueprints.intelligence.queue_intelligence_state_refresh"):
                    with patch("syndicate.blueprints.intelligence.queue_board_state_refresh") as mocked_queue_board_state:
                        intelligence_module._safe_queue_intelligence_state_refresh({"date": "2026-06-10"})

        mocked_queue_board_state.assert_not_called()

    def test_safe_queue_intelligence_state_refresh_swallows_board_state_queue_failure(self) -> None:
        with patch("syndicate.blueprints.intelligence.canonical_board_state_enabled", return_value=True):
            with patch("syndicate.blueprints.intelligence.queue_intelligence_state_refresh"):
                with patch("syndicate.blueprints.intelligence.queue_board_state_refresh", side_effect=RuntimeError("boom")):
                    # Must not raise -- this is a best-effort side channel,
                    # same discipline as the existing legacy queue call above it.
                    intelligence_module._safe_queue_intelligence_state_refresh({"date": "2026-06-10"})

    def test_load_canonical_board_response_computes_when_only_shadow_compare_enabled(self) -> None:
        # The serving flag is off, but shadow-compare alone must still be
        # enough to trigger the canonical read -- otherwise there would be
        # nothing to compare against during the validation window.
        with patch("syndicate.blueprints.intelligence.canonical_board_state_enabled", return_value=False):
            with patch("syndicate.blueprints.intelligence.canonical_board_state_shadow_compare_enabled", return_value=True):
                with patch("syndicate.blueprints.intelligence.read_intelligence_board_state", return_value=None) as mocked_read:
                    intelligence_module._load_canonical_board_response({"date": "2026-06-10"})

        mocked_read.assert_called_once()

    def test_load_canonical_board_response_stays_disabled_when_both_flags_off(self) -> None:
        with patch("syndicate.blueprints.intelligence.canonical_board_state_enabled", return_value=False):
            with patch("syndicate.blueprints.intelligence.canonical_board_state_shadow_compare_enabled", return_value=False):
                with patch("syndicate.blueprints.intelligence.read_intelligence_board_state") as mocked_read:
                    response, source = intelligence_module._load_canonical_board_response({"date": "2026-06-10"})

        self.assertIsNone(response)
        self.assertEqual(source, "canonical_disabled")
        mocked_read.assert_not_called()

    def test_cached_intelligence_response_logs_shadow_diff_without_changing_what_is_served(self) -> None:
        payload = {"question": "top edges today", "date": "2026-06-10", "sport": "mlb"}
        canonical_state = {
            "selected_date": "2026-06-10",
            "candidate_count": 1,
            "covered_sports": ["mlb"],
            "by_sport": {"mlb": [{"name": "Canonical Only Play"}]},
            "ranked_all": [{"name": "Canonical Only Play"}],
        }
        legacy_worker_response = {
            "ok": True,
            "selected_date": "2026-06-10",
            "last_updated": "2026-06-10T18:40:54Z",
            "top_opportunities": [{"name": "Legacy Only Play"}],
            "analysis": {"recommendations": [{"name": "Legacy Only Play"}], "picks": [], "top_live_opportunities": [], "portfolio": {}, "parlays": []},
        }

        with patch("syndicate.blueprints.intelligence.canonical_board_state_enabled", return_value=False):
            with patch("syndicate.blueprints.intelligence.canonical_board_state_shadow_compare_enabled", return_value=True):
                with patch("syndicate.blueprints.intelligence.read_intelligence_board_state", return_value=canonical_state):
                    with patch("syndicate.blueprints.intelligence._response_needs_refresh", return_value=False):
                        with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state_response", return_value=dict(legacy_worker_response)):
                            with patch("syndicate.blueprints.intelligence.read_latest_intelligence_board_snapshot_response", return_value=None):
                                with patch("syndicate.blueprints.intelligence._LOGGER.info") as mocked_log_info:
                                    cached_response, source = intelligence_module._cached_intelligence_response_with_source(payload)

        # The serving flag is off, so the legacy cascade's result must still
        # be what's actually returned -- shadow-compare only observes.
        self.assertEqual(source, "worker")
        self.assertEqual(cached_response.get("top_opportunities", [])[0]["name"], "Legacy Only Play")

        shadow_diff_calls = [call for call in mocked_log_info.call_args_list if call.args and call.args[0] == "CANONICAL_BOARD_STATE_SHADOW_DIFF"]
        self.assertEqual(len(shadow_diff_calls), 1)
        diff_extra = shadow_diff_calls[0].kwargs["extra"]
        self.assertEqual(diff_extra["canonical_source"], "canonical_board_state")
        self.assertEqual(diff_extra["served_source"], "worker")
        self.assertFalse(diff_extra["served_is_canonical"])
        self.assertEqual(diff_extra["names_only_in_canonical"], ["Canonical Only Play"])
        self.assertEqual(diff_extra["names_only_in_served"], ["Legacy Only Play"])

    def test_cached_intelligence_response_skips_shadow_diff_when_both_flags_disabled(self) -> None:
        payload = {"question": "top edges today", "date": "2026-06-10"}
        with patch("syndicate.blueprints.intelligence.canonical_board_state_enabled", return_value=False):
            with patch("syndicate.blueprints.intelligence.canonical_board_state_shadow_compare_enabled", return_value=False):
                with patch("syndicate.blueprints.intelligence.read_latest_intelligence_state_response", return_value=None):
                    with patch("syndicate.blueprints.intelligence.read_latest_intelligence_board_snapshot_response", return_value=None):
                        with patch("syndicate.blueprints.intelligence._LOGGER.info") as mocked_log_info:
                            intelligence_module._cached_intelligence_response_with_source(payload)

        shadow_diff_calls = [call for call in mocked_log_info.call_args_list if call.args and call.args[0] == "CANONICAL_BOARD_STATE_SHADOW_DIFF"]
        self.assertEqual(shadow_diff_calls, [])

    def test_log_canonical_board_state_shadow_diff_swallows_exceptions(self) -> None:
        # A malformed response (not a Mapping-like get()) must never let a
        # logging bug escape into the real request path.
        with patch("syndicate.blueprints.intelligence._LOGGER.info", side_effect=RuntimeError("boom")):
            with patch("syndicate.blueprints.intelligence._LOGGER.exception") as mocked_log_exception:
                intelligence_module._log_canonical_board_state_shadow_diff(
                    {"date": "2026-06-10"},
                    canonical_response={"top_opportunities": [{"name": "A"}]},
                    canonical_source="canonical_board_state",
                    served_response={"top_opportunities": [{"name": "B"}]},
                    served_source="worker",
                )

        mocked_log_exception.assert_called_once()


class WatchedPayloadEvictionTests(unittest.TestCase):
    """Layer 2 went fully empty on 2026-07-25 because _watched_payloads
    survives restarts and _background_loop re-queues any stale-snapshot
    entry forever. A payload still dated 2026-07-24 recomputed against
    rolled-over artifacts, produced zero candidates, and clobbered
    _latest_key with that empty response -- every sport reported
    context_label 2026-07-24 and generated=0 in ~0.004ms while MLB had 15
    games and a fresh sim that day.
    """

    def _reason(self, payload, today="2026-07-25"):
        return intelligence_state_module._watched_payload_eviction_reason(payload, today)

    def test_evicts_payload_dated_before_today(self) -> None:
        self.assertEqual(
            self._reason({"question": "top edges today", "date": "2026-07-24"}),
            "stale_date:2026-07-24",
        )

    def test_evicts_via_selected_date_alias(self) -> None:
        self.assertEqual(
            self._reason({"question": "top edges today", "selected_date": "2026-07-01"}),
            "stale_date:2026-07-01",
        )

    def test_keeps_todays_payload(self) -> None:
        self.assertIsNone(self._reason({"question": "top edges today", "date": "2026-07-25"}))

    def test_keeps_future_dated_lookahead_payload(self) -> None:
        # A future date is a real look-ahead request, not a stale replay.
        self.assertIsNone(self._reason({"question": "top edges today", "date": "2026-07-26"}))

    def test_keeps_undated_payload(self) -> None:
        # The undated payload is the legitimate "today" default that
        # get_latest_intelligence_cached_response constructs.
        self.assertIsNone(self._reason({"question": "top edges today"}))

    def test_keeps_payload_with_unparseable_date(self) -> None:
        # Never evict on a value we cannot order against today -- dropping a
        # payload is destructive, so ambiguity must fail safe toward keeping.
        self.assertIsNone(self._reason({"question": "q", "date": "garbage"}))

    def test_keeps_payload_with_datetime_shaped_date(self) -> None:
        # date.fromisoformat accepts fuller ISO forms on 3.11, but the value
        # would no longer be lexicographically comparable to a bare
        # YYYY-MM-DD, so the length guard must reject it.
        self.assertIsNone(self._reason({"question": "q", "date": "2026-07-24T00:00:00"}))

    def test_still_evicts_stale_limit_payload(self) -> None:
        # Pre-existing behavior this refactor must not regress.
        self.assertEqual(self._reason({"question": "q", "limit": 10}), "stale_limit")

    def test_limit_eviction_wins_over_date_for_a_payload_with_both(self) -> None:
        self.assertEqual(self._reason({"question": "q", "limit": 10, "date": "2026-07-24"}), "stale_limit")

    def test_handles_none_payload(self) -> None:
        self.assertIsNone(self._reason(None))

    def test_is_iso_date_only_guards(self) -> None:
        checker = intelligence_state_module._is_iso_date_only
        self.assertTrue(checker("2026-07-25"))
        self.assertFalse(checker("2026-7-25"))
        self.assertFalse(checker("2026-07-25T00:00:00"))
        self.assertFalse(checker("2026-13-45"))
        self.assertFalse(checker(""))
        self.assertFalse(checker(None))


class DeferToMlbSimTests(unittest.TestCase):
    """#55: the MLB sim (~1.1GB) and this pipeline both live on
    refresh-worker and together exceed the 2GB container. On 2026-07-25 that
    was an OOM crash loop -- the sim fires ~5s after every boot inside the
    tip-off window while the board build is already running, and the instance
    died about once a minute until the sim trigger was disabled entirely.

    The bound must be pipeline-yields-to-sim, not the reverse: the sim runs
    ~15 minutes while this loop wakes every ~60s, so avoiding a simultaneous
    START just moves the collision a minute later.
    """

    def test_defers_while_a_sim_subprocess_is_resident(self) -> None:
        with patch(
            "syndicate.features.shared.live_refresh_loop._mlb_daily_sim_process_still_running",
            return_value=True,
        ):
            self.assertTrue(intelligence_state_module._mlb_sim_subprocess_running())

    def test_does_not_defer_when_no_sim_is_running(self) -> None:
        with patch(
            "syndicate.features.shared.live_refresh_loop._mlb_daily_sim_process_still_running",
            return_value=False,
        ):
            self.assertFalse(intelligence_state_module._mlb_sim_subprocess_running())

    def test_can_be_disabled_by_env(self) -> None:
        # Escape hatch: if deference ever starves the board, it must be
        # switchable without a deploy.
        with patch.dict(os.environ, {"SYNDICATE_INTELLIGENCE_DEFER_TO_MLB_SIM": "false"}, clear=False):
            with patch(
                "syndicate.features.shared.live_refresh_loop._mlb_daily_sim_process_still_running",
                return_value=True,
            ):
                self.assertFalse(intelligence_state_module._mlb_sim_subprocess_running())

    def test_enabled_by_default(self) -> None:
        # This is the fix, so it must be on unless explicitly turned off.
        for value in ("", None):
            with patch.dict(os.environ, {} if value is None else {"SYNDICATE_INTELLIGENCE_DEFER_TO_MLB_SIM": ""}, clear=False):
                os.environ.pop("SYNDICATE_INTELLIGENCE_DEFER_TO_MLB_SIM", None)
                self.assertTrue(intelligence_state_module._defer_to_mlb_sim_enabled())

    def test_a_broken_sim_check_never_stops_the_board(self) -> None:
        # Instrumentation must not be able to break the thing it guards: if
        # the check raises, the pipeline should run, not stall forever.
        with patch(
            "syndicate.features.shared.live_refresh_loop._mlb_daily_sim_process_still_running",
            side_effect=RuntimeError("boom"),
        ):
            self.assertFalse(intelligence_state_module._mlb_sim_subprocess_running())


class DeferToOddsRefreshTests(unittest.TestCase):
    """#57: the board build is moving to live-odds-worker, whose own hazard
    differs from refresh-worker's -- its odds refresh can spawn WNBA SmartSim
    and is documented spiking to ~1.3-1.5GB in the same 2048MB container.
    Stacking the board build on that would relocate the 2026-07-25 outage
    rather than fix it.
    """

    def test_defers_while_an_odds_refresh_is_in_flight_when_enabled(self) -> None:
        # Explicitly enabled: the default is now off (see
        # test_disabled_by_default_after_the_4gb_upgrade).
        with patch.dict(os.environ, {"SYNDICATE_INTELLIGENCE_DEFER_TO_ODDS_REFRESH": "true"}, clear=False):
            with patch("syndicate.features.shared.ops_refresh.is_refresh_run_active", return_value=True):
                self.assertTrue(intelligence_state_module._odds_refresh_in_flight())

    def test_does_not_defer_when_no_refresh_is_running(self) -> None:
        with patch("syndicate.features.shared.ops_refresh.is_refresh_run_active", return_value=False):
            self.assertFalse(intelligence_state_module._odds_refresh_in_flight())

    def test_can_be_disabled_by_env(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_INTELLIGENCE_DEFER_TO_ODDS_REFRESH": "false"}, clear=False):
            with patch("syndicate.features.shared.ops_refresh.is_refresh_run_active", return_value=True):
                self.assertFalse(intelligence_state_module._odds_refresh_in_flight())

    def test_disabled_by_default_after_the_4gb_upgrade(self) -> None:
        # This branch existed only to survive the board build sharing a 2GB
        # box with its own odds refresh, and it starved the board completely
        # before it was bounded. At 4GB the arithmetic no longer justifies it
        # (~1479MB board + ~532MB refresh tree ~= 2.0GB). Kept, but off.
        os.environ.pop("SYNDICATE_INTELLIGENCE_DEFER_TO_ODDS_REFRESH", None)
        with patch("syndicate.features.shared.ops_refresh.is_refresh_run_active", return_value=True):
            self.assertFalse(intelligence_state_module._odds_refresh_in_flight())

    def test_can_be_re_enabled_by_env(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_INTELLIGENCE_DEFER_TO_ODDS_REFRESH": "true"}, clear=False):
            with patch("syndicate.features.shared.ops_refresh.is_refresh_run_active", return_value=True):
                self.assertTrue(intelligence_state_module._odds_refresh_in_flight())

    def test_a_broken_check_never_stalls_the_board(self) -> None:
        # A false positive would stall the board indefinitely, which is worse
        # than the occasional stacking that happens today anyway.
        with patch("syndicate.features.shared.ops_refresh.is_refresh_run_active", side_effect=RuntimeError("boom")):
            self.assertFalse(intelligence_state_module._odds_refresh_in_flight())


class BoardBuildDeferralBoundTests(unittest.TestCase):
    """The two hazards are not symmetric, and treating them as if they were
    took the board down on 2026-07-25 after it moved to live-odds-worker.

    An MLB sim is finite (~15 min), so waiting for one always terminates. An
    odds refresh on that host is effectively continuous -- the tick runs
    every 60s and refreshes regularly outrun it -- so an unbounded
    "defer while a refresh is in flight" degenerated into "never run":
    8 deferrals across 13 iterations, candidate_count 0, and
    snapshot_generated_at never set.
    """

    def _reason(self, *, sim, refresh, count, headroom=True):
        with patch.object(intelligence_state_module, "_mlb_sim_subprocess_running", return_value=sim), patch.object(
            intelligence_state_module, "_odds_refresh_in_flight", return_value=refresh
        ), patch.object(intelligence_state_module, "_board_build_has_memory_headroom", return_value=headroom):
            return intelligence_state_module._board_build_deferral_reason(consecutive_odds_defers=count)

    def test_runs_when_nothing_is_in_the_way(self) -> None:
        self.assertIsNone(self._reason(sim=False, refresh=False, count=0))

    def test_sim_deferral_is_unbounded_because_a_sim_is_finite(self) -> None:
        self.assertEqual(self._reason(sim=True, refresh=False, count=999), "sim_subprocess_resident")

    def test_defers_to_an_odds_refresh_up_to_the_bound(self) -> None:
        self.assertEqual(self._reason(sim=False, refresh=True, count=0), "odds_refresh_in_flight")
        self.assertEqual(
            self._reason(sim=False, refresh=True, count=intelligence_state_module._MAX_CONSECUTIVE_ODDS_REFRESH_DEFERS - 1),
            "odds_refresh_in_flight",
        )

    def test_runs_past_the_bound_when_memory_actually_allows(self) -> None:
        # The anti-starvation branch: a near-continuous refresh must not be
        # able to hold the board off forever.
        self.assertIsNone(
            self._reason(sim=False, refresh=True, count=intelligence_state_module._MAX_CONSECUTIVE_ODDS_REFRESH_DEFERS, headroom=True)
        )

    def test_keeps_deferring_past_the_bound_when_memory_does_not_allow(self) -> None:
        # Overriding a safety wait is only justified by real headroom.
        self.assertEqual(
            self._reason(sim=False, refresh=True, count=99, headroom=False),
            "odds_refresh_in_flight_and_no_headroom",
        )

    def test_sim_takes_precedence_over_the_refresh_branch(self) -> None:
        # A resident sim is the larger, better-evidenced hazard.
        self.assertEqual(self._reason(sim=True, refresh=True, count=99), "sim_subprocess_resident")

    def test_unmeasurable_headroom_counts_as_insufficient(self) -> None:
        with patch("syndicate.features.shared.memory_observability.memory_headroom_snapshot", return_value=None):
            self.assertFalse(intelligence_state_module._board_build_has_memory_headroom())

    def test_broken_headroom_check_counts_as_insufficient(self) -> None:
        with patch("syndicate.features.shared.memory_observability.memory_headroom_snapshot", side_effect=RuntimeError("boom")):
            self.assertFalse(intelligence_state_module._board_build_has_memory_headroom())
