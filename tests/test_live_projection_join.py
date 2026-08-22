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
        # `layer2-live-projection-actual`, 2026-08-20: NOT projection["projected"]
        # -- that field is reserved for the pregame number and this fixture row
        # starts with no `projection` at all, so there is no pregame baseline to
        # show. `live_projected` is the join's own, correctly-named output; this
        # assertion is what the test was actually verifying (the vocabulary/name
        # match succeeded and the live number landed), not a claim that live and
        # pregame are the same field.
        self.assertEqual(grid[0]["projection"]["live_projected"], 1.24)
        self.assertNotIn("projected", grid[0]["projection"])
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
        # `miss_no_market_alias` used to absorb this, and that was the defect
        # `#296`'s contract exists to prevent: "Nobody Here" is not in the live
        # lens AT ALL, which is a different fact from the market vocabulary
        # missing. The 2026-08-21 production reading -- `miss_market=428` with
        # player and line both 0 -- is what forced the split, and this row is
        # the player case.
        self.assertEqual(coverage["miss_player_not_live"], 1)
        self.assertEqual(coverage["miss_no_market_alias"], 0)

        # THE INVARIANT THIS TEST IS NAMED FOR, added by `#517` alongside the
        # bucket assertion above. Both branches reached the same fix for the
        # bucket independently; this is the part only one had. It pins the
        # claim in the test's NAME -- every considered row lands in exactly one
        # reason -- rather than one bucket's value, so it survives the next
        # split of the kind `#296` just made, which is precisely what broke the
        # old assertion.
        miss_total = sum(value for key, value in coverage.items() if key.startswith("miss_"))
        self.assertEqual(miss_total + coverage["rows_live_projected"], coverage["rows_live_considered"])
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
