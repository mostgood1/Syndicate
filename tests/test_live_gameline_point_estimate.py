"""The published POINT estimate must come from the same estimator as the INTERVAL.

WHY THIS FILE EXISTS. `prob_std_err` computes Agresti-Coull `(k+2)/(n+4)` for
the width -- deliberately, with a docstring explaining that Wald is 0.0 at the
boundary and that "it is a LIVE case: the re-sim quantises to k/n" -- and then
threw the smoothed value away. The raw `k/n` was published as the estimate. The
correction reached the WIDTH and never the CENTRE.

WHAT THAT COST, measured on production 2026-09-06 (MLB live-gameline ledger, 6
days, 2,810 h2h records; the export was truncated so these are FLOORS):

    exactly 0.0 or 1.0    83     of those PRICED   59     distinct games   25
    of those 25: 23 hit, 2 LOST

      2026-08-29  ARI 2 @ SF  7   p=0.0, home won   max |edge_pp| 46.2
      2026-08-29  BOS 2 @ NYY 9   p=0.0, home won   max |edge_pp| 55.9

An exact 0.0 that loses has no recovery: Brier hits its 1.0 ceiling and log loss
is INFINITE, so two rows can dominate the series used to judge the engine.

THE TESTS THAT MATTER MOST HERE ARE THE LAST TWO. Everything above them checks
arithmetic, which is the easy half. `test_the_interval_is_NOT_double_shrunk`
pins the ordering trap -- `prob_std_err` reconstructs `successes = p * n`, so
smoothing before the SE is computed applies add-two twice and over-widens the
bar by 39% at the boundary, silently withholding real edges. And
`test_disabling_the_smoothing_turns_a_test_RED` is the reachability check this
repo requires before correctness checks: a fix that is never reached passes
every assertion about its output. Both were written after a lane in this repo
shipped 26 green tests over a fallback that `build_records` never called.
"""
from __future__ import annotations

import unittest

from syndicate.features.shared import live_gameline_join as J


class AgrestiCoullPointTests(unittest.TestCase):
    """The estimator itself, in isolation."""

    def test_the_boundary_is_pulled_off_0_and_1(self) -> None:
        # 120/120 -> 122/124. This is the case that produced 83 certainty rows.
        self.assertAlmostEqual(J.agresti_coull_point(1.0, 120), 122.0 / 124.0, places=12)
        self.assertAlmostEqual(J.agresti_coull_point(0.0, 120), 2.0 / 124.0, places=12)

    def test_it_never_returns_an_exact_certainty_for_any_n(self) -> None:
        """The whole point. No sim count may produce 0.0 or 1.0."""
        for n in (1, 20, 120, 300, 1000, 100000):
            for raw in (0.0, 1.0):
                with self.subTest(n=n, raw=raw):
                    value = J.agresti_coull_point(raw, n)
                    self.assertGreater(value, 0.0)
                    self.assertLess(value, 1.0)

    def test_the_middle_is_untouched(self) -> None:
        """Shrinkage toward 0.5 means ZERO shift AT 0.5.

        This is what makes the change safe for the bulk of the book: it is not a
        blanket haircut on every edge, it moves the tails and leaves the centre
        exactly where it was.
        """
        self.assertAlmostEqual(J.agresti_coull_point(0.5, 120), 0.5, places=12)
        self.assertAlmostEqual(J.agresti_coull_point(0.5, 300), 0.5, places=12)

    def test_the_shift_is_bounded_and_shrinks_as_n_grows(self) -> None:
        """~1.6 pp at n=120, and it decays -- so this cannot swamp a real edge."""
        shift_120 = 1.0 - J.agresti_coull_point(1.0, 120)
        shift_300 = 1.0 - J.agresti_coull_point(1.0, 300)
        self.assertLess(shift_120, 0.017)
        self.assertLess(shift_300, shift_120)

    def test_bad_input_returns_None_not_a_number(self) -> None:
        """Same contract as `prob_std_err`: absence must not read as a value."""
        for probability, sims in ((None, 120), ("x", 120), (1.0, 0), (1.0, -5),
                                  (1.0, None), (-0.1, 120), (1.1, 120), (0.5, "x")):
            with self.subTest(probability=probability, sims=sims):
                self.assertIsNone(J.agresti_coull_point(probability, sims))


