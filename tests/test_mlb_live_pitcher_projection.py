"""Live MLB pitcher props: the projection tracks the game, the probability follows it.

Every case here is taken from the served board at 2026-08-15 20:12:48Z, on the
game the report came in about (STL @ CHC, Top 7, STL 7-3). The numbers in the
docstrings are production readings, not invented fixtures.
"""

from __future__ import annotations

import unittest

from syndicate.features.mlb.cards import _bounded_live_pitcher_projection
from syndicate.features.shared.live_projection_join import (
    attach_live_projections,
    build_live_prop_index,
)


class BoundedLivePitcherProjectionTests(unittest.TestCase):
    # Matthew Boyd: 5.1 IP, 2 K, 7 ER, pulled -- two relievers behind him --
    # and the board projected him to finish with 4.057 K and 3.242 ER.
    def test_a_pulled_starter_stops_accruing(self):
        projection = _bounded_live_pitcher_projection(
            2.0,            # strikeouts actually recorded
            5.4,            # pregame mean
            0.55,           # game is 55% done, which used to license 45% of the residual
            outs_mean=17.0,
            outs_recorded=16.0,
            pitcher_removed=True,
        )
        self.assertEqual(projection, 2.0)

    def test_a_pulled_starter_is_not_rescued_by_a_generous_outs_budget(self):
        # Removal must win over the opportunity model, not be averaged with it:
        # `outs_mean` says 8 outs remain, and there are none.
        projection = _bounded_live_pitcher_projection(
            2.0, 5.4, 0.10, outs_mean=24.0, outs_recorded=16.0, pitcher_removed=True
        )
        self.assertEqual(projection, 2.0)

    # Michael McGreevy: 18 outs recorded, projected 17.136 -- below a banked
    # actual, which no monotone counting stat can do.
    def test_projection_never_falls_below_an_already_recorded_actual(self):
        projection = _bounded_live_pitcher_projection(
            18.0, 17.7, 0.55, outs_mean=17.7, outs_recorded=18.0
        )
        self.assertIsNotNone(projection)
        self.assertGreaterEqual(projection, 18.0)

    def test_a_pitcher_ahead_of_his_mean_still_accrues(self):
        # `max(mean - actual, 0.0)` floored the residual at zero, so a pitcher
        # beating his pregame mean projected to add exactly nothing for the rest
        # of his start. With 6 outs left and a 0.3 K/out rate he adds ~1.8.
        projection = _bounded_live_pitcher_projection(
            7.0,            # already past the 5.1 mean
            5.1,
            0.55,
            outs_mean=17.0,
            outs_recorded=11.0,
        )
        self.assertIsNotNone(projection)
        self.assertGreater(projection, 7.0)

    def test_the_clock_is_the_pitchers_workload_not_the_games(self):
        # Identical game progress, different remaining workload, must differ.
        # This is the defect in one assertion: `_live_progress_fraction` is
        # total outs over 54 and a starter is expected to record ~17 of them.
        early = _bounded_live_pitcher_projection(
            1.0, 6.0, 0.5, outs_mean=18.0, outs_recorded=3.0
        )
        late = _bounded_live_pitcher_projection(
            1.0, 6.0, 0.5, outs_mean=18.0, outs_recorded=15.0
        )
        self.assertIsNotNone(early)
        self.assertIsNotNone(late)
        self.assertGreater(early, late)

    def test_the_outs_market_is_an_identity_and_floors_at_the_actual(self):
        # For `outs` itself the rate is 1.0, so a pitcher short of his mean
        # projects to it, and one past it projects to what he has.
        self.assertEqual(
            _bounded_live_pitcher_projection(12.0, 18.0, 0.4, outs_mean=18.0, outs_recorded=12.0),
            18.0,
        )
        self.assertEqual(
            _bounded_live_pitcher_projection(20.0, 18.0, 0.4, outs_mean=18.0, outs_recorded=20.0),
            20.0,
        )

    def test_missing_opportunity_inputs_degrade_to_the_previous_behaviour(self):
        # A thin sim payload must not produce nothing -- it produces the old
        # game-progress number, which is what shipped before this change.
        legacy = round(2.0 + max(5.0 - 2.0, 0.0) * 0.5, 3)
        self.assertEqual(_bounded_live_pitcher_projection(2.0, 5.0, 0.5), legacy)
        self.assertEqual(
            _bounded_live_pitcher_projection(2.0, 5.0, 0.5, outs_mean=None, outs_recorded=9.0),
            legacy,
        )

    def test_absent_inputs_still_return_the_honest_half(self):
        self.assertEqual(_bounded_live_pitcher_projection(4.0, None, 0.5), 4.0)
        self.assertEqual(_bounded_live_pitcher_projection(None, 5.0, 0.5), 5.0)


