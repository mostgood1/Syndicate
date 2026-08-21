"""A between-period break must not revert the board to its tip-off opinion.

THE DEFECT, measured against the real shipped functions before the fix. The
clock blanks at halftime and at each quarter end, so `_wnba_elapsed_minutes`
cannot parse it and returns None. None does not degrade gracefully:

  * `source` falls back to `pregame`, which EMPTIES `markets` for the whole
    break -- no live moneyline, spread or total.
  * `_wnba_live_margin_win_prob` short-circuits to `pregame_p_home_win`,
    DISCARDING the live margin.

With a 0.45 pregame anchor, a home team up 12 at halftime and a home team down
12 both published 0.4500. Observed live 2026-08-21 on IND@DAL: the
`live_projection` lane vanished for a ~20-minute hole between samples at 19:58
and 20:19 CT, which also caused a watcher to misread the break as the game
being FINAL.

WHY THIS IS NARROW, and what would falsify it. The fix does NOT adopt "blank
clock means the period ended" -- that would be wrong by a full period if ESPN
blanks the clock at a period's START, which has not been observed either way.
It defers to `_infer_period_clock_from_status_text`, which recognises only the
EXPLICIT break labels and was confirmed against a live halftime game on
2026-08-01. `test_unrecognised_blank_clock_still_falls_back` is the guard on
that narrowness: any other blank-clock state must behave exactly as before.
"""
from __future__ import annotations

import unittest

from syndicate.features.wnba import cards


def _game(*, home_pts: float, away_pts: float, detail: str, clock: str, period, pregame: float = 0.45):
    return {
        "away_tri": "IND",
        "home_tri": "DAL",
        "status": {
            "period": period,
            "clock": clock,
            "detail": detail,
            "status": detail,
            "in_progress": True,
            "final": False,
        },
        "live_state": {"home_pts": home_pts, "away_pts": away_pts},
        "betting": {
            "p_home_win": pregame,
            "home_ml": -120,
            "away_ml": 100,
            "home_spread": 3.5,
            "p_home_cover": 0.54,
            "total": 165.5,
            "p_total_over": 0.5,
            "pred_total": 165.0,
        },
    }


def _lane(game):
    lanes = cards._build_wnba_game_lens(game)
    assert lanes, "lens produced no lane"
    return lanes[0]


class HalftimeElapsedTests(unittest.TestCase):
    # --- the lane's testable outcome ---------------------------------------

    def test_margin_sign_changes_the_probability_at_halftime(self) -> None:
        """THE REGRESSION TEST. Before the fix both sides returned 0.4500."""
        up = _lane(_game(home_pts=62, away_pts=50, detail="Halftime", clock="", period=2))
        down = _lane(_game(home_pts=50, away_pts=62, detail="Halftime", clock="", period=2))
        self.assertNotEqual(up["modelHomeWinProb"], down["modelHomeWinProb"])
        self.assertGreater(up["modelHomeWinProb"], 0.45, "up 12 must beat the pregame anchor")
        self.assertLess(down["modelHomeWinProb"], 0.45, "down 12 must trail it")
        # Symmetric about the anchor is not required, but both must have MOVED.
        self.assertNotAlmostEqual(up["modelHomeWinProb"], 0.45, places=3)
        self.assertNotAlmostEqual(down["modelHomeWinProb"], 0.45, places=3)

    def test_halftime_keeps_the_live_lane_and_its_markets(self) -> None:
        lane = _lane(_game(home_pts=62, away_pts=50, detail="Halftime", clock="", period=2))
        self.assertEqual(lane["source"], "live_projection")
        self.assertTrue(lane["markets"], "markets must not be emptied during the break")
        self.assertIn("moneyline", lane["markets"])
        self.assertEqual(lane["projection"]["homeMargin"], 12.0)

    def test_halftime_blend_weight_is_exactly_half_the_game(self) -> None:
        """Halftime is 20.0 of 40.0 minutes -- not an estimate, a boundary."""
        lane = _lane(_game(home_pts=62, away_pts=50, detail="Halftime", clock="", period=2))
        expected = cards._wnba_live_margin_win_prob(0.45, 12.0, 20.0)
        self.assertAlmostEqual(lane["modelHomeWinProb"], expected, places=12)

    def test_end_of_quarter_breaks_resolve_too(self) -> None:
        for detail, elapsed in (("End of 1st", 10.0), ("End of 3rd", 30.0)):
            with self.subTest(detail=detail):
                lane = _lane(_game(home_pts=60, away_pts=50, detail=detail, clock="", period=None))
                self.assertEqual(lane["source"], "live_projection")
                self.assertAlmostEqual(
                    lane["modelHomeWinProb"],
                    cards._wnba_live_margin_win_prob(0.45, 10.0, elapsed),
                    places=12,
                )

    # --- the narrowness guard ----------------------------------------------

    def test_unrecognised_blank_clock_still_falls_back(self) -> None:
        """The fix must fire ONLY on an explicit break label.

        If this ever fails, the change has quietly become "blank clock means
        the period ended", which is the general rule deliberately not adopted.
        """
        lane = _lane(_game(home_pts=62, away_pts=50, detail="Delayed", clock="", period=2))
        self.assertEqual(lane["source"], "pregame")
        self.assertEqual(lane["modelHomeWinProb"], 0.45)

    def test_normal_in_play_clock_is_untouched(self) -> None:
        lane = _lane(_game(home_pts=55, away_pts=50, detail="6:32 - 1st", clock="6:32", period=1))
        self.assertEqual(lane["source"], "live_projection")
        self.assertAlmostEqual(
            lane["modelHomeWinProb"],
            cards._wnba_live_margin_win_prob(0.45, 5.0, cards._wnba_elapsed_minutes(1, "6:32")),
            places=12,
        )


if __name__ == "__main__":
    unittest.main()
