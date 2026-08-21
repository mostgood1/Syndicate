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



class AnalyticSpreadTests(unittest.TestCase):
    """A spread priced from a LINE-SPECIFIC probability, and refused elsewhere.

    WNBA publishes a live cover probability at ONE line (`#475`/`#481`). It
    prices that line and no other; answering an alt line from it would invent a
    distribution, which is the very thing the distribution path exists to do
    honestly.
    """

    ANALYTIC = {"spread": {"line": 3.5, "p_home_cover": 0.72}}

    def test_prices_at_the_matching_line(self) -> None:
        v = J.price_analytic_line_market(
            analytic=self.ANALYTIC, market="spreads", line=3.5,
            market_prob=0.50, analytic_std_err=0.054,
        )
        self.assertIsNotNone(v)
        self.assertTrue(v["priceable"])
        self.assertEqual(v["std_err_basis"], "analytic_calibration")
        self.assertAlmostEqual(v["edge_pp"], 22.0, places=6)

    def test_refuses_a_different_line_by_name(self) -> None:
        for other in (2.5, 4.5, -3.5, 0.0):
            with self.subTest(line=other):
                v = J.price_analytic_line_market(
                    analytic=self.ANALYTIC, market="spreads_alt", line=other,
                    market_prob=0.50, analytic_std_err=0.054,
                )
                self.assertFalse(v["priceable"])
                self.assertEqual(v["withheld_reason"], J.REASON_ANALYTIC_LINE_MISMATCH)

    def test_small_edge_still_refused_at_the_matching_line(self) -> None:
        v = J.price_analytic_line_market(
            analytic={"spread": {"line": 3.5, "p_home_cover": 0.55}},
            market="spreads", line=3.5, market_prob=0.50, analytic_std_err=0.054,
        )
        self.assertFalse(v["priceable"])
        self.assertEqual(v["withheld_reason"], J.REASON_NOT_PRICEABLE)

    def test_totals_now_PRICE_at_their_own_measured_interval(self) -> None:
        """`#499` graded the totals transform (249 games / 23,712 samples), so
        the blanket "never backtested" refusal is retired for wnba totals.

        THE SIGMA IS FOUR TIMES THE WIN PATH'S (0.150 vs 0.054) and that is the
        measurement, not a penalty: it is the worst calibration gap BY PREDICTED
        BUCKET on held-out data. By minutes-left bucket it would read 0.023,
        which is an averaging artifact -- +0.109 at p=0.35 and -0.150 at p=0.65
        cancel within a time bucket. At 2 sigma this is a 30pp bar, so almost
        nothing prices, which is correct for an estimator still visibly
        under-dispersed.
        """
        v = J.price_analytic_line_market(
            analytic={"total": {"line": 165.5, "p_over": 0.95}},
            market="totals", line=165.5, market_prob=0.50,
            analytic_std_err=0.054, sport="wnba",
        )
        self.assertIsNotNone(v)
        self.assertAlmostEqual(v["prob_std_err"], 0.150, places=6,
                               msg="totals must use their OWN measured sigma, not the win path's")
        self.assertEqual(v["std_err_basis"], "analytic_calibration")
        self.assertTrue(v["priceable"], "a 45pp edge clears the 30pp bar")

    def test_a_typical_totals_edge_is_still_refused_by_the_30pp_bar(self) -> None:
        """The bar is the feature. 10pp is a large edge and must NOT price."""
        v = J.price_analytic_line_market(
            analytic={"total": {"line": 165.5, "p_over": 0.60}},
            market="totals", line=165.5, market_prob=0.50,
            analytic_std_err=0.054, sport="wnba",
        )
        self.assertFalse(v["priceable"])
        self.assertEqual(v["withheld_reason"], J.REASON_NOT_PRICEABLE)

    def test_totals_at_a_DIFFERENT_line_still_refuse_by_line(self) -> None:
        v = J.price_analytic_line_market(
            analytic={"total": {"line": 165.5, "p_over": 0.95}},
            market="totals", line=170.5, market_prob=0.50,
            analytic_std_err=0.054, sport="wnba",
        )
        self.assertFalse(v["priceable"])
        self.assertEqual(v["withheld_reason"], J.REASON_ANALYTIC_LINE_MISMATCH)

    def test_an_ABSENT_sport_refuses_rather_than_defaulting(self) -> None:
        """No sport on the hit must not silently become wnba."""
        v = J.price_analytic_line_market(
            analytic={"total": {"line": 165.5, "p_over": 0.95}},
            market="totals", line=165.5, market_prob=0.50, analytic_std_err=0.054,
        )
        self.assertFalse(v["priceable"])
        self.assertEqual(v["withheld_reason"], J.REASON_ANALYTIC_UNCALIBRATED)

    def test_the_index_stamps_the_sport_so_the_lookup_cannot_default(self) -> None:
        snap = {"games": [{"away_name": "A", "home_name": "B",
                           "gameLens": [{"source": "live_projection",
                                         "modelHomeWinProb": 0.6,
                                         "projection": {"homeMargin": 4.0}}]}]}
        idx = J.build_live_gameline_index(snap, sources=("live_projection",),
                                          analytic_std_err=0.054, sport="wnba")
        self.assertEqual(next(iter(idx.values()))["sport"], "wnba")

    def test_a_sport_with_NO_totals_measurement_still_refuses_by_name(self) -> None:
        """Retiring the refusal for a MEASURED pair must not retire it for
        everything -- that would be the permissive default this repo forbids."""
        v = J.price_analytic_line_market(
            analytic={"total": {"line": 165.5, "p_over": 0.95}},
            market="totals", line=165.5, market_prob=0.50,
            analytic_std_err=0.054, sport="nba",
        )
        self.assertFalse(v["priceable"])
        self.assertEqual(v["withheld_reason"], J.REASON_ANALYTIC_UNCALIBRATED)

    def test_totals_are_refused_as_UNCALIBRATED_not_as_missing_a_shape(self) -> None:
        """The distinction is the point: a known gap must not read as a shrug.

        `_wnba_live_total_over_prob` still carries the un-backtested
        `8.0 + 0.50*min_left`; `#481` explicitly declined to refit it.
        """
        v = J.price_analytic_line_market(
            analytic={"total": {"line": 165.5, "p_over": 0.61}},
            market="totals", line=165.5, market_prob=0.50, analytic_std_err=0.054,
            sport="nba",  # no totals measurement for this sport
        )
        self.assertIsNotNone(v)
        self.assertFalse(v["priceable"])
        self.assertEqual(v["withheld_reason"], J.REASON_ANALYTIC_UNCALIBRATED)
        self.assertNotEqual(v["withheld_reason"], J.REASON_NO_LIVE_DISTRIBUTION)

    def test_returns_None_when_the_path_does_not_apply(self) -> None:
        """None means 'fall through', so MLB reaches the distribution path and
        its real reason is not masked by this one."""
        self.assertIsNone(J.price_analytic_line_market(
            analytic=None, market="spreads", line=3.5, market_prob=0.5, analytic_std_err=0.054))
        self.assertIsNone(J.price_analytic_line_market(
            analytic={}, market="spreads", line=3.5, market_prob=0.5, analytic_std_err=0.054))
        self.assertIsNone(J.price_analytic_line_market(
            analytic=self.ANALYTIC, market="h2h", line=3.5, market_prob=0.5, analytic_std_err=0.054))

    def test_lens_extraction_reads_the_wnba_markets_block(self) -> None:
        lens = {
            "source": "live_projection",
            "modelHomeWinProb": 0.6,
            "projection": {"homeMargin": 4.0, "total": 160.0},
            "markets": {
                "spread": {"homeLine": 3.5, "p_win": 0.72, "selection": "home"},
                "total": {"line": 165.5, "p_win": 0.61},
            },
        }
        got = J._analytic_markets_from_lens(lens)
        self.assertEqual(got["spread"], {"line": 3.5, "p_home_cover": 0.72})
        self.assertEqual(got["total"]["line"], 165.5)

    def test_lens_without_markets_yields_empty_so_mlb_is_untouched(self) -> None:
        self.assertEqual(J._analytic_markets_from_lens({"source": "live_mc"}), {})

    def test_an_away_selection_spread_is_not_read_as_home(self) -> None:
        """Guard against silently inverting the side if the lens ever changes."""
        lens = {"markets": {"spread": {"homeLine": 3.5, "p_win": 0.72, "selection": "away"}}}
        self.assertNotIn("spread", J._analytic_markets_from_lens(lens))

if __name__ == "__main__":
    unittest.main()
