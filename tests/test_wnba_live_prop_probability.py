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
        # Table refreshed 2026-09-28 (48 dates / 140 games): `0-5` p90/sd = 1.83 and
        # `30+` 1.67 widen; the middle buckets measured below 1.6449 and keep sd.
        self.assertAlmostEqual(residual_sigma(2.0), 6.00 / 1.6449, places=3)
        self.assertGreater(residual_sigma(2.0), 3.28, "heavy tail must widen")
        self.assertAlmostEqual(residual_sigma(25.0), 6.64, places=3)
        self.assertAlmostEqual(residual_sigma(7.0), 4.44, places=3)

    def test_outside_the_measured_range_it_refuses(self) -> None:
        for bad in (None, -1.0, "n/a", float("nan")):
            with self.subTest(bad=bad):
                self.assertIsNone(residual_sigma(bad))


class ProbabilityTests(unittest.TestCase):
    """`[2026-09-28]` Points prices on the NegBin remainder over the game-state
    remaining-minutes model, like rebounds/assists -- the normal branch that these
    tests used to pin was removed when it lost its last caller. The properties that
    matter carry over; the normal-specific ones (exact symmetry, a coin flip at the
    line) do not hold for a skewed count and are not asserted."""

    KW = dict(projected=20.0, minutes_remaining=15.0, market="points", current=10.0)

    def test_more_expected_production_raises_the_over(self) -> None:
        slow = live_prop_prob_over(line=17.5, rate=0.3, expected_minutes=15.0, **self.KW)
        fast = live_prop_prob_over(line=17.5, rate=0.8, expected_minutes=15.0, **self.KW)
        self.assertGreater(fast["prob_over"], slow["prob_over"])

    def test_more_minutes_left_raises_the_over(self) -> None:
        few = live_prop_prob_over(line=17.5, rate=0.5, expected_minutes=4.0, **self.KW)
        many = live_prop_prob_over(line=17.5, rate=0.5, expected_minutes=20.0, **self.KW)
        self.assertGreater(many["prob_over"], few["prob_over"])

    def test_it_stays_a_probability(self) -> None:
        for rate in (0.0, 0.2, 1.0, 3.0):
            with self.subTest(rate=rate):
                out = live_prop_prob_over(line=17.5, rate=rate, expected_minutes=12.0, **self.KW)
                self.assertGreaterEqual(out["prob_over"], 0.0)
                self.assertLessEqual(out["prob_over"], 1.0)

    def test_a_line_already_reached_is_one(self) -> None:
        out = live_prop_prob_over(line=9.5, rate=0.5, expected_minutes=12.0, **self.KW)
        self.assertEqual(out["prob_over"], 1.0)

    def test_it_carries_the_spread_that_produced_it(self) -> None:
        out = live_prop_prob_over(line=17.5, rate=0.5, expected_minutes=15.0, **self.KW)
        self.assertEqual(out["basis"], "measured_negbin_remainder")
        self.assertGreater(out["residual_sigma"], 0.0)


class RefusalTests(unittest.TestCase):
    def test_no_projection_no_price(self) -> None:
        out = live_prop_prob_over(projected=None, line=17.5, minutes_remaining=10.0,
                                  current=10.0, rate=0.5, expected_minutes=10.0)
        self.assertIsNone(out["prob_over"])
        self.assertEqual(out["unavailable_reason"], REASON_NO_PROJECTION)

    def test_no_line_no_price(self) -> None:
        out = live_prop_prob_over(projected=20.0, line=None, minutes_remaining=10.0,
                                  current=10.0, rate=0.5, expected_minutes=10.0)
        self.assertIsNone(out["prob_over"])
        self.assertEqual(out["unavailable_reason"], REASON_NO_LINE)

    def test_unknown_remaining_minutes_REFUSES_rather_than_guessing(self) -> None:
        """THE GUARD. No game-state minutes means no fitted remainder; a default
        would price a state nobody measured."""
        for bad in (None, -1.0, "later"):
            with self.subTest(bad=bad):
                out = live_prop_prob_over(projected=20.0, line=17.5, minutes_remaining=10.0,
                                          current=10.0, rate=0.5, expected_minutes=bad)
                self.assertIsNone(out["prob_over"])
                self.assertEqual(out["unavailable_reason"], REASON_NO_MINUTES_REMAINING)

    def test_it_never_returns_a_bare_None(self) -> None:
        out = live_prop_prob_over(projected=None, line=None, minutes_remaining=None)
        self.assertIsInstance(out, dict)
        self.assertIn("prob_over", out)
        self.assertIsNotNone(out["unavailable_reason"])


if __name__ == "__main__":
    unittest.main()
