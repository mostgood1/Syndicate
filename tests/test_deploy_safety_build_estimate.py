"""`#427`. The deploy gate's build estimate must not collapse on short-circuits.

MEASURED (refresh-worker, 4h to 2026-08-14 18:0xZ, live `294f9ca9`), n=39
`COLLECT_SPAN_EXIT collect_candidates`:

    p50 0.00   p90 146.19   max 209.66
    of those >= 1s: n=9, p50 138.30, max 209.66
    ~77% sub-second, 23.1% >= 60s

The sub-second calls are `collect_candidates` short-circuiting on an empty pool.
MAX over a MIXED sample is the right statistic and is unchanged; what is added
is excluding the non-builds first, because the max of twelve zeros is zero.

NOT a live failure at the time of writing -- the gate returned `~2.3min` against
production. `_render_logs(..., limit=12)` returns rows oldest-first regardless
of direction, so the sampled twelve are not the ranked twelve. These tests pin
the latent case shut.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import scripts.check_deploy_safety as gate


def _row(elapsed: float) -> dict:
    return {"message": f"[intelligence] COLLECT_SPAN_EXIT stage=collect_candidates elapsed_s={elapsed}"}


class ExpectedBuildSecondsTests(unittest.TestCase):
    def _expected(self, elapsed_values):
        with patch.object(gate, "_render_logs", return_value=[_row(v) for v in elapsed_values]):
            return gate._expected_build_seconds("key")

    # -- the defect this closes -------------------------------------------

    def test_all_short_circuits_does_not_report_a_cheap_build(self) -> None:
        """The whole point: twelve zeros must not become 'a build takes 0 min'."""
        result = self._expected([0.0] * 12)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(
            result, 60.0,
            "an all-short-circuit window reported a sub-minute build, which tells "
            "an operator there is nothing to protect",
        )
        self.assertEqual(result, gate._NO_REAL_BUILD_FALLBACK_SECONDS)

    def test_the_measured_production_mix(self) -> None:
        """77% zeros with real builds present -> the real maximum, unchanged."""
        result = self._expected([0.0] * 9 + [138.3, 146.19, 209.66])
        self.assertAlmostEqual(result, 209.66, places=2)

    def test_a_single_real_build_among_zeros_wins(self) -> None:
        self.assertAlmostEqual(self._expected([0.0] * 11 + [187.4]), 187.4, places=2)

    # -- what must NOT change ---------------------------------------------

    def test_max_not_median_on_a_mixed_real_sample(self) -> None:
        """The asymmetry argument in the docstring is load-bearing and stays:
        over-waiting costs idle minutes, under-waiting destroys a board build."""
        self.assertAlmostEqual(self._expected([120.0, 200.0, 1372.2, 180.0]), 1372.2, places=1)

    def test_unreadable_logs_still_return_None_not_a_number(self) -> None:
        """None means UNKNOWN, which callers already treat as a block. It must
        not be conflated with the no-real-build fallback."""
        with patch.object(gate, "_render_logs", side_effect=RuntimeError("api down")):
            self.assertIsNone(gate._expected_build_seconds("key"))

    def test_empty_window_returns_None(self) -> None:
        with patch.object(gate, "_render_logs", return_value=[]):
            self.assertIsNone(gate._expected_build_seconds("key"))

    def test_rows_without_an_elapsed_field_are_ignored_not_counted_as_zero(self) -> None:
        rows = [{"message": "COLLECT_SPAN_EXIT stage=collect_candidates"}, _row(150.0)]
        with patch.object(gate, "_render_logs", return_value=rows):
            self.assertAlmostEqual(gate._expected_build_seconds("key"), 150.0, places=1)

    def test_threshold_sits_below_every_measured_real_build(self) -> None:
        """A guard against someone raising the threshold into the real band."""
        self.assertLess(gate._MIN_REAL_BUILD_SECONDS, 138.3)
        self.assertGreater(gate._MIN_REAL_BUILD_SECONDS, 0.0)

    def test_fallback_is_within_the_measured_band(self) -> None:
        self.assertGreaterEqual(gate._NO_REAL_BUILD_FALLBACK_SECONDS, 146.19)


if __name__ == "__main__":
    unittest.main()
