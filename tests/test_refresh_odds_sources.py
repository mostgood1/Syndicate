from __future__ import annotations

import json
import argparse
import importlib.util
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
        self.assertEqual(sport_result["sport_manifest"], manifest_payload)
        mocked_publish.assert_called_once()
        _, kwargs = mocked_publish.call_args
        self.assertEqual(kwargs["sport"], "wnba")
        self.assertIn("artifact_paths", kwargs)
        self.assertEqual(kwargs["metadata"]["execution_mode"], "source")

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

    def test_wnba_uses_player_prop_markets_while_other_basketball_sports_keep_interval_defaults(self) -> None:
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
        player_prop_markets = "player_points,player_rebounds,player_assists,player_points_rebounds_assists,player_threes,player_steals,player_blocks,player_turnovers,player_points_rebounds,player_points_assists,player_rebounds_assists,player_double_double,player_triple_double"

        self.assertIn("--markets", nba_steps[0].command)
        self.assertIn(interval_markets, nba_steps[0].command)
        self.assertIn("--markets", wnba_steps[0].command)
        self.assertIn(player_prop_markets, wnba_steps[0].command)
        self.assertNotIn(interval_markets, wnba_steps[0].command)
        self.assertIn("--markets", ncaab_steps[0].command)
        self.assertIn(interval_markets, ncaab_steps[0].command)

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
        self.assertEqual(len(artifact_paths), 4)