def _snapshot(*, live_prob_over=None):
    prop = {
        "playerName": "Logan Webb",
        "market": "strikeouts",
        "line": 5.5,
        "liveProjection": 4.786,
        # The PREGAME probability, which `live_lens.py:541` falls through to
        # `estimatedWinProb` to produce.
        "modelProbOver": 0.9,
        "actualSoFar": 1,
        "selection": "Over",
    }
    if live_prob_over is not None:
        prop["liveModelProbOver"] = live_prob_over
    return {"games": [{"status": {"abstract": "Live", "detailed": "In Progress"}, "liveProps": [prop]}]}


def _grid():
    return [
        {
            "kind": "prop",
            "player_name": "Logan Webb",
            "market": "pitcher_strikeouts",
            "line": 5.5,
            "game": {"state": "live"},
            "projection": {"projected": 4.932, "basis": "so_dist", "source": "pitcher_distribution",
                           "model_prob_over": 0.9, "market_fair_prob_over": 0.5},
        }
    ]


class LiveProbabilityFollowsLiveProjectionTests(unittest.TestCase):
    def test_a_pregame_probability_is_not_relabelled_live(self):
        # Served 2026-08-15: `live_projected` 4.786 against a 5.5 line -- UNDER --
        # sitting beside P(over) 0.90. The projection moved with the game and the
        # probability did not, because it was the pregame number carried across.
        grid = _grid()
        coverage = attach_live_projections(grid, build_live_prop_index(_snapshot()))
        projection = grid[0]["projection"]

        self.assertEqual(coverage["rows_live_projected"], 1)
        self.assertEqual(projection["projected"], 4.786)
        self.assertIsNone(projection["model_prob_over"])
        self.assertIn("model_prob_over_unavailable_reason", projection)
        self.assertEqual(coverage["rows_live_prob_withheld"], 1)

    def test_the_pregame_probability_is_preserved_not_discarded(self):
        grid = _grid()
        attach_live_projections(grid, build_live_prop_index(_snapshot()))
        projection = grid[0]["projection"]
        self.assertEqual(projection["sim_model_prob_over"], 0.9)
        self.assertEqual(projection["sim_projected"], 4.932)
        self.assertEqual(projection["sim_source"], "pitcher_distribution")

    def test_a_real_live_probability_is_shown(self):
        grid = _grid()
        coverage = attach_live_projections(grid, build_live_prop_index(_snapshot(live_prob_over=0.31)))
        projection = grid[0]["projection"]
        self.assertEqual(projection["model_prob_over"], 0.31)
        self.assertNotIn("model_prob_over_unavailable_reason", projection)
        self.assertEqual(coverage["rows_live_prob_withheld"], 0)

    def test_projection_and_probability_never_straddle_the_line(self):
        # The property the report was actually about, asserted directly: a row
        # may not claim the under with its projection and the over with its
        # probability. 7 of 13 live pitcher rows did exactly that.
        for live_prob in (None, 0.31):
            with self.subTest(live_prob=live_prob):
                grid = _grid()
                attach_live_projections(grid, build_live_prop_index(_snapshot(live_prob_over=live_prob)))
                projection = grid[0]["projection"]
                probability = projection["model_prob_over"]
                if probability is None:
                    continue
                self.assertEqual(projection["projected"] > grid[0]["line"], probability > 0.5)

    def test_a_second_tick_does_not_record_the_live_number_as_the_sims(self):
        grid = _grid()
        index = build_live_prop_index(_snapshot(live_prob_over=0.31))
        attach_live_projections(grid, index)
        attach_live_projections(grid, index)
        self.assertEqual(grid[0]["projection"]["sim_model_prob_over"], 0.9)
        self.assertEqual(grid[0]["projection"]["sim_projected"], 4.932)


if __name__ == "__main__":
    unittest.main()
