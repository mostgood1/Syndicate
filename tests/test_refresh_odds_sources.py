from __future__ import annotations

import argparse
import importlib.util
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