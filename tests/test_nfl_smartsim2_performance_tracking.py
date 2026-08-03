from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from syndicate.features.nfl.smartsim2_performance_tracking import GamePerformanceRecord
from syndicate.features.nfl.smartsim2_performance_tracking import build_game_performance_record
from syndicate.features.nfl.smartsim2_performance_tracking import compute_margin_stats
from syndicate.features.nfl.smartsim2_performance_tracking import compute_total_stats
from syndicate.features.nfl.smartsim2_performance_tracking import read_performance_log
from syndicate.features.nfl.smartsim2_performance_tracking import record_game_performance
from syndicate.features.nfl.smartsim2_performance_tracking import summarize_by_week
from syndicate.features.nfl.smartsim2_performance_tracking import summarize_performance


def _record(**overrides) -> GamePerformanceRecord:
    base = dict(
        game_id="2025_01_NE_SEA",
        season=2025,
        week=1,
        home_team="SEA",
        away_team="NE",
        market_margin=-3.5,
        market_total=44.5,
        model_margin=0.3,
        model_total=43.9,
        actual_home_points=24,
        actual_away_points=20,
    )
    base.update(overrides)
    return build_game_performance_record(**base)


class BuildRecordTests(unittest.TestCase):
    def test_actual_margin_and_total_computed_from_scores(self) -> None:
        record = _record(actual_home_points=24, actual_away_points=20)
        self.assertEqual(record.actual_margin, 4.0)
        self.assertEqual(record.actual_total, 44.0)

    def test_model_picked_winner_true_when_signs_match(self) -> None:
        record = _record(model_margin=3.0, actual_home_points=24, actual_away_points=20)
        self.assertTrue(record.model_picked_winner)

    def test_model_picked_winner_false_when_signs_differ(self) -> None:
        record = _record(model_margin=-3.0, actual_home_points=24, actual_away_points=20)
        self.assertFalse(record.model_picked_winner)

    def test_large_mismatch_flag_uses_market_margin(self) -> None:
        below = _record(market_margin=13.0)
        at = _record(market_margin=14.0)
        above = _record(market_margin=20.0)
        self.assertFalse(below.large_mismatch)
        self.assertTrue(at.large_mismatch)
        self.assertTrue(above.large_mismatch)

    def test_large_mismatch_falls_back_to_model_margin_when_market_missing(self) -> None:
        record = _record(market_margin=None, model_margin=20.0)
        self.assertTrue(record.large_mismatch)
        self.assertIsNone(record.market_margin)


class LogRoundTripTests(unittest.TestCase):
    def test_record_and_read_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "perf.jsonl"
            record = _record()
            record_game_performance(record, log_path=log_path)
            rows = read_performance_log(log_path=log_path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["game_id"], "2025_01_NE_SEA")
            self.assertEqual(rows[0]["actual_margin"], 4.0)

    def test_read_missing_log_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "missing.jsonl"
            self.assertEqual(read_performance_log(log_path=log_path), [])

    def test_recording_never_raises_when_path_unwritable(self) -> None:
        bogus_path = Path("Z:\\definitely\\does\\not\\exist\\perf.jsonl")
        record_game_performance(_record(), log_path=bogus_path)  # must not raise

    def test_log_ignores_malformed_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "perf.jsonl"
            log_path.write_text("not json\n" + json.dumps(_record().to_dict()) + "\n", encoding="utf-8")
            rows = read_performance_log(log_path=log_path)
            self.assertEqual(len(rows), 1)


class StatsTests(unittest.TestCase):
    def test_margin_stats_perfect_prediction(self) -> None:
        rows = [_record(model_margin=4.0, actual_home_points=24, actual_away_points=20).to_dict()]
        stats = compute_margin_stats(rows)
        self.assertEqual(stats["mae"], 0.0)
        self.assertEqual(stats["rmse"], 0.0)
        self.assertEqual(stats["side_accuracy"], 1.0)

    def test_margin_stats_none_when_empty(self) -> None:
        self.assertIsNone(compute_margin_stats([]))

    def test_total_stats_mae_rmse(self) -> None:
        rows = [
            _record(model_total=37.0, actual_home_points=24, actual_away_points=20).to_dict(),  # error -7
            _record(model_total=44.0, actual_home_points=24, actual_away_points=20).to_dict(),  # error 0
        ]
        stats = compute_total_stats(rows)
        self.assertAlmostEqual(stats["mae"], 3.5)
        self.assertAlmostEqual(stats["rmse"], (7.0 ** 2 / 2) ** 0.5, places=3)

    def test_side_accuracy_counts_sign_mismatch(self) -> None:
        correct = _record(model_margin=3.0, actual_home_points=24, actual_away_points=20).to_dict()
        wrong = _record(model_margin=-3.0, actual_home_points=24, actual_away_points=20).to_dict()
        stats = compute_margin_stats([correct, wrong])
        self.assertEqual(stats["side_accuracy"], 0.5)


class SummarizeTests(unittest.TestCase):
    def test_summarize_performance_partitions_by_large_mismatch(self) -> None:
        agree_small = _record(game_id="a", market_margin=2.0).to_dict()
        mismatch = _record(game_id="b", market_margin=20.0).to_dict()
        summary = summarize_performance([agree_small, mismatch])
        self.assertEqual(summary["n_games"], 2)
        self.assertEqual(summary["large_mismatch"]["n"], 1)
        self.assertEqual(summary["overall"]["n"], 2)

    def test_summarize_by_week_groups_correctly(self) -> None:
        wk1 = _record(game_id="a", week=1).to_dict()
        wk5 = _record(game_id="b", week=5).to_dict()
        by_week = summarize_by_week([wk1, wk5])
        self.assertEqual(set(by_week), {1, 5})
        self.assertEqual(by_week[1]["n"], 1)
        self.assertEqual(by_week[5]["n"], 1)


if __name__ == "__main__":
    unittest.main()