class PriceMoneylinePointEstimateTests(unittest.TestCase):
    """The estimator as the module actually publishes it."""

    def test_a_certainty_is_never_published(self) -> None:
        out = J.price_moneyline(model_prob=1.0, market_prob=0.55, sims=120)
        self.assertNotEqual(out["model_prob"], 1.0)
        self.assertAlmostEqual(out["model_prob"], 122.0 / 124.0, places=12)
        self.assertEqual(out["point_estimator"], "agresti_coull")

    def test_the_raw_proportion_is_kept_for_diagnosis(self) -> None:
        """`k/n` is still what the sim said. Losing it would make the two
        estimators indistinguishable in the ledger afterwards, which is the same
        blindness that let this defect run for six days."""
        out = J.price_moneyline(model_prob=0.0, market_prob=0.55, sims=120)
        self.assertEqual(out["model_prob_raw"], 0.0)
        self.assertAlmostEqual(out["model_prob"], 2.0 / 124.0, places=12)

    def test_the_edge_is_computed_from_the_SMOOTHED_value(self) -> None:
        """If the edge were still taken from the raw proportion, the published
        probability and the published edge would disagree -- and the edge is the
        number the board acts on."""
        out = J.price_moneyline(model_prob=1.0, market_prob=0.55, sims=120)
        expected = (out["model_prob"] - 0.55) * 100.0
        self.assertAlmostEqual(out["edge_pp"], expected, places=9)

    def test_a_large_edge_still_prices(self) -> None:
        """This fixes an ESTIMATOR, not a disagreement. A 46 pp edge shrinks by
        ~1.6 pp and stays priceable -- claiming otherwise would oversell it."""
        out = J.price_moneyline(model_prob=1.0, market_prob=0.54, sims=120)
        self.assertTrue(out["priceable"], out.get("withheld_reason"))
        self.assertGreater(abs(out["edge_pp"]), 40.0)

    def test_the_refused_shape_matches_the_priced_shape(self) -> None:
        """A key present only on success is a key consumers forget can be absent."""
        priced = J.price_moneyline(model_prob=1.0, market_prob=0.55, sims=120)
        refused = J.price_moneyline(model_prob=None, market_prob=0.55, sims=120)
        self.assertEqual(set(priced), set(refused))
        self.assertIn("model_prob_raw", refused)
        self.assertIn("point_estimator", refused)

    def test_the_analytic_path_is_NOT_smoothed(self) -> None:
        """`#481` (WNBA) is a closed-form probability with a measured calibration
        error, not a count. Add-two there would shrink a quantity that was never
        `k/n`, and `_margin_win_prob` is already bounded off 0 and 1 by
        construction -- so the gate is on `basis`, not on `n`."""
        se = J.analytic_std_err_for_sport("wnba")
        out = J.price_moneyline(model_prob=0.97, market_prob=0.55, sims=0,
                                analytic_std_err=se)
        self.assertEqual(out["std_err_basis"], "analytic_calibration")
        self.assertEqual(out["model_prob"], 0.97)
        self.assertIsNone(out["point_estimator"])
        self.assertIsNone(out["model_prob_raw"])

    def test_the_interval_is_NOT_double_shrunk(self) -> None:
        """THE ORDERING TRAP, pinned.

        `prob_std_err` reconstructs `successes = p * n` internally. Hand it an
        already-smoothed `p` and add-two is applied TWICE: at p=1.0, n=120 the
        bar comes out 0.0157 instead of 0.0113 -- 39% too wide, which silently
        withholds real edges. Smoothing before the SE is computed is the obvious
        way to write this fix and it is the wrong way.

        So: the published SE must equal `prob_std_err(RAW, n)`, and must NOT
        equal `prob_std_err(SMOOTHED, n)`. Asserting only the first would pass
        under the buggy ordering whenever the two happen to round together, so
        both directions are checked.
        """
        raw = 1.0
        n = 120
        out = J.price_moneyline(model_prob=raw, market_prob=0.55, sims=n)
        from_raw = J.prob_std_err(raw, n)
        from_smoothed = J.prob_std_err(J.agresti_coull_point(raw, n), n)

        self.assertAlmostEqual(out["prob_std_err"], from_raw, places=12)
        self.assertNotAlmostEqual(out["prob_std_err"], from_smoothed, places=6)
        # And the two really are far enough apart for that to mean something.
        self.assertGreater(from_smoothed / from_raw, 1.3)

    def test_disabling_the_smoothing_turns_a_test_RED(self) -> None:
        """REACHABILITY, before correctness. `off != on`.

        A fix that is never reached passes every assertion about its output.
        This monkeypatches the estimator to the identity -- exactly what the code
        did before -- and asserts the published value CHANGES. If this test ever
        passes with the patch in place, `price_moneyline` has stopped calling it
        and every other test in this file has gone vacuous.
        """
        original = J.agresti_coull_point
        try:
            J.agresti_coull_point = lambda probability, sims: None  # type: ignore[assignment]
            inert = J.price_moneyline(model_prob=1.0, market_prob=0.55, sims=120)
        finally:
            J.agresti_coull_point = original  # type: ignore[assignment]
        live = J.price_moneyline(model_prob=1.0, market_prob=0.55, sims=120)

        self.assertEqual(inert["model_prob"], 1.0)          # the OLD behaviour
        self.assertIsNone(inert["point_estimator"])
        self.assertNotEqual(live["model_prob"], inert["model_prob"])
        # The interval is identical either way -- it was never the broken half.
        self.assertAlmostEqual(live["prob_std_err"], inert["prob_std_err"], places=12)


