from __future__ import annotations

import unittest

from syndicate.features.correlation_engine import DEFAULT_BOARD_CORRELATION_BADGE_THRESHOLD
from syndicate.features.correlation_engine import attach_board_correlation_flags


class AttachBoardCorrelationFlagsTests(unittest.TestCase):
    """Layer 2 Phase 4. Board-level correlation badging (annotate, never
    suppress -- explicit user call): the CLE@CIN doubleheader screenshot
    that started this thread showed 5 markets on one game as if 5
    independent opportunities. This flags that pattern instead of hiding
    it.
    """

    def _mlb_pair_same_game(self) -> tuple[dict, dict]:
        # Measured live: same matchup/event_id/team, different market ->
        # correlation_score 0.56, above the 0.5 default threshold.
        candidate_a = {
            "sport_slug": "mlb",
            "matchup": "CLE @ CIN",
            "event_id": "game-824489",
            "market": "moneyline",
            "selection": "Home ML",
            "team": "CIN",
            "recommendation_id": "reco_a",
        }
        candidate_b = {
            "sport_slug": "mlb",
            "matchup": "CLE @ CIN",
            "event_id": "game-824489",
            "market": "spread",
            "selection": "Home -1.5",
            "team": "CIN",
            "recommendation_id": "reco_b",
        }
        return candidate_a, candidate_b

    def test_flags_a_highly_correlated_same_game_pair(self) -> None:
        candidate_a, candidate_b = self._mlb_pair_same_game()
        candidates = [candidate_a, candidate_b]

        attach_board_correlation_flags(candidates)

        self.assertEqual(len(candidate_a["correlated_with"]), 1)
        self.assertEqual(len(candidate_b["correlated_with"]), 1)
        flag = candidate_a["correlated_with"][0]
        self.assertEqual(flag["recommendation_id"], "reco_b")
        self.assertTrue(flag["same_game"])
        self.assertGreaterEqual(flag["correlation_score"], DEFAULT_BOARD_CORRELATION_BADGE_THRESHOLD)
        # Symmetric: b's flag points back at a.
        self.assertEqual(candidate_b["correlated_with"][0]["recommendation_id"], "reco_a")

    def test_does_not_flag_unrelated_candidates(self) -> None:
        candidate_a, _ = self._mlb_pair_same_game()
        candidate_c = {
            "sport_slug": "mlb",
            "matchup": "LAD @ SFG",
            "event_id": "game-999",
            "market": "moneyline",
            "selection": "Home ML",
            "team": "SFG",
            "recommendation_id": "reco_c",
        }
        candidates = [candidate_a, candidate_c]

        attach_board_correlation_flags(candidates)

        self.assertEqual(candidate_a["correlated_with"], [])
        self.assertEqual(candidate_c["correlated_with"], [])

    def test_every_candidate_gets_the_key_even_with_zero_matches(self) -> None:
        candidates = [
            {"sport_slug": "mlb", "matchup": "LAD @ SFG", "market": "moneyline", "recommendation_id": "solo"}
        ]

        attach_board_correlation_flags(candidates)

        self.assertIn("correlated_with", candidates[0])
        self.assertEqual(candidates[0]["correlated_with"], [])

    def test_never_compares_across_different_sports(self) -> None:
        # Same matchup text, different sport (a coincidental abbreviation
        # collision) -- must never cross-flag; correlation is only ever
        # meaningful within one sport's own games.
        candidate_mlb = {
            "sport_slug": "mlb",
            "matchup": "NYY @ BOS",
            "event_id": "mlb-1",
            "market": "moneyline",
            "recommendation_id": "reco_mlb",
        }
        candidate_nba = {
            "sport_slug": "nba",
            "matchup": "NYY @ BOS",
            "event_id": "mlb-1",
            "market": "moneyline",
            "recommendation_id": "reco_nba",
        }
        candidates = [candidate_mlb, candidate_nba]

        attach_board_correlation_flags(candidates)

        self.assertEqual(candidate_mlb["correlated_with"], [])
        self.assertEqual(candidate_nba["correlated_with"], [])

    def test_respects_a_custom_threshold(self) -> None:
        candidate_a, candidate_b = self._mlb_pair_same_game()
        candidates = [candidate_a, candidate_b]

        # Measured score is 0.56 -- a threshold just above it must suppress
        # the flag entirely.
        attach_board_correlation_flags(candidates, threshold=0.9)

        self.assertEqual(candidate_a["correlated_with"], [])
        self.assertEqual(candidate_b["correlated_with"], [])


if __name__ == "__main__":
    unittest.main()
