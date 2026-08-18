"""Tests for projection_score -- Phase 7's scoring layer (`#440` Part 4).

The properties under test are the HONESTY rules, not the arithmetic (that
lives in model_scoring and is tested there): a thin cell must refuse to print a
number, every statistic must carry its n, the model must never be reported
without its baseline, and the PMF must win over any supplied summary.
"""

from __future__ import annotations

import math
import unittest

from syndicate.features.shared.model_scoring import EXPECTED_DISPERSION_RATIO
from syndicate.features.shared.projection_score import (
    ProjectionObservation,
    score_cell,
    score_projections,
)


def observation(actual: float, **kwargs) -> ProjectionObservation:
    kwargs.setdefault("sport", "mlb")
    kwargs.setdefault("market", "strikeouts")
    return ProjectionObservation(actual=actual, **kwargs)


class UnmeasuredFloorTests(unittest.TestCase):
    def test_a_thin_cell_refuses_to_print_any_statistic(self) -> None:
        cell = score_cell([observation(5.0, mean=4.0, sigma=2.0)], min_sample=30)
        self.assertEqual(cell["verdict"], "unmeasured")
        self.assertEqual(cell["sample_size"], 1)
        for key in (
            "crps_empirical",
            "crps_normal_approx",
            "mean_signed_error",
            "mean_absolute_error",
            "dispersion_ratio",
            "baseline_constant_mae",
            "beats_constant_baseline",
        ):
            self.assertIsNone(cell[key], f"{key} leaked a number from an unmeasured cell")

    def test_the_floor_is_inclusive_and_the_cell_flips_at_it(self) -> None:
        below = score_cell([observation(1.0, mean=1.0, sigma=1.0)] * 29, min_sample=30)
        at = score_cell([observation(1.0, mean=1.0, sigma=1.0)] * 30, min_sample=30)
        self.assertEqual(below["verdict"], "unmeasured")
        self.assertEqual(at["verdict"], "measured")
        self.assertIsNotNone(at["mean_absolute_error"])

    def test_sample_size_is_reported_even_when_unmeasured(self) -> None:
        cell = score_cell([observation(1.0, mean=1.0, sigma=1.0)] * 7, min_sample=30)
        self.assertEqual(cell["sample_size"], 7)
        self.assertEqual(cell["min_sample"], 30)


class DistributionWinsTests(unittest.TestCase):
    def test_pmf_overrides_a_disagreeing_supplied_mean(self) -> None:
        # The PMF says mean 2.0; the caller wrongly supplies 99.0.
        obs = observation(2.0, distribution={1: 250, 2: 500, 3: 250}, mean=99.0, sigma=99.0)
        mean, sigma, draws = obs.resolved()
        self.assertAlmostEqual(mean, 2.0, places=9)
        self.assertAlmostEqual(sigma, math.sqrt(0.5), places=9)
        self.assertEqual(draws, 1000)

    def test_falls_back_to_supplied_summary_when_there_is_no_pmf(self) -> None:
        mean, sigma, draws = observation(2.0, mean=3.0, sigma=1.5).resolved()
        self.assertEqual((mean, sigma, draws), (3.0, 1.5, 0))

    def test_empirical_crps_is_produced_only_where_a_pmf_exists(self) -> None:
        with_pmf = [observation(2.0, distribution={1: 500, 3: 500}) for _ in range(30)]
        without = [observation(2.0, mean=2.0, sigma=1.0) for _ in range(30)]
        self.assertIsNotNone(score_cell(with_pmf)["crps_empirical"])
        self.assertEqual(score_cell(with_pmf)["crps_empirical_n"], 30)
        self.assertIsNone(score_cell(without)["crps_empirical"])
        self.assertEqual(score_cell(without)["crps_empirical_n"], 0)
        # ...but the Normal approximation is still available on both.
        self.assertIsNotNone(score_cell(without)["crps_normal_approx"])

    def test_reports_the_gap_between_the_normal_summary_and_the_real_pmf(self) -> None:
        # A deliberately skewed, bounded-at-zero PMF -- the shape the Normal
        # mismatches. The gap must be non-zero and reported.
        skewed = {0: 600, 1: 250, 2: 100, 3: 30, 8: 20}
        cell = score_cell([observation(1.0, distribution=skewed) for _ in range(40)])
        self.assertIsNotNone(cell["normal_minus_empirical"])
        self.assertNotAlmostEqual(cell["normal_minus_empirical"], 0.0, places=3)


