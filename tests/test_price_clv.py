"""Price-based closing-line value.

The existing `_clv` measures LINE movement only, which is structurally
blind to moneylines (no line to move) and misses every market where the
number holds while the price walks -- a prop at 5.5 going -110 -> -130 is
real CLV that line CLV scores as zero. CLV also matters disproportionately
because it converges on far fewer settled bets than win rate does.
"""

from __future__ import annotations

import unittest

from syndicate.features.shared.intelligence_evaluation import _implied_probability_from_american
from syndicate.features.shared.intelligence_evaluation import _price_clv
from syndicate.features.shared.intelligence_evaluation import settle_result


class ImpliedProbabilityTests(unittest.TestCase):
    def test_even_money_is_a_half(self) -> None:
        self.assertAlmostEqual(_implied_probability_from_american(100), 0.5, places=6)
        self.assertAlmostEqual(_implied_probability_from_american(-100), 0.5, places=6)

    def test_favourite_and_underdog_sit_either_side_of_even(self) -> None:
        self.assertGreater(_implied_probability_from_american(-200), 0.5)
        self.assertLess(_implied_probability_from_american(200), 0.5)

    def test_standard_juice_is_about_52_percent(self) -> None:
        self.assertAlmostEqual(_implied_probability_from_american(-110), 0.5238, places=3)

    def test_missing_and_zero_are_declined(self) -> None:
        self.assertIsNone(_implied_probability_from_american(None))
        self.assertIsNone(_implied_probability_from_american(0))
        self.assertIsNone(_implied_probability_from_american("not-a-price"))


class PriceClvTests(unittest.TestCase):
    @staticmethod
    def _record(bet_price: object, closing_price: object) -> dict[str, object]:
        return {"recommendation": {"odds": bet_price}, "closing_price": closing_price}

    def test_beating_the_close_is_positive(self) -> None:
        # Taken at +120, closed at -110: the market moved toward the bet.
        value = _price_clv([self._record(120, -110)])
        self.assertIsNotNone(value)
        self.assertGreater(value, 0)

    def test_losing_to_the_close_is_negative(self) -> None:
        value = _price_clv([self._record(-130, 105)])
        self.assertLess(value, 0)

    def test_unchanged_price_is_zero_clv(self) -> None:
        self.assertAlmostEqual(_price_clv([self._record(-110, -110)]), 0.0, places=6)

    def test_moneylines_are_scored_even_though_they_have_no_line(self) -> None:
        # The exact gap line CLV cannot see: no line field anywhere.
        value = _price_clv([{"recommendation": {"odds": -150}, "closing_price": -200}])
        self.assertIsNotNone(value)
        self.assertGreater(value, 0)

    def test_records_without_a_closing_price_are_skipped_not_zeroed(self) -> None:
        # Scoring these as 0.0 would silently drag the average toward zero
        # and make a real edge look like noise.
        self.assertIsNone(_price_clv([self._record(-110, None)]))

    def test_mixed_records_average_only_the_scorable_ones(self) -> None:
        records = [self._record(120, -110), self._record(-110, None)]
        single = _price_clv([self._record(120, -110)])
        self.assertAlmostEqual(_price_clv(records), single, places=6)

    def test_price_is_read_from_alternate_field_names(self) -> None:
        record = {"recommendation": {"price": 120}, "closing_price": -110}
        self.assertGreater(_price_clv([record]), 0)


class SettleResultClosingPriceTests(unittest.TestCase):
    def test_closing_price_is_persisted_onto_the_settled_record(self) -> None:
        settled = settle_result(
            record={"recommendation_id": "abc", "recommendation": {"odds": 120}},
            result="win",
            pnl=1.2,
            closing_line=5.5,
            closing_price=-110,
            persist=False,
        )
        self.assertEqual(settled["closing_price"], -110)
        self.assertEqual(settled["closing_line"], 5.5)

    def test_omitting_closing_price_keeps_existing_callers_working(self) -> None:
        settled = settle_result(
            record={"recommendation_id": "abc"},
            result="loss",
            pnl=-1.0,
            closing_line=5.5,
            persist=False,
        )
        self.assertIsNone(settled["closing_price"])

    def test_existing_record_closing_price_is_preserved_when_not_passed(self) -> None:
        settled = settle_result(
            record={"recommendation_id": "abc", "closing_price": -125},
            result="win",
            pnl=1.0,
            closing_line=None,
            persist=False,
        )
        self.assertEqual(settled["closing_price"], -125)


if __name__ == "__main__":
    unittest.main()
