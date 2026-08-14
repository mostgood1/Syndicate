"""Regression coverage for
scripts/generate_smartsim2_nfl_preseason_projections.py -- the real,
data-driven shrinkage-toward-league-neutral preseason projection
generator. Mirrors tests/test_generate_smartsim2_nfl_projections.py's
fixture-tuple + tempdir-patched-DATA_ROOT pattern.
"""

from __future__ import annotations

import unittest

import scripts.generate_smartsim2_nfl_preseason_projections as gen


def _play(week: int, posteam: str, defteam: str, play_type: str, epa: float) -> tuple:
    return (week, posteam, defteam, play_type, epa)


class ShrunkRatingTests(unittest.TestCase):
    """MEAN_SHRINKAGE_SCALE (0.35) means shrunk_rating()'s mean shift is a
    fraction OF the participation share, not the raw share itself -- a
    real, live spot-check (2025 NE off +0.158 vs TEN off -0.160 EPA/play)
    found the earlier 1:1 design collapsed real team-quality spread
    almost to nothing at high shares, making every game's projected score
    converge on the same ~21-23 baseline regardless of who was playing."""

    def test_zero_share_leaves_rating_unchanged(self) -> None:
        shrunk, applied = gen.shrunk_rating(0.4, nonstarter_share=0.0)
        self.assertAlmostEqual(shrunk, 0.4)
        self.assertEqual(applied, 0.0)

    def test_full_share_only_moves_rating_by_the_scaled_fraction(self) -> None:
        shrunk, applied = gen.shrunk_rating(0.4, nonstarter_share=1.0)
        expected_mean_share = gen.MEAN_SHRINKAGE_SCALE
        self.assertAlmostEqual(applied, expected_mean_share)
        self.assertAlmostEqual(shrunk, 0.4 * (1.0 - expected_mean_share) + gen.LEAGUE_NEUTRAL_RATING * expected_mean_share)
        # Real team identity survives even at a full 100% participation share.
        self.assertGreater(shrunk, gen.LEAGUE_NEUTRAL_RATING)

    def test_partial_share_is_a_weighted_average_of_the_scaled_fraction(self) -> None:
        shrunk, applied = gen.shrunk_rating(0.4, nonstarter_share=0.5)
        expected_mean_share = 0.5 * gen.MEAN_SHRINKAGE_SCALE
        self.assertAlmostEqual(applied, expected_mean_share)
        self.assertAlmostEqual(shrunk, 0.4 * (1.0 - expected_mean_share))

    def test_negative_rating_shrinks_toward_neutral_too(self) -> None:
        shrunk, applied = gen.shrunk_rating(-0.4, nonstarter_share=0.5)
        expected_mean_share = 0.5 * gen.MEAN_SHRINKAGE_SCALE
        self.assertAlmostEqual(shrunk, -0.4 * (1.0 - expected_mean_share))

    def test_real_team_spread_mostly_survives_at_the_highest_real_share(self) -> None:
        # Regression guard for the exact bug the live spot-check found:
        # real 2025 NE (+0.1583) vs TEN (-0.1597) offense ratings, week 1's
        # real share (0.92) -- confirm the gap between them stays large,
        # not compressed to near-zero.
        share = gen.NONSTARTER_PARTICIPATION_SHARE[1]
        ne_shrunk, _ = gen.shrunk_rating(0.1583, nonstarter_share=share)
        ten_shrunk, _ = gen.shrunk_rating(-0.1597, nonstarter_share=share)
        real_spread = 0.1583 - (-0.1597)
        shrunk_spread = ne_shrunk - ten_shrunk
        self.assertGreater(shrunk_spread, real_spread * 0.5)


class WidenedStdevTests(unittest.TestCase):
    def test_zero_share_leaves_stdev_unchanged(self) -> None:
        self.assertAlmostEqual(gen.widened_stdev(10.0, nonstarter_share=0.0), 10.0)

    def test_positive_share_widens_stdev(self) -> None:
        self.assertAlmostEqual(gen.widened_stdev(10.0, nonstarter_share=0.5), 15.0)

    def test_higher_share_widens_more(self) -> None:
        wide_share = gen.widened_stdev(10.0, nonstarter_share=0.92)
        low_share = gen.widened_stdev(10.0, nonstarter_share=0.55)
        self.assertGreater(wide_share, low_share)


