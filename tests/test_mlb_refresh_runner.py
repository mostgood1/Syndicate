from __future__ import annotations

import importlib.util
import json
import os
import sys
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

    def test_live_lens_report_refresh_default_is_thirty_seconds(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module_path = repo_root / "vendor" / "mlb_bettingv2" / "tools" / "web" / "flask_frontend.py"
        spec = importlib.util.spec_from_file_location("test_mlb_flask_frontend", module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module

        try:
            with patch.dict(os.environ, {}, clear=True):
                spec.loader.exec_module(module)

            self.assertEqual(module._live_lens_report_refresh_interval_seconds(), 30)
        finally:
            sys.modules.pop(spec.name, None)

    def test_live_lens_data_dir_prefers_render_disk_when_only_syndicate_root_is_set(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module_path = repo_root / "vendor" / "mlb_bettingv2" / "tools" / "web" / "flask_frontend.py"
        spec = importlib.util.spec_from_file_location("test_mlb_flask_frontend_data_dir", module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module

        with tempfile.TemporaryDirectory() as tmp_dir:
            syndicate_root = Path(tmp_dir)
            expected_root = syndicate_root / "mlb_source" / "source_artifacts" / "data"
            expected_root.mkdir(parents=True, exist_ok=True)

            try:
                with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": str(syndicate_root)}, clear=True):
                    spec.loader.exec_module(module)

                self.assertEqual(module._DATA_DIR, expected_root.resolve())
                self.assertEqual(module._LIVE_LENS_DIR, (expected_root / "live_lens").resolve())
            finally:
                sys.modules.pop(spec.name, None)

    def test_live_lens_reports_payload_overrides_stale_report_metadata(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module_path = repo_root / "vendor" / "mlb_bettingv2" / "tools" / "web" / "flask_frontend.py"
        spec = importlib.util.spec_from_file_location("test_mlb_flask_frontend_reports", module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module

        try:
            with tempfile.TemporaryDirectory() as tmp_dir, patch.dict(os.environ, {}, clear=True):
                spec.loader.exec_module(module)
                runtime_root = Path(tmp_dir) / "source" / "data"
                module._DATA_DIR = runtime_root
                module._LIVE_LENS_DIR = runtime_root / "live_lens"
                expected_data_root = module._relative_path_str(runtime_root)
                expected_live_lens_dir = module._relative_path_str(runtime_root / "live_lens")
                module._local_timestamp_text = lambda: "2026-06-01T21:00:00-05:00"
                module._load_json_file = lambda path: {
                    "generatedAt": "1999-01-01T00:00:00-05:00",
                    "dataRoot": "C:/stale/data",
                    "liveLensDir": "C:/stale/data/live_lens",
                    "counts": {"games": 1, "live": 1, "final": 0, "pregame": 0, "props": 0, "archivedLiveProps": 0},
                }
                module._live_prop_registry_summary = lambda d: {}
                module._load_live_prop_first_observation_archive = lambda d: []
                module._live_lens_optimization_regime = lambda d: "baseline"
                module._live_lens_log_path = lambda d: runtime_root / f"live_lens_{d}.jsonl"
                module._live_prop_observation_log_path = lambda d: runtime_root / "prop_registry" / f"live_prop_observations_{d}.jsonl"
                module._live_prop_registry_path = lambda d: runtime_root / "prop_registry" / f"live_prop_registry_{d}.json"
                module._live_prop_registry_log_path = lambda d: runtime_root / "prop_registry" / f"live_prop_registry_{d}.jsonl"
                module._live_lens_daily_recap_path = lambda d: runtime_root / "recaps" / f"live_lens_daily_recap_{d}.json"

                payload = module._live_lens_reports_payload("2026-06-01")

            self.assertEqual(payload["latestReport"]["generatedAt"], "2026-06-01T21:00:00-05:00")
            self.assertEqual(payload["latestReport"]["dataRoot"], expected_data_root)
            self.assertEqual(payload["latestReport"]["liveLensDir"], expected_live_lens_dir)
        finally:
            sys.modules.pop(spec.name, None)

    def test_api_live_lens_overrides_stale_report_metadata_on_read_path(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module_path = repo_root / "vendor" / "mlb_bettingv2" / "tools" / "web" / "flask_frontend.py"
        spec = importlib.util.spec_from_file_location("test_mlb_flask_frontend_api_live_lens", module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module

        try:
            with tempfile.TemporaryDirectory() as tmp_dir, patch.dict(os.environ, {}, clear=True):
                spec.loader.exec_module(module)
                runtime_root = Path(tmp_dir) / "source" / "data"
                runtime_live_lens_dir = runtime_root / "live_lens"
                runtime_root.mkdir(parents=True, exist_ok=True)
                runtime_live_lens_dir.mkdir(parents=True, exist_ok=True)
                report_path = runtime_live_lens_dir / "live_lens_report_2026_06_01.json"
                report_path.write_text("{}\n", encoding="utf-8")
                module._DATA_DIR = runtime_root
                module._LIVE_LENS_DIR = runtime_live_lens_dir
                module._is_live_lens_loop_enabled = lambda: False
                module._local_timestamp_text = lambda: "2026-06-01T21:00:00-05:00"
                module._live_lens_report_path = lambda d: report_path
                module._load_json_file = lambda path: {
                    "generatedAt": "1999-01-01T00:00:00-05:00",
                    "dataRoot": "C:/stale/data",
                    "liveLensDir": "C:/stale/data/live_lens",
                    "counts": {"games": 1, "live": 1, "final": 0, "pregame": 0, "props": 0, "archivedLiveProps": 0},
                }

                with module.app.test_client() as client:
                    response = client.get("/api/live-lens?date=2026-06-01")

                self.assertEqual(response.status_code, 200)
                payload = response.get_json()

            self.assertIsInstance(payload, dict)
            self.assertEqual(payload["generatedAt"], "2026-06-01T21:00:00-05:00")
            self.assertEqual(payload["dataRoot"], module._relative_path_str(runtime_root))
            self.assertEqual(payload["liveLensDir"], module._relative_path_str(runtime_live_lens_dir))
        finally:
            sys.modules.pop(spec.name, None)

    def test_api_live_lens_persist_bypasses_cache_and_rewrites_report(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module_path = repo_root / "vendor" / "mlb_bettingv2" / "tools" / "web" / "flask_frontend.py"
        spec = importlib.util.spec_from_file_location("test_mlb_flask_frontend_api_live_lens_persist", module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module

        try:
            with tempfile.TemporaryDirectory() as tmp_dir, patch.dict(os.environ, {}, clear=True):
                spec.loader.exec_module(module)
                runtime_root = Path(tmp_dir) / "source" / "data"
                runtime_live_lens_dir = runtime_root / "live_lens"
                runtime_live_lens_dir.mkdir(parents=True, exist_ok=True)
                report_path = runtime_live_lens_dir / "live_lens_report_2026_06_01.json"
                counter = {"value": 0}

                def fake_live_lens_payload(date_str: str, *, persist: bool = False, refresh_markets: bool = False):
                    counter["value"] += 1
                    payload = {
                        "date": date_str,
                        "generatedAt": f"2026-06-01T21:00:0{counter['value']}-05:00",
                        "dataRoot": module._relative_path_str(runtime_root),
                        "liveLensDir": module._relative_path_str(runtime_live_lens_dir),
                        "counts": {"games": 1, "live": 1, "final": 0, "pregame": 0, "props": 0, "archivedLiveProps": 0},
                        "performance": {"marketsRefreshed": bool(refresh_markets), "persistMs": 0.0},
                        "games": [],
                    }
                    report_path.write_text(json.dumps(payload), encoding="utf-8")
                    return payload

                module._DATA_DIR = runtime_root
                module._LIVE_LENS_DIR = runtime_live_lens_dir
                module._is_live_lens_loop_enabled = lambda: False
                module._is_historical_date = lambda d: False
                module._live_lens_report_path = lambda d: report_path
                module._payload_cache_get_or_build = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("cache should be bypassed for persist=on"))
                module._live_lens_payload = fake_live_lens_payload

                with module.app.test_client() as client:
                    first_response = client.get("/api/live-lens?date=2026-06-01&persist=on")
                    second_response = client.get("/api/live-lens?date=2026-06-01&persist=on")

                first_payload = first_response.get_json()
                second_payload = second_response.get_json()
                report_payload = json.loads(report_path.read_text(encoding="utf-8"))

            self.assertEqual(first_response.status_code, 200)
            self.assertEqual(second_response.status_code, 200)
            self.assertEqual(counter["value"], 2)
            self.assertEqual(first_payload["generatedAt"], "2026-06-01T21:00:01-05:00")
            self.assertEqual(second_payload["generatedAt"], "2026-06-01T21:00:02-05:00")
            self.assertEqual(report_payload["generatedAt"], "2026-06-01T21:00:02-05:00")
        finally:
            sys.modules.pop(spec.name, None)

    def test_build_live_lens_page_context_persist_rewrites_report(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        module_path = repo_root / "syndicate" / "features" / "mlb" / "live_lens.py"
        spec = importlib.util.spec_from_file_location("test_mlb_live_lens_feature", module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module

        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                spec.loader.exec_module(module)
                runtime_root = Path(tmp_dir) / "source" / "data"
                runtime_live_lens_dir = runtime_root / "live_lens"
                runtime_live_lens_dir.mkdir(parents=True, exist_ok=True)
                report_path = runtime_live_lens_dir / "live_lens_report_2026_06_01.json"
                report_path.write_text(
                    json.dumps(
                        {
                            "generatedAt": "1999-01-01T00:00:00-05:00",
                            "counts": {"games": 1, "live": 1, "final": 0, "pregame": 0, "props": 0, "archivedLiveProps": 0},
                            "games": [],
                            "dataRoot": "stale",
                            "liveLensDir": "stale",
                        }
                    ),
                    encoding="utf-8",
                )

                counter = {"value": 0}

                def fake_persist(selected_date: str):
                    counter["value"] += 1
                    payload = {
                        "generatedAt": f"2026-06-01T21:00:0{counter['value']}-05:00",
                        "counts": {"games": 1, "live": 1, "final": 0, "pregame": 0, "props": 0, "archivedLiveProps": 0},
                        "games": [],
                        "dataRoot": module.live_lens_report_path(selected_date).parent.parent.as_posix(),
                        "liveLensDir": module.live_lens_report_path(selected_date).parent.as_posix(),
                        "optimizationRegime": None,
                    }
                    report_path.write_text(json.dumps(payload), encoding="utf-8")
                    return payload

                module.live_lens_report_path = lambda d: report_path
                module.load_json_file = lambda path: json.loads(report_path.read_text(encoding="utf-8"))
                module._persist_live_lens_report = fake_persist

                first_context = module.build_live_lens_page_context("2026-06-01", persist=True)
                second_context = module.build_live_lens_page_context("2026-06-01", persist=True)
                persisted_report = json.loads(report_path.read_text(encoding="utf-8"))

            self.assertEqual(counter["value"], 2)
            self.assertEqual(first_context["generatedAt"], "2026-06-01T21:00:01-05:00")
            self.assertEqual(second_context["generatedAt"], "2026-06-01T21:00:02-05:00")
            self.assertEqual(persisted_report["generatedAt"], "2026-06-01T21:00:02-05:00")
        finally:
            sys.modules.pop(spec.name, None)

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

    def test_main_builds_live_lens_locally_when_http_refresh_is_unavailable(self) -> None:
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
                "counts": {"games": 2, "live": 1, "pregame": 1, "final": 0, "props": 3, "archivedLiveProps": 0},
                "games": [{"gamePk": 1}, {"gamePk": 2}],
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
                patch.object(module, "_build_local_live_lens_reports_payload", return_value=payload) as local_builder, \
                patch.dict("os.environ", {"MLB_BETTING_BASE_URL": "", "MLB_BETTING_CRON_TOKEN": ""}, clear=False), \
                patch("sys.argv", argv):
                rc = module.main()

            self.assertEqual(rc, 0)
            self.assertEqual(local_builder.call_count, 1)
            self.assertEqual(local_builder.call_args.kwargs["source_root"].resolve(), source_root.resolve())
            self.assertEqual(local_builder.call_args.kwargs["date_str"], date_str)
            report_path = source_root / "data" / "live_lens" / f"live_lens_report_{date_slug}.json"
            self.assertTrue(report_path.exists())
            self.assertEqual(json.loads(report_path.read_text(encoding="utf-8"))["counts"]["props"], 3)

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

    def test_render_live_lens_refresh_always_requests_market_refresh(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "vendor" / "mlb_bettingv2" / "tools" / "render_live_lens_refresh.py"
        spec = importlib.util.spec_from_file_location("test_render_live_lens_refresh", script_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        calls: list[dict[str, object]] = []

        def _fake_request(session, method, url, *, token, timeout, params=None):
            calls.append(
                {
                    "method": method,
                    "url": url,
                    "token": token,
                    "timeout": timeout,
                    "params": dict(params or {}),
                }
            )
            return {"ok": True, "url": url}

        with patch.dict(
            module.os.environ,
            {
                "MLB_CRON_TOKEN": "token",
                "MLB_WEB_INTERNAL_BASE_URL": "http://example.test",
                "MLB_LIVE_LENS_MARKET_REFRESH_INTERVAL_MINUTES": "999",
            },
            clear=False,
        ), patch.object(module, "_request", side_effect=_fake_request):
            rc = module.main()

        self.assertEqual(rc, 0)
        self.assertEqual([call["url"] for call in calls], [
            "http://example.test/api/cron/refresh-oddsapi-markets",
            "http://example.test/api/cron/live-lens-tick",
            "http://example.test/api/cron/warm-cards-cache",
        ])
        self.assertEqual(calls[0]["params"], {"republish": "off", "overwrite": "on"})
        self.assertEqual(calls[1]["params"], {"refreshMarkets": "off"})