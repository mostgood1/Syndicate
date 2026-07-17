from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from syndicate.features.ncaaf.smartsim2_blend import blend_total
from syndicate.features.ncaaf.smartsim2_performance_tracking import GamePerformanceRecord
from syndicate.features.ncaaf.smartsim2_performance_tracking import build_game_performance_record
from syndicate.features.ncaaf.smartsim2_performance_tracking import compute_margin_stats
from syndicate.features.ncaaf.smartsim2_performance_tracking import compute_total_stats
from syndicate.features.ncaaf.smartsim2_performance_tracking import detect_drift
from syndicate.features.ncaaf.smartsim2_performance_tracking import order_records_chronologically
from syndicate.features.ncaaf.smartsim2_performance_tracking import partition_by_total_level
from syndicate.features.ncaaf.smartsim2_performance_tracking import read_performance_log
from syndicate.features.ncaaf.smartsim2_performance_tracking import record_game_performance
from syndicate.features.ncaaf.smartsim2_performance_tracking import rolling_windows
from syndicate.features.ncaaf.smartsim2_performance_tracking import summarize_by_week
from syndicate.features.ncaaf.smartsim2_performance_tracking import summarize_performance
from syndicate.features.ncaaf.smartsim2_performance_tracking import summarize_season_to_date


def _record(**overrides) -> GamePerformanceRecord:
    base = dict(
        game_id="1",
        season=2025,
        week=1,
        home_team="Sam Houston",
        away_team="UNLV",
        conference_game=False,
        market_margin=4.0,
        market_total=55.0,
        engine_margin=4.0,
        engine_total=50.0,
        smartsim_margin=6.0,
        smartsim_total=60.0,
        actual_home_points=30,
        actual_away_points=27,
    )
    base.update(overrides)
    return build_game_performance_record(**base)


class BuildRecordTests(unittest.TestCase):
    def test_agreement_uses_engine_consensus_margin(self) -> None:
        # ATS policy (smartsim_ats_policy_implementation_report.md): engine_margin=4.0,
        # smartsim_margin=6.0 agree in sign -- Engine's margin is used, unblended.
        record = _record()
        self.assertFalse(record.consensus_used_smartsim_margin)
        self.assertEqual(record.consensus_margin, 4.0)
        self.assertAlmostEqual(record.consensus_total, blend_total(50.0, 60.0))
        self.assertEqual(record.actual_margin, 3.0)
        self.assertEqual(record.actual_total, 57.0)

    def test_disagreement_uses_smartsim_consensus_margin(self) -> None:
        record = _record(engine_margin=15.0, smartsim_margin=-2.0)
        self.assertTrue(record.side_disagreement)
        self.assertTrue(record.consensus_used_smartsim_margin)
        self.assertEqual(record.consensus_margin, -2.0)

    def test_large_mismatch_with_agreement_still_uses_engine_margin(self) -> None:
        # large_mismatch is now a pure reporting category -- it no longer
        # drives the consensus margin decision, only side_disagreement does.
        record = _record(market_margin=15.0, engine_margin=15.0, smartsim_margin=2.0)
        self.assertTrue(record.large_mismatch)
        self.assertFalse(record.side_disagreement)
        self.assertFalse(record.consensus_used_smartsim_margin)
        self.assertEqual(record.consensus_margin, 15.0)

    def test_large_mismatch_with_disagreement_uses_smartsim_margin(self) -> None:
        record = _record(market_margin=15.0, engine_margin=15.0, smartsim_margin=-2.0)
        self.assertTrue(record.large_mismatch)
        self.assertTrue(record.side_disagreement)
        self.assertTrue(record.consensus_used_smartsim_margin)
        self.assertEqual(record.consensus_margin, -2.0)

    def test_market_margin_unavailable_still_computes_large_mismatch_via_engine_fallback(self) -> None:
        # market_margin=None falls back to engine_margin for the large_mismatch
        # reporting category only -- unaffected by the ATS policy change.
        record = _record(market_margin=None, engine_margin=15.0, smartsim_margin=2.0)
        self.assertTrue(record.large_mismatch)
        self.assertFalse(record.consensus_used_smartsim_margin)
        self.assertEqual(record.consensus_margin, 15.0)

    def test_side_disagreement_flag(self) -> None:
        agree = _record(engine_margin=4.0, smartsim_margin=6.0)
        disagree = _record(engine_margin=-4.0, smartsim_margin=6.0)
        self.assertFalse(agree.side_disagreement)
        self.assertTrue(disagree.side_disagreement)

    def test_total_disagreement_flag_threshold(self) -> None:
        below = _record(engine_total=50.0, smartsim_total=59.0)
        at = _record(engine_total=50.0, smartsim_total=60.0)
        above = _record(engine_total=50.0, smartsim_total=65.0)
        self.assertFalse(below.total_disagreement)
        self.assertTrue(at.total_disagreement)
        self.assertTrue(above.total_disagreement)


