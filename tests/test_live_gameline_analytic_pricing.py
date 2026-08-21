"""A sport whose live probability is ANALYTIC must still price, and still refuse.

WHY. `price_moneyline`'s precision gate derives its interval from a sim count.
WNBA has none: `state.md` records that WNBA deliberately does not re-sim live,
so `#481`'s live probability is an analytic transform of the pregame sim. The
sims gate therefore refused every WNBA row permanently, and the board counter
said so by name -- measured on production 2026-08-21 against a live IND@DAL,
`rows_live_gameline_considered: 194`, `rows_live_gameline_priceable: 0`,
`sim_count_unusable` among the reasons.

WHAT MUST NOT HAPPEN. The fix is NOT "skip the gate when there are no sims".
That would price every analytic row at an implied zero interval, which is the
exact `0.0`-for-a-missing-value substitution `prob_std_err`'s own docstring
calls the worst available in this module, and which already shipped once
(`PHI @ MIN model=0.0 se=0.0` published PRICEABLE). The analytic path has to
bring a MEASURED interval or stay refused. These tests pin both halves.
"""
from __future__ import annotations

import unittest

from syndicate.features.shared import live_gameline_join as J


class AnalyticStdErrTableTests(unittest.TestCase):
    def test_wnba_has_a_measured_interval_and_it_is_positive(self) -> None:
        se = J.analytic_std_err_for_sport("wnba")
        self.assertIsNotNone(se)
        self.assertGreater(se, 0.0)
        # Pinned to `#481`'s held-out worst calibration gap. If this constant is
        # ever changed, the ledger entry justifying the new number should change
        # with it -- the value is a measurement, not a tuning knob.
        self.assertAlmostEqual(se, 0.054, places=6)

    def test_a_sport_with_no_measured_interval_gets_none(self) -> None:
        """Absence must not read as 'no uncertainty'."""
        for sport in ("mlb", "nfl", "soccer", "", None, "unknown"):
            with self.subTest(sport=sport):
                self.assertIsNone(J.analytic_std_err_for_sport(sport))


class PriceMoneylineAnalyticTests(unittest.TestCase):
    def test_analytic_interval_prices_a_row_that_sims_would_refuse(self) -> None:
        """THE REGRESSION TEST. Same inputs, no sims -- refused before, priced now."""
        without = J.price_moneyline(model_prob=0.75, market_prob=0.55, sims=None)
        self.assertFalse(without["priceable"])
        self.assertEqual(without["withheld_reason"], J.REASON_UNUSABLE_SIMS)

        with_bar = J.price_moneyline(
            model_prob=0.75, market_prob=0.55, sims=None, analytic_std_err=0.054
        )
        self.assertTrue(with_bar["priceable"])
        self.assertEqual(with_bar["std_err_basis"], "analytic_calibration")
        self.assertAlmostEqual(with_bar["prob_std_err"], 0.054, places=6)
        self.assertAlmostEqual(with_bar["edge_pp"], 20.0, places=6)

    def test_the_refusal_survives_a_small_edge(self) -> None:
        """2 sigma at se=0.054 is a 10.8pp bar. A 5pp edge must NOT price."""
        verdict = J.price_moneyline(
            model_prob=0.60, market_prob=0.55, sims=None, analytic_std_err=0.054
        )
        self.assertFalse(verdict["priceable"])
        self.assertEqual(verdict["withheld_reason"], J.REASON_NOT_PRICEABLE)
        self.assertAlmostEqual(verdict["edge_pp"], 5.0, places=6)

    def test_a_zero_or_negative_interval_is_refused_not_treated_as_precise(self) -> None:
        """The single worst substitution available in this module."""
        for bad in (0.0, -0.1, "not-a-number", float("nan")):
            with self.subTest(bad=bad):
                verdict = J.price_moneyline(
                    model_prob=0.99, market_prob=0.20, sims=None, analytic_std_err=bad
                )
                self.assertFalse(
                    verdict["priceable"],
                    f"analytic_std_err={bad!r} must never make a row priceable",
                )
                self.assertEqual(verdict["withheld_reason"], J.REASON_UNUSABLE_SIMS)

    def test_no_interval_at_all_is_still_refused_by_the_same_name(self) -> None:
        verdict = J.price_moneyline(model_prob=0.75, market_prob=0.55, sims=5)
        self.assertFalse(verdict["priceable"])
        self.assertEqual(verdict["withheld_reason"], J.REASON_UNUSABLE_SIMS)

    # --- MLB must be untouched --------------------------------------------

    def test_sims_path_is_unchanged_and_wins_when_both_are_present(self) -> None:
        """MLB behaviour must be bit-for-bit identical, including its refusals."""
        sims_only = J.price_moneyline(model_prob=0.90, market_prob=0.70, sims=120)
        both = J.price_moneyline(
            model_prob=0.90, market_prob=0.70, sims=120, analytic_std_err=0.054
        )
        self.assertEqual(sims_only["prob_std_err"], both["prob_std_err"])
        self.assertEqual(sims_only["priceable"], both["priceable"])
        self.assertEqual(both["std_err_basis"], "sim_count")
        # And the sims-derived bar is the real one, not the analytic constant.
        self.assertNotAlmostEqual(both["prob_std_err"], 0.054, places=6)

    def test_market_and_projection_refusals_still_precede_the_interval(self) -> None:
        no_model = J.price_moneyline(model_prob=None, market_prob=0.5, sims=None,
                                     analytic_std_err=0.054)
        self.assertEqual(no_model["withheld_reason"], J.REASON_NO_LIVE_PROJECTION)
        no_market = J.price_moneyline(model_prob=0.7, market_prob=None, sims=None,
                                      analytic_std_err=0.054)
        self.assertEqual(no_market["withheld_reason"], J.REASON_NO_MARKET_PRICE)


class IndexThreadingTests(unittest.TestCase):
    """The interval must travel WITH the projection it describes."""

    def _snapshot(self):
        return {
            "games": [{
                "away_name": "Indiana Fever",
                "home_name": "Dallas Wings",
                "gameLens": [{
                    "source": "live_projection",
                    "modelHomeWinProb": 0.72,
                    "projection": {"homeMargin": 8.0, "total": 165.0},
                }],
            }]
        }

    def test_index_stamps_the_interval_when_given(self) -> None:
        idx = J.build_live_gameline_index(
            self._snapshot(), sources=("live_projection",), analytic_std_err=0.054
        )
        self.assertEqual(len(idx), 1)
        hit = next(iter(idx.values()))
        self.assertAlmostEqual(hit["analytic_std_err"], 0.054, places=6)
        self.assertAlmostEqual(hit["home_win_prob"], 0.72, places=6)

    def test_index_omits_it_when_absent_so_mlb_hits_are_unchanged(self) -> None:
        idx = J.build_live_gameline_index(self._snapshot(), sources=("live_projection",))
        hit = next(iter(idx.values()))
        self.assertNotIn("analytic_std_err", hit)


if __name__ == "__main__":
    unittest.main()
