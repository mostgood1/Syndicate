from __future__ import annotations

import unittest

import pandas as pd

from syndicate.features.football.sim_engine.smartsim2.calibration.benchmark_contracts import CalibrationBenchmarkSnapshot
from syndicate.features.football.sim_engine.smartsim2.contracts import PossessionOutcome
from syndicate.features.football.sim_engine.smartsim2.historical_truth.historical_snapshot_builder import (
    build_historical_truth_snapshot,
    canonical_drive_result,
)


def _play(
    play_id: int,
    game_id: str,
    drive: int,
    posteam: str,
    defteam: str,
    *,
    qtr: int = 1,
    yardline_100: float = 75.0,
    yards_gained: float = 5.0,
    result: str = "Punt",
    drive_play_count: int = 6,
    top: str = "2:45",
    posteam_score: int = 0,
    posteam_score_post: int = 0,
    home_score: int = 0,
    away_score: int = 0,
) -> dict:
    return {
        "play_id": play_id,
        "game_id": game_id,
        "season": 2024,
        "week": 1,
        "season_type": "REG",
        "home_team": "PHI",
        "away_team": "DAL",
        "posteam": posteam,
        "defteam": defteam,
        "qtr": qtr,
        "down": 1,
        "ydstogo": 10,
        "yardline_100": yardline_100,
        "yards_gained": yards_gained,
        "play": 1,
        "fixed_drive": drive,
        "fixed_drive_result": result,
        "drive_play_count": drive_play_count,
        "drive_time_of_possession": top,
        "posteam_score": posteam_score,
        "posteam_score_post": posteam_score_post,
        "total_home_score": home_score,
        "total_away_score": away_score,
    }


class SmartSim2HistoricalTruthTests(unittest.TestCase):
    def _frame(self) -> pd.DataFrame:
        rows = [
            # Drive 1: PHI touchdown drive entering the red zone in Q1.
            _play(1, "g1", 1, "PHI", "DAL", yardline_100=75, result="Touchdown", drive_play_count=8, top="4:10"),
            _play(2, "g1", 1, "PHI", "DAL", yardline_100=15, result="Touchdown", drive_play_count=8, top="4:10", posteam_score=0, posteam_score_post=7, home_score=7),
            # Drive 2: DAL punt drive in Q2.
            _play(3, "g1", 2, "DAL", "PHI", qtr=2, yardline_100=80, result="Punt", drive_play_count=5, top="2:30", home_score=7),
            # Drive 3: PHI missed field goal in Q3.
            _play(4, "g1", 3, "PHI", "DAL", qtr=3, yardline_100=45, result="Missed field goal", drive_play_count=7, top="3:05", home_score=7),
            # Drive 4: DAL turnover in Q4.
            _play(5, "g1", 4, "DAL", "PHI", qtr=4, yardline_100=70, result="Turnover", drive_play_count=4, top="1:40", home_score=7, away_score=3),
        ]
        return pd.DataFrame(rows)

    def test_canonical_result_mapping(self) -> None:
        self.assertEqual(canonical_drive_result("Touchdown"), "touchdown")
        self.assertEqual(canonical_drive_result("Opp touchdown"), "turnover")
        self.assertEqual(canonical_drive_result("Missed field goal"), "missed_field_goal")
        self.assertEqual(canonical_drive_result("Turnover on downs"), "turnover_on_downs")
        self.assertEqual(canonical_drive_result("End of half"), "end_of_half")
        self.assertEqual(canonical_drive_result("Something new"), "other")

    def test_snapshot_builds_drive_and_game_records(self) -> None:
        snapshot = build_historical_truth_snapshot(self._frame(), seasons=[2024])

        self.assertEqual(snapshot.league, "nfl")
        self.assertEqual(snapshot.seasons, (2024,))
        self.assertEqual(len(snapshot.drive_records), 4)
        self.assertEqual(len(snapshot.game_records), 1)

        td_drive = snapshot.drive_records[0]
        self.assertEqual(td_drive.result, "touchdown")
        self.assertEqual(td_drive.points, 7)
        self.assertTrue(td_drive.red_zone_entry)
        self.assertEqual(td_drive.plays, 8)
        self.assertEqual(td_drive.seconds, 250)
        self.assertEqual(td_drive.field_position_start, 25)

        game = snapshot.game_records[0]
        self.assertEqual(game.drives, 4)
        self.assertEqual(game.home_points, 7)
        self.assertEqual(game.away_points, 3)
        self.assertEqual(game.quarter_home_points, (7, 0, 0, 0))
        self.assertEqual(game.quarter_away_points, (0, 0, 0, 3))

        metrics = snapshot.metrics
        self.assertAlmostEqual(metrics.touchdown_rate, 0.25)
        self.assertAlmostEqual(metrics.punt_rate, 0.25)
        self.assertAlmostEqual(metrics.missed_field_goal_rate, 0.25)
        self.assertAlmostEqual(metrics.turnover_rate, 0.25)
        self.assertAlmostEqual(metrics.possessions_per_game, 4.0)
        self.assertAlmostEqual(metrics.game_totals, 10.0)

    def test_adapts_to_calibration_snapshot_contract(self) -> None:
        snapshot = build_historical_truth_snapshot(self._frame(), seasons=[2024])
        calibration = snapshot.to_calibration_snapshot()

        self.assertIsInstance(calibration, CalibrationBenchmarkSnapshot)
        self.assertEqual(len(calibration.drive_records), 4)
        self.assertEqual(len(calibration.game_records), 1)
        outcomes = {record.outcome for record in calibration.drive_records}
        self.assertIn(PossessionOutcome.TOUCHDOWN, outcomes)
        self.assertIn(PossessionOutcome.MISSED_FIELD_GOAL, outcomes)
        self.assertEqual(calibration.game_records[0].possessions, 4)


if __name__ == "__main__":
    unittest.main()