class LogRoundTripTests(unittest.TestCase):
    def test_record_and_read_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "perf.jsonl"
            record = _record()
            record_game_performance(record, log_path=log_path)
            rows = read_performance_log(log_path=log_path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["game_id"], "1")
            self.assertEqual(rows[0]["actual_margin"], 3.0)

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
        rows = [_record(engine_margin=3.0, actual_home_points=30, actual_away_points=27).to_dict()]
        stats = compute_margin_stats(rows, "engine")
        self.assertEqual(stats["mae"], 0.0)
        self.assertEqual(stats["rmse"], 0.0)
        self.assertEqual(stats["side_accuracy"], 1.0)

    def test_margin_stats_none_when_empty(self) -> None:
        self.assertIsNone(compute_margin_stats([], "engine"))

    def test_total_stats_mae_rmse(self) -> None:
        rows = [
            _record(engine_total=50.0, actual_home_points=30, actual_away_points=27).to_dict(),  # error -7
            _record(engine_total=57.0, actual_home_points=30, actual_away_points=27).to_dict(),  # error 0
        ]
        stats = compute_total_stats(rows, "engine")
        self.assertAlmostEqual(stats["mae"], 3.5)
        self.assertAlmostEqual(stats["rmse"], (7.0 ** 2 / 2) ** 0.5, places=3)

    def test_side_accuracy_counts_sign_mismatch(self) -> None:
        correct = _record(engine_margin=3.0, actual_home_points=30, actual_away_points=27).to_dict()
        wrong = _record(engine_margin=-3.0, actual_home_points=30, actual_away_points=27).to_dict()
        stats = compute_margin_stats([correct, wrong], "engine")
        self.assertEqual(stats["side_accuracy"], 0.5)


class SummarizeTests(unittest.TestCase):
    def test_summarize_performance_partitions_by_category(self) -> None:
        agree_small = _record(
            game_id="a", conference_game=False, market_margin=2.0, engine_margin=2.0, smartsim_margin=3.0,
            engine_total=50.0, smartsim_total=54.0,
        ).to_dict()
        mismatch = _record(
            game_id="b", conference_game=True, market_margin=15.0, engine_margin=15.0, smartsim_margin=1.0,
            engine_total=50.0, smartsim_total=65.0,
        ).to_dict()
        summary = summarize_performance([agree_small, mismatch])
        self.assertEqual(summary["n_games"], 2)
        self.assertEqual(summary["large_mismatch"]["n"], 1)
        self.assertEqual(summary["conference_games"]["n"], 1)
        self.assertEqual(summary["non_conference_games"]["n"], 1)
        self.assertEqual(summary["total_disagreement"]["n"], 1)

    def test_summarize_by_week_groups_correctly(self) -> None:
        wk1 = _record(game_id="a", week=1).to_dict()
        wk5 = _record(game_id="b", week=5).to_dict()
        by_week = summarize_by_week([wk1, wk5])
        self.assertEqual(set(by_week), {1, 5})
        self.assertEqual(by_week[1]["n"], 1)
        self.assertEqual(by_week[5]["n"], 1)


class OrderingAndRollingWindowTests(unittest.TestCase):
    def test_order_records_chronologically_sorts_by_week_then_game_id(self) -> None:
        rows = [
            _record(game_id="200", week=1).to_dict(),
            _record(game_id="100", week=1).to_dict(),
            _record(game_id="50", week=2).to_dict(),
        ]
        ordered = order_records_chronologically(rows)
        self.assertEqual([(r["week"], r["game_id"]) for r in ordered], [(1, "100"), (1, "200"), (2, "50")])

    def test_rolling_windows_splits_into_non_overlapping_chunks(self) -> None:
        rows = [_record(game_id=str(i), week=1).to_dict() for i in range(5)]
        windows = rolling_windows(rows, window_size=2)
        self.assertEqual(len(windows), 3)
        self.assertEqual([w["n"] for w in windows], [2, 2, 1])
        self.assertFalse(windows[0]["partial"])
        self.assertTrue(windows[2]["partial"])
        self.assertEqual(windows[0]["start"], 1)
        self.assertEqual(windows[0]["end"], 2)
        self.assertEqual(windows[2]["start"], 5)
        self.assertEqual(windows[2]["end"], 5)

    def test_rolling_windows_empty_input(self) -> None:
        self.assertEqual(rolling_windows([], window_size=50), [])


