from __future__ import annotations

import io
import json
import argparse
import importlib.util
import tempfile
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


class RefreshOddsSourcesTests(unittest.TestCase):
    def _load_module(self):
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "refresh_odds_sources.py"
        spec = importlib.util.spec_from_file_location("test_refresh_odds_sources", script_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    def _make_step(self, module):
        return module.RefreshStep(
            name="mlb_test_step",
            phases=("live",),
            cwd=Path("."),
            command=("python", "child.py"),
            env_updates=None,
            description="test step",
        )

    def test_run_command_uses_default_timeout_when_env_is_absent(self) -> None:
        module = self._load_module()
        step = self._make_step(module)
        completed = subprocess.CompletedProcess(args=list(step.command), returncode=0, stdout="ok", stderr="")

        with patch.dict(module.os.environ, {}, clear=True), patch.object(module.subprocess, "run", return_value=completed) as mocked_run, patch.object(
            module,
            "_log_memory",
            return_value=None,
        ), patch.object(module, "_dump_child_runtime_state", return_value=None):
            result = module._run_command(step)

        self.assertTrue(result["ok"])
        self.assertEqual(mocked_run.call_args.kwargs["timeout"], module._DEFAULT_REFRESH_STEP_TIMEOUT_SECONDS)

    def test_run_command_honors_explicit_timeout_override(self) -> None:
        module = self._load_module()
        step = self._make_step(module)
        completed = subprocess.CompletedProcess(args=list(step.command), returncode=0, stdout="ok", stderr="")

        with patch.dict(module.os.environ, {"SYNDICATE_REFRESH_STEP_TIMEOUT_SECONDS": "77"}, clear=True), patch.object(
            module.subprocess,
            "run",
            return_value=completed,
        ) as mocked_run, patch.object(module, "_log_memory", return_value=None), patch.object(module, "_dump_child_runtime_state", return_value=None):
            result = module._run_command(step)

        self.assertTrue(result["ok"])
        self.assertEqual(mocked_run.call_args.kwargs["timeout"], 77)

    def test_run_command_timeout_path_logs_failure_and_raises(self) -> None:
        module = self._load_module()
        step = self._make_step(module)
        stderr_capture = io.StringIO()
        timeout_exc = subprocess.TimeoutExpired(cmd=list(step.command), timeout=module._DEFAULT_REFRESH_STEP_TIMEOUT_SECONDS)

        with patch.dict(module.os.environ, {}, clear=True), patch.object(module.subprocess, "run", side_effect=timeout_exc) as mocked_run, patch.object(
            module,
            "sys",
            wraps=module.sys,
        ) as mocked_sys, patch.object(module, "_log_memory", return_value=None), patch.object(module, "_dump_child_runtime_state", return_value=None):
            mocked_sys.stderr = stderr_capture
            with self.assertRaises(subprocess.TimeoutExpired):
                module._run_command(step)

        self.assertEqual(mocked_run.call_args.kwargs["timeout"], module._DEFAULT_REFRESH_STEP_TIMEOUT_SECONDS)
        stderr_text = stderr_capture.getvalue()
        self.assertIn("STEP_FAIL name=mlb_test_step status=timeout", stderr_text)
        self.assertIn("STEP_END name=mlb_test_step status=timeout", stderr_text)
        self.assertIn("timeout_seconds=1800", stderr_text)

    def test_build_summary_runs_post_refresh_tracking_for_supported_sport(self) -> None:
        module = self._load_module()
        args = argparse.Namespace(
            date="2026-06-07",
            sports="wnba",
            phase="live",
            regions="us",
            bookmakers="",
            markets="",
            season=None,
            week=None,
            skip_mirror=True,
            execution_mode="source",
            mirror_only=False,
            continue_on_error=True,
            dry_run=False,
            json=False,
            list=False,
        )

        with patch.object(module, "_run_command", return_value={"ok": True, "name": "wnba_oddsapi_props_job", "dry_run": False}), patch.object(
            module,
            "_sync_post_refresh_tracking_step",
            return_value={"ok": True, "name": "wnba_post_refresh_tracking_sync", "dry_run": False, "meta": {"signals_rows": 3}},
        ) as mocked_tracking:
            summary = module._build_summary(args)

        self.assertTrue(summary["ok"])
        self.assertEqual(len(summary["results"]), 1)
        sport_result = summary["results"][0]
        self.assertIn("post_refresh", sport_result)
        self.assertEqual(sport_result["post_refresh"]["name"], "wnba_post_refresh_tracking_sync")
        mocked_tracking.assert_called_once()

    def test_build_summary_publishes_sport_manifest_after_each_completed_sport(self) -> None:
        module = self._load_module()
        args = argparse.Namespace(
            date="2026-06-07",
            sports="wnba",
            phase="all",
            regions="us",
            bookmakers="",
            markets="",
            season=None,
            week=None,
            skip_mirror=True,
            execution_mode="source",
            mirror_only=False,
            continue_on_error=True,
            dry_run=False,
            json=False,
            list=False,
        )

        manifest_payload = {"path": "reports/manifests/wnba.json", "payload": {"sport": "wnba"}}
        with patch.object(module, "_run_command", return_value={"ok": True, "name": "wnba_oddsapi_props_job", "dry_run": False}), patch.object(
            module,
            "_sync_post_refresh_tracking_step",
            return_value={"ok": True, "name": "wnba_post_refresh_tracking_sync", "dry_run": False, "meta": {"signals_rows": 3}},
        ), patch.object(module, "publish_sport_manifest", return_value=manifest_payload) as mocked_publish:
            summary = module._build_summary(args)

        self.assertTrue(summary["ok"])
        self.assertEqual(len(summary["results"]), 1)
        sport_result = summary["results"][0]
        # Result-retention compaction keeps only the manifest path plus an
        # artifact count in the summary, not the full publish payload.
        self.assertEqual(sport_result["sport_manifest"], {"path": "reports/manifests/wnba.json", "artifact_count": 0})
        mocked_publish.assert_called_once()
        _, kwargs = mocked_publish.call_args
        self.assertEqual(kwargs["sport"], "wnba")
        self.assertIn("artifact_paths", kwargs)
        self.assertEqual(kwargs["metadata"]["execution_mode"], "source")
        self.assertEqual(
            kwargs["metadata"]["refresh_contract"],
            {
                "required": ["snapshot", "snapshot_alias", "game_slate", "predictions", "board_contract", "manifest"],
                "optional": ["smart_sim", "recommendations", "edges", "live_lens", "advanced_analytics", "simulation_detail"],
            },
        )

    def test_build_summary_compacts_step_stdout_after_artifact_paths_are_extracted(self) -> None:
        module = self._load_module()
        args = argparse.Namespace(
            date="2026-06-07",
            sports="wnba",
            phase="live",
            regions="us",
            bookmakers="",
            markets="",
            season=None,
            week=None,
            skip_mirror=True,
            execution_mode="source",
            mirror_only=False,
            continue_on_error=True,
            dry_run=False,
            json=False,
            list=False,
        )

        artifact_path = r"C:\render\data\wnba_source\source_artifacts\data\processed\wnba_player_props.csv"
        step_result = {
            "name": "wnba_oddsapi_props_job",
            "description": "Refresh WNBA OddsAPI props snapshot, edges, and recommendations.",
            "cwd": r"C:\Users\tempadmin\OneDrive\Coding\Syndicate",
            "command": ["python", "scripts/refresh_wnba_oddsapi_props.py"],
            "return_code": 0,
            "started_at": "2026-06-07T00:00:00+00:00",
            "finished_at": "2026-06-07T00:00:01+00:00",
            "row_counts": None,
            "stdout": json.dumps({"artifact_bundle_files": {"files": [artifact_path]}}),
            "stderr": "",
            "ok": True,
            "dry_run": False,
        }

        with patch.object(module, "_run_command", return_value=step_result), patch.object(
            module,
            "_sync_post_refresh_tracking_step",
            return_value={"ok": True, "name": "wnba_post_refresh_tracking_sync", "dry_run": False, "meta": {"signals_rows": 3}},
        ), patch.object(module, "publish_sport_manifest", return_value={"path": "reports/manifests/wnba.json", "payload": {"sport": "wnba"}}):
            summary = module._build_summary(args)

        sport_result = summary["results"][0]
        self.assertIn(artifact_path, sport_result["artifact_paths"])
        # Compaction now rebuilds each step as a compact view that omits the
        # bulky keys entirely (stdout/stderr/empty row_counts) rather than
        # blanking them in place.
        self.assertNotIn("stdout", sport_result["refresh_steps"][0])
        self.assertNotIn("stderr", sport_result["refresh_steps"][0])
        self.assertNotIn("row_counts", sport_result["refresh_steps"][0])

    def test_build_summary_emits_publish_parity_on_success(self) -> None:
        module = self._load_module()
        args = argparse.Namespace(
            date="2026-06-07",
            sports="wnba",
            phase="all",
            regions="us",
            bookmakers="",
            markets="",
            season=None,
            week=None,
            skip_mirror=True,
            execution_mode="source",
            mirror_only=False,
            continue_on_error=True,
            dry_run=False,
            json=False,
            list=False,
        )

        with patch.object(module, "_run_command", return_value={"ok": True, "name": "wnba_oddsapi_props_job", "dry_run": False}), patch.object(
            module,
            "_sync_post_refresh_tracking_step",
            return_value={"ok": True, "name": "wnba_post_refresh_tracking_sync", "dry_run": False, "meta": {"signals_rows": 3}},
        ), patch.object(module, "publish_sport_manifest", return_value={"path": "reports/manifests/wnba.json", "payload": {"sport": "wnba"}}), patch.object(
            module,
            "build_publish_parity_summary",
            return_value={"date": "2026-06-07", "sports": [], "totalForcedPublishPaths": 3},
        ) as mocked_publish_parity:
            summary = module._build_summary(args)

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["publish_parity"]["totalForcedPublishPaths"], 3)
        mocked_publish_parity.assert_called_once()

    def test_build_summary_omits_runtime_memory_snapshot(self) -> None:
        # The structured summary["runtime"] block (and the
        # get_all_process_memory_snapshot import feeding it) was removed:
        # runtime memory observability now flows through the
        # log_all_process_memory/log_runtime_memory log lines instead of the
        # persisted summary payload.
        module = self._load_module()
        args = argparse.Namespace(
            date="2026-06-07",
            sports="wnba",
            phase="all",
            regions="us",
            bookmakers="",
            markets="",
            season=None,
            week=None,
            skip_mirror=True,
            execution_mode="source",
            mirror_only=False,
            continue_on_error=True,
            dry_run=False,
            json=False,
            list=False,
        )

        with patch.object(module, "_log_memory", return_value=None), patch.object(module, "log_all_process_memory", return_value={}), patch.object(
            module,
            "log_runtime_memory",
            return_value=None,
        ), patch.object(module, "_run_command", return_value={"ok": True, "name": "wnba_oddsapi_props_job", "dry_run": False}), patch.object(
            module,
            "_sync_post_refresh_tracking_step",
            return_value={"ok": True, "name": "wnba_post_refresh_tracking_sync", "dry_run": False, "meta": {"signals_rows": 3}},
        ), patch.object(module, "publish_sport_manifest", return_value={"path": "reports/manifests/wnba.json", "payload": {"sport": "wnba"}}), patch.object(
            module,
            "build_publish_parity_summary",
            return_value={"date": "2026-06-07", "sports": [], "totalForcedPublishPaths": 3},
        ):
            summary = module._build_summary(args)

        self.assertTrue(summary["ok"])
        self.assertNotIn("runtime", summary)
        self.assertFalse(hasattr(module, "get_all_process_memory_snapshot"))

    def test_build_summary_routes_progress_logs_to_stdout(self) -> None:
        # Progress lines like serial_gate deliberately go to stdout (no
        # file= kwarg): stderr is reserved for the STEP_* status lines that
        # get persisted as the failure record, and stdout is what Render's
        # log collector reliably captures.
        module = self._load_module()
        args = argparse.Namespace(
            date="2026-06-07",
            sports="wnba",
            phase="all",
            regions="us",
            bookmakers="",
            markets="",
            season=None,
            week=None,
            skip_mirror=True,
            execution_mode="source",
            mirror_only=False,
            continue_on_error=True,
            dry_run=False,
            json=False,
            list=False,
        )

        with patch.object(module, "_run_command", return_value={"ok": True, "name": "wnba_oddsapi_props_job", "dry_run": False}), patch.object(
            module,
            "_sync_post_refresh_tracking_step",
            return_value={"ok": True, "name": "wnba_post_refresh_tracking_sync", "dry_run": False, "meta": {"signals_rows": 3}},
        ), patch.object(module, "publish_sport_manifest", return_value={"path": "reports/manifests/wnba.json", "payload": {"sport": "wnba"}}), patch.object(
            module,
            "build_publish_parity_summary",
            return_value={"date": "2026-06-07", "sports": [], "totalForcedPublishPaths": 3},
        ), patch.object(module, "_log_memory", return_value=None), patch.object(module, "log_all_process_memory", return_value={}), patch.object(
            module,
            "log_runtime_memory",
            return_value=None,
        ), patch("builtins.print") as mocked_print:
            summary = module._build_summary(args)

        self.assertTrue(summary["ok"])
        serial_gate_calls = [call for call in mocked_print.call_args_list if "[refresh_odds_sources] serial_gate" in str(call.args[0])]
        self.assertEqual(len(serial_gate_calls), 1)
        self.assertIsNone(serial_gate_calls[0].kwargs.get("file"))

    def test_sport_control_plane_metadata_uses_same_refresh_contract_for_mlb_and_wnba(self) -> None:
        module = self._load_module()

        mlb_metadata = module._sport_control_plane_metadata(
            {"sport": "mlb", "ok": True, "post_refresh": {"ok": True}, "mirror": {"ok": True}},
            date="2026-07-09",
            phase="all",
            execution_mode="source",
            refresh_mode="full",
        )
        wnba_metadata = module._sport_control_plane_metadata(
            {"sport": "wnba", "ok": True, "post_refresh": {"ok": True}, "mirror": {"ok": True}},
            date="2026-07-09",
            phase="all",
            execution_mode="source",
            refresh_mode="full",
        )

        self.assertEqual(mlb_metadata["refresh_contract"], wnba_metadata["refresh_contract"])
        self.assertEqual(mlb_metadata["refresh_contract"]["required"], ["snapshot", "snapshot_alias", "game_slate", "predictions", "board_contract", "manifest"])
        self.assertEqual(mlb_metadata["refresh_contract"]["optional"], ["smart_sim", "recommendations", "edges", "live_lens", "advanced_analytics", "simulation_detail"])
        self.assertEqual(mlb_metadata["required_artifact_failures"], [])
        self.assertEqual(wnba_metadata["optional_artifact_failures"], [])

    def test_publish_sport_manifest_marks_required_failures_as_failed_but_optional_only_as_complete(self) -> None:
        from syndicate.features.shared.manifest import publish_sport_manifest

        with tempfile.TemporaryDirectory() as tmp_dir:
            reports_root = Path(tmp_dir) / "reports"
            (reports_root / "manifests").mkdir(parents=True, exist_ok=True)

            with patch("syndicate.features.shared.manifest.reports_root", return_value=reports_root):
                required_result = publish_sport_manifest(
                    "wnba",
                    ["data/wnba_source/source_artifacts/data/processed/game_cards_2026-07-09.csv"],
                    {
                        "refresh_contract": {
                            "required": ["snapshot", "snapshot_alias", "game_slate", "predictions", "board_contract", "manifest"],
                            "optional": ["smart_sim", "recommendations", "edges", "live_lens", "advanced_analytics", "simulation_detail"],
                        },
                        "required_artifact_failures": ["predictions missing"],
                        "optional_artifact_failures": ["SmartSim missing"],
                    },
                )
                optional_result = publish_sport_manifest(
                    "mlb",
                    ["data/mlb_source/source_artifacts/data/processed/game_cards_2026-07-09.csv"],
                    {
                        "refresh_contract": {
                            "required": ["snapshot", "snapshot_alias", "game_slate", "predictions", "board_contract", "manifest"],
                            "optional": ["smart_sim", "recommendations", "edges", "live_lens", "advanced_analytics", "simulation_detail"],
                        },
                        "optional_artifact_failures": ["live lens missing"],
                    },
                )

        self.assertEqual(required_result["payload"]["status"], "failed")
        self.assertEqual(optional_result["payload"]["status"], "complete")
        self.assertEqual(required_result["payload"]["metadata"]["required_artifact_failures"], ["predictions missing"])
        self.assertEqual(optional_result["payload"]["metadata"]["optional_artifact_failures"], ["live lens missing"])

    def test_build_odds_coverage_audit_reports_date_and_week_spans(self) -> None:
        module = self._load_module()

        with patch.object(module, "mlb_available_daily_summary_dates", return_value=["2026-07-05", "2026-07-06"]), patch.object(
            module,
            "nba_available_dates",
            return_value=["2026-07-04", "2026-07-05"],
        ), patch.object(module, "wnba_available_dates", return_value=["2026-07-05"]), patch.object(
            module,
            "nhl_available_dates",
            return_value=["2026-07-03", "2026-07-04"],
        ), patch.object(module, "ncaab_available_dates", return_value=["2026-07-02", "2026-07-05"]), patch.object(
            module,
            "nfl_latest_season",
            return_value=2025,
        ), patch.object(module, "nfl_week_summaries", return_value=[{"season": 2025, "week": 1}, {"season": 2025, "week": 2}]), patch.object(
            module,
            "ncaaf_default_season",
            return_value=2025,
        ), patch.object(module, "ncaaf_week_summaries", return_value=[{"season": 2025, "week": 1, "has_data": True}, {"season": 2025, "week": 2, "has_data": True}]):
            audit = module._build_odds_coverage_audit(requested_date="2026-07-05")

        self.assertEqual(audit["requested_date"], "2026-07-05")
        self.assertIn("mlb", audit["future_supported_sports"])
        self.assertEqual(audit["sports"][0]["coverage_kind"], "dates")
        self.assertEqual(audit["sports"][0]["earliest_collected"], "2026-07-05")
        self.assertEqual(audit["sports"][0]["latest_collected"], "2026-07-06")
        nfl_report = next(item for item in audit["sports"] if item["sport"] == "nfl")
        self.assertEqual(nfl_report["coverage_kind"], "weeks")
        self.assertEqual(nfl_report["earliest_collected"], "2025 Week 1")
        self.assertEqual(nfl_report["latest_collected"], "2025 Week 2")

    def test_wnba_uses_combined_game_and_player_prop_markets_while_other_basketball_sports_keep_interval_defaults(self) -> None:
        module = self._load_module()
        args = argparse.Namespace(
            date="2026-06-07",
            regions="us",
            bookmakers="",
            markets="",
        )

        nba_steps = module._build_nba_steps(args)
        wnba_steps = module._build_wnba_steps(args)
        ncaab_steps = module._build_ncaab_steps(args)

        interval_markets = "h2h,spreads,totals,spreads_h1,totals_h1,spreads_h2,totals_h2"
        game_markets = interval_markets
        player_prop_markets = "player_points,player_rebounds,player_assists,player_points_rebounds_assists,player_threes,player_steals,player_blocks,player_turnovers,player_points_rebounds,player_points_assists,player_rebounds_assists,player_double_double,player_triple_double"
        wnba_markets = f"{game_markets},{player_prop_markets}"

        self.assertIn("--markets", nba_steps[0].command)
        self.assertIn(interval_markets, nba_steps[0].command)
        self.assertIn("--markets", ncaab_steps[0].command)
        self.assertIn(interval_markets, ncaab_steps[0].command)

        # WNBA combines the same game markets NBA/NCAAB use (h2h/spreads/
        # totals plus the half markets) with the player-prop markets, so a
        # single request captures moneyline/spread/total parsing alongside
        # player props.
        self.assertIn("--markets", wnba_steps[0].command)
        self.assertIn(wnba_markets, wnba_steps[0].command)

    def test_source_root_helpers_prefer_render_disk(self) -> None:
        module = self._load_module()

        with patch.dict(module.os.environ, {"SYNDICATE_DATA_ROOT": r"C:\render\data"}, clear=False):
            self.assertEqual(module._source_repo_root("nfl", "NFL-Betting"), Path(r"C:\render\data\nfl_source"))
            self.assertEqual(module._basketball_source_root("nba", "nba_betting_repo"), Path(r"C:\render\data\nba_source"))

    def test_validate_source_root_reports_missing_render_disk(self) -> None:
        module = self._load_module()

        with patch.dict(module.os.environ, {"SYNDICATE_DATA_ROOT": r"C:\render\data"}, clear=False):
            message = module._validate_source_root(module.REGISTRY["mlb"])

        self.assertIsInstance(message, str)
        self.assertIn("Render data disk is missing", message)
        self.assertIn(r"C:\render\data\mlb_source", message)

    def test_sport_artifact_paths_include_bundle_file_outputs(self) -> None:
        module = self._load_module()

        sport_result = {
            "ok": True,
            "generation": {
                "steps": [
                    {
                        "stdout": json.dumps(
                            {
                                "artifact_bundle_files": {
                                    "files": [
                                        r"C:\render\data\mlb_source\source_artifacts\data\processed\boxscores_history.csv",
                                        r"C:\render\data\mlb_source\source_artifacts\data\processed\cards_snapshot.json",
                                    ],
                                    "directories": [r"C:\render\data\mlb_source\source_artifacts\data\processed"],
                                    "report_path": r"C:\render\data\mlb_source\source_artifacts\reports\mlb_bundle_report.json",
                                }
                            }
                        ),
                    }
                ]
            },
        }

        artifact_paths = module._sport_artifact_paths(sport_result)

        self.assertIn(r"C:\render\data\mlb_source\source_artifacts\data\processed\boxscores_history.csv", artifact_paths)
        self.assertIn(r"C:\render\data\mlb_source\source_artifacts\data\processed\cards_snapshot.json", artifact_paths)
        self.assertIn(r"C:\render\data\mlb_source\source_artifacts\data\processed", artifact_paths)
        self.assertIn(r"C:\render\data\mlb_source\source_artifacts\reports\mlb_bundle_report.json", artifact_paths)

    def test_step_command_with_mode_appends_force_refresh_for_wnba(self) -> None:
        module = self._load_module()
        step = module.RefreshStep(
            name="wnba_oddsapi_props_job",
            phases=("pregame", "live"),
            cwd=Path("."),
            command=("python", "scripts/refresh_wnba_oddsapi_props.py", "--date", "2026-07-13"),
            env_updates=None,
            description="test step",
        )

        command = module._step_command_with_mode(step, "full", force_refresh=True)

        self.assertIn("--force-refresh", command)

    def test_step_command_with_mode_appends_force_refresh_for_nba(self) -> None:
        module = self._load_module()
        step = module.RefreshStep(
            name="nba_oddsapi_props_job",
            phases=("pregame", "live"),
            cwd=Path("."),
            command=("python", "scripts/refresh_nba_oddsapi_props.py", "--date", "2026-07-13"),
            env_updates=None,
            description="test step",
        )

        command = module._step_command_with_mode(step, "full", force_refresh=True)

        self.assertIn("--force-refresh", command)

    def test_step_command_with_mode_omits_force_refresh_when_not_requested(self) -> None:
        module = self._load_module()
        step = module.RefreshStep(
            name="wnba_oddsapi_props_job",
            phases=("pregame", "live"),
            cwd=Path("."),
            command=("python", "scripts/refresh_wnba_oddsapi_props.py", "--date", "2026-07-13"),
            env_updates=None,
            description="test step",
        )

        command = module._step_command_with_mode(step, "full", force_refresh=False)

        self.assertNotIn("--force-refresh", command)

    def test_step_command_with_mode_does_not_add_force_refresh_for_mlb(self) -> None:
        # MLB's refresh script has no --force-refresh flag (it always overwrites
        # via --overwrite on); appending it would error on an unrecognized arg.
        module = self._load_module()
        step = module.RefreshStep(
            name="mlb_oddsapi_refresh",
            phases=("pregame", "live"),
            cwd=Path("."),
            command=("python", "scripts/refresh_mlb_oddsapi.py", "--date", "2026-07-13"),
            env_updates=None,
            description="test step",
        )

        command = module._step_command_with_mode(step, "full", force_refresh=True)

        self.assertNotIn("--force-refresh", command)

    def test_step_command_with_mode_appends_only_matchups_when_force_refresh_and_scoped(self) -> None:
        module = self._load_module()
        step = module.RefreshStep(
            name="wnba_oddsapi_props_job",
            phases=("pregame", "live"),
            cwd=Path("."),
            command=("python", "scripts/refresh_wnba_oddsapi_props.py", "--date", "2026-07-13"),
            env_updates=None,
            description="test step",
        )

        command = module._step_command_with_mode(step, "full", force_refresh=True, only_matchups="LVA-NYL,SEA-CHI")

        self.assertIn("--only-matchups", command)
        self.assertIn("LVA-NYL,SEA-CHI", command)

    def test_step_command_with_mode_omits_only_matchups_when_force_refresh_false(self) -> None:
        # --only-matchups without --force-refresh would be silently
        # ineffective (refresh_wnba_oddsapi_props.py's own cache-reuse gate
        # skips the run first), so it must never be appended standalone.
        module = self._load_module()
        step = module.RefreshStep(
            name="wnba_oddsapi_props_job",
            phases=("pregame", "live"),
            cwd=Path("."),
            command=("python", "scripts/refresh_wnba_oddsapi_props.py", "--date", "2026-07-13"),
            env_updates=None,
            description="test step",
        )

        command = module._step_command_with_mode(step, "full", force_refresh=False, only_matchups="LVA-NYL")

        self.assertNotIn("--only-matchups", command)

    def test_step_command_with_mode_omits_only_matchups_when_unscoped(self) -> None:
        module = self._load_module()
        step = module.RefreshStep(
            name="wnba_oddsapi_props_job",
            phases=("pregame", "live"),
            cwd=Path("."),
            command=("python", "scripts/refresh_wnba_oddsapi_props.py", "--date", "2026-07-13"),
            env_updates=None,
            description="test step",
        )

        command = module._step_command_with_mode(step, "full", force_refresh=True, only_matchups="")

        self.assertNotIn("--only-matchups", command)

    def test_step_command_with_mode_does_not_add_only_matchups_for_nba(self) -> None:
        # Only refresh_wnba_oddsapi_props.py accepts --only-matchups today;
        # NBA's script would error on an unrecognized argument.
        module = self._load_module()
        step = module.RefreshStep(
            name="nba_oddsapi_props_job",
            phases=("pregame", "live"),
            cwd=Path("."),
            command=("python", "scripts/refresh_nba_oddsapi_props.py", "--date", "2026-07-13"),
            env_updates=None,
            description="test step",
        )

        command = module._step_command_with_mode(step, "full", force_refresh=True, only_matchups="LVA-NYL")

        self.assertNotIn("--only-matchups", command)

    def test_wnba_only_matchups_argument_is_accepted_by_the_parser(self) -> None:
        module = self._load_module()
        with patch.object(
            module.sys,
            "argv",
            ["refresh_odds_sources.py", "--date", "2026-07-13", "--force-refresh", "--wnba-only-matchups", "LVA-NYL", "--list"],
        ), patch("builtins.print"):
            rc = module.main()

        self.assertEqual(rc, 0)

    def test_force_refresh_argument_is_accepted_by_the_parser(self) -> None:
        # Exercise the real argparse parser via main()'s early --list branch
        # (returns 0 without needing the full pipeline). An unrecognized
        # --force-refresh flag would make argparse exit(2) before reaching it.
        module = self._load_module()
        with patch.object(module.sys, "argv", ["refresh_odds_sources.py", "--date", "2026-07-13", "--force-refresh", "--list"]), patch("builtins.print"):
            rc = module.main()

        self.assertEqual(rc, 0)

    def test_force_refresh_sports_argument_is_accepted_by_the_parser(self) -> None:
        module = self._load_module()
        with patch.object(
            module.sys,
            "argv",
            ["refresh_odds_sources.py", "--date", "2026-07-13", "--force-refresh", "--force-refresh-sports", "nba", "--list"],
        ), patch("builtins.print"):
            rc = module.main()

        self.assertEqual(rc, 0)

    def test_sport_force_refresh_scope_defaults_to_all_when_unspecified(self) -> None:
        # Omitting --force-refresh-sports must preserve the original
        # behavior exactly: force_refresh applies to every sport.
        module = self._load_module()
        args = argparse.Namespace(force_refresh=True, force_refresh_sports="")

        self.assertTrue(module._sport_force_refresh_scope(args, "nba"))
        self.assertTrue(module._sport_force_refresh_scope(args, "wnba"))

    def test_sport_force_refresh_scope_narrows_to_specified_sports(self) -> None:
        # An NBA-only lineup/injury change must not also force WNBA's
        # refresh script to bypass its cache.
        module = self._load_module()
        args = argparse.Namespace(force_refresh=True, force_refresh_sports="nba")

        self.assertTrue(module._sport_force_refresh_scope(args, "nba"))
        self.assertFalse(module._sport_force_refresh_scope(args, "wnba"))

    def test_sport_force_refresh_scope_false_when_force_refresh_not_requested(self) -> None:
        module = self._load_module()
        args = argparse.Namespace(force_refresh=False, force_refresh_sports="nba")

        self.assertFalse(module._sport_force_refresh_scope(args, "nba"))
    def test_one_leagues_failed_step_does_not_block_odds_history_sync_for_the_others(self) -> None:
        # Was gated on sport_result["ok"] -- a single AND across EVERY step
        # of the whole sport. For soccer specifically, refresh_steps is a
        # flat list spanning every league's odds/props/picks/artifacts
        # tasks, one entry per (league, task). Confirmed live 2026-08-05: a
        # single unrelated league's fixture-artifact-build step failing (an
        # ESPN 403 on primeira_liga/eredivisie, since fixed separately)
        # silently skipped the odds_history sync for EVERY league including
        # MLS, whose own odds/props steps had already succeeded and written
        # genuinely fresh data. The sync itself only reads whatever files
        # exist on disk, so there was never a correctness reason to require
        # every OTHER step to have succeeded first.
        module = self._load_module()
        args = argparse.Namespace(
            date="2026-08-05",
            sports="soccer",
            phase="pregame",
            regions="us",
            bookmakers="",
            markets="",
            season=None,
            week=None,
            skip_mirror=True,
            execution_mode="source",
            mirror_only=False,
            continue_on_error=True,
            dry_run=False,
            json=False,
            list=False,
        )

        call_count = {"n": 0}

        def _mixed_step_results(step, dry_run=False):
            call_count["n"] += 1
            # First step (an arbitrary league's fixture build, in this
            # reproduction) fails; every other league's step succeeds --
            # exactly the shape observed live.
            ok = call_count["n"] != 1
            return {"ok": ok, "name": step.name, "dry_run": dry_run}

        with patch.object(module, "_run_command", side_effect=_mixed_step_results), patch.object(
            module,
            "_sync_post_refresh_tracking_step",
            return_value={"ok": True, "name": "soccer_post_refresh_tracking_sync", "dry_run": False, "meta": {"signals_rows": 3}},
        ) as mocked_tracking:
            summary = module._build_summary(args)

        self.assertGreater(call_count["n"], 1, "soccer should have more than one refresh step to make this scenario meaningful")
        sport_result = summary["results"][0]
        self.assertFalse(sport_result["ok"], "sport_result[ok] should still correctly reflect the real failure")
        mocked_tracking.assert_called_once()
        self.assertIn("post_refresh", sport_result)
        self.assertEqual(sport_result["post_refresh"]["name"], "soccer_post_refresh_tracking_sync")

    def test_a_sport_with_zero_successful_steps_never_attempts_the_sync(self) -> None:
        # The opposite edge: nothing on disk worth syncing should still
        # correctly skip it, not attempt a no-op sync.
        module = self._load_module()
        args = argparse.Namespace(
            date="2026-08-05",
            sports="soccer",
            phase="pregame",
            regions="us",
            bookmakers="",
            markets="",
            season=None,
            week=None,
            skip_mirror=True,
            execution_mode="source",
            mirror_only=False,
            continue_on_error=True,
            dry_run=False,
            json=False,
            list=False,
        )

        with patch.object(module, "_run_command", return_value={"ok": False, "name": "soccer_every_step_fails", "dry_run": False}), patch.object(
            module,
            "_sync_post_refresh_tracking_step",
        ) as mocked_tracking:
            summary = module._build_summary(args)

        sport_result = summary["results"][0]
        self.assertFalse(sport_result["ok"])
        mocked_tracking.assert_not_called()
        self.assertNotIn("post_refresh", sport_result)

    def test_post_refresh_gate_diagnostic_records_whether_the_gate_was_entered(self) -> None:
        # _log_memory's own trace of this gate is silent in production
        # (gated behind SYNDICATE_LIVE_ODDS_REFRESH_MEMORY_TRACE, default
        # off) -- this always-on companion write is what made it possible
        # to actually observe, in production, whether the fixed gate is
        # being reached and entered for a given sport at all.
        module = self._load_module()
        args = argparse.Namespace(
            date="2026-08-05",
            sports="soccer",
            phase="pregame",
            regions="us",
            bookmakers="",
            markets="",
            season=None,
            week=None,
            skip_mirror=True,
            execution_mode="source",
            mirror_only=False,
            continue_on_error=True,
            dry_run=False,
            json=False,
            list=False,
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.object(module, "_run_command", return_value={"ok": True, "name": "soccer_mls_props", "dry_run": False}), patch.object(
                module,
                "_sync_post_refresh_tracking_step",
                return_value={"ok": True, "name": "soccer_post_refresh_tracking_sync", "dry_run": False, "meta": {}},
            ), patch(
                "syndicate.features.shared.refresh_state_store.reports_root", return_value=Path(tmp_dir)
            ):
                module._build_summary(args)

            status_path = Path(tmp_dir) / "refresh_status" / "latest" / "odds_history_post_refresh_gate_status.json"
            self.assertTrue(status_path.exists())
            status_payload = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertIn("soccer", status_payload)
            self.assertTrue(status_payload["soccer"]["gate_entered"])
            self.assertTrue(status_payload["soccer"]["sport_had_a_successful_step"])
