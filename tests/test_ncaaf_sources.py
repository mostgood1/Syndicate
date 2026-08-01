from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.ncaaf import sources


class NcaafTargetWeekTests(unittest.TestCase):
    def test_missing_season_returns_none(self) -> None:
        with patch(
            "syndicate.features.football.sim_engine.smartsim2.historical_truth.ncaaf_historical_loader.load_games_season",
            side_effect=Exception("no cache"),
        ):
            self.assertIsNone(sources.ncaaf_target_week(2099))

    def test_all_games_unplayed_returns_lowest_week(self) -> None:
        games = [
            {"week": 1, "completed": False},
            {"week": 2, "completed": False},
        ]
        with patch(
            "syndicate.features.football.sim_engine.smartsim2.historical_truth.ncaaf_historical_loader.load_games_season",
            return_value=games,
        ):
            self.assertEqual(sources.ncaaf_target_week(2026), 1)

    def test_completed_weeks_are_skipped(self) -> None:
        games = [
            {"week": 1, "completed": True},
            {"week": 2, "completed": False},
        ]
        with patch(
            "syndicate.features.football.sim_engine.smartsim2.historical_truth.ncaaf_historical_loader.load_games_season",
            return_value=games,
        ):
            self.assertEqual(sources.ncaaf_target_week(2026), 2)

    def test_all_games_played_returns_none(self) -> None:
        games = [{"week": 1, "completed": True}]
        with patch(
            "syndicate.features.football.sim_engine.smartsim2.historical_truth.ncaaf_historical_loader.load_games_season",
            return_value=games,
        ):
            self.assertIsNone(sources.ncaaf_target_week(2026))


if __name__ == "__main__":
    unittest.main()