class BuildPreseasonProjectionTests(unittest.TestCase):
    def test_current_plays_empty_always_forces_prior_season_fallback(self) -> None:
        prior = [_play(10, "KC", "DEN", "pass", 0.3), _play(10, "DEN", "KC", "run", -0.1)]
        projection = gen.build_preseason_projection(
            season=2026, week=1, home_team="KC", away_team="DEN", game_id="g1",
            prior_season_plays=prior, seeds=10,
        )
        self.assertIn("prior_season_fallback", projection.rating_source)

    def test_seeded_output_is_deterministic_and_shaped_correctly(self) -> None:
        prior = [
            _play(1, "KC", "DEN", "pass", 0.3),
            _play(1, "DEN", "KC", "run", -0.1),
            _play(1, "DEN", "KC", "pass", 0.1),
            _play(1, "KC", "DEN", "run", -0.05),
        ]
        kwargs = dict(season=2026, week=2, home_team="KC", away_team="DEN", game_id="g1", prior_season_plays=prior, seeds=25)
        first = gen.build_preseason_projection(**kwargs)
        second = gen.build_preseason_projection(**kwargs)
        self.assertEqual(first.home_score_mean, second.home_score_mean)
        self.assertEqual(first.seeds_used, 25)
        self.assertEqual(first.profile_name, "nfl_preseason_v1")
        self.assertTrue(0.0 <= first.home_win_rate <= 1.0)
        self.assertGreater(first.total_mean, 0)
        self.assertGreaterEqual(first.margin_stdev, 0)

    def test_week_specific_participation_share_is_recorded(self) -> None:
        prior = [_play(1, "KC", "DEN", "pass", 0.3), _play(1, "DEN", "KC", "run", -0.1)]
        for week in (1, 2, 3, 4):
            projection = gen.build_preseason_projection(
                season=2026, week=week, home_team="KC", away_team="DEN", game_id="g1",
                prior_season_plays=prior, seeds=5,
            )
            self.assertEqual(projection.nonstarter_participation_share, gen.NONSTARTER_PARTICIPATION_SHARE[week])

    def test_dress_rehearsal_week_has_least_shrinkage(self) -> None:
        prior = [_play(1, "KC", "DEN", "pass", 0.3), _play(1, "DEN", "KC", "run", -0.1)]
        week1 = gen.build_preseason_projection(season=2026, week=1, home_team="KC", away_team="DEN", game_id="g1", prior_season_plays=prior, seeds=5)
        week3 = gen.build_preseason_projection(season=2026, week=3, home_team="KC", away_team="DEN", game_id="g1", prior_season_plays=prior, seeds=5)
        self.assertLess(week3.shrinkage_applied, week1.shrinkage_applied)

    def test_uncertainty_note_names_the_real_week_label(self) -> None:
        prior = [_play(1, "KC", "DEN", "pass", 0.3), _play(1, "DEN", "KC", "run", -0.1)]
        projection = gen.build_preseason_projection(season=2026, week=3, home_team="KC", away_team="DEN", game_id="g1", prior_season_plays=prior, seeds=5)
        self.assertIn("dress rehearsal", projection.uncertainty_note.lower())


