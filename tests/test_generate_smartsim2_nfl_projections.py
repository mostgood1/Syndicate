"""Regression coverage for scripts/generate_smartsim2_nfl_projections.py --
the NFL-equivalent of generate_smartsim2_ncaaf_projections.py. Unlike the
NCAAF script (which gets team ratings from a live CFBD API call), this one
derives everything locally from real nflverse play-by-play, since no
external team-rating API exists for the NFL -- so these tests build small
fixture play lists rather than mocking an API.
"""

from __future__ import annotations

import unittest

import scripts.generate_smartsim2_nfl_projections as gen


def _play(week: int, posteam: str, defteam: str, play_type: str, epa: float) -> tuple:
    return (week, posteam, defteam, play_type, epa)


class MeanEpaTests(unittest.TestCase):
    def test_offense_and_defense_filter_correctly(self) -> None:
        plays = [
            _play(1, "KC", "DEN", "pass", 0.4),
            _play(1, "DEN", "KC", "run", -0.1),
            _play(2, "KC", "SEA", "run", 0.2),
        ]
        self.assertAlmostEqual(gen._mean_epa(plays, team="KC", side="offense", before_week=None), 0.3)
        self.assertAlmostEqual(gen._mean_epa(plays, team="KC", side="defense", before_week=None), -0.1)

    def test_before_week_filter_excludes_later_weeks(self) -> None:
        plays = [_play(1, "KC", "DEN", "pass", 0.5), _play(5, "KC", "DEN", "pass", -0.5)]
        self.assertAlmostEqual(gen._mean_epa(plays, team="KC", side="offense", before_week=2), 0.5)

    def test_no_matching_plays_returns_none(self) -> None:
        self.assertIsNone(gen._mean_epa([], team="KC", side="offense", before_week=None))


class TeamRatingTests(unittest.TestCase):
    def test_uses_current_season_rolling_when_available(self) -> None:
        current = [_play(1, "KC", "DEN", "pass", 0.3), _play(1, "DEN", "KC", "run", -0.2)]
        offense, defense, source = gen.team_rating("KC", week=2, current_plays=current, prior_plays=None)
        self.assertAlmostEqual(offense, 0.3)
        self.assertAlmostEqual(defense, 0.2)
        self.assertEqual(source, "current_season_rolling")

    def test_falls_back_to_prior_season_at_week_one(self) -> None:
        prior = [_play(10, "KC", "DEN", "pass", 0.25), _play(10, "DEN", "KC", "run", -0.15)]
        offense, defense, source = gen.team_rating("KC", week=1, current_plays=[], prior_plays=prior)
        self.assertAlmostEqual(offense, 0.25)
        self.assertAlmostEqual(defense, 0.15)
        self.assertEqual(source, "prior_season_fallback")

    def test_defaults_to_neutral_when_no_data_anywhere(self) -> None:
        offense, defense, source = gen.team_rating("KC", week=1, current_plays=[], prior_plays=[])
        self.assertEqual((offense, defense), (0.0, 0.0))
        self.assertEqual(source, "neutral_no_data")


class BuildProjectionTests(unittest.TestCase):
    def test_seeded_output_is_deterministic_and_shaped_correctly(self) -> None:
        current = [
            _play(1, "KC", "DEN", "pass", 0.3),
            _play(1, "DEN", "KC", "run", -0.1),
            _play(1, "DEN", "KC", "pass", 0.1),
            _play(1, "KC", "DEN", "run", -0.05),
        ]
        kwargs = dict(season=2025, week=2, home_team="KC", away_team="DEN", game_id="2025_02_DEN_KC", current_plays=current, prior_plays=None, seeds=25)
        first = gen.build_projection(**kwargs)
        second = gen.build_projection(**kwargs)
        self.assertEqual(first.home_score_mean, second.home_score_mean)
        self.assertEqual(first.seeds_used, 25)
        self.assertEqual(first.profile_name, "nfl_v1")
        self.assertTrue(0.0 <= first.home_win_rate <= 1.0)
        self.assertGreater(first.total_mean, 0)
        self.assertGreaterEqual(first.margin_stdev, 0)


if __name__ == "__main__":
    unittest.main()
