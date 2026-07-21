"""Regression coverage for the season-aware market-lines cache lookup added
to scripts/backfill_smartsim2_performance.py for the 2026 NCAAF bootstrap."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import scripts.backfill_smartsim2_performance as backfill


def _write_lines(path: Path, home_team: str, away_team: str, spread: float, total: float) -> None:
    payload = [
        {
            "homeTeam": home_team,
            "awayTeam": away_team,
            "lines": [{"spread": spread, "overUnder": total}],
        }
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")


class LoadMarketLinesSeasonAwareTests(unittest.TestCase):
    def test_prefers_season_specific_file_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lines_dir = Path(tmp)
            _write_lines(lines_dir / "cfbd_lines_2026_wk1.json", "TCU", "North Carolina", -6.5, 49.5)
            _write_lines(lines_dir / "cfbd_lines_wk1.json", "Other Home", "Other Away", -3.0, 55.0)
            index = backfill.load_market_lines(lines_dir, 1, season=2026)
            self.assertIn(("tcu", "north carolina"), index)
            self.assertNotIn(("other home", "other away"), index)

    def test_falls_back_to_legacy_filename_when_season_specific_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lines_dir = Path(tmp)
            _write_lines(lines_dir / "cfbd_lines_wk1.json", "Ohio State", "Texas", -7.0, 51.0)
            index = backfill.load_market_lines(lines_dir, 1, season=2026)
            self.assertIn(("ohio st", "texas"), index)

    def test_legacy_call_without_season_still_works(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lines_dir = Path(tmp)
            _write_lines(lines_dir / "cfbd_lines_wk1.json", "Ohio State", "Texas", -7.0, 51.0)
            index = backfill.load_market_lines(lines_dir, 1)
            self.assertIn(("ohio st", "texas"), index)

    def test_missing_file_returns_empty_dict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            index = backfill.load_market_lines(Path(tmp), 1, season=2026)
            self.assertEqual(index, {})


if __name__ == "__main__":
    unittest.main()
