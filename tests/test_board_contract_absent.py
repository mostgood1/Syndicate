"""Lane F: absent data must render as absent, and a number must be the
quantity its label claims.

Every case here was measured against the real contract on 2026-08-14 before
being fixed, by driving `apply_game_board_contract` with a known game rather
than by hoping the right shape was sitting in an artifact:

    projected 21.0-24.0, no win probability -> away_pct 46.67 / home_pct 53.33
    the same game WITH p_home_win = 0.62    -> bar still 53.33, text 62.0%
    nothing at all                          -> 50.0 / 50.0
    a genuine 0.0 home win probability      -> 50.0 / 50.0

The first two are the serious ones: 46.67/53.33 is the share of projected
POINTS, rendered in a bar under a panel headed "Period win probabilities". A
3-point favourite is not a 53.3% favourite.
"""

from __future__ import annotations

import unittest

from syndicate.app import create_app
from syndicate.features.shared.game_board_contract import apply_game_board_contract


def _game(**overrides) -> dict:
    game = {
        "gamePk": "g1",
        "away": {"abbr": "SEA", "name": "Seattle Seahawks"},
        "home": {"abbr": "NE", "name": "New England Patriots"},
        "status": "Scheduled",
    }
    game.update(overrides)
    return game


def _normalize(game: dict, sport: str = "nfl") -> dict:
    return apply_game_board_contract({"games": [game]}, sport=sport, module="cards")["games"][0]


class AbsentProbabilityTests(unittest.TestCase):
    def test_no_probability_anywhere_renders_no_split(self) -> None:
        rows = _normalize(_game())["shared_probability_rows"]
        self.assertTrue(rows)
        for row in rows:
            self.assertIsNone(row["away_pct"])
            self.assertIsNone(row["home_pct"])

    def test_a_projection_is_not_a_win_probability(self) -> None:
        # The regression that matters: a 21-24 projection used to emit
        # 46.67/53.33 -- the points share -- into the win-probability bar.
        game = _game(sim={"score": {"away_mean": 21.0, "home_mean": 24.0},
                          "periods": {"full": {"away_mean": 21.0, "home_mean": 24.0}}})
        for row in _normalize(game)["shared_period_rows"]:
            self.assertIsNone(row["away_pct"], "a scoreline is not a probability")
            self.assertIsNone(row["home_pct"], "a scoreline is not a probability")

    def test_the_bar_and_the_text_agree_when_a_probability_exists(self) -> None:
        game = _game(
            sim={"score": {"away_mean": 21.0, "home_mean": 24.0},
                 "periods": {"full": {"away_mean": 21.0, "home_mean": 24.0, "p_home_win": 0.62}}},
            betting={"p_home_win": 0.62, "p_away_win": 0.38},
        )
        rows = _normalize(game)["shared_period_rows"]
        self.assertEqual(62.0, round(rows[0]["home_pct"], 6))
        self.assertEqual("62.0%", rows[0]["home_win"])

    def test_a_genuine_zero_is_not_a_coin_flip(self) -> None:
        game = _game(probability_rows=[{"label": "Full Game", "away_pct": 100.0, "home_pct": 0.0}])
        row = _normalize(game)["shared_probability_rows"][0]
        self.assertEqual(0.0, row["home_pct"])
        self.assertEqual(100.0, row["away_pct"])


class ThreeWayMarketTests(unittest.TestCase):
    """The soccer card showed two different home-win numbers. They were the
    sim's (tiles) and the market's (bar) -- two quantities, one label."""

    SOCCER = {
        "gamePk": "epl-1",
        "away": {"abbr": "COV", "name": "Coventry City"},
        "home": {"abbr": "ARS", "name": "Arsenal"},
        "status": "Scheduled",
        "sim": {"score": {"away_mean": 0.7, "home_mean": 2.4}, "periods": {},
                "win_probability": {"home": 0.773, "draw": 0.140, "away": 0.087}},
        "betting": {"p_home_win": 0.811, "p_away_win": 0.189},
    }

    def test_the_bar_follows_the_sim_not_the_market(self) -> None:
        row = _normalize(dict(self.SOCCER), sport="soccer")["shared_probability_rows"][0]
        self.assertAlmostEqual(77.3, row["home_pct"], places=6)
        self.assertNotAlmostEqual(81.1, row["home_pct"], places=1)

    def test_the_draw_survives_instead_of_being_renormalised_away(self) -> None:
        row = _normalize(dict(self.SOCCER), sport="soccer")["shared_probability_rows"][0]
        self.assertAlmostEqual(14.0, row["draw_pct"], places=6)
        total = row["home_pct"] + row["draw_pct"] + row["away_pct"]
        self.assertAlmostEqual(100.0, total, places=6)

    def test_a_two_way_market_still_completes_from_one_side(self) -> None:
        game = _game(betting={"p_home_win": 0.62})
        row = _normalize(game)["shared_probability_rows"][0]
        self.assertAlmostEqual(38.0, row["away_pct"], places=6)
        self.assertIsNone(row["draw_pct"])


class RenderedCardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app()
        self.app.config.update(TESTING=True)

    def _render(self, game: dict, sport: str = "nfl") -> str:
        normalized = _normalize(game, sport=sport)
        normalized.setdefault("market_tiles", [])
        with self.app.test_request_context("/"):
            from flask import render_template

            return render_template("shared/_game_card_generic.html", game=normalized)

    def test_no_bar_is_drawn_without_a_probability(self) -> None:
        html = self._render(_game())
        self.assertNotIn('class="cards-prob-bar', html)
        self.assertIn("No win probability was published", html)

    def test_a_bar_is_drawn_with_one(self) -> None:
        html = self._render(_game(betting={"p_home_win": 0.62, "p_away_win": 0.38}))
        self.assertIn('class="cards-prob-bar', html)
        self.assertIn('data-home-pct="62.0"', html)

    def test_the_draw_segment_appears_only_on_three_way_markets(self) -> None:
        two_way = self._render(_game(betting={"p_home_win": 0.62, "p_away_win": 0.38}))
        self.assertNotIn("cards-prob-draw", two_way)
        three_way = self._render(dict(ThreeWayMarketTests.SOCCER), sport="soccer")
        self.assertIn("cards-prob-draw", three_way)
        self.assertIn("data-draw-pct=", three_way)


if __name__ == "__main__":
    unittest.main()
