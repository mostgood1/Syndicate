from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class NflRefreshRunnerTests(unittest.TestCase):
    def _load_module(self):
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "refresh_nfl_oddsapi.py"
        spec = importlib.util.spec_from_file_location("test_refresh_nfl_oddsapi", script_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_main_calls_source_modules_directly(self) -> None:
        module = self._load_module()

        class _FakeOddsModule:
            def __init__(self) -> None:
                self.calls = 0

            def main(self) -> None:
                self.calls += 1

        class _FakePropsModule:
            def __init__(self) -> None:
                self.calls = 0

            def main(self) -> int:
                self.calls += 1
                return 0

        odds_module = _FakeOddsModule()
        props_module = _FakePropsModule()

        with tempfile.TemporaryDirectory() as tmp_dir:
            source_root = Path(tmp_dir) / "source"
            (source_root / "nfl_compare" / "data").mkdir(parents=True)
            argv = [
                "refresh_nfl_oddsapi.py",
                "--source-root",
                str(source_root),
                "--artifact-root",
                str(Path(tmp_dir) / "bundle"),
                "--season",
                "2026",
                "--week",
                "4",
            ]
            with patch.object(module, "_load_source_modules", return_value=(odds_module, props_module)), patch("sys.argv", argv):
                rc = module.main()

        self.assertEqual(rc, 0)
        self.assertEqual(odds_module.calls, 1)
        self.assertEqual(props_module.calls, 1)

    def test_main_materializes_nfl_artifacts_into_bundle_root(self) -> None:
        module = self._load_module()

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            source_root = tmp_root / "source"
            source_data_root = source_root / "nfl_compare" / "data"
            artifact_root = tmp_root / "bundle"
            (source_data_root / "manifests").mkdir(parents=True)

            for name in (
                "current_week.json",
                "calibration_active.json",
                "prob_calibration.json",
                "sigma_calibration.json",
                "totals_calibration.json",
            ):
                (source_data_root / name).write_text("{}\n", encoding="utf-8")
            (source_data_root / "upcoming_recs_2026_wk4.csv").write_text("team\nKC\n", encoding="utf-8")
            (source_data_root / "manifests" / "2026_wk4.json").write_text("{}\n", encoding="utf-8")

            class _FakeOddsModule:
                def main(self) -> None:
                    (source_data_root / "real_betting_lines_2026_10_01.json").write_text("{}\n", encoding="utf-8")

            class _FakePropsModule:
                def main(self) -> int:
                    (source_data_root / "oddsapi_player_props_2026_wk4.csv").write_text("player\nMahomes\n", encoding="utf-8")
                    return 0

            argv = [
                "refresh_nfl_oddsapi.py",
                "--source-root",
                str(source_root),
                "--artifact-root",
                str(artifact_root),
                "--season",
                "2026",
                "--week",
                "4",
            ]
            with patch.object(module, "_load_source_modules", return_value=(_FakeOddsModule(), _FakePropsModule())), patch("sys.argv", argv):
                rc = module.main()

            self.assertEqual(rc, 0)
            self.assertTrue((artifact_root / "current_week.json").exists())
            self.assertTrue((artifact_root / "calibration_active.json").exists())
            self.assertTrue((artifact_root / "prob_calibration.json").exists())
            self.assertTrue((artifact_root / "sigma_calibration.json").exists())
            self.assertTrue((artifact_root / "totals_calibration.json").exists())
            self.assertTrue((artifact_root / "upcoming_recs_2026_wk4.csv").exists())
            self.assertTrue((artifact_root / "real_betting_lines_2026_10_01.json").exists())
            self.assertTrue((artifact_root / "oddsapi_player_props_2026_wk4.csv").exists())
            self.assertTrue((artifact_root / "manifests" / "2026_wk4.json").exists())