"""Regression coverage for the 2026 season-bootstrap fixes in
scripts/generate_smartsim2_ncaaf_projections.py:

1. PPA ratings have no fallback for a brand-new season with no games played
   yet (confirmed live: CFBD's /ppa/teams returns [] for 2026). Fixed with a
   whole-index fallback to the prior season's final ratings.
2. The legacy engine's predicted-totals schedule is a single, non-season-
   partitioned file only ever refreshed for the engine's own season -- for a
   season the engine has no rows for, the games-to-simulate list must come
   directly from the already-fetched real CFBD games instead.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import scripts.generate_smartsim2_ncaaf_projections as gen


class LoadPpaRatingsWithFallbackTests(unittest.TestCase):
    def test_uses_current_season_when_populated(self) -> None:
        def fake_load(season):
            if season == 2026:
                return {"ohio st": {"team": "Ohio State"}}
            raise AssertionError("should not fetch prior season when current season is populated")

        with patch.object(gen, "load_ppa_ratings", side_effect=fake_load):
            index, rating_source = gen.load_ppa_ratings_with_fallback(2026)
        self.assertEqual(index, {"ohio st": {"team": "Ohio State"}})
        self.assertEqual(rating_source, "cfbd_ppa_season_2026")

    def test_falls_back_to_prior_season_when_current_is_empty(self) -> None:
        def fake_load(season):
            return {} if season == 2026 else {"ohio st": {"team": "Ohio State"}}

        with patch.object(gen, "load_ppa_ratings", side_effect=fake_load):
            index, rating_source = gen.load_ppa_ratings_with_fallback(2026)
        self.assertEqual(index, {"ohio st": {"team": "Ohio State"}})
        self.assertEqual(rating_source, "cfbd_ppa_season_2025_fallback_for_2026")

    def test_both_empty_returns_empty_index_and_current_season_label(self) -> None:
        with patch.object(gen, "load_ppa_ratings", return_value={}):
            index, rating_source = gen.load_ppa_ratings_with_fallback(2026)
        self.assertEqual(index, {})
        self.assertEqual(rating_source, "cfbd_ppa_season_2026")


class GamesFromCfbdWhenEngineScheduleEmptyTests(unittest.TestCase):
    def test_filters_to_strict_fbs_vs_fbs(self) -> None:
        cfbd_games = {
            ("a", "b"): {"homeTeam": "TCU", "awayTeam": "North Carolina", "homeClassification": "fbs", "awayClassification": "fbs"},
            ("c", "d"): {"homeTeam": "Delaware State", "awayTeam": "Stony Brook", "homeClassification": "fcs", "awayClassification": "fcs"},
            ("e", "f"): {"homeTeam": "Texas Tech", "awayTeam": "Abilene Christian", "homeClassification": "fbs", "awayClassification": "fcs"},
        }
        rows = gen.games_from_cfbd_when_engine_schedule_empty(cfbd_games)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0], {"home_team": "TCU", "away_team": "North Carolina"})

    def test_skips_games_missing_team_names(self) -> None:
        cfbd_games = {("a", "b"): {"homeTeam": "", "awayTeam": "North Carolina", "homeClassification": "fbs", "awayClassification": "fbs"}}
        rows = gen.games_from_cfbd_when_engine_schedule_empty(cfbd_games)
        self.assertEqual(rows, [])

    def test_empty_input_returns_empty_list(self) -> None:
        self.assertEqual(gen.games_from_cfbd_when_engine_schedule_empty({}), [])


if __name__ == "__main__":
    unittest.main()
