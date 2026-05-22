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