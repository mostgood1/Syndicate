"""The exchange-prop option-value measurement — `#624` step 5.

Three things this measurement gets right that an obvious version gets wrong,
and each has a test because each was a real error on the way to the number:

  * FEE-AWARE SELECTION. My first pass subtracted the exchange fee on every
    row, including ones where you would take the sportsbook and never pay it.
    That understates the value. You take whichever is cheaper AFTER fees, so
    the gain floors at zero.
  * THE FEE SHAPES DIFFER. Kalshi is a parabola that vanishes at the tails
    (`rate x P x (1-P)`); Polymarket is FLAT notional and does not vanish.
    Modelling Polymarket as a quadratic understates the tails by an order of
    magnitude — and the tails are where in-play pairs live.
  * IMPOSSIBLE PRICES ARE REFUSED. A value strictly inside (-100, +100) is not
    an American price; coercing one invents a probability.
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "exchange_prop_value_under_test",
        REPO_ROOT / "scripts" / "measure_exchange_prop_option_value.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MOD = _load()


class ImpliedProbabilityTests(unittest.TestCase):
    def test_real_prices_convert(self) -> None:
        self.assertAlmostEqual(MOD.implied(-110), 110 / 210, places=6)
        self.assertAlmostEqual(MOD.implied(+110), 100 / 210, places=6)
        self.assertAlmostEqual(MOD.implied(-100), 0.5, places=6)

    def test_impossible_prices_are_refused_not_coerced(self) -> None:
        """The 43%-impossible-prices class: a value in the hole is a parse or
        averaging artefact, and coercing it invents a probability."""
        for bad in (-89.125, -50, 0, 42, 99.9):
            self.assertIsNone(MOD.implied(bad), bad)


class FeeShapeTests(unittest.TestCase):
    def test_polymarket_is_flat_and_does_not_vanish_at_the_tails(self) -> None:
        """Kalshi's parabola vanishes at the tails; Polymarket's does not, and
        conflating them understates the tails by an order of magnitude."""
        for probability in (0.05, 0.5, 0.94):
            self.assertAlmostEqual(MOD.fee_pp("polymarket", probability, 1.0), 1.50, places=6)

    def test_kalshi_is_a_parabola_peaking_at_a_half(self) -> None:
        mid = MOD.fee_pp("kalshi", 0.5, 1.0)
        tail = MOD.fee_pp("kalshi", 0.94, 1.0)
        self.assertAlmostEqual(mid, 1.75, places=6)
        self.assertLess(tail, mid / 4)

    def test_the_multiplier_halves_the_kalshi_fee(self) -> None:
        self.assertAlmostEqual(
            MOD.fee_pp("kalshi", 0.5, 0.5), MOD.fee_pp("kalshi", 0.5, 1.0) / 2, places=9
        )

    def test_at_the_tails_polymarket_costs_far_more_than_kalshi(self) -> None:
        """The documented comparison, and note it is at the MLB HALF rate: at
        P=0.94 Kalshi's MLB fee is $0.0020/contract (0.20pp) against
        Polymarket's $0.0150 (1.50pp), "seven times larger". Reproducing it
        requires m=0.5 -- at full rate the gap is only ~3.8x, and my first
        version of this test asserted the 7x against m=1.0 and failed. The
        multiplier is not a detail."""
        kalshi_mlb = MOD.fee_pp("kalshi", 0.94, 0.5)
        self.assertAlmostEqual(kalshi_mlb, 0.1974, places=4)
        self.assertGreater(MOD.fee_pp("polymarket", 0.94, 1.0), 7 * kalshi_mlb)


class FeeAwareSelectionTests(unittest.TestCase):
    """The correction I had to make to my own number before believing it."""

    @staticmethod
    def _gain(book_prob: float, exchange_prob: float, venue: str, multiplier: float) -> float:
        effective = exchange_prob + MOD.fee_pp(venue, exchange_prob, multiplier) / 100.0
        return max(0.0, book_prob - effective) * 100.0

    def test_no_gain_when_the_sportsbook_is_cheaper(self) -> None:
        """And crucially NO FEE either -- you never took the exchange."""
        self.assertEqual(self._gain(0.50, 0.55, "kalshi", 1.0), 0.0)

    def test_a_fee_can_erase_an_apparent_gain(self) -> None:
        """1pp cheaper on the screen, 1.75pp of fee at P=0.5 -> nothing."""
        self.assertGreater(0.50 - 0.49, 0)
        self.assertEqual(self._gain(0.50, 0.49, "kalshi", 1.0), 0.0)

    def test_a_real_gain_survives_the_fee(self) -> None:
        gain = self._gain(0.55, 0.49, "kalshi", 1.0)
        self.assertGreater(gain, 0)
        self.assertLess(gain, 6.0, "the fee must reduce the raw 6pp difference")

    def test_gain_never_goes_negative(self) -> None:
        """Flooring at zero is what makes this a SELECTION rather than a blanket
        fee subtraction -- the bug in my first pass."""
        for exchange_prob in (0.10, 0.30, 0.50, 0.80, 0.95):
            self.assertGreaterEqual(self._gain(0.50, exchange_prob, "polymarket", 1.0), 0.0)


class KeyingTests(unittest.TestCase):
    def test_the_key_separates_players_and_sides(self) -> None:
        """A prop key without player or side would compare one batter's price
        against another's, which is the cross-game keying defect one layer over."""
        base = {"event_id": "e1", "market": "batter_hits", "player_name": "A", "line": 0.5, "selection": "over"}
        other_player = dict(base, player_name="B")
        other_side = dict(base, selection="under")
        self.assertNotEqual(MOD.quote_key(base), MOD.quote_key(other_player))
        self.assertNotEqual(MOD.quote_key(base), MOD.quote_key(other_side))


