from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from syndicate.features.shared.week_calendar import shard_key_for_week
from syndicate.features.shared.week_calendar import week_for_date
from syndicate.features.shared.week_calendar import week_windows_for_sport


class WeekCalendarTests(unittest.TestCase):
    def _write_nfl_week(self, root: Path, *, season: int, week: int, game_dates: list[str]) -> None:
        path = root / f"upcoming_recs_{season}_wk{week}.csv"
        lines = ["type,confidence,ev_pct,odds,home_team,away_team,game_date,season,week"]
        for game_date in game_dates:
            lines.append(f"SPREAD,High,10.0,-110,Home,Away,{game_date},{season},{week}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_week_for_date_matches_correct_week(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write_nfl_week(root, season=2025, week=1, game_dates=["2025-09-07"])
            self._write_nfl_week(root, season=2025, week=2, game_dates=["2025-09-14"])

            self.assertEqual(week_for_date("nfl", date(2025, 9, 7), source_root=root), (2025, 1))
            self.assertEqual(week_for_date("nfl", date(2025, 9, 14), source_root=root), (2025, 2))

    def test_week_for_date_returns_none_outside_any_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write_nfl_week(root, season=2025, week=1, game_dates=["2025-09-07"])

            self.assertIsNone(week_for_date("nfl", date(2026, 1, 1), source_root=root))

    def test_week_for_date_tie_break_prefers_later_week_on_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            # Week 1 window: 2025-09-04 .. 2025-09-14 (+/-3 days around 09-07..09-11)
            self._write_nfl_week(root, season=2025, week=1, game_dates=["2025-09-07", "2025-09-11"])
            # Week 2 window: 2025-09-11 .. 2025-09-17 (+/-3 days around 09-14)
            self._write_nfl_week(root, season=2025, week=2, game_dates=["2025-09-14"])

            # 2025-09-12 falls inside both windows' overlap; later week wins.
            self.assertEqual(week_for_date("nfl", date(2025, 9, 12), source_root=root), (2025, 2))

    def test_week_windows_for_sport_unsupported_slug_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.assertEqual(week_windows_for_sport("mlb", source_root=Path(tmp_dir)), [])

    def test_shard_key_for_week_format(self) -> None:
        self.assertEqual(shard_key_for_week(2025, 1), "2025_wk1")
        self.assertEqual(shard_key_for_week(2025, 17), "2025_wk17")


if __name__ == "__main__":
    unittest.main()
