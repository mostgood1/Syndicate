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


if __name__ == "__main__":
    unittest.main()
