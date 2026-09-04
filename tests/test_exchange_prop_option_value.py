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


class DerivedEntryCostTests(unittest.TestCase):
    """`GATE_PER_SIDE_TODAY = 4.05` WAS NEVER MEASURED. It is `8.1% / 2`, the
    label on the top row of item 07's table, halved — and that halving is an
    identity that holds only AT EVEN MONEY. Measured on production shards
    2026-09-01..09-04, the gate book's unders sit at fair 0.607, so they carry
    ~61% of the hold and the real per-side cost is 4.233pp at a 7.012% two-way
    hold, not 4.05pp at 8.1%. Substituting it flipped step 6's ROI leg from MET
    to NOT MET.

    These tests pin the DERIVATION, not a replacement number. A hard-coded
    4.233 fails exactly the same way: the value moved 4.327 -> 3.776 across four
    consecutive days."""

    WINDOW = 30 * 60

    @staticmethod
    def _row(stamp, book, price, selection="under", market="batter_hits",
             captured="c1", player="A", line=0.5, event="e1"):
        payload = {"event_id": event, "market": market, "player_name": player,
                   "line": line, "selection": selection, "captured_at": captured}
        probability = MOD.implied(price)
        return (stamp, book, probability, payload)

    def _book(self, captured, stamp, under, over, book="draftkings", **kw):
        return [self._row(stamp, book, under, "under", captured=captured, **kw),
                self._row(stamp, book, over, "over", captured=captured, **kw)]

    # ---- the identity the constant got wrong ---------------------------

    def test_the_two_sides_split_the_hold_50_50_ONLY_at_even_money(self) -> None:
        """`side_cost = fair x hold`. The whole 4.05 error in one assertion."""
        even = MOD.side_cost_of(0.55, 0.55)          # fair 0.5 exactly
        self.assertAlmostEqual(even[0] * 2, even[1], places=9)
        skewed = MOD.side_cost_of(0.70, 0.37)        # fair well above 0.5
        self.assertGreater(skewed[0] * 2, skewed[1],
                           "doubling a favourite's cost OVERSTATES the hold")

    def test_the_hold_transform_is_cost_over_fair_not_twice_cost(self) -> None:
        cost, hold, fair = MOD.side_cost_of(0.70, 0.37)
        self.assertAlmostEqual(MOD.two_way_hold_pct(cost, fair), hold, places=9)
        self.assertNotAlmostEqual(2 * cost, hold, places=2)

    def test_the_asserted_constant_disagrees_with_its_own_hold(self) -> None:
        """4.05pp was published as "== today's ~8.1% two-way hold". At the
        measured fair of 0.607 it implies 6.67%, not 8.1% — the constant and its
        own stated justification never agreed."""
        implied_hold = MOD.two_way_hold_pct(MOD.GATE_PER_SIDE_ASSERTED_2026_08_31, 0.607)
        self.assertLess(implied_hold, 7.0)
        self.assertGreater(abs(implied_hold - 8.1), 1.4)

    def test_an_unusable_overround_is_refused_not_priced_at_zero(self) -> None:
        """Unknown must not default permissive: a broken pair dropped onto a
        cheap default reads as a FREE entry."""
        self.assertIsNone(MOD.side_cost_of(0.40, 0.40))   # overround 0.80, arb
        self.assertIsNone(MOD.side_cost_of(0.80, 0.60))   # overround 1.40
        self.assertIsNotNone(MOD.side_cost_of(0.60, 0.47))

    def test_the_hold_transform_refuses_a_non_probability(self) -> None:
        for bad in (0.0, 1.0, -0.2, 1.5):
            with self.assertRaises(ValueError):
                MOD.two_way_hold_pct(4.0, bad)

    # ---- REACHABILITY: the number must MOVE with the data ---------------

    def test_the_cost_RESPONDS_to_the_prices_it_is_given(self) -> None:
        """THE PIN. A hard-coded constant cannot answer two different books
        differently. `off != on`, before any correctness check: if this passes
        with the derivation removed, the derivation is not wired in."""
        cheap = self._book("c1", 100.0, -120, +115)
        rich = self._book("c1", 100.0, -160, +135)
        a = MOD.derive_entry_cost(cheap, self.WINDOW)["today_pp"]
        b = MOD.derive_entry_cost(rich, self.WINDOW)["today_pp"]
        self.assertGreater(abs(a - b), 0.5,
                           "the derived cost did not move with the prices — "
                           "something is answering from a constant")

    def test_the_cost_is_NOT_the_asserted_constant_on_arbitrary_input(self) -> None:
        """Belt and braces on the same point: three unrelated books must give
        three unrelated answers, none of them 4.05."""
        seen = set()
        for under, over in ((-120, +115), (-160, +135), (-105, -105)):
            value = MOD.derive_entry_cost(
                self._book("c1", 100.0, under, over), self.WINDOW)["today_pp"]
            self.assertNotAlmostEqual(
                value, MOD.GATE_PER_SIDE_ASSERTED_2026_08_31, places=2)
            seen.add(round(value, 4))
        self.assertEqual(len(seen), 3)

    def test_the_arithmetic_never_READS_the_asserted_constant(self) -> None:
        """The constant is kept only so the drift is printable. If anything in
        the derivation consults it, changing it would change an answer."""
        rows = self._book("c1", 100.0, -140, +125)
        before = MOD.derive_entry_cost(rows, self.WINDOW)
        original = MOD.GATE_PER_SIDE_ASSERTED_2026_08_31
        try:
            MOD.GATE_PER_SIDE_ASSERTED_2026_08_31 = 99.0
            after = MOD.derive_entry_cost(rows, self.WINDOW)
        finally:
            MOD.GATE_PER_SIDE_ASSERTED_2026_08_31 = original
        for field in ("today_pp", "gain_pp", "after_pp", "fair", "hold_measured_pct"):
            self.assertAlmostEqual(before[field], after[field], places=9, msg=field)

    def test_the_module_no_longer_defines_the_unmeasured_constant(self) -> None:
        """`GATE_PER_SIDE_TODAY` is the name the arithmetic used to read. If it
        comes back, so has the defect."""
        self.assertFalse(hasattr(MOD, "GATE_PER_SIDE_TODAY"))

    # ---- correctness, only after reachability ---------------------------

    def test_the_derived_cost_matches_the_reference_definition_by_hand(self) -> None:
        """One cell, arithmetic done longhand: -150 / +130 -> q 0.6, q_opp
        0.43478, overround 1.03478, fair 0.57983, cost 2.0169pp, hold 3.478%."""
        report = MOD.derive_entry_cost(self._book("c1", 100.0, -150, +130), self.WINDOW)
        self.assertEqual(report["n"], 1)
        self.assertAlmostEqual(report["today_pp"], 2.0169, places=3)
        self.assertAlmostEqual(report["hold_measured_pct"], 3.4783, places=3)
        self.assertAlmostEqual(report["fair"], 0.57983, places=4)
        self.assertTrue(report["hold_identity_ok"])

    def test_it_takes_the_CHEAPEST_book_at_the_snapshot(self) -> None:
        """The gain is measured against the best book, so the baseline must be
        too — that population mismatch is worth -0.807pp, twice the constant
        error it hid behind."""
        rows = (self._book("c1", 100.0, -150, +130, book="draftkings")
                + self._book("c1", 100.0, -190, +160, book="betmgm"))
        report = MOD.derive_entry_cost(rows, self.WINDOW)
        self.assertEqual(report["n"], 1, "two books at one snapshot is ONE cell")
        self.assertAlmostEqual(report["today_pp"], 2.0169, places=3)

    def test_an_absent_exchange_quote_is_a_ZERO_GAIN_not_a_dropped_cell(self) -> None:
        """The population fix. Dropping uncovered cells answers 'the exchange is
        cheaper where it quotes'; the gate asks about the BOOK, and you cannot
        take a price that is not there."""
        report = MOD.derive_entry_cost(self._book("c1", 100.0, -150, +130), self.WINDOW)
        self.assertEqual(report["n"], 1)
        self.assertEqual(report["covered"], 0)
        self.assertEqual(report["gain_pp"], 0.0)
        self.assertAlmostEqual(report["after_pp"], report["today_pp"], places=9)
        self.assertEqual(report["subset_n"], 0)

    def test_the_subset_and_the_book_are_reported_as_different_numbers(self) -> None:
        rows = (self._book("c1", 100.0, -150, +130, player="A")
                + self._book("c1", 100.0, -150, +130, player="B")
                + [self._row(100.0, "kalshi", -110, "under", player="A")])
        report = MOD.derive_entry_cost(rows, self.WINDOW)
        self.assertEqual((report["n"], report["covered"], report["subset_n"]), (2, 1, 1))
        self.assertGreater(report["subset_gain_pp"], report["gain_pp"],
                           "the covered subset must look better than the book")

    def test_a_stale_exchange_quote_outside_the_window_does_not_count(self) -> None:
        fresh = [self._row(100.0, "kalshi", -110, "under")]
        stale = [self._row(100.0 - 10 * self.WINDOW, "kalshi", -110, "under")]
        base = self._book("c1", 100.0, -150, +130)
        self.assertEqual(MOD.derive_entry_cost(base + fresh, self.WINDOW)["covered"], 1)
        self.assertEqual(MOD.derive_entry_cost(base + stale, self.WINDOW)["covered"], 0)

    def test_it_takes_the_LATEST_exchange_quote_not_the_cheapest_in_the_window(self) -> None:
        """A venue shows one price at a time. The minimum over a half hour is a
        price nobody could have taken — this script's own documented defect #1,
        and on the real shards it reads +3.172pp against +3.069pp."""
        base = self._book("c1", 1000.0, -150, +130)          # sportsbook under q=0.600
        stale = self._row(400.0, "kalshi", +200, "under")    # q=0.333 -- CHEAP, and OLD
        current = self._row(900.0, "kalshi", -145, "under")  # q=0.592 -- dear, CURRENT
        both = MOD.derive_entry_cost(base + [stale, current], self.WINDOW)
        self.assertEqual(both["covered"], 1)
        self.assertLess(both["subset_gain_pp"], 1.0,
                        "the stale +200 must not be what got priced")
        # And prove the fixture can SEE the difference. My first version of this
        # test had the price sign backwards -- it used -400 as "cheap", which is
        # q=0.8 and the DEAREST quote on the board -- so a cheapest-in-window
        # rule passed it. A fixture that cannot distinguish the two rules proves
        # nothing about which one is running, and the mutation check is what
        # caught it: the defect was reintroduced and the suite stayed green.
        only_stale = MOD.derive_entry_cost(base + [stale], self.WINDOW)
        self.assertEqual(only_stale["covered"], 1)
        self.assertGreater(only_stale["subset_gain_pp"], 20.0)

    def test_excluded_markets_stay_out_of_the_derivation(self) -> None:
        """One definition of the book, used by both halves. `in_gate_market` is
        `in_gate_book` without the side filter — de-vig needs the other leg."""
        rows = self._book("c1", 100.0, -150, +130, market="batter_home_runs")
        self.assertEqual(MOD.derive_entry_cost(rows, self.WINDOW).get("n", 0), 0)
        for market in ("batter_home_runs", "batter_hits_runs_rbis"):
            self.assertFalse(MOD.in_gate_market({"market": market}))
            self.assertFalse(MOD.in_gate_book({"market": market, "selection": "under"}))
        self.assertTrue(MOD.in_gate_market({"market": "batter_hits", "selection": "over"}))

    def test_a_one_sided_cell_cannot_be_de_vigged_and_is_refused(self) -> None:
        rows = [self._row(100.0, "draftkings", -150, "under")]
        report = MOD.derive_entry_cost(rows, self.WINDOW)
        self.assertEqual(report.get("n", 0), 0)
        self.assertEqual(report["refused"]["no_opposite_side_at_this_book"], 1)

    def test_snapshots_are_separate_cells_not_pooled(self) -> None:
        """Keyed on `captured_at`, the refresh-cycle stamp. Pooling snapshots
        would let a price from one cycle de-vig against another's."""
        rows = (self._book("c1", 100.0, -150, +130)
                + self._book("c2", 200.0, -150, +130))
        self.assertEqual(MOD.derive_entry_cost(rows, self.WINDOW)["n"], 2)

    def test_pooling_dates_is_weighted_by_n_not_a_flat_mean(self) -> None:
        """09-01 carries 37,111 cells and 09-04 carries 6,362; a flat mean over
        dates would give the thin day equal say in the gate's number."""
        fat = {"n": 900, "covered": 0, "today_pp": 4.0, "gain_pp": 0.0,
               "after_pp": 4.0, "fair": 0.6, "hold_measured_pct": 6.667,
               "subset_n": 0, "subset_today_pp": None, "subset_gain_pp": None,
               "subset_after_pp": None, "subset_fair": None, "refused": {}}
        thin = dict(fat, n=100, today_pp=1.0, after_pp=1.0, hold_measured_pct=1.667)
        pooled = MOD.combine_entry_costs([fat, thin])
        self.assertEqual(pooled["n"], 1000)
        self.assertAlmostEqual(pooled["today_pp"], 3.7, places=6)   # not 2.5

    def test_the_hold_identity_is_CHECKED_not_assumed(self) -> None:
        """Gate on the output. If the de-vig and the cost stop describing the
        same price, `cost / fair` stops reproducing the overround — and that is
        the exact failure 4.05 represents, so it must be an assertion."""
        report = MOD.derive_entry_cost(self._book("c1", 100.0, -150, +130), self.WINDOW)
        self.assertIn("hold_identity_ok", report)
        self.assertTrue(report["hold_identity_ok"])
        self.assertLess(report["hold_identity_slack_pp"], MOD.HOLD_IDENTITY_TOLERANCE_PP)

    def test_a_cost_past_the_table_is_flagged_rather_than_silently_clamped(self) -> None:
        """Today's measured 4.233pp is OUTSIDE item 07's table, which ends at
        4.05pp. Clamping is right; clamping QUIETLY is how an anchor gets
        asserted in the first place."""
        dear = MOD.derive_entry_cost(self._book("c1", 100.0, -400, +250), self.WINDOW)
        self.assertGreater(dear["today_pp"], MOD.GATE_SENSITIVITY[-1][0])
        self.assertTrue(dear["today_off_table"])
        self.assertFalse(MOD.derive_entry_cost(
            self._book("c1", 100.0, -150, +130), self.WINDOW)["today_off_table"])


