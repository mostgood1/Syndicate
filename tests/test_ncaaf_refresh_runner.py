from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class NcaafRefreshRunnerTests(unittest.TestCase):
    def _load_module(self):
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "refresh_ncaaf_oddsapi.py"
        spec = importlib.util.spec_from_file_location("test_refresh_ncaaf_oddsapi", script_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_main_calls_source_fetcher_directly(self) -> None:
        module = self._load_module()

        class _FakeSourceModule:
            def __init__(self) -> None:
                self.calls = 0
                self.argv: list[str] = []

            def main(self) -> int:
                self.calls += 1
                self.argv = list(__import__("sys").argv)
                return 0

        source_module = _FakeSourceModule()

        with tempfile.TemporaryDirectory() as tmp_dir:
            source_root = Path(tmp_dir) / "source"
            (source_root / "data").mkdir(parents=True)
            argv = [
                "refresh_ncaaf_oddsapi.py",
                "--source-root",
                str(source_root),
                "--artifact-root",
                str(Path(tmp_dir) / "bundle"),
                "--week",
                "7",
            ]
            refresh_result = {
                "status": "ok",
                "week": 7,
                "written_rows": 1,
                "preserved_rows": 0,
                "total_rows": 1,
                "path": str(source_root / "data" / "college_football_betting_lines_2025.csv"),
                "matched_games": 1,
                "pred_games_in_week": 1,
            }
            with patch.object(module, "_run_refresh", return_value=refresh_result) as run_refresh, patch.object(module, "_materialize_artifact_bundle", return_value=[]), patch.dict("os.environ", {"ODDS_API_KEY": "test-key"}, clear=False), patch("sys.argv", argv):
                rc = module.main()

        self.assertEqual(rc, 0)
        run_refresh.assert_called_once()
        _, kwargs = run_refresh.call_args
        self.assertEqual(kwargs["source_root"], source_root.resolve())
        self.assertEqual(kwargs["week"], 7)
        self.assertEqual(kwargs["api_key"], "test-key")

    def test_main_materializes_ncaaf_artifacts_into_bundle_root(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            source_data_root = source_root / "data"
            artifact_root = tmp_root / "bundle"
            summary_root = source_data_root / "recommendations_summary"
            summary_root.mkdir(parents=True)

            (source_data_root / "recommendations_latest.json").write_text("{}\n", encoding="utf-8")
            (source_data_root / "recommendations_2025.csv").write_text("week\n7\n", encoding="utf-8")
            (source_data_root / "college_football_betting_lines_2025.csv").write_text("week,homeTeam\n7,Texas\n", encoding="utf-8")
            (source_data_root / "college_football_schedule_2025_predicted_totals_enhanced.csv").write_text("season,week,home_team,away_team,start_date\n2025,7,Texas,Oklahoma,2025-10-11T19:00:00Z\n", encoding="utf-8")
            (summary_root / "reconciliation.csv").write_text("week,count\n7,3\n", encoding="utf-8")


            argv = [
                "refresh_ncaaf_oddsapi.py",
                "--source-root",
                str(source_root),
                "--artifact-root",
                str(artifact_root),
                "--week",
                "7",
            ]
            with patch.object(module, "_run_refresh", return_value={"status": "ok", "week": 7}), patch.dict("os.environ", {"ODDS_API_KEY": "test-key"}, clear=False), patch("sys.argv", argv):
                rc = module.main()

            self.assertEqual(rc, 0)
            self.assertTrue((artifact_root / "recommendations_latest.json").exists())
            self.assertTrue((artifact_root / "recommendations_2025.csv").exists())
            self.assertTrue((artifact_root / "college_football_betting_lines_2025.csv").exists())
            self.assertTrue((artifact_root / "college_football_schedule_2025_predicted_totals_enhanced.csv").exists())
            self.assertTrue((artifact_root / "recommendations_summary" / "reconciliation.csv").exists())