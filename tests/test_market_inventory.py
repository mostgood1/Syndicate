from __future__ import annotations

import unittest

from syndicate.features.shared.market_inventory import (
    JOIN_STATUS_MATCHED,
    JOIN_STATUS_NEEDS_RESIM,
    JOIN_STATUS_NO_SIM_COVERAGE,
    join_odds_to_sim,
)


class JoinOddsToSimTests(unittest.TestCase):
    def test_game_market_matches_sim_row_regardless_of_side(self) -> None:
        # A single sim win-probability projection informs both the home and
        # away moneyline quotes -- both sides should join to the same row.
        odds_rows = [
            {"game_id": "824247", "market": "moneyline", "period": "full_game", "entity": None, "side": "home", "odds": -229},
            {"game_id": "824247", "market": "moneyline", "period": "full_game", "entity": None, "side": "away", "odds": 190},
        ]
        sim_rows = [
            {"game_id": "824247", "market": "moneyline", "period": "full_game", "entity": None, "sim_projection": 0.695, "sim_source": "locked_policy_2026-07-23"},
        ]

        inventory = join_odds_to_sim(odds_rows, sim_rows)

        self.assertEqual(len(inventory), 2)
        for row in inventory:
            self.assertEqual(row["join_status"], JOIN_STATUS_MATCHED)
            self.assertEqual(row["sim_projection"], 0.695)
            self.assertEqual(row["sim_source"], "locked_policy_2026-07-23")
            self.assertTrue(row["is_eligible"])

    def test_prop_matches_sim_projection_for_same_entity(self) -> None:
        odds_rows = [
            {"game_id": "824406", "market": "hits", "period": "full_game", "entity": "Brooks Lee", "side": "over", "line": 1.5, "odds": -120},
        ]
        sim_rows = [
            {"game_id": "824406", "market": "hits", "period": "full_game", "entity": "Brooks Lee", "sim_projection": 1.3, "sim_source": "mlb_daily_sim_2026-07-23"},
        ]

        inventory = join_odds_to_sim(odds_rows, sim_rows)

        self.assertEqual(inventory[0]["join_status"], JOIN_STATUS_MATCHED)
        self.assertEqual(inventory[0]["sim_projection"], 1.3)
        self.assertTrue(inventory[0]["is_eligible"])

    def test_unmatched_market_with_no_sim_coverage_at_all(self) -> None:
        # A real quoted line the book offers, but nothing modeled this
        # market/period for ANY entity -- a genuine coverage gap, not a
        # world-changed-since-the-sim-ran situation. Still eligible: it's
        # just unscored, not stale.
        odds_rows = [
            {"game_id": "824247", "market": "first_5_total", "period": "first_5", "entity": None, "side": "over", "line": 4.5, "odds": -110},
        ]
        sim_rows = [
            {"game_id": "824247", "market": "moneyline", "period": "full_game", "entity": None, "sim_projection": 0.695, "sim_source": "locked_policy_2026-07-23"},
        ]

        inventory = join_odds_to_sim(odds_rows, sim_rows)

        self.assertEqual(inventory[0]["join_status"], JOIN_STATUS_NO_SIM_COVERAGE)
        self.assertIsNone(inventory[0]["sim_projection"])
        self.assertTrue(inventory[0]["is_eligible"])

    def test_prop_for_different_entity_than_sim_flags_needs_resim(self) -> None:
        # The sim projected R. Smith as the starting pitcher for this
        # market/period; the current odds feed shows a prop for a
        # different pitcher entirely -- a pitching change happened since
        # the sim ran. This must be flagged, not silently dropped or
        # treated as an ordinary coverage gap.
        odds_rows = [
            {"game_id": "824893", "market": "strikeouts", "period": "full_game", "entity": "J. Cronenworth", "side": "over", "line": 5.5, "odds": -115},
        ]
        sim_rows = [
            {"game_id": "824893", "market": "strikeouts", "period": "full_game", "entity": "R. Smith", "sim_projection": 6.2, "sim_source": "mlb_daily_sim_2026-07-23"},
        ]

        inventory = join_odds_to_sim(odds_rows, sim_rows)

        row = inventory[0]
        self.assertEqual(row["join_status"], JOIN_STATUS_NEEDS_RESIM)
        self.assertIsNone(row["sim_projection"])
        self.assertFalse(row["is_eligible"])
        self.assertIn("R. Smith", row["join_note"])
        self.assertIn("J. Cronenworth", row["join_note"])

    def test_entity_matching_is_case_insensitive(self) -> None:
        odds_rows = [
            {"game_id": "1", "market": "hits", "period": "full_game", "entity": "brooks lee", "odds": -120},
        ]
        sim_rows = [
            {"game_id": "1", "market": "hits", "period": "full_game", "entity": "Brooks Lee", "sim_projection": 1.3, "sim_source": "sim"},
        ]

        inventory = join_odds_to_sim(odds_rows, sim_rows)

        self.assertEqual(inventory[0]["join_status"], JOIN_STATUS_MATCHED)

    def test_non_dict_rows_are_skipped_without_raising(self) -> None:
        inventory = join_odds_to_sim([None, {"game_id": "1", "market": "hits", "period": "full_game", "entity": "A"}], [None, "not a dict"])
        self.assertEqual(len(inventory), 1)
        self.assertEqual(inventory[0]["join_status"], JOIN_STATUS_NO_SIM_COVERAGE)


if __name__ == "__main__":
    unittest.main()
