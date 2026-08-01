from __future__ import annotations

import csv
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.features.nfl import player_stats
from syndicate.features.nfl import props


class NflPropsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.nfl_root = os.path.join(self._tmp.name, "nfl_source")
        os.makedirs(self.nfl_root, exist_ok=True)
        self._root_patch = patch.object(props, "default_nfl_source_root", return_value=Path(self.nfl_root))
        self._root_patch.start()
        self.addCleanup(self._root_patch.stop)
        # player_stats.resolve_player_id also resolves its own source root
        # (for the pbp file, a separate lookup from the props CSV above) --
        # must be patched too, or these tests would fall through to the
        # real repo's production pbp_2025.csv (slow, non-hermetic).
        self._player_stats_root_patch = patch.object(player_stats, "default_nfl_source_root", return_value=Path(self.nfl_root))
        self._player_stats_root_patch.start()
        self.addCleanup(self._player_stats_root_patch.stop)
        props._nfl_raw_player_props.cache_clear()
        player_stats.load_player_plays.cache_clear()
        player_stats.player_name_index.cache_clear()

    def _write_props(self, season: int, week: int, rows: list[dict]) -> None:
        fieldnames = ["player", "team", "market", "line", "over_price", "under_price", "book", "event", "game_time", "home_team", "away_team", "is_ladder"]
        path = os.path.join(self.nfl_root, f"oddsapi_player_props_{season}_wk{week}.csv")
        with open(path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                full = {key: "" for key in fieldnames}
                full.update(row)
                writer.writerow(full)

    def test_missing_file_returns_empty(self) -> None:
        odds_rows, sim_rows = props.nfl_props_rows_for_week(2025, 5)
        self.assertEqual(odds_rows, [])
        self.assertEqual(sim_rows, [])

    def test_header_only_stub_returns_empty(self) -> None:
        self._write_props(2025, 5, [])
        odds_rows, sim_rows = props.nfl_props_rows_for_week(2025, 5)
        self.assertEqual(odds_rows, [])
        self.assertEqual(sim_rows, [])

    def test_real_line_kept_even_without_resolvable_player_rate(self) -> None:
        # Unknown player -> resolve_player_id returns None -> no sim row,
        # but the real quoted line must still appear as an odds row.
        self._write_props(2025, 5, [
            {"player": "Totally Unknown Guy", "market": "Passing Yards", "line": "230.5", "over_price": "-110", "under_price": "-110", "home_team": "New England Patriots", "away_team": "Seattle Seahawks"},
        ])
        odds_rows, sim_rows = props.nfl_props_rows_for_week(2025, 5)
        self.assertEqual(len(odds_rows), 2)
        self.assertEqual(sim_rows, [])

    def test_anytime_td_is_one_sided(self) -> None:
        self._write_props(2025, 5, [
            {"player": "Some Guy", "market": "Anytime TD", "line": "", "over_price": "250", "under_price": "", "home_team": "New England Patriots", "away_team": "Seattle Seahawks"},
        ])
        odds_rows, _sim_rows = props.nfl_props_rows_for_week(2025, 5)
        self.assertEqual(len(odds_rows), 1)
        self.assertEqual(odds_rows[0]["side"], "over")
        self.assertNotIn("line", odds_rows[0])

    def test_unmapped_market_is_skipped(self) -> None:
        self._write_props(2025, 5, [
            {"player": "Some Guy", "market": "Some Unknown Market", "line": "1.5", "over_price": "-110", "under_price": "-110", "home_team": "New England Patriots", "away_team": "Seattle Seahawks"},
        ])
        odds_rows, sim_rows = props.nfl_props_rows_for_week(2025, 5)
        self.assertEqual(odds_rows, [])
        self.assertEqual(sim_rows, [])

    def test_props_key_matches_away_home_pair(self) -> None:
        self.assertEqual(props.nfl_props_key("Seattle Seahawks", "New England Patriots"), "Seattle Seahawks|New England Patriots")

    def test_available_weeks_excludes_header_only_stubs(self) -> None:
        self._write_props(2025, 5, [])
        self._write_props(2025, 6, [
            {"player": "Some Guy", "market": "Anytime TD", "over_price": "250", "home_team": "A", "away_team": "B"},
        ])
        self.assertEqual(props.nfl_props_available_weeks(2025), [6])

    def test_model_probability_uses_hit_rate_for_anytime_td(self) -> None:
        prob = props._nfl_prop_model_probability(stat="anytime_td", mean=0.4, stdev=None, n=5, line=None)
        self.assertEqual(prob, 0.4)

    def test_model_probability_none_below_two_samples(self) -> None:
        prob = props._nfl_prop_model_probability(stat="passing_yards", mean=250.0, stdev=20.0, n=1, line=230.0)
        self.assertIsNone(prob)


if __name__ == "__main__":
    unittest.main()
