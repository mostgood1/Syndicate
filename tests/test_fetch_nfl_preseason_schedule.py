from __future__ import annotations

import unittest
from pathlib import Path

import scripts.fetch_nfl_preseason_schedule as fetch_preseason


def _event(*, event_id: str, week: int, home_abbr: str, away_abbr: str, home_score: str = "", away_score: str = "",
           status: str = "Scheduled", season_type: int = 1, date: str = "2026-08-07T00:00Z", venue: str = "Tom Benson Hall of Fame Stadium"):
    return {
        "id": event_id,
        "date": date,
        "season": {"type": season_type, "year": 2026},
        "week": {"number": week},
        "competitions": [
            {
                "status": {"type": {"description": status}},
                "venue": {"fullName": venue},
                "competitors": [
                    {"homeAway": "home", "team": {"abbreviation": home_abbr}, "score": home_score},
                    {"homeAway": "away", "team": {"abbreviation": away_abbr}, "score": away_score},
                ],
            }
        ],
    }


class RowsFromEventsTests(unittest.TestCase):
    def test_real_shape_produces_one_row(self) -> None:
        events = [_event(event_id="401772936", week=1, home_abbr="ARI", away_abbr="CAR", status="Scheduled")]
        rows = fetch_preseason.rows_from_events(events, 2026)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["game_id"], "401772936")
        self.assertEqual(row["season"], "2026")
        self.assertEqual(row["game_type"], "PRE")
        self.assertEqual(row["week"], "1")
        self.assertEqual(row["home_team"], "ARI")
        self.assertEqual(row["away_team"], "CAR")
        self.assertEqual(row["status"], "Scheduled")
        self.assertEqual(row["venue"], "Tom Benson Hall of Fame Stadium")
        self.assertEqual(row["gameday"], "2026-08-07")

    def test_completed_game_carries_real_scores(self) -> None:
        events = [_event(event_id="401772940", week=2, home_abbr="DET", away_abbr="CIN", home_score="17", away_score="14", status="Final")]
        rows = fetch_preseason.rows_from_events(events, 2026)
        self.assertEqual(rows[0]["home_score"], "17")
        self.assertEqual(rows[0]["away_score"], "14")
        self.assertEqual(rows[0]["status"], "Final")

    def test_non_preseason_season_type_excluded(self) -> None:
        events = [_event(event_id="401772999", week=1, home_abbr="KC", away_abbr="BUF", season_type=2)]
        rows = fetch_preseason.rows_from_events(events, 2026)
        self.assertEqual(rows, [])

    def test_week_outside_1_to_4_excluded(self) -> None:
        events = [_event(event_id="401772999", week=5, home_abbr="KC", away_abbr="BUF")]
        rows = fetch_preseason.rows_from_events(events, 2026)
        self.assertEqual(rows, [])

    def test_missing_game_id_excluded(self) -> None:
        events = [_event(event_id="", week=1, home_abbr="KC", away_abbr="BUF")]
        rows = fetch_preseason.rows_from_events(events, 2026)
        self.assertEqual(rows, [])

    def test_empty_events_returns_empty(self) -> None:
        self.assertEqual(fetch_preseason.rows_from_events([], 2026), [])

    def test_non_dict_event_skipped(self) -> None:
        rows = fetch_preseason.rows_from_events([None, "not a dict"], 2026)  # type: ignore[list-item]
        self.assertEqual(rows, [])


class PreseasonSchedulePathTests(unittest.TestCase):
    def test_uses_provided_source_root(self) -> None:
        path = fetch_preseason.preseason_schedule_path(2026, source_root=Path("/tmp/nfl_source"))
        self.assertEqual(path, Path("/tmp/nfl_source/schedule_preseason_2026.csv"))


if __name__ == "__main__":
    unittest.main()
