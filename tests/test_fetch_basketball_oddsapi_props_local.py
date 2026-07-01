from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from scripts.fetch_basketball_oddsapi_props_local import _latest_existing_snapshot_path


class FetchBasketballOddsapiPropsLocalTests(unittest.TestCase):
    def test_latest_existing_snapshot_path_prefers_latest_prior_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "odds_wnba_player_props_2026-06-27.csv").write_text("a\n1\n", encoding="utf-8")
            (root / "odds_wnba_player_props_2026-06-28.csv").write_text("a\n2\n", encoding="utf-8")
            (root / "odds_wnba_player_props_2026-06-30.csv").write_text("a\n3\n", encoding="utf-8")

            chosen = _latest_existing_snapshot_path(
                out_path=root / "odds_wnba_player_props_2026-06-30.csv",
                target_date="2026-06-30",
            )

            self.assertEqual(chosen, root / "odds_wnba_player_props_2026-06-30.csv")

    def test_latest_existing_snapshot_path_ignores_newer_files_for_prior_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "odds_wnba_player_props_2026-06-27.csv").write_text("a\n1\n", encoding="utf-8")
            (root / "odds_wnba_player_props_2026-06-28.csv").write_text("a\n2\n", encoding="utf-8")
            (root / "odds_wnba_player_props_2026-06-30.csv").write_text("a\n3\n", encoding="utf-8")

            chosen = _latest_existing_snapshot_path(
                out_path=root / "odds_wnba_player_props_2026-06-29.csv",
                target_date="2026-06-29",
            )

            self.assertEqual(chosen, root / "odds_wnba_player_props_2026-06-28.csv")


if __name__ == "__main__":
    unittest.main()