class PreseasonScheduleRowsTests(unittest.TestCase):
    def _write_schedule(self, tmp, season, rows):
        import csv
        import os

        fieldnames = ["game_id", "season", "game_type", "week", "gameday", "gametime", "away_team", "home_team", "away_score", "home_score", "status", "venue"]
        with open(os.path.join(tmp, f"schedule_preseason_{season}.csv"), "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                full = {key: "" for key in fieldnames}
                full.update(row)
                writer.writerow(full)

    def test_filters_to_requested_week(self) -> None:
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            self._write_schedule(tmp, 2026, [
                {"game_id": "g1", "week": "1", "home_team": "ARI", "away_team": "CAR"},
                {"game_id": "g2", "week": "2", "home_team": "CIN", "away_team": "DET"},
            ])
            with patch.object(gen, "DATA_ROOT", Path(tmp)), patch.object(gen, "nfl_artifact_output_root", lambda: Path(tmp)):
                rows = gen.preseason_schedule_rows(2026, 1)

        self.assertEqual(rows, [{"game_id": "g1", "home_team": "ARI", "away_team": "CAR"}])

    def test_missing_file_returns_empty(self) -> None:
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(gen, "DATA_ROOT", Path(tmp)), patch.object(gen, "nfl_artifact_output_root", lambda: Path(tmp)):
                rows = gen.preseason_schedule_rows(2026, 1)

        self.assertEqual(rows, [])


class MainTests(unittest.TestCase):
    def test_main_writes_artifact_for_real_schedule_rows(self) -> None:
        import csv
        import os
        import sys
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        import scripts.generate_smartsim2_nfl_projections as regular_gen

        with tempfile.TemporaryDirectory() as tmp:
            fieldnames = ["game_id", "season", "game_type", "week", "gameday", "gametime", "away_team", "home_team", "away_score", "home_score", "status", "venue"]
            with open(os.path.join(tmp, "schedule_preseason_2026.csv"), "w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerow({**{k: "" for k in fieldnames}, "game_id": "g1", "week": "1", "home_team": "ARI", "away_team": "CAR"})

            # SYNTHETIC PRIOR-SEASON PLAYS. Added 2026-08-13 with the
            # degenerate-writer guard: this fixture previously supplied no
            # play-by-play at all, so `main()` ran with every club rated
            # `neutral_no_data` and wrote a file identical for every game --
            # the exact production defect that put one constant on 16 games
            # across four dates. The test passed, because it only asserted the
            # artifact existed and named the game. The broken behaviour had
            # test coverage asserting it.
            #
            # Still hermetic: synthetic rows under tmp, never the real
            # pbp_2025.csv.
            pbp_dir = os.path.join(tmp, "tracking", "nflverse", "pbp")
            os.makedirs(pbp_dir, exist_ok=True)
            with open(os.path.join(pbp_dir, "pbp_2025.csv"), "w", encoding="utf-8", newline="") as handle:
                pbp_fields = ["season_type", "week", "posteam", "defteam", "play_type", "epa"]
                pbp_writer = csv.DictWriter(handle, fieldnames=pbp_fields)
                pbp_writer.writeheader()
                for week, (off, deff, play, epa) in enumerate(
                    [("ARI", "CAR", "pass", "0.12"), ("CAR", "ARI", "run", "-0.07"),
                     ("ARI", "CAR", "run", "0.05"), ("CAR", "ARI", "pass", "-0.03")],
                    start=1,
                ):
                    pbp_writer.writerow({"season_type": "REG", "week": str(week), "posteam": off, "defteam": deff, "play_type": play, "epa": epa})

            # load_pbp_plays() (imported from the REGULAR-season script)
            # reads from that module's own DATA_ROOT, not this one's --
            # patch both so the real production pbp_2025.csv is never
            # touched by this test (hermetic, same discipline as
            # test_generate_smartsim2_nfl_projections.py's own tests).
            with patch.object(gen, "DATA_ROOT", Path(tmp)), patch.object(gen, "nfl_artifact_output_root", lambda: Path(tmp)), patch.object(regular_gen, "DATA_ROOT", Path(tmp)), patch.object(
                sys, "argv", ["generate_smartsim2_nfl_preseason_projections.py", "--season", "2026", "--week", "1", "--seeds", "2"],
            ):
                gen.main()
            artifact_path = Path(tmp) / "smartsim2_preseason_projections_2026_wk1.csv"
            self.assertTrue(artifact_path.exists())
            content = artifact_path.read_text(encoding="utf-8")
            self.assertIn("g1", content)
            self.assertIn("nonstarter_participation_share", content)


if __name__ == "__main__":
    unittest.main()
