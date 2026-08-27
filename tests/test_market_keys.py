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

    def test_hockey_resolves_the_stats_kalshi_lists_series_for(self) -> None:
        """`_BY_SPORT` had no `nhl` key, and `auto_series_from_catalogue`
        requires this call to resolve before it will register a prop series --
        so NO NHL prop could ever auto-register, in season or out.

        The values are this repo's own: `vendor/nhl_betting_repo/.../
        player_props.py` requests player_points/assists/goals/shots_on_goal
        and its comment calls them "confirmed by provider docs and our live
        probes".
        """
        self.assertEqual(k("nhl", "saves"), "player_saves")
        self.assertEqual(k("nhl", "points"), "player_points")
        self.assertEqual(k("nhl", "goals"), "player_goals")
        self.assertEqual(k("nhl", "assists"), "player_assists")
        self.assertEqual(k("nhl", "shots on goal"), "player_shots_on_goal")
        self.assertEqual(k("nhl", "SOG"), "player_shots_on_goal")
        self.assertEqual(k("nhl", "blocked shots"), "player_blocked_shots")

    def test_hockey_refuses_a_stat_from_another_sport(self) -> None:
        """None is a real answer. A hockey board asking for hits or rebounds
        must not acquire a baseball or basketball key."""
        self.assertIsNone(k("nhl", "rebounds"))
        self.assertIsNone(k("nhl", "home runs"))
        self.assertIsNone(k("nhl", "receptions"))

    def test_the_anytime_goal_scorer_market_is_deliberately_not_mapped(self) -> None:
        """`KXNHLANYGOAL` is a ticker we have SEEN and a title we have NOT.

        Whether it is a player prop or a team market is unknown, and this repo
        carries two different spellings of that key
        (`player_goal_scorer_anytime` in `_SOCCER`, `player_anytime_goal_scorer`
        in `test_layer2_excluded_markets`). Guessing between them on an unread
        title is how a bet gets priced as a different bet. Refusing sends the
        series to the COVERAGE_GAPS queue by name, carrying its real title.

        Delete this test the day that title is read -- not before.
        """
        self.assertIsNone(k("nhl", "anytime goal scorer"))
        self.assertIsNone(k("nhl", "goalscorer"))

    def test_ncaab_shares_the_basketball_vocabulary(self) -> None:
        """Exactly as `ncaaf` shares football's. `_TOTAL_UNIT` already carried
        `ncaab`, so a college GAME TOTAL resolved while every college PLAYER
        PROP refused -- which is what made the gap read as coverage."""
        self.assertEqual(k("ncaab", "points"), "player_points")
        self.assertEqual(k("ncaab", "rebounds"), "player_rebounds")
        self.assertEqual(k("ncaab", "assists"), "player_assists")
        self.assertEqual(k("ncaab", "three pointers made"), "player_threes")
        self.assertEqual(k("ncaab", "points"), k("nba", "points"))

    def test_ncaab_does_not_price_ncaa_BASEBALL_off_a_basketball_map(self) -> None:
        """THE ONE REAL COLLISION IN THIS TABLE, and the reason `ncaab` was not
        simply aliased without checking.

        `sport_for_ticker` matches `NCAAB` as a SUBSTRING, and
        `KXNCAABASEBALL` -- NCAA *baseball*, observed in the live catalogue
        2026-08-25T20:21:24Z -- contains it. So a baseball series resolves to
        sport `ncaab` and reaches the basketball map. It must still refuse.
        """
        for baseball_stat in ("home runs", "hits", "RBIs", "strikeouts", "total bases"):
            with self.subTest(stat=baseball_stat):
                self.assertIsNone(k("ncaab", baseball_stat))

    def test_the_new_entries_did_not_leak_into_another_sport(self) -> None:
        """`_MLB` is per-sport and must stay that way -- a basketball board
        asking for stolen bases must still get None, not a baseball key."""
        self.assertIsNone(k("nba", "stolen bases"))
        self.assertIsNone(k("wnba", "hits + runs + RBIs"))


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# "FULL GAME" IS THE ABSENCE OF A PERIOD. Measured 2026-08-26T01:49:32Z, on the
# first tick that could read these titles at all:
#
#   GAP series=KXNFLTOTAL count=304 reason=stat_not_in_market_vocabulary
#       detail='Full Game points scored'
#       sample='Full Game: over 58.5 points scored?'
#
# 304 markets parsed and then refused one gate later for want of one entry --
# the same shape the coverage audit records for KXMLBHRR.
# ---------------------------------------------------------------------------


def test_full_game_resolves_to_the_bare_game_total():
    from syndicate.features.shared.market_keys import total_market_from_stat

    assert total_market_from_stat("nfl", "Full Game points scored") == "totals"
    assert total_market_from_stat("nfl", "full game points") == "totals"
    assert total_market_from_stat("mlb", "Full Game runs") == "totals"


def test_full_game_does_not_disturb_the_real_periods():
    from syndicate.features.shared.market_keys import total_market_from_stat

    assert total_market_from_stat("nfl", "1Q points scored") == "totals_q1"
    assert total_market_from_stat("nfl", "2nd half points") == "totals_h2"
    assert total_market_from_stat("nfl", "points scored") == "totals"


def test_full_game_with_no_unit_is_still_refused():
    """The `token == phrase` guard. A title naming a period and no stat says
    nothing about WHAT is being counted, and guessing the sport's default unit
    would price a market we did not read."""
    from syndicate.features.shared.market_keys import total_market_from_stat

    assert total_market_from_stat("nfl", "Full Game") is None


def test_full_game_does_not_widen_the_totals_unit():
    """The audit is explicit: "Needs a corners market. Do not widen the totals
    unit." Stripping a period must never make a foreign unit acceptable."""
    from syndicate.features.shared.market_keys import total_market_from_stat

    assert total_market_from_stat("soccer", "Full Game corners") is None
    assert total_market_from_stat("nfl", "Full Game receptions") is None