class SeasonToDateTests(unittest.TestCase):
    def test_checkpoints_include_final_partial_boundary(self) -> None:
        rows = [_record(game_id=str(i), week=1).to_dict() for i in range(120)]
        checkpoints = summarize_season_to_date(rows, checkpoint_size=50)
        self.assertEqual([c["through_game"] for c in checkpoints], [50, 100, 120])
        self.assertEqual(checkpoints[0]["n"], 50)
        self.assertEqual(checkpoints[-1]["n"], 120)

    def test_checkpoints_exact_multiple_has_no_duplicate_final(self) -> None:
        rows = [_record(game_id=str(i), week=1).to_dict() for i in range(100)]
        checkpoints = summarize_season_to_date(rows, checkpoint_size=50)
        self.assertEqual([c["through_game"] for c in checkpoints], [50, 100])

    def test_empty_input_returns_no_checkpoints(self) -> None:
        self.assertEqual(summarize_season_to_date([], checkpoint_size=50), [])


class TotalLevelPartitionTests(unittest.TestCase):
    def test_median_split_high_and_low(self) -> None:
        rows = [
            _record(game_id="1", market_total=40.0).to_dict(),
            _record(game_id="2", market_total=50.0).to_dict(),
            _record(game_id="3", market_total=60.0).to_dict(),
            _record(game_id="4", market_total=70.0).to_dict(),
        ]
        high, low = partition_by_total_level(rows)
        self.assertEqual({r["game_id"] for r in high}, {"3", "4"})
        self.assertEqual({r["game_id"] for r in low}, {"1", "2"})

    def test_ignores_rows_without_market_total(self) -> None:
        rows = [
            _record(game_id="1", market_total=None).to_dict(),
            _record(game_id="2", market_total=50.0).to_dict(),
        ]
        high, low = partition_by_total_level(rows)
        self.assertEqual(len(high) + len(low), 1)

    def test_empty_input(self) -> None:
        self.assertEqual(partition_by_total_level([]), ([], []))


class DriftDetectionTests(unittest.TestCase):
    def test_insufficient_data_does_not_flag(self) -> None:
        result = detect_drift([_record(game_id="1").to_dict()])
        self.assertFalse(result["performance_drift"]["flagged"])
        self.assertFalse(result["calibration_drift"]["flagged"])
        self.assertFalse(result["policy_drift"]["flagged"])

    def test_stable_sample_does_not_flag_performance_drift(self) -> None:
        rows = []
        for i in range(40):
            rows.append(
                _record(
                    game_id=str(i), week=1 + i // 10,
                    engine_margin=4.0, smartsim_margin=6.0, market_margin=4.0,
                    engine_total=50.0, smartsim_total=60.0, market_total=55.0,
                    actual_home_points=30, actual_away_points=27,
                ).to_dict()
            )
        result = detect_drift(rows)
        self.assertFalse(result["performance_drift"]["flagged"])
        self.assertFalse(result["calibration_drift"]["flagged"])

    def test_large_accuracy_swing_flags_performance_drift(self) -> None:
        rows = []
        for i in range(20):
            # First half: engine always correct.
            rows.append(
                _record(
                    game_id=str(i), week=1,
                    engine_margin=5.0, smartsim_margin=5.0, market_margin=5.0,
                    actual_home_points=30, actual_away_points=27,
                ).to_dict()
            )
        for i in range(20, 40):
            # Second half: engine always wrong (flips sign vs actual outcome).
            rows.append(
                _record(
                    game_id=str(i), week=2,
                    engine_margin=-5.0, smartsim_margin=5.0, market_margin=-5.0,
                    actual_home_points=30, actual_away_points=27,
                ).to_dict()
            )
        result = detect_drift(rows)
        self.assertTrue(result["performance_drift"]["flagged"])
        self.assertTrue(any("engine" in detail for detail in result["performance_drift"]["details"]))

    def test_calibration_drift_flagged_when_smartsim_total_bias_shifts(self) -> None:
        rows = []
        for i in range(20):
            rows.append(
                _record(game_id=str(i), week=1, smartsim_total=60.0, actual_home_points=30, actual_away_points=27).to_dict()
            )  # raw bias = 3.0
        for i in range(20, 40):
            rows.append(
                _record(game_id=str(i), week=2, smartsim_total=70.0, actual_home_points=30, actual_away_points=27).to_dict()
            )  # raw bias = 13.0
        result = detect_drift(rows)
        self.assertTrue(result["calibration_drift"]["flagged"])
        self.assertAlmostEqual(result["calibration_drift"]["delta"], 10.0)


if __name__ == "__main__":
    unittest.main()