class GateBookTests(unittest.TestCase):
    """`#624` step 6 is a gate on ONE book — unders, minus HR and HRR. Measuring
    entry improvement over all props and spending it against that book's ROI
    sensitivity assumes the two move together, and on 2026-09-01 they did not:
    all-props gave +1.121pp where the gate book gave +0.955pp."""

    def test_the_gate_book_is_unders_only(self) -> None:
        self.assertTrue(MOD.in_gate_book({"selection": "under", "market": "batter_hits"}))
        self.assertFalse(MOD.in_gate_book({"selection": "over", "market": "batter_hits"}))

    def test_home_runs_and_hrr_are_excluded(self) -> None:
        """The two markets item 07 removed. HR overs are separately marked DO
        NOT INVERT, and HRR carried the producer null."""
        self.assertFalse(MOD.in_gate_book({"selection": "under", "market": "batter_home_runs"}))
        self.assertFalse(MOD.in_gate_book({"selection": "under", "market": "batter_hits_runs_rbis"}))

    def test_a_missing_selection_is_excluded_not_admitted(self) -> None:
        """Unknown must not default permissive: a row with no side is not
        evidence that it is an under."""
        self.assertFalse(MOD.in_gate_book({"market": "batter_hits"}))
        self.assertFalse(MOD.in_gate_book({"selection": None, "market": "batter_hits"}))


class SensitivityTests(unittest.TestCase):
    def test_the_table_reproduces_item_07_exactly_at_its_own_points(self) -> None:
        for side_cost, roi in MOD.GATE_SENSITIVITY:
            self.assertAlmostEqual(MOD.roi_at_side_cost(side_cost), roi, places=6, msg=str(side_cost))

    def test_the_slope_is_about_1_77_not_0_75(self) -> None:
        """The correction this module exists to carry. The 08-31 write-up said
        1pp of better entry is worth ~+0.75pp of ROI and attributed it to this
        very table; the table says otherwise, and step 5 spent the wrong one."""
        slope = (MOD.roi_at_side_cost(2.50) - MOD.roi_at_side_cost(4.05)) / (4.05 - 2.50)
        self.assertAlmostEqual(slope, 1.7677, places=3)
        self.assertGreater(slope, 2 * 0.75, "0.75 understates by more than half")

    def test_cheaper_entry_never_lowers_roi(self) -> None:
        previous = None
        for step in range(0, 41):
            roi = MOD.roi_at_side_cost(step / 10.0)
            if previous is not None:
                self.assertLessEqual(roi, previous + 1e-9)
            previous = roi

    def test_it_clamps_instead_of_extrapolating(self) -> None:
        """Past a measured endpoint there is no measurement, so it must not
        invent one -- a negative entry cost is not +9% ROI."""
        self.assertEqual(MOD.roi_at_side_cost(-3.0), 8.48)
        self.assertEqual(MOD.roi_at_side_cost(99.0), 0.98)

    def test_the_measured_gate_readings_fail_both_conditions(self) -> None:
        """2026-09-01, gate book, n=653: +0.955pp (m=0.5) and +0.703pp (m=1.0).
        Neither reaches +3% ROI, and neither brings the two-way hold to <=5%."""
        for gain, expected_roi in ((0.955, 2.66), (0.703, 2.22)):
            side_cost = MOD.GATE_PER_SIDE_TODAY - gain
            self.assertAlmostEqual(MOD.roi_at_side_cost(side_cost), expected_roi, places=1)
            self.assertLess(MOD.roi_at_side_cost(side_cost), MOD.GATE_ROI_TARGET_PCT)
            self.assertGreater(2 * side_cost, MOD.GATE_HOLD_TARGET_PCT)


