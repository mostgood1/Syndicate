from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class NcaabRefreshRunnerTests(unittest.TestCase):
    def _load_module(self):
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "refresh_ncaab_odds_history.py"
        spec = importlib.util.spec_from_file_location("test_refresh_ncaab_odds_history", script_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_main_writes_source_compatible_odds_filename(self) -> None:
        module = self._load_module()

        class _FakeRow:
            def model_dump(self):
                return {"event_id": "evt-1", "market": "h2h", "book": "DraftKings"}

        class _FakeAdapter:
            def __init__(self, region: str = "us") -> None:
                self.region = region

            def iter_current_odds_expanded(self, *, markets: str, date_iso: str, bookmakers: str | None = None):
                return [_FakeRow()]

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_dir = Path(tmp_dir) / "odds_history"
            argv = [
                "refresh_ncaab_odds_history.py",
                "--date",
                "2026-05-22",
                "--source-root",
                tmp_dir,
                "--out-dir",
                str(out_dir),
            ]
            with patch.object(module, "_load_source_adapter", return_value=_FakeAdapter), patch("sys.argv", argv):
                rc = module.main()

            self.assertEqual(rc, 0)
            self.assertTrue((out_dir / "odds_2026-05-22.csv").exists())
            self.assertFalse((out_dir / "odds_history_2026-05-22.csv").exists())
