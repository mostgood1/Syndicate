from __future__ import annotations

import csv
import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from syndicate.features.nfl import player_stats
from syndicate.features.nfl import props as nfl_props

import backtest_nfl_props as bt


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


class PureHelpersTests(unittest.TestCase):
    def test_mae_zero_for_perfect_predictions(self) -> None:
        self.assertEqual(bt.mae([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]), 0.0)

    def test_mae_matches_hand_computation(self) -> None:
        # |1-2| + |5-3| = 1 + 2 = 3, mean = 1.5
        self.assertEqual(bt.mae([1.0, 5.0], [2.0, 3.0]), 1.5)

    def test_corr_none_below_three_points(self) -> None:
        self.assertIsNone(bt.corr([1.0, 2.0], [1.0, 2.0]))

    def test_corr_perfect_positive(self) -> None:
        self.assertEqual(bt.corr([1.0, 2.0, 3.0], [2.0, 4.0, 6.0]), 1.0)

    def test_corr_zero_variance_is_none(self) -> None:
        # dx == 0 (constant predictions) must not raise a ZeroDivisionError.
        self.assertIsNone(bt.corr([5.0, 5.0, 5.0], [1.0, 2.0, 3.0]))

    def test_brier_zero_for_perfect_calls(self) -> None:
        self.assertEqual(bt.brier([1.0, 0.0], [1, 0]), 0.0)

    def test_brier_matches_hand_computation(self) -> None:
        # (0.8-1)^2 + (0.3-0)^2 = 0.04 + 0.09 = 0.13, mean 0.065
        self.assertEqual(bt.brier([0.8, 0.3], [1, 0]), 0.065)


class MarketGateTests(unittest.TestCase):
    """_market_rows implements the "exclude players with no real
    engagement in that stat" honesty rule -- tested in isolation from any
    file I/O."""

    def test_zero_mean_excluded_for_yardage_stat(self) -> None:
        rows = [
            {"stat": "passing_yards", "pred_mean": 0.0, "actual": 0.0},
            {"stat": "passing_yards", "pred_mean": 210.5, "actual": 190.0},
        ]
        kept, excluded = bt._market_rows(rows, "passing_yards")
        self.assertEqual(len(kept), 1)
        self.assertEqual(excluded, 1)
        self.assertEqual(kept[0]["pred_mean"], 210.5)

    def test_anytime_td_zero_mean_not_excluded(self) -> None:
        # A real TE with zero prior TDs is still a legitimate anytime_td
        # candidate -- the whole point of the market is "will they score",
        # and a genuine zero rate is part of that prediction, not a sign
        # of an off-market player.
        rows = [{"stat": "anytime_td", "pred_mean": 0.0, "actual": 0.0}]
        kept, excluded = bt._market_rows(rows, "anytime_td")
        self.assertEqual(len(kept), 1)
        self.assertEqual(excluded, 0)

    def test_other_markets_untouched(self) -> None:
        rows = [
            {"stat": "passing_yards", "pred_mean": 210.5, "actual": 190.0},
            {"stat": "receptions", "pred_mean": 4.0, "actual": 5.0},
        ]
        kept, _ = bt._market_rows(rows, "receptions")
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["stat"], "receptions")


