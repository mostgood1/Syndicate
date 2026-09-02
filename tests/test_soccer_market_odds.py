"""The odds feed that makes soccer market-anchoring reachable at all.

`anchor_ratings_to_market` is validated (-40..-51% MAE vs a HELD-OUT consensus)
and has never run, because production fixtures carry no `market_odds` and the
anchor silently `continue`s past them. These tests pin the two arithmetic rules
this repo has already broken once each, and the counting that stops a silent
no-op from reading as success.
"""
from __future__ import annotations

import unittest

from syndicate.features.soccer.features.market_odds import (
    american_to_probability,
    attach_market_odds,
    home_win_probability_by_event,
)


def _row(side: str, price, book: str = "bookA", event: str = "e1",
         market: str = "h2h", home: str = "Home FC", away: str = "Away FC") -> dict:
    return {"league": "epl", "event_id": event, "home_team": home, "away_team": away,
            "commence_time": "2026-09-12T19:00:00Z", "market": market,
            "side": side, "line": "", "price": price, "book": book}


def _three_way(prices: dict, event: str = "e1", book: str = "bookA") -> list[dict]:
    return [_row("Home FC", prices["home"], book, event),
            _row("Draw", prices["draw"], book, event),
            _row("Away FC", prices["away"], book, event)]


class AmericanConversionTests(unittest.TestCase):
    def test_real_prices_convert(self) -> None:
        self.assertAlmostEqual(american_to_probability(-205), 205 / 305, places=9)
        self.assertAlmostEqual(american_to_probability(+180), 100 / 280, places=9)
        self.assertAlmostEqual(american_to_probability(-100), 0.5, places=9)

    def test_a_price_inside_the_hole_is_REFUSED(self) -> None:
        """Strictly inside (-100, 100) is not an American price. Coercing one
        invents a probability."""
        for bad in (-99.9, -50, 0, 42, 99.9):
            self.assertIsNone(american_to_probability(bad), bad)

    def test_junk_is_refused_not_crashed(self) -> None:
        for bad in (None, "", "abc", [], {}):
            self.assertIsNone(american_to_probability(bad), repr(bad))


class DevigTests(unittest.TestCase):
    def test_the_three_sides_sum_to_one(self) -> None:
        priced = home_win_probability_by_event(_three_way({"home": -150, "draw": +260, "away": +420}))
        self.assertIn("e1", priced)
        self.assertGreater(priced["e1"]["overround"], 1.0, "a real book has vig")
        self.assertTrue(0 < priced["e1"]["home_win_probability"] < 1)

    def test_averaging_happens_in_PROBABILITY_space_not_on_the_american_scale(self) -> None:
        """The `[wnba-consensus-price]` defect: averaging -400 and +300 on the
        American scale is meaningless and made 43% of card prices impossible.
        Two books at -400 and +300 must average to the mean of their
        PROBABILITIES, not to the probability of their mean price."""
        rows = _three_way({"home": -400, "draw": +300, "away": +300}, book="A")
        rows += _three_way({"home": +300, "draw": +300, "away": +300}, book="B")
        priced = home_win_probability_by_event(rows)["e1"]

        prob_space_home = (american_to_probability(-400) + american_to_probability(300)) / 2
        american_mean_home = american_to_probability((-400 + 300) / 2)  # -50 -> refused
        self.assertIsNone(american_mean_home, "the american mean is not even a price here")

        expected = prob_space_home / (prob_space_home
                                      + american_to_probability(300)
                                      + american_to_probability(300))
        self.assertAlmostEqual(priced["home_win_probability"], expected, places=9)

    def test_a_two_way_event_is_EXCLUDED_not_devigged(self) -> None:
        """Soccer h2h is three-way. De-vigging two sides would systematically
        overstate both, which is worse than having no anchor."""
        rows = [_row("Home FC", -150), _row("Away FC", +420)]
        self.assertEqual(home_win_probability_by_event(rows), {})

    def test_refused_prices_are_counted_not_hidden(self) -> None:
        rows = _three_way({"home": -150, "draw": +260, "away": +420}, book="A")
        rows.append(_row("Home FC", -50, book="B"))          # in the hole
        priced = home_win_probability_by_event(rows)["e1"]
        self.assertEqual(priced["refused_prices"], 1)

    def test_non_h2h_markets_are_ignored(self) -> None:
        rows = _three_way({"home": -150, "draw": +260, "away": +420})
        rows.append(_row("Over", -110, market="totals"))
        self.assertIn("e1", home_win_probability_by_event(rows))

    def test_a_side_naming_neither_team_is_ignored(self) -> None:
        rows = _three_way({"home": -150, "draw": +260, "away": +420})
        rows.append(_row("Some Other Club", -110))
        priced = home_win_probability_by_event(rows)["e1"]
        self.assertTrue(0 < priced["home_win_probability"] < 1)

    def test_more_books_move_the_consensus(self) -> None:
        one = home_win_probability_by_event(_three_way({"home": -150, "draw": +260, "away": +420}))
        rows = _three_way({"home": -150, "draw": +260, "away": +420}, book="A")
        rows += _three_way({"home": +200, "draw": +260, "away": +420}, book="B")
        two = home_win_probability_by_event(rows)
        self.assertEqual(two["e1"]["books"], 2)
        self.assertLess(two["e1"]["home_win_probability"], one["e1"]["home_win_probability"])


class AttachTests(unittest.TestCase):
    """A silent no-op is the failure mode. The COUNTS are the guard."""

    def test_an_unpriced_slate_reports_zero_attached_rather_than_looking_fine(self) -> None:
        fixtures = [{"match_id": "x", "home_team": "A", "away_team": "B"}]
        audit = attach_market_odds(fixtures, {})
        self.assertEqual(audit["attached"], 0)
        self.assertEqual(audit["skipped"], 1)
        self.assertNotIn("market_odds", fixtures[0], "nothing to attach means nothing attached")

    def test_a_priced_fixture_gets_the_block_the_anchor_reads(self) -> None:
        fixtures = [{"match_id": "e1", "home_team": "Home FC", "away_team": "Away FC"}]
        priced = home_win_probability_by_event(_three_way({"home": -150, "draw": +260, "away": +420}))
        audit = attach_market_odds(fixtures, priced)
        self.assertEqual(audit["attached"], 1)
        self.assertIn("home_win_probability", fixtures[0]["market_odds"])

    def test_it_falls_back_to_the_team_pair_when_match_id_was_synthesised(self) -> None:
        """`build_soccer_artifacts` synthesises match_id when event_id is
        absent, so keying only on it would drop fixtures the feed covers."""
        fixtures = [{"match_id": "epl_2026-09-12_Home_FC_Away_FC",
                     "home_team": "Home FC", "away_team": "Away FC"}]
        priced = home_win_probability_by_event(_three_way({"home": -150, "draw": +260, "away": +420}))
        audit = attach_market_odds(fixtures, priced)
        self.assertEqual(audit["attached"], 1)

    def test_the_audit_names_what_was_skipped(self) -> None:
        fixtures = [{"match_id": "z", "home_team": "Ghost", "away_team": "Phantom"}]
        audit = attach_market_odds(fixtures, {})
        self.assertIn("Ghost v Phantom", audit["skipped_examples"])


if __name__ == "__main__":
    unittest.main()
