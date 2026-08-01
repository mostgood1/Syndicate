from __future__ import annotations

import csv
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.features.football.ingestion import nflverse_ingestion as ing


class NewNflverseFetcherTests(unittest.TestCase):
    """Covers the roster/injuries/depth_chart fetchers added this session
    -- mirrors the existing _pbp_rows/_player_stats_rows pattern exactly,
    so these tests just confirm URL construction and cache-path shape
    without hitting the network (download_to_cache is mocked)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.nfl_root = os.path.join(self._tmp.name, "nfl_source")
        os.makedirs(self.nfl_root, exist_ok=True)
        self._root_patch = patch.object(ing, "nflverse_tracking_root", return_value=Path(self.nfl_root) / "tracking" / "nflverse")
        self._root_patch.start()
        self.addCleanup(self._root_patch.stop)

    def _write_csv(self, path: Path, rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = list(rows[0].keys()) if rows else ["a"]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    def test_roster_rows_requests_the_real_rosters_release_url(self) -> None:
        captured = {}

        def fake_download(url, target_path):
            captured["url"] = url
            captured["target_path"] = target_path
            self._write_csv(target_path, [{"team": "GB", "full_name": "Test Player", "position": "DL"}])
            return target_path

        with patch.object(ing, "download_to_cache", side_effect=fake_download):
            rows = ing.load_nflverse_roster(2026)

        self.assertEqual(captured["url"], f"{ing.NFLVERSE_BASE_URL}/rosters/roster_2026.csv")
        self.assertTrue(str(captured["target_path"]).endswith(os.path.join("roster", "roster_2026.csv")))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["full_name"], "Test Player")

    def test_injuries_rows_requests_the_real_injuries_release_url(self) -> None:
        captured = {}

        def fake_download(url, target_path):
            captured["url"] = url
            self._write_csv(target_path, [{"team": "ARI", "full_name": "Test Player", "report_status": "Questionable"}])
            return target_path

        with patch.object(ing, "download_to_cache", side_effect=fake_download):
            rows = ing.load_nflverse_injuries(2025)

        self.assertEqual(captured["url"], f"{ing.NFLVERSE_BASE_URL}/injuries/injuries_2025.csv")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["report_status"], "Questionable")

    def test_depth_chart_rows_requests_the_real_depth_charts_release_url(self) -> None:
        captured = {}

        def fake_download(url, target_path):
            captured["url"] = url
            self._write_csv(target_path, [{"team": "GB", "player_name": "Test Player", "pos_abb": "C", "pos_rank": "1"}])
            return target_path

        with patch.object(ing, "download_to_cache", side_effect=fake_download):
            rows = ing.load_nflverse_depth_chart(2026)

        self.assertEqual(captured["url"], f"{ing.NFLVERSE_BASE_URL}/depth_charts/depth_charts_2026.csv")
        self.assertEqual(len(rows), 1)

    def test_failed_download_returns_empty_not_fabricated(self) -> None:
        with patch.object(ing, "download_to_cache", return_value=None):
            self.assertEqual(ing.load_nflverse_roster(2099), ())
            self.assertEqual(ing.load_nflverse_injuries(2099), ())
            self.assertEqual(ing.load_nflverse_depth_chart(2099), ())


if __name__ == "__main__":
    unittest.main()
