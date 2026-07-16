from __future__ import annotations

import unittest

from syndicate.features.football.sim_engine.smartsim2.historical_truth.historical_snapshot_builder import (
    build_historical_truth_snapshot,
)
from syndicate.features.football.sim_engine.smartsim2.historical_truth.ncaaf_historical_loader import (
    canonical_cfbd_drive_result,
    canonicalize_ncaaf_frame,
)


def _game(game_id: int, *, home: str, away: str, home_points: int, away_points: int, fbs_both: bool = True) -> dict:
    return {
        "id": game_id,
        "season": 2024,
        "week": 1,
        "seasonType": "regular",
        "homeTeam": home,
        "awayTeam": away,
        "homePoints": home_points,
        "awayPoints": away_points,
        "homeClassification": "fbs",
        "awayClassification": "fbs" if fbs_both else "fcs",
    }


def _drive(game_id: int, drive_number: int, *, result: str, plays: int, minutes: int, seconds: int, end_offense_score: int) -> dict:
    return {
        "gameId": game_id,
        "driveNumber": drive_number,
        "driveResult": result,
        "plays": plays,
        "elapsed": {"minutes": minutes, "seconds": seconds},
        "endOffenseScore": end_offense_score,
    }


def _play(
    game_id: int,
    drive_number: int,
    play_number: int,
    *,
    offense: str,
    defense: str,
    home: str,
    away: str,
    period: int = 1,
    yards_to_goal: int = 75,
    yards_gained: int = 5,
    offense_score: int = 0,
    defense_score: int = 0,
) -> dict:
    return {
        "gameId": game_id,
        "driveNumber": drive_number,
        "playNumber": play_number,
        "offense": offense,
        "defense": defense,
        "home": home,
        "away": away,
        "period": period,
        "down": 1,
        "distance": 10,
        "yardsToGoal": yards_to_goal,
        "yardsGained": yards_gained,
        "offenseScore": offense_score,
        "defenseScore": defense_score,
        "season": 2024,
        "week": 1,
    }


class CanonicalCfbdDriveResultTests(unittest.TestCase):
    def test_maps_recognized_variants_into_shared_vocabulary(self) -> None:
        self.assertEqual(canonical_cfbd_drive_result("TD"), "touchdown")
        self.assertEqual(canonical_cfbd_drive_result("FG"), "field goal")
        self.assertEqual(canonical_cfbd_drive_result("MISSED FG"), "missed field goal")
        self.assertEqual(canonical_cfbd_drive_result("PUNT"), "punt")
        self.assertEqual(canonical_cfbd_drive_result("DOWNS"), "turnover on downs")
        self.assertEqual(canonical_cfbd_drive_result("INT"), "turnover")
        self.assertEqual(canonical_cfbd_drive_result("FUMBLE"), "turnover")
        self.assertEqual(canonical_cfbd_drive_result("INT TD"), "opp touchdown")
        self.assertEqual(canonical_cfbd_drive_result("FUMBLE RETURN TD"), "opp touchdown")
        self.assertEqual(canonical_cfbd_drive_result("END OF HALF"), "end of half")
        self.assertEqual(canonical_cfbd_drive_result("END OF 4TH QUARTER"), "end of half")
        self.assertEqual(canonical_cfbd_drive_result("SF"), "safety")

    def test_unrecognized_text_passes_through_to_shared_other_bucket(self) -> None:
        # canonical_drive_result() in the shared builder defaults anything it
        # doesn't recognize to RESULT_OTHER; this loader must not invent a
        # mapping for CFBD's own "Uncategorized" tag.
        self.assertEqual(canonical_cfbd_drive_result("Uncategorized"), "uncategorized")


