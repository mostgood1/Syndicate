"""Fractional-Kelly board staking.

Kelly assumes the probability estimate is CORRECT and is punishing when it
is not. Several of this repo's probability models say in their own
docstrings that they are not backtested, and settlement was only just
enabled so most markets have zero settled bets. Board staking therefore
shrinks twice -- a fixed fractional-Kelly multiplier, and a credibility
factor driven by real settled sample size.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from syndicate.features.bankroll_manager import _sample_credibility
from syndicate.features.bankroll_manager import compute_board_stake


def _candidate(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {"model_probability": 0.62, "odds": -110, "confidence": 70}
    base.update(overrides)
    return base


class SampleCredibilityTests(unittest.TestCase):
    def test_zero_settled_bets_floors_rather_than_zeroes(self) -> None:
        # A silent 0 stake reads as a broken feature; a small honest one
        # communicates "we have no evidence yet" without hiding the card.
        self.assertEqual(_sample_credibility(0), 0.25)
        self.assertEqual(_sample_credibility(None), 0.25)

    def test_credibility_rises_with_settled_evidence(self) -> None:
        self.assertLess(_sample_credibility(10), _sample_credibility(40))

    def test_credibility_saturates_at_one(self) -> None:
        self.assertEqual(_sample_credibility(50), 1.0)
        self.assertEqual(_sample_credibility(5000), 1.0)


class ComputeBoardStakeTests(unittest.TestCase):
    def test_stake_is_far_below_full_kelly_with_no_evidence(self) -> None:
        sizing = compute_board_stake(_candidate(), settled_sample_size=0)
        full_kelly = sizing["kelly_fraction"]
        self.assertGreater(full_kelly, 0.0)
        # quarter Kelly x 0.25 credibility = ~1/16th of full Kelly.
        self.assertLess(sizing["stake_fraction"], full_kelly * 0.1)

    def test_more_settled_evidence_permits_a_larger_stake(self) -> None:
        thin = compute_board_stake(_candidate(), settled_sample_size=0)
        proven = compute_board_stake(_candidate(), settled_sample_size=200)
        self.assertGreater(proven["stake_fraction"], thin["stake_fraction"])

    def test_no_edge_produces_no_stake(self) -> None:
        # Model probability at/below the vig-inclusive implied probability.
        sizing = compute_board_stake(_candidate(model_probability=0.40), settled_sample_size=200)
        self.assertEqual(sizing["stake_fraction"], 0.0)

    def test_stake_never_exceeds_the_cap(self) -> None:
        sizing = compute_board_stake(
            _candidate(model_probability=0.99, odds=1000, confidence=99),
            settled_sample_size=5000,
        )
        self.assertLessEqual(sizing["stake_fraction"], sizing["cap_fraction"])

    def test_shrinkage_factors_are_reported_for_inspection(self) -> None:
        sizing = compute_board_stake(_candidate(), settled_sample_size=12)
        self.assertIn("kelly_multiplier", sizing)
        self.assertIn("sample_credibility", sizing)
        self.assertEqual(sizing["settled_sample_size"], 12)
        self.assertEqual(sizing["stake_basis"], "fractional_kelly_shrunk_by_settled_sample")

    def test_stake_units_track_the_fraction(self) -> None:
        sizing = compute_board_stake(_candidate(), settled_sample_size=200)
        self.assertAlmostEqual(sizing["stake_units"], sizing["stake_fraction"] * 100.0, places=2)

    def test_multiplier_is_configurable_and_bounded(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_KELLY_FRACTION_MULTIPLIER": "0.5"}):
            half = compute_board_stake(_candidate(), settled_sample_size=200)
        with patch.dict(os.environ, {"SYNDICATE_KELLY_FRACTION_MULTIPLIER": "0.25"}):
            quarter = compute_board_stake(_candidate(), settled_sample_size=200)
        self.assertGreater(half["stake_fraction"], quarter["stake_fraction"])

    def test_garbage_multiplier_falls_back_to_the_conservative_default(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_KELLY_FRACTION_MULTIPLIER": "not-a-number"}):
            sizing = compute_board_stake(_candidate(), settled_sample_size=200)
        self.assertEqual(sizing["kelly_multiplier"], 0.25)

    def test_missing_odds_does_not_raise(self) -> None:
        sizing = compute_board_stake({"model_probability": 0.6}, settled_sample_size=0)
        self.assertGreaterEqual(sizing["stake_fraction"], 0.0)


class AttachBoardStakesTests(unittest.TestCase):
    """End-to-end over the real board hook.

    _attach_board_stakes wraps each candidate in a broad `except: continue`
    so a sizing failure can never drop a real opportunity off the board.
    That also means a NameError inside it would be swallowed silently and
    ship a board with no stakes at all -- which is exactly what happened
    during development (_coerce_float does not exist in that module). These
    assert stakes are actually ATTACHED, not merely that nothing raised.
    """

    def test_stakes_are_attached_to_every_candidate(self) -> None:
        from pipeline.intelligence_state import IntelligenceStateService

        pool = [
            {"sport_slug": "mlb", "model_probability": 0.62, "odds": -110, "confidence": 70},
            {"sport_slug": "wnba", "model_probability": 0.58, "odds": 120, "confidence": 65},
        ]
        IntelligenceStateService._attach_board_stakes(pool)
        for candidate in pool:
            self.assertIn("stake", candidate)
            self.assertIn("stake_fraction", candidate["stake"])
            self.assertGreaterEqual(candidate["stake"]["stake_fraction"], 0.0)

    def test_settled_sample_size_is_read_from_the_historical_profile(self) -> None:
        from pipeline.intelligence_state import IntelligenceStateService

        pool = [
            {
                "sport_slug": "mlb",
                "model_probability": 0.62,
                "odds": -110,
                "confidence": 70,
                "historical_profile": {"sample_size": 200},
            }
        ]
        IntelligenceStateService._attach_board_stakes(pool)
        self.assertEqual(pool[0]["stake"]["settled_sample_size"], 200)
        self.assertGreater(pool[0]["stake"]["sample_credibility"], 0.25)

    def test_non_dict_entries_are_skipped_without_raising(self) -> None:
        from pipeline.intelligence_state import IntelligenceStateService

        pool = [None, "junk", {"sport_slug": "mlb", "model_probability": 0.6, "odds": -110}]
        IntelligenceStateService._attach_board_stakes(pool)
        self.assertIn("stake", pool[2])


if __name__ == "__main__":
    unittest.main()
