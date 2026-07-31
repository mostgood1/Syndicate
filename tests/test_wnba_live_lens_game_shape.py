from __future__ import annotations

import unittest

from syndicate.features.wnba.cards import _build_wnba_game_lens
from syndicate.features.wnba.cards import _wnba_elapsed_minutes
from syndicate.features.wnba.cards import _wnba_game_lens_markets
from syndicate.features.wnba.cards import _wnba_live_margin_win_prob


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
        # Matches the real shape build_cards_page_context returns (confirmed
        # live 2026-07-30): period/clock live under `status`, NOT
        # `live_state` -- live_state only carries home_pts/away_pts/
        # in_progress/final/a text status label. A synthetic fixture that
        # put period/clock under live_state (this test's own shape prior to
        # the 2026-07-30 fix) would have masked the exact bug that fix
        # addressed, since it never exercised the real lookup path.
        base = {
            "status": {
                "detail": "5:00 - 3rd",
                "final": False,
                "in_progress": True,
                "period": 3,
                "clock": "5:00",
                "status": "Live",
            },
            "betting": {"p_home_win": 0.6},
            "live_state": {
                "home_pts": 55,
                "away_pts": 50,
                "in_progress": True,
                "final": False,
                "status": "5:00 - 3rd",
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

    def test_real_production_shape_without_period_clock_in_live_state(self) -> None:
        # Regression test for the 2026-07-30 bug found live: a genuinely
        # in-progress game whose live_state carried only
        # {away_pts, final, home_pts, in_progress, status} -- no period/clock
        # at all -- silently fell back to source="pregame" forever, even
        # though margin was fully computable, because elapsed_min could never
        # resolve. This is the *exact* dict shape observed in production.
        game = {
            "status": {"clock": "5:54", "detail": "5:54 - 1st", "final": False, "in_progress": True, "period": 1, "status": "Live"},
            "betting": {"p_home_win": 0.65},
            "live_state": {"away_pts": 9.0, "final": False, "home_pts": 10.0, "in_progress": True, "status": "5:54 - 1st"},
        }
        lens = _build_wnba_game_lens(game)
        row = lens[0]
        self.assertEqual(row["source"], "live_projection")
        self.assertEqual(row["projection"]["homeMargin"], 1.0)
        self.assertIsNotNone(row["modelHomeWinProb"])
        self.assertNotEqual(row["modelHomeWinProb"], 0.65)

    def test_pregame_only_game_falls_back_to_pregame_source(self) -> None:
        game = self._game(
            status={"detail": "Scheduled", "final": False, "in_progress": False, "period": None, "clock": None, "status": "Scheduled"},
            live_state={"home_pts": None, "away_pts": None, "in_progress": False, "final": False},
        )
        lens = _build_wnba_game_lens(game)
        row = lens[0]
        self.assertEqual(row["source"], "pregame")
        self.assertEqual(row["modelHomeWinProb"], 0.6)
        self.assertIsNone(row["projection"]["homeMargin"])

    def test_final_game_is_closed(self) -> None:
        game = self._game(
            status={"detail": "Final", "final": True, "in_progress": False, "period": 4, "clock": "0:00", "status": "Final"},
            live_state={"home_pts": 80, "away_pts": 70, "in_progress": False, "final": True},
        )
        lens = _build_wnba_game_lens(game)
        self.assertTrue(lens[0]["closed"])

    def test_missing_pregame_probability_still_returns_a_lane(self) -> None:
        game = self._game(betting={})
        lens = _build_wnba_game_lens(game)
        self.assertEqual(len(lens), 1)
        self.assertIsNone(lens[0]["baselineHomeWinProb"])

    def test_live_game_pace_extrapolates_total_points(self) -> None:
        # 105 combined points at 25 min elapsed (of 40) -> pace total 168.0.
        lens = _build_wnba_game_lens(
            self._game(
                status={"detail": "5:00 - 3rd", "final": False, "in_progress": True, "period": 3, "clock": "5:00", "status": "Live"},
                live_state={"home_pts": 55, "away_pts": 50, "in_progress": True, "final": False},
            )
        )
        self.assertAlmostEqual(lens[0]["projection"]["total"], 168.0, delta=0.1)

    def test_pregame_game_has_no_pace_total(self) -> None:
        game = self._game(
            status={"detail": "Scheduled", "final": False, "in_progress": False, "period": None, "clock": None, "status": "Scheduled"},
            live_state={"home_pts": None, "away_pts": None, "in_progress": False, "final": False},
        )
        lens = _build_wnba_game_lens(game)
        self.assertIsNone(lens[0]["projection"]["total"])

    def test_live_game_with_full_betting_dict_produces_markets(self) -> None:
        # Home favored live (up 6, was a pick'em pregame), real book lines on
        # all three markets -- exercises home.py's gameLens consumer
        # requirement that each market carry a non-empty `pick`.
        game = self._game(
            betting={
                "p_home_win": 0.5,
                "home_ml": -150,
                "away_ml": 130,
                "home_spread": -4.5,
                "home_spread_ev": 0.05,
                "total": 165.5,
                "over_ev": 0.03,
                "p_home_cover": 0.55,
                "p_total_over": 0.5,
            },
            live_state={"home_pts": 55, "away_pts": 49, "in_progress": True, "final": False},
        )
        lens = _build_wnba_game_lens(game)
        markets = lens[0]["markets"]
        self.assertIn("moneyline", markets)
        self.assertIn("spread", markets)
        self.assertIn("total", markets)
        for market in markets.values():
            self.assertTrue(market.get("pick"))
        self.assertEqual(markets["spread"]["homeLine"], -4.5)
        self.assertEqual(markets["total"]["line"], 165.5)
        for market_key in ("moneyline", "spread", "total"):
            p_win = markets[market_key]["p_win"]
            self.assertGreaterEqual(p_win, 0.0)
            self.assertLessEqual(p_win, 1.0)

    def test_final_game_has_no_markets(self) -> None:
        game = self._game(
            status={"detail": "Final", "final": True, "in_progress": False, "period": 4, "clock": "0:00", "status": "Final"},
            live_state={"home_pts": 80, "away_pts": 70, "in_progress": False, "final": True},
            betting={"p_home_win": 0.6, "home_ml": -150, "away_ml": 130, "home_spread": -4.5, "total": 165.5},
        )
        lens = _build_wnba_game_lens(game)
        self.assertEqual(lens[0]["markets"], {})

    def test_pregame_game_has_no_markets(self) -> None:
        # markets are only populated for genuinely live rows (live_home_win_prob
        # is passed through only when source == "live_projection") -- a
        # pregame-only game already has plain betting-dict-sourced Moneyline/
        # Spread/Total candidates from home.py; gameLens markets exist to
        # carry the *live* update on top, not to duplicate the pregame ones.
        game = self._game(
            status={"detail": "Scheduled", "final": False, "in_progress": False, "period": None, "clock": None, "status": "Scheduled"},
            live_state={"home_pts": None, "away_pts": None, "in_progress": False, "final": False},
            betting={"p_home_win": 0.6, "home_ml": -150, "away_ml": 130, "home_spread": -4.5, "total": 165.5},
        )
        lens = _build_wnba_game_lens(game)
        self.assertEqual(lens[0]["markets"], {})


class WnbaGameLensMarketsTests(unittest.TestCase):
    def test_no_markets_when_betting_dict_is_empty(self) -> None:
        markets = _wnba_game_lens_markets({}, live_home_win_prob=0.6, live_margin=5.0, pace_total=150.0)
        self.assertEqual(markets, {})

    def test_moneyline_omitted_without_live_win_prob(self) -> None:
        markets = _wnba_game_lens_markets({"home_ml": -150, "away_ml": 130}, live_home_win_prob=None, live_margin=5.0, pace_total=150.0)
        self.assertNotIn("moneyline", markets)

    def test_moneyline_picks_favored_side(self) -> None:
        home_favored = _wnba_game_lens_markets({"home_ml": -150, "away_ml": 130}, live_home_win_prob=0.7, live_margin=None, pace_total=None)
        self.assertEqual(home_favored["moneyline"]["pick"], "Home ML")
        self.assertEqual(home_favored["moneyline"]["selection"], "home")
        away_favored = _wnba_game_lens_markets({"home_ml": -150, "away_ml": 130}, live_home_win_prob=0.3, live_margin=None, pace_total=None)
        self.assertEqual(away_favored["moneyline"]["pick"], "Away ML")
        self.assertEqual(away_favored["moneyline"]["selection"], "away")

    def test_spread_omitted_without_live_margin(self) -> None:
        markets = _wnba_game_lens_markets({"home_spread": -4.5}, live_home_win_prob=0.6, live_margin=None, pace_total=None)
        self.assertNotIn("spread", markets)

    def test_total_omitted_without_line(self) -> None:
        markets = _wnba_game_lens_markets({}, live_home_win_prob=0.6, live_margin=5.0, pace_total=150.0)
        self.assertNotIn("total", markets)


if __name__ == "__main__":
    unittest.main()