class CollectRawIntegrationTests(unittest.TestCase):
    """End-to-end through the real player_stats module against a tiny
    synthetic season -- same fixture shape as tests/test_nfl_player_stats.py."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.nfl_root = os.path.join(self._tmp.name, "nfl_source")
        self.pbp_dir = os.path.join(self.nfl_root, "tracking", "nflverse", "pbp")
        os.makedirs(self.pbp_dir, exist_ok=True)
        self._root_patch = patch.object(player_stats, "default_nfl_source_root", return_value=Path(self.nfl_root))
        self._root_patch.start()
        self.addCleanup(self._root_patch.stop)
        self._props_root_patch = patch.object(nfl_props, "default_nfl_source_root", return_value=Path(self.nfl_root))
        self._props_root_patch.start()
        self.addCleanup(self._props_root_patch.stop)
        player_stats.load_player_plays.cache_clear()
        player_stats.player_name_index.cache_clear()
        nfl_props._nfl_raw_player_props.cache_clear()

    def _write_pbp(self, season: int, rows: list[dict]) -> None:
        fieldnames = list(_play().keys())
        with open(os.path.join(self.pbp_dir, f"pbp_{season}.csv"), "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

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

    def test_collect_raw_needs_two_prior_games_before_a_rate_exists(self) -> None:
        # Weeks 1 and 2 have no prior games (n<2) -> excluded. Week 3
        # onward has a resolvable rate for every stat the player touched.
        self._write_pbp(2025, [
            _play(game_id="g1", week="1", passer_player_id="QB1", passer_player_name="P.One", passing_yards="200", pass_attempt="1"),
            _play(game_id="g2", week="2", passer_player_id="QB1", passer_player_name="P.One", passing_yards="220", pass_attempt="1"),
            _play(game_id="g3", week="3", passer_player_id="QB1", passer_player_name="P.One", passing_yards="240", pass_attempt="1"),
        ])
        raw_rows, coverage = bt.collect_raw([2025])
        weeks_with_a_row = {row["week"] for row in raw_rows if row["player_id"] == "QB1" and row["stat"] == "passing_yards"}
        self.assertEqual(weeks_with_a_row, {3})
        self.assertEqual(coverage["player_game_weeks"], 3)
        row3 = next(r for r in raw_rows if r["player_id"] == "QB1" and r["stat"] == "passing_yards" and r["week"] == 3)
        self.assertEqual(row3["pred_mean"], 210.0)  # mean of weeks 1,2
        self.assertEqual(row3["actual"], 240.0)

    def test_non_qb_gets_a_zero_passing_rate_row_ungated(self) -> None:
        # A pure receiver has a structural zero passing history. collect_raw
        # is UNGATED (gate 2 applies only inside _market_rows), so this row
        # exists with pred_mean == 0.0 -- excluded later, not here.
        self._write_pbp(2025, [
            _play(game_id="g1", week="1", receiver_player_id="WR1", receiver_player_name="W.One", receiving_yards="50", complete_pass="1"),
            _play(game_id="g2", week="2", receiver_player_id="WR1", receiver_player_name="W.One", receiving_yards="60", complete_pass="1"),
            _play(game_id="g3", week="3", receiver_player_id="WR1", receiver_player_name="W.One", receiving_yards="70", complete_pass="1"),
        ])
        raw_rows, _ = bt.collect_raw([2025])
        passing_row = next(r for r in raw_rows if r["player_id"] == "WR1" and r["stat"] == "passing_yards" and r["week"] == 3)
        self.assertEqual(passing_row["pred_mean"], 0.0)
        kept, excluded = bt._market_rows(raw_rows, "passing_yards")
        self.assertEqual(excluded, 1)
        self.assertEqual(len(kept), 0)

    def test_real_market_hit_rate_scores_a_resolvable_line(self) -> None:
        self._write_pbp(2025, [
            _play(game_id="g1", week="1", receiver_player_id="WR1", receiver_player_name="W.One", receiving_yards="40", complete_pass="1"),
            _play(game_id="g2", week="2", receiver_player_id="WR1", receiver_player_name="W.One", receiving_yards="60", complete_pass="1"),
            _play(game_id="g3", week="3", receiver_player_id="WR1", receiver_player_name="W.One", receiving_yards="80", complete_pass="1"),
        ])
        # Prior-week (1,2) mean = 50.0, stdev = 10.0. A line at 40.5 is
        # well below the mean -> model should call "over", and the real
        # week-3 outcome (80) is over -> a hit.
        self._write_props(2025, 3, [
            {"player": "W. One", "market": "Receiving Yards", "line": "40.5", "over_price": "-115", "under_price": "-105", "home_team": "New England Patriots", "away_team": "Seattle Seahawks"},
        ])
        raw_rows, _ = bt.collect_raw([2025])
        with patch.object(player_stats, "resolve_player_id", return_value="WR1"):
            report = bt.real_market_hit_rate_report(raw_rows, [2025], min_games=1)
        self.assertIn("receiving_yards", report["markets"])
        self.assertEqual(report["markets"]["receiving_yards"]["n"], 1)
        self.assertEqual(report["markets"]["receiving_yards"]["hit_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()
