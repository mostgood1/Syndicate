"""A published board must not drop a projected total or margin it was given.

WHY THIS FILE EXISTS. `_shared_predictions` read the projected means from
`predictions`, then `sim.score`, then `score` -- and never from
`sim.periods.full`, which is where NFL's cards put the complete four-field
projection. `nfl/preseason_cards.py` and `nfl/cards.py` set all four in
`periods.full` and only TWO (away_mean/home_mean) in `sim.score`.

MEASURED ON PRODUCTION 2026-08-18, both NFL boards, 16 of 16 games each:

    home_mean 100%   away_mean 100%   total_mean 0%   margin_mean 0%

The artifact had them all along -- `SmartSimNflPreseasonProjection` carries
`margin_mean` and `total_mean` as required CSV columns, and the card wrote them
into `periods.full`. They were lost in transit, so the board could show a
projected SCORE but no projected SPREAD or TOTAL: on a betting product, the two
numbers a market line is actually compared against.

The same shape as the NCAAF cap fix earlier that day, and the same lesson: the
value being present upstream is not the value being reachable downstream.
"""
from __future__ import annotations

import unittest

from syndicate.features.shared.publication_adapter import _shared_predictions


class PublishedProjectionMeansTest(unittest.TestCase):
    def _nfl_card(self) -> dict:
        """The real NFL preseason card shape (`preseason_cards.py`).

        Deliberately mirrors the producer rather than an idealised payload:
        four fields in `periods.full`, TWO in `score`. That asymmetry IS the
        defect, so a fixture that filled both would test nothing.
        """
        return {
            "sim": {
                "periods": {
                    "full": {
                        "away_mean": 19.305,
                        "home_mean": 22.47,
                        "total_mean": 41.775,
                        "margin_mean": 3.165,
                        "p_home_win": 0.615,
                    }
                },
                "score": {"away_mean": 19.305, "home_mean": 22.47},
            },
            "predictions": {"probabilities": {"home_win": 0.615, "away_win": 0.385}},
        }

    def test_full_period_projection_reaches_the_payload(self) -> None:
        out = _shared_predictions(self._nfl_card())
        self.assertAlmostEqual(out["home_mean"], 22.47)
        self.assertAlmostEqual(out["away_mean"], 19.305)
        self.assertAlmostEqual(out["total_mean"], 41.775, msg="total_mean must come from sim.periods.full")
        self.assertAlmostEqual(out["margin_mean"], 3.165, msg="margin_mean must come from sim.periods.full")

    def test_total_and_margin_are_derived_when_only_scores_exist(self) -> None:
        """Definitional, not a guess: total = home + away, margin = home - away.

        `game_board_contract._normalize_game` already derives exactly this for
        its market tiles; it simply never reached the published payload.
        """
        out = _shared_predictions({"sim": {"score": {"away_mean": 20.0, "home_mean": 24.0}}})
        self.assertEqual(out["total_mean"], 44.0)
        self.assertEqual(out["margin_mean"], 4.0)

    def test_an_explicit_value_is_never_overwritten_by_derivation(self) -> None:
        """The fallback may only fill a hole.

        A producer whose own margin disagrees with home-minus-away (a shrunk or
        calibrated margin, which preseason legitimately produces) must keep its
        own number.
        """
        out = _shared_predictions({
            "predictions": {
                "away_mean": 20.0, "home_mean": 24.0,
                "total_mean": 999.0, "margin_mean": -7.0,
            },
            "sim": {"periods": {"full": {"total_mean": 1.0, "margin_mean": 2.0}}},
        })
        self.assertEqual(out["total_mean"], 999.0)
        self.assertEqual(out["margin_mean"], -7.0)

    def test_precedence_is_predictions_then_score_then_full_period(self) -> None:
        """`sim.score` must still outrank `periods.full`, as it did before."""
        out = _shared_predictions({
            "sim": {
                "score": {"away_mean": 1.0, "home_mean": 2.0, "total_mean": 3.0},
                "periods": {"full": {"away_mean": 90.0, "home_mean": 90.0, "total_mean": 180.0}},
            }
        })
        self.assertEqual(out["total_mean"], 3.0)
        self.assertEqual(out["home_mean"], 2.0)

    def test_absent_stays_none_and_never_becomes_zero(self) -> None:
        """0.0 is a projection; None is 'no projection'. A board that shows 0.0
        where it has nothing is asserting a 0-0 game."""
        out = _shared_predictions({})
        for key in ("home_mean", "away_mean", "total_mean", "margin_mean"):
            self.assertIsNone(out[key], "%s must stay None when nothing supplies it" % key)

    def test_a_partial_score_does_not_derive_a_half_truth(self) -> None:
        """One score alone cannot produce a total or a margin."""
        out = _shared_predictions({"sim": {"score": {"home_mean": 24.0}}})
        self.assertEqual(out["home_mean"], 24.0)
        self.assertIsNone(out["away_mean"])
        self.assertIsNone(out["total_mean"])
        self.assertIsNone(out["margin_mean"])


if __name__ == "__main__":
    unittest.main()