class CanonicalizeNcaafFrameTests(unittest.TestCase):
    def test_builds_frame_consumable_by_shared_builder(self) -> None:
        games = [_game(1, home="Ohio State", away="Michigan", home_points=10, away_points=7)]
        drives = [
            _drive(1, 1, result="TD", plays=8, minutes=4, seconds=10, end_offense_score=7),
            _drive(1, 2, result="PUNT", plays=5, minutes=2, seconds=30, end_offense_score=0),
            _drive(1, 3, result="FG", plays=6, minutes=3, seconds=0, end_offense_score=3),
        ]
        plays = [
            _play(1, 1, 1, offense="Ohio State", defense="Michigan", home="Ohio State", away="Michigan", period=1, yards_to_goal=75, offense_score=0, defense_score=0),
            _play(1, 1, 2, offense="Ohio State", defense="Michigan", home="Ohio State", away="Michigan", period=1, yards_to_goal=15, offense_score=0, defense_score=0),
            _play(1, 2, 1, offense="Michigan", defense="Ohio State", home="Ohio State", away="Michigan", period=2, yards_to_goal=80, offense_score=0, defense_score=7),
            _play(1, 3, 1, offense="Ohio State", defense="Michigan", home="Ohio State", away="Michigan", period=3, yards_to_goal=18, offense_score=7, defense_score=0),
        ]

        frame, metadata = canonicalize_ncaaf_frame(games=games, drives=drives, plays=plays)

        self.assertEqual(metadata["excluded_non_fbs_games"], 0)
        self.assertEqual(len(frame), 4)
        self.assertEqual(set(frame["fixed_drive_result"].unique()), {"touchdown", "punt", "field goal"})

        snapshot = build_historical_truth_snapshot(frame, seasons=[2024], league="ncaaf")
        self.assertEqual(snapshot.league, "ncaaf")
        self.assertEqual(len(snapshot.drive_records), 3)
        self.assertEqual(len(snapshot.game_records), 1)

        td_drive = next(record for record in snapshot.drive_records if record.result == "touchdown")
        self.assertEqual(td_drive.points, 7)
        self.assertTrue(td_drive.red_zone_entry)
        self.assertEqual(td_drive.plays, 8)
        self.assertEqual(td_drive.seconds, 250)

        game = snapshot.game_records[0]
        self.assertEqual(game.drives, 3)
        self.assertEqual(game.home_points, 10)
        self.assertEqual(game.away_points, 7)

    def test_excludes_fbs_vs_fcs_games_by_default(self) -> None:
        games = [
            _game(1, home="Ohio State", away="Michigan", home_points=10, away_points=7, fbs_both=True),
            _game(2, home="Alabama", away="Chattanooga", home_points=40, away_points=3, fbs_both=False),
        ]
        drives = [
            _drive(1, 1, result="TD", plays=8, minutes=4, seconds=10, end_offense_score=7),
            _drive(2, 1, result="TD", plays=8, minutes=4, seconds=10, end_offense_score=7),
        ]
        plays = [
            _play(1, 1, 1, offense="Ohio State", defense="Michigan", home="Ohio State", away="Michigan"),
            _play(2, 1, 1, offense="Alabama", defense="Chattanooga", home="Alabama", away="Chattanooga"),
        ]

        frame, metadata = canonicalize_ncaaf_frame(games=games, drives=drives, plays=plays, fbs_only=True)

        self.assertEqual(metadata["excluded_non_fbs_games"], 1)
        self.assertEqual(set(frame["game_id"].unique()), {"1"})

    def test_fbs_only_false_keeps_all_games(self) -> None:
        games = [
            _game(1, home="Ohio State", away="Michigan", home_points=10, away_points=7, fbs_both=True),
            _game(2, home="Alabama", away="Chattanooga", home_points=40, away_points=3, fbs_both=False),
        ]
        drives = [
            _drive(1, 1, result="TD", plays=8, minutes=4, seconds=10, end_offense_score=7),
            _drive(2, 1, result="TD", plays=8, minutes=4, seconds=10, end_offense_score=7),
        ]
        plays = [
            _play(1, 1, 1, offense="Ohio State", defense="Michigan", home="Ohio State", away="Michigan"),
            _play(2, 1, 1, offense="Alabama", defense="Chattanooga", home="Alabama", away="Chattanooga"),
        ]

        frame, metadata = canonicalize_ncaaf_frame(games=games, drives=drives, plays=plays, fbs_only=False)

        self.assertEqual(metadata["excluded_non_fbs_games"], 0)
        self.assertEqual(set(frame["game_id"].unique()), {"1", "2"})

    def test_quarter_scoring_uses_post_play_cumulative_score(self) -> None:
        games = [_game(1, home="Ohio State", away="Michigan", home_points=7, away_points=3)]
        drives = [
            _drive(1, 1, result="TD", plays=2, minutes=1, seconds=0, end_offense_score=7),
            _drive(1, 2, result="FG", plays=1, minutes=1, seconds=0, end_offense_score=3),
        ]
        plays = [
            _play(1, 1, 1, offense="Ohio State", defense="Michigan", home="Ohio State", away="Michigan", period=1, offense_score=0, defense_score=0),
            _play(1, 1, 2, offense="Ohio State", defense="Michigan", home="Ohio State", away="Michigan", period=1, offense_score=0, defense_score=0),
            _play(1, 2, 1, offense="Michigan", defense="Ohio State", home="Ohio State", away="Michigan", period=2, offense_score=0, defense_score=7),
        ]

        frame, _ = canonicalize_ncaaf_frame(games=games, drives=drives, plays=plays)
        snapshot = build_historical_truth_snapshot(frame, seasons=[2024], league="ncaaf")
        game = snapshot.game_records[0]

        self.assertEqual(game.quarter_home_points, (7, 0, 0, 0))
        self.assertEqual(game.quarter_away_points, (0, 3, 0, 0))


if __name__ == "__main__":
    unittest.main()
