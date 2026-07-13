from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from syndicate.features.shared.basketball_props_smart_sim import _load_team_advanced_stats_asof_local


class LoadTeamAdvancedStatsAsofLocalTests(unittest.TestCase):
    def _write_asof_csv(self, processed_root: Path, *, season: int, compact_date: str) -> None:
        path = processed_root / f"team_advanced_stats_{season}_asof_{compact_date}.csv"
        path.write_text(
            "team,pace,off_rtg,def_rtg\n"
            "ATL,82.83,99.9,95.5\n"
            "LAS,84.04,101.2,98.3\n"
            "LVA,87.09,103.5,96.1\n",
            encoding="utf-8",
        )

    def test_finds_asof_file_with_compact_yyyymmdd_date(self) -> None:
        # The as-of file is written with a compact YYYYMMDD suffix
        # (team_advanced_stats_2026_asof_20260713.csv), not the ISO
        # YYYY-MM-DD date_str used elsewhere in the pipeline. Callers must
        # convert before calling this loader.
        with TemporaryDirectory() as tmp_dir:
            processed_root = Path(tmp_dir)
            self._write_asof_csv(processed_root, season=2026, compact_date="20260713")

            df = _load_team_advanced_stats_asof_local(
                processed_root=processed_root, season=2026, as_of_date_str="20260713"
            )

        self.assertEqual(len(df), 3)
        row = df[df["team"] == "LAS"]
        self.assertEqual(float(row["pace"].iloc[0]), 84.04)
        row = df[df["team"] == "LVA"]
        self.assertEqual(float(row["pace"].iloc[0]), 87.09)

    def test_does_not_find_asof_file_with_iso_dashed_date(self) -> None:
        # Regression guard: passing the ISO-dashed date string (the bug this
        # fix corrects) must not silently match the compact-named file.
        with TemporaryDirectory() as tmp_dir:
            processed_root = Path(tmp_dir)
            self._write_asof_csv(processed_root, season=2026, compact_date="20260713")

            df = _load_team_advanced_stats_asof_local(
                processed_root=processed_root, season=2026, as_of_date_str="2026-07-13"
            )

        self.assertTrue(df.empty)

    def test_date_compaction_matches_expected_filename(self) -> None:
        compact = "2026-07-13".strip().replace("-", "")
        self.assertEqual(compact, "20260713")


if __name__ == "__main__":
    unittest.main()
