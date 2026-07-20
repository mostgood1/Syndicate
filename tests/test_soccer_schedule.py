from __future__ import annotations

import unittest
from datetime import date

from syndicate.features.soccer.features.schedule import compute_matchweeks
from syndicate.features.soccer.features.schedule import default_season
from syndicate.features.soccer.features.schedule import season_date_range


class SeasonDateRangeTests(unittest.TestCase):
    def test_european_calendar_league_spans_aug_to_may(self) -> None:
        start, end = season_date_range("epl", 2025)
        self.assertEqual(start, date(2025, 8, 1))
        self.assertEqual(end, date(2026, 5, 31))

    def test_mls_is_a_single_calendar_year_season(self) -> None:
        start, end = season_date_range("mls", 2026)
        self.assertEqual(start.year, 2026)
        self.assertEqual(end.year, 2026)


class DefaultSeasonTests(unittest.TestCase):
    def test_european_league_before_july_belongs_to_prior_season(self) -> None:
        self.assertEqual(default_season("epl", today=date(2026, 3, 15)), 2025)

    def test_european_league_from_july_belongs_to_new_season(self) -> None:
        self.assertEqual(default_season("epl", today=date(2026, 7, 20)), 2026)

    def test_mls_season_is_the_calendar_year(self) -> None:
        self.assertEqual(default_season("mls", today=date(2026, 3, 15)), 2026)


class ComputeMatchweeksTests(unittest.TestCase):
    def test_buckets_fixtures_into_sequential_weeks_from_season_start(self) -> None:
        matches = [
            {"date": "2026-08-08T15:00Z", "home_team": "A", "away_team": "B"},
            {"date": "2026-08-09T15:00Z", "home_team": "C", "away_team": "D"},
            {"date": "2026-08-15T15:00Z", "home_team": "A", "away_team": "C"},
            {"date": "2026-08-22T15:00Z", "home_team": "B", "away_team": "D"},
        ]
        annotated, week_index = compute_matchweeks(matches, league="epl", season=2026)
        weeks = [row["week"] for row in annotated]
        self.assertEqual(weeks, [1, 1, 2, 3])
        self.assertEqual([entry["week"] for entry in week_index], [1, 2, 3])
        self.assertEqual(week_index[0]["match_count"], 2)

    def test_weeks_are_numbered_sequentially_even_with_a_gap(self) -> None:
        # No fixtures at all in the 3rd bucket -- week numbers must still be
        # dense (1, 2, 3), not (1, 2, 4), since the UI's prev/next nav
        # assumes contiguous integers.
        matches = [
            {"date": "2026-08-08T15:00Z", "home_team": "A", "away_team": "B"},
            {"date": "2026-09-05T15:00Z", "home_team": "A", "away_team": "B"},
        ]
        _annotated, week_index = compute_matchweeks(matches, league="epl", season=2026)
        self.assertEqual([entry["week"] for entry in week_index], [1, 2])

    def test_matches_with_unparseable_dates_get_no_week(self) -> None:
        matches = [{"date": "not-a-date", "home_team": "A", "away_team": "B"}]
        annotated, week_index = compute_matchweeks(matches, league="epl", season=2026)
        self.assertIsNone(annotated[0]["week"])
        self.assertEqual(week_index, [])

    def test_empty_input_produces_empty_output(self) -> None:
        annotated, week_index = compute_matchweeks([], league="mls", season=2026)
        self.assertEqual(annotated, [])
        self.assertEqual(week_index, [])


if __name__ == "__main__":
    unittest.main()
