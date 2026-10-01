from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from syndicate.features.shared import week_calendar
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


class WeekWindowCacheTests(unittest.TestCase):
    """2026-10-01: the NCAAF reader re-parsed ~300k schedule rows per call and
    score_candidate called it once per candidate -- 632s to score 273 NCAAF
    candidates. These assert the PARSE is skipped on a repeat call (the branch),
    and that any change to the source files still re-parses."""

    def setUp(self) -> None:
        week_calendar._window_cache.clear()
        self.addCleanup(week_calendar._window_cache.clear)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "source_artifacts").mkdir()

    def _write_ncaaf(self, name: str, rows: list[tuple[int, int, str]]) -> Path:
        path = self.root / "source_artifacts" / name
        lines = ["season,week,start_date,home_team,away_team"]
        lines += [f"{season},{week},{start},Home,Away" for season, week, start in rows]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def _counted(self):
        return patch.object(week_calendar, "_ncaaf_week_windows", wraps=week_calendar._ncaaf_week_windows)

    def test_repeat_call_does_not_reparse(self) -> None:
        self._write_ncaaf("college_football_schedule_2026_predicted_totals_enhanced.csv", [(2026, 5, "2026-10-03T19:00:00Z")])
        with self._counted() as parse:
            for _ in range(5):
                self.assertEqual(week_for_date("ncaaf", date(2026, 10, 3), source_root=self.root), (2026, 5))
        self.assertEqual(parse.call_count, 1)

    def test_a_rewritten_file_is_reparsed(self) -> None:
        path = self._write_ncaaf(
            "college_football_schedule_2026_predicted_totals_enhanced.csv", [(2026, 5, "2026-10-03T19:00:00Z")]
        )
        with self._counted() as parse:
            self.assertEqual(week_for_date("ncaaf", date(2026, 10, 3), source_root=self.root), (2026, 5))
            self._write_ncaaf(path.name, [(2026, 6, "2026-10-03T19:00:00Z"), (2026, 6, "2026-10-04T19:00:00Z")])
            self.assertEqual(week_for_date("ncaaf", date(2026, 10, 3), source_root=self.root), (2026, 6))
        self.assertEqual(parse.call_count, 2)

    def test_an_added_file_is_reparsed(self) -> None:
        self._write_ncaaf("college_football_schedule_2026_predicted_totals_enhanced.csv", [(2026, 5, "2026-10-03T19:00:00Z")])
        with self._counted() as parse:
            self.assertIsNone(week_for_date("ncaaf", date(2026, 11, 28), source_root=self.root))
            self._write_ncaaf(
                "college_football_schedule_2026_predicted_totals_enhanced_wk13.csv", [(2026, 13, "2026-11-28T19:00:00Z")]
            )
            self.assertEqual(week_for_date("ncaaf", date(2026, 11, 28), source_root=self.root), (2026, 13))
        self.assertEqual(parse.call_count, 2)

    def test_callers_get_copies_not_the_cached_windows(self) -> None:
        self._write_ncaaf("college_football_schedule_2026_predicted_totals_enhanced.csv", [(2026, 5, "2026-10-03T19:00:00Z")])
        first = week_windows_for_sport("ncaaf", source_root=self.root)
        first[0]["week"] = 99
        self.assertEqual(week_windows_for_sport("ncaaf", source_root=self.root)[0]["week"], 5)


if __name__ == "__main__":
    unittest.main()
