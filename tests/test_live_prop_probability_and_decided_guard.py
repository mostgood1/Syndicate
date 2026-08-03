"""Live player props must carry real variance, and effectively-decided
live props must stop presenting as placeable opportunities.

Both regressions were confirmed on the live 2026-08-02 Layer 2 board:
  * an UNDER 12.5 with 4:24 left in the FIRST quarter (live projection 5.5)
    published model probability 1.0 -- the live path dropped sigma
    entirely, so any projection sitting either side of the line saturated;
  * an UNDER 14.5 with 6:18 left in the 4th (live projection 3) was the
    single highest-ranked opportunity on the board at +100, because the
    decided-prop guard only ever tested `actual > line`, which an UNDER
    can never satisfy.
"""

from __future__ import annotations

import unittest

from syndicate.features.intelligence import _candidate_prop_outcome_decided
from syndicate.features.wnba.cards import _wnba_live_prop_over_probability
from syndicate.features.wnba.cards import _wnba_live_prop_sigma_for_stat


class WnbaLivePropProbabilityTests(unittest.TestCase):
    def test_early_game_projection_below_line_is_not_a_certainty(self) -> None:
        # The exact shape of the confirmed bug: 4:24 left in Q1 means ~34.4
        # minutes still to play, so a 5.5 projection against a 12.5 line is
        # unlikely to go over -- but nowhere near impossible.
        over_probability, live_sigma = _wnba_live_prop_over_probability(5.5, 12.5, "pa", 34.4)
        self.assertIsNotNone(over_probability)
        under_probability = 1.0 - over_probability
        self.assertLess(under_probability, 0.97, "early-game UNDER must not read as decided")
        self.assertGreater(under_probability, 0.5, "UNDER is still the correct lean here")
        self.assertIsNotNone(live_sigma)
        self.assertGreater(live_sigma, 4.0, "most of the game remains, so most of the variance does too")

    def test_late_game_projection_far_from_line_is_near_certain(self) -> None:
        # 6:18 left in the 4th, projection 3 against a 14.5 line: this one
        # genuinely is settled, and the model should say so.
        over_probability, _ = _wnba_live_prop_over_probability(3.0, 14.5, "pts", 6.3)
        self.assertIsNotNone(over_probability)
        self.assertGreater(1.0 - over_probability, 0.97)

    def test_sigma_shrinks_as_the_game_runs_out(self) -> None:
        _, sigma_start = _wnba_live_prop_over_probability(10.0, 12.5, "pts", 40.0)
        _, sigma_half = _wnba_live_prop_over_probability(10.0, 12.5, "pts", 20.0)
        _, sigma_late = _wnba_live_prop_over_probability(10.0, 12.5, "pts", 2.0)
        self.assertGreater(sigma_start, sigma_half)
        self.assertGreater(sigma_half, sigma_late)

    def test_no_time_remaining_collapses_to_the_outcome(self) -> None:
        over_probability, live_sigma = _wnba_live_prop_over_probability(20.0, 12.5, "pts", 0.0)
        self.assertEqual(over_probability, 1.0)
        self.assertEqual(live_sigma, 0.0)

    def test_combination_market_sigma_exceeds_its_parts(self) -> None:
        pts_sigma = _wnba_live_prop_sigma_for_stat("pts")
        pa_sigma = _wnba_live_prop_sigma_for_stat("pa")
        self.assertIsNotNone(pa_sigma)
        self.assertGreater(pa_sigma, pts_sigma)

    def test_unknown_stat_yields_no_probability(self) -> None:
        over_probability, live_sigma = _wnba_live_prop_over_probability(5.0, 6.5, "not_a_stat", 10.0)
        self.assertIsNone(over_probability)
        self.assertIsNone(live_sigma)

    def test_missing_projection_or_line_yields_no_probability(self) -> None:
        self.assertEqual(_wnba_live_prop_over_probability(None, 6.5, "pts", 10.0), (None, None))
        self.assertEqual(_wnba_live_prop_over_probability(5.0, None, "pts", 10.0), (None, None))


class DecidedLivePropGuardTests(unittest.TestCase):
    @staticmethod
    def _candidate(**overrides: object) -> dict[str, object]:
        base: dict[str, object] = {
            "candidate_type": "prop",
            "market": "pts",
            "player_name": "Test Player",
            "entity": "Test Player",
            "pick": "UNDER 14.5",
            "line": "14.5",
            "is_live": True,
        }
        base.update(overrides)
        return base

    def test_locked_under_is_decided_even_though_actual_never_crossed_the_line(self) -> None:
        # The confirmed board bug: actual stays *below* the line, so the
        # original `actual > line` test could never fire for an UNDER.
        candidate = self._candidate(model_probability=1.0, actual="3")
        self.assertEqual(_candidate_prop_outcome_decided(candidate), "hit")

    def test_losing_live_prop_is_decided_too(self) -> None:
        candidate = self._candidate(model_probability=0.01)
        self.assertEqual(_candidate_prop_outcome_decided(candidate), "missed")

    def test_strong_but_undecided_live_prop_survives(self) -> None:
        candidate = self._candidate(model_probability=0.80)
        self.assertIsNone(_candidate_prop_outcome_decided(candidate))

    def test_pregame_prop_is_never_decided_by_probability(self) -> None:
        # A confident pregame projection is exactly what the board exists to
        # surface -- it must not be filtered out as "decided".
        candidate = self._candidate(model_probability=0.99, is_live=False)
        self.assertIsNone(_candidate_prop_outcome_decided(candidate))

    def test_existing_actual_crossed_line_behaviour_is_preserved(self) -> None:
        over = self._candidate(pick="OVER 14.5", actual="20", model_probability=None)
        under = self._candidate(pick="UNDER 14.5", actual="20", model_probability=None)
        self.assertEqual(_candidate_prop_outcome_decided(over), "hit")
        self.assertEqual(_candidate_prop_outcome_decided(under), "missed")

    def test_game_level_market_is_untouched(self) -> None:
        candidate = self._candidate(candidate_type="game", market="Moneyline", pick="Home ML", model_probability=0.99)
        candidate.pop("player_name", None)
        candidate.pop("entity", None)
        self.assertIsNone(_candidate_prop_outcome_decided(candidate))


if __name__ == "__main__":
    unittest.main()
