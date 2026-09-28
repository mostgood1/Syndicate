"""The last two hops: the tick captures, and the lens consumes.

WHY THESE ARE TESTED SEPARATELY FROM THE MATH. Phases 1-3 were pure functions
with real inputs; this is the plumbing that decides whether any of it ever runs.
The failure mode here is silence -- a lens with no `liveProps` and a prop join
reporting zero rows looks identical to a slate where nobody is playing.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch


class LensConsumesTheCaptureTests(unittest.TestCase):
    def _game(self):
        return {
            "event_id": "401857158",
            "status": {"period": 2, "clock": "5:00"},
            "sim": {"players": {"home": [{"player_name": "Paige Bueckers",
                                          "min_mean": 30.0, "pts_mean": 18.0}],
                                "away": []}},
            "shared_prop_rows": [
                {"name": "Paige Bueckers", "market": "pts", "line": 17.5},
                # A combination market that CANNOT be projected from one mean.
                {"name": "Paige Bueckers", "market": "ra", "line": 9.5},
            ],
        }

    def _record(self):
        return {"payload": {"games": [{"event_id": "401857158", "players": [
            {"player": "Paige Bueckers", "team_tri": "DAL", "mp": "9",
             "pts": 6.0, "reb": 2.0, "ast": 1.0, "threes_made": 1.0}]}]}}

    def test_the_lens_stamps_liveProps_from_the_captured_artifact(self) -> None:
        from syndicate.features.wnba.live_lens import _attach_live_props

        games = [self._game()]
        with patch("syndicate.features.shared.refresh_state_store.read_json_file",
                   return_value=self._record()):
            _attach_live_props(games, "2026-08-20")

        props = games[0].get("liveProps")
        self.assertTrue(props, "the lens must carry liveProps for the prop join")
        points = [p for p in props if p["prop"] == "player_points"]
        # POINTS carries a line GRID around the live projection (lane
        # live-props-model-probability, 2026-09-28): live board lines move off the
        # pregame one. The supplied line is always among them.
        self.assertGreater(len(points), 1)
        by_line = {p["line"]: p for p in points}
        self.assertIn(17.5, by_line)
        self.assertIsNotNone(by_line[17.5]["liveProjection"])
        self.assertIsNotNone(by_line[17.5]["liveModelProbOver"], "a line was supplied")
        self.assertTrue(all(p["liveModelProbOver"] is not None for p in points))

    def test_a_combination_market_is_not_priced_from_a_single_mean(self) -> None:
        from syndicate.features.wnba.live_lens import _attach_live_props

        games = [self._game()]
        with patch("syndicate.features.shared.refresh_state_store.read_json_file",
                   return_value=self._record()):
            _attach_live_props(games, "2026-08-20")
        self.assertNotIn("ra", {p["prop"] for p in games[0]["liveProps"]})

    def test_an_absent_capture_leaves_the_lens_untouched(self) -> None:
        """Degrades to pre-phase-4, which the join then names."""
        from syndicate.features.wnba.live_lens import _attach_live_props

        games = [self._game()]
        with patch("syndicate.features.shared.refresh_state_store.read_json_file",
                   return_value=None):
            _attach_live_props(games, "2026-08-20")
        self.assertNotIn("liveProps", games[0])

    def test_coverage_counters_ride_along(self) -> None:
        from syndicate.features.wnba.live_lens import _attach_live_props

        games = [self._game()]
        with patch("syndicate.features.shared.refresh_state_store.read_json_file",
                   return_value=self._record()):
            _attach_live_props(games, "2026-08-20")
        coverage = games[0]["livePropsCoverage"]
        self.assertEqual(coverage["players_matched"], 1)
        # Only POINTS is priced -- the one market with a line in this fixture, and
        # the one market gridded -- so `priced` is its supplied line plus the grid.
        self.assertEqual(coverage["priced"], 1 + coverage["grid_rows"])
        self.assertGreater(coverage["grid_rows"], 0)


class CardLineVocabularyTests(unittest.TestCase):
    def test_the_card_market_keys_are_the_VERIFIED_ones(self) -> None:
        """Read off production 2026-08-19/16: pts/reb/ast/threes, with
        combination markets ra/pa/pr present and deliberately unmapped."""
        from syndicate.features.wnba.live_lens import _CARD_PROP_MARKETS

        self.assertEqual(set(_CARD_PROP_MARKETS), {"pts", "reb", "ast", "threes"})
        for combo in ("ra", "pa", "pr"):
            self.assertNotIn(combo, _CARD_PROP_MARKETS)


if __name__ == "__main__":
    unittest.main()
