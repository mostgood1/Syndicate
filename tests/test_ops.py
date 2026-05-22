from __future__ import annotations

import json
import os
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
                json.dumps({"date": "2026-05-19", "artifactsDir": str(artifacts_dir)}),
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
                json.dumps({"date": "2026-05-19", "latestRunDir": "reports/daily_update/2026-05-19/run"}),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False), patch(
                "syndicate.features.shared.ops_refresh.REPO_ROOT", repo_root
            ), patch("syndicate.features.shared.ops_refresh.REPORTS_ROOT", reports_root):
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
        self.assertGreaterEqual(len(payload["status"]["refresh_status"]["history"]), 1)
        self.assertEqual(payload["status"]["refresh_status"]["mirror_manifests"][0]["sport"], "mlb")
        self.assertEqual(payload["status"]["refresh_status"]["mirror_manifests"][0]["copied_artifact_count"], 14)
        self.assertEqual(payload["status"]["daily_update"]["manifest"]["date"], "2026-05-19")

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

            with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False), patch(
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

            with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False), patch(
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

    def test_status_reads_from_env_configured_reports_and_data_roots(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            reports_root = root / "persistent" / "reports"
            data_root = root / "persistent" / "data"
            refresh_latest = reports_root / "refresh_status" / "latest"
            daily_latest = reports_root / "daily_update" / "latest"
            artifacts_dir = reports_root / "migration_runs" / "2026-05-22" / "20260522_120000"
            mirror_manifest_dir = data_root / "mlb_source" / "manifests"

            refresh_latest.mkdir(parents=True, exist_ok=True)
            daily_latest.mkdir(parents=True, exist_ok=True)
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            mirror_manifest_dir.mkdir(parents=True, exist_ok=True)

            (artifacts_dir / "odds_refresh.json").write_text(
                json.dumps({"ok": True, "dry_run": False, "sports": ["mlb"]}),
                encoding="utf-8",
            )
            (artifacts_dir / "odds_refresh.stderr.txt").write_text("", encoding="utf-8")
            (refresh_latest / "refresh_status_latest.json").write_text(
                json.dumps({"date": "2026-05-22", "artifactsDir": str(artifacts_dir)}),
                encoding="utf-8",
            )
            (daily_latest / "daily_update_latest.json").write_text(
                json.dumps({"date": "2026-05-22"}),
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
        self.assertEqual(payload["status"]["reports_root"], str(reports_root))
        self.assertEqual(payload["status"]["refresh_status"]["manifest"]["date"], "2026-05-22")
        self.assertEqual(payload["status"]["refresh_status"]["mirror_manifests"][0]["sport"], "mlb")

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
        self.assertEqual(((result.get("ingestion") or {}).get("contract") or {}).get("kind"), "existing_mirror_artifacts")
        self.assertEqual(result["refresh_steps"], [])
        mirror = result.get("mirror") or {}
        self.assertTrue(mirror.get("ok"))
        self.assertTrue(mirror.get("dry_run"))
        command = mirror.get("command") or []
        self.assertIn("refresh_mlb_source_mirror.ps1", " ".join(str(part) for part in command))
        self.assertIn("-UseExistingMirrorArtifacts", command)

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
        self.assertEqual(result["refresh_steps"], [])
        mirror = result.get("mirror") or {}
        self.assertTrue(mirror.get("ok"))
        self.assertTrue(mirror.get("dry_run"))
        command = mirror.get("command") or []
        self.assertIn("refresh_nhl_source_mirror.ps1", " ".join(str(part) for part in command))
        self.assertIn("-UseExistingMirrorArtifacts", command)

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
        self.assertEqual(result["refresh_steps"], [])
        mirror = result.get("mirror") or {}
        self.assertTrue(mirror.get("ok"))
        self.assertTrue(mirror.get("dry_run"))
        command = mirror.get("command") or []
        self.assertIn("refresh_nba_source_mirror.ps1", " ".join(str(part) for part in command))
        self.assertIn("-UseExistingMirrorArtifacts", command)

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
        self.assertEqual(result["refresh_steps"], [])
        mirror = result.get("mirror") or {}
        self.assertTrue(mirror.get("ok"))
        self.assertTrue(mirror.get("dry_run"))
        command = mirror.get("command") or []
        self.assertIn("refresh_wnba_source_mirror.ps1", " ".join(str(part) for part in command))
        self.assertIn("-UseExistingMirrorArtifacts", command)

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
        self.assertEqual(((result.get("ingestion") or {}).get("contract") or {}).get("kind"), "existing_mirror_artifacts")
        self.assertEqual(result["refresh_steps"], [])
        self.assertTrue((result.get("mirror") or {}).get("dry_run"))

    def test_build_refresh_plan_marks_nfl_ingest_as_not_hosted_safe(self) -> None:
        from syndicate.features.shared import ops_refresh

        plan = ops_refresh.build_refresh_plan(date="2026-10-01", sports="nfl", execution_mode="ingest")

        self.assertTrue(plan["ok"])
        result = plan["results"][0]
        self.assertEqual((result.get("generation") or {}).get("kind"), "none")
        self.assertEqual((result.get("ingestion") or {}).get("kind"), "mirror_script")
        self.assertFalse((result.get("ingestion") or {}).get("hosted_safe"))
        self.assertEqual(((result.get("ingestion") or {}).get("contract") or {}).get("kind"), "source_repo_artifacts")

    def test_ops_page_requires_admin_token(self) -> None:
        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False):
            response = self.client.get("/ops/odds-refresh")

        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.get_json()["ok"])

    def test_ops_page_renders_status_and_plan(self) -> None:
        fake_status = {
            "refresh_status": {
                "manifest_path": "reports/refresh_status/latest/refresh_status_latest.json",
                "manifest": {"date": "2026-05-19", "refreshOdds": True, "artifactsDir": "reports/x"},
                "artifacts": {"odds_refresh": {"path": "reports/x/odds_refresh.json", "exists": True}},
                "mirror_manifests": [
                    {
                        "sport": "mlb",
                        "path": "data/mlb_source/manifests/mirror_refresh_latest.json",
                        "exists": True,
                        "date": "2026-05-19",
                        "copied_artifact_count": 14,
                        "artifact_groups": {"daily": 10, "eval": 4},
                        "manifest": {"sourceRepo": "C:/repos/MLB-BettingV2"},
                    }
                ],
                "runtime": {"state": "finished", "detail": "Latest refresh run completed successfully.", "pid": 4321},
            },
            "daily_update": {"manifest": {"date": "2026-05-19"}},
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
                    "source_repo": "C:/repos/MLB-BettingV2",
                    "generation": {"kind": "source_repo", "source_dependency": "source_repo", "hosted_safe": False},
                    "ingestion": {"kind": "mirror_script", "source_dependency": "local_artifacts", "hosted_safe": True, "contract": {"kind": "existing_mirror_artifacts"}},
                    "refresh_steps": [
                        {
                            "name": "mlb_oddsapi_markets",
                            "ok": True,
                            "description": "Refresh MLB markets",
                            "command": ["python", "-m", "tools.oddsapi.fetch_daily_oddsapi_markets"],
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
        self.assertIn("mlb_oddsapi_markets", html)
        self.assertIn("skip mirror", html.lower())
        self.assertIn("Launch Refresh", html)
        self.assertIn("Run state: finished", html)
        self.assertIn("Mirror manifests", html)
        self.assertIn("Copied 14 artifacts", html)
        self.assertIn("Contract: existing_mirror_artifacts", html)

    def test_run_endpoint_returns_launch_payload(self) -> None:
        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False), patch(
            "syndicate.blueprints.ops.launch_refresh_run",
            return_value={"ok": True, "pid": 4321, "run_stamp": "20260520_123000", "date": "2026-05-20"},
        ) as mocked:
            response = self.client.post(
                "/api/ops/odds-refresh/run",
                json={"sports": "mlb", "phase": "live", "skip_mirror": True, "dry_run": True},
                headers={"X-Admin-Token": "secret-token"},
            )

        self.assertEqual(response.status_code, 202)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["launch"]["pid"], 4321)
        mocked.assert_called_once()

    def test_run_page_redirects_after_launch(self) -> None:
        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False), patch(
            "syndicate.blueprints.ops.launch_refresh_run",
            return_value={"ok": True, "pid": 4321, "run_stamp": "20260520_123000", "date": "2026-05-20"},
        ) as mocked:
            response = self.client.post(
                "/ops/odds-refresh/run",
                data={"sports": "mlb", "phase": "live", "skip_mirror": "1", "dry_run": "1", "admin_token": "secret-token"},
                headers={"X-Admin-Token": "secret-token"},
            )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/ops/odds-refresh", response.headers["Location"])
        self.assertIn("launched=1", response.headers["Location"])
        self.assertIn("dry_run=1", response.headers["Location"])
        mocked.assert_called_once()

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

    def test_launch_refresh_run_uses_wrapper_command(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            reports_root = repo_root / "reports"
            with patch("syndicate.features.shared.ops_refresh.REPO_ROOT", repo_root), patch(
                "syndicate.features.shared.ops_refresh.REPORTS_ROOT", reports_root
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
            with patch("syndicate.features.shared.ops_refresh.REPO_ROOT", repo_root), patch(
                "syndicate.features.shared.ops_refresh.REPORTS_ROOT", reports_root
            ), patch("syndicate.features.shared.ops_refresh.subprocess.Popen") as mocked_popen:
                mocked_popen.return_value.pid = 2468
                from syndicate.features.shared import ops_refresh

                result = ops_refresh.launch_refresh_run(sports="mlb", phase="live", execution_mode="ingest", dry_run=True)

            self.assertTrue(result["ok"])
            called_command = mocked_popen.call_args.args[0]
            self.assertIn("--execution-mode", called_command)
            self.assertIn("ingest", called_command)

    def test_launch_refresh_run_supports_manifest_only_mode(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            reports_root = repo_root / "reports"
            with patch.dict(os.environ, {"SYNDICATE_REFRESH_LAUNCH_MODE": "manifest_only"}, clear=False), patch(
                "syndicate.features.shared.ops_refresh.REPO_ROOT", repo_root
            ), patch(
                "syndicate.features.shared.ops_refresh.REPORTS_ROOT", reports_root
            ), patch("syndicate.features.shared.ops_refresh.subprocess.Popen") as mocked_popen:
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

    def test_launch_refresh_run_supports_external_runner_mode_alias(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            reports_root = repo_root / "reports"
            with patch.dict(os.environ, {"SYNDICATE_REFRESH_LAUNCH_MODE": "external_runner"}, clear=False), patch(
                "syndicate.features.shared.ops_refresh.REPO_ROOT", repo_root
            ), patch(
                "syndicate.features.shared.ops_refresh.REPORTS_ROOT", reports_root
            ), patch("syndicate.features.shared.ops_refresh.subprocess.Popen") as mocked_popen:
                from syndicate.features.shared import ops_refresh

                result = ops_refresh.launch_refresh_run(sports="mlb", phase="live", dry_run=True)

            mocked_popen.assert_not_called()
            self.assertTrue(result["ok"])
            self.assertEqual(result["launch_mode"], "external_runner")
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

            with patch("syndicate.features.shared.ops_refresh.REPO_ROOT", repo_root), patch(
                "syndicate.features.shared.ops_refresh.REPORTS_ROOT", reports_root
            ):
                from syndicate.features.shared import ops_refresh

                result = ops_refresh.cancel_latest_refresh_run()

            self.assertTrue(result["ok"])
            self.assertIsNone(result["pid"])
            self.assertEqual(result["state"], "canceled")

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
                        "runtime": {"state": "failed", "detail": "Latest refresh run finished with a failure payload."},
                    },
                ],
            },
            "daily_update": {"manifest": {"date": "2026-05-19"}},
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
        self.assertIn("Stdout log", html)
        self.assertIn("Cancel Latest Refresh", html)

    def test_base_shell_shows_ops_link_when_admin_token_present(self) -> None:
        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False):
            response = self.client.get("/?admin_token=secret-token", headers={"X-Admin-Token": "secret-token"})

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("/ops/odds-refresh?admin_token=secret-token", html)