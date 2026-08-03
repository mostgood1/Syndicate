from __future__ import annotations

import csv
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.features.nfl import player_stats


def _play(**overrides) -> dict:
    row = {
        "game_id": "2025_01_KC_DEN", "week": "1", "season_type": "REG",
        "passer_player_id": "", "passer_player_name": "", "passing_yards": "",
        "pass_attempt": "0", "pass_touchdown": "0",
        "rusher_player_id": "", "rusher_player_name": "", "rushing_yards": "",
        "rush_attempt": "0", "rush_touchdown": "0",
        "receiver_player_id": "", "receiver_player_name": "", "receiving_yards": "",
        "complete_pass": "0", "touchdown": "0", "interception": "0",
    }
    row.update(overrides)
    return row


class NflPlayerStatsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.nfl_root = os.path.join(self._tmp.name, "nfl_source")
        self.pbp_dir = os.path.join(self.nfl_root, "tracking", "nflverse", "pbp")
        os.makedirs(self.pbp_dir, exist_ok=True)
        # Patch the resolved root directly rather than the env var --
        # default_nfl_source_root()'s own resolution logic requires a real
        # upcoming_recs_*.csv to prefer an env-provided root over the repo's
        # real data/nfl_source (a fixture dir with only pbp files would be
        # silently skipped in favor of real production data otherwise).
        self._root_patch = patch.object(player_stats, "default_nfl_source_root", return_value=Path(self.nfl_root))
        self._root_patch.start()
        self.addCleanup(self._root_patch.stop)
        player_stats.load_player_plays.cache_clear()
        player_stats.player_name_index.cache_clear()

    def _write_pbp(self, season: int, rows: list[dict]) -> None:
        fieldnames = list(_play().keys())
        with open(os.path.join(self.pbp_dir, f"pbp_{season}.csv"), "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    def test_short_name_from_full(self) -> None:
        self.assertEqual(player_stats.short_name_from_full("Drake Maye"), "D.Maye")
        self.assertEqual(player_stats.short_name_from_full("Kyler Murray"), "K.Murray")
        self.assertEqual(player_stats.short_name_from_full(""), "")

    def test_player_game_log_extracts_all_stats(self) -> None:
        self._write_pbp(2025, [
            _play(game_id="2025_01_KC_DEN", week="1", passer_player_id="QB1", passer_player_name="P.One", passing_yards="20", pass_attempt="1"),
            _play(game_id="2025_01_KC_DEN", week="1", passer_player_id="QB1", passer_player_name="P.One", passing_yards="15", pass_attempt="1", pass_touchdown="1", touchdown="1"),
            _play(game_id="2025_01_KC_DEN", week="1", receiver_player_id="WR1", receiver_player_name="W.One", receiving_yards="15", complete_pass="1"),
            _play(game_id="2025_02_KC_LV", week="2", passer_player_id="QB1", passer_player_name="P.One", passing_yards="30", pass_attempt="1"),
        ])
        log = player_stats.player_game_log(2025, "QB1")
        self.assertEqual(len(log), 2)
        week1 = log[0]
        self.assertEqual(week1["passing_yards"], 35.0)
        self.assertEqual(week1["passing_attempts"], 2.0)
        self.assertEqual(week1["passing_tds"], 1.0)
        # The passer's own passing TD must not count as their anytime_td --
        # only rusher/receiver attribution does.
        self.assertEqual(week1["anytime_td"], 0.0)

    def test_receiving_yards_attributed_to_receiver_only(self) -> None:
        # Regression: receiving_yards had no extractor at all (silently
        # dropped before ever reaching the board) until 2026-08-03.
        self._write_pbp(2025, [
            _play(game_id="2025_01_KC_DEN", week="1", receiver_player_id="WR1", receiver_player_name="W.One", receiving_yards="15", complete_pass="1"),
            _play(game_id="2025_01_KC_DEN", week="1", receiver_player_id="WR1", receiver_player_name="W.One", receiving_yards="30", complete_pass="1"),
            # Passer's own passing yards must never count toward a receiver's total.
            _play(game_id="2025_01_KC_DEN", week="1", passer_player_id="QB1", passer_player_name="P.One", passing_yards="200", pass_attempt="1"),
        ])
        log = player_stats.player_game_log(2025, "WR1")
        self.assertEqual(log[0]["receiving_yards"], 45.0)

    def test_interceptions_attributed_to_passer_only(self) -> None:
        # Regression: interceptions had no extractor at all (silently
        # dropped before ever reaching the board) until 2026-08-03.
        self._write_pbp(2025, [
            _play(game_id="2025_01_KC_DEN", week="1", passer_player_id="QB1", passer_player_name="P.One", passing_yards="10", pass_attempt="1", interception="1"),
            _play(game_id="2025_01_KC_DEN", week="1", passer_player_id="QB1", passer_player_name="P.One", passing_yards="20", pass_attempt="1"),
        ])
        log = player_stats.player_game_log(2025, "QB1")
        self.assertEqual(log[0]["interceptions"], 1.0)

    def test_anytime_td_attributed_to_scorer_only(self) -> None:
        self._write_pbp(2025, [
            _play(game_id="2025_01_KC_DEN", week="1", rusher_player_id="RB1", rusher_player_name="R.One", rushing_yards="5", rush_attempt="1", rush_touchdown="1", touchdown="1"),
        ])
        log = player_stats.player_game_log(2025, "RB1")
        self.assertEqual(log[0]["anytime_td"], 1.0)

    def test_player_rate_requires_at_least_two_games(self) -> None:
        self._write_pbp(2025, [
            _play(game_id="2025_01_KC_DEN", week="1", passer_player_id="QB1", passer_player_name="P.One", passing_yards="200", pass_attempt="1"),
        ])
        mean, stdev, n = player_stats.player_rate(2025, 2, "QB1", "passing_yards")
        self.assertIsNone(mean)
        self.assertEqual(n, 1)

    def test_player_rate_excludes_current_and_later_weeks(self) -> None:
        self._write_pbp(2025, [
            _play(game_id="2025_01_KC_DEN", week="1", passer_player_id="QB1", passer_player_name="P.One", passing_yards="200", pass_attempt="1"),
            _play(game_id="2025_02_KC_LV", week="2", passer_player_id="QB1", passer_player_name="P.One", passing_yards="220", pass_attempt="1"),
            _play(game_id="2025_05_KC_BUF", week="5", passer_player_id="QB1", passer_player_name="P.One", passing_yards="999", pass_attempt="1"),
        ])
        mean, stdev, n = player_stats.player_rate(2025, 3, "QB1", "passing_yards")
        self.assertEqual(n, 2)
        self.assertAlmostEqual(mean, 210.0)

    def test_resolve_player_id_matches_full_name_to_short_name(self) -> None:
        self._write_pbp(2025, [
            _play(game_id="2025_01_KC_DEN", week="1", passer_player_id="00-1234567", passer_player_name="D.Maye", passing_yards="200", pass_attempt="1"),
        ])
        self.assertEqual(player_stats.resolve_player_id(2025, "Drake Maye"), "00-1234567")
        self.assertIsNone(player_stats.resolve_player_id(2025, "Nobody Real"))

    def test_final_stat_value_returns_real_settled_value(self) -> None:
        self._write_pbp(2025, [
            _play(game_id="2025_01_KC_DEN", week="1", passer_player_id="QB1", passer_player_name="P.One", passing_yards="200", pass_attempt="1"),
        ])
        self.assertEqual(player_stats.final_stat_value(2025, "2025_01_KC_DEN", "QB1", "passing_yards"), 200.0)
        self.assertIsNone(player_stats.final_stat_value(2025, "no_such_game", "QB1", "passing_yards"))


if __name__ == "__main__":
    unittest.main()
