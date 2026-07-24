"""Phase-2 tests for the hockeysim adapter + game-market contract mapping.

Lock the game-market aggregation: probabilities are coherent (ml/over-under sum to ~1, favored
side tracks lambdas), EV maths matches American-odds conventions, seeding is deterministic per
game, and the output populates every ``predictions_*`` field. Network-free / synthetic.
"""
from __future__ import annotations

import unittest

from syndicate.features.nhl.sim_engine.hockeysim import (
    HockeyGameFeatures,
    HockeyMarketLines,
    HockeyTeamFeatures,
    american_to_decimal,
    build_game_prediction,
    ev_per_unit,
    game_seed,
)


def _game(home_lam=(1.1, 1.15, 1.25), away_lam=(0.8, 0.85, 0.95), market=None) -> HockeyGameFeatures:
    return HockeyGameFeatures(
        game_pk="2026020001",
        date="2026-03-15",
        home=HockeyTeamFeatures(name="HOME", period_goal_lambdas=home_lam, goals_per_60=3.5),
        away=HockeyTeamFeatures(name="AWAY", period_goal_lambdas=away_lam, goals_per_60=2.6),
        market=market or HockeyMarketLines(total_line=6.5, puck_line=-1.5),
    )


class HockeySimAdapterTest(unittest.TestCase):
    def test_odds_helpers(self) -> None:
        self.assertAlmostEqual(american_to_decimal(100), 2.0)
        self.assertAlmostEqual(american_to_decimal(-110), 1.9090909, places=5)
        self.assertAlmostEqual(american_to_decimal(150), 2.5)
        # Fair coin at +100 is break-even.
        self.assertAlmostEqual(ev_per_unit(0.5, 100), 0.0, places=6)
        # 60% at -110 is positive EV.
        self.assertGreater(ev_per_unit(0.6, -110), 0.0)
        self.assertIsNone(ev_per_unit(0.6, None))

    def test_prediction_probabilities_coherent(self) -> None:
        pred = build_game_prediction(_game(), n_sims=40000)
        self.assertAlmostEqual(pred.p_home_ml + pred.p_away_ml, 1.0, places=6)
        self.assertAlmostEqual(pred.p_home_pl_minus_1_5 + pred.p_away_pl_plus_1_5, 1.0, places=6)
        # over + under <= 1 (remainder is push mass at the line).
        self.assertLessEqual(pred.p_over + pred.p_under, 1.0 + 1e-9)
        self.assertGreater(pred.p_over + pred.p_under, 0.9)
        # 0 <= f10 <= 1 and complementary.
        self.assertTrue(0.0 <= pred.p_f10_yes <= 1.0)
        self.assertAlmostEqual(pred.p_f10_yes + pred.p_f10_no, 1.0, places=9)

    def test_favored_team_has_higher_ml(self) -> None:
        # Home lambdas dominate away -> home should be favored.
        pred = build_game_prediction(_game(), n_sims=40000)
        self.assertGreater(pred.p_home_ml, pred.p_away_ml)
        self.assertGreater(pred.proj_home_goals, pred.proj_away_goals)
        self.assertAlmostEqual(pred.model_total, pred.proj_home_goals + pred.proj_away_goals, places=4)
        self.assertGreater(pred.model_spread, 0.0)  # home margin positive

    def test_projection_fields_populated(self) -> None:
        pred = build_game_prediction(_game(), n_sims=20000)
        self.assertEqual(len(pred.period_home_proj), 3)
        self.assertEqual(len(pred.period_away_proj), 3)
        self.assertEqual(pred.totals_line_used, 6.5)
        # x.5 total -> no push mass.
        self.assertEqual(pred.p_push_total, 0.0)

    def test_ev_populated_from_market_odds(self) -> None:
        market = HockeyMarketLines(
            total_line=6.5, home_ml_odds=-140, away_ml_odds=120,
            over_odds=-105, under_odds=-115, home_pl_odds=175, away_pl_odds=-210,
        )
        pred = build_game_prediction(_game(market=market), n_sims=40000)
        for key in ("home_ml", "away_ml", "over", "under", "home_pl_-1.5", "away_pl_+1.5"):
            self.assertIn(key, pred.ev)

    def test_integer_total_has_push_mass(self) -> None:
        pred = build_game_prediction(
            _game(market=HockeyMarketLines(total_line=6.0, puck_line=-1.5)), n_sims=20000
        )
        self.assertGreater(pred.p_push_total, 0.0)

    def test_deterministic_seed(self) -> None:
        self.assertEqual(game_seed("2026-03-15", "2026020001"), game_seed("2026-03-15", "2026020001"))
        a = build_game_prediction(_game(), n_sims=10000)
        b = build_game_prediction(_game(), n_sims=10000)
        self.assertEqual(a.p_home_ml, b.p_home_ml)
        self.assertEqual(a.p_over, b.p_over)


if __name__ == "__main__":
    unittest.main()
