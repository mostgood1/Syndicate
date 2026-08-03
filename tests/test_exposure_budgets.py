"""Correlation exposure budgets.

The greedy low-correlation selection this replaces was removed for good
reason (a 0.65 threshold collapsed 100+ candidates to ~5), but nothing took
its place -- so the board could serve five legs off one game with no
exposure penalty, each sized as if independent. Five correlated legs at 2%
each is a 10% swing on one game, not five diversified 2% bets.

Shrinks rather than drops, matching the standing call that board visibility
stays complete.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from syndicate.features.bankroll_manager import _exposure_group_key
from syndicate.features.bankroll_manager import apply_exposure_budgets


def _leg(event_id: str, stake: float, score: float, **extra: object) -> dict[str, object]:
    row: dict[str, object] = {
        "sport_slug": "mlb",
        "event_id": event_id,
        "adjusted_score": score,
        "stake": {"stake_fraction": stake, "stake_units": stake * 100.0},
    }
    row.update(extra)
    return row


class ExposureGroupKeyTests(unittest.TestCase):
    def test_same_event_groups_together(self) -> None:
        self.assertEqual(_exposure_group_key(_leg("123", 0.02, 1.0)), _exposure_group_key(_leg("123", 0.01, 2.0)))

    def test_different_events_do_not_group(self) -> None:
        self.assertNotEqual(_exposure_group_key(_leg("123", 0.02, 1.0)), _exposure_group_key(_leg("456", 0.02, 1.0)))

    def test_same_id_in_different_sports_does_not_collide(self) -> None:
        a = {"sport_slug": "mlb", "event_id": "1"}
        b = {"sport_slug": "wnba", "event_id": "1"}
        self.assertNotEqual(_exposure_group_key(a), _exposure_group_key(b))

    def test_falls_back_to_matchup_when_no_id_was_stamped(self) -> None:
        # A board whose builders never stamped an id must still be budgeted,
        # not silently treated as all-independent.
        key = _exposure_group_key({"sport_slug": "mlb", "matchup": "CLE @ CIN"})
        self.assertIn("cle @ cin", key)


class ApplyExposureBudgetsTests(unittest.TestCase):
    def test_correlated_legs_are_shrunk_not_dropped(self) -> None:
        pool = [_leg("g1", 0.02, 5.0), _leg("g1", 0.02, 4.0), _leg("g1", 0.02, 3.0)]
        apply_exposure_budgets(pool)
        # Every candidate survives -- visibility stays complete.
        self.assertEqual(len(pool), 3)
        for candidate in pool:
            self.assertIn("stake", candidate)

    def test_best_ranked_leg_keeps_the_largest_stake(self) -> None:
        pool = [_leg("g1", 0.02, 3.0), _leg("g1", 0.02, 9.0)]
        apply_exposure_budgets(pool)
        best = next(c for c in pool if c["adjusted_score"] == 9.0)
        worst = next(c for c in pool if c["adjusted_score"] == 3.0)
        self.assertGreater(best["stake"]["stake_fraction"], worst["stake"]["stake_fraction"])

    def test_total_game_exposure_respects_the_cap(self) -> None:
        pool = [_leg("g1", 0.04, float(10 - i)) for i in range(6)]
        with patch.dict(os.environ, {"SYNDICATE_MAX_GAME_EXPOSURE_FRACTION": "0.05"}):
            apply_exposure_budgets(pool)
        total = sum(c["stake"]["stake_fraction"] for c in pool)
        self.assertLessEqual(total, 0.05 + 1e-6)

    def test_uncorrelated_single_leg_is_left_alone(self) -> None:
        pool = [_leg("g1", 0.01, 5.0), _leg("g2", 0.01, 5.0)]
        apply_exposure_budgets(pool)
        for candidate in pool:
            self.assertAlmostEqual(candidate["stake"]["stake_fraction"], 0.01, places=6)

    def test_original_stake_is_preserved_for_inspection(self) -> None:
        pool = [_leg("g1", 0.02, 5.0), _leg("g1", 0.02, 4.0)]
        apply_exposure_budgets(pool)
        for candidate in pool:
            self.assertIn("stake_fraction_pre_exposure", candidate["stake"])
            self.assertAlmostEqual(candidate["stake"]["stake_fraction_pre_exposure"], 0.02, places=6)

    def test_group_size_and_cap_flag_are_reported(self) -> None:
        pool = [_leg("g1", 0.04, 5.0), _leg("g1", 0.04, 4.0), _leg("g1", 0.04, 3.0)]
        with patch.dict(os.environ, {"SYNDICATE_MAX_GAME_EXPOSURE_FRACTION": "0.05"}):
            apply_exposure_budgets(pool)
        for candidate in pool:
            self.assertEqual(candidate["stake"]["exposure_group_size"], 3)
            self.assertTrue(candidate["stake"]["exposure_capped"])

    def test_stake_units_stay_consistent_with_the_fraction(self) -> None:
        pool = [_leg("g1", 0.02, 5.0), _leg("g1", 0.02, 4.0)]
        apply_exposure_budgets(pool)
        for candidate in pool:
            self.assertAlmostEqual(
                candidate["stake"]["stake_units"],
                candidate["stake"]["stake_fraction"] * 100.0,
                places=2,
            )

    def test_summary_reports_what_was_touched(self) -> None:
        pool = [_leg("g1", 0.04, 5.0), _leg("g1", 0.04, 4.0), _leg("g2", 0.001, 1.0)]
        summary = apply_exposure_budgets(pool)
        self.assertEqual(summary["groups"], 2)
        self.assertGreaterEqual(summary["adjusted_groups"], 1)

    def test_candidates_without_a_stake_are_ignored(self) -> None:
        pool = [{"sport_slug": "mlb", "event_id": "g1"}, _leg("g1", 0.02, 5.0)]
        apply_exposure_budgets(pool)
        self.assertNotIn("stake", pool[0])
        self.assertIn("stake", pool[1])

    def test_zero_stakes_do_not_divide_by_zero(self) -> None:
        pool = [_leg("g1", 0.0, 5.0), _leg("g1", 0.0, 4.0)]
        apply_exposure_budgets(pool)
        for candidate in pool:
            self.assertEqual(candidate["stake"]["stake_fraction"], 0.0)


if __name__ == "__main__":
    unittest.main()
