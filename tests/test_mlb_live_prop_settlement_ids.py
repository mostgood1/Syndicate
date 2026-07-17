"""ID-first settlement for MLB live prop registry entries."""

from __future__ import annotations

import unittest

from syndicate.features.mlb.live_lens_daily_accuracy import _actual_from_feed


def _feed(players: dict) -> dict:
    return {"liveData": {"boxscore": {"teams": {"away": {"players": players}, "home": {"players": {}}}}}}


class ActualFromFeedTests(unittest.TestCase):
    def test_resolves_by_mlbam_id_when_name_differs(self) -> None:
        feed = _feed(
            {
                "ID660271": {
                    "person": {"id": 660271, "fullName": "Sho Ohtani Jr."},
                    "stats": {"batting": {"hits": 2, "runs": 1, "rbi": 3, "totalBases": 5, "homeRuns": 1}},
                }
            }
        )
        # Registry knows the player as a different name variant; only the id matches.
        self.assertEqual(_actual_from_feed(feed, "Shohei Ohtani", "hitter_props", "hits", player_id=660271), 2.0)
        self.assertEqual(_actual_from_feed(feed, "Shohei Ohtani", "hitter_props", "total_bases", player_id=660271), 5.0)

    def test_falls_back_to_normalized_name_without_id(self) -> None:
        feed = _feed(
            {
                "ID1": {
                    "person": {"id": 1, "fullName": "José Ramírez"},
                    "stats": {"batting": {"hits": 1, "runs": 0, "rbi": 0, "totalBases": 1, "homeRuns": 0}},
                }
            }
        )
        # Accent-insensitive normalized-name fallback still works.
        self.assertEqual(_actual_from_feed(feed, "Jose Ramirez", "hitter_props", "hits"), 1.0)

    def test_pitcher_strikeouts_by_id(self) -> None:
        feed = _feed(
            {
                "ID543037": {
                    "person": {"id": 543037, "fullName": "Gerrit A. Cole"},
                    "stats": {"pitching": {"strikeOuts": 9}},
                }
            }
        )
        self.assertEqual(_actual_from_feed(feed, "Gerrit Cole", "pitcher_props", "strikeouts", player_id=543037), 9.0)

    def test_missing_player_returns_none(self) -> None:
        feed = _feed({})
        self.assertIsNone(_actual_from_feed(feed, "Nobody", "hitter_props", "hits", player_id=999))


if __name__ == "__main__":
    unittest.main()
