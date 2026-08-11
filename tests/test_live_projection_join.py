from __future__ import annotations

import unittest

from syndicate.features.shared.live_edge_policy import live_edge_unavailable_reason
from syndicate.features.shared.live_projection_join import (
    attach_live_projections,
    build_live_prop_index,
)


def _snapshot():
    return {
        "games": [
            {
                "status": {"abstract": "Live", "detailed": "In Progress"},
                "liveProps": [
                    {"playerName": "J.D. Martinez", "market": "hits", "line": 0.5,
                     "liveProjection": 1.24, "modelProbOver": 0.61, "actualSoFar": 1, "selection": "Over"},
                    {"playerName": "Tarik Skubal", "market": "strikeouts", "line": 6.5,
                     "liveProjection": 7.8, "modelProbOver": 0.66, "actualSoFar": 4, "selection": "Over"},
                ],
            }
        ]
    }


class LiveProjectionJoinTests(unittest.TestCase):
    def test_punctuation_and_market_vocabulary_still_join(self):
        # The board speaks OddsAPI (`batter_hits`), the live lens speaks the
        # sim's vocabulary (`hits`). A join that only matched identical strings
        # would report zero coverage and look like "the sim had no opinion" --
        # the exact failure that left settlement at 20.6% unnoticed.
        grid = [
            {"kind": "prop", "player_name": "JD Martinez", "market": "batter_hits",
             "line": 0.5, "game": {"state": "live"}},
            {"kind": "prop", "player_name": "Tarik Skubal", "market": "pitcher_strikeouts",
             "line": 6.5, "game": {"state": "live"}},
        ]
        coverage = attach_live_projections(grid, build_live_prop_index(_snapshot()))
        self.assertEqual(coverage["rows_live_projected"], 2)
        self.assertEqual(grid[0]["projection"]["projected"], 1.24)
        self.assertTrue(grid[0]["projection"]["live_aware"])

    def test_pregame_rows_are_untouched(self):
        # This adds a live TIER; it must not rewrite the pregame model.
        grid = [{"kind": "prop", "player_name": "JD Martinez", "market": "batter_hits",
                 "line": 0.5, "game": {"state": "pregame"},
                 "projection": {"projected": 0.9, "basis": "pregame"}}]
        attach_live_projections(grid, build_live_prop_index(_snapshot()))
        self.assertEqual(grid[0]["projection"]["basis"], "pregame")
        self.assertNotIn("live_aware", grid[0]["projection"])

    def test_a_miss_is_counted_by_reason_not_silently_dropped(self):
        grid = [{"kind": "prop", "player_name": "Nobody Here", "market": "batter_hits",
                 "line": 1.5, "game": {"state": "live"}}]
        coverage = attach_live_projections(grid, build_live_prop_index(_snapshot()))
        self.assertEqual(coverage["rows_live_projected"], 0)
        self.assertEqual(coverage["miss_no_market_alias"], 1)
        self.assertTrue(coverage["unmatched_samples"])
        self.assertIn("tried", coverage["unmatched_samples"][0])

    def test_absent_snapshot_reports_a_reason_rather_than_zero_coverage(self):
        coverage = attach_live_projections([], {"index": None})
        self.assertFalse(coverage["supported"])
        self.assertIn("reason", coverage)


class LiveEdgePolicyBasisTests(unittest.TestCase):
    """The predicate is the PROJECTION's basis, not the game's state."""

    def test_live_game_with_a_live_projection_now_carries_an_edge(self):
        # THE POINT OF #350. Keying on game state alone was right while nothing
        # joined a live model, and became wrong the moment one did.
        row = {"game": {"state": "live"}, "projection": {"live_aware": True}}
        self.assertIsNone(live_edge_unavailable_reason(row))

    def test_live_game_with_a_pregame_projection_is_still_suppressed(self):
        row = {"game": {"state": "live"}, "projection": {"basis": "pregame"}}
        self.assertIsNotNone(live_edge_unavailable_reason(row))

    def test_final_refuses_even_a_live_projection(self):
        # A settled market has no price to beat; model freshness cannot rescue it.
        row = {"game": {"state": "final"}, "projection": {"live_aware": True}}
        reason = live_edge_unavailable_reason(row)
        self.assertIsNotNone(reason)
        self.assertIn("settled", reason)

    def test_unknown_state_still_allows_the_edge(self):
        self.assertIsNone(live_edge_unavailable_reason({"game": {}}))
