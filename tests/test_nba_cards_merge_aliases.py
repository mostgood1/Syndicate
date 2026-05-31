from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.nba.cards import _merge_games_with_live_state


class NbaCardsMergeAliasTests(unittest.TestCase):
    def test_merge_uses_canonical_team_aliases(self) -> None:
        processed_games = [
            {
                "gamePk": "1",
                "event_id": "",
                "away_tri": "SAS",
                "home_tri": "OKC",
                "status": "Scheduled",
                "detail": "2026-05-31T00:00:00+00:00",
            }
        ]
        live_games = [
            {
                "gamePk": "SA@OKC",
                "event_id": "",
                "away_tri": "SA",
                "home_tri": "OKC",
                "status": "Final",
                "detail": "Final",
                "live_state": {
                    "away": "SA",
                    "home": "OKC",
                    "status": "Final",
                    "final": True,
                },
            }
        ]

        with patch(
            "syndicate.features.nba.cards._games_from_live_state_fallback",
            return_value=(live_games, "espn_live_fetch"),
        ):
            merged_games, _, supplemented_count, updated_count = _merge_games_with_live_state(processed_games, "2026-05-30")

        self.assertEqual(len(merged_games), 1)
        self.assertEqual(supplemented_count, 0)
        self.assertEqual(updated_count, 1)
        self.assertEqual(merged_games[0].get("away_tri"), "SAS")
        self.assertEqual(merged_games[0].get("home_tri"), "OKC")
        self.assertEqual(merged_games[0].get("status"), "Final")
        self.assertEqual(merged_games[0].get("detail"), "Final")


if __name__ == "__main__":
    unittest.main()