class KalshiMultiplierTests(unittest.TestCase):
    """Read live from `GET /trade-api/v2/series/<ticker>` on 2026-09-01, all 14
    registered MLB series — reproduce with `scripts/read_kalshi_fee_params.py`.
    These pin the two things the read established."""

    def test_every_batter_prop_series_is_half_rate(self) -> None:
        """The question `#624` step 6 could not answer, now answered. It was
        reported as a bound m=0.5..1.0 whose width was 0.44 ROI points."""
        for market in ("batter_hits", "batter_home_runs", "batter_hits_runs_rbis",
                       "batter_rbis", "batter_total_bases", "batter_stolen_bases"):
            multiplier, resolved = MOD.kalshi_multiplier_for_market(market)
            self.assertTrue(resolved, market)
            self.assertEqual(multiplier, 0.5, market)

    def test_pitcher_rate_stats_are_FULL_rate(self) -> None:
        """Why "MLB is half rate" is the wrong rule: these three are full rate
        AND they sit inside the gate book, which is unders-minus-HR/HRR rather
        than batter-unders. One multiplier would be wrong in both directions."""
        for market in ("earned_runs", "hits_allowed", "walks_allowed"):
            multiplier, resolved = MOD.kalshi_multiplier_for_market(market)
            self.assertTrue(resolved, market)
            self.assertEqual(multiplier, 1.0, market)

    def test_the_map_is_not_uniform(self) -> None:
        """If it ever collapses to one value, the per-market machinery is
        pointless and something upstream has flattened it."""
        self.assertEqual(set(MOD.KALSHI_MULTIPLIER_BY_MARKET.values()), {0.5, 1.0})

    def test_an_unknown_market_rounds_AGAINST_us(self) -> None:
        """`venue_fees`: a fee model that is too LOW manufactures fake edges and
        loses money on every fill. Unknown must not land on the cheap branch."""
        multiplier, resolved = MOD.kalshi_multiplier_for_market("batter_doubles_off_lefties")
        self.assertFalse(resolved)
        self.assertEqual(multiplier, MOD.KALSHI_UNKNOWN_MULTIPLIER)
        self.assertEqual(MOD.KALSHI_UNKNOWN_MULTIPLIER, max(MOD.KALSHI_MULTIPLIER_BY_MARKET.values()))

    def test_the_unknown_default_is_the_expensive_branch_not_the_common_one(self) -> None:
        """The common case is 0.5 (11 of 14 series). Defaulting to the COMMON
        value would be cheaper and wrong; the rule is conservative, not modal."""
        values = list(MOD.KALSHI_MULTIPLIER_BY_MARKET.values())
        modal = max(set(values), key=values.count)
        self.assertEqual(modal, 0.5)
        self.assertNotEqual(MOD.KALSHI_UNKNOWN_MULTIPLIER, modal)

    def test_resolution_is_case_and_whitespace_insensitive(self) -> None:
        self.assertEqual(MOD.kalshi_multiplier_for_market("  Batter_Hits "), (0.5, True))

    def test_a_missing_market_does_not_crash_and_is_conservative(self) -> None:
        for bad in (None, "", 0):
            multiplier, resolved = MOD.kalshi_multiplier_for_market(bad)
            self.assertFalse(resolved)
            self.assertEqual(multiplier, MOD.KALSHI_UNKNOWN_MULTIPLIER)

    def test_the_resolved_gate_reading_still_fails_both_conditions(self) -> None:
        """2026-09-01, gate book, per-series multipliers: +0.949pp. Resolving the
        multiplier COLLAPSED the bound to its optimistic end — it did not close
        the gate, and saying it was 'worth 0.44 points' overstated it."""
        side_cost = MOD.GATE_PER_SIDE_TODAY - 0.949
        roi = MOD.roi_at_side_cost(side_cost)
        self.assertAlmostEqual(roi, 2.65, places=1)
        self.assertLess(roi, MOD.GATE_ROI_TARGET_PCT)
        self.assertGreater(2 * side_cost, MOD.GATE_HOLD_TARGET_PCT)


if __name__ == "__main__":
    unittest.main()
