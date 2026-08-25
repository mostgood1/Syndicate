"""Season and slate futures were being fetched, stored and joined against.

They are real markets in sports we model, and NO board row can ever match one:
the board is built per GAME DATE and a season future has no game.

HOW THEY GOT IN. `auto_game_series_from_catalogue` registers any sport-token
series whose title TAIL resolves via `canonical_game_market`, and Kalshi titles
a division future "... Division Winner". "Winner" is a game-market word, so the
gate that exists to find moneylines admitted the futures alongside them.

WHAT IT COST, measured 2026-08-25 on `[kalshi_odds] TICK this_tick` and
`[kalshi_odds] JOIN_TITLES by_series` (21:13:07Z / 21:15:49Z): 1,661 markets of
a 6,000-market working set and 38 of 193 slots in a 60-per-tick rotation, so a
live ladder waited ~8 extra minutes behind markets that cannot be bet.
`KXNCAAFWINS` (618 listed) and `KXNCAAFAWARD` (509) were each capped at EXACTLY
400 by MAX_MARKETS_PER_SERIES -- consuming the entire per-series bound -- and
all 800 came back `unreadable_title`.

THE REGRESSION GUARD IS THE POINT OF THIS FILE. Evicting by ticker is only safe
if no series carrying real game markets went with them, and the names are
adjacent by construction (KXNBAWINS beside KXNBAGAME, KXNHLCENTRAL beside the
NHL game lines). Every market family the board actually bets is asserted still
registered, below.
"""

from __future__ import annotations

import unittest

# Measured per-series market counts, from the production lines named above.
EVICTED_WITH_COUNTS = {
    "KXNCAAFWINS": 618, "KXNCAAFAWARD": 509, "KXNBAWINS": 312,
    "KXNFLPLAYOFFHOST": 32, "KXNFLH2HWINS": 22, "KXWNBAWINS": 19,
    "KXNCAAFHIGHSCORE": 10, "KXNFLHIGHSCORE": 9, "KXNBAMOSTWINS": 4,
    "KXNFLCOMPETE": 2,
}

# Series that carry the markets the board actually bets. NONE may be evicted.
MUST_STILL_REGISTER = {
    "KXMLBGAME": "Professional Baseball Game",
    "KXMLBSPREAD": "Professional Baseball Spread",
    "KXMLBTOTAL": "Professional Baseball Total",
    "KXNFLGAME": "Professional Football Game",
    "KXNFLSPREAD": "Professional Football Spread",
    "KXNFLTOTAL": "Professional Football Total",
    "KXNCAAFGAME": "College Football Game",
    "KXNCAAFSPREAD": "College Football Spread",
    "KXNCAAFTOTAL": "College Football Total",
    "KXNBAGAME": "Pro Basketball Game",
    "KXNBASPREAD": "Pro Basketball Spread",
    "KXWNBAGAME": "Women's Pro Basketball Game",
    "KXWNBASPREAD": "Women's Pro Basketball Spread",
    "KXWNBATOTAL": "Women's Pro Basketball Total",
    "KXNHLGAME": "NHL Game",
}


class TheFuturesAreEvicted(unittest.TestCase):
    def test_every_evicted_series_is_out_of_scope_by_name(self) -> None:
        """`SERIES_OUT_OF_SCOPE`, not a silent drop: "we do not model this" and
        "we have not looked at this yet" are different states, and the work
        queue is only useful if it means the second."""
        from syndicate.features.shared.kalshi_catalogue import SERIES_OUT_OF_SCOPE

        for ticker in EVICTED_WITH_COUNTS:
            with self.subTest(ticker=ticker):
                self.assertIn(ticker, SERIES_OUT_OF_SCOPE)

    def test_a_futures_series_can_no_longer_register(self) -> None:
        """The eviction has to bite at REGISTRATION, because that is what keeps
        it out of `sports_series()` and therefore out of the fetch. Refusing it
        later would still spend the request."""
        from syndicate.features.shared.kalshi_catalogue import (
            auto_game_series_from_catalogue,
        )

        found = auto_game_series_from_catalogue({
            "KXNFLAFCEAST": "Pro Football AFC East Division Winner",
            "KXNCAAFWINS": "College Football Season Wins",
            "KXNBAWINS": "Pro Basketball Season Wins",
        })
        self.assertEqual(found, {}, found)

    def test_the_refusal_is_named_and_carries_its_category(self) -> None:
        from syndicate.features.shared.kalshi_catalogue import classify_market

        verdict = classify_market({
            "series": "KXNCAAFWINS",
            "title": "Will Alabama win over 9.5 games?",
            "ticker": "KXNCAAFWINS-26-ALA",
        })
        self.assertEqual(verdict["status"], "refused", verdict)
        self.assertEqual(verdict["reason"], "series_out_of_scope", verdict)
        self.assertEqual(verdict["detail"], "season_futures", verdict)

    def test_they_leave_the_work_queue_rather_than_filling_it(self) -> None:
        """`unmapped_series` excludes out-of-scope deliberately -- otherwise the
        queue drowns in things nobody intends to do and stops being read."""
        from syndicate.features.shared.kalshi_catalogue import unmapped_series

        gaps = unmapped_series([
            {"series": "KXNCAAFAWARD", "title": "Will Alabama win the Heisman?"},
        ])
        self.assertEqual(gaps, {}, gaps)


class NothingTheBoardBetsWasEvicted(unittest.TestCase):
    """THE GUARD. `KXNBAWINS` sits beside `KXNBAGAME`; `KXNHLCENTRAL` beside the
    NHL game lines. An eviction by ticker is only safe if it is checked."""

    def test_every_real_game_series_still_registers(self) -> None:
        from syndicate.features.shared.kalshi_catalogue import (
            auto_game_series_from_catalogue,
        )

        found = auto_game_series_from_catalogue(MUST_STILL_REGISTER)
        missing = sorted(set(MUST_STILL_REGISTER) - set(found))
        self.assertEqual(missing, [], f"evicted a real game series: {missing}")

    def test_no_real_game_series_is_out_of_scope(self) -> None:
        from syndicate.features.shared.kalshi_catalogue import SERIES_OUT_OF_SCOPE

        for ticker in MUST_STILL_REGISTER:
            with self.subTest(ticker=ticker):
                self.assertNotIn(ticker, SERIES_OUT_OF_SCOPE)

    def test_the_hand_registry_is_untouched_by_the_eviction(self) -> None:
        """`sport_for_series` checks `SERIES_SPORT` FIRST, so a hand-registered
        series and an evicted one must never be the same ticker -- that would
        be a registry that disagrees with itself."""
        from syndicate.features.shared.kalshi_catalogue import (
            SERIES_OUT_OF_SCOPE,
            SERIES_SPORT,
        )

        overlap = sorted(set(SERIES_SPORT) & set(SERIES_OUT_OF_SCOPE))
        self.assertEqual(overlap, [], f"registered AND out of scope: {overlap}")


if __name__ == "__main__":
    unittest.main()