class BaselineTests(unittest.TestCase):
    def test_a_model_that_only_predicts_the_pool_mean_does_not_beat_the_baseline(self) -> None:
        actuals = [1.0, 2.0, 3.0, 4.0, 5.0] * 8
        pool_mean = sum(actuals) / len(actuals)
        cell = score_cell([observation(a, mean=pool_mean, sigma=1.0) for a in actuals])
        self.assertEqual(cell["verdict"], "measured")
        self.assertFalse(cell["beats_constant_baseline"])
        self.assertAlmostEqual(cell["mean_absolute_error"], cell["baseline_constant_mae"], places=3)

    def test_a_perfect_model_beats_the_baseline(self) -> None:
        actuals = [1.0, 2.0, 3.0, 4.0, 5.0] * 8
        cell = score_cell([observation(a, mean=a, sigma=1.0) for a in actuals])
        self.assertTrue(cell["beats_constant_baseline"])
        self.assertAlmostEqual(cell["mean_absolute_error"], 0.0, places=9)
        self.assertGreater(cell["baseline_constant_mae"], 0.0)


class DispersionVerdictTests(unittest.TestCase):
    def test_names_an_overconfident_sigma(self) -> None:
        # Errors of 2.0 against a claimed sigma of 0.1 -- wildly too narrow.
        cell = score_cell([observation(3.0, mean=1.0, sigma=0.1) for _ in range(40)])
        self.assertEqual(cell["dispersion_verdict"], "sigma_too_narrow")

    def test_names_an_underconfident_sigma(self) -> None:
        cell = score_cell([observation(1.05, mean=1.0, sigma=50.0) for _ in range(40)])
        self.assertEqual(cell["dispersion_verdict"], "sigma_too_wide")

    def test_names_a_calibrated_sigma(self) -> None:
        # |error|/sigma == E|Z| for a correctly scaled Normal.
        error = EXPECTED_DISPERSION_RATIO
        cell = score_cell([observation(1.0 + error, mean=1.0, sigma=1.0) for _ in range(40)])
        self.assertEqual(cell["dispersion_verdict"], "sigma_calibrated")

    def test_bias_and_dispersion_are_separable(self) -> None:
        # Centred wrong by exactly +2.0 every time, with a fine sigma.
        cell = score_cell([observation(5.0, mean=3.0, sigma=2.5) for _ in range(40)])
        self.assertAlmostEqual(cell["mean_signed_error"], 2.0, places=6)


class GroupingAndCountersTests(unittest.TestCase):
    def test_groups_by_sport_market_and_segment(self) -> None:
        rows = (
            [observation(1.0, mean=1.0, sigma=1.0, market="strikeouts")] * 3
            + [observation(1.0, mean=1.0, sigma=1.0, market="outs")] * 2
            + [observation(1.0, mean=1.0, sigma=1.0, market="outs", segment="first5")] * 4
            + [observation(1.0, mean=1.0, sigma=1.0, sport="wnba", market="points")] * 5
        )
        result = score_projections(rows)
        keys = {(c["sport"], c["market"], c["segment"]) for c in result["cells"]}
        self.assertEqual(
            keys,
            {
                ("mlb", "strikeouts", "full"),
                ("mlb", "outs", "full"),
                ("mlb", "outs", "first5"),
                ("wnba", "points", "full"),
            },
        )
        self.assertEqual(result["counters"]["cells_total"], 4)

    def test_counters_report_what_was_dropped_not_only_what_was_kept(self) -> None:
        rows = [observation(1.0, mean=1.0, sigma=1.0)] * 5 + [observation(1.0)] * 3
        result = score_projections(rows)
        counters = result["counters"]
        self.assertEqual(counters["observations_in"], 8)
        self.assertEqual(counters["dropped_no_model_mean"], 3)
        self.assertEqual(counters["observations_scored"], 5)

    def test_measured_and_unmeasured_cells_are_counted_separately(self) -> None:
        rows = [observation(1.0, mean=1.0, sigma=1.0, market="thick")] * 40 + [
            observation(1.0, mean=1.0, sigma=1.0, market="thin")
        ] * 2
        counters = score_projections(rows)["counters"]
        self.assertEqual(counters["cells_measured"], 1)
        self.assertEqual(counters["cells_unmeasured"], 1)

    def test_reports_date_coverage_per_cell(self) -> None:
        rows = [
            observation(1.0, mean=1.0, sigma=1.0, date=f"2026-07-{day:02d}") for day in range(1, 12)
        ]
        cell = score_projections(rows)["cells"][0]
        self.assertEqual(cell["date_count"], 11)
        self.assertEqual(cell["date_span"], ["2026-07-01", "2026-07-11"])

    def test_an_empty_batch_produces_no_cells_and_does_not_raise(self) -> None:
        result = score_projections([])
        self.assertEqual(result["cells"], [])
        self.assertEqual(result["counters"]["observations_in"], 0)


if __name__ == "__main__":
    unittest.main()
