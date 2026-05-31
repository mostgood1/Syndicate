from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.wnba.cards import _supplement_games_with_live_state


class WnbaCardsMergeAliasTests(unittest.TestCase):
    def test_live_aliases_do_not_create_duplicate_cards(self) -> None:
        processed_games = [
            {
                "gamePk": "1",
                "event_id": "",
                "away_tri": "LAS",
                "home_tri": "WSH",
                "status": "Scheduled",
                "detail": "2026-05-31T00:00:00+00:00",
            }
        ]
        live_games = [
            {
                "gamePk": "LVA@WSH",
                "event_id": "",
                "away_tri": "LVA",
                "home_tri": "WSH",
                "status": "Final",
                "detail": "Final",
                "live_state": {
                    "away": "LVA",
                    "home": "WSH",
                    "status": "Final",
                    "final": True,
                },
            }
        ]

        with patch(
            "syndicate.features.wnba.cards._games_from_live_state_fallback",
            return_value=(live_games, "espn_live_fetch"),
        ):
            merged_games, _, supplemented_count = _supplement_games_with_live_state(processed_games, "2026-05-30")

        self.assertEqual(len(merged_games), 1)
        self.assertEqual(supplemented_count, 0)

    def test_live_event_id_variant_does_not_duplicate_matchup(self) -> None:
        processed_games = [
            {
                "gamePk": "3",
                "event_id": "",
                "away_tri": "IND",
                "home_tri": "POR",
                "status": "Scheduled",
                "detail": "2026-05-31T00:00:00+00:00",
            }
        ]
        live_games = [
            {
                "gamePk": "IND@POR",
                "event_id": "401772472",
                "away_tri": "IND",
                "home_tri": "POR",
                "status": "Live",
                "detail": "Q3",
                "live_state": {
                    "away": "IND",
                    "home": "POR",
                    "status": "Q3",
                    "event_id": "401772472",
                },
            }
        ]

        with patch(
            "syndicate.features.wnba.cards._games_from_live_state_fallback",
            return_value=(live_games, "espn_live_fetch"),
        ):
            merged_games, _, supplemented_count = _supplement_games_with_live_state(processed_games, "2026-05-30")

        self.assertEqual(len(merged_games), 1)
        self.assertEqual(supplemented_count, 0)


if __name__ == "__main__":
    unittest.main()
