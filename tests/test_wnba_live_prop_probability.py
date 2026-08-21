"""`P(final >= line)` from a MEASURED residual -- its shape, and its refusals.

The table in the module under test is a MEASUREMENT (n=796, 5 slates, replay
reconciling 100%). These tests pin the properties that make it usable and the
refusals that keep it honest outside the range it was measured over.
"""
from __future__ import annotations

import unittest

from syndicate.features.shared.wnba_live_prop_probability import (
    REASON_NO_LINE,
    REASON_NO_MINUTES_REMAINING,
    REASON_NO_PROJECTION,
    live_prop_prob_over,
    residual_sigma,
)


class SigmaTableTests(unittest.TestCase):
    def test_the_interval_shrinks_as_the_game_runs_down(self) -> None:
        """The whole reason the table is bucketed. 6.03 -> 2.70 measured."""
        sigmas = [residual_sigma(m) for m in (35.0, 25.0, 15.0, 7.0, 2.0)]
        self.assertTrue(all(s is not None for s in sigmas))
        self.assertEqual(sigmas, sorted(sigmas, reverse=True),
                         "sigma must be monotone non-increasing as time runs out")

    def test_only_the_heavy_tailed_bucket_is_widened(self) -> None:
        """`max(sd, p90/1.6449)`: measured sd, widened where the tail is fatter.

        `0-5` measured p90/sd = 1.90 against 1.6449 for a normal, so it widens
        2.70 -> ~3.12. The others measured BELOW 1.6449 and keep their sd.
        """
        self.assertAlmostEqual(residual_sigma(2.0), 5.14 / 1.6449, places=3)
        self.assertGreater(residual_sigma(2.0), 2.70, "heavy tail must widen")
        self.assertAlmostEqual(residual_sigma(25.0), 5.38, places=3)
        self.assertAlmostEqual(residual_sigma(7.0), 3.88, places=3)

    def test_outside_the_measured_range_it_refuses(self) -> None:
        for bad in (None, -1.0, "n/a", float("nan")):
            with self.subTest(bad=bad):
                self.assertIsNone(residual_sigma(bad))


class ProbabilityTests(unittest.TestCase):
    def test_a_projection_on_the_line_is_a_coin_flip(self) -> None:
        out = live_prop_prob_over(projected=17.5, line=17.5, minutes_remaining=15.0)
        self.assertAlmostEqual(out["prob_over"], 0.5, places=6)

    def test_above_the_line_exceeds_a_half_and_below_it_falls_short(self) -> None:
        over = live_prop_prob_over(projected=22.0, line=17.5, minutes_remaining=15.0)
        under = live_prop_prob_over(projected=13.0, line=17.5, minutes_remaining=15.0)
        self.assertGreater(over["prob_over"], 0.5)
        self.assertLess(under["prob_over"], 0.5)
        # Symmetric about the line, because the residual is modelled normal.
        self.assertAlmostEqual(over["prob_over"] + under["prob_over"], 1.0, places=3)

    def test_the_SAME_gap_is_more_confident_later_in_the_game(self) -> None:
        """The point of the bucketing: 4 points clear of the line means much
        more with 2 minutes left than with 25."""
        early = live_prop_prob_over(projected=21.5, line=17.5, minutes_remaining=25.0)
        late = live_prop_prob_over(projected=21.5, line=17.5, minutes_remaining=2.0)
        self.assertGreater(late["prob_over"], early["prob_over"])

    def test_it_stays_a_probability(self) -> None:
        for projection in (0.0, 5.0, 40.0, 80.0):
            with self.subTest(projection=projection):
                out = live_prop_prob_over(projected=projection, line=17.5,
                                          minutes_remaining=8.0)
                self.assertGreaterEqual(out["prob_over"], 0.0)
                self.assertLessEqual(out["prob_over"], 1.0)

    def test_it_carries_the_sigma_that_produced_it(self) -> None:
        out = live_prop_prob_over(projected=20.0, line=17.5, minutes_remaining=15.0)
        self.assertAlmostEqual(out["residual_sigma"], 5.30, places=2)
        self.assertEqual(out["basis"], "measured_residual_normal")


class RefusalTests(unittest.TestCase):
    def test_no_projection_no_price(self) -> None:
        out = live_prop_prob_over(projected=None, line=17.5, minutes_remaining=10.0)
        self.assertIsNone(out["prob_over"])
        self.assertEqual(out["unavailable_reason"], REASON_NO_PROJECTION)

    def test_no_line_no_price(self) -> None:
        out = live_prop_prob_over(projected=20.0, line=None, minutes_remaining=10.0)
        self.assertIsNone(out["prob_over"])
        self.assertEqual(out["unavailable_reason"], REASON_NO_LINE)

    def test_unknown_minutes_remaining_REFUSES_rather_than_guessing(self) -> None:
        """THE GUARD. A default sigma here would price a state never measured,
        and a 0.0 would make every edge clear its bar."""
        for bad in (None, -1.0, "later"):
            with self.subTest(bad=bad):
                out = live_prop_prob_over(projected=20.0, line=17.5,
                                          minutes_remaining=bad)
                self.assertIsNone(out["prob_over"])
                self.assertEqual(out["unavailable_reason"], REASON_NO_MINUTES_REMAINING)

    def test_it_never_returns_a_bare_None(self) -> None:
        out = live_prop_prob_over(projected=None, line=None, minutes_remaining=None)
        self.assertIsInstance(out, dict)
        self.assertIn("prob_over", out)
        self.assertIsNotNone(out["unavailable_reason"])


if __name__ == "__main__":
    unittest.main()
