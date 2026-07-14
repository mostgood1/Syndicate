from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from syndicate.app import create_app


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
            processed_root = Path(tmp_dir) / "processed"
            processed_root.mkdir(parents=True, exist_ok=True)
            (processed_root / "game_cards_2026-07-13.csv").write_text(
                "date,home_tri,away_tri\n2026-07-13,ATL,LAS\n2026-07-13,MIN,PHX\n",
                encoding="utf-8",
            )
            (processed_root / "props_recommendations_top_by_game_2026-07-13.json").write_text(
                json.dumps({"date": "2026-07-13", "data": []}),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False), patch(
                "syndicate.features.wnba.sources.processed_root",
                return_value=processed_root,
            ):
                response = self.client.get(
                    "/api/ops/wnba/artifact-counts?date=2026-07-13",
                    headers={"X-Admin-Token": "secret-token"},
                )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        results = payload["results"]
        self.assertTrue(results["game_cards_2026-07-13.csv"]["exists"])
        self.assertEqual(results["game_cards_2026-07-13.csv"]["data_rows"], 2)
        self.assertTrue(results["props_recommendations_top_by_game_2026-07-13.json"]["exists"])
        self.assertEqual(results["props_recommendations_top_by_game_2026-07-13.json"]["data_rows"], 0)
        self.assertFalse(results["props_recommendations_2026-07-13.csv"]["exists"])

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