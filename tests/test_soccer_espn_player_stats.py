from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.soccer.ingestion.espn_player_stats import aggregate_season_player_stats


def _event(event_id: str) -> dict:
    return {"event_id": event_id, "home_team": "Home FC", "away_team": "Away FC"}


def _rows_for_match(event_id: str, *, striker_shots: float, sub_shots: float) -> list[dict]:
    return [
        {
            "event_id": event_id,
            "team": "Home FC",
            "side": "home",
            "player_id": "p1",
            "player_name": "Home Striker",
            "position": "Forward",
            "starter": True,
            "subbed_in": False,
            "is_goalkeeper": False,
            "total_shots": striker_shots,
            "shots_on_target": striker_shots / 2,
            "total_goals": 1.0,
            "goal_assists": 0.0,
        },
        {
            "event_id": event_id,
            "team": "Home FC",
            "side": "home",
            "player_id": "p2",
            "player_name": "Home Sub",
            "position": "Midfielder",
            "starter": False,
            "subbed_in": True,
            "is_goalkeeper": False,
            "total_shots": sub_shots,
            "shots_on_target": 0.0,
            "total_goals": 0.0,
            "goal_assists": 0.0,
        },
        {
            "event_id": event_id,
            "team": "Home FC",
            "side": "home",
            "player_id": "p3",
            "player_name": "Home Keeper",
            "position": "Goalkeeper",
            "starter": True,
            "subbed_in": False,
            "is_goalkeeper": True,
            "total_shots": 0.0,
            "shots_on_target": 0.0,
            "total_goals": 0.0,
            "goal_assists": 0.0,
        },
        {
            "event_id": event_id,
            "team": "Home FC",
            "side": "home",
            "player_id": "p5",
            "player_name": "Home Unused Bench",
            "position": "Defender",
            "starter": False,
            "subbed_in": False,
            "is_goalkeeper": False,
            "total_shots": 0.0,
            "shots_on_target": 0.0,
            "total_goals": 0.0,
            "goal_assists": 0.0,
        },
        {
            "event_id": event_id,
            "team": "Away FC",
            "side": "away",
            "player_id": "p4",
            "player_name": "Away Winger",
            "position": "Forward",
            "starter": True,
            "subbed_in": False,
            "is_goalkeeper": False,
            "total_shots": 2.0,
            "shots_on_target": 1.0,
            "total_goals": 0.0,
            "goal_assists": 1.0,
        },
    ]


def _minutes_for_match() -> dict[str, float]:
    # p5 (unused bench) intentionally absent -- never entered the match.
    return {"p1": 90.0, "p2": 15.0, "p3": 90.0, "p4": 90.0}


class AggregateSeasonPlayerStatsTests(unittest.TestCase):
    def _run(self, rows_by_event: dict[str, list[dict]], *, min_appearances: int = 3) -> list[dict]:
        events = [_event(eid) for eid in rows_by_event]
        with patch(
            "syndicate.features.soccer.ingestion.espn_player_stats.fetch_completed_events", return_value=events
        ), patch(
            "syndicate.features.soccer.ingestion.espn_player_stats.fetch_match_summary",
            side_effect=lambda league, event_id: {"_rows": rows_by_event[event_id]},
        ), patch(
            "syndicate.features.soccer.ingestion.espn_player_stats.extract_match_player_rows",
            side_effect=lambda summary, event_id: summary["_rows"],
        ), patch(
            "syndicate.features.soccer.ingestion.espn_player_stats.extract_key_events", return_value=[]
        ), patch(
            "syndicate.features.soccer.ingestion.espn_player_stats.compute_minutes_played",
            return_value=_minutes_for_match(),
        ):
            return aggregate_season_player_stats("epl", date_windows=["20250101-20250107"], min_appearances=min_appearances)

    def test_true_per90_rate_accounts_for_partial_minutes(self) -> None:
        rows_by_event = {
            "e1": _rows_for_match("e1", striker_shots=4.0, sub_shots=1.0),
            "e2": _rows_for_match("e2", striker_shots=2.0, sub_shots=1.0),
            "e3": _rows_for_match("e3", striker_shots=3.0, sub_shots=1.0),
        }
        rows = self._run(rows_by_event)
        by_name = {row["player_name"]: row for row in rows}

        striker = by_name["Home Striker"]
        self.assertEqual(striker["appearances"], 3)
        self.assertEqual(striker["starts"], 3)
        self.assertAlmostEqual(striker["minutes_played"], 270.0)
        # Full-match starter: 9 total shots over 3 nineties -> exactly 3.0 per90.
        self.assertAlmostEqual(striker["shots_per90"], 3.0)
        self.assertEqual(striker["expected_minutes_share"], 1.0)

        sub = by_name["Home Sub"]
        self.assertEqual(sub["starts"], 0)
        self.assertAlmostEqual(sub["minutes_played"], 45.0)  # 15 min x 3 matches
        # 3 shots over 0.5 nineties -> 6.0 per90: the true-per-90 upgrade this
        # module exists for -- a per-appearance rate would have shown 1.0.
        self.assertAlmostEqual(sub["shots_per90"], 6.0)
        self.assertAlmostEqual(sub["expected_minutes_share"], 45.0 / 270.0, places=3)

    def test_unused_substitute_is_excluded_from_aggregation(self) -> None:
        rows_by_event = {
            "e1": _rows_for_match("e1", striker_shots=4.0, sub_shots=1.0),
            "e2": _rows_for_match("e2", striker_shots=2.0, sub_shots=1.0),
            "e3": _rows_for_match("e3", striker_shots=3.0, sub_shots=1.0),
        }
        rows = self._run(rows_by_event)
        names = {row["player_name"] for row in rows}
        self.assertNotIn("Home Unused Bench", names)

    def test_min_appearances_excludes_fringe_players(self) -> None:
        rows_by_event = {"e1": _rows_for_match("e1", striker_shots=4.0, sub_shots=1.0)}
        rows = self._run(rows_by_event, min_appearances=3)
        self.assertEqual(rows, [])

    def test_shot_on_target_rate_handles_zero_shots(self) -> None:
        rows_by_event = {
            "e1": _rows_for_match("e1", striker_shots=0.0, sub_shots=0.0),
            "e2": _rows_for_match("e2", striker_shots=0.0, sub_shots=0.0),
            "e3": _rows_for_match("e3", striker_shots=0.0, sub_shots=0.0),
        }
        rows = self._run(rows_by_event)
        keeper = next(row for row in rows if row["player_name"] == "Home Keeper")
        self.assertIsNone(keeper["shot_on_target_rate"])
        self.assertEqual(keeper["shots_per90"], 0.0)


if __name__ == "__main__":
    unittest.main()
