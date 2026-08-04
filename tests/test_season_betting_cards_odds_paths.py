"""Odds-path resolution in the season betting-card manifest builder.

This is the fix for MLB grading producing zero rows for 16+ consecutive
days. `_odds_paths` resolved the odds tree against `_ROOT` -- the vendored
package root, i.e. the CODE CHECKOUT -- which carries only whatever is
committed (as of 2026-08-04: four files, all for 2026_07_10). On a hosted
deploy the real odds live on the mounted data disk, so for every other date
`game_lines_path.exists()` was False and
`_collect_report_game_recommendations` returned empty immediately.

That early return is why input size never mattered: 2026-08-02's batch
report had 15 reconciled games and 2026-08-03's had 2, and BOTH produced a
day artifact with zero selections. No graded rows -> nothing for settlement
to match -> the evaluation ledger stayed fully pending, which gates
reliability multipliers, dynamic thresholds, policy promotion, CLV and
stake credibility.
"""

from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MODULE_PATH = _REPO_ROOT / "vendor" / "mlb_bettingv2" / "tools" / "eval" / "build_season_betting_cards_manifest.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("_bscm_under_test", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        # The vendored module pulls in heavy sim-engine imports that are not
        # needed for path resolution; a partially-initialised module still
        # exposes the functions under test.
        pass
    return module


class OddsPathResolutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_module()
        if not hasattr(cls.module, "_odds_paths"):
            raise unittest.SkipTest("vendored module did not expose _odds_paths")

    def _make_odds_tree(self, root: Path, token: str) -> Path:
        odds_dir = root / "market" / "oddsapi"
        odds_dir.mkdir(parents=True, exist_ok=True)
        path = odds_dir / f"oddsapi_game_lines_{token}.json"
        path.write_text("{}", encoding="utf-8")
        return path

    def test_env_data_root_is_used_when_checkout_lacks_the_date(self) -> None:
        """The exact production failure: the date exists on the mounted data
        root but not in the checkout."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "mounted" / "data"
            expected = self._make_odds_tree(data_root, "2026_08_03")
            with patch.dict(os.environ, {"MLB_BETTING_DATA_ROOT": str(data_root)}, clear=False):
                paths = self.module._odds_paths("2026-08-03")
            self.assertTrue(paths["game_lines"].exists(), "must find odds on the mounted data root")
            self.assertEqual(paths["game_lines"].resolve(), expected.resolve())

    def test_source_artifacts_nesting_is_accepted(self) -> None:
        """The mounted bundle nests the same tree under source_artifacts."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "mlb_source"
            expected = self._make_odds_tree(base / "source_artifacts" / "data", "2026_08_02")
            with patch.dict(os.environ, {"MLB_BETTING_DATA_ROOT": str(base)}, clear=False):
                paths = self.module._odds_paths("2026-08-02")
            self.assertTrue(paths["game_lines"].exists())
            self.assertEqual(paths["game_lines"].resolve(), expected.resolve())

    def test_all_three_odds_families_resolve_together(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "data"
            odds_dir = data_root / "market" / "oddsapi"
            odds_dir.mkdir(parents=True)
            for name in ("oddsapi_game_lines", "oddsapi_hitter_props", "oddsapi_pitcher_props"):
                (odds_dir / f"{name}_2026_08_03.json").write_text("{}", encoding="utf-8")
            with patch.dict(os.environ, {"MLB_BETTING_DATA_ROOT": str(data_root)}, clear=False):
                paths = self.module._odds_paths("2026-08-03")
            for key in ("game_lines", "hitter_lines", "pitcher_lines"):
                self.assertTrue(paths[key].exists(), f"{key} must resolve")

    def test_missing_date_returns_a_named_path_rather_than_raising(self) -> None:
        """The caller warns using this path, so it must stay meaningful even
        when nothing exists -- an empty/None path would make the warning
        useless."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"MLB_BETTING_DATA_ROOT": str(Path(tmp) / "data")}, clear=False):
                paths = self.module._odds_paths("2030-01-01")
            self.assertFalse(paths["game_lines"].exists())
            self.assertIn("oddsapi_game_lines_2030_01_01.json", str(paths["game_lines"]))

    def test_checkout_still_works_when_no_env_root_is_set(self) -> None:
        """Local/dev use with no env var must keep resolving against the
        checkout exactly as before."""
        env = {k: v for k, v in os.environ.items() if k not in {"MLB_BETTING_DATA_ROOT", "MLB_BETTING_DATA_ROOT_DIR"}}
        with patch.dict(os.environ, env, clear=True):
            paths = self.module._odds_paths("2026-07-10")
        self.assertIn("oddsapi_game_lines_2026_07_10.json", str(paths["game_lines"]))


if __name__ == "__main__":
    unittest.main()