class PriceDistributionMarketPointEstimateTests(unittest.TestCase):
    """The totals/spreads path carries the SAME defect and the same fix.

    `_dist_prob_over` is a proportion of the re-sim's own histogram -- `k/n` by
    another name -- and it returns exactly 1.0 for any line outside the sampled
    support, which a live total routinely is once a game has partly resolved.
    """

    # A histogram far below the line: every sample is under, so P(over) is 0.0
    # and P(under) is 1.0 on the raw proportion.
    DIST = {"4": 40, "5": 40, "6": 40}

    def test_a_certainty_off_the_histogram_is_never_published(self) -> None:
        out = J.price_distribution_market(
            dist=self.DIST, line=40.5, side="under", market="totals",
            market_prob=0.55, sims=120,
        )
        self.assertEqual(out["model_prob_raw"], 1.0)
        self.assertLess(out["model_prob"], 1.0)
        self.assertEqual(out["point_estimator"], "agresti_coull")

    def test_the_edge_uses_the_smoothed_value(self) -> None:
        out = J.price_distribution_market(
            dist=self.DIST, line=40.5, side="under", market="totals",
            market_prob=0.55, sims=120,
        )
        self.assertAlmostEqual(out["edge_pp"],
                               round((out["model_prob"] - 0.55) * 100.0, 2), places=9)

    def test_the_interval_is_NOT_double_shrunk_here_either(self) -> None:
        out = J.price_distribution_market(
            dist=self.DIST, line=40.5, side="under", market="totals",
            market_prob=0.55, sims=120,
        )
        self.assertAlmostEqual(out["prob_std_err"], J.prob_std_err(1.0, 120), places=12)

    def test_the_refused_shape_matches_the_priced_shape(self) -> None:
        priced = J.price_distribution_market(
            dist=self.DIST, line=40.5, side="under", market="totals",
            market_prob=0.55, sims=120,
        )
        refused = J.price_distribution_market(
            dist=None, line=40.5, side="under", market="totals",
            market_prob=0.55, sims=120,
        )
        self.assertEqual(set(priced), set(refused))


if __name__ == "__main__":
    unittest.main()
