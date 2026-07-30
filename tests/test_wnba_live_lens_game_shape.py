from __future__ import annotations

import unittest

from syndicate.features.wnba.live_lens import _build_wnba_game_lens
from syndicate.features.wnba.live_lens import _wnba_elapsed_minutes
from syndicate.features.wnba.live_lens import _wnba_live_margin_win_prob


class WnbaElapsedMinutesTests(unittest.TestCase):
    def test_start_of_first_quarter(self) -> None:
        self.assertEqual(_wnba_elapsed_minutes(1, "10:00"), 0.0)

    def test_end_of_first_quarter(self) -> None:
        self.assertAlmostEqual(_wnba_elapsed_minutes(1, "0:00"), 10.0)

    def test_midway_third_quarter(self) -> None:
        # Two full quarters (20 min) + 5 min into Q3's 10-min clock.
        self.assertAlmostEqual(_wnba_elapsed_minutes(3, "5:00"), 25.0)

    def test_end_of_regulation(self) -> None:
        self.assertAlmostEqual(_wnba_elapsed_minutes(4, "0:00"), 40.0)

    def test_overtime_period_is_five_minutes(self) -> None:
        # Full regulation (40) + 2:30 into a 5-min OT period.
        self.assertAlmostEqual(_wnba_elapsed_minutes(5, "2:30"), 42.5)

    def test_second_overtime_period(self) -> None:
        # 40 (regulation) + 5 (OT1) + 1:00 into OT2.
        self.assertAlmostEqual(_wnba_elapsed_minutes(6, "4:00"), 46.0)

    def test_unparseable_clock_returns_none(self) -> None:
        self.assertIsNone(_wnba_elapsed_minutes(2, "halftime"))
        self.assertIsNone(_wnba_elapsed_minutes(2, None))
        self.assertIsNone(_wnba_elapsed_minutes(2, ""))

    def test_missing_period_returns_none(self) -> None:
        self.assertIsNone(_wnba_elapsed_minutes(None, "5:00"))
        self.assertIsNone(_wnba_elapsed_minutes(0, "5:00"))


class WnbaLiveMarginWinProbTests(unittest.TestCase):
    def test_missing_pregame_probability_returns_none(self) -> None:
        self.assertIsNone(_wnba_live_margin_win_prob(None, 5.0, 20.0))

    def test_missing_live_inputs_falls_back_to_pregame(self) -> None:
        self.assertEqual(_wnba_live_margin_win_prob(0.62, None, 20.0), 0.62)
        self.assertEqual(_wnba_live_margin_win_prob(0.62, 5.0, None), 0.62)

    def test_early_game_stays_close_to_pregame(self) -> None:
        # elapsed_min near 0 -> blend weight near 0 -> result near pregame.
        pregame = 0.70
        result = _wnba_live_margin_win_prob(pregame, -20.0, 0.1)
        self.assertAlmostEqual(result, pregame, delta=0.05)

    def test_late_game_leans_toward_live_margin(self) -> None:
        # Home team down big with almost no time left -> win prob should
        # collapse toward 0 regardless of a favorable pregame number.
        result = _wnba_live_margin_win_prob(0.75, -25.0, 39.5)
        self.assertLess(result, 0.15)

    def test_blowout_lead_late_pushes_toward_certainty(self) -> None:
        result = _wnba_live_margin_win_prob(0.50, 25.0, 39.5)
        self.assertGreater(result, 0.85)

    def test_result_always_between_zero_and_one(self) -> None:
        for elapsed in (0.0, 10.0, 20.0, 30.0, 40.0, 45.0):
            result = _wnba_live_margin_win_prob(0.5, -10.0, elapsed)
            self.assertGreaterEqual(result, 0.0)
            self.assertLessEqual(result, 1.0)


class BuildWnbaGameLensTests(unittest.TestCase):
    def _game(self, **overrides) -> dict:
        base = {
            "status": "in progress",
            "betting": {"p_home_win": 0.6},
            "live_state": {
                "home_pts": 55,
                "away_pts": 50,
                "period": 3,
                "clock": "5:00",
                "in_progress": True,
                "final": False,
            },
        }
        base.update(overrides)
        return base

    def test_live_game_produces_single_live_projection_lane(self) -> None:
        lens = _build_wnba_game_lens(self._game())
        self.assertEqual(len(lens), 1)
        row = lens[0]
        self.assertEqual(row["key"], "live")
        self.assertEqual(row["source"], "live_projection")
        self.assertFalse(row["closed"])
        self.assertEqual(row["projection"]["homeMargin"], 5.0)
        self.assertEqual(row["baselineHomeWinProb"], 0.6)
        self.assertIsNotNone(row["modelHomeWinProb"])

    def test_pregame_only_game_falls_back_to_pregame_source(self) -> None:
        game = self._game(live_state={"home_pts": None, "away_pts": None, "period": None, "clock": None, "in_progress": False, "final": False})
        lens = _build_wnba_game_lens(game)
        row = lens[0]
        self.assertEqual(row["source"], "pregame")
        self.assertEqual(row["modelHomeWinProb"], 0.6)
        self.assertIsNone(row["projection"]["homeMargin"])

    def test_final_game_is_closed(self) -> None:
        game = self._game(live_state={"home_pts": 80, "away_pts": 70, "period": 4, "clock": "0:00", "in_progress": False, "final": True})
        lens = _build_wnba_game_lens(game)
        self.assertTrue(lens[0]["closed"])

    def test_missing_pregame_probability_still_returns_a_lane(self) -> None:
        game = self._game(betting={})
        lens = _build_wnba_game_lens(game)
        self.assertEqual(len(lens), 1)
        self.assertIsNone(lens[0]["baselineHomeWinProb"])


if __name__ == "__main__":
    unittest.main()
