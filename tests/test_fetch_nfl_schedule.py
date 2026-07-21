from __future__ import annotations

import unittest
from pathlib import Path

import scripts.fetch_nfl_schedule as fetch_schedule


class FilterSeasonGamesTests(unittest.TestCase):
    def test_filters_to_season_and_regular_season_only(self) -> None:
        all_games = [
            {"season": "2026", "game_type": "REG", "week": "1"},
            {"season": "2026", "game_type": "POST", "week": "19"},
            {"season": "2025", "game_type": "REG", "week": "1"},
        ]
        result = fetch_schedule.filter_season_games(all_games, 2026)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["week"], "1")

    def test_empty_input_returns_empty(self) -> None:
        self.assertEqual(fetch_schedule.filter_season_games([], 2026), [])


class SchedulePathTests(unittest.TestCase):
    def test_uses_provided_source_root(self) -> None:
        path = fetch_schedule.schedule_path(2026, source_root=Path("/tmp/nfl_source"))
        self.assertEqual(path, Path("/tmp/nfl_source/schedule_2026.csv"))


if __name__ == "__main__":
    unittest.main()
