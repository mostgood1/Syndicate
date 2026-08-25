"""#224 -- canonical market keys, the join key between board and odds feed."""
from __future__ import annotations
import unittest
from syndicate.features.shared.market_keys import canonical_market_key as k


class MarketKeyTests(unittest.TestCase):
    def test_display_labels_map_to_the_feeds_vocabulary(self) -> None:
        """The whole point: the board says "Hits", book_quotes says
        "batter_hits", and nothing joined until these met."""
        self.assertEqual(k("mlb", "Hits"), "batter_hits")
        self.assertEqual(k("mlb", "Total Bases"), "batter_total_bases")
        self.assertEqual(k("mlb", "Outs Recorded"), "outs")
        self.assertEqual(k("mlb", "Walks Allowed"), "walks_allowed")

    def test_game_markets_are_sport_agnostic(self) -> None:
        """ATS, run line and puck line are the same wager, and h2h/totals are
        the same words in every sport -- so these are not per-sport tables."""
        for sport in ("mlb", "nba", "nfl", "nhl", "soccer"):
            self.assertEqual(k(sport, "Moneyline"), "h2h")
            self.assertEqual(k(sport, "Total"), "totals")
        self.assertEqual(k("nfl", "ATS"), "spreads")
        self.assertEqual(k("nhl", "Puck Line"), "spreads")
        self.assertEqual(k("mlb", "Run Line"), "spreads")

    def test_the_same_tri_code_means_different_things_per_sport(self) -> None:
        self.assertEqual(k("wnba", "Pts"), "player_points")
        self.assertEqual(k("nba", "Threes"), "player_threes")

    def test_first_resolvable_value_wins(self) -> None:
        """Callers pass candidates in order of trustworthiness -- explicit key,
        then stat, then label."""
        self.assertEqual(k("mlb", None, "", "total_bases", "Total Bases"), "batter_total_bases")

    def test_an_unknown_label_returns_none_rather_than_guessing(self) -> None:
        """A wrong key silently joins a bet to another market's price, which is
        worse than an unjoined row -- the #217 lesson."""
        self.assertIsNone(k("mlb", "Simulations: 400"))
        self.assertIsNone(k("mlb", "Projected score"))
        self.assertIsNone(k("mlb", None))
        self.assertIsNone(k("mlb", ""))

    def test_a_key_already_in_the_feeds_vocabulary_passes_through(self) -> None:
        """A market we have no label for yet still joins; dropping it would
        lose a key we already hold."""
        self.assertEqual(k("mlb", "batter_singles"), "batter_singles")
        self.assertEqual(k("nba", "player_blocks"), "player_blocks")

    def test_underscore_and_space_spellings_are_the_same_key(self) -> None:
        self.assertEqual(k("mlb", "outs_recorded"), k("mlb", "Outs Recorded"))
        self.assertEqual(k("mlb", "home runs"), k("mlb", "home_runs"))

    def test_kalshis_own_hits_runs_rbis_wording_resolves(self) -> None:
        """The exact string production reported refusing, verbatim.

        MEASURED 2026-08-25T20:33:06Z: `GAP series=KXMLBHRR count=136
        reason=stat_not_in_market_vocabulary detail='hits + runs + RBIs'`. The
        underscored spellings were already here and did not cover it, so the
        largest MLB prop family on Kalshi refused every market while the series
        sat registered -- indistinguishable from a series Kalshi does not list.
        """
        self.assertEqual(k("mlb", "hits + runs + RBIs"), "batter_hits_runs_rbis")

    def test_the_near_spellings_of_hits_runs_rbis_resolve_too(self) -> None:
        """Widening cannot mismap -- no other baseball market means this -- and
        adding only the one wording we happened to see is what left
        `player_threes` refusing."""
        for spelling in (
            "hits + runs + rbi",
            "hits+runs+rbis",
            "hits runs rbis",
            "H+R+RBI",
            "HRR",
            "hits_runs_rbis",
        ):
            with self.subTest(spelling=spelling):
                self.assertEqual(k("mlb", spelling), "batter_hits_runs_rbis")

    def test_stolen_bases_resolves_to_the_key_this_repo_already_uses(self) -> None:
        """`batter_stolen_bases` is not invented here: `test_mlb_ladders_build`
        keeps it in `known_unfed`, i.e. the sim models it and nothing prices
        it. `KXMLBSB` is that price source."""
        self.assertEqual(k("mlb", "stolen bases"), "batter_stolen_bases")
        self.assertEqual(k("mlb", "Stolen Bases"), "batter_stolen_bases")
        self.assertEqual(k("mlb", "stolen_bases"), "batter_stolen_bases")

    def test_the_new_entries_did_not_leak_into_another_sport(self) -> None:
        """`_MLB` is per-sport and must stay that way -- a basketball board
        asking for stolen bases must still get None, not a baseball key."""
        self.assertIsNone(k("nba", "stolen bases"))
        self.assertIsNone(k("wnba", "hits + runs + RBIs"))


if __name__ == "__main__":
    unittest.main()
