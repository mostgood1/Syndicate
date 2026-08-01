"""Coverage for syndicate/features/nfl/injury_adjustment.py -- real, per-play
EPA-attribution-based injury adjustment for NFL team ratings. Uses small
real-shaped fixture CSVs (pbp/injuries/depth-chart) under a tempdir-patched
source root, same pattern as tests/test_generate_smartsim2_nfl_projections.py.
"""

from __future__ import annotations

import csv
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.features.nfl import injury_adjustment as inj
from syndicate.features.nfl import player_stats


_PBP_FIELDNAMES = [
    "season_type", "week", "game_id", "posteam", "defteam", "epa",
    "passer_player_id", "passer_player_name", "passing_yards", "pass_attempt", "pass_touchdown",
    "rusher_player_id", "rusher_player_name", "rushing_yards", "rush_attempt", "rush_touchdown",
    "receiver_player_id", "receiver_player_name", "receiving_yards", "complete_pass", "touchdown",
    "sack_player_id", "half_sack_1_player_id", "half_sack_2_player_id", "interception_player_id",
    "tackle_for_loss_1_player_id", "tackle_for_loss_2_player_id",
    "forced_fumble_player_1_player_id", "forced_fumble_player_2_player_id",
    "fumble_recovery_1_player_id", "fumble_recovery_2_player_id",
    "pass_defense_1_player_id", "pass_defense_2_player_id",
]


class InjuryAdjustmentTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        player_stats.load_player_plays.cache_clear()
        self.addCleanup(player_stats.load_player_plays.cache_clear)
        patcher_a = patch.object(player_stats, "default_nfl_source_root", return_value=self.root)
        patcher_b = patch.object(inj, "default_nfl_source_root", return_value=self.root)
        patcher_a.start()
        patcher_b.start()
        self.addCleanup(patcher_a.stop)
        self.addCleanup(patcher_b.stop)

    def _write_pbp(self, season: int, rows: list[dict]) -> None:
        directory = self.root / "tracking" / "nflverse" / "pbp"
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / f"pbp_{season}.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=_PBP_FIELDNAMES)
            writer.writeheader()
            for row in rows:
                full = {key: "" for key in _PBP_FIELDNAMES}
                full.update(row)
                writer.writerow(full)

    def _write_injuries(self, season: int, rows: list[dict]) -> None:
        directory = self.root / "tracking" / "nflverse" / "injuries"
        directory.mkdir(parents=True, exist_ok=True)
        fieldnames = ["season", "week", "team", "gsis_id", "position", "full_name", "report_status"]
        with (directory / f"injuries_{season}.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    def _write_depth_chart(self, season: int, rows: list[dict]) -> None:
        directory = self.root / "source_artifacts" / "data" / "processed" / "depth"
        directory.mkdir(parents=True, exist_ok=True)
        fieldnames = ["team", "player_id", "positional_group", "depth_rank"]
        with (directory / f"depth_{season}_snapshot.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    def _pass_play(self, week, posteam, defteam, epa, passer, receiver=""):
        return {"season_type": "REG", "week": str(week), "game_id": f"g{week}", "posteam": posteam, "defteam": defteam, "epa": str(epa), "passer_player_id": passer, "pass_attempt": "1", "receiver_player_id": receiver, "complete_pass": "1" if receiver else ""}

    def _run_play(self, week, posteam, defteam, epa, rusher):
        return {"season_type": "REG", "week": str(week), "game_id": f"g{week}", "posteam": posteam, "defteam": defteam, "epa": str(epa), "rusher_player_id": rusher, "rush_attempt": "1"}


class PositionSideTests(InjuryAdjustmentTestCase):
    def test_offense_positions_map_to_offense(self) -> None:
        for code in ("QB", "RB", "WR", "TE", "FB"):
            self.assertEqual(inj.position_side(code), "offense")

    def test_defense_positions_map_to_defense(self) -> None:
        for code in ("DE", "DT", "LB", "CB", "S"):
            self.assertEqual(inj.position_side(code), "defense")

    def test_offensive_line_and_special_teams_map_to_none(self) -> None:
        for code in ("T", "G", "C", "K", "P", "LS"):
            self.assertIsNone(inj.position_side(code))


class OffenseExclusionTests(InjuryAdjustmentTestCase):
    def test_excluding_player_recomputes_real_conditional_average(self) -> None:
        # QB1 threw 20 passes at +0.5 EPA; backup QB2 threw 25 at -0.2 EPA,
        # all before week 5 -- excluding QB1 should land near QB2's rate.
        plays = [self._pass_play(1, "KC", "DEN", 0.5, "QB1") for _ in range(20)]
        plays += [self._pass_play(2, "KC", "DEN", -0.2, "QB2") for _ in range(25)]
        self._write_pbp(2025, plays)

        excluded = inj.team_offense_rating_excluding_player(2025, week=5, team="KC", player_id="QB1")
        self.assertIsNotNone(excluded)
        rating, sample_size = excluded
        self.assertAlmostEqual(rating, -0.2, places=4)
        self.assertEqual(sample_size, 25)

    def test_thin_exclusion_sample_returns_none(self) -> None:
        # Only 5 plays without QB1 -- below MIN_EXCLUSION_SAMPLE (20).
        plays = [self._pass_play(1, "KC", "DEN", 0.5, "QB1") for _ in range(40)]
        plays += [self._pass_play(2, "KC", "DEN", -0.2, "QB2") for _ in range(5)]
        self._write_pbp(2025, plays)

        self.assertIsNone(inj.team_offense_rating_excluding_player(2025, week=5, team="KC", player_id="QB1"))


class OffenseAdjustmentIntegrationTests(InjuryAdjustmentTestCase):
    def test_out_starter_with_real_backup_sample_uses_exclusion_method(self) -> None:
        plays = [self._pass_play(1, "KC", "DEN", 0.5, "QB1") for _ in range(20)]
        plays += [self._pass_play(2, "KC", "DEN", -0.2, "QB2") for _ in range(25)]
        self._write_pbp(2025, plays)
        self._write_injuries(2025, [{"season": "2025", "week": "5", "team": "KC", "gsis_id": "QB1", "position": "QB", "full_name": "Starter QB", "report_status": "Out"}])

        base_rating = 0.4
        adjusted, diagnostics = inj.adjust_team_rating_for_injuries(season=2025, week=5, team="KC", side="offense", base_rating=base_rating)
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0]["method"], "real_team_rate_excluding_player")
        self.assertEqual(diagnostics[0]["player"], "Starter QB")
        self.assertAlmostEqual(adjusted, -0.2, places=4)

    def test_questionable_status_is_not_adjusted(self) -> None:
        plays = [self._pass_play(1, "KC", "DEN", 0.5, "QB1") for _ in range(20)]
        self._write_pbp(2025, plays)
        self._write_injuries(2025, [{"season": "2025", "week": "5", "team": "KC", "gsis_id": "QB1", "position": "QB", "full_name": "Starter QB", "report_status": "Questionable"}])

        adjusted, diagnostics = inj.adjust_team_rating_for_injuries(season=2025, week=5, team="KC", side="offense", base_rating=0.4)
        self.assertEqual(diagnostics, [])
        self.assertEqual(adjusted, 0.4)

    def test_no_real_signal_applies_no_adjustment(self) -> None:
        # QB1 has plays this season (so team-level data isn't totally empty)
        # but no backup ever played (thin exclusion sample) and no real
        # depth-chart backup exists -- must not guess.
        plays = [self._pass_play(1, "KC", "DEN", 0.5, "QB1") for _ in range(40)]
        self._write_pbp(2025, plays)
        self._write_injuries(2025, [{"season": "2025", "week": "5", "team": "KC", "gsis_id": "QB1", "position": "QB", "full_name": "Starter QB", "report_status": "Out"}])
        # No depth chart written at all -- real_depth_chart_backup returns None.

        adjusted, diagnostics = inj.adjust_team_rating_for_injuries(season=2025, week=5, team="KC", side="offense", base_rating=0.4)
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0]["method"], "no_real_substitution_data")
        self.assertEqual(diagnostics[0]["reason"], "no_real_backup_signal")
        self.assertEqual(adjusted, 0.4)

    def test_backup_substitution_uses_real_depth_chart_and_backup_rate(self) -> None:
        # QB1 takes 100% of snaps this season (no in-season exclusion
        # sample at all) -- must fall back to the real depth-chart backup's
        # own real rate. Real-gsis-shaped ids (00-NNNNNNN) since
        # real_depth_chart_backup rejects non-gsis-shaped ids by design.
        starter_id, backup_id = "00-0000001", "00-0000002"
        plays = [self._pass_play(1, "KC", "DEN", 0.5, starter_id) for _ in range(40)]
        # Backup has real prior-season production to draw a rate from.
        plays_prior = [self._pass_play(10, "KC", "DEN", -0.3, backup_id) for _ in range(30)]
        self._write_pbp(2025, plays)
        self._write_pbp(2024, plays_prior)
        self._write_injuries(2025, [{"season": "2025", "week": "5", "team": "KC", "gsis_id": starter_id, "position": "QB", "full_name": "Starter QB", "report_status": "Out"}])
        self._write_depth_chart(2025, [
            {"team": "KC", "player_id": starter_id, "positional_group": "QB", "depth_rank": "1"},
            {"team": "KC", "player_id": backup_id, "positional_group": "QB", "depth_rank": "2"},
        ])

        adjusted, diagnostics = inj.adjust_team_rating_for_injuries(season=2025, week=5, team="KC", side="offense", base_rating=0.5)
        self.assertEqual(len(diagnostics), 1)
        note = diagnostics[0]
        self.assertEqual(note["method"], "real_backup_epa_substitution")
        self.assertEqual(note["backup_player_id"], backup_id)
        # share=1.0 (starter took all plays), backup_rate=-0.3, starter_rate=0.5 -> delta = 1.0 * (-0.3 - 0.5) = -0.8
        self.assertAlmostEqual(note["delta"], -0.8, places=4)
        self.assertAlmostEqual(adjusted, 0.5 - 0.8, places=4)

    def test_synthetic_depth_chart_id_is_skipped(self) -> None:
        plays = [self._pass_play(1, "KC", "DEN", 0.5, "QB1") for _ in range(40)]
        self._write_pbp(2025, plays)
        self._write_injuries(2025, [{"season": "2025", "week": "5", "team": "KC", "gsis_id": "QB1", "position": "QB", "full_name": "Starter QB", "report_status": "Doubtful"}])
        self._write_depth_chart(2025, [
            {"team": "KC", "player_id": "QB1", "positional_group": "QB", "depth_rank": "1"},
            {"team": "KC", "player_id": "SYNTHETIC123", "positional_group": "QB", "depth_rank": "2"},
        ])

        self.assertIsNone(inj.real_depth_chart_backup(2025, "KC", "QB1"))
        adjusted, diagnostics = inj.adjust_team_rating_for_injuries(season=2025, week=5, team="KC", side="offense", base_rating=0.5)
        self.assertEqual(diagnostics[0]["method"], "no_real_substitution_data")
        self.assertEqual(adjusted, 0.5)

    def test_multiple_injured_players_compose_by_addition(self) -> None:
        plays = [self._pass_play(1, "KC", "DEN", 0.5, "QB1") for _ in range(20)]
        plays += [self._pass_play(2, "KC", "DEN", -0.1, "QB2") for _ in range(25)]
        plays += [self._run_play(1, "KC", "DEN", 0.2, "RB1") for _ in range(20)]
        plays += [self._run_play(2, "KC", "DEN", -0.05, "RB2") for _ in range(25)]
        self._write_pbp(2025, plays)
        self._write_injuries(2025, [
            {"season": "2025", "week": "5", "team": "KC", "gsis_id": "QB1", "position": "QB", "full_name": "Starter QB", "report_status": "Out"},
            {"season": "2025", "week": "5", "team": "KC", "gsis_id": "RB1", "position": "RB", "full_name": "Starter RB", "report_status": "Out"},
        ])

        adjusted, diagnostics = inj.adjust_team_rating_for_injuries(season=2025, week=5, team="KC", side="offense", base_rating=1.0)
        self.assertEqual(len(diagnostics), 2)
        expected = 1.0 + sum(d["delta"] for d in diagnostics)
        self.assertAlmostEqual(adjusted, expected, places=4)


