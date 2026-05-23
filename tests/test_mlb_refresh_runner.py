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

        class _FakeWebModule:
            def __init__(self) -> None:
                self.live_lens_calls = 0

            def _local_now(self):
                return datetime(2026, 5, 22, 12, 0, 0)

            def _freeze_oddsapi_pregame_markets(self, _date: str):
                return {"ok": True}

            def _daily_snapshot_dir(self, date_str: str):
                return str(Path.cwd() / "data" / "daily" / "snapshots" / date_str)

            def _ensure_dir(self, path: Path):
                Path(path).mkdir(parents=True, exist_ok=True)
                return path

            def _archive_oddsapi_refresh_outputs(self, _date: str, _result, *, recorded_at):
                return {"recordedAt": recorded_at.isoformat()}

            def _local_timestamp_text(self, value):
                return value.isoformat()

            def _write_json_file(self, path: Path, value):
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                Path(path).write_text(str(value), encoding="utf-8")

            def _cron_meta_dir(self):
                return Path.cwd() / "data" / "live_lens" / "cron_meta"

            def _persist_live_lens_tick(self, _date: str, *, trigger: str, refresh_markets: bool):
                self.live_lens_calls += 1
                return {"ok": True, "trigger": trigger, "refresh_markets": refresh_markets}

        odds_module = _FakeOddsModule()
        web_module = _FakeWebModule()

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
            with patch.object(module, "_load_source_modules", return_value=(odds_module, web_module)), patch("sys.argv", argv):
                rc = module.main()

        self.assertEqual(rc, 0)
        self.assertEqual(len(odds_module.calls), 1)
        self.assertEqual(odds_module.calls[0]["date"], "2026-05-22")
        self.assertEqual(odds_module.calls[0]["regions"], "us,eu")
        self.assertEqual(web_module.live_lens_calls, 1)

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
                source_root / "data" / "live_lens" / "prop_registry" / f"live_prop_registry_{date_slug}.json": "{}\n",
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

            class _FakeWebModule:
                def _local_now(self):
                    return datetime(2026, 5, 22, 12, 0, 0)

                def _freeze_oddsapi_pregame_markets(self, _date: str):
                    return {"ok": True}

                def _daily_snapshot_dir(self, current_date: str):
                    return str(source_root / "data" / "daily" / "snapshots" / current_date)

                def _ensure_dir(self, path: Path):
                    Path(path).mkdir(parents=True, exist_ok=True)
                    return path

                def _archive_oddsapi_refresh_outputs(self, current_date: str, _result, *, recorded_at):
                    archive_dir = source_root / "data" / "market" / "oddsapi" / "refresh_history" / date_slug / "20260522T120000_000000Z"
                    archive_dir.mkdir(parents=True, exist_ok=True)
                    (archive_dir / "refresh_meta.json").write_text(recorded_at.isoformat(), encoding="utf-8")
                    return {"archiveDir": str(archive_dir)}

                def _local_timestamp_text(self, value):
                    return value.isoformat()

                def _write_json_file(self, path: Path, value):
                    Path(path).parent.mkdir(parents=True, exist_ok=True)
                    Path(path).write_text(json.dumps(value), encoding="utf-8")

                def _cron_meta_dir(self):
                    return source_root / "data" / "live_lens" / "cron_meta"

                def _persist_live_lens_tick(self, current_date: str, *, trigger: str, refresh_markets: bool):
                    report_path = source_root / "data" / "live_lens" / f"live_lens_{date_slug}.jsonl"
                    report_path.parent.mkdir(parents=True, exist_ok=True)
                    report_path.write_text("{}\n", encoding="utf-8")
                    observations = source_root / "data" / "live_lens" / "prop_registry" / f"live_prop_observations_{date_slug}.jsonl"
                    observations.parent.mkdir(parents=True, exist_ok=True)
                    observations.write_text("{}\n", encoding="utf-8")
                    return {"ok": True, "date": current_date, "trigger": trigger, "refresh_markets": refresh_markets}

            argv = [
                "refresh_mlb_oddsapi.py",
                "--date",
                date_str,
                "--source-root",
                str(source_root),
                "--artifact-root",
                str(artifact_root),
            ]
            with patch.object(module, "_load_source_modules", return_value=(_FakeOddsModule(), _FakeWebModule())), patch("sys.argv", argv):
                rc = module.main()

            self.assertEqual(rc, 0)
            self.assertTrue((artifact_root / "data" / "daily" / f"daily_summary_{date_slug}.json").exists())
            self.assertTrue((artifact_root / "data" / "live_lens" / f"live_lens_report_{date_slug}.json").exists())
            self.assertTrue((artifact_root / "data" / "daily" / "snapshots" / date_str / f"oddsapi_game_lines_{date_slug}.json").exists())
            self.assertTrue((artifact_root / "data" / "market" / "oddsapi" / "refresh_history" / date_slug / "20260522T120000_000000Z" / "refresh_meta.json").exists())
            self.assertTrue((artifact_root / "sim_engine" / "live_prop_ranking.py").exists())
            self.assertTrue((artifact_root / "data" / "eval" / "seasons" / season / "season_eval_manifest.json").exists())