from __future__ import annotations

import unittest

from syndicate.features.wnba.cards import _estimated_live_projection
from syndicate.features.wnba.cards import _garbage_time_minutes_factor
from syndicate.features.wnba.cards import _live_state_status_from_row
from syndicate.features.wnba.cards import _period_from_status
from syndicate.features.wnba.cards import _score_differential_from_status


class GarbageTimeMinutesFactorTests(unittest.TestCase):
    def test_no_adjustment_before_fourth_quarter(self) -> None:
        factor = _garbage_time_minutes_factor(period=3, score_differential=30.0, sim_minutes=30.0)
        self.assertEqual(factor, 1.0)

    def test_no_adjustment_when_game_is_close(self) -> None:
        factor = _garbage_time_minutes_factor(period=4, score_differential=8.0, sim_minutes=30.0)
        self.assertEqual(factor, 1.0)

    def test_no_adjustment_when_period_or_differential_missing(self) -> None:
        self.assertEqual(_garbage_time_minutes_factor(period=None, score_differential=25.0, sim_minutes=30.0), 1.0)
        self.assertEqual(_garbage_time_minutes_factor(period=4, score_differential=None, sim_minutes=30.0), 1.0)

    def test_dampens_likely_starter_minutes_in_blowout(self) -> None:
        factor = _garbage_time_minutes_factor(period=4, score_differential=25.0, sim_minutes=32.0)
        self.assertLess(factor, 1.0)

    def test_boosts_likely_bench_minutes_in_blowout(self) -> None:
        factor = _garbage_time_minutes_factor(period=4, score_differential=25.0, sim_minutes=10.0)
        self.assertGreater(factor, 1.0)

    def test_no_adjustment_for_mid_rotation_player(self) -> None:
        factor = _garbage_time_minutes_factor(period=4, score_differential=25.0, sim_minutes=20.0)
        self.assertEqual(factor, 1.0)

    def test_overtime_period_still_counts_as_late_game(self) -> None:
        factor = _garbage_time_minutes_factor(period=5, score_differential=25.0, sim_minutes=32.0)
        self.assertLess(factor, 1.0)


class EstimatedLiveProjectionTests(unittest.TestCase):
    def test_regulation_cap_is_forty_minutes_not_nba_forty_eight(self) -> None:
        # No sim_minutes provided -> falls back to the WNBA regulation constant.
        projection = _estimated_live_projection(20.0, 20.0, None, None)
        # actual rate (1.0 pt/min) * 40 regulation minutes = 40, not 48.
        self.assertEqual(projection, 40.0)

    def test_garbage_time_dampens_starter_projection_relative_to_close_game(self) -> None:
        close_game = _estimated_live_projection(20.0, 25.0, 32.0, 22.0, period=4, score_differential=5.0)
        blowout = _estimated_live_projection(20.0, 25.0, 32.0, 22.0, period=4, score_differential=25.0)
        self.assertIsNotNone(close_game)
        self.assertIsNotNone(blowout)
        self.assertLess(blowout, close_game)

    def test_garbage_time_boosts_bench_projection_relative_to_close_game(self) -> None:
        close_game = _estimated_live_projection(6.0, 8.0, 10.0, 7.0, period=4, score_differential=5.0)
        blowout = _estimated_live_projection(6.0, 8.0, 10.0, 7.0, period=4, score_differential=25.0)
        self.assertIsNotNone(close_game)
        self.assertIsNotNone(blowout)
        self.assertGreater(blowout, close_game)

    def test_target_minutes_never_drops_below_minutes_already_played(self) -> None:
        # played=38 already exceeds sim_minutes=34, so the dampened target
        # (34 * 0.85 = 28.9) would fall below minutes already on the floor --
        # it must clamp back to played (38), not undercut what's already happened.
        projection = _estimated_live_projection(30.0, 38.0, 34.0, 28.0, period=4, score_differential=30.0)
        # With target_minutes clamped to played=38: raw_projection = 30/38*38 = 30.0,
        # blend_weight = min(0.85, 38/38) = 0.85 -> 0.15*28 + 0.85*30.0 = 29.7.
        self.assertEqual(projection, 29.7)

    def test_no_actual_returns_sim_mean(self) -> None:
        self.assertEqual(_estimated_live_projection(None, 10.0, 30.0, 15.0), 15.0)

    def test_no_minutes_played_returns_sim_mean_or_actual(self) -> None:
        self.assertEqual(_estimated_live_projection(5.0, 0, 30.0, 15.0), 15.0)
        self.assertEqual(_estimated_live_projection(5.0, None, None, None), 5.0)


class LiveStateStatusFromRowTests(unittest.TestCase):
    def test_carries_score_through_flat_row_shape(self) -> None:
        status = _live_state_status_from_row(
            {"in_progress": True, "final": False, "period": 3, "clock": "5:00", "status": "3rd", "home_pts": 61, "away_pts": 58}
        )
        self.assertEqual(status["home_pts"], 61)
        self.assertEqual(status["away_pts"], 58)

    def test_carries_score_through_when_status_already_a_dict(self) -> None:
        status = _live_state_status_from_row(
            {
                "status": {"in_progress": True, "final": False, "period": 3, "clock": "5:00"},
                "home_pts": 61,
                "away_pts": 58,
            }
        )
        self.assertEqual(status["home_pts"], 61)
        self.assertEqual(status["away_pts"], 58)

    def test_non_dict_input_returns_empty(self) -> None:
        self.assertEqual(_live_state_status_from_row(None), {})


class ScoreDifferentialAndPeriodHelpersTests(unittest.TestCase):
    def test_score_differential_computes_absolute_margin(self) -> None:
        self.assertEqual(_score_differential_from_status({"home_pts": 70, "away_pts": 55}), 15.0)
        self.assertEqual(_score_differential_from_status({"home_pts": 55, "away_pts": 70}), 15.0)

    def test_score_differential_none_when_missing(self) -> None:
        self.assertIsNone(_score_differential_from_status({"home_pts": None, "away_pts": 55}))
        self.assertIsNone(_score_differential_from_status(None))

    def test_period_from_status_coerces_int(self) -> None:
        self.assertEqual(_period_from_status({"period": "4"}), 4)
        self.assertIsNone(_period_from_status({"period": None}))
        self.assertIsNone(_period_from_status(None))


if __name__ == "__main__":
    unittest.main()
