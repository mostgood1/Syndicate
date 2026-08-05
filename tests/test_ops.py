from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pipeline.intelligence_state as intelligence_state_module
from syndicate.app import create_app
from syndicate.features.shared.live_refresh_loop import ScheduleEvent


class OpsRefreshApiTests(unittest.TestCase):
    def setUp(self) -> None:
        app = create_app()
        app.testing = True
        self.client = app.test_client()

    def test_status_requires_admin_token(self) -> None:
        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False):
            response = self.client.get("/api/ops/odds-refresh/status")

        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.get_json()["ok"])

    def test_status_reads_latest_refresh_manifest(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            reports_root = repo_root / "reports"
            refresh_latest = reports_root / "refresh_status" / "latest"
            daily_latest = reports_root / "daily_update" / "latest"
            artifacts_dir = reports_root / "migration_runs" / "2026-05-19" / "20260519_120000"
            refresh_latest.mkdir(parents=True, exist_ok=True)
            daily_latest.mkdir(parents=True, exist_ok=True)
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            mlb_mirror_manifest_dir = repo_root / "data" / "mlb_source" / "manifests"
            mlb_mirror_manifest_dir.mkdir(parents=True, exist_ok=True)

            (artifacts_dir / "refresh_and_gate_run.json").write_text(
                json.dumps({"date": "2026-05-19", "refreshOdds": True}),
                encoding="utf-8",
            )
            (artifacts_dir / "odds_refresh.json").write_text(
                json.dumps({"ok": True, "dry_run": False, "sports": ["mlb", "nba"]}),
                encoding="utf-8",
            )
            (artifacts_dir / "migration_gate_report.json").write_text(
                json.dumps({"ok": True, "tests": {"ok": True}}),
                encoding="utf-8",
            )
            (artifacts_dir / "migration_gate_console.txt").write_text("gate ok", encoding="utf-8")
            (artifacts_dir / "odds_refresh.stderr.txt").write_text("", encoding="utf-8")

            historical_run_dir = reports_root / "refresh_status" / "2026-05-18" / "20260518_120000"
            historical_run_dir.mkdir(parents=True, exist_ok=True)
            historical_artifacts = reports_root / "migration_runs" / "2026-05-18" / "odds_refresh_20260518_120000"
            historical_artifacts.mkdir(parents=True, exist_ok=True)
            (historical_artifacts / "odds_refresh.json").write_text(
                json.dumps({"ok": False, "dry_run": True, "sports": ["mlb"]}),
                encoding="utf-8",
            )
            (historical_artifacts / "odds_refresh.stderr.txt").write_text("failed once", encoding="utf-8")
            (historical_run_dir / "refresh_status_manifest.json").write_text(
                json.dumps({
                    "date": "2026-05-18",
                    "runStamp": "20260518_120000",
                    "artifactsDir": str(historical_artifacts),
                    "oddsPhase": "live",
                    "oddsSports": "mlb",
                    "dryRun": True,
                    "state": "failed",
                    "finishedAt": "2026-05-18T12:05:00Z",
                }),
                encoding="utf-8",
            )

            (refresh_latest / "refresh_status_latest.json").write_text(
                json.dumps({"date": "2026-05-19", "artifactsDir": str(artifacts_dir), "generatedAt": "2026-05-19T12:00:00Z", "finishedAt": "2026-05-19T12:30:00Z"}),
                encoding="utf-8",
            )
            (mlb_mirror_manifest_dir / "mirror_refresh_latest.json").write_text(
                json.dumps(
                    {
                        "sport": "mlb",
                        "date": "2026-05-19",
                        "copiedArtifactCount": 14,
                        "artifactGroups": {"daily": 10, "eval": 4},
                    }
                ),
                encoding="utf-8",
            )
            (daily_latest / "daily_update_latest.json").write_text(
                json.dumps({"date": "2026-05-19", "latestRunDir": "reports/daily_update/2026-05-19/run", "generatedAt": "2026-05-19T12:00:00Z", "completedAt": "2026-05-19T12:45:00Z"}),
                encoding="utf-8",
            )

            mocked_status = {
                "refresh_status": {
                    "manifest": {"date": "2026-05-19", "generatedAt": "2026-05-19T12:00:00Z"},
                    "runtime": {
                        "state": "finished",
                        "elapsed_seconds": 1800,
                        "remaining_budget_seconds": 12600,
                        "finishedAt": "2026-05-19T12:30:00Z",
                    },
                    "artifacts": {"odds_refresh": {"exists": True}},
                    "mirror_manifests": [{"sport": "mlb", "copiedArtifactCount": 14}],
                    "history": [{"finishedAt": "2026-05-18T12:05:00Z"}],
                },
                "daily_update": {
                    "manifest": {"date": "2026-05-19", "generatedAt": "2026-05-19T12:00:00Z"},
                    "runtime": {"elapsed_seconds": 2700, "remaining_budget_seconds": 11700, "completedAt": "2026-05-19T12:45:00Z"},
                },
            }

            with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False), patch(
                "syndicate.blueprints.ops.load_latest_refresh_status", return_value=mocked_status
            ):
                response = self.client.get(
                    "/api/ops/odds-refresh/status",
                    headers={"X-Admin-Token": "secret-token"},
                )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"]["refresh_status"]["manifest"]["date"], "2026-05-19")
        self.assertTrue(payload["status"]["refresh_status"]["artifacts"]["odds_refresh"]["exists"])
        self.assertEqual(payload["status"]["refresh_status"]["runtime"]["state"], "finished")
        self.assertEqual(payload["status"]["refresh_status"]["runtime"]["elapsed_seconds"], 1800)
        self.assertEqual(payload["status"]["refresh_status"]["runtime"]["remaining_budget_seconds"], 12600)
        self.assertEqual(payload["status"]["refresh_status"]["manifest"]["generatedAt"], "2026-05-19T07:00:00-05:00")
        self.assertEqual(payload["status"]["refresh_status"]["runtime"]["finishedAt"], "2026-05-19T07:30:00-05:00")
        self.assertGreaterEqual(len(payload["status"]["refresh_status"]["history"]), 1)
        self.assertEqual(payload["status"]["refresh_status"]["mirror_manifests"][0]["sport"], "mlb")
        self.assertEqual(payload["status"]["refresh_status"]["mirror_manifests"][0]["copiedArtifactCount"], 14)
        self.assertEqual(payload["status"]["daily_update"]["manifest"]["date"], "2026-05-19")
        self.assertEqual(payload["status"]["daily_update"]["runtime"]["elapsed_seconds"], 2700)
        self.assertEqual(payload["status"]["daily_update"]["runtime"]["remaining_budget_seconds"], 11700)

    def test_status_separates_required_and_optional_artifact_failures(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            reports_root = repo_root / "reports"
            refresh_latest = reports_root / "refresh_status" / "latest"
            artifacts_dir = reports_root / "migration_runs" / "2026-07-09" / "odds_refresh_20260709_120000"
            refresh_latest.mkdir(parents=True, exist_ok=True)
            artifacts_dir.mkdir(parents=True, exist_ok=True)

            refresh_status_manifest = {
                "date": "2026-07-09",
                "runStamp": "20260709_120000",
                "generatedAt": "2026-07-09T12:00:00Z",
                "finishedAt": "2026-07-09T12:30:00Z",
                "artifactsDir": str(artifacts_dir),
                "state": "finished",
            }
            odds_refresh_payload = {
                "ok": False,
                "date": "2026-07-09",
                "results": [
                    {
                        "sport": "mlb",
                        "ok": False,
                        "error": "required predictions missing for mlb",
                        "sport_manifest": {
                            "payload": {
                                "metadata": {
                                    "refresh_contract": {
                                        "required": ["snapshot", "snapshot_alias", "game_slate", "predictions", "board_contract", "manifest"],
                                        "optional": ["smart_sim", "recommendations", "edges", "live_lens", "advanced_analytics", "simulation_detail"],
                                    }
                                }
                            }
                        },
                    },
                    {
                        "sport": "wnba",
                        "ok": True,
                        "warning": "optional SmartSim artifact missing for wnba",
                        "optional_artifact_failures": ["optional SmartSim artifact missing for wnba"],
                        "sport_manifest": {
                            "payload": {
                                "metadata": {
                                    "refresh_contract": {
                                        "required": ["snapshot", "snapshot_alias", "game_slate", "predictions", "board_contract", "manifest"],
                                        "optional": ["smart_sim", "recommendations", "edges", "live_lens", "advanced_analytics", "simulation_detail"],
                                    }
                                }
                            }
                        },
                    },
                ],
            }

            (refresh_latest / "refresh_status_latest.json").write_text(json.dumps(refresh_status_manifest), encoding="utf-8")
            (artifacts_dir / "odds_refresh.json").write_text(json.dumps(odds_refresh_payload), encoding="utf-8")
            (artifacts_dir / "odds_refresh.stderr.txt").write_text("", encoding="utf-8")

            with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token", "SYNDICATE_REPORTS_ROOT": str(reports_root)}, clear=False), patch(
                "syndicate.features.shared.ops_refresh.REPO_ROOT",
                repo_root,
            ), patch("syndicate.features.shared.ops_refresh.REPORTS_ROOT", reports_root):
                response = self.client.get(
                    "/api/ops/odds-refresh/status",
                    headers={"X-Admin-Token": "secret-token"},
                )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        refresh_status = payload["status"]["refresh_status"]
        self.assertIn("required predictions missing for mlb", refresh_status["required_artifact_failures"])
        self.assertIn("optional SmartSim artifact missing for wnba", refresh_status["optional_artifact_failures"])
        self.assertEqual(refresh_status["refresh_contract"]["required"], ["snapshot", "snapshot_alias", "game_slate", "predictions", "board_contract", "manifest"])
        self.assertEqual(refresh_status["refresh_contract"]["optional"], ["smart_sim", "recommendations", "edges", "live_lens", "advanced_analytics", "simulation_detail"])

    def test_version_endpoint_returns_render_commit_metadata(self) -> None:
        with patch.dict(
            os.environ,
            {
                "ADMIN_TOKEN": "secret-token",
                "RENDER_GIT_COMMIT": "273983a",
                "RENDER_GIT_BRANCH": "main",
                "RENDER_SERVICE_NAME": "syndicate-web",
            },
            clear=False,
        ), patch("syndicate.blueprints.ops._git_value", return_value=None):
            response = self.client.get(
                "/api/ops/version",
                headers={"X-Admin-Token": "secret-token"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["version"]["commit"], "273983a")
        self.assertEqual(payload["version"]["commit_source"], "env")
        self.assertEqual(payload["version"]["branch"], "main")
        self.assertEqual(payload["version"]["render_service_name"], "syndicate-web")

    def test_board_snapshot_inspect_requires_admin_token(self) -> None:
        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False):
            response = self.client.get("/api/ops/board-snapshot/inspect")

        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.get_json()["ok"])

    def test_board_snapshot_inspect_reports_missing_snapshot(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            fake_path = Path(tmp_dir) / "reports" / "intelligence" / "board_snapshot.json"
            with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False), patch.object(
                intelligence_state_module, "BOARD_SNAPSHOT_PATH", fake_path
            ):
                response = self.client.get(
                    "/api/ops/board-snapshot/inspect",
                    headers={"X-Admin-Token": "secret-token"},
                )

        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["exists"])

    def test_board_snapshot_inspect_breaks_down_candidate_types_and_markets(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            fake_path = Path(tmp_dir) / "reports" / "intelligence" / "board_snapshot.json"
            fake_path.parent.mkdir(parents=True, exist_ok=True)
            fake_path.write_text(
                json.dumps(
                    {
                        "updated_at": "2026-08-04T04:00:00Z",
                        "response": {
                            "selected_date": "2026-08-04",
                            "candidate_count": 3,
                            "recommendations": [
                                {"candidate_type": "prop", "market": "Hitter Hits"},
                                {"candidate_type": "steam", "market": "Total · Steam"},
                                {"candidate_type": "game", "market": "Moneyline"},
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False), patch.object(
                intelligence_state_module, "BOARD_SNAPSHOT_PATH", fake_path
            ):
                response = self.client.get(
                    "/api/ops/board-snapshot/inspect",
                    headers={"X-Admin-Token": "secret-token"},
                )

        payload = response.get_json()
        self.assertTrue(payload["exists"])
        self.assertEqual(payload["recommendation_count"], 3)
        self.assertEqual(
            payload["recommendations_candidate_type_market_breakdown"],
            {"prop / Hitter Hits": 1, "steam / Total · Steam": 1, "game / Moneyline": 1},
        )

    def test_memory_endpoint_requires_admin_token(self) -> None:
        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False):
            response = self.client.get("/api/ops/memory")

        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.get_json()["ok"])

    def test_memory_endpoint_returns_process_snapshot(self) -> None:
        fake_snapshot = {"accounted_rss_mb": 123.4, "process_count": 2}
        with patch.dict(
            os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False
        ), patch(
            "syndicate.features.shared.memory_observability.get_all_process_memory_snapshot",
            return_value=fake_snapshot,
        ):
            response = self.client.get(
                "/api/ops/memory",
                headers={"X-Admin-Token": "secret-token"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["memory"], fake_snapshot)

    def test_evaluation_settlement_status_requires_admin_token(self) -> None:
        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False):
            response = self.client.get("/api/ops/evaluation-settlement/status")

        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.get_json()["ok"])

    def test_evaluation_settlement_status_reads_autorun_status_and_supported_sports(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            reports_root = Path(tmp_dir) / "reports"
            status_dir = reports_root / "refresh_status" / "latest"
            status_dir.mkdir(parents=True, exist_ok=True)
            (status_dir / "evaluation_settlement_autorun_status.json").write_text(
                json.dumps(
                    {
                        "epoch": 1785000000.0,
                        "dates": ["2026-08-02", "2026-08-03"],
                        "summary": {"pending": 12, "matched": 9, "settled": 9, "unmatched": 3},
                        "error": None,
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {"ADMIN_TOKEN": "secret-token", "SYNDICATE_REPORTS_ROOT": str(reports_root)},
                clear=False,
            ):
                response = self.client.get(
                    "/api/ops/evaluation-settlement/status",
                    headers={"X-Admin-Token": "secret-token"},
                )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        # "Supported" is driven by graded_outcomes.GRADED_OUTCOME_GRADERS
        # (has a registered grader), not a hardcoded allowlist -- assert
        # membership/superset rather than an exact list so this doesn't
        # need updating every time another sport's grader lands.
        self.assertIn("mlb", payload["supported_sports"])
        self.assertIn("wnba", payload["supported_sports"])
        self.assertEqual(payload["autorun_status"]["summary"], {"pending": 12, "matched": 9, "settled": 9, "unmatched": 3})

    def test_evaluation_settlement_status_includes_board_state_ledger_fingerprints(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            reports_root = Path(tmp_dir) / "reports"
            intelligence_dir = reports_root / "intelligence"
            intelligence_dir.mkdir(parents=True, exist_ok=True)
            (intelligence_dir / "canonical_board_state_ledger_fingerprints.json").write_text(
                json.dumps({"2026-08-03": "fp-abc123"}),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {"ADMIN_TOKEN": "secret-token", "SYNDICATE_REPORTS_ROOT": str(reports_root)},
                clear=False,
            ):
                response = self.client.get(
                    "/api/ops/evaluation-settlement/status",
                    headers={"X-Admin-Token": "secret-token"},
                )

        payload = response.get_json()
        self.assertEqual(payload["board_state_ledger_recorded_fingerprints"], {"2026-08-03": "fp-abc123"})

    def test_odds_history_matchup_coverage_requires_admin_token(self) -> None:
        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False):
            response = self.client.get("/api/ops/odds-history/matchup-coverage")

        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.get_json()["ok"])

    def test_odds_history_matchup_coverage_reads_status_file(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            reports_root = Path(tmp_dir) / "reports"
            status_dir = reports_root / "refresh_status" / "latest"
            status_dir.mkdir(parents=True, exist_ok=True)
            (status_dir / "odds_history_h2h_matchup_coverage_status.json").write_text(
                json.dumps(
                    {
                        "mlb": {
                            "date": "2026-08-04",
                            "updated_at": "2026-08-04T15:26:00Z",
                            "in_source": ["Away@Home", "Away2@Home2"],
                            "passed_gate": ["Away@Home"],
                            "written": ["Away@Home"],
                            "dropped_at_gate": ["Away2@Home2"],
                            "dropped_after_gate": [],
                        }
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {"ADMIN_TOKEN": "secret-token", "SYNDICATE_REPORTS_ROOT": str(reports_root)},
                clear=False,
            ):
                response = self.client.get(
                    "/api/ops/odds-history/matchup-coverage",
                    headers={"X-Admin-Token": "secret-token"},
                )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["by_sport"]["mlb"]["dropped_at_gate"], ["Away2@Home2"])

    def test_odds_history_matchup_coverage_empty_when_no_status_file(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            reports_root = Path(tmp_dir) / "reports"
            with patch.dict(
                os.environ,
                {"ADMIN_TOKEN": "secret-token", "SYNDICATE_REPORTS_ROOT": str(reports_root)},
                clear=False,
            ):
                response = self.client.get(
                    "/api/ops/odds-history/matchup-coverage",
                    headers={"X-Admin-Token": "secret-token"},
                )

        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["by_sport"], {})

    def test_force_mlb_resim_requires_game_pks(self) -> None:
        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False):
            response = self.client.post(
                "/api/ops/live-refresh/force-mlb-resim?date=2026-07-19",
                headers={"X-Admin-Token": "secret-token"},
            )

        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertIn("game_pks", payload["error"])

    def test_force_mlb_resim_rejects_unknown_game_pks(self) -> None:
        events = [ScheduleEvent(sport="mlb", event_id="100", home="A", away="B", start_time_utc=None)]
        with patch.dict(
            os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False
        ), patch("syndicate.features.shared.schedule_adapter.fetch_schedule_for_date", return_value=events):
            response = self.client.post(
                "/api/ops/live-refresh/force-mlb-resim?date=2026-07-19&game_pks=999",
                headers={"X-Admin-Token": "secret-token"},
            )

        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertIn("999", payload["error"])

    def test_force_mlb_resim_scopes_invalidation_to_requested_games_only(self) -> None:
        events = [
            ScheduleEvent(sport="mlb", event_id="100", home="A", away="B", start_time_utc=None),
            ScheduleEvent(sport="mlb", event_id="200", home="C", away="D", start_time_utc=None),
            ScheduleEvent(sport="mlb", event_id="300", home="E", away="F", start_time_utc=None),
        ]
        current_fingerprints = {"100": "aaa", "200": "bbb", "300": "ccc"}
        stored_check = {
            "date": "2026-07-19",
            "fingerprints": {"100": "old_aaa", "200": "old_bbb", "300": "old_ccc"},
        }
        with patch.dict(
            os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False
        ), patch(
            "syndicate.features.shared.schedule_adapter.fetch_schedule_for_date", return_value=events
        ), patch(
            "syndicate.features.shared.live_refresh_loop._mlb_sim_input_fingerprint_by_game",
            return_value=current_fingerprints,
        ), patch(
            "syndicate.features.shared.live_refresh_loop._read_last_mlb_sim_check", return_value=stored_check
        ), patch(
            "syndicate.features.shared.live_refresh_loop._record_mlb_sim_check"
        ) as mocked_record:
            response = self.client.post(
                "/api/ops/live-refresh/force-mlb-resim?date=2026-07-19&game_pks=200",
                headers={"X-Admin-Token": "secret-token"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["game_pks"], ["200"])

        mocked_record.assert_called_once()
        recorded_args = mocked_record.call_args.args
        recorded_fingerprints = recorded_args[2]
        # Untouched games keep their real current hash -- they'll read
        # "unchanged" next tick and stay out of the resim.
        self.assertEqual(recorded_fingerprints["100"], "aaa")
        self.assertEqual(recorded_fingerprints["300"], "ccc")
        # The requested game's stored hash is invalidated (differs from both
        # its own current hash and its prior stored hash), forcing it -- and
        # only it -- to show as changed.
        self.assertNotEqual(recorded_fingerprints["200"], "bbb")
        self.assertNotEqual(recorded_fingerprints["200"], "old_bbb")

    def test_healthz_exposes_public_render_version_metadata_without_admin_auth(self) -> None:
        response = self.client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["service"], "syndicate")

    def test_status_marks_running_when_pid_is_alive(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            reports_root = repo_root / "reports"
            refresh_latest = reports_root / "refresh_status" / "latest"
            refresh_latest.mkdir(parents=True, exist_ok=True)
            artifacts_dir = reports_root / "migration_runs" / "2026-05-20" / "odds_refresh_20260520_120000"
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            (refresh_latest / "refresh_status_latest.json").write_text(
                json.dumps({"date": "2026-05-20", "artifactsDir": str(artifacts_dir), "pid": 9999, "state": "running"}),
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {"ADMIN_TOKEN": "secret-token", "SYNDICATE_REPORTS_ROOT": str(reports_root)},
                clear=False,
            ), patch(
                "syndicate.features.shared.ops_refresh.REPO_ROOT", repo_root
            ), patch("syndicate.features.shared.ops_refresh.REPORTS_ROOT", reports_root), patch(
                "syndicate.features.shared.ops_refresh._pid_is_running",
                return_value=True,
            ):
                response = self.client.get(
                    "/api/ops/odds-refresh/status",
                    headers={"X-Admin-Token": "secret-token"},
                )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"]["refresh_status"]["runtime"]["state"], "running")

    def test_status_surfaces_external_runner_contract(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            reports_root = repo_root / "reports"
            refresh_latest = reports_root / "refresh_status" / "latest"
            artifacts_dir = reports_root / "migration_runs" / "2026-05-22" / "odds_refresh_20260522_120000"
            refresh_latest.mkdir(parents=True, exist_ok=True)
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            (refresh_latest / "refresh_worker_status.json").write_text(
                json.dumps({"state": "finished", "detail": "worker finished", "ranJob": True, "runExitCode": 0, "refreshCycle": {"claimed_count": 1, "reclaimed_count": 0, "skipped_due_to_cap": 0}}),
                encoding="utf-8",
            )
            (artifacts_dir / "refresh_job_status.json").write_text(
                json.dumps({"state": "finished", "exitCode": 0}),
                encoding="utf-8",
            )
            (refresh_latest / "refresh_status_latest.json").write_text(
                json.dumps(
                    {
                        "date": "2026-05-22",
                        "artifactsDir": str(artifacts_dir),
                        "state": "pending_external",
                        "launchOwner": "external_runner",
                        "externalRunner": {"kind": "external_runner", "queue_state": "queued", "runStamp": "20260522_120000"},
                    }
                ),
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {"ADMIN_TOKEN": "secret-token", "SYNDICATE_REPORTS_ROOT": str(reports_root)},
                clear=False,
            ), patch(
                "syndicate.features.shared.ops_refresh.REPO_ROOT", repo_root
            ), patch("syndicate.features.shared.ops_refresh.REPORTS_ROOT", reports_root):
                response = self.client.get(
                    "/api/ops/odds-refresh/status",
                    headers={"X-Admin-Token": "secret-token"},
                )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        runtime = payload["status"]["refresh_status"]["runtime"]
        self.assertEqual(runtime["state"], "pending_external")
        self.assertEqual(runtime["launch_owner"], "external_runner")
        self.assertEqual((runtime.get("external_runner") or {}).get("queue_state"), "queued")
        self.assertEqual(runtime["refresh_cycle"], {"claimed_count": 1, "reclaimed_count": 0, "skipped_due_to_cap": 0})
        self.assertEqual((payload["status"]["refresh_status"]["artifacts"]["refresh_worker_status"]["payload"] or {}).get("state"), "finished")
        self.assertEqual((payload["status"]["refresh_status"]["artifacts"]["refresh_job_status"]["payload"] or {}).get("state"), "finished")

    def test_status_reads_from_env_configured_reports_and_data_roots(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            reports_root = root / "persistent" / "reports"
            data_root = root / "persistent" / "data"
            refresh_latest = reports_root / "refresh_status" / "latest"
            daily_latest = reports_root / "daily_update" / "latest"
            mirror_manifest_dir = data_root / "mlb_source" / "manifests"
            artifacts_dir = reports_root / "migration_runs" / "2026-05-22" / "odds_refresh_20260522_120000"

            refresh_latest.mkdir(parents=True, exist_ok=True)
            daily_latest.mkdir(parents=True, exist_ok=True)
            mirror_manifest_dir.mkdir(parents=True, exist_ok=True)
            artifacts_dir.mkdir(parents=True, exist_ok=True)

            (artifacts_dir / "odds_refresh.stderr.txt").write_text("", encoding="utf-8")
            (refresh_latest / "refresh_status_latest.json").write_text(
                json.dumps({"date": "2026-05-22", "artifactsDir": str(artifacts_dir)}),
                encoding="utf-8",
            )
            (daily_latest / "daily_update_latest.json").write_text(
                json.dumps({"date": "2026-05-22"}),
                encoding="utf-8",
            )
            (daily_latest / "unified_daily_update_latest_checkpoint.json").write_text(
                json.dumps({"date": "2026-05-22", "currentStage": "refresh_gate", "completedStages": ["source_update"]}),
                encoding="utf-8",
            )
            (daily_latest / "unified_daily_update_latest_run_state.json").write_text(
                json.dumps({"date": "2026-05-22", "currentStage": "refresh_gate", "completedStages": ["source_update"], "failedStage": None}),
                encoding="utf-8",
            )
            (daily_latest / "unified_daily_update_latest_run_trace.json").write_text(
                json.dumps({"date": "2026-05-22", "trace": {"inputFingerprintCount": 3, "artifactPathCount": 2}}),
                encoding="utf-8",
            )
            # This test asserts simulation_contract_exists is True but never
            # wrote the file, so it could only ever fail. The other daily_update
            # artifacts it checks are all seeded above; this one was simply
            # missed, and the assertion is legitimate -- load_latest_refresh_status
            # does read it from the env-configured reports root.
            (daily_latest / "unified_daily_update_latest_simulation_contract.json").write_text(
                json.dumps({"date": "2026-05-22", "scope": "daily_update", "simulatedSports": ["mlb"]}),
                encoding="utf-8",
            )
            (mirror_manifest_dir / "mirror_refresh_latest.json").write_text(
                json.dumps({"sport": "mlb", "date": "2026-05-22", "copiedArtifactCount": 3}),
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {
                    "ADMIN_TOKEN": "secret-token",
                    "SYNDICATE_REPORTS_ROOT": str(reports_root),
                    "SYNDICATE_DATA_ROOT": str(data_root),
                },
                clear=False,
            ):
                response = self.client.get(
                    "/api/ops/odds-refresh/status",
                    headers={"X-Admin-Token": "secret-token"},
                )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(Path(payload["status"]["reports_root"]).resolve(), reports_root.resolve())
        self.assertEqual(payload["status"]["refresh_status"]["manifest"]["date"], "2026-05-22")
        self.assertEqual(payload["status"]["refresh_status"]["mirror_manifests"][0]["sport"], "mlb")
        self.assertEqual(payload["status"]["daily_update"]["checkpoint"]["currentStage"], "refresh_gate")
        self.assertEqual(payload["status"]["daily_update"]["run_state"]["currentStage"], "refresh_gate")
        self.assertEqual(payload["status"]["daily_update"]["trace"]["trace"]["inputFingerprintCount"], 3)
        self.assertTrue(payload["status"]["daily_update"]["simulation_contract_exists"])
        self.assertEqual(payload["status"]["daily_update"]["simulation_contract"]["scope"], "daily_update")

    def test_plan_endpoint_returns_dry_run_payload(self) -> None:
        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False), patch(
            "syndicate.blueprints.ops.build_refresh_plan",
            return_value={"ok": True, "dry_run": True, "sports": ["mlb"]},
        ) as mocked:
            response = self.client.get(
                "/api/ops/odds-refresh/plan?sports=mlb&skip_mirror=1",
                headers={"Authorization": "Bearer secret-token"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["plan"]["dry_run"])
        mocked.assert_called_once()

    def test_plan_endpoint_threads_force_refresh_through(self) -> None:
        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False), patch(
            "syndicate.blueprints.ops.build_refresh_plan",
            return_value={"ok": True, "dry_run": True, "sports": ["wnba"]},
        ) as mocked:
            response = self.client.get(
                "/api/ops/odds-refresh/plan?sports=wnba&force_refresh=1",
                headers={"Authorization": "Bearer secret-token"},
            )

        self.assertEqual(response.status_code, 200)
        mocked.assert_called_once()
        self.assertTrue(mocked.call_args.kwargs.get("force_refresh"))

    def test_build_refresh_plan_uses_ncaab_raw_only_mirror_command_in_mirror_only_mode(self) -> None:
        from syndicate.features.shared import ops_refresh

        plan = ops_refresh.build_refresh_plan(date="2026-04-06", sports="ncaab", mirror_only=True)

        self.assertTrue(plan["ok"])
        self.assertEqual(plan["execution_mode"], "ingest")
        self.assertEqual(plan["sports"], ["ncaab"])
        self.assertEqual(len(plan["results"]), 1)
        result = plan["results"][0]
        self.assertEqual(result["sport"], "ncaab")
        self.assertEqual(result["generation_mode"], "none")
        self.assertEqual(result["ingestion_mode"], "mirror_script")
        self.assertEqual(result["refresh_steps"], [])
        mirror = result.get("mirror") or {}
        self.assertTrue(mirror.get("ok"))
        self.assertTrue(mirror.get("dry_run"))
        command = mirror.get("command") or []
        self.assertIn("refresh_ncaab_source_mirror.ps1", " ".join(str(part) for part in command))
        self.assertIn("-UseExistingRawOutputs", command)

    def test_build_refresh_plan_uses_ncaab_local_raw_outputs_in_source_mode(self) -> None:
        from syndicate.features.shared import ops_refresh

        plan = ops_refresh.build_refresh_plan(date="2026-04-06", sports="ncaab", execution_mode="source")

        self.assertTrue(plan["ok"])
        result = plan["results"][0]
        self.assertEqual(result["generation_mode"], "local_raw_outputs")
        self.assertEqual((result.get("generation") or {}).get("kind"), "local_raw_outputs")
        self.assertEqual((result.get("generation") or {}).get("source_dependency"), "local_raw_outputs")
        self.assertTrue((result.get("generation") or {}).get("hosted_safe"))
        self.assertEqual((result.get("ingestion") or {}).get("source_dependency"), "local_artifacts")
        refresh_steps = result.get("refresh_steps") or []
        self.assertEqual(len(refresh_steps), 1)
        step = refresh_steps[0]
        command = step.get("command") or []
        self.assertIn("scripts/refresh_ncaab_odds_history.py", " ".join(str(part) for part in command))
        self.assertNotIn("ncaab_model.cli", " ".join(str(part) for part in command))
        self.assertNotIn("--source-root", command)
        self.assertIn("--out-dir", command)
        self.assertIn("data/ncaab_source/raw_outputs/by_date/2026-04-06", " ".join(str(part).replace("\\", "/") for part in command))
        mirror = result.get("mirror") or {}
        command = mirror.get("command") or []
        self.assertIn("refresh_ncaab_source_mirror.ps1", " ".join(str(part) for part in command))
        self.assertNotIn("-UseExistingRawOutputs", command)
        self.assertNotIn("-RefreshRawOutputsFromSource", command)

    def test_build_refresh_plan_allows_ncaab_source_mode_without_source_repo_path(self) -> None:
        from syndicate.features.shared import ops_refresh

        module = ops_refresh._refresh_script_module()
        missing_root = Path("C:/definitely_missing_ncaab_repo")
        with patch.object(module, "_source_repo_root", return_value=missing_root), patch("syndicate.features.shared.ops_refresh._refresh_script_module", return_value=module):
            plan = ops_refresh.build_refresh_plan(date="2026-04-06", sports="ncaab", execution_mode="source")

        self.assertTrue(plan["ok"])
        result = plan["results"][0]
        self.assertTrue(result["ok"])
        self.assertEqual(result["generation_mode"], "local_raw_outputs")
        self.assertEqual((result.get("generation") or {}).get("kind"), "local_raw_outputs")
        self.assertEqual(result["source_repo"], str(missing_root))
        refresh_steps = result.get("refresh_steps") or []
        self.assertEqual(len(refresh_steps), 1)
        command = refresh_steps[0].get("command") or []
        self.assertNotIn("--source-root", command)

    def test_build_refresh_plan_uses_mlb_existing_mirror_command_in_mirror_only_mode(self) -> None:
        from syndicate.features.shared import ops_refresh

        plan = ops_refresh.build_refresh_plan(date="2026-05-22", sports="mlb", mirror_only=True)

        self.assertTrue(plan["ok"])
        self.assertEqual(plan["execution_mode"], "ingest")
        self.assertEqual(plan["sports"], ["mlb"])
        result = plan["results"][0]
        self.assertEqual(result["sport"], "mlb")
        self.assertEqual(result["generation_mode"], "none")
        self.assertEqual(result["ingestion_mode"], "mirror_script")
        self.assertEqual((result.get("generation") or {}).get("kind"), "none")
        self.assertEqual((result.get("ingestion") or {}).get("kind"), "mirror_script")
        self.assertTrue((result.get("ingestion") or {}).get("hosted_safe"))
        self.assertEqual(((result.get("ingestion") or {}).get("contract") or {}).get("kind"), "artifact_bundle_or_existing_mirror")
        self.assertEqual(result["refresh_steps"], [])
        mirror = result.get("mirror") or {}
        self.assertTrue(mirror.get("ok"))
        self.assertTrue(mirror.get("dry_run"))
        command = mirror.get("command") or []
        self.assertIn("refresh_mlb_source_mirror.ps1", " ".join(str(part) for part in command))
        self.assertIn("-UseExistingMirrorArtifacts", command)

    def test_build_refresh_plan_uses_mlb_artifact_root_when_configured(self) -> None:
        from syndicate.features.shared import ops_refresh

        with patch.dict(os.environ, {"SYNDICATE_ARTIFACT_ROOT_MLB": "C:/published/mlb-bundle"}, clear=False):
            plan = ops_refresh.build_refresh_plan(date="2026-05-22", sports="mlb", execution_mode="ingest")

        self.assertTrue(plan["ok"])
        result = plan["results"][0]
        self.assertEqual(((result.get("ingestion") or {}).get("contract") or {}).get("kind"), "artifact_bundle_or_existing_mirror")
        command = ((result.get("mirror") or {}).get("command") or [])
        self.assertIn("-SourceArtifactRoot", command)
        self.assertIn("C:/published/mlb-bundle", command)

    def test_build_refresh_plan_uses_mlb_syndicate_runner_in_source_mode(self) -> None:
        from syndicate.features.shared import ops_refresh

        module = ops_refresh._refresh_script_module()
        with patch.object(module, "_source_repo_root", side_effect=AssertionError("MLB should not resolve a sibling source repo")), patch(
            "syndicate.features.shared.ops_refresh._refresh_script_module", return_value=module
        ):
            plan = ops_refresh.build_refresh_plan(date="2026-05-22", sports="mlb", execution_mode="source")

        self.assertTrue(plan["ok"])
        result = plan["results"][0]
        self.assertEqual(result["generation_mode"], "local_artifact_bundle")
        self.assertEqual((result.get("generation") or {}).get("kind"), "local_artifact_bundle")
        self.assertEqual((result.get("generation") or {}).get("source_dependency"), "local_artifact_bundle")
        self.assertTrue((result.get("generation") or {}).get("hosted_safe"))
        self.assertIn("data/mlb_source", (result.get("source_repo") or "").replace("\\", "/"))
        refresh_steps = result.get("refresh_steps") or []
        self.assertEqual(len(refresh_steps), 1)
        step = refresh_steps[0]
        command = step.get("command") or []
        self.assertIn("scripts/refresh_mlb_oddsapi.py", " ".join(str(part) for part in command))
        self.assertNotIn("tools.oddsapi.fetch_daily_oddsapi_markets", " ".join(str(part) for part in command))
        self.assertIn("--source-root", command)
        self.assertIn("--artifact-root", command)
        self.assertIn("data/mlb_source/source_artifacts", " ".join(str(part).replace("\\", "/") for part in command))
        self.assertNotIn("source checkout", " ".join(str(part) for part in command).lower())
        mirror = result.get("mirror") or {}
        mirror_command = mirror.get("command") or []
        self.assertIn("-SourceArtifactRoot", mirror_command)
        self.assertIn("data/mlb_source/source_artifacts", " ".join(str(part).replace("\\", "/") for part in mirror_command))
        self.assertNotIn("source checkout", " ".join(str(part) for part in mirror_command).lower())

    def test_build_refresh_plan_uses_nhl_existing_mirror_command_in_mirror_only_mode(self) -> None:
        from syndicate.features.shared import ops_refresh

        plan = ops_refresh.build_refresh_plan(date="2026-05-22", sports="nhl", mirror_only=True)

        self.assertTrue(plan["ok"])
        self.assertEqual(plan["execution_mode"], "ingest")
        self.assertEqual(plan["sports"], ["nhl"])
        result = plan["results"][0]
        self.assertEqual(result["sport"], "nhl")
        self.assertEqual(result["generation_mode"], "none")
        self.assertEqual(result["ingestion_mode"], "mirror_script")
        self.assertEqual(((result.get("ingestion") or {}).get("contract") or {}).get("kind"), "artifact_bundle_or_existing_mirror")
        self.assertEqual(result["refresh_steps"], [])
        mirror = result.get("mirror") or {}
        self.assertTrue(mirror.get("ok"))
        self.assertTrue(mirror.get("dry_run"))
        command = mirror.get("command") or []
        self.assertIn("refresh_nhl_source_mirror.ps1", " ".join(str(part) for part in command))
        self.assertIn("-UseExistingMirrorArtifacts", command)

    def test_build_refresh_plan_uses_nhl_artifact_root_when_configured(self) -> None:
        from syndicate.features.shared import ops_refresh

        with patch.dict(os.environ, {"SYNDICATE_ARTIFACT_ROOT_NHL": "C:/published/nhl-bundle"}, clear=False):
            plan = ops_refresh.build_refresh_plan(date="2026-05-22", sports="nhl", execution_mode="ingest")

        self.assertTrue(plan["ok"])
        result = plan["results"][0]
        self.assertEqual(((result.get("ingestion") or {}).get("contract") or {}).get("kind"), "artifact_bundle_or_existing_mirror")
        command = ((result.get("mirror") or {}).get("command") or [])
        self.assertIn("-SourceArtifactRoot", command)
        self.assertIn("C:/published/nhl-bundle", command)

    def test_build_refresh_plan_uses_nhl_syndicate_runner_in_source_mode(self) -> None:
        from syndicate.features.shared import ops_refresh

        plan = ops_refresh.build_refresh_plan(date="2026-05-22", sports="nhl", execution_mode="source")

        self.assertTrue(plan["ok"])
        result = plan["results"][0]
        self.assertEqual(result["generation_mode"], "local_artifact_bundle")
        self.assertEqual((result.get("generation") or {}).get("kind"), "local_artifact_bundle")
        self.assertEqual((result.get("generation") or {}).get("source_dependency"), "local_artifact_bundle")
        self.assertTrue((result.get("generation") or {}).get("hosted_safe"))
        self.assertEqual((result.get("ingestion") or {}).get("source_dependency"), "local_artifact_bundle")
        refresh_steps = result.get("refresh_steps") or []
        self.assertEqual(len(refresh_steps), 1)
        step = refresh_steps[0]
        command = step.get("command") or []
        self.assertIn("scripts/refresh_nhl_oddsapi.py", " ".join(str(part) for part in command))
        self.assertNotIn("nhl_betting.cli", " ".join(str(part) for part in command))
        self.assertNotIn("--source-root", command)
        self.assertIn("--artifact-root", command)
        self.assertIn("data/nhl_source/source_artifacts", " ".join(str(part).replace("\\", "/") for part in command))
        mirror = result.get("mirror") or {}
        mirror_command = mirror.get("command") or []
        self.assertIn("-SourceArtifactRoot", mirror_command)
        self.assertIn("data/nhl_source/source_artifacts", " ".join(str(part).replace("\\", "/") for part in mirror_command))

    def test_build_refresh_plan_allows_nhl_source_mode_without_source_repo_path(self) -> None:
        from syndicate.features.shared import ops_refresh

        module = ops_refresh._refresh_script_module()
        missing_root = Path("C:/definitely_missing_nhl_repo")
        with patch.object(module, "_source_repo_root", return_value=missing_root), patch("syndicate.features.shared.ops_refresh._refresh_script_module", return_value=module):
            plan = ops_refresh.build_refresh_plan(date="2026-05-22", sports="nhl", execution_mode="source")

        self.assertTrue(plan["ok"])
        result = plan["results"][0]
        self.assertTrue(result["ok"])
        self.assertEqual(result["generation_mode"], "local_artifact_bundle")
        self.assertEqual((result.get("generation") or {}).get("kind"), "local_artifact_bundle")
        self.assertEqual(result["source_repo"], str(missing_root))
        refresh_steps = result.get("refresh_steps") or []
        self.assertEqual(len(refresh_steps), 1)
        command = refresh_steps[0].get("command") or []
        self.assertNotIn("--source-root", command)

    def test_build_refresh_plan_uses_nba_existing_mirror_command_in_mirror_only_mode(self) -> None:
        from syndicate.features.shared import ops_refresh

        plan = ops_refresh.build_refresh_plan(date="2026-05-22", sports="nba", mirror_only=True)

        self.assertTrue(plan["ok"])
        self.assertEqual(plan["execution_mode"], "ingest")
        self.assertEqual(plan["sports"], ["nba"])
        result = plan["results"][0]
        self.assertEqual(result["sport"], "nba")
        self.assertEqual(result["generation_mode"], "none")
        self.assertEqual(result["ingestion_mode"], "mirror_script")
        self.assertEqual(((result.get("ingestion") or {}).get("contract") or {}).get("kind"), "artifact_bundle_or_existing_mirror")
        self.assertEqual(result["refresh_steps"], [])
        mirror = result.get("mirror") or {}
        self.assertTrue(mirror.get("ok"))
        self.assertTrue(mirror.get("dry_run"))
        command = mirror.get("command") or []
        self.assertIn("refresh_nba_source_mirror.ps1", " ".join(str(part) for part in command))
        self.assertIn("-UseExistingMirrorArtifacts", command)

    def test_build_refresh_plan_uses_nba_syndicate_runner_in_source_mode(self) -> None:
        from syndicate.features.shared import ops_refresh

        plan = ops_refresh.build_refresh_plan(date="2026-05-22", sports="nba", execution_mode="source")

        self.assertTrue(plan["ok"])
        result = plan["results"][0]
        self.assertEqual(result["generation_mode"], "local_artifact_bundle")
        self.assertEqual((result.get("generation") or {}).get("kind"), "local_artifact_bundle")
        self.assertEqual((result.get("generation") or {}).get("source_dependency"), "local_artifact_bundle")
        self.assertTrue((result.get("generation") or {}).get("hosted_safe"))
        self.assertEqual((result.get("ingestion") or {}).get("source_dependency"), "local_artifact_bundle")
        refresh_steps = result.get("refresh_steps") or []
        self.assertEqual(len(refresh_steps), 1)
        step = refresh_steps[0]
        command = step.get("command") or []
        self.assertIn("scripts/refresh_nba_oddsapi_props.py", " ".join(str(part) for part in command))
        self.assertNotIn("nba_betting.refresh_oddsapi_props_job", " ".join(str(part) for part in command))
        self.assertIn("--source-root", command)
        self.assertIn("--artifact-root", command)
        self.assertIn("data/nba_source/source_artifacts", " ".join(str(part).replace("\\", "/") for part in command))
        self.assertIn("--log-file", command)
        self.assertIn("--do-edges", command)
        self.assertIn("--do-export", command)
        mirror = result.get("mirror") or {}
        mirror_command = mirror.get("command") or []
        self.assertIn("-SourceArtifactRoot", mirror_command)
        self.assertIn("data/nba_source/source_artifacts", " ".join(str(part).replace("\\", "/") for part in mirror_command))

    def test_build_refresh_plan_uses_nba_artifact_root_when_configured(self) -> None:
        from syndicate.features.shared import ops_refresh

        with patch.dict(os.environ, {"SYNDICATE_ARTIFACT_ROOT_NBA": "C:/published/nba-bundle"}, clear=False):
            plan = ops_refresh.build_refresh_plan(date="2026-05-22", sports="nba", execution_mode="ingest")

        self.assertTrue(plan["ok"])
        result = plan["results"][0]
        self.assertEqual(((result.get("ingestion") or {}).get("contract") or {}).get("kind"), "artifact_bundle_or_existing_mirror")
        command = ((result.get("mirror") or {}).get("command") or [])
        self.assertIn("-SourceArtifactRoot", command)
        self.assertIn("C:/published/nba-bundle", command)

    def test_build_refresh_plan_uses_wnba_existing_mirror_command_in_mirror_only_mode(self) -> None:
        from syndicate.features.shared import ops_refresh

        plan = ops_refresh.build_refresh_plan(date="2026-05-22", sports="wnba", mirror_only=True)

        self.assertTrue(plan["ok"])
        self.assertEqual(plan["execution_mode"], "ingest")
        self.assertEqual(plan["sports"], ["wnba"])
        result = plan["results"][0]
        self.assertEqual(result["sport"], "wnba")
        self.assertEqual(result["generation_mode"], "none")
        self.assertEqual(result["ingestion_mode"], "mirror_script")
        self.assertEqual(((result.get("ingestion") or {}).get("contract") or {}).get("kind"), "artifact_bundle_or_existing_mirror")
        self.assertEqual(result["refresh_steps"], [])
        mirror = result.get("mirror") or {}
        self.assertTrue(mirror.get("ok"))
        self.assertTrue(mirror.get("dry_run"))
        command = mirror.get("command") or []
        self.assertIn("refresh_wnba_source_mirror.ps1", " ".join(str(part) for part in command))
        self.assertIn("-UseExistingMirrorArtifacts", command)

    def test_build_refresh_plan_uses_wnba_syndicate_runner_in_source_mode(self) -> None:
        from syndicate.features.shared import ops_refresh

        plan = ops_refresh.build_refresh_plan(date="2026-05-22", sports="wnba", execution_mode="source")

        self.assertTrue(plan["ok"])
        result = plan["results"][0]
        self.assertEqual(result["generation_mode"], "local_artifact_bundle")
        self.assertEqual((result.get("generation") or {}).get("kind"), "local_artifact_bundle")
        self.assertEqual((result.get("generation") or {}).get("source_dependency"), "local_artifact_bundle")
        self.assertTrue((result.get("generation") or {}).get("hosted_safe"))
        self.assertEqual((result.get("ingestion") or {}).get("source_dependency"), "local_artifact_bundle")
        refresh_steps = result.get("refresh_steps") or []
        self.assertEqual(len(refresh_steps), 1)
        step = refresh_steps[0]
        command = step.get("command") or []
        self.assertIn("scripts/refresh_wnba_oddsapi_props.py", " ".join(str(part) for part in command))
        self.assertNotIn("wnba_betting.refresh_oddsapi_props_job", " ".join(str(part) for part in command))
        self.assertIn("--source-root", command)
        self.assertIn("--artifact-root", command)
        self.assertIn("data/wnba_source/source_artifacts", " ".join(str(part).replace("\\", "/") for part in command))
        self.assertIn("--log-file", command)
        self.assertIn("--do-edges", command)
        self.assertIn("--do-export", command)
        mirror = result.get("mirror") or {}
        mirror_command = mirror.get("command") or []
        self.assertIn("-SourceArtifactRoot", mirror_command)
        self.assertIn("data/wnba_source/source_artifacts", " ".join(str(part).replace("\\", "/") for part in mirror_command))

    def test_build_refresh_plan_uses_wnba_artifact_root_when_configured(self) -> None:
        from syndicate.features.shared import ops_refresh

        with patch.dict(os.environ, {"SYNDICATE_ARTIFACT_ROOT_WNBA": "C:/published/wnba-bundle"}, clear=False):
            plan = ops_refresh.build_refresh_plan(date="2026-05-22", sports="wnba", execution_mode="ingest")

        self.assertTrue(plan["ok"])
        result = plan["results"][0]
        self.assertEqual(((result.get("ingestion") or {}).get("contract") or {}).get("kind"), "artifact_bundle_or_existing_mirror")
        command = ((result.get("mirror") or {}).get("command") or [])
        self.assertIn("-SourceArtifactRoot", command)
        self.assertIn("C:/published/wnba-bundle", command)

    def test_build_refresh_plan_supports_explicit_ingest_execution_mode(self) -> None:
        from syndicate.features.shared import ops_refresh

        plan = ops_refresh.build_refresh_plan(date="2026-05-22", sports="mlb", execution_mode="ingest")

        self.assertTrue(plan["ok"])
        self.assertEqual(plan["execution_mode"], "ingest")
        self.assertEqual(plan["sports"], ["mlb"])
        result = plan["results"][0]
        self.assertEqual(result["generation_mode"], "none")
        self.assertEqual(result["ingestion_mode"], "mirror_script")
        self.assertEqual((result.get("generation") or {}).get("kind"), "none")
        self.assertEqual((result.get("ingestion") or {}).get("kind"), "mirror_script")
        self.assertTrue((result.get("ingestion") or {}).get("hosted_safe"))
        self.assertEqual(((result.get("ingestion") or {}).get("contract") or {}).get("kind"), "artifact_bundle_or_existing_mirror")
        self.assertEqual(result["refresh_steps"], [])
        self.assertTrue((result.get("mirror") or {}).get("dry_run"))

    def test_build_refresh_plan_uses_nfl_existing_mirror_command_in_mirror_only_mode(self) -> None:
        from syndicate.features.shared import ops_refresh

        plan = ops_refresh.build_refresh_plan(date="2026-10-01", sports="nfl", mirror_only=True)

        self.assertTrue(plan["ok"])
        result = plan["results"][0]
        self.assertEqual((result.get("generation") or {}).get("kind"), "none")
        self.assertEqual((result.get("ingestion") or {}).get("kind"), "mirror_script")
        self.assertTrue((result.get("ingestion") or {}).get("hosted_safe"))
        self.assertEqual(((result.get("ingestion") or {}).get("contract") or {}).get("kind"), "artifact_bundle_or_existing_mirror")
        self.assertEqual(result["refresh_steps"], [])
        mirror = result.get("mirror") or {}
        self.assertTrue(mirror.get("ok"))
        self.assertTrue(mirror.get("dry_run"))
        command = mirror.get("command") or []
        self.assertIn("refresh_nfl_source_mirror.ps1", " ".join(str(part) for part in command))
        self.assertIn("-UseExistingMirrorArtifacts", command)

    def test_build_refresh_plan_uses_nfl_artifact_root_when_configured(self) -> None:
        from syndicate.features.shared import ops_refresh

        with patch.dict(os.environ, {"SYNDICATE_ARTIFACT_ROOT_NFL": "C:/published/nfl-bundle"}, clear=False):
            plan = ops_refresh.build_refresh_plan(date="2026-10-01", sports="nfl", execution_mode="ingest")

        self.assertTrue(plan["ok"])
        result = plan["results"][0]
        self.assertEqual((result.get("generation") or {}).get("kind"), "none")
        self.assertEqual((result.get("ingestion") or {}).get("kind"), "mirror_script")
        self.assertTrue((result.get("ingestion") or {}).get("hosted_safe"))
        self.assertEqual(((result.get("ingestion") or {}).get("contract") or {}).get("kind"), "artifact_bundle_or_existing_mirror")
        command = ((result.get("mirror") or {}).get("command") or [])
        self.assertIn("-SourceArtifactRoot", command)
        self.assertIn("C:/published/nfl-bundle", command)

    def test_build_refresh_plan_uses_nfl_syndicate_runner_in_source_mode(self) -> None:
        from syndicate.features.shared import ops_refresh

        plan = ops_refresh.build_refresh_plan(date="2026-10-01", sports="nfl", execution_mode="source")

        self.assertTrue(plan["ok"])
        result = plan["results"][0]
        self.assertEqual((result.get("ingestion") or {}).get("source_dependency"), "local_artifact_bundle")
        refresh_steps = result.get("refresh_steps") or []
        self.assertEqual(len(refresh_steps), 1)
        step = refresh_steps[0]
        command = step.get("command") or []
        self.assertIn("scripts/refresh_nfl_oddsapi.py", " ".join(str(part) for part in command))
        self.assertNotIn("fetch_oddsapi_props.py --out", " ".join(str(part) for part in command))
        self.assertNotIn("src.odds_api_client", " ".join(str(part) for part in command))
        self.assertNotIn("--source-root", command)
        self.assertIn("--artifact-root", command)
        self.assertIn("data/nfl_source/source_artifacts", " ".join(str(part).replace("\\", "/") for part in command))
        mirror = result.get("mirror") or {}
        mirror_command = mirror.get("command") or []
        self.assertIn("-SourceArtifactRoot", mirror_command)
        self.assertIn("data/nfl_source/source_artifacts", " ".join(str(part).replace("\\", "/") for part in mirror_command))

    def test_build_refresh_plan_uses_ncaaf_syndicate_runner_in_source_mode(self) -> None:
        from syndicate.features.shared import ops_refresh

        plan = ops_refresh.build_refresh_plan(date="2026-10-01", sports="ncaaf", execution_mode="source")

        self.assertTrue(plan["ok"])
        result = plan["results"][0]
        self.assertEqual(result["generation_mode"], "local_artifact_bundle")
        self.assertEqual((result.get("generation") or {}).get("kind"), "local_artifact_bundle")
        self.assertEqual((result.get("generation") or {}).get("source_dependency"), "local_artifact_bundle")
        self.assertTrue((result.get("generation") or {}).get("hosted_safe"))
        refresh_steps = result.get("refresh_steps") or []
        self.assertEqual(len(refresh_steps), 1)
        step = refresh_steps[0]
        command = step.get("command") or []
        self.assertIn("scripts/refresh_ncaaf_oddsapi.py", " ".join(str(part) for part in command))
        self.assertNotIn("fetch_2025_lines.py --week", " ".join(str(part) for part in command))
        self.assertNotIn("--source-root", command)
        self.assertIn("--artifact-root", command)
        self.assertIn("data/ncaaf_source/source_artifacts", " ".join(str(part).replace("\\", "/") for part in command))
        mirror = result.get("mirror") or {}
        mirror_command = mirror.get("command") or []
        self.assertIn("-SourceArtifactRoot", mirror_command)
        self.assertIn("data/ncaaf_source/source_artifacts", " ".join(str(part).replace("\\", "/") for part in mirror_command))

    def test_build_refresh_plan_allows_ncaaf_source_mode_without_source_repo_path(self) -> None:
        from syndicate.features.shared import ops_refresh

        module = ops_refresh._refresh_script_module()
        missing_root = Path("C:/definitely_missing_ncaaf_compare_repo")
        with patch.object(module, "_source_repo_root", return_value=missing_root), patch("syndicate.features.shared.ops_refresh._refresh_script_module", return_value=module):
            plan = ops_refresh.build_refresh_plan(date="2026-10-01", sports="ncaaf", execution_mode="source")

        self.assertTrue(plan["ok"])
        result = plan["results"][0]
        self.assertTrue(result["ok"])
        self.assertEqual(result["generation_mode"], "local_artifact_bundle")
        self.assertEqual((result.get("generation") or {}).get("kind"), "local_artifact_bundle")
        self.assertEqual(result["source_repo"], str(missing_root))
        refresh_steps = result.get("refresh_steps") or []
        self.assertEqual(len(refresh_steps), 1)
        command = refresh_steps[0].get("command") or []
        self.assertNotIn("--source-root", command)

    def test_build_refresh_plan_uses_ncaaf_existing_mirror_command_in_mirror_only_mode(self) -> None:
        from syndicate.features.shared import ops_refresh

        plan = ops_refresh.build_refresh_plan(date="2026-10-01", sports="ncaaf", mirror_only=True)

        self.assertTrue(plan["ok"])
        result = plan["results"][0]
        self.assertEqual((result.get("generation") or {}).get("kind"), "none")
        self.assertEqual((result.get("ingestion") or {}).get("kind"), "mirror_script")
        self.assertTrue((result.get("ingestion") or {}).get("hosted_safe"))
        self.assertEqual(((result.get("ingestion") or {}).get("contract") or {}).get("kind"), "artifact_bundle_or_existing_mirror")
        self.assertEqual(result["refresh_steps"], [])
        mirror = result.get("mirror") or {}
        self.assertTrue(mirror.get("ok"))
        self.assertTrue(mirror.get("dry_run"))
        command = mirror.get("command") or []
        self.assertIn("refresh_ncaaf_source_mirror.ps1", " ".join(str(part) for part in command))
        self.assertIn("-UseExistingMirrorArtifacts", command)

    def test_build_refresh_plan_uses_ncaaf_artifact_root_when_configured(self) -> None:
        from syndicate.features.shared import ops_refresh

        with patch.dict(os.environ, {"SYNDICATE_ARTIFACT_ROOT_NCAAF": "C:/published/ncaaf-bundle"}, clear=False):
            plan = ops_refresh.build_refresh_plan(date="2026-10-01", sports="ncaaf", execution_mode="ingest")

        self.assertTrue(plan["ok"])
        result = plan["results"][0]
        self.assertEqual((result.get("generation") or {}).get("kind"), "none")
        self.assertEqual((result.get("ingestion") or {}).get("kind"), "mirror_script")
        self.assertTrue((result.get("ingestion") or {}).get("hosted_safe"))
        self.assertEqual(((result.get("ingestion") or {}).get("contract") or {}).get("kind"), "artifact_bundle_or_existing_mirror")
        command = ((result.get("mirror") or {}).get("command") or [])
        self.assertIn("-SourceArtifactRoot", command)
        self.assertIn("C:/published/ncaaf-bundle", command)

    def test_odds_history_inspect_requires_sport_and_date(self) -> None:
        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False):
            response = self.client.get(
                "/api/ops/odds-history/inspect?sport=wnba",
                headers={"X-Admin-Token": "secret-token"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()["ok"])

    def test_odds_history_inspect_flags_content_collisions(self) -> None:
        # Mirrors the real symptom confirmed live 2026-07-29: distinct
        # market_id keys (different players/markets) whose stored history
        # is byte-identical -- a write-side collision, not a coincidence.
        shared_history = [
            {"current_line": 9.5, "last_odds": -110, "captured_at": "2026-07-29T10:00:00Z"},
            {"current_line": 24.5, "last_odds": -110, "captured_at": "2026-07-29T12:00:00Z"},
        ]
        payload = {
            "markets": {
                "WNBA:401857098:THREES:kahleah_copper:1.5": {
                    "market_id": "WNBA:401857098:THREES:kahleah_copper:1.5",
                    "last_line": 24.5,
                    "last_odds": -110,
                    "history": shared_history,
                },
                "WNBA:401857098:RA:alyssa_thomas:16.5": {
                    "market_id": "WNBA:401857098:RA:alyssa_thomas:16.5",
                    "last_line": 24.5,
                    "last_odds": -110,
                    "history": shared_history,
                },
                "WNBA:401857098:TOTAL::171.5": {
                    "market_id": "WNBA:401857098:TOTAL::171.5",
                    "last_line": 171.5,
                    "last_odds": -110,
                    "history": [{"current_line": 171.5, "last_odds": -110, "captured_at": "2026-07-29T10:00:00Z"}],
                },
            }
        }
        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False), patch(
            "syndicate.features.shared.odds_control_plane.load_odds_history_payload_for_sport",
            return_value=payload,
        ), patch(
            "syndicate.features.shared.odds_control_plane.odds_history_path_status_for_sport",
            return_value={"active_path": "fake/path.json"},
        ):
            response = self.client.get(
                "/api/ops/odds-history/inspect?sport=wnba&date=2026-07-29",
                headers={"X-Admin-Token": "secret-token"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["market_count"], 3)
        collisions = list(body["content_collisions"].values())
        self.assertEqual(len(collisions), 1)
        self.assertEqual(
            set(collisions[0]),
            {"WNBA:401857098:THREES:kahleah_copper:1.5", "WNBA:401857098:RA:alyssa_thomas:16.5"},
        )

    def test_wnba_artifact_counts_requires_date(self) -> None:
        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False):
            response = self.client.get(
                "/api/ops/wnba/artifact-counts",
                headers={"X-Admin-Token": "secret-token"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()["ok"])

    def test_wnba_artifact_counts_reports_row_counts(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            fake_root = Path(tmp_dir) / "wnba_source"
            processed = fake_root / "data" / "processed"
            processed.mkdir(parents=True, exist_ok=True)
            (processed / "game_cards_2026-07-13.csv").write_text(
                "date,home_tri,away_tri\n2026-07-13,ATL,LAS\n2026-07-13,MIN,PHX\n",
                encoding="utf-8",
            )
            (processed / "props_recommendations_top_by_game_2026-07-13.json").write_text(
                json.dumps({"date": "2026-07-13", "data": []}),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False), patch(
                "syndicate.features.shared.source_roots.preferred_artifact_roots",
                return_value=[fake_root],
            ), patch(
                "syndicate.features.wnba.sources.processed_root",
                return_value=processed,
            ):
                response = self.client.get(
                    "/api/ops/wnba/artifact-counts?date=2026-07-13",
                    headers={"X-Admin-Token": "secret-token"},
                )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        results = payload["results"]
        game_cards_entries = results["game_cards_2026-07-13.csv"]
        self.assertEqual(len(game_cards_entries), 1)
        self.assertTrue(game_cards_entries[0]["exists"])
        self.assertEqual(game_cards_entries[0]["data_rows"], 2)
        self.assertTrue(game_cards_entries[0]["is_processed_root_default"])
        top_by_game_entries = results["props_recommendations_top_by_game_2026-07-13.json"]
        self.assertTrue(top_by_game_entries[0]["exists"])
        self.assertEqual(top_by_game_entries[0]["data_rows"], 0)
        self.assertFalse(results["props_recommendations_2026-07-13.csv"][0]["exists"])

    def test_ops_page_requires_admin_token(self) -> None:
        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False):
            response = self.client.get("/ops/odds-refresh")

        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.get_json()["ok"])

    def test_ops_page_renders_status_and_plan(self) -> None:
        fake_status = {
            "refresh_status": {
                "manifest_path": "reports/refresh_status/latest/refresh_status_latest.json",
                    "manifest": {"date": "2026-05-22", "refreshOdds": True, "artifactsDir": "reports/x", "generatedAt": "2026-05-22T12:00:00Z", "finishedAt": "2026-05-22T12:30:00Z"},
                "artifacts": {"odds_refresh": {"path": "reports/x/odds_refresh.json", "exists": True}},
                "mirror_manifests": [
                    {
                        "sport": "mlb",
                        "path": "data/mlb_source/manifests/mirror_refresh_latest.json",
                        "exists": True,
                        "date": "2026-05-19",
                        "copied_artifact_count": 14,
                        "artifact_groups": {"daily": 10, "eval": 4},
                            "manifest": {"sourceRepo": "C:/repos/mlb_source_bundle"},
                    }
                ],
                "runtime": {"state": "finished", "detail": "Latest refresh run completed successfully.", "pid": 4321, "elapsed_seconds": 1800, "runtime_budget_seconds": 14400},
            },
            "daily_update": {
                "manifest": {"date": "2026-05-19", "generatedAt": "2026-05-19T12:00:00Z", "completedAt": "2026-05-19T12:45:00Z"},
                "checkpoint": {"currentStage": "refresh_gate"},
                "run_state": {"currentStage": "refresh_gate"},
                "runtime": {"elapsed_seconds": 2700, "runtime_budget_seconds": 14400},
                "checkpoint_path": "reports/daily_update/latest/unified_daily_update_latest_checkpoint.json",
                "run_state_path": "reports/daily_update/latest/unified_daily_update_latest_run_state.json",
            },
        }
        fake_plan = {
            "ok": True,
            "date": "2026-05-20",
            "phase": "live",
            "sports": ["mlb"],
            "skip_mirror": True,
            "mirror_only": False,
            "results": [
                {
                    "sport": "mlb",
                    "ok": True,
                    "notes": "MLB live refresh",
                        "source_repo": "C:/repos/mlb_source_bundle",
                    "generation": {"kind": "source_repo", "source_dependency": "source_repo", "hosted_safe": False},
                    "ingestion": {"kind": "mirror_script", "source_dependency": "local_artifacts", "hosted_safe": True, "contract": {"kind": "artifact_bundle_or_existing_mirror"}},
                    "refresh_steps": [
                        {
                            "name": "mlb_oddsapi_refresh",
                            "ok": True,
                            "description": "Refresh MLB markets",
                            "command": ["python", "scripts/refresh_mlb_oddsapi.py"],
                        }
                    ],
                    "mirror": {
                        "ok": True,
                        "command": ["powershell.exe", "-File", "refresh_mlb_source_mirror.ps1"],
                    },
                }
            ],
        }
        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False), patch(
            "syndicate.blueprints.ops.load_latest_refresh_status",
            return_value=fake_status,
        ), patch(
            "syndicate.blueprints.ops.build_refresh_plan",
            return_value=fake_plan,
        ):
            response = self.client.get(
                "/ops/odds-refresh?phase=live&sports=mlb&skip_mirror=1",
                headers={"X-Admin-Token": "secret-token"},
            )

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Odds refresh control plane", html)
        self.assertIn("Persisted refresh status", html)
        self.assertIn("Dry-run execution plan", html)
        self.assertIn("mlb_oddsapi_refresh", html)
        self.assertIn("skip mirror", html.lower())
        self.assertIn("Refresh Plan View", html)
        self.assertIn("Refresh state: finished", html)
        self.assertIn("Mirror manifests", html)
        self.assertIn("Copied 14 artifacts", html)
        self.assertIn("Contract: artifact_bundle_or_existing_mirror", html)
        self.assertIn("Source repo: C:/repos/mlb_source_bundle", html)

    def test_ops_page_renders_run_form_posting_to_run_endpoint(self) -> None:
        fake_status = {"refresh_status": {"mirror_manifests": [], "runtime": {"state": "idle", "detail": "No active refresh run."}}, "daily_update": {"manifest": None}}
        fake_plan = {"ok": True, "date": "2026-05-20", "phase": "all", "sports": ["mlb"], "skip_mirror": False, "mirror_only": False, "results": []}
        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False), patch(
            "syndicate.blueprints.ops.load_latest_refresh_status",
            return_value=fake_status,
        ), patch(
            "syndicate.blueprints.ops.build_refresh_plan",
            return_value=fake_plan,
        ):
            response = self.client.get(
                "/ops/odds-refresh?force_refresh=1&mode=full",
                headers={"X-Admin-Token": "secret-token"},
            )

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('action="/ops/odds-refresh/run"', html)
        self.assertIn("Run Refresh Now", html)
        self.assertIn('name="mode"', html)
        self.assertIn('<option value="full" selected>full</option>', html)

    def test_ops_page_labels_bundle_local_generation_as_source_context(self) -> None:
        fake_status = {"refresh_status": {"mirror_manifests": [], "runtime": {"state": "idle", "detail": "No active refresh run."}}, "daily_update": {"manifest": None}}
        fake_plan = {
            "ok": True,
            "date": "2026-10-01",
            "phase": "all",
            "sports": ["ncaaf"],
            "skip_mirror": False,
            "mirror_only": False,
            "results": [
                {
                    "sport": "ncaaf",
                    "ok": True,
                    "notes": "NCAAF local artifact bundle refresh",
                    "source_repo": "C:/repos/NCAAFCompare",
                    "generation": {"kind": "local_artifact_bundle", "source_dependency": "local_artifact_bundle", "hosted_safe": True},
                    "ingestion": {"kind": "mirror_script", "source_dependency": "local_artifact_bundle", "hosted_safe": False, "contract": {"kind": "artifact_bundle_or_existing_mirror"}},
                    "refresh_steps": [
                        {
                            "name": "ncaaf_lines_snapshot",
                            "ok": True,
                            "description": "Refresh NCAAF lines",
                            "command": ["python", "scripts/refresh_ncaaf_oddsapi.py", "--artifact-root", "data/ncaaf_source/source_artifacts"],
                        }
                    ],
                    "mirror": {
                        "ok": True,
                        "command": ["powershell.exe", "-File", "refresh_ncaaf_source_mirror.ps1", "-SourceArtifactRoot", "data/ncaaf_source/source_artifacts"],
                    },
                }
            ],
        }
        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False), patch(
            "syndicate.blueprints.ops.load_latest_refresh_status",
            return_value=fake_status,
        ), patch(
            "syndicate.blueprints.ops.build_refresh_plan",
            return_value=fake_plan,
        ):
            response = self.client.get(
                "/ops/odds-refresh?sports=ncaaf",
                headers={"X-Admin-Token": "secret-token"},
            )

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Source context: C:/repos/NCAAFCompare", html)
        self.assertNotIn("Source repo: C:/repos/NCAAFCompare", html)

    def test_full_refresh_run_uses_full_mode(self) -> None:
        def _fake_launch_refresh_run(**_: object) -> dict[str, object]:
            return {"ok": True, "pid": 4343, "run_stamp": "20260520_123100", "date": "2026-05-20", "state": "running"}

        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False), patch(
            "syndicate.blueprints.ops.launch_refresh_run",
            side_effect=_fake_launch_refresh_run,
        ) as mocked, patch("syndicate.features.shared.ops_refresh._reports_root", return_value=Path(tempfile.gettempdir()) / "syndicate-test-reports"), patch(
            "syndicate.blueprints.ops.reports_root",
            return_value=Path(tempfile.gettempdir()) / "syndicate-test-reports",
        ):
            response = self.client.post(
                "/api/ops/full-refresh/run",
                json={"sports": "mlb", "phase": "live", "skip_mirror": True, "dry_run": True},
                headers={"X-Admin-Token": "secret-token"},
            )

            self.assertEqual(response.status_code, 202)
            payload = response.get_json()
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["status"], "started")
            self.assertTrue(payload["job_id"])
            mocked.assert_called_once()
            self.assertEqual(mocked.call_args.kwargs.get("mode"), "full")
            self.assertEqual(mocked.call_args.kwargs.get("launch_mode"), "manifest_only")

    def test_full_refresh_run_threads_force_refresh_through(self) -> None:
        def _fake_launch_refresh_run(**_: object) -> dict[str, object]:
            return {"ok": True, "pid": 4343, "run_stamp": "20260520_123100", "date": "2026-05-20", "state": "running"}

        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False), patch(
            "syndicate.blueprints.ops.launch_refresh_run",
            side_effect=_fake_launch_refresh_run,
        ) as mocked, patch("syndicate.features.shared.ops_refresh._reports_root", return_value=Path(tempfile.gettempdir()) / "syndicate-test-reports"), patch(
            "syndicate.blueprints.ops.reports_root",
            return_value=Path(tempfile.gettempdir()) / "syndicate-test-reports",
        ):
            response = self.client.post(
                "/api/ops/full-refresh/run",
                json={"sports": "wnba", "date": "2026-07-13", "force_refresh": True},
                headers={"X-Admin-Token": "secret-token"},
            )

            self.assertEqual(response.status_code, 202)
            mocked.assert_called_once()
            self.assertTrue(mocked.call_args.kwargs.get("force_refresh"))

    def test_odds_refresh_run_defaults_force_refresh_to_false(self) -> None:
        def _fake_launch_refresh_run(**_: object) -> dict[str, object]:
            return {"ok": True, "pid": 4344, "run_stamp": "20260520_123101", "date": "2026-05-20", "state": "running"}

        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False), patch(
            "syndicate.blueprints.ops.launch_refresh_run",
            side_effect=_fake_launch_refresh_run,
        ) as mocked, patch("syndicate.features.shared.ops_refresh._reports_root", return_value=Path(tempfile.gettempdir()) / "syndicate-test-reports"), patch(
            "syndicate.blueprints.ops.reports_root",
            return_value=Path(tempfile.gettempdir()) / "syndicate-test-reports",
        ):
            response = self.client.post(
                "/api/ops/odds-refresh/run",
                json={"sports": "wnba", "date": "2026-07-13"},
                headers={"X-Admin-Token": "secret-token"},
            )

            self.assertEqual(response.status_code, 202)
            mocked.assert_called_once()
            self.assertFalse(mocked.call_args.kwargs.get("force_refresh"))

    def test_run_endpoint_starts_odds_refresh_job(self) -> None:
        def _fake_launch_refresh_run(**_: object) -> dict[str, object]:
            return {"ok": True, "pid": 4242, "run_stamp": "20260520_123100", "date": "2026-05-20", "state": "running"}

        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False), patch(
            "syndicate.blueprints.ops.launch_refresh_run",
            side_effect=_fake_launch_refresh_run,
        ) as mocked, patch("syndicate.features.shared.ops_refresh._reports_root", return_value=Path(tempfile.gettempdir()) / "syndicate-test-reports"), patch(
            "syndicate.blueprints.ops.reports_root",
            return_value=Path(tempfile.gettempdir()) / "syndicate-test-reports",
        ):
            response = self.client.post(
                "/api/ops/odds-refresh/run",
                json={"sports": "mlb", "phase": "live", "skip_mirror": True, "dry_run": True},
                headers={"X-Admin-Token": "secret-token"},
            )

        self.assertEqual(response.status_code, 202)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "started")
        self.assertTrue(payload["job_id"])
        mocked.assert_called_once()
        self.assertEqual(mocked.call_args.kwargs.get("mode"), "fast")

    def test_run_page_route_starts_odds_refresh_job_and_redirects(self) -> None:
        def _fake_launch_refresh_run(**_: object) -> dict[str, object]:
            return {"ok": True, "pid": 5252, "run_stamp": "20260520_123100", "date": "2026-05-20", "state": "running"}

        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False), patch(
            "syndicate.blueprints.ops.launch_refresh_run",
            side_effect=_fake_launch_refresh_run,
        ) as mocked, patch("syndicate.features.shared.ops_refresh._reports_root", return_value=Path(tempfile.gettempdir()) / "syndicate-test-reports"), patch(
            "syndicate.blueprints.ops.reports_root",
            return_value=Path(tempfile.gettempdir()) / "syndicate-test-reports",
        ):
            response = self.client.post(
                "/ops/odds-refresh/run",
                data={"sports": "mlb", "phase": "live", "skip_mirror": "1", "dry_run": "1", "admin_token": "secret-token"},
                headers={"X-Admin-Token": "secret-token"},
            )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/ops/odds-refresh?", response.headers.get("Location") or "")
        mocked.assert_called_once()
        self.assertEqual(mocked.call_args.kwargs.get("mode"), "fast")

    def test_run_page_route_accepts_admin_token_from_form_body_alone(self) -> None:
        # Regression: a real browser submitting the HTML "Run Refresh Now" form
        # only sends admin_token as a form field, with no X-Admin-Token header
        # and no admin_token query string. This must still authenticate.
        def _fake_launch_refresh_run(**_: object) -> dict[str, object]:
            return {"ok": True, "pid": 5252, "run_stamp": "20260520_123100", "date": "2026-05-20", "state": "running"}

        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False), patch(
            "syndicate.blueprints.ops.launch_refresh_run",
            side_effect=_fake_launch_refresh_run,
        ) as mocked:
            response = self.client.post(
                "/ops/odds-refresh/run",
                data={"sports": "wnba", "phase": "live", "force_refresh": "1", "mode": "full", "admin_token": "secret-token"},
            )

        self.assertEqual(response.status_code, 302)
        self.assertIn("admin_token=secret-token", response.headers.get("Location") or "")
        mocked.assert_called_once()
        self.assertTrue(mocked.call_args.kwargs.get("force_refresh"))

    def test_cancel_endpoint_returns_cancel_payload(self) -> None:
        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False), patch(
            "syndicate.blueprints.ops.cancel_latest_refresh_run",
            return_value={"ok": True, "pid": 4321, "state": "canceled", "detail": "Refresh run canceled."},
        ) as mocked:
            response = self.client.post(
                "/api/ops/odds-refresh/cancel",
                headers={"X-Admin-Token": "secret-token"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["cancel"]["state"], "canceled")
        mocked.assert_called_once()

    def test_logs_endpoint_returns_plaintext(self) -> None:
        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False), patch(
            "syndicate.blueprints.ops.load_latest_refresh_log",
            return_value={"stream": "stderr", "content": "line1\nline2", "tail": "line1\nline2", "path": "reports/x.log", "exists": True},
        ):
            response = self.client.get(
                "/api/ops/odds-refresh/logs?stream=stderr&raw=1",
                headers={"X-Admin-Token": "secret-token"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True), "line1\nline2")

    def test_logs_endpoint_can_return_wnba_source_log(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            reports_root = root / "reports"
            refresh_latest = reports_root / "refresh_status" / "latest"
            source_root = root / "data" / "wnba_source"
            source_logs = source_root / "logs"
            refresh_latest.mkdir(parents=True, exist_ok=True)
            source_logs.mkdir(parents=True, exist_ok=True)

            log_path = source_logs / "syndicate_refresh_oddsapi_props_2026-07-10.log"
            log_content = "before_smart_sim\nSMART_SIM_RETURNED date=2026-07-10 workers=1 n_sims=150\nSMART_SIM_RESULT_LOAD_COMPLETE date=2026-07-10 rows=105\nSMART_SIM_MERGE_COMPLETE date=2026-07-10 rows=105\nafter_smart_sim\nPredictions stage finished for 2026-07-10: rc_pred=0, rows=105\n"
            log_path.write_text(log_content, encoding="utf-8")

            (refresh_latest / "refresh_status_latest.json").write_text(
                json.dumps(
                    {
                        "date": "2026-07-10",
                        "runStamp": "20260710_165843",
                        "artifactsDir": str(reports_root / "migration_runs" / "2026-07-10" / "odds_refresh_20260710_165843"),
                        "results": [
                            {
                                "sport": "wnba",
                                "source_repo": str(source_root),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {"ADMIN_TOKEN": "secret-token", "SYNDICATE_REPORTS_ROOT": str(reports_root)},
                clear=False,
            ):
                response = self.client.get(
                    "/api/ops/odds-refresh/logs?stream=wnba&raw=1",
                    headers={"X-Admin-Token": "secret-token"},
                )

        self.assertEqual(response.status_code, 200)
        self.assertIn("SMART_SIM_RETURNED date=2026-07-10", response.get_data(as_text=True))
        self.assertIn("Predictions stage finished for 2026-07-10", response.get_data(as_text=True))

    def test_launch_refresh_run_uses_wrapper_command(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            reports_root = repo_root / "reports"
            with patch.dict(os.environ, {"SYNDICATE_REPORTS_ROOT": str(reports_root)}, clear=False), patch(
                "syndicate.features.shared.ops_refresh.REPO_ROOT", repo_root
            ), patch("syndicate.features.shared.ops_refresh.subprocess.Popen") as mocked_popen:
                mocked_popen.return_value.pid = 2468
                from syndicate.features.shared import ops_refresh

                result = ops_refresh.launch_refresh_run(sports="mlb", phase="live", dry_run=True)

            self.assertTrue(result["ok"])
            called_command = mocked_popen.call_args.args[0]
            self.assertIn(str(repo_root / "scripts" / "run_refresh_odds_job.py"), called_command)
            self.assertIn("--", called_command)
            self.assertIn(str(repo_root / "scripts" / "refresh_odds_sources.py"), called_command)

    def test_launch_refresh_run_includes_execution_mode_flag(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            reports_root = repo_root / "reports"
            with patch.dict(os.environ, {"SYNDICATE_REPORTS_ROOT": str(reports_root)}, clear=False), patch(
                "syndicate.features.shared.ops_refresh.REPO_ROOT", repo_root
            ), patch("syndicate.features.shared.ops_refresh.subprocess.Popen") as mocked_popen:
                mocked_popen.return_value.pid = 2468
                from syndicate.features.shared import ops_refresh

                result = ops_refresh.launch_refresh_run(sports="mlb", phase="live", execution_mode="ingest", dry_run=True)

            self.assertTrue(result["ok"])
            called_command = mocked_popen.call_args.args[0]
            self.assertIn("--execution-mode", called_command)
            self.assertIn("ingest", called_command)

    def test_launch_refresh_run_scopes_force_refresh_to_specified_sports(self) -> None:
        # An NBA-only lineup/injury change must not also force WNBA's
        # refresh script to bypass its cache -- --force-refresh-sports scopes
        # --force-refresh to just the sport(s) that actually changed.
        with TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            reports_root = repo_root / "reports"
            with patch.dict(os.environ, {"SYNDICATE_REPORTS_ROOT": str(reports_root)}, clear=False), patch(
                "syndicate.features.shared.ops_refresh.REPO_ROOT", repo_root
            ), patch("syndicate.features.shared.ops_refresh.subprocess.Popen") as mocked_popen:
                mocked_popen.return_value.pid = 2469
                from syndicate.features.shared import ops_refresh

                result = ops_refresh.launch_refresh_run(
                    sports="nba,wnba", phase="live", dry_run=True, force_refresh=True, force_refresh_sports="nba"
                )

            self.assertTrue(result["ok"])
            called_command = mocked_popen.call_args.args[0]
            self.assertIn("--force-refresh", called_command)
            self.assertIn("--force-refresh-sports", called_command)
            self.assertIn("nba", called_command)

    def test_launch_refresh_run_omits_force_refresh_sports_when_not_provided(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            reports_root = repo_root / "reports"
            with patch.dict(os.environ, {"SYNDICATE_REPORTS_ROOT": str(reports_root)}, clear=False), patch(
                "syndicate.features.shared.ops_refresh.REPO_ROOT", repo_root
            ), patch("syndicate.features.shared.ops_refresh.subprocess.Popen") as mocked_popen:
                mocked_popen.return_value.pid = 2470
                from syndicate.features.shared import ops_refresh

                result = ops_refresh.launch_refresh_run(sports="nba,wnba", phase="live", dry_run=True, force_refresh=True)

            self.assertTrue(result["ok"])
            called_command = mocked_popen.call_args.args[0]
            self.assertIn("--force-refresh", called_command)
            self.assertNotIn("--force-refresh-sports", called_command)

    def test_launch_refresh_run_includes_wnba_only_matchups_when_force_refresh_and_scoped(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            reports_root = repo_root / "reports"
            with patch.dict(os.environ, {"SYNDICATE_REPORTS_ROOT": str(reports_root)}, clear=False), patch(
                "syndicate.features.shared.ops_refresh.REPO_ROOT", repo_root
            ), patch("syndicate.features.shared.ops_refresh.subprocess.Popen") as mocked_popen:
                mocked_popen.return_value.pid = 2471
                from syndicate.features.shared import ops_refresh

                result = ops_refresh.launch_refresh_run(
                    sports="wnba", phase="live", dry_run=True, force_refresh=True, wnba_only_matchups="LVA-NYL"
                )

            self.assertTrue(result["ok"])
            called_command = mocked_popen.call_args.args[0]
            self.assertIn("--wnba-only-matchups", called_command)
            self.assertIn("LVA-NYL", called_command)

    def test_launch_refresh_run_omits_wnba_only_matchups_when_not_provided(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            reports_root = repo_root / "reports"
            with patch.dict(os.environ, {"SYNDICATE_REPORTS_ROOT": str(reports_root)}, clear=False), patch(
                "syndicate.features.shared.ops_refresh.REPO_ROOT", repo_root
            ), patch("syndicate.features.shared.ops_refresh.subprocess.Popen") as mocked_popen:
                mocked_popen.return_value.pid = 2472
                from syndicate.features.shared import ops_refresh

                result = ops_refresh.launch_refresh_run(sports="wnba", phase="live", dry_run=True, force_refresh=True)

            self.assertTrue(result["ok"])
            called_command = mocked_popen.call_args.args[0]
            self.assertNotIn("--wnba-only-matchups", called_command)

    def test_launch_refresh_run_omits_wnba_only_matchups_when_force_refresh_false(self) -> None:
        # Without --force-refresh, refresh_wnba_oddsapi_props.py's own
        # cache-reuse gate skips the run before scoping would ever matter --
        # this pairing is structural, not left to caller discipline.
        with TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            reports_root = repo_root / "reports"
            with patch.dict(os.environ, {"SYNDICATE_REPORTS_ROOT": str(reports_root)}, clear=False), patch(
                "syndicate.features.shared.ops_refresh.REPO_ROOT", repo_root
            ), patch("syndicate.features.shared.ops_refresh.subprocess.Popen") as mocked_popen:
                mocked_popen.return_value.pid = 2473
                from syndicate.features.shared import ops_refresh

                result = ops_refresh.launch_refresh_run(
                    sports="wnba", phase="live", dry_run=True, force_refresh=False, wnba_only_matchups="LVA-NYL"
                )

            self.assertTrue(result["ok"])
            called_command = mocked_popen.call_args.args[0]
            self.assertNotIn("--wnba-only-matchups", called_command)

    def test_launch_refresh_run_uses_render_live_refresh_defaults_when_args_are_omitted(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            reports_root = repo_root / "reports"
            with patch.dict(
                os.environ,
                {
                    "SYNDICATE_REPORTS_ROOT": str(reports_root),
                    "SYNDICATE_LIVE_ODDS_REFRESH_MODE": "full",
                    "SYNDICATE_LIVE_ODDS_REFRESH_PHASE": "live",
                    "SYNDICATE_LIVE_ODDS_REFRESH_REGIONS": "us",
                    "SYNDICATE_LIVE_ODDS_REFRESH_EXECUTION_MODE": "source",
                    "SYNDICATE_LIVE_ODDS_REFRESH_SKIP_MIRROR": "true",
                },
                clear=False,
            ), patch("syndicate.features.shared.ops_refresh.REPO_ROOT", repo_root), patch(
                "syndicate.features.shared.ops_refresh.subprocess.Popen"
            ) as mocked_popen:
                mocked_popen.return_value.pid = 2468
                from syndicate.features.shared import ops_refresh

                result = ops_refresh.launch_refresh_run(
                    sports="mlb",
                    mode=None,
                    phase=None,
                    regions=None,
                    execution_mode=None,
                    skip_mirror=None,
                    dry_run=True,
                )

            self.assertTrue(result["ok"])
            called_command = mocked_popen.call_args.args[0]
            self.assertIn("full", called_command)
            self.assertIn("live", called_command)
            self.assertIn("source", called_command)
            self.assertIn("--skip-mirror", called_command)

    def test_launch_refresh_run_supports_manifest_only_mode(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            reports_root = repo_root / "reports"
            with patch.dict(
                os.environ,
                {"SYNDICATE_REPORTS_ROOT": str(reports_root), "SYNDICATE_REFRESH_LAUNCH_MODE": "manifest_only"},
                clear=False,
            ), patch("syndicate.features.shared.ops_refresh.REPO_ROOT", repo_root), patch(
                "syndicate.features.shared.ops_refresh.subprocess.Popen"
            ) as mocked_popen:
                from syndicate.features.shared import ops_refresh

                result = ops_refresh.launch_refresh_run(sports="mlb", phase="live", dry_run=True)

            mocked_popen.assert_not_called()
            self.assertTrue(result["ok"])
            self.assertIsNone(result["pid"])
            self.assertEqual(result["launch_mode"], "manifest_only")
            self.assertEqual(result["launch_owner"], "external_runner")
            self.assertEqual(result["state"], "pending_external")
            self.assertEqual((result.get("external_runner") or {}).get("kind"), "external_runner")

            latest_manifest = reports_root / "refresh_status" / "latest" / "refresh_status_latest.json"
            payload = json.loads(latest_manifest.read_text(encoding="utf-8"))
            self.assertEqual(payload["state"], "pending_external")
            self.assertEqual(payload["launchMode"], "manifest_only")
            self.assertEqual(payload["launchOwner"], "external_runner")
            self.assertEqual((payload.get("externalRunner") or {}).get("queue_state"), "queued")

    def test_launch_refresh_run_defaults_to_detached_subprocess_on_render(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            reports_root = repo_root / "reports"
            with patch.dict(
                os.environ,
                {"SYNDICATE_REPORTS_ROOT": str(reports_root), "RENDER_SERVICE_ID": "svc-123"},
                clear=False,
            ), patch("syndicate.features.shared.ops_refresh.REPO_ROOT", repo_root), patch(
                "syndicate.features.shared.ops_refresh.subprocess.Popen"
            ) as mocked_popen:
                from syndicate.features.shared import ops_refresh

                result = ops_refresh.launch_refresh_run(sports="mlb", phase="live", dry_run=True)

            mocked_popen.assert_called_once()
            self.assertTrue(result["ok"])
            self.assertIsNotNone(result["pid"])
            self.assertEqual(result["launch_mode"], "detached_subprocess")
            self.assertEqual(result["launch_owner"], "web_process")
            self.assertEqual(result["state"], "running")

    def test_launch_refresh_run_supports_external_runner_mode_alias(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            reports_root = repo_root / "reports"
            with patch.dict(
                os.environ,
                {"SYNDICATE_REPORTS_ROOT": str(reports_root), "SYNDICATE_REFRESH_LAUNCH_MODE": "external_runner"},
                clear=False,
            ), patch("syndicate.features.shared.ops_refresh.REPO_ROOT", repo_root), patch(
                "syndicate.features.shared.ops_refresh.subprocess.Popen"
            ) as mocked_popen:
                from syndicate.features.shared import ops_refresh

                result = ops_refresh.launch_refresh_run(sports="mlb", phase="live", dry_run=True)

            mocked_popen.assert_not_called()
            self.assertTrue(result["ok"])
            self.assertEqual(result["launch_mode"], "external_runner")
            self.assertEqual(result["launch_owner"], "external_runner")
            self.assertEqual(result["state"], "pending_external")

    def test_launch_refresh_run_supports_launch_mode_override(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            reports_root = repo_root / "reports"
            with patch.dict(
                os.environ,
                {"SYNDICATE_REPORTS_ROOT": str(reports_root), "SYNDICATE_REFRESH_LAUNCH_MODE": "detached_subprocess"},
                clear=False,
            ), patch("syndicate.features.shared.ops_refresh.REPO_ROOT", repo_root), patch(
                "syndicate.features.shared.ops_refresh.subprocess.Popen"
            ) as mocked_popen:
                from syndicate.features.shared import ops_refresh

                result = ops_refresh.launch_refresh_run(sports="mlb", phase="live", dry_run=True, launch_mode="manifest_only")

            mocked_popen.assert_not_called()
            self.assertTrue(result["ok"])
            self.assertEqual(result["launch_mode"], "manifest_only")
            self.assertEqual(result["launch_owner"], "external_runner")
            self.assertEqual(result["state"], "pending_external")

    def test_cancel_latest_refresh_run_supports_manifest_only_queue(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            reports_root = repo_root / "reports"
            latest_dir = reports_root / "refresh_status" / "latest"
            run_dir = reports_root / "migration_runs" / "2026-05-22" / "odds_refresh_20260522_120000"
            latest_dir.mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "refresh_and_gate_run.json").write_text(
                json.dumps({"state": "pending_external"}),
                encoding="utf-8",
            )
            latest_manifest = latest_dir / "refresh_status_latest.json"
            latest_manifest.write_text(
                json.dumps(
                    {
                        "date": "2026-05-22",
                        "runStamp": "20260522_120000",
                        "artifactsDir": str(run_dir),
                        "runSummaryPath": str(run_dir / "refresh_and_gate_run.json"),
                        "state": "pending_external",
                    }
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"SYNDICATE_REPORTS_ROOT": str(reports_root)}, clear=False), patch(
                "syndicate.features.shared.ops_refresh.REPO_ROOT", repo_root
            ):
                from syndicate.features.shared import ops_refresh

                result = ops_refresh.cancel_latest_refresh_run()

            self.assertTrue(result["ok"])
            self.assertIsNone(result["pid"])
            self.assertEqual(result["state"], "canceled")

    def test_assert_no_active_refresh_run_blocks_alive_pid(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            reports_root = repo_root / "reports"
            latest_dir = reports_root / "refresh_status" / "latest"
            latest_dir.mkdir(parents=True, exist_ok=True)
            (latest_dir / "refresh_status_latest.json").write_text(
                json.dumps({"state": "running", "pid": 4321, "externalRunner": {"kind": "external_runner", "queue_state": "running"}}),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"SYNDICATE_REPORTS_ROOT": str(reports_root)}, clear=False), patch(
                "syndicate.features.shared.ops_refresh.REPO_ROOT", repo_root
            ), patch("syndicate.features.shared.ops_refresh._pid_is_running", return_value=True):
                from syndicate.features.shared import ops_refresh

                with self.assertRaises(ValueError):
                    ops_refresh._assert_no_active_refresh_run()

    def test_assert_no_active_refresh_run_blocks_recent_cross_service_pointer(self) -> None:
        # A pid recorded by a DIFFERENT Render service (separate container,
        # separate PID namespace) can never be verified via OS pid liveness
        # from here -- checking it would almost always read "not running"
        # even when genuinely alive elsewhere. Recent-enough cross-service
        # pointers must still block (fail closed), even though
        # _pid_is_running (mocked False here, simulating "no such pid in
        # this container") says otherwise.
        with TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            reports_root = repo_root / "reports"
            latest_dir = reports_root / "refresh_status" / "latest"
            latest_dir.mkdir(parents=True, exist_ok=True)
            (latest_dir / "refresh_status_latest.json").write_text(
                json.dumps(
                    {
                        "state": "running",
                        "pid": 4321,
                        "launcherServiceId": "srv-refresh-worker",
                        "generatedAt": datetime.now(timezone.utc).isoformat(),
                        "externalRunner": {"kind": "external_runner", "queue_state": "running"},
                    }
                ),
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {"SYNDICATE_REPORTS_ROOT": str(reports_root), "RENDER_SERVICE_ID": "srv-live-odds-worker"},
                clear=False,
            ), patch("syndicate.features.shared.ops_refresh.REPO_ROOT", repo_root), patch(
                "syndicate.features.shared.ops_refresh._pid_is_running", return_value=False
            ):
                from syndicate.features.shared import ops_refresh

                with self.assertRaises(ValueError):
                    ops_refresh._assert_no_active_refresh_run()

    def test_assert_no_active_refresh_run_allows_stale_cross_service_pointer(self) -> None:
        # A cross-service pointer old enough that no legitimate refresh run
        # could still be executing is treated as dead, so a crashed run in
        # another service doesn't block launches forever.
        with TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            reports_root = repo_root / "reports"
            latest_dir = reports_root / "refresh_status" / "latest"
            latest_dir.mkdir(parents=True, exist_ok=True)
            stale_generated_at = (datetime.now(timezone.utc) - timedelta(seconds=7200)).isoformat()
            (latest_dir / "refresh_status_latest.json").write_text(
                json.dumps(
                    {
                        "state": "running",
                        "pid": 4321,
                        "launcherServiceId": "srv-refresh-worker",
                        "generatedAt": stale_generated_at,
                        "externalRunner": {"kind": "external_runner", "queue_state": "running"},
                    }
                ),
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {"SYNDICATE_REPORTS_ROOT": str(reports_root), "RENDER_SERVICE_ID": "srv-live-odds-worker"},
                clear=False,
            ), patch("syndicate.features.shared.ops_refresh.REPO_ROOT", repo_root), patch(
                "syndicate.features.shared.ops_refresh._pid_is_running", return_value=False
            ):
                from syndicate.features.shared import ops_refresh

                ops_refresh._assert_no_active_refresh_run()

    def test_refresh_run_still_active_matches_expected_command_within_same_service(self) -> None:
        from syndicate.features.shared import ops_refresh

        with patch.dict(os.environ, {"RENDER_SERVICE_ID": "srv-live-odds-worker"}, clear=False), patch(
            "syndicate.features.shared.ops_refresh._pid_is_running", return_value=True
        ), patch(
            "syndicate.features.shared.ops_refresh._process_cmdline", return_value=["python", "run_refresh_odds_job.py"]
        ):
            manifest = {"pid": 999, "launcherServiceId": "srv-live-odds-worker"}
            run_summary = {"launcherCommand": ["python", "run_refresh_odds_job.py"]}
            self.assertTrue(ops_refresh._refresh_run_still_active(manifest, run_summary=run_summary))

            mismatched_run_summary = {"launcherCommand": ["python", "some_other_script.py"]}
            self.assertFalse(ops_refresh._refresh_run_still_active(manifest, run_summary=mismatched_run_summary))

    def test_refresh_run_still_active_treats_different_instance_as_dead_even_with_matching_pid(self) -> None:
        # Real production bug found while verifying the per-service-lane
        # rebuild: RENDER_SERVICE_ID stays the SAME across a redeploy (same
        # service, fresh container), but the recorded pid can be reoccupied
        # by an unrelated process in the new container. Without checking
        # instance identity, a stale "running" pointer from a PREVIOUS
        # container generation kept blocking the next launch after every
        # redeploy, since _process_matches_expected_command fails OPEN
        # (assumes a match) whenever the command can't be read.
        from syndicate.features.shared import ops_refresh

        with patch.dict(
            os.environ,
            {"RENDER_SERVICE_ID": "srv-live-odds-worker", "RENDER_INSTANCE_ID": "instance-new"},
            clear=False,
        ), patch("syndicate.features.shared.ops_refresh._pid_is_running", return_value=True), patch(
            "syndicate.features.shared.ops_refresh._process_cmdline", return_value=["python", "run_refresh_odds_job.py"]
        ):
            manifest = {
                "pid": 999,
                "launcherServiceId": "srv-live-odds-worker",
                "launcherInstanceId": "instance-old",
            }
            run_summary = {"launcherCommand": ["python", "run_refresh_odds_job.py"]}
            self.assertFalse(ops_refresh._refresh_run_still_active(manifest, run_summary=run_summary))

    def test_refresh_run_still_active_still_checks_pid_when_instance_matches(self) -> None:
        from syndicate.features.shared import ops_refresh

        with patch.dict(
            os.environ,
            {"RENDER_SERVICE_ID": "srv-live-odds-worker", "RENDER_INSTANCE_ID": "instance-current"},
            clear=False,
        ), patch("syndicate.features.shared.ops_refresh._pid_is_running", return_value=True), patch(
            "syndicate.features.shared.ops_refresh._process_cmdline", return_value=["python", "run_refresh_odds_job.py"]
        ):
            manifest = {
                "pid": 999,
                "launcherServiceId": "srv-live-odds-worker",
                "launcherInstanceId": "instance-current",
            }
            run_summary = {"launcherCommand": ["python", "run_refresh_odds_job.py"]}
            self.assertTrue(ops_refresh._refresh_run_still_active(manifest, run_summary=run_summary))

    def test_launch_refresh_run_records_launcher_service_id(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            reports_root = repo_root / "reports"

            with patch.dict(
                os.environ,
                {
                    "SYNDICATE_REPORTS_ROOT": str(reports_root),
                    "RENDER_SERVICE_ID": "srv-live-odds-worker",
                    "RENDER_INSTANCE_ID": "instance-abc",
                },
                clear=False,
            ), patch("syndicate.features.shared.ops_refresh.REPO_ROOT", repo_root), patch(
                "syndicate.features.shared.ops_refresh._assert_no_active_refresh_run"
            ), patch(
                "syndicate.features.shared.ops_refresh.subprocess.Popen"
            ) as mocked_popen:
                mocked_popen.return_value.pid = 8080
                from syndicate.features.shared import ops_refresh

                ops_refresh.launch_refresh_run(sports="mlb", phase="live", dry_run=True)

            manifest = json.loads((reports_root / "refresh_status" / "latest" / "refresh_status_latest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest.get("launcherServiceId"), "srv-live-odds-worker")
            self.assertEqual(manifest.get("launcherInstanceId"), "instance-abc")

    def test_assert_no_active_refresh_run_fails_closed_when_manifest_read_fails(self) -> None:
        # A transient keyvalue-backend read failure must never be treated the
        # same as "no run recorded" -- that fail-open behavior let
        # overlapping refresh_odds_sources.py launches slip past this guard
        # in production, stacking process trees until the container OOMed.
        with TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            reports_root = repo_root / "reports"

            with patch.dict(os.environ, {"SYNDICATE_REPORTS_ROOT": str(reports_root)}, clear=False), patch(
                "syndicate.features.shared.ops_refresh.REPO_ROOT", repo_root
            ), patch(
                "syndicate.features.shared.ops_refresh.read_json_file_result", return_value=(None, False)
            ):
                from syndicate.features.shared import ops_refresh

                with self.assertRaises(ValueError):
                    ops_refresh._assert_no_active_refresh_run()

    def test_assert_no_active_refresh_run_proceeds_when_manifest_genuinely_absent(self) -> None:
        # Local dev/tests (and a genuinely first-ever run) have no manifest
        # file at all -- this must NOT be treated the same as a failed read,
        # or the guard would block every launch forever.
        with TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            reports_root = repo_root / "reports"

            with patch.dict(os.environ, {"SYNDICATE_REPORTS_ROOT": str(reports_root)}, clear=False), patch(
                "syndicate.features.shared.ops_refresh.REPO_ROOT", repo_root
            ):
                from syndicate.features.shared import ops_refresh

                ops_refresh._assert_no_active_refresh_run()

    def test_launch_refresh_run_spawns_subprocess_before_any_manifest_write(self) -> None:
        # launch_refresh_run used to write state="running" with no pid
        # BEFORE spawning the subprocess, then add pid in a second write --
        # a reader landing in that window saw state=="running", pid==None,
        # which _assert_no_active_refresh_run's self-heal logic (mis)treated
        # as "died without updating status" and cleared the way for a new
        # launch while the original was still starting.
        with TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            reports_root = repo_root / "reports"
            call_order: list[str] = []

            class _FakeProcess:
                pid = 7070

            def _fake_popen(*_args: object, **_kwargs: object) -> _FakeProcess:
                call_order.append("popen")
                return _FakeProcess()

            def _record_write(path: Path, payload: dict[str, object]) -> None:
                call_order.append("write")

            with patch.dict(os.environ, {"SYNDICATE_REPORTS_ROOT": str(reports_root)}, clear=False), patch(
                "syndicate.features.shared.ops_refresh.REPO_ROOT", repo_root
            ), patch(
                "syndicate.features.shared.ops_refresh._assert_no_active_refresh_run"
            ), patch(
                "syndicate.features.shared.ops_refresh.write_json_file", side_effect=_record_write
            ), patch(
                "syndicate.features.shared.ops_refresh.subprocess.Popen", side_effect=_fake_popen
            ):
                from syndicate.features.shared import ops_refresh

                ops_refresh.launch_refresh_run(sports="mlb", phase="live", dry_run=True)

            self.assertEqual(call_order[0], "popen")
            self.assertIn("write", call_order[1:])

    def test_launch_refresh_run_includes_pid_in_every_observed_manifest_write(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            reports_root = repo_root / "reports"
            observed_payloads: list[dict[str, object]] = []

            def _record_write(path: Path, payload: dict[str, object]) -> None:
                observed_payloads.append(dict(payload))

            with patch.dict(os.environ, {"SYNDICATE_REPORTS_ROOT": str(reports_root)}, clear=False), patch(
                "syndicate.features.shared.ops_refresh.REPO_ROOT", repo_root
            ), patch(
                "syndicate.features.shared.ops_refresh._assert_no_active_refresh_run"
            ), patch(
                "syndicate.features.shared.ops_refresh.write_json_file", side_effect=_record_write
            ), patch(
                "syndicate.features.shared.ops_refresh.subprocess.Popen"
            ) as mocked_popen:
                mocked_popen.return_value.pid = 5150
                from syndicate.features.shared import ops_refresh

                result = ops_refresh.launch_refresh_run(sports="mlb", phase="live", dry_run=True)

            self.assertTrue(result["ok"])
            self.assertGreaterEqual(len(observed_payloads), 2)
            for payload in observed_payloads:
                self.assertEqual(payload.get("state"), "running")
                self.assertEqual(payload.get("pid"), 5150)

    def test_latest_refresh_context_rejects_mismatched_run_stamp(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            reports_root = repo_root / "reports"
            latest_dir = reports_root / "refresh_status" / "latest"
            run_dir = reports_root / "migration_runs" / "2026-05-22" / "odds_refresh_20260522_120000"
            latest_dir.mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)
            run_summary_path = run_dir / "refresh_and_gate_run.json"
            run_summary_path.write_text(json.dumps({"state": "running", "runStamp": "20260522_120000"}), encoding="utf-8")
            (latest_dir / "refresh_status_latest.json").write_text(
                json.dumps(
                    {
                        "date": "2026-05-22",
                        "runStamp": "20260522_130000",
                        "artifactsDir": str(run_dir),
                        "runSummaryPath": str(run_summary_path),
                        "state": "running",
                    }
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"SYNDICATE_REPORTS_ROOT": str(reports_root)}, clear=False), patch(
                "syndicate.features.shared.ops_refresh.REPO_ROOT", repo_root
            ):
                from syndicate.features.shared import ops_refresh

                context = ops_refresh._latest_refresh_manifest_context()
                self.assertIsNotNone(context.get("consistency_error"))
                self.assertIn("does not match", str(context.get("consistency_error")))
                with self.assertRaises(ValueError):
                    ops_refresh._ensure_refresh_context_consistent(context)

    def test_latest_refresh_context_accepts_legacy_missing_run_stamp(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            reports_root = repo_root / "reports"
            latest_dir = reports_root / "refresh_status" / "latest"
            run_dir = reports_root / "migration_runs" / "2026-05-22" / "odds_refresh_20260522_120000"
            latest_dir.mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)
            run_summary_path = run_dir / "refresh_and_gate_run.json"
            run_summary_path.write_text(json.dumps({"state": "running"}), encoding="utf-8")
            (latest_dir / "refresh_status_latest.json").write_text(
                json.dumps(
                    {
                        "date": "2026-05-22",
                        "artifactsDir": str(run_dir),
                        "runSummaryPath": str(run_summary_path),
                        "state": "running",
                    }
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"SYNDICATE_REPORTS_ROOT": str(reports_root)}, clear=False), patch(
                "syndicate.features.shared.ops_refresh.REPO_ROOT", repo_root
            ):
                from syndicate.features.shared import ops_refresh

                context = ops_refresh._latest_refresh_manifest_context()
                self.assertIsNone(context.get("consistency_error"))
                ops_refresh._ensure_refresh_context_consistent(context)

    def test_launch_refresh_run_publishes_run_summary_before_latest_pointer(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            reports_root = repo_root / "reports"
            call_order: list[str] = []

            def _record_write(path: Path, payload: dict[str, object]) -> None:
                call_order.append(path.name)

            with patch.dict(os.environ, {"SYNDICATE_REPORTS_ROOT": str(reports_root)}, clear=False), patch(
                "syndicate.features.shared.ops_refresh.REPO_ROOT", repo_root
            ), patch(
                "syndicate.features.shared.ops_refresh._assert_no_active_refresh_run"
            ), patch(
                "syndicate.features.shared.ops_refresh.write_json_file",
                side_effect=_record_write,
            ):
                from syndicate.features.shared import ops_refresh

                result = ops_refresh.launch_refresh_run(
                    sports="mlb",
                    phase="live",
                    launch_mode="manifest_only",
                    dry_run=True,
                )

            self.assertTrue(result["ok"])
            self.assertGreaterEqual(len(call_order), 3)
            self.assertEqual(
                call_order[:3],
                ["refresh_and_gate_run.json", "refresh_status_manifest.json", "refresh_status_latest.json"],
            )

    def test_assert_no_active_refresh_run_heals_terminal_pending_external_contract(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            reports_root = repo_root / "reports"
            latest_dir = reports_root / "refresh_status" / "latest"
            run_dir = reports_root / "migration_runs" / "2026-05-22" / "odds_refresh_20260522_120000"
            latest_dir.mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)
            run_summary_path = run_dir / "refresh_and_gate_run.json"
            run_summary_path.write_text(
                json.dumps({"state": "finished", "exitCode": 0, "finishedAt": "2026-05-22T12:05:00Z"}),
                encoding="utf-8",
            )
            (latest_dir / "refresh_status_latest.json").write_text(
                json.dumps(
                    {
                        "date": "2026-05-22",
                        "runStamp": "20260522_120000",
                        "artifactsDir": str(run_dir),
                        "runSummaryPath": str(run_summary_path),
                        "state": "pending_external",
                        "externalRunner": {"kind": "external_runner", "queue_state": "queued"},
                    }
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"SYNDICATE_REPORTS_ROOT": str(reports_root)}, clear=False), patch(
                "syndicate.features.shared.ops_refresh.REPO_ROOT", repo_root
            ), patch("syndicate.features.shared.ops_refresh._pid_is_running", return_value=False):
                from syndicate.features.shared import ops_refresh

                ops_refresh._assert_no_active_refresh_run()

            healed_payload = json.loads((latest_dir / "refresh_status_latest.json").read_text(encoding="utf-8"))
            healed_run_summary = json.loads(run_summary_path.read_text(encoding="utf-8"))
            self.assertEqual(healed_payload["state"], "finished")
            self.assertTrue(str(healed_payload.get("finishedAt") or "").strip())
            self.assertEqual(healed_run_summary["state"], "finished")

    def test_assert_no_active_refresh_run_heals_stale_running_contract_with_dead_pid(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            reports_root = repo_root / "reports"
            latest_dir = reports_root / "refresh_status" / "latest"
            run_dir = reports_root / "migration_runs" / "2026-05-22" / "odds_refresh_20260522_120000"
            latest_dir.mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)
            run_summary_path = run_dir / "refresh_and_gate_run.json"
            run_summary_path.write_text(json.dumps({"state": "running"}), encoding="utf-8")
            (latest_dir / "refresh_status_latest.json").write_text(
                json.dumps(
                    {
                        "date": "2026-05-22",
                        "runStamp": "20260522_120000",
                        "artifactsDir": str(run_dir),
                        "runSummaryPath": str(run_summary_path),
                        "state": "running",
                        "pid": 22517,
                        "externalRunner": {"kind": "external_runner", "queue_state": "queued"},
                    }
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"SYNDICATE_REPORTS_ROOT": str(reports_root)}, clear=False), patch(
                "syndicate.features.shared.ops_refresh.REPO_ROOT", repo_root
            ), patch("syndicate.features.shared.ops_refresh._pid_is_running", return_value=False):
                from syndicate.features.shared import ops_refresh

                ops_refresh._assert_no_active_refresh_run()

            healed_payload = json.loads((latest_dir / "refresh_status_latest.json").read_text(encoding="utf-8"))
            healed_run_summary = json.loads(run_summary_path.read_text(encoding="utf-8"))
            self.assertEqual(healed_payload["state"], "failed")
            self.assertEqual(healed_run_summary["state"], "failed")

    def test_ops_page_renders_recent_history(self) -> None:
        fake_status = {
            "refresh_status": {
                "manifest_path": "reports/refresh_status/latest/refresh_status_latest.json",
                "manifest": {"date": "2026-05-19", "refreshOdds": True, "artifactsDir": "reports/x"},
                "artifacts": {"odds_refresh": {"path": "reports/x/odds_refresh.json", "exists": True}},
                "runtime": {"state": "finished", "detail": "Latest refresh run completed successfully.", "pid": 4321},
                "history": [
                    {
                        "date": "2026-05-19",
                        "run_stamp": "20260519_120000",
                        "sports": "mlb,nba",
                        "phase": "all",
                        "dry_run": False,
                        "runtime": {"state": "finished", "detail": "Latest refresh run completed successfully.", "finished_at": "2026-05-19T12:05:00Z"},
                    },
                    {
                        "date": "2026-05-18",
                        "run_stamp": "20260518_120000",
                        "sports": "mlb",
                        "phase": "live",
                        "dry_run": True,
                        "runtime": {"state": "failed", "detail": "Latest refresh run finished with a failure payload.", "elapsed_seconds": 600, "remaining_budget_seconds": 13800, "runtime_budget_seconds": 14400},
                    },
                ],
            },
            "daily_update": {
                "manifest": {"date": "2026-05-19"},
                "checkpoint": {"currentStage": "refresh_gate"},
                "run_state": {"currentStage": "refresh_gate"},
                "trace": {"trace": {"inputFingerprintCount": 3}},
            },
        }
        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False), patch(
            "syndicate.blueprints.ops.load_latest_refresh_status",
            return_value=fake_status,
        ), patch(
            "syndicate.blueprints.ops.build_refresh_plan",
            return_value={"ok": True, "date": "2026-05-20", "phase": "live", "sports": ["mlb"], "results": []},
        ):
            response = self.client.get(
                "/ops/odds-refresh?phase=live&sports=mlb",
                headers={"X-Admin-Token": "secret-token"},
            )

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Recent Runs", html)
        self.assertIn("2026-05-18 · 20260518_120000", html)
        self.assertIn("Elapsed: 600 seconds", html)
        self.assertIn("Remaining: 13800 seconds", html)
        self.assertIn("Budget: 14400 seconds", html)
        self.assertIn("Stdout log", html)
        self.assertIn("Cancel Latest Refresh", html)
        self.assertIn("Refresh elapsed", html)
        self.assertIn("Refresh remaining", html)
        self.assertIn("Daily checkpoint stage", html)
        self.assertIn("refresh_gate", html)
        self.assertIn("Daily run-state", html)
        self.assertIn("Daily trace inputs", html)
        self.assertIn("Daily elapsed", html)
        self.assertIn("Daily remaining", html)
        self.assertIn("Daily budget", html)

    def test_base_shell_shows_ops_link_when_admin_token_present(self) -> None:
        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False):
            response = self.client.get("/?admin_token=secret-token", headers={"X-Admin-Token": "secret-token"})

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("/ops/odds-refresh?admin_token=secret-token", html)


class RefreshRunPerServiceLaneTests(unittest.TestCase):
    # Root cause of the soccer/WNBA starvation bug: _assert_no_active_refresh_run
    # used to enforce ONE mutex shared across all 3 Render services, even
    # though only same-container runs pose any real OOM risk. These tests
    # cover the per-service-lane redesign that fixes it.
    def setUp(self) -> None:
        from syndicate.features.shared import ops_refresh

        self.ops_refresh = ops_refresh
        self._env_patch = patch.dict(os.environ, {}, clear=False)
        self._env_patch.start()
        for key in ("SYNDICATE_REFRESH_RUN_PER_SERVICE_LANES", "SYNDICATE_REFRESH_LANE", "RENDER_SERVICE_ID", "RENDER_SERVICE_NAME"):
            os.environ.pop(key, None)

    def tearDown(self) -> None:
        self._env_patch.stop()

    def test_lane_key_defaults_to_legacy_when_flag_disabled(self) -> None:
        os.environ["RENDER_SERVICE_ID"] = "srv-some-service"
        self.assertEqual(self.ops_refresh._refresh_lane_key(), "global")
        self.assertEqual(self.ops_refresh._refresh_lane_key("refresh-worker"), "global")

    def test_lane_key_resolves_service_identity_when_enabled(self) -> None:
        os.environ["SYNDICATE_REFRESH_RUN_PER_SERVICE_LANES"] = "true"
        os.environ["RENDER_SERVICE_ID"] = "srv-some-service"
        self.assertEqual(self.ops_refresh._refresh_lane_key(), "srv-some-service")

    def test_lane_key_prefers_explicit_syndicate_refresh_lane_env_over_service_identity(self) -> None:
        os.environ["SYNDICATE_REFRESH_RUN_PER_SERVICE_LANES"] = "true"
        os.environ["RENDER_SERVICE_ID"] = "srv-some-service"
        os.environ["SYNDICATE_REFRESH_LANE"] = "refresh-worker"
        self.assertEqual(self.ops_refresh._refresh_lane_key(), "refresh-worker")

    def test_lane_key_explicit_override_wins_over_everything(self) -> None:
        os.environ["SYNDICATE_REFRESH_RUN_PER_SERVICE_LANES"] = "true"
        os.environ["SYNDICATE_REFRESH_LANE"] = "live-odds-worker"
        self.assertEqual(self.ops_refresh._refresh_lane_key("refresh-worker"), "refresh-worker")

    def test_lane_key_falls_back_to_local_outside_render(self) -> None:
        os.environ["SYNDICATE_REFRESH_RUN_PER_SERVICE_LANES"] = "true"
        self.assertEqual(self.ops_refresh._refresh_lane_key(), "local")

    def test_manifest_filename_legacy_vs_lane(self) -> None:
        self.assertEqual(self.ops_refresh._refresh_manifest_filename("global"), "refresh_status_latest.json")
        self.assertEqual(self.ops_refresh._refresh_manifest_filename("refresh-worker"), "refresh_status_latest__refresh-worker.json")

    def test_assert_no_active_refresh_run_blocks_only_within_same_lane(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            reports_root = Path(tmp_dir) / "reports"
            latest_dir = reports_root / "refresh_status" / "latest"
            latest_dir.mkdir(parents=True, exist_ok=True)
            os.environ["SYNDICATE_REFRESH_RUN_PER_SERVICE_LANES"] = "true"
            os.environ["SYNDICATE_REPORTS_ROOT"] = str(reports_root)
            # Lane "worker-a" has an active (self-pid, so genuinely alive) run.
            (latest_dir / "refresh_status_latest__worker-a.json").write_text(
                json.dumps({"state": "running", "pid": os.getpid(), "launcherServiceId": "worker-a", "generatedAt": datetime.now(timezone.utc).isoformat()}),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                self.ops_refresh._assert_no_active_refresh_run(lane="worker-a")
            # A different lane, even though "worker-a" is active, must not be blocked.
            self.ops_refresh._assert_no_active_refresh_run(lane="worker-b")

    def test_list_latest_refresh_manifests_by_lane(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            reports_root = Path(tmp_dir) / "reports"
            latest_dir = reports_root / "refresh_status" / "latest"
            latest_dir.mkdir(parents=True, exist_ok=True)
            os.environ["SYNDICATE_REPORTS_ROOT"] = str(reports_root)
            (latest_dir / "refresh_status_latest.json").write_text(json.dumps({"state": "finished", "date": "2026-07-23"}), encoding="utf-8")
            (latest_dir / "refresh_status_latest__refresh-worker.json").write_text(json.dumps({"state": "running", "date": "2026-07-23"}), encoding="utf-8")
            (latest_dir / "refresh_status_latest__live-odds-worker.json").write_text(json.dumps({"state": "finished", "date": "2026-07-23"}), encoding="utf-8")

            by_lane = self.ops_refresh.list_latest_refresh_manifests_by_lane()

            self.assertEqual(set(by_lane.keys()), {"global", "refresh-worker", "live-odds-worker"})
            self.assertEqual(by_lane["refresh-worker"]["state"], "running")
            self.assertEqual(by_lane["live-odds-worker"]["state"], "finished")

    def test_list_latest_refresh_manifests_by_lane_uses_keyvalue_index_when_disk_has_nothing(self) -> None:
        # Reproduces the real production bug found while verifying this fix:
        # under the keyvalue backend, "latest" manifest files written by a
        # DIFFERENT service are never materialized on THIS service's local
        # disk at all -- a raw filesystem glob (the original implementation)
        # finds nothing, even though the manifests genuinely exist in the
        # shared Redis-backed store. list_latest_refresh_manifests_by_lane
        # must fall back to the explicit known-lanes index in that case.
        from unittest.mock import MagicMock
        from syndicate.features.shared import refresh_state_store as state_store

        fake_client = MagicMock()
        fake_store: dict[str, str] = {}

        def _get(key: str) -> str | None:
            return fake_store.get(key)

        def _set(key: str, value: str, ex: int | None = None) -> bool:
            fake_store[key] = str(value)
            return True

        fake_client.get.side_effect = _get
        fake_client.set.side_effect = _set

        with TemporaryDirectory() as tmp_dir:
            reports_root = Path(tmp_dir) / "reports"
            os.environ["SYNDICATE_REPORTS_ROOT"] = str(reports_root)
            os.environ["SYNDICATE_REFRESH_STATE_BACKEND"] = "keyvalue"
            os.environ["SYNDICATE_REFRESH_STATE_URL"] = "redis://example"
            with patch.object(state_store, "_get_keyvalue_client", return_value=fake_client):
                # No local files are ever created here -- everything lives
                # only in the fake Redis store, exactly like a real
                # cross-service scenario.
                self.ops_refresh.record_known_refresh_lane("refresh-worker")
                self.ops_refresh.write_json_file(
                    reports_root / "refresh_status" / "latest" / "refresh_status_latest__refresh-worker.json",
                    {"state": "running", "date": "2026-07-23"},
                )

                by_lane = self.ops_refresh.list_latest_refresh_manifests_by_lane()

        self.assertEqual(by_lane.get("refresh-worker", {}).get("state"), "running")

    def test_load_latest_refresh_status_exposes_by_lane_and_keeps_legacy_key(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            reports_root = Path(tmp_dir) / "reports"
            latest_dir = reports_root / "refresh_status" / "latest"
            latest_dir.mkdir(parents=True, exist_ok=True)
            (reports_root / "daily_update" / "latest").mkdir(parents=True, exist_ok=True)
            os.environ["SYNDICATE_REPORTS_ROOT"] = str(reports_root)
            older = datetime(2026, 7, 23, 10, 0, 0, tzinfo=timezone.utc).isoformat()
            newer = datetime(2026, 7, 23, 12, 0, 0, tzinfo=timezone.utc).isoformat()
            (latest_dir / "refresh_status_latest__refresh-worker.json").write_text(
                json.dumps({"state": "finished", "date": "2026-07-23", "generatedAt": older}), encoding="utf-8"
            )
            (latest_dir / "refresh_status_latest__live-odds-worker.json").write_text(
                json.dumps({"state": "running", "date": "2026-07-23", "generatedAt": newer}), encoding="utf-8"
            )

            status = self.ops_refresh.load_latest_refresh_status()

            self.assertIn("refresh_status_by_lane", status)
            self.assertEqual(set(status["refresh_status_by_lane"].keys()), {"refresh-worker", "live-odds-worker"})
            # Legacy singular key stays populated for backward compatibility --
            # from whichever lane was most recently updated.
            self.assertEqual(status["refresh_status"]["manifest"]["state"], "running")

class OpsLiveRefreshStateSimRunResolutionTests(unittest.TestCase):
    """The endpoint used to require BOTH sim_date and sim_run, and silently
    omitted sim_run_status when only one was passed -- which reads exactly
    like "no sim is running". The run stamp is only ever printed to the
    worker log, so callers had no way to supply it without grepping Render.
    """

    def setUp(self) -> None:
        app = create_app()
        app.testing = True
        self.client = app.test_client()
        # ignore_cleanup_errors: create_app() starts the intelligence-state
        # background loop, which keeps writing into this reports root while
        # teardown runs -- without it, cleanup intermittently dies on
        # "directory is not empty" and fails an otherwise-passing test.
        self._tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        self.reports_root = Path(self._tmp.name) / "reports"
        self.sim_base = self.reports_root / "live_refresh_loop" / "mlb_sim_runs"
        self.sim_base.mkdir(parents=True, exist_ok=True)
        os.environ["SYNDICATE_REPORTS_ROOT"] = str(self.reports_root)
        self._prior_admin_token = os.environ.get("ADMIN_TOKEN")
        os.environ["ADMIN_TOKEN"] = "test-token"
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(lambda: os.environ.pop("SYNDICATE_REPORTS_ROOT", None))
        self.addCleanup(self._restore_admin_token)

    def _restore_admin_token(self) -> None:
        if self._prior_admin_token is None:
            os.environ.pop("ADMIN_TOKEN", None)
        else:
            os.environ["ADMIN_TOKEN"] = self._prior_admin_token

    def _write(self, name: str, payload: dict) -> None:
        (self.sim_base / name).write_text(json.dumps(payload), encoding="utf-8")

    def _get(self, query: str = "") -> dict:
        response = self.client.get(
            f"/api/ops/live-refresh/state{query}", headers={"X-Admin-Token": "test-token"}
        )
        self.assertEqual(response.status_code, 200)
        return response.get_json()["state"]

    def test_resolves_running_sim_from_active_pointer_without_run_stamp(self) -> None:
        self._write("_active.json", {"date": "2026-07-25", "run_stamp": "20260725_162656", "pid": 110})
        self._write("2026-07-25_20260725_162656_status.json", {"state": "running", "reason": "fingerprint_change"})

        state = self._get("?sim_date=2026-07-25")

        self.assertEqual(state["sim_run_resolution"]["source"], "active_pointer")
        self.assertEqual(state["sim_run_resolution"]["run_stamp"], "20260725_162656")
        self.assertEqual(state["sim_run_status"]["state"], "running")

    def test_falls_back_to_last_attempt_when_active_pointer_cleared(self) -> None:
        # _clear_active_pointer writes {} rather than deleting -- an empty dict
        # must fall through to the launch-time marker, not be treated as a hit.
        self._write("_active.json", {})
        self._write("_last_attempt.json", {"date": "2026-07-25", "run_stamp": "20260725_150000"})
        self._write("2026-07-25_20260725_150000_status.json", {"state": "finished", "returncode": 0})

        state = self._get()

        self.assertEqual(state["sim_run_resolution"]["source"], "last_attempt")
        self.assertEqual(state["sim_run_status"]["state"], "finished")

    def test_explicit_run_stamp_wins_over_pointers(self) -> None:
        self._write("_active.json", {"date": "2026-07-25", "run_stamp": "20260725_162656"})
        self._write("2026-07-25_20260725_111111_status.json", {"state": "finished"})

        state = self._get("?sim_date=2026-07-25&sim_run=20260725_111111")

        self.assertEqual(state["sim_run_resolution"]["source"], "request")
        self.assertEqual(state["sim_run_resolution"]["run_stamp"], "20260725_111111")
        self.assertEqual(state["sim_run_status"]["state"], "finished")

    def test_does_not_answer_with_a_different_date_than_requested(self) -> None:
        self._write("_active.json", {"date": "2026-07-25", "run_stamp": "20260725_162656"})
        self._write("2026-07-25_20260725_162656_status.json", {"state": "running"})

        state = self._get("?sim_date=2026-07-24")

        self.assertIsNone(state["sim_run_resolution"]["run_stamp"])
        self.assertNotIn("sim_run_status", state)

    def test_reports_unresolved_when_no_pointers_exist(self) -> None:
        state = self._get()

        self.assertEqual(state["sim_run_resolution"], {"run_stamp": None, "date": None, "source": None})
        self.assertNotIn("sim_run_status", state)


class OpsSportLivenessCheckTests(unittest.TestCase):
    """2026-08-05: WNBA's odds-history stayed frozen from before a real
    game's tip-off for over an hour even after a confirmed, deployed fix
    to a separate artifact-freezing bug -- meaning something gates the
    live-odds-worker's sweep from ever including WNBA once it's live, even
    though the code that decides that should, by reading it, detect the
    game as live. This endpoint exercises each layer of that decision
    (artifact check, ESPN subprocess fallback, combined checker) so a
    production read can show which layer is lying, instead of only the
    combined boolean.
    """

    def setUp(self) -> None:
        app = create_app()
        app.testing = True
        self.client = app.test_client()
        self._prior_admin_token = os.environ.get("ADMIN_TOKEN")
        os.environ["ADMIN_TOKEN"] = "test-token"
        self.addCleanup(self._restore_admin_token)

    def _restore_admin_token(self) -> None:
        if self._prior_admin_token is None:
            os.environ.pop("ADMIN_TOKEN", None)
        else:
            os.environ["ADMIN_TOKEN"] = self._prior_admin_token

    def _get(self, query: str) -> tuple:
        response = self.client.get(
            f"/api/ops/live-refresh/sport-liveness-check{query}", headers={"X-Admin-Token": "test-token"}
        )
        return response.status_code, response.get_json()

    def test_requires_sport_param(self) -> None:
        status_code, payload = self._get("")
        self.assertEqual(status_code, 400)
        self.assertFalse(payload["ok"])

    def test_rejects_a_sport_with_no_registered_checker(self) -> None:
        status_code, payload = self._get("?sport=not_a_real_sport")
        self.assertEqual(status_code, 400)
        self.assertFalse(payload["ok"])

    def test_reports_each_layer_when_espn_fallback_is_the_one_that_is_true(self) -> None:
        # The exact production scenario this was built to distinguish: the
        # artifact says not-live (stale/never-written), but ESPN's own
        # scoreboard confirms a real live game.
        with patch(
            "syndicate.features.shared.live_refresh_loop._wnba_has_live_game_via_artifact",
            return_value=False,
        ), patch(
            "syndicate.features.shared.live_refresh_loop._espn_has_live_game",
            return_value=True,
        ), patch(
            "syndicate.features.shared.live_refresh_loop._any_tracked_sport_game_live",
            return_value=True,
        ), patch(
            "syndicate.blueprints.ops.subprocess.run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout='{"live_event_ids": ["401857114"]}', stderr=""),
        ):
            status_code, payload = self._get("?sport=wnba&date=2026-08-04")

        self.assertEqual(status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["artifact_check"], {"ok": True, "value": False})
        self.assertTrue(payload["espn_fallback_check"]["ok"])
        self.assertTrue(payload["espn_fallback_check"]["value"])
        self.assertTrue(payload["combined_checker_result"])
        self.assertTrue(payload["any_tracked_sport_game_live"])

    def test_reports_when_the_espn_subprocess_itself_fails(self) -> None:
        # The theory this session couldn't yet confirm or refute in
        # production: a subprocess spawn failure, PATH/env difference, or
        # timeout would make _espn_has_live_game return False via its own
        # bare except-return-False, indistinguishable from "genuinely not
        # live" anywhere else. This endpoint's whole point is to surface
        # that distinction -- if _espn_has_live_game itself raises (rather
        # than swallowing and returning False), this ok=False branch is
        # what a real subprocess failure looks like here.
        with patch(
            "syndicate.features.shared.live_refresh_loop._wnba_has_live_game_via_artifact",
            return_value=False,
        ), patch(
            "syndicate.features.shared.live_refresh_loop._espn_has_live_game",
            side_effect=RuntimeError("subprocess spawn failed"),
        ), patch(
            "syndicate.features.shared.live_refresh_loop._any_tracked_sport_game_live",
            return_value=False,
        ), patch(
            "syndicate.blueprints.ops.subprocess.run",
            side_effect=RuntimeError("subprocess spawn failed"),
        ):
            status_code, payload = self._get("?sport=wnba&date=2026-08-04")

        self.assertEqual(status_code, 200)
        self.assertFalse(payload["espn_fallback_check"]["ok"])
        self.assertIn("subprocess spawn failed", payload["espn_fallback_check"]["error"])

    def test_espn_helper_raw_surfaces_a_non_zero_exit_that_espn_has_live_game_would_otherwise_swallow(self) -> None:
        # This is the actual production gap this endpoint was built to
        # close: _espn_has_live_game internally treats a non-zero
        # returncode from the helper subprocess exactly like "not live" (no
        # exception, no distinguishing signal) -- so espn_fallback_check
        # alone reads identically for "genuinely not live" and "the helper
        # subprocess failed for some other reason". espn_helper_raw runs
        # the SAME subprocess call independently and reports its actual
        # returncode/stderr, so a real failure (network error, DNS, a bad
        # response) is visible instead of silently indistinguishable.
        with patch(
            "syndicate.features.shared.live_refresh_loop._wnba_has_live_game_via_artifact",
            return_value=False,
        ), patch(
            "syndicate.features.shared.live_refresh_loop._espn_has_live_game",
            return_value=False,
        ), patch(
            "syndicate.features.shared.live_refresh_loop._any_tracked_sport_game_live",
            return_value=True,
        ), patch(
            "syndicate.blueprints.ops.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr='{"error": "URLError: <urlopen error [Errno -2] Name or service not known>"}'
            ),
        ):
            status_code, payload = self._get("?sport=wnba&date=2026-08-04")

        self.assertEqual(status_code, 200)
        # The misleading "looks like it worked" signal this bug hides behind.
        self.assertTrue(payload["espn_fallback_check"]["ok"])
        self.assertFalse(payload["espn_fallback_check"]["value"])
        # The actual answer: it didn't work, and here is exactly why.
        self.assertEqual(payload["espn_helper_raw"]["return_code"], 1)
        self.assertIn("Name or service not known", payload["espn_helper_raw"]["stderr"])
