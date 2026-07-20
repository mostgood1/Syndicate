from __future__ import annotations

import unittest

from syndicate.features.soccer.sim_engine.soccersim.calibration import BenchmarkMatchRecord
from syndicate.features.soccer.sim_engine.soccersim.calibration import BenchmarkPossessionRecord
from syndicate.features.soccer.sim_engine.soccersim.calibration import CalibrationBenchmarkSnapshot
from syndicate.features.soccer.sim_engine.soccersim.calibration import CalibrationSplit
from syndicate.features.soccer.sim_engine.soccersim.calibration import evaluate_simulator
from syndicate.features.soccer.sim_engine.soccersim.calibration import generate_calibration_report
from syndicate.features.soccer.sim_engine.soccersim.calibration import summarize_benchmark_snapshot
from syndicate.features.soccer.sim_engine.soccersim.calibration import summarize_simulation_outputs
from syndicate.features.soccer.sim_engine.soccersim.contracts import PossessionOutcome
from syndicate.features.soccer.sim_engine.soccersim.contracts import SoccerSimSimulationInput
from syndicate.features.soccer.sim_engine.soccersim.match_simulator import simulate_match


def _benchmark_snapshot() -> CalibrationBenchmarkSnapshot:
    possession_records = (
        BenchmarkPossessionRecord(
            possession_id="p1",
            match_id="m1",
            attacking_team="ARS",
            defending_team="LIV",
            events=4,
            seconds=40,
            outcome=PossessionOutcome.SHOT_SAVED,
            shot_taken=True,
            shot_on_target=True,
            reached_final_third=True,
        ),
        BenchmarkPossessionRecord(
            possession_id="p2",
            match_id="m1",
            attacking_team="LIV",
            defending_team="ARS",
            events=2,
            seconds=20,
            outcome=PossessionOutcome.TURNOVER,
        ),
        BenchmarkPossessionRecord(
            possession_id="p3",
            match_id="m1",
            attacking_team="ARS",
            defending_team="LIV",
            events=5,
            seconds=55,
            goals=1,
            outcome=PossessionOutcome.GOAL,
            shot_taken=True,
            shot_on_target=True,
            reached_final_third=True,
            reached_penalty_box=True,
        ),
    )
    match_records = (
        BenchmarkMatchRecord(
            match_id="m1",
            home_team="ARS",
            away_team="LIV",
            home_goals=2,
            away_goals=1,
            half_home_goals=(1, 1),
            half_away_goals=(0, 1),
            possessions=150,
            shots=24,
            shots_on_target=9,
            corners=10,
        ),
    )
    return CalibrationBenchmarkSnapshot(
        split=CalibrationSplit.CALIBRATION,
        source_name="unit_test_fixture",
        possession_records=possession_records,
        match_records=match_records,
    )


class SoccerSimCalibrationTests(unittest.TestCase):
    def test_benchmark_summary_combines_possession_and_match_records(self) -> None:
        summary = summarize_benchmark_snapshot(_benchmark_snapshot())

        self.assertAlmostEqual(summary.possession_length_events, (4 + 2 + 5) / 3)
        self.assertAlmostEqual(summary.possessions_per_match, 150.0)
        self.assertAlmostEqual(summary.match_totals, 3.0)
        self.assertAlmostEqual(summary.home_win_rate, 1.0)
        self.assertAlmostEqual(summary.shot_rate, 2 / 3)
        self.assertAlmostEqual(summary.goal_rate, 1 / 3)

    def test_simulated_summary_and_evaluation(self) -> None:
        outputs = [
            simulate_match(SoccerSimSimulationInput(home_team="ARS", away_team="LIV", seed=seed))
            for seed in range(1, 9)
        ]
        simulated_summary = summarize_simulation_outputs(outputs)
        self.assertGreater(simulated_summary.possessions_per_match, 50)
        self.assertGreater(simulated_summary.shot_rate, 0.02)
        self.assertEqual(simulated_summary.sample_size, 8)

        evaluation = evaluate_simulator(_benchmark_snapshot(), outputs)
        self.assertGreaterEqual(evaluation.score, 0.0)
        self.assertLessEqual(evaluation.score, 1.0)
        metric_names = {metric.name for metric in evaluation.metric_results}
        self.assertIn("match_totals", metric_names)
        self.assertIn("possessions_per_match", metric_names)
        self.assertIn("half_1_scoring", metric_names)

    def test_calibration_report_renders_markdown(self) -> None:
        outputs = [
            simulate_match(SoccerSimSimulationInput(home_team="ARS", away_team="LIV", seed=seed))
            for seed in range(1, 4)
        ]
        evaluation = evaluate_simulator(_benchmark_snapshot(), outputs, notes=("unit test",))
        report = generate_calibration_report(evaluation)

        self.assertIn("# SoccerSim Calibration Report", report)
        self.assertIn("| match_totals |", report)
        self.assertIn("unit test", report)


if __name__ == "__main__":
    unittest.main()
