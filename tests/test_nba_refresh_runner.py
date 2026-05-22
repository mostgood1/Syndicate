from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class NbaRefreshRunnerTests(unittest.TestCase):
    def _load_module(self):
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "refresh_nba_oddsapi_props.py"
        spec = importlib.util.spec_from_file_location("test_refresh_nba_oddsapi_props", script_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_main_calls_source_refresh_function_directly(self) -> None:
        module = self._load_module()

        class _FakeSourceModule:
            def __init__(self) -> None:
                self.calls = []

            def run_refresh_oddsapi_props_job(self, **kwargs):
                self.calls.append(kwargs)
                return {
                    "snapshot_rows": 12,
                    "snapshot_alias_rows": 12,
                    "edges_rows": 5,
                    "recs_rows": 3,
                    "error": None,
                }

        fake_source = _FakeSourceModule()
        with tempfile.TemporaryDirectory() as tmp_dir:
            argv = [
                "refresh_nba_oddsapi_props.py",
                "--date",
                "2026-05-22",
                "--regions",
                "us",
                "--source-root",
                tmp_dir,
                "--log-file",
                str(Path(tmp_dir) / "refresh.log"),
                "--do-edges",
                "--do-export",
            ]
            with patch.object(module, "_load_source_module", return_value=fake_source), patch("sys.argv", argv):
                rc = module.main()

        self.assertEqual(rc, 0)
        self.assertEqual(len(fake_source.calls), 1)
        self.assertEqual(fake_source.calls[0]["date_str"], "2026-05-22")
        self.assertTrue(fake_source.calls[0]["do_edges"])
        self.assertTrue(fake_source.calls[0]["do_export"])

    def test_main_materializes_core_artifacts_into_bundle_root(self) -> None:
        module = self._load_module()

        class _FakeSourceModule:
            def run_refresh_oddsapi_props_job(self, **kwargs):
                return {
                    "date": "2026-05-22",
                    "snapshot_rows": 12,
                    "snapshot_alias_rows": 12,
                    "edges_rows": 5,
                    "recs_rows": 3,
                    "error": None,
                    "snapshot_path": kwargs["log_file"].parent / "odds_nba_player_props_2026-05-22.csv",
                    "snapshot_alias_path": kwargs["log_file"].parent / "oddsapi_player_props_2026-05-22.csv",
                    "predictions_path": kwargs["log_file"].parent / "props_predictions_2026-05-22.csv",
                    "edges_path": kwargs["log_file"].parent / "props_edges_2026-05-22.csv",
                    "recs_path": kwargs["log_file"].parent / "props_recommendations_2026-05-22.csv",
                }

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            for name in [
                "odds_nba_player_props_2026-05-22.csv",
                "oddsapi_player_props_2026-05-22.csv",
                "props_predictions_2026-05-22.csv",
                "props_edges_2026-05-22.csv",
                "props_recommendations_2026-05-22.csv",
                "smart_sim_2026-05-22_BOS_NYK.json",
                "smart_sim_2026-05-22_LAL_GSW.json",
            ]:
                (tmp_root / name).write_text("id\n1\n", encoding="utf-8")
            source_root = tmp_root / "source"
            source_root.mkdir()
            artifact_root = tmp_root / "bundle"
            argv = [
                "refresh_nba_oddsapi_props.py",
                "--date",
                "2026-05-22",
                "--regions",
                "us",
                "--source-root",
                str(source_root),
                "--artifact-root",
                str(artifact_root),
                "--log-file",
                str(tmp_root / "refresh.log"),
                "--do-edges",
                "--do-export",
            ]
            class _FakeSourceApp:
                class _Client:
                    @staticmethod
                    def get(_query):
                        class _Response:
                            @staticmethod
                            def get_json():
                                return {"data": [{"player": "Test NBA Player"}]}

                            status_code = 200

                        return _Response()

                app = type("_App", (), {"test_client": staticmethod(lambda: _FakeSourceApp._Client())})()

            with patch.object(module, "_load_source_module", return_value=_FakeSourceModule()), patch.object(module, "_load_source_app", return_value=_FakeSourceApp()), patch("sys.argv", argv):
                rc = module.main()

            self.assertEqual(rc, 0)
            self.assertTrue((artifact_root / "data" / "raw" / "odds_nba_player_props_2026-05-22.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "oddsapi_player_props_2026-05-22.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "props_predictions_2026-05-22.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "props_edges_2026-05-22.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "props_recommendations_2026-05-22.csv").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "smart_sim_2026-05-22_BOS_NYK.json").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "smart_sim_2026-05-22_LAL_GSW.json").exists())
            self.assertTrue((artifact_root / "data" / "processed" / "props_recommendations_top_by_game_2026-05-22.json").exists())