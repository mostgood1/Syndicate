from __future__ import annotations

import csv
from pathlib import Path
import tempfile
import unittest

from syndicate.features.football.sim_engine.smartsim2 import BenchmarkDriveRecord
from syndicate.features.football.sim_engine.smartsim2 import BenchmarkGameRecord
from syndicate.features.football.sim_engine.smartsim2 import generate_baseline_audit_report
from syndicate.features.football.sim_engine.smartsim2 import CalibrationBenchmarkSnapshot
from syndicate.features.football.sim_engine.smartsim2 import CalibrationSplit
from syndicate.features.football.sim_engine.smartsim2 import generate_calibration_report
from syndicate.features.football.sim_engine.smartsim2 import load_baseline_audit_result
from syndicate.features.football.sim_engine.smartsim2 import evaluate_simulator
from syndicate.features.football.sim_engine.smartsim2.calibration.evaluation_metrics import summarize_drive_outcome_frequencies
from syndicate.features.football.sim_engine.smartsim2.calibration.evaluation_metrics import summarize_simulated_drive_outcome_frequencies
from syndicate.features.football.sim_engine.smartsim2.contracts import PossessionOutcome
from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationOutput


class SmartSim2CalibrationTests(unittest.TestCase):
    def test_evaluate_simulator_builds_core_metric_bundle(self) -> None:
        benchmark_snapshot = CalibrationBenchmarkSnapshot(
            split=CalibrationSplit.VALIDATION,
            source_name="test-benchmark",
            drive_records=(
                BenchmarkDriveRecord(
                    drive_id="g1-d1",
                    game_id="g1",
                    offense_team="PHI",
                    defense_team="DAL",
                    plays=6,
                    seconds=180,
                    yards=55,
                    points=7,
                    outcome=PossessionOutcome.TOUCHDOWN,
                    red_zone_entry=True,
                    touchdown=True,
                ),
                BenchmarkDriveRecord(
                    drive_id="g1-d2",
                    game_id="g1",
                    offense_team="DAL",
                    defense_team="PHI",
                    plays=4,
                    seconds=120,
                    yards=22,
                    points=3,
                    outcome=PossessionOutcome.FIELD_GOAL,
                    red_zone_entry=True,
                    field_goal_attempt=True,
                ),
            ),
            game_records=(
                BenchmarkGameRecord(
                    game_id="g1",
                    home_team="PHI",
                    away_team="DAL",
                    home_points=24,
                    away_points=20,
                    quarter_home_points=(7, 3, 7, 7),
                    quarter_away_points=(3, 7, 3, 7),
                    possessions=12,
                    drives=12,
                ),
            ),
        )
        simulation_output = SmartSim2SimulationOutput(
            simulation_kind="smartsim2_possession",
            seed=7,
            input_state={},
            possession_log=(),
            drive_log=(
                {
                    "play_count": 5,
                    "clock_consumed": 165,
                    "yards_gained": 48,
                    "outcome": "touchdown",
                    "points_scored": 7,
                },
                {
                    "play_count": 7,
                    "clock_consumed": 210,
                    "yards_gained": 31,
                    "outcome": "field_goal",
                    "points_scored": 3,
                },
            ),
            quarter_log=(
                {"quarter": 1, "home_points": 7, "away_points": 3},
                {"quarter": 2, "home_points": 3, "away_points": 7},
                {"quarter": 3, "home_points": 7, "away_points": 3},
                {"quarter": 4, "home_points": 7, "away_points": 7},
            ),
            final_score={"home": 24, "away": 20},
            win_probability={"home": 1.0, "away": 0.0},
            spread={"home": 4.0, "away": -4.0},
            total={"value": 44.0},
            distribution_summary={},
            compatibility_summary={},
            final_state={},
        )

        evaluation = evaluate_simulator(benchmark_snapshot, [simulation_output])

        metric_names = {metric.name for metric in evaluation.metric_results}
        self.assertIn("drive_length_plays", metric_names)
        self.assertIn("possessions_per_game", metric_names)
        self.assertIn("touchdown_rate", metric_names)
        self.assertIn("quarter_1_scoring", metric_names)
        self.assertGreaterEqual(evaluation.score, 0.0)
        self.assertLessEqual(evaluation.score, 1.0)

    def test_generate_calibration_report_includes_metric_table(self) -> None:
        benchmark_snapshot = CalibrationBenchmarkSnapshot(
            split=CalibrationSplit.CALIBRATION,
            source_name="test-benchmark",
        )
        simulation_output = SmartSim2SimulationOutput(
            simulation_kind="smartsim2_possession",
            seed=7,
            input_state={},
            possession_log=(),
            drive_log=(),
            quarter_log=(),
            final_score={"home": 0, "away": 0},
            win_probability={"home": 0.5, "away": 0.5},
            spread={"home": 0.0, "away": 0.0},
            total={"value": 0.0},
            distribution_summary={},
            compatibility_summary={},
            final_state={},
        )
        evaluation = evaluate_simulator(benchmark_snapshot, [simulation_output], notes=("smoke-test",))

        report = generate_calibration_report(evaluation)

        self.assertIn("SmartSim 2.0 Calibration Report", report)
        self.assertIn("Target Metrics", report)
        self.assertIn("drive_length_plays", report)
        self.assertIn("smoke-test", report)

    def test_baseline_audit_loader_and_report_use_proxy_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            data_root = temp_dir / "data"
            data_root.mkdir(parents=True, exist_ok=True)

            def write_csv(relative_name: str, header: list[str], rows: list[dict[str, object]]) -> None:
                path = data_root / relative_name
                with path.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=header)
                    writer.writeheader()
                    writer.writerows(rows)

            write_csv(
                "pfr_drive_stats.csv",
                ["season", "week", "team", "drives", "points_per_drive", "td_per_drive", "fg_per_drive", "avg_start_fp", "yards_per_drive", "seconds_per_drive"],
                [
                    {"season": 2025, "week": 1, "team": "PHI", "drives": 10, "points_per_drive": 2.4, "td_per_drive": 0.2, "fg_per_drive": 0.2, "avg_start_fp": 48.0, "yards_per_drive": 36.0, "seconds_per_drive": 180.0},
                    {"season": 2025, "week": 1, "team": "DAL", "drives": 9, "points_per_drive": 2.0, "td_per_drive": 0.1, "fg_per_drive": 0.2, "avg_start_fp": 46.0, "yards_per_drive": 31.0, "seconds_per_drive": 175.0},
                ],
            )
            write_csv(
                "special_teams.csv",
                ["season", "week", "team", "fg_acc", "punt_epa", "kick_return_epa", "touchback_rate"],
                [
                    {"season": 2025, "week": 1, "team": "PHI", "fg_acc": 0.9, "punt_epa": 0.1, "kick_return_epa": 0.0, "touchback_rate": 0.2},
                    {"season": 2025, "week": 1, "team": "DAL", "fg_acc": 0.8, "punt_epa": 0.0, "kick_return_epa": 0.0, "touchback_rate": 0.1},
                ],
            )
            write_csv(
                "redzone_splits.csv",
                ["season", "week", "team", "rzd_off_td_rate", "rzd_off_eff", "rzd_def_td_rate", "rzd_def_eff"],
                [
                    {"season": 2025, "week": 1, "team": "PHI", "rzd_off_td_rate": 0.5, "rzd_off_eff": 0.7, "rzd_def_td_rate": 0.3, "rzd_def_eff": 0.5},
                    {"season": 2025, "week": 1, "team": "DAL", "rzd_off_td_rate": 0.4, "rzd_off_eff": 0.6, "rzd_def_td_rate": 0.2, "rzd_def_eff": 0.4},
                ],
            )
            write_csv(
                "penalties_stats.csv",
                ["season", "week", "team", "penalty_rate", "turnover_adj_rate"],
                [
                    {"season": 2025, "week": 1, "team": "PHI", "penalty_rate": 0.08, "turnover_adj_rate": 0.02},
                    {"season": 2025, "week": 1, "team": "DAL", "penalty_rate": 0.09, "turnover_adj_rate": 0.01},
                ],
            )
            write_csv(
                "team_stats.csv",
                ["season", "week", "team", "off_epa", "def_epa", "pace_secs_play", "pass_rate", "rush_rate", "off_sack_rate", "def_sack_rate", "off_rz_pass_rate", "def_rz_pass_rate", "qb_adj", "sos"],
                [
                    {"season": 2025, "week": 1, "team": "Philadelphia Eagles", "off_epa": 0.12, "def_epa": 0.03, "pace_secs_play": 23.5, "pass_rate": 0.62, "rush_rate": 0.38, "off_sack_rate": 0.04, "def_sack_rate": 0.05, "off_rz_pass_rate": 0.52, "def_rz_pass_rate": 0.48, "qb_adj": 0.05, "sos": 0.1},
                    {"season": 2025, "week": 1, "team": "Dallas Cowboys", "off_epa": 0.04, "def_epa": 0.07, "pace_secs_play": 24.1, "pass_rate": 0.58, "rush_rate": 0.42, "off_sack_rate": 0.03, "def_sack_rate": 0.04, "off_rz_pass_rate": 0.49, "def_rz_pass_rate": 0.51, "qb_adj": -0.02, "sos": 0.2},
                ],
            )

            game_path = data_root / "games_details.csv"
            with game_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "season",
                        "week",
                        "game_id",
                        "home_team",
                        "away_team",
                        "home_score",
                        "away_score",
                        "home_q1",
                        "home_q2",
                        "home_q3",
                        "home_q4",
                        "away_q1",
                        "away_q2",
                        "away_q3",
                        "away_q4",
                        "home_off_epa",
                        "home_def_epa",
                        "away_off_epa",
                        "away_def_epa",
                        "home_pace_secs_play",
                        "away_pace_secs_play",
                        "market_total",
                        "market_spread_home",
                        "margin_actual",
                        "total_actual",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "season": 2025,
                        "week": 1,
                        "game_id": "2025_01_PHI_DAL",
                        "home_team": "Philadelphia Eagles",
                        "away_team": "Dallas Cowboys",
                        "home_score": 24,
                        "away_score": 20,
                        "home_q1": 7,
                        "home_q2": 3,
                        "home_q3": 7,
                        "home_q4": 7,
                        "away_q1": 3,
                        "away_q2": 7,
                        "away_q3": 3,
                        "away_q4": 7,
                        "home_off_epa": 0.12,
                        "home_def_epa": 0.03,
                        "away_off_epa": 0.04,
                        "away_def_epa": 0.07,
                        "home_pace_secs_play": 23.5,
                        "away_pace_secs_play": 24.1,
                        "market_total": 44.5,
                        "market_spread_home": -3.5,
                        "margin_actual": 4,
                        "total_actual": 44,
                    }
                )

            result = load_baseline_audit_result(data_root=data_root, game_detail_paths=(game_path,))
            report = generate_baseline_audit_report(result, top_n=3)

            self.assertEqual(result.evaluation.benchmark_snapshot.split, CalibrationSplit.CALIBRATION)
            self.assertEqual(len(result.evaluation.benchmark_snapshot.game_records), 1)
            self.assertGreater(len(result.evaluation.benchmark_snapshot.drive_records), 0)
            self.assertIn("proxy benchmark", report.lower())
            self.assertIn("Largest Gaps", report)
            self.assertIn("Critical", report)

    def test_drive_outcome_frequencies_include_missed_field_goals(self) -> None:
        benchmark_snapshot = CalibrationBenchmarkSnapshot(
            split=CalibrationSplit.CALIBRATION,
            source_name="drive-outcome-test",
            drive_records=(
                BenchmarkDriveRecord(drive_id="d1", game_id="g1", offense_team="PHI", defense_team="DAL", outcome=PossessionOutcome.PUNT, punt=True),
                BenchmarkDriveRecord(drive_id="d2", game_id="g1", offense_team="DAL", defense_team="PHI", outcome=PossessionOutcome.MISSED_FIELD_GOAL),
                BenchmarkDriveRecord(drive_id="d3", game_id="g1", offense_team="PHI", defense_team="DAL", outcome=PossessionOutcome.TURNOVER, turnover=True),
            ),
        )
        output = SmartSim2SimulationOutput(
            simulation_kind="smartsim2_possession",
            seed=1,
            input_state={},
            possession_log=(),
            drive_log=(
                {"outcome": "punt", "play_count": 4, "clock_consumed": 120, "yards_gained": 35, "points_scored": 0},
                {"outcome": "missed_field_goal", "play_count": 5, "clock_consumed": 90, "yards_gained": 0, "points_scored": 0},
                {"outcome": "turnover", "play_count": 3, "clock_consumed": 60, "yards_gained": -6, "points_scored": 0},
            ),
            quarter_log=(),
            final_score={"home": 0, "away": 0},
            win_probability={"home": 0.5, "away": 0.5},
            spread={"home": 0.0, "away": 0.0},
            total={"value": 0.0},
            distribution_summary={},
            compatibility_summary={},
            final_state={},
        )

        benchmark_freq = summarize_drive_outcome_frequencies(benchmark_snapshot.drive_records)
        simulated_freq = summarize_simulated_drive_outcome_frequencies([output])

        self.assertGreater(benchmark_freq["punt"], 0.0)
        self.assertGreater(benchmark_freq["missed_field_goal"], 0.0)
        self.assertEqual(simulated_freq["missed_field_goal"], 1 / 3)


if __name__ == "__main__":
    unittest.main()