class GateVerdictTests(unittest.TestCase):
    """The verdict at the corrected numbers. Measured on production shards
    2026-09-01..09-04, n=85,591 gate cells: 4.233pp -> 3.956pp, hold
    7.01% -> 6.52%, ROI +1.14%. BOTH LEGS NOT MET."""

    MEASURED_TODAY_PP = 4.233
    MEASURED_AFTER_PP = 3.956
    MEASURED_FAIR = 0.607

    def test_the_book_fails_BOTH_legs_at_the_measured_numbers(self) -> None:
        verdict = MOD.gate_verdict(self.MEASURED_AFTER_PP, self.MEASURED_FAIR)
        self.assertAlmostEqual(verdict["roi_pct"], 1.14, places=1)
        self.assertAlmostEqual(verdict["hold_pct"], 6.52, places=1)
        self.assertFalse(verdict["roi_met"])
        self.assertFalse(verdict["hold_met"])

    def test_the_asserted_constant_was_the_difference_between_ship_and_dont(self) -> None:
        """4.05 - 1.172 = 2.88pp -> +3.05%, which CLEARS the +3% bar. The
        measured 4.198 - 1.172 = 3.03pp -> +2.79%, which does not. An unmeasured
        constant was the whole decision."""
        asserted = MOD.roi_at_side_cost(MOD.GATE_PER_SIDE_ASSERTED_2026_08_31 - 1.172)
        measured = MOD.roi_at_side_cost(4.198 - 1.172)
        self.assertGreaterEqual(asserted, MOD.GATE_ROI_TARGET_PCT)
        self.assertLess(measured, MOD.GATE_ROI_TARGET_PCT)
        self.assertAlmostEqual(asserted, 3.05, places=1)
        self.assertAlmostEqual(measured, 2.79, places=1)

    def test_the_hold_leg_has_never_been_met_by_any_method(self) -> None:
        """5.8% by the old doubling, 6.52% derived, 7.09% measured directly.
        Every reading is above the 5.0% bar."""
        for hold in (5.8, 6.52, 7.09):
            self.assertGreater(hold, MOD.GATE_HOLD_TARGET_PCT)

    def test_the_old_doubling_would_have_reported_a_kinder_hold(self) -> None:
        """2 x 3.956 = 7.91%... but 2 x (4.05 - 1.172) = 5.76%, which is what
        shipped. The doubling was wrong in whichever direction the anchor was."""
        self.assertAlmostEqual(
            2 * (MOD.GATE_PER_SIDE_ASSERTED_2026_08_31 - 1.172), 5.76, places=2)
        self.assertGreater(
            MOD.two_way_hold_pct(self.MEASURED_AFTER_PP, self.MEASURED_FAIR), 5.76)


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

    def test_the_healed_shard_reading_fails_both_conditions(self) -> None:
        """THE CURRENT READING. 2026-09-01 re-measured after `e78aee52` repaired
        the shard: gate book n=1,235, gain +0.824pp, per-side 4.05 -> 3.23,
        two-way hold 6.5%, ROI +2.43%. Shortfall 0.57 points, wider than the
        clobbered copy's 0.35."""
        side_cost = MOD.GATE_PER_SIDE_ASSERTED_2026_08_31 - 0.824
        roi = MOD.roi_at_side_cost(side_cost)
        self.assertAlmostEqual(roi, 2.43, places=1)
        self.assertLess(roi, MOD.GATE_ROI_TARGET_PCT)
        self.assertGreater(2 * side_cost, MOD.GATE_HOLD_TARGET_PCT)

    def test_the_healed_reading_is_WORSE_than_the_clobbered_one(self) -> None:
        """The counterintuitive direction, pinned so nobody 'restores' the older
        and friendlier number. Repairing a file that had LOST rows made the
        exchange look WORSE: the truncation had preserved exactly the window
        where it looks best (64.5% taken / +1.021pp before the old cutoff
        against 40.2% / +0.737pp after), so the clobber was biased in the
        exchange's favour."""
        healed = MOD.roi_at_side_cost(MOD.GATE_PER_SIDE_ASSERTED_2026_08_31 - 0.824)
        clobbered = MOD.roi_at_side_cost(MOD.GATE_PER_SIDE_ASSERTED_2026_08_31 - 0.949)
        self.assertLess(healed, clobbered)
        self.assertAlmostEqual(clobbered - healed, 0.22, places=1)

    def test_the_superseded_bound_readings_still_fail_both_conditions(self) -> None:
        """HISTORICAL, from the CLOBBERED copy: +0.955pp (m=0.5) and +0.703pp
        (m=1.0), before the multiplier was resolved and before the shard was
        repaired. Kept because they exercise the interpolator across a wide
        span, and because the decision has survived every restatement."""
        for gain, expected_roi in ((0.955, 2.66), (0.703, 2.22)):
            side_cost = MOD.GATE_PER_SIDE_ASSERTED_2026_08_31 - gain
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

    def test_the_superseded_resolved_reading_still_fails_both_conditions(self) -> None:
        """HISTORICAL, and superseded by the healed-shard reading in
        `SensitivityTests`. 2026-09-01 on the CLOBBERED copy, per-series
        multipliers: +0.949pp -> +2.65%. Resolving the multiplier COLLAPSED the
        bound to its optimistic end — it did not close the gate, and saying it
        was 'worth 0.44 points' overstated it. The current number is +2.43%."""
        side_cost = MOD.GATE_PER_SIDE_ASSERTED_2026_08_31 - 0.949
        roi = MOD.roi_at_side_cost(side_cost)
        self.assertAlmostEqual(roi, 2.65, places=1)
        self.assertLess(roi, MOD.GATE_ROI_TARGET_PCT)
        self.assertGreater(2 * side_cost, MOD.GATE_HOLD_TARGET_PCT)


