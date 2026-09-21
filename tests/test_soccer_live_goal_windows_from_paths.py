# -*- coding: utf-8 -*-
"""The goal window is read off real-clock paths, not simulated on a truncated clock.

`goal_in_window_probability` used to resume the match with `clock_remaining = W`.
`soccersim.situation_model.classify_urgency` READS that field -- DESPERATION in
the 2nd half at <= 480 s trailing by 1-2, TRAILING_PUSH at <= 1500 s trailing,
PROTECT_LEAD at <= 900 s leading, CLOSING_HALF in the 1st half at <= 120 s -- so
"the next 5 minutes at the 60th minute" was simulated as the last 5 minutes of a
half.

These tests carry the OLD method as a local reference and compare, because the
distinction is only visible against it:
  * where no urgency rule can fire the two must agree EXACTLY (same seeds, same
    paths) -- that is what proves the new counting adds nothing of its own;
  * where one fires they must differ, upward, because the old one played
    end-of-half football.
Both are deterministic: fixed seeds, so the numbers below are the numbers.
"""

from __future__ import annotations

import unittest
from random import Random
from typing import Any

from syndicate.features.soccer.features.live_lens import build_resume_state
from syndicate.features.soccer.features.live_lens import goal_window_probabilities
from syndicate.features.soccer.features.live_lens import simulate_live_paths
from syndicate.features.soccer.sim_engine.soccersim.calibration_profile import SOCCER_CALIBRATION_PROFILE
from syndicate.features.soccer.sim_engine.soccersim.contracts import SoccerSimSimulationInput
from syndicate.features.soccer.sim_engine.soccersim.match_simulator import simulate_match

N = 300
SEED = 1


def _state(half: int, clock: float, home: int, away: int) -> dict[str, Any]:
    return {"home_team": "Home FC", "away_team": "Away FC", "half": half, "clock_remaining": clock,
            "score_home": home, "score_away": away, "home_red_cards": 0, "away_red_cards": 0}


def _truncated_clock_probability(state: dict[str, Any], window: float, *, simulations: int = N, seed: int = SEED) -> float:
    """The method this change replaced, kept here as the reference it is compared
    against. Resume with the WINDOW as the clock; count any goal at all."""
    truncated = min(float(state["clock_remaining"]), max(0.0, window))
    reaches_half_end = max(0.0, window) >= float(state["clock_remaining"])
    scored = 0
    for offset in range(simulations):
        run_seed = seed + offset
        resume = build_resume_state({**state, "clock_remaining": truncated},
                                    possession_owner="home", include_stoppage=reaches_half_end)
        simulation_input = SoccerSimSimulationInput(
            home_team=state["home_team"], away_team=state["away_team"], seed=run_seed,
            halves=int(state["half"]), home_attack_rating=0.0, home_defense_rating=0.0,
            away_attack_rating=0.0, away_defense_rating=0.0)
        output = simulate_match(simulation_input, rng=Random(run_seed), profile=SOCCER_CALIBRATION_PROFILE,
                                initial_state=resume)
        if int(output.final_score["home"]) > int(state["score_home"]) or \
                int(output.final_score["away"]) > int(state["score_away"]):
            scored += 1
    return round(scored / simulations, 4)


def _from_paths(state: dict[str, Any], windows: dict[str, float]) -> dict[str, float]:
    paths = simulate_live_paths(state, home_rating={}, away_rating={}, simulations=N, seed=SEED)
    return goal_window_probabilities(paths, state, windows=windows)


class GoalWindowFromPathsTests(unittest.TestCase):
    def test_where_no_urgency_rule_can_fire_the_two_methods_agree_exactly(self) -> None:
        """0-0 in the 2nd half with half an hour left: no urgency rule reads the
        clock, so the truncated run IS a prefix of the real-clock run, seed for
        seed. Any difference here would be the new counting, not the model."""
        state = _state(2, 1800.0, 0, 0)

        new = _from_paths(state, {"next_5": 300.0, "next_10": 600.0})

        self.assertEqual(new["next_5"], _truncated_clock_probability(state, 300.0))
        self.assertEqual(new["next_10"], _truncated_clock_probability(state, 600.0))

    def test_a_one_goal_lead_at_the_hour_was_published_too_low(self) -> None:
        """Same state but 1-0. Under the truncated clock the leader is told there
        are 300 s left, so PROTECT_LEAD fires and the trailing side goes to
        DESPERATION -- end-of-half football at the 60th minute. The real clock
        says neither applies, and the window comes out higher."""
        state = _state(2, 1800.0, 1, 0)

        new = _from_paths(state, {"next_5": 300.0, "next_10": 600.0})
        old_5 = _truncated_clock_probability(state, 300.0)
        old_10 = _truncated_clock_probability(state, 600.0)

        self.assertGreater(new["next_5"] - old_5, 0.005, (new["next_5"], old_5))
        self.assertGreater(new["next_10"] - old_10, 0.005, (new["next_10"], old_10))

    def test_the_score_only_moves_the_window_through_the_clock(self) -> None:
        """A consistency check on the model, not on this change: with 1800 s left
        no urgency rule fires at any score, so 0-0, 1-0 and 0-2 must give the
        same window off the real clock. The old method separated them only
        because it lied about the clock."""
        windows = {"next_5": 300.0}
        even = _from_paths(_state(2, 1800.0, 0, 0), windows)["next_5"]
        lead = _from_paths(_state(2, 1800.0, 1, 0), windows)["next_5"]
        two_down = _from_paths(_state(2, 1800.0, 0, 2), windows)["next_5"]

        self.assertEqual(even, lead)
        self.assertEqual(even, two_down)

    def test_a_goal_in_a_later_half_does_not_count(self) -> None:
        """The paths run to the end of the match; the window is "rest of THIS
        half" and must not borrow a goal from the next one."""
        state = _state(1, 60.0, 0, 0)          # a minute of the first half left

        out = _from_paths(state, {"huge": 100000.0})

        self.assertLessEqual(out["huge"], 0.35)  # a minute plus stoppage, not a whole match


if __name__ == "__main__":
    unittest.main()
