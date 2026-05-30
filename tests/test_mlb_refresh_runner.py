from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


class MlbRefreshRunnerTests(unittest.TestCase):
    def _load_module(self):
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "refresh_mlb_oddsapi.py"
        spec = importlib.util.spec_from_file_location("test_refresh_mlb_oddsapi", script_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_main_calls_source_modules_directly(self) -> None:
        module = self._load_module()

        class _FakeOddsModule:
            def __init__(self) -> None:
                self.calls: list[dict[str, object]] = []

            def fetch_and_write_live_odds_for_date(self, date_str: str, *, out_dir, overwrite: bool, regions: str):
                self.calls.append(
                    {
                        "date": date_str,
                        "out_dir": str(out_dir),
                        "overwrite": overwrite,
                        "regions": regions,
                    }
                )
                return {}

        odds_module = _FakeOddsModule()

        with tempfile.TemporaryDirectory() as tmp_dir:
            source_root = Path(tmp_dir) / "source"
            (source_root / "data").mkdir(parents=True)
            argv = [
                "refresh_mlb_oddsapi.py",
                "--date",
                "2026-05-22",
                "--source-root",
                str(source_root),
                "--artifact-root",
                str(Path(tmp_dir) / "bundle"),
                "--regions",
                "us,eu",
            ]
            with patch.object(module, "_load_local_fetcher", return_value=odds_module), patch("sys.argv", argv):
                rc = module.main()

        self.assertEqual(rc, 0)
        self.assertEqual(len(odds_module.calls), 1)
        self.assertEqual(odds_module.calls[0]["date"], "2026-05-22")
        self.assertEqual(odds_module.calls[0]["regions"], "us,eu")

    def test_main_prefers_existing_source_artifacts_when_overwrite_off(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            artifact_root = tmp_root / "bundle"
            date_str = "2026-05-22"
            date_slug = "2026_05_22"
            season = "2026"

            ready_paths = (
                source_root / "data" / "daily" / f"daily_summary_{date_slug}.json",
                source_root / "data" / "live_lens" / f"live_lens_report_{date_slug}.json",
                source_root / "data" / "daily" / "snapshots" / date_str / f"oddsapi_game_lines_{date_slug}.json",
                source_root / "data" / "market" / "oddsapi" / "refresh_history" / date_slug / "20260522T120000_000000Z" / "refresh_meta.json",
                source_root / "data" / "eval" / "seasons" / season / "season_eval_manifest.json",
                source_root / "data" / "live_lens" / "prop_registry" / f"live_prop_registry_{date_slug}.json",
                source_root / "data" / "tuning" / "live_prop_ranking" / "default.json",
                source_root / "sim_engine" / "live_prop_ranking.py",
            )
            for path in ready_paths:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}\n", encoding="utf-8")

            argv = [
                "refresh_mlb_oddsapi.py",
                "--date",
                date_str,
                "--source-root",
                str(source_root),
                "--artifact-root",
                str(artifact_root),
                "--overwrite",
                "off",
            ]
            with patch.object(module, "_load_local_fetcher", side_effect=AssertionError("local fetcher should not load")), patch("sys.argv", argv):
                rc = module.main()

            self.assertEqual(rc, 0)
            self.assertTrue((artifact_root / "data" / "daily" / f"daily_summary_{date_slug}.json").exists())
            self.assertTrue((artifact_root / "data" / "live_lens" / f"live_lens_report_{date_slug}.json").exists())

    def test_main_refreshes_live_lens_when_overwrite_off(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            artifact_root = tmp_root / "bundle"
            date_str = "2026-05-22"
            date_slug = "2026_05_22"
            season = "2026"

            ready_paths = (
                source_root / "data" / "daily" / f"daily_summary_{date_slug}.json",
                source_root / "data" / "live_lens" / f"live_lens_report_{date_slug}.json",
                source_root / "data" / "daily" / "snapshots" / date_str / f"oddsapi_game_lines_{date_slug}.json",
                source_root / "data" / "market" / "oddsapi" / "refresh_history" / date_slug / "20260522T120000_000000Z" / "refresh_meta.json",
                source_root / "data" / "eval" / "seasons" / season / "season_eval_manifest.json",
                source_root / "data" / "live_lens" / "prop_registry" / f"live_prop_registry_{date_slug}.json",
                source_root / "data" / "tuning" / "live_prop_ranking" / "default.json",
                source_root / "sim_engine" / "live_prop_ranking.py",
            )
            for path in ready_paths:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}\n", encoding="utf-8")

            payload = {
                "generatedAt": "2026-05-22T19:15:00-05:00",
                "counts": {"games": 1, "live": 1, "pregame": 0, "final": 0, "props": 0, "archivedLiveProps": 0},
                "games": [{"gamePk": 1}],
            }
            argv = [
                "refresh_mlb_oddsapi.py",
                "--date",
                date_str,
                "--source-root",
                str(source_root),
                "--artifact-root",
                str(artifact_root),
                "--overwrite",
                "off",
            ]
            with patch.object(module, "_load_local_fetcher", side_effect=AssertionError("local fetcher should not load")), \
                patch.object(module, "_fetch_live_lens_reports_payload", return_value=payload), \
                patch.dict("os.environ", {"MLB_BETTING_BASE_URL": "https://example.com", "MLB_BETTING_CRON_TOKEN": "token"}, clear=False), \
                patch("sys.argv", argv):
                rc = module.main()

            self.assertEqual(rc, 0)
            report_path = source_root / "data" / "live_lens" / f"live_lens_report_{date_slug}.json"
            self.assertTrue(report_path.exists())
            self.assertEqual(json.loads(report_path.read_text(encoding="utf-8"))["counts"]["live"], 1)
            self.assertEqual(
                json.loads((artifact_root / "data" / "live_lens" / f"live_lens_report_{date_slug}.json").read_text(encoding="utf-8"))["counts"]["live"],
                1,
            )

    def test_main_materializes_mlb_artifacts_into_bundle_root(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            artifact_root = tmp_root / "bundle"
            date_str = "2026-05-22"
            date_slug = "2026_05_22"
            season = "2026"

            required_files = {
                source_root / "data" / "daily" / f"daily_summary_{date_slug}.json": "{}\n",
                source_root / "data" / "live_lens" / f"live_lens_report_{date_slug}.json": "{}\n",
                source_root / "data" / "live_lens" / f"live_lens_{date_slug}.jsonl": "{}\n",
                source_root / "data" / "live_lens" / "prop_registry" / f"live_prop_registry_{date_slug}.json": "{}\n",
                source_root / "data" / "live_lens" / "prop_registry" / f"live_prop_observations_{date_slug}.jsonl": "{}\n",
                source_root / "data" / "tuning" / "live_prop_ranking" / "default.json": "{}\n",
                source_root / "sim_engine" / "live_prop_ranking.py": "def rank():\n    return []\n",
                source_root / "data" / "eval" / "seasons" / season / "season_eval_manifest.json": "{}\n",
            }
            for path, content in required_files.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

            snapshot_dir = source_root / "data" / "daily" / "snapshots" / date_str
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            (snapshot_dir / f"oddsapi_game_lines_{date_slug}.json").write_text("{}\n", encoding="utf-8")

            refresh_history_dir = source_root / "data" / "market" / "oddsapi" / "refresh_history" / date_slug / "20260522T120000_000000Z"
            refresh_history_dir.mkdir(parents=True, exist_ok=True)
            (refresh_history_dir / "refresh_meta.json").write_text("{}\n", encoding="utf-8")

            class _FakeOddsModule:
                def fetch_and_write_live_odds_for_date(self, date_str: str, *, out_dir, overwrite: bool, regions: str):
                    out_dir = Path(out_dir)
                    out_dir.mkdir(parents=True, exist_ok=True)
                    game = out_dir / f"oddsapi_game_lines_{date_slug}.json"
                    pitcher = out_dir / f"oddsapi_pitcher_props_{date_slug}.json"
                    hitter = out_dir / f"oddsapi_hitter_props_{date_slug}.json"
                    game.write_text("{}\n", encoding="utf-8")
                    pitcher.write_text("{}\n", encoding="utf-8")
                    hitter.write_text("{}\n", encoding="utf-8")
                    return {
                        "game_lines_path": str(game),
                        "pitcher_props_path": str(pitcher),
                        "hitter_props_path": str(hitter),
                    }

            argv = [
                "refresh_mlb_oddsapi.py",
                "--date",
                date_str,
                "--source-root",
                str(source_root),
                "--artifact-root",
                str(artifact_root),
            ]
            with patch.object(module, "_load_local_fetcher", return_value=_FakeOddsModule()), patch.object(module, "_local_now", return_value=datetime(2026, 5, 22, 12, 0, 0).astimezone()), patch("sys.argv", argv):
                rc = module.main()

            self.assertEqual(rc, 0)
            self.assertTrue((artifact_root / "data" / "daily" / f"daily_summary_{date_slug}.json").exists())
            self.assertTrue((artifact_root / "data" / "live_lens" / f"live_lens_report_{date_slug}.json").exists())
            self.assertTrue((artifact_root / "data" / "live_lens" / f"live_lens_{date_slug}.jsonl").exists())
            self.assertTrue((artifact_root / "data" / "live_lens" / "prop_registry" / f"live_prop_registry_{date_slug}.json").exists())
            self.assertTrue((artifact_root / "data" / "daily" / "snapshots" / date_str / f"oddsapi_game_lines_{date_slug}.json").exists())
            self.assertTrue((artifact_root / "data" / "market" / "oddsapi" / "refresh_history" / date_slug / "20260522T120000_000000Z" / "refresh_meta.json").exists())
            self.assertTrue((artifact_root / "sim_engine" / "live_prop_ranking.py").exists())
            self.assertTrue((artifact_root / "data" / "eval" / "seasons" / season / "season_eval_manifest.json").exists())

    def test_main_overwrites_existing_bundle_tree_without_deleting_root_first(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            artifact_root = tmp_root / "bundle"
            date_str = "2026-05-22"
            date_slug = "2026_05_22"
            season = "2026"

            required_files = {
                source_root / "data" / "daily" / f"daily_summary_{date_slug}.json": "{}\n",
                source_root / "data" / "live_lens" / f"live_lens_report_{date_slug}.json": "{}\n",
                source_root / "data" / "live_lens" / f"live_lens_{date_slug}.jsonl": "{}\n",
                source_root / "data" / "live_lens" / "prop_registry" / f"live_prop_registry_{date_slug}.json": "{}\n",
                source_root / "data" / "live_lens" / "prop_registry" / f"live_prop_observations_{date_slug}.jsonl": "{}\n",
                source_root / "data" / "tuning" / "live_prop_ranking" / "default.json": "{}\n",
                source_root / "sim_engine" / "live_prop_ranking.py": "def rank():\n    return []\n",
                source_root / "data" / "eval" / "seasons" / season / "season_eval_manifest.json": "{}\n",
            }
            for path, content in required_files.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

            snapshot_dir = source_root / "data" / "daily" / "snapshots" / date_str
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            (snapshot_dir / f"oddsapi_game_lines_{date_slug}.json").write_text("{\"fresh\": true}\n", encoding="utf-8")

            refresh_history_dir = source_root / "data" / "market" / "oddsapi" / "refresh_history" / date_slug / "20260522T120000_000000Z"
            refresh_history_dir.mkdir(parents=True, exist_ok=True)
            (refresh_history_dir / "refresh_meta.json").write_text("{}\n", encoding="utf-8")

            existing_snapshot_dir = artifact_root / "data" / "daily" / "snapshots" / date_str
            existing_snapshot_dir.mkdir(parents=True, exist_ok=True)
            (existing_snapshot_dir / "stale.json").write_text("{}\n", encoding="utf-8")

            class _FakeOddsModule:
                def fetch_and_write_live_odds_for_date(self, date_str: str, *, out_dir, overwrite: bool, regions: str):
                    out_dir = Path(out_dir)
                    out_dir.mkdir(parents=True, exist_ok=True)
                    game = out_dir / f"oddsapi_game_lines_{date_slug}.json"
                    pitcher = out_dir / f"oddsapi_pitcher_props_{date_slug}.json"
                    hitter = out_dir / f"oddsapi_hitter_props_{date_slug}.json"
                    game.write_text("{}\n", encoding="utf-8")
                    pitcher.write_text("{}\n", encoding="utf-8")
                    hitter.write_text("{}\n", encoding="utf-8")
                    return {
                        "game_lines_path": str(game),
                        "pitcher_props_path": str(pitcher),
                        "hitter_props_path": str(hitter),
                    }

            argv = [
                "refresh_mlb_oddsapi.py",
                "--date",
                date_str,
                "--source-root",
                str(source_root),
                "--artifact-root",
                str(artifact_root),
            ]
            with patch.object(module, "_load_local_fetcher", return_value=_FakeOddsModule()), patch.object(module, "_local_now", return_value=datetime(2026, 5, 22, 12, 0, 0).astimezone()), patch("sys.argv", argv):
                rc = module.main()

            self.assertEqual(rc, 0)
            self.assertTrue((artifact_root / "data" / "daily" / "snapshots" / date_str / f"oddsapi_game_lines_{date_slug}.json").exists())