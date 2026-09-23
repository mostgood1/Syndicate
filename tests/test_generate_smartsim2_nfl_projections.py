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


class PpgRatingBlendTests(unittest.TestCase):
    """The per-game path production runs (`SYNDICATE_NFL_PPG_RATINGS=1`).

    2026-09-21: from week 2 the rating was ONLY this season's games, so a
    week-2 rating was one game of EPA -- NYG @ LA served at NYG by 17.8 against
    a close of LA -8.5. These pin the blend that replaced it."""

    # One wild week-1 game for KC this season; a calm, longer prior season.
    CURRENT = [_play(1, "KC", "DEN", "pass", 3.0), _play(1, "DEN", "KC", "run", -2.0)]
    PRIOR = [
        _play(week, off, dfn, "pass", epa)
        for week in range(1, 11)
        for off, dfn, epa in (("KC", "DEN", 0.4), ("DEN", "KC", -0.1))
    ]

    def _rating(self, week, env):
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {"SYNDICATE_NFL_PPG_RATINGS": "1", **env}, clear=False):
            if "SYNDICATE_NFL_RATING_PRIOR_GAMES" not in env:
                # ABSENT is the default under test; a developer's shell must not leak in.
                os.environ.pop("SYNDICATE_NFL_RATING_PRIOR_GAMES", None)
            return gen.team_rating("KC", week=week, current_plays=self.CURRENT, prior_plays=self.PRIOR)

    def test_week_two_blends_one_game_with_four_games_of_prior(self) -> None:
        current = gen._rating_pair(self.CURRENT, team="KC", before_week=2)
        prior = gen._rating_pair(self.PRIOR, team="KC", before_week=None)
        offense, defense, source = self._rating(2, {})
        self.assertEqual(source, "current_season_blend")
        # n=1 game this season against K=4: one fifth current, four fifths prior.
        self.assertAlmostEqual(offense, (current[0] + 4 * prior[0]) / 5)
        self.assertAlmostEqual(defense, (current[1] + 4 * prior[1]) / 5)
        # Reachability: the blend must actually move the number off the old path.
        self.assertNotAlmostEqual(offense, current[0])

    def test_zero_prior_games_restores_the_old_estimator(self) -> None:
        current = gen._rating_pair(self.CURRENT, team="KC", before_week=2)
        offense, defense, source = self._rating(2, {"SYNDICATE_NFL_RATING_PRIOR_GAMES": "0"})
        self.assertEqual(source, "current_season_rolling")
        self.assertAlmostEqual(offense, current[0])
        self.assertAlmostEqual(defense, current[1])

    def test_week_one_is_unchanged_prior_season(self) -> None:
        prior = gen._rating_pair(self.PRIOR, team="KC", before_week=None)
        offense, defense, source = self._rating(1, {})
        self.assertEqual(source, "prior_season_fallback")
        self.assertAlmostEqual(offense, prior[0])
        self.assertAlmostEqual(defense, prior[1])


