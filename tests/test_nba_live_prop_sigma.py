"""NBA live-prop variance -- port of the WNBA sigma fix.

NBA had the identical defect: the live path carried no variance, so
`win_prob` stayed at its stale pregame value and any probability derived
from the live projection saturated to 0/1 the moment the projection sat
either side of the line, regardless of how much game was left. Ported
off-season, deliberately, because it cannot be validated mid-season
without shipping into a live board.
"""

from __future__ import annotations

import unittest

from syndicate.features.nba.cards import _NBA_REGULATION_MINUTES
from syndicate.features.nba.cards import _nba_elapsed_minutes
from syndicate.features.nba.cards import _nba_live_prop_over_probability
from syndicate.features.nba.cards import _nba_live_prop_sigma_for_stat


class NbaElapsedMinutesTests(unittest.TestCase):
    def test_quarters_are_twelve_minutes_not_wnbas_ten(self) -> None:
        # 4:24 left in Q1 -> 7.6 elapsed. The WNBA helper would say 5.6.
        self.assertAlmostEqual(_nba_elapsed_minutes(1, "4:24"), 7.6, places=2)

    def test_later_quarters_accumulate_prior_periods(self) -> None:
        # 6:00 left in Q4 -> 36 prior + 6 elapsed = 42.
        self.assertAlmostEqual(_nba_elapsed_minutes(4, "6:00"), 42.0, places=2)

    def test_overtime_periods_are_five_minutes(self) -> None:
        # Start of OT1 with a full 5:00 clock -> exactly regulation.
        self.assertAlmostEqual(_nba_elapsed_minutes(5, "5:00"), 48.0, places=2)

    def test_missing_period_is_unknown_not_zero(self) -> None:
        self.assertIsNone(_nba_elapsed_minutes(None, "5:00"))


class NbaLivePropSigmaTests(unittest.TestCase):
    def test_combo_markets_use_an_independent_sum(self) -> None:
        pts = _nba_live_prop_sigma_for_stat("pts")
        reb = _nba_live_prop_sigma_for_stat("reb")
        combo = _nba_live_prop_sigma_for_stat("pr")
        self.assertIsNotNone(combo)
        self.assertAlmostEqual(combo, (pts**2 + reb**2) ** 0.5, places=6)

    def test_unknown_market_has_no_sigma(self) -> None:
        self.assertIsNone(_nba_live_prop_sigma_for_stat("not_a_market"))

    def test_nba_sigma_exceeds_the_wnba_equivalent(self) -> None:
        from syndicate.features.wnba.cards import _wnba_live_prop_sigma_for_stat

        # 48-minute game, higher-scoring environment -- a straight copy of
        # the WNBA constants would understate NBA variance.
        self.assertGreater(_nba_live_prop_sigma_for_stat("pts"), _wnba_live_prop_sigma_for_stat("pts"))


class NbaLivePropOverProbabilityTests(unittest.TestCase):
    def test_early_game_projection_below_line_is_not_a_certainty(self) -> None:
        # The exact shape of the bug: a projection well under the line with
        # most of the game left must NOT read as settled.
        probability, sigma = _nba_live_prop_over_probability(5.5, 12.5, "pa", minutes_remaining=40.0)
        self.assertIsNotNone(probability)
        self.assertGreater(probability, 0.02)
        self.assertLess(probability, 0.35)
        self.assertGreater(sigma, 0.0)

    def test_late_game_lock_stays_near_certain(self) -> None:
        probability, _ = _nba_live_prop_over_probability(3.0, 14.5, "pts", minutes_remaining=0.5)
        self.assertLess(probability, 0.02)

    def test_no_time_left_collapses_to_the_outcome(self) -> None:
        over, sigma = _nba_live_prop_over_probability(20.0, 14.5, "pts", minutes_remaining=0.0)
        self.assertEqual(over, 1.0)
        self.assertEqual(sigma, 0.0)
        under, _ = _nba_live_prop_over_probability(9.0, 14.5, "pts", minutes_remaining=0.0)
        self.assertEqual(under, 0.0)

    def test_sigma_shrinks_as_the_game_runs_out(self) -> None:
        _, early = _nba_live_prop_over_probability(10.0, 12.5, "pts", minutes_remaining=44.0)
        _, late = _nba_live_prop_over_probability(10.0, 12.5, "pts", minutes_remaining=4.0)
        self.assertGreater(early, late)

    def test_probability_moves_toward_certainty_as_time_drains(self) -> None:
        early, _ = _nba_live_prop_over_probability(4.0, 12.5, "pts", minutes_remaining=44.0)
        late, _ = _nba_live_prop_over_probability(4.0, 12.5, "pts", minutes_remaining=2.0)
        self.assertGreater(early, late)

    def test_missing_inputs_are_declined_rather_than_guessed(self) -> None:
        self.assertEqual(_nba_live_prop_over_probability(None, 12.5, "pts", 10.0), (None, None))
        self.assertEqual(_nba_live_prop_over_probability(5.0, None, "pts", 10.0), (None, None))
        self.assertEqual(_nba_live_prop_over_probability(5.0, 12.5, "unknown", 10.0), (None, None))

    def test_absent_clock_falls_back_to_full_regulation_variance(self) -> None:
        unknown, _ = _nba_live_prop_over_probability(5.0, 12.5, "pts", minutes_remaining=None)
        full, _ = _nba_live_prop_over_probability(5.0, 12.5, "pts", minutes_remaining=_NBA_REGULATION_MINUTES)
        self.assertAlmostEqual(unknown, full, places=6)


if __name__ == "__main__":
    unittest.main()