def _row(stamp: float, book: str, probability: float = 0.5, **over) -> tuple:
    payload = {"event_id": "e1", "market": "batter_hits", "player_name": "A",
               "line": 0.5, "selection": "under"}
    payload.update(over)
    return (stamp, book, probability, payload)


class FeedOverlapGuardTests(unittest.TestCase):
    """The shard can be clobbered by a competing whole-file publish, and the
    damage is INVISIBLE in the output — every surviving row is real and
    correctly aligned, so a clobbered date still prints a tidy ROI. Measured
    2026-09-01: the sportsbook feed stops at 20:18:49 while exchange rows run to
    22:22:27, and 76% of the 'no time-aligned quote' exclusions are that gap."""

    def test_a_healthy_date_passes(self) -> None:
        rows = [_row(t, "fanduel") for t in range(0, 1000, 100)]
        rows += [_row(t, "kalshi") for t in range(0, 900, 100)]
        self.assertTrue(MOD.feed_overlap(rows)["ok"])

    def test_a_clobbered_tail_is_caught(self) -> None:
        """Sportsbook stops early; most exchange rows come after it."""
        rows = [_row(t, "fanduel") for t in range(0, 300, 100)]
        rows += [_row(t, "kalshi") for t in range(0, 2000, 100)]
        overlap = MOD.feed_overlap(rows)
        self.assertFalse(overlap["ok"])
        self.assertIn("clobber", overlap["reason"])

    def test_the_real_2026_09_01_shape_is_refused(self) -> None:
        """The actual measured proportion — 46.1% matchable — must NOT pass.
        This is the date the published +2.65% came from."""
        rows = [_row(float(i), "fanduel") for i in range(461)]
        rows += [_row(float(i), "kalshi") for i in range(461)]
        rows += [_row(float(1000 + i), "kalshi") for i in range(539)]
        overlap = MOD.feed_overlap(rows)
        self.assertAlmostEqual(overlap["matchable"], 0.461, places=2)
        self.assertFalse(overlap["ok"])

    def test_an_absent_feed_is_refused_not_scored(self) -> None:
        """08-26..08-31 have zero exchange rows. That is 'no data', which must
        not be reported as an overlap failure or folded into a total."""
        for rows in ([_row(1.0, "fanduel")], [_row(1.0, "kalshi")], []):
            overlap = MOD.feed_overlap(rows)
            self.assertFalse(overlap["ok"])
            self.assertNotIn("book_span", overlap)

    def test_the_floor_is_a_named_constant_not_a_literal(self) -> None:
        self.assertGreater(MOD.FEED_OVERLAP_FLOOR, 0.5)
        self.assertLess(MOD.FEED_OVERLAP_FLOOR, 1.0)


class DateExpansionTests(unittest.TestCase):
    def test_a_span_expands_inclusively(self) -> None:
        """'A full week' must be 7 dates, not 6 — an off-by-one here silently
        shrinks the sample the conclusion rests on."""
        dates = MOD.expand_dates([], "2026-09-02", "2026-09-08")
        self.assertEqual(len(dates), 7)
        self.assertEqual(dates[0], "2026-09-02")
        self.assertEqual(dates[-1], "2026-09-08")

    def test_a_single_day_span_is_one_date(self) -> None:
        self.assertEqual(MOD.expand_dates([], "2026-09-01", "2026-09-01"), ["2026-09-01"])

    def test_repeated_and_comma_forms_both_work(self) -> None:
        self.assertEqual(MOD.expand_dates(["a", "b,c"], "", ""), ["a", "b", "c"])

    def test_a_reversed_span_is_refused(self) -> None:
        with self.assertRaises(SystemExit):
            MOD.expand_dates([], "2026-09-08", "2026-09-02")


if __name__ == "__main__":
    unittest.main()