class WeekScheduleTests(unittest.TestCase):
    def test_includes_post_season_games(self) -> None:
        import csv
        import os
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            pbp_dir = os.path.join(tmp, "tracking", "nflverse", "pbp")
            os.makedirs(pbp_dir, exist_ok=True)
            fieldnames = ["season_type", "week", "game_id", "home_team", "away_team"]
            with open(os.path.join(pbp_dir, "pbp_2025.csv"), "w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerow({"season_type": "POST", "week": "22", "game_id": "2025_22_SEA_NE", "home_team": "NE", "away_team": "SEA"})
                writer.writerow({"season_type": "PRE", "week": "22", "game_id": "2025_22_XX_YY", "home_team": "YY", "away_team": "XX"})

            # `SYNDICATE_NFL_SOURCE_ROOT`, not just `DATA_ROOT`. `#441`
            # deliberately moved `_pbp_path` OFF `DATA_ROOT` and onto a
            # candidate-root resolver, because `default_nfl_source_root()`
            # picks a root by probing for `upcoming_recs_*.csv` and so chose
            # the ephemeral CHECKOUT on refresh-worker while the pbp lives
            # only on the mounted disk -- measured: zero plays, the
            # degenerate-run guard refused, artifact 2.36 days stale at ~107
            # relaunches/day. Patching `DATA_ROOT` alone therefore stopped
            # steering the pbp read, and this test silently reached for the
            # REAL repo path instead of its own fixture.
            #
            # Setting the env var exercises the real resolver rather than
            # stubbing it, and it lands on exactly the tmp tree the fixture
            # above already writes.
            with patch.dict(os.environ, {"SYNDICATE_NFL_SOURCE_ROOT": tmp}, clear=False), patch.object(gen, "DATA_ROOT", Path(tmp)), patch.object(gen, "nfl_artifact_output_root", lambda: Path(tmp)):
                rows = gen.week_schedule(2025, 22, [])

        self.assertEqual(rows, [{"game_id": "2025_22_SEA_NE", "home_team": "NE", "away_team": "SEA"}])


class RealScheduleFallbackTests(unittest.TestCase):
    def _write_real_schedule(self, tmp, season, rows):
        import csv
        import os

        fieldnames = ["game_id", "season", "game_type", "week", "gameday", "gametime", "away_team", "home_team", "away_score", "home_score", "spread_line", "total_line", "away_moneyline", "home_moneyline", "stadium"]
        with open(os.path.join(tmp, f"schedule_{season}.csv"), "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                full = {key: "" for key in fieldnames}
                full.update(row)
                writer.writerow(full)

    def test_reads_real_schedule_csv_for_requested_week(self) -> None:
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            self._write_real_schedule(tmp, 2026, [
                {"game_id": "2026_01_NE_SEA", "week": "1", "home_team": "SEA", "away_team": "NE"},
                {"game_id": "2026_02_X_Y", "week": "2", "home_team": "Y", "away_team": "X"},
            ])
            with patch.object(gen, "DATA_ROOT", Path(tmp)), patch.object(gen, "nfl_artifact_output_root", lambda: Path(tmp)):
                rows = gen.week_schedule_from_real_schedule(2026, 1)

        self.assertEqual(rows, [{"game_id": "2026_01_NE_SEA", "home_team": "SEA", "away_team": "NE"}])

    def test_missing_file_returns_empty(self) -> None:
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(gen, "DATA_ROOT", Path(tmp)), patch.object(gen, "nfl_artifact_output_root", lambda: Path(tmp)):
                rows = gen.week_schedule_from_real_schedule(2026, 1)

        self.assertEqual(rows, [])

    def _write_prior_season_pbp(self, tmp, season, teams):
        """Synthetic prior-season plays, so a test about the SCHEDULE is not
        also a test about a total ratings outage.

        Added 2026-08-13 with the degenerate-writer guard. This fixture used to
        supply no play-by-play at all, which meant `main()` ran with every club
        rated `neutral_no_data` and produced a file identical for every game --
        the exact production defect that put one constant on 16 games. The test
        passed, because it only asserted the artifact existed and named the
        game. **The broken behaviour had test coverage asserting it.**

        Kept hermetic: synthetic rows under tmp, never the real pbp_2025.csv.
        """
        import csv
        import os

        directory = os.path.join(tmp, "tracking", "nflverse", "pbp")
        os.makedirs(directory, exist_ok=True)
        fieldnames = ["season_type", "week", "posteam", "defteam", "play_type", "epa"]
        with open(os.path.join(directory, f"pbp_{season}.csv"), "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for index, team in enumerate(teams):
                other = teams[(index + 1) % len(teams)]
                # Distinct epa per club, so the resulting projections differ by
                # matchup -- a fixture where every team rates identically would
                # reintroduce the constant this guard exists to prevent.
                writer.writerow({"season_type": "REG", "week": "1", "posteam": team, "defteam": other, "play_type": "pass", "epa": f"{0.10 + index * 0.05:.2f}"})
                writer.writerow({"season_type": "REG", "week": "1", "posteam": other, "defteam": team, "play_type": "run", "epa": f"{-0.08 - index * 0.03:.2f}"})
                writer.writerow({"season_type": "REG", "week": "2", "posteam": team, "defteam": other, "play_type": "run", "epa": f"{0.04 + index * 0.02:.2f}"})
                writer.writerow({"season_type": "REG", "week": "2", "posteam": other, "defteam": team, "play_type": "pass", "epa": f"{-0.05 - index * 0.01:.2f}"})

    def test_main_falls_back_when_no_pbp_exists_yet(self) -> None:
        # "No pbp exists yet" means THIS season has none (week 1, nothing
        # played). The PRIOR season still does -- that is what
        # `prior_season_fallback` is for. Supplying it keeps this a test of the
        # schedule fallback rather than of a data outage, which now refuses.
        import os
        import sys
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            self._write_real_schedule(tmp, 2026, [
                {"game_id": "2026_01_NE_SEA", "week": "1", "home_team": "SEA", "away_team": "NE"},
            ])
            self._write_prior_season_pbp(tmp, 2025, ["SEA", "NE"])
            # `SYNDICATE_NFL_SOURCE_ROOT`, not just `DATA_ROOT`. `#441`
            # deliberately moved `_pbp_path` OFF `DATA_ROOT` and onto a
            # candidate-root resolver, because `default_nfl_source_root()`
            # picks a root by probing for `upcoming_recs_*.csv` and so chose
            # the ephemeral CHECKOUT on refresh-worker while the pbp lives
            # only on the mounted disk -- measured: zero plays, the
            # degenerate-run guard refused, artifact 2.36 days stale at ~107
            # relaunches/day. Patching `DATA_ROOT` alone therefore stopped
            # steering the pbp read, and this test silently reached for the
            # REAL repo path instead of its own fixture.
            #
            # Setting the env var exercises the real resolver rather than
            # stubbing it, and it lands on exactly the tmp tree the fixture
            # above already writes.
            with patch.dict(os.environ, {"SYNDICATE_NFL_SOURCE_ROOT": tmp}, clear=False), patch.object(gen, "DATA_ROOT", Path(tmp)), patch.object(gen, "nfl_artifact_output_root", lambda: Path(tmp)), patch.object(
                sys, "argv", ["generate_smartsim2_nfl_projections.py", "--season", "2026", "--week", "1", "--seeds", "2"],
            ):
                gen.main()
            artifact_path = Path(tmp) / "smartsim2_projections_2026_wk1.csv"
            self.assertTrue(artifact_path.exists())
            content = artifact_path.read_text(encoding="utf-8")
            self.assertIn("2026_01_NE_SEA", content)

    def _write_partial_week_pbp(self, tmp, season, week, teams, played_games):
        """Current-season pbp for a week IN PROGRESS: every club has earlier-week
        plays (so ratings exist), and only `played_games` carry plays at `week`
        -- the state the file is in on a Sunday evening or a Monday."""
        import csv
        import os

        directory = os.path.join(tmp, "tracking", "nflverse", "pbp")
        os.makedirs(directory, exist_ok=True)
        fieldnames = ["season_type", "week", "game_id", "home_team", "away_team", "posteam", "defteam", "play_type", "epa"]
        with open(os.path.join(directory, f"pbp_{season}.csv"), "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for index, team in enumerate(teams):
                other = teams[(index + 1) % len(teams)]
                game_id = f"{season}_{week - 1:02d}_{other}_{team}"
                base = {"season_type": "REG", "week": str(week - 1), "game_id": game_id, "home_team": team, "away_team": other}
                writer.writerow({**base, "posteam": team, "defteam": other, "play_type": "pass", "epa": f"{0.10 + index * 0.05:.2f}"})
                writer.writerow({**base, "posteam": other, "defteam": team, "play_type": "run", "epa": f"{-0.08 - index * 0.03:.2f}"})
            for game_id, home_team, away_team in played_games:
                base = {"season_type": "REG", "week": str(week), "game_id": game_id, "home_team": home_team, "away_team": away_team}
                writer.writerow({**base, "posteam": home_team, "defteam": away_team, "play_type": "pass", "epa": "0.05"})
                writer.writerow({**base, "posteam": away_team, "defteam": home_team, "play_type": "run", "epa": "-0.02"})

    def test_main_keeps_unplayed_games_when_the_week_is_partly_played(self) -> None:
        # The production defect, 2026-09-21: the pbp held 8 of week 2's 16
        # games, the schedule fallback only fired on an EMPTY pbp week, and the
        # file dropped the other 8 -- that night's Monday game among them.
        import csv
        import os
        import sys
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        scheduled = [
            ("2026_02_DET_BUF", "BUF", "DET"),
            ("2026_02_CAR_ATL", "ATL", "CAR"),
            ("2026_02_NYG_LA", "LA", "NYG"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            self._write_real_schedule(tmp, 2026, [
                {"game_id": game_id, "week": "2", "home_team": home, "away_team": away}
                for game_id, home, away in scheduled
            ])
            self._write_partial_week_pbp(tmp, 2026, 2, ["BUF", "DET", "ATL", "CAR", "LA", "NYG"], played_games=scheduled[:1])
            self._write_prior_season_pbp(tmp, 2025, ["BUF", "DET", "ATL", "CAR", "LA", "NYG"])
            with patch.dict(os.environ, {"SYNDICATE_NFL_SOURCE_ROOT": tmp}, clear=False), patch.object(gen, "DATA_ROOT", Path(tmp)), patch.object(gen, "nfl_artifact_output_root", lambda: Path(tmp)), patch.object(
                sys, "argv", ["generate_smartsim2_nfl_projections.py", "--season", "2026", "--week", "2", "--seeds", "2"],
            ):
                # The fixture must reproduce the production state, or this test
                # proves nothing: the pbp's own week-2 list is ONE game.
                self.assertEqual([row["game_id"] for row in gen.week_schedule(2026, 2, [])], ["2026_02_DET_BUF"])
                gen.main()
            artifact_path = Path(tmp) / "smartsim2_projections_2026_wk2.csv"
            with artifact_path.open(encoding="utf-8", newline="") as handle:
                written = [row["game_id"] for row in csv.DictReader(handle)]

        self.assertEqual(sorted(written), sorted(game_id for game_id, _, _ in scheduled))

    def test_week_game_list_unions_by_game_id(self) -> None:
        # A game only the pbp knows (a playoff game not yet in the schedule
        # file) is kept; a game in both appears once.
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            self._write_real_schedule(tmp, 2026, [
                {"game_id": "2026_02_DET_BUF", "week": "2", "home_team": "BUF", "away_team": "DET"},
                {"game_id": "2026_02_NYG_LA", "week": "2", "home_team": "LA", "away_team": "NYG"},
            ])
            pbp_rows = [
                {"game_id": "2026_02_DET_BUF", "home_team": "BUF", "away_team": "DET"},
                {"game_id": "2026_02_X_Y", "home_team": "Y", "away_team": "X"},
            ]
            with patch.object(gen, "DATA_ROOT", Path(tmp)), patch.object(gen, "nfl_artifact_output_root", lambda: Path(tmp)), patch.object(gen, "week_schedule", lambda season, week, plays: pbp_rows):
                rows, counts = gen.week_game_list(2026, 2, [])

        self.assertEqual([row["game_id"] for row in rows], ["2026_02_DET_BUF", "2026_02_NYG_LA", "2026_02_X_Y"])
        self.assertEqual(counts, {"pbp_rows": 2, "real_schedule_rows": 2, "pbp_only_rows": 1})


class BuildProjectionTests(unittest.TestCase):
    def test_seeded_output_is_deterministic_and_shaped_correctly(self) -> None:
        current = [
            _play(1, "KC", "DEN", "pass", 0.3),
            _play(1, "DEN", "KC", "run", -0.1),
            _play(1, "DEN", "KC", "pass", 0.1),
            _play(1, "KC", "DEN", "run", -0.05),
        ]
        kwargs = dict(season=2025, week=2, home_team="KC", away_team="DEN", game_id="2025_02_DEN_KC", current_plays=current, prior_plays=None, seeds=25, apply_injury_adjustment=False)
        first, first_notes = gen.build_projection(**kwargs)
        second, second_notes = gen.build_projection(**kwargs)
        self.assertEqual(first.home_score_mean, second.home_score_mean)
        self.assertEqual(first.seeds_used, 25)
        self.assertEqual(first.profile_name, "nfl_v1")
        self.assertTrue(0.0 <= first.home_win_rate <= 1.0)
        self.assertGreater(first.total_mean, 0)
        self.assertGreaterEqual(first.margin_stdev, 0)
        self.assertEqual(first_notes, [])
        self.assertEqual(second_notes, [])

    def test_injury_adjustment_disabled_when_explicitly_off(self) -> None:
        current = [
            _play(1, "KC", "DEN", "pass", 0.3),
            _play(1, "DEN", "KC", "run", -0.1),
        ]
        projection, notes = gen.build_projection(
            season=2025, week=2, home_team="KC", away_team="DEN", game_id="2025_02_DEN_KC",
            current_plays=current, prior_plays=None, seeds=5, apply_injury_adjustment=False,
        )
        self.assertEqual(notes, [])

    def test_injury_adjustment_defaults_to_off(self) -> None:
        # Backtested (scripts/backtest_nfl_injury_adjustment.py,
        # scripts/analyze_nfl_injury_adjustment_sides.py) to HURT full-
        # season win accuracy against real 2025 games -- defaults OFF, not
        # just available as an opt-out. Real production injuries file
        # doesn't exist under this tempdir-free call, so if the default
        # were still True this would raise or silently look up the real
        # production data on disk; confirm the default keeps that lookup
        # out of the call path entirely by checking no diagnostics appear
        # even though this fixture never patches DATA_ROOT/source_root.
        current = [_play(1, "KC", "DEN", "pass", 0.3), _play(1, "DEN", "KC", "run", -0.1)]
        import inspect
        default_value = inspect.signature(gen.build_projection).parameters["apply_injury_adjustment"].default
        self.assertFalse(default_value)
        projection, notes = gen.build_projection(
            season=2025, week=2, home_team="KC", away_team="DEN", game_id="2025_02_DEN_KC",
            current_plays=current, prior_plays=None, seeds=5,
        )
        self.assertEqual(notes, [])


class TotalLevelShrinkTests(unittest.TestCase):
    """The LEVEL gain, fitted separately from the DIFFERENCE gain.

    2026-09-22: production's served 2026 wk3 board priced totals with SD 9.02
    against a market SD of 2.51 -- 3.60x -- while the MARGIN over the same 16
    games was calibrated (5.58 vs 4.86). `NFL_RATING_SCALE` was fitted by OLS of
    actual MARGIN on the rating DIFFERENTIAL and the level inherited it; against
    544 actual games the level wants 0.35 on offence and 0.01 on defence where
    the engine applies 0.80 and 0.76.

    THE FIRST TEST IS THE ONE THAT MATTERS: the shrink must not move the
    DIFFERENCE between the two teams, which is what the margin reads.

    IT PINS THE RATINGS, NOT `margin_mean`, and that is deliberate -- the sim is
    not linear in its ratings, so the simulated margin does move a little. It was
    measured rather than assumed: on 2025 wk10 at 300 seeds the mean signed
    change was +0.108 (t = +0.61) with an RMS of 0.86 seed-standard-errors, i.e.
    unchanged in expectation and wandering only as far as the seeds already
    wander. A test asserting `margin_mean` equality would fail on that noise and
    teach the next reader that the shrink moves the margin, which it does not."""

    RATINGS = (0.40, -0.10, 0.06, 0.22)  # home_off, home_def, away_off, away_def

    def test_the_difference_between_the_teams_is_exactly_preserved(self) -> None:
        for shrink in (0.0, 0.3, 0.5, 1.0):
            with self.subTest(shrink=shrink):
                ho, hd, ao, ad = gen.shrink_rating_level(*self.RATINGS, shrink)
                before_off, before_def = self.RATINGS[0] - self.RATINGS[2], self.RATINGS[1] - self.RATINGS[3]
                self.assertAlmostEqual(ho - ao, before_off, places=12)
                self.assertAlmostEqual(hd - ad, before_def, places=12)

    def test_level_is_scaled_by_the_shrink(self) -> None:
        ho, hd, ao, ad = gen.shrink_rating_level(*self.RATINGS, 0.3)
        self.assertAlmostEqual(ho + ao, 0.3 * (self.RATINGS[0] + self.RATINGS[2]), places=12)
        self.assertAlmostEqual(hd + ad, 0.3 * (self.RATINGS[1] + self.RATINGS[3]), places=12)

    def test_shrink_of_one_is_an_exact_no_op(self) -> None:
        # The kill switch has to return the SAME numbers, not merely close ones:
        # it is what a revert falls back to.
        self.assertEqual(gen.shrink_rating_level(*self.RATINGS, 1.0), self.RATINGS)

    def test_zero_shrink_sends_the_level_to_the_league_mean(self) -> None:
        # Ratings are centred, so level 0 IS the league-average total.
        ho, hd, ao, ad = gen.shrink_rating_level(*self.RATINGS, 0.0)
        self.assertAlmostEqual(ho + ao, 0.0, places=12)
        self.assertAlmostEqual(hd + ad, 0.0, places=12)

    def _shrink(self, env):
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, env, clear=False):
            if "SYNDICATE_NFL_TOTAL_LEVEL_SHRINK" not in env:
                # ABSENT is the default under test; a developer's shell must not leak in.
                os.environ.pop("SYNDICATE_NFL_TOTAL_LEVEL_SHRINK", None)
            return gen._total_level_shrink()

    def test_absent_means_the_fitted_value_not_off(self) -> None:
        # "absent != off" is a documented trap in this repo and this knob is ON
        # when absent -- the reverse of `SYNDICATE_NFL_DRIVE_PRIORS`.
        self.assertEqual(self._shrink({}), gen.NFL_TOTAL_LEVEL_SHRINK)
        self.assertLess(gen.NFL_TOTAL_LEVEL_SHRINK, 1.0)

    def test_env_overrides_and_one_is_the_kill_switch(self) -> None:
        self.assertEqual(self._shrink({"SYNDICATE_NFL_TOTAL_LEVEL_SHRINK": "1"}), 1.0)
        self.assertEqual(self._shrink({"SYNDICATE_NFL_TOTAL_LEVEL_SHRINK": "0.5"}), 0.5)

    def test_a_typo_falls_back_to_the_fitted_value(self) -> None:
        self.assertEqual(self._shrink({"SYNDICATE_NFL_TOTAL_LEVEL_SHRINK": "nope"}), gen.NFL_TOTAL_LEVEL_SHRINK)


class TotalDifferenceCorrectionTests(unittest.TestCase):
    """`#686`: the engine adds total purely for a MISMATCH, and reality gives
    that direction a coefficient of zero.

    Measured causally on a 5x5 grid with both rating SUMS pinned at zero:
    `total_shift = +7.3493*off_diff - 4.8940*def_diff`, R2 0.933, residual SD
    0.67 against a 0.97 seed SE. `corr(|market spread|, ACTUAL total)` on 2025
    is -0.032, so the response is REMOVED rather than rescaled."""

    def test_response_is_zero_when_the_teams_match(self) -> None:
        self.assertEqual(gen.total_difference_response(0.2, -0.1, 0.2, -0.1), 0.0)

    def test_response_is_odd_in_the_difference(self) -> None:
        # Measured at +/-0.2/0.4/0.8: flipping the sign of the mismatch flips the
        # sign of the shift. A correction built on abs() would be wrong here.
        a = gen.total_difference_response(0.3, -0.2, -0.1, 0.1)
        b = gen.total_difference_response(-0.1, 0.1, 0.3, -0.2)
        self.assertAlmostEqual(a, -b, places=12)

    def test_offence_and_defence_push_the_total_opposite_ways(self) -> None:
        off_only = gen.total_difference_response(0.4, 0.0, 0.0, 0.0)
        def_only = gen.total_difference_response(0.0, 0.4, 0.0, 0.0)
        self.assertGreater(off_only, 0.0)
        self.assertLess(def_only, 0.0)

    def _correction(self, env):
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, env, clear=False):
            if "SYNDICATE_NFL_TOTAL_DIFF_CORRECTION" not in env:
                os.environ.pop("SYNDICATE_NFL_TOTAL_DIFF_CORRECTION", None)
            return gen._total_diff_correction()

    def test_absent_means_OFF_and_that_is_deliberate(self) -> None:
        """This knob ships INERT, unlike the level shrink in the same file.

        Removing the response bought nothing measurable: paired on 272 held-out
        games, today -> both is -0.147 +- 0.185 (t=-0.79), better on 139/272,
        and weeks 2-4 go the WRONG WAY at +0.531 +- 0.475. Pinned as a test so
        that flipping the default later is a deliberate act with a failing test
        attached, not a quiet edit."""
        self.assertEqual(self._correction({}), 0.0)

    def test_the_mechanism_is_still_REACHABLE_when_armed(self) -> None:
        # Shipping disabled must not mean shipping untestable: off != on.
        self.assertEqual(self._correction({"SYNDICATE_NFL_TOTAL_DIFF_CORRECTION": "1"}), 1.0)
        self.assertNotEqual(self._correction({}), self._correction({"SYNDICATE_NFL_TOTAL_DIFF_CORRECTION": "1"}))

    def test_a_typo_falls_back_to_OFF(self) -> None:
        self.assertEqual(self._correction({"SYNDICATE_NFL_TOTAL_DIFF_CORRECTION": "nope"}), 0.0)

    def test_disabled_leaves_every_score_mean_untouched(self) -> None:
        """The whole point of landing it dark: with the default, the correction
        term is exactly 0.0, so no score mean moves by even a rounding unit."""
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SYNDICATE_NFL_TOTAL_DIFF_CORRECTION", None)
            delta = gen._total_diff_correction() * gen.total_difference_response(0.4, -0.3, -0.2, 0.25)
        self.assertEqual(delta, 0.0)

    def test_taking_half_off_each_side_moves_total_and_not_margin(self) -> None:
        """The arithmetic the wiring depends on, pinned independently of the sim."""
        home_raw, away_raw = 27.0, 19.0
        delta = gen.total_difference_response(0.3, -0.1, -0.1, 0.2)
        home, away = home_raw - delta / 2.0, away_raw - delta / 2.0
        self.assertAlmostEqual(home - away, home_raw - away_raw, places=12)
        self.assertAlmostEqual((home + away) - (home_raw + away_raw), -delta, places=12)


if __name__ == "__main__":
    unittest.main()