class DefenseAdjustmentTests(InjuryAdjustmentTestCase):
    def test_credited_splash_plays_reduce_defense_rating(self) -> None:
        # DEN defense has 100 real defensive plays this season; CB1 is
        # credited with 2 real interceptions worth -1.5 EPA each (i.e. +1.5
        # defensive value each).
        plays = [self._run_play(1, "KC", "DEN", 0.0, "RBX") for _ in range(98)]
        plays += [{"season_type": "REG", "week": "1", "game_id": "g1", "posteam": "KC", "defteam": "DEN", "epa": "-1.5", "interception_player_id": "CB1"} for _ in range(2)]
        self._write_pbp(2025, plays)
        self._write_injuries(2025, [{"season": "2025", "week": "5", "team": "DEN", "gsis_id": "CB1", "position": "CB", "full_name": "Starter CB", "report_status": "Out"}])

        adjusted, diagnostics = inj.adjust_team_rating_for_injuries(season=2025, week=5, team="DEN", side="defense", base_rating=0.1)
        self.assertEqual(len(diagnostics), 1)
        note = diagnostics[0]
        self.assertEqual(note["method"], "real_credited_value_removed")
        self.assertEqual(note["sample_size"], 2)
        # credited value sum = 1.5 + 1.5 = 3.0, team defense play count = 100 -> delta_per_play = 0.03, adjustment = -0.03
        self.assertAlmostEqual(note["delta"], -0.03, places=4)
        self.assertAlmostEqual(adjusted, 0.07, places=4)

    def test_no_credited_plays_applies_no_adjustment(self) -> None:
        plays = [self._run_play(1, "KC", "DEN", 0.0, "RBX") for _ in range(50)]
        self._write_pbp(2025, plays)
        self._write_injuries(2025, [{"season": "2025", "week": "5", "team": "DEN", "gsis_id": "CB1", "position": "CB", "full_name": "Starter CB", "report_status": "Out"}])

        adjusted, diagnostics = inj.adjust_team_rating_for_injuries(season=2025, week=5, team="DEN", side="defense", base_rating=0.1)
        self.assertEqual(diagnostics[0]["method"], "no_real_substitution_data")
        self.assertEqual(diagnostics[0]["reason"], "no_real_credited_plays")
        self.assertEqual(adjusted, 0.1)


class NoInjuriesTests(InjuryAdjustmentTestCase):
    def test_no_injuries_file_returns_unchanged_rating_and_empty_diagnostics(self) -> None:
        self._write_pbp(2025, [self._pass_play(1, "KC", "DEN", 0.5, "QB1")])
        adjusted, diagnostics = inj.adjust_team_rating_for_injuries(season=2025, week=5, team="KC", side="offense", base_rating=0.4)
        self.assertEqual(adjusted, 0.4)
        self.assertEqual(diagnostics, [])


if __name__ == "__main__":
    unittest.main()
