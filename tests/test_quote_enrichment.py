"""#215 -- price context on board rows, and best-price re-ranking.

The defect: a Layer 2 candidate row is built from
display_pick/ev_pct/p_win/market_label/selection and carries no price, no book
and no timestamp, so "which book has the edge" had nowhere to live and the board
could not tell a dead market from a fresh one.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from syndicate.features.shared import odds_book_quotes as quotes_module
from syndicate.features.shared.odds_book_quotes import append_book_quotes
from syndicate.features.shared.quote_enrichment import _game_date, enrich_recommendation_rows

DATE = "2026-08-06"
NOW = datetime(2026, 8, 6, 22, 0, 0, tzinfo=timezone.utc)
GAME = {"event_id": "evt-1", "game_date": DATE, "home_team": "New York Yankees", "away_team": "Boston Red Sox"}


def _quote(book: str, price: int, *, when: str = "2026-08-06T21:55:00Z") -> dict:
    return {
        "kind": "game", "event_id": "evt-1", "commence_time": "2026-08-06T23:05:00Z",
        "home_team": "New York Yankees", "away_team": "Boston Red Sox", "segment": "full",
        "market": "h2h", "selection": "home", "bookmaker": book, "price": price,
        "book_updated_at": when,
    }


class EnrichmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch.object(quotes_module, "data_root", lambda: Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        append_book_quotes(
            sport="mlb", date_str=DATE, publish=False, captured_at="2026-08-06T21:58:00Z",
            rows=[_quote("fanduel", -130), _quote("draftkings", -110), _quote("betmgm", -120)],
        )

    def _rows(self, **overrides) -> list[dict]:
        row = {"market_label": "Moneyline", "display_pick": "Home ML", "selection": "home",
               "odds": -130, "confidence": 0.55}
        row.update(overrides)
        return [row]

    def test_row_gains_the_book_and_the_field_it_was_priced_against(self) -> None:
        rows = enrich_recommendation_rows(GAME, self._rows(), sport_slug="mlb", now=NOW)
        quote = rows[0]["quote"]
        self.assertEqual(quote["best_bookmaker"], "draftkings")
        self.assertEqual(quote["best_price"], -110)
        self.assertEqual(quote["books_quoting"], 3)

    def test_ev_is_recomputed_against_best_price_not_an_arbitrary_book(self) -> None:
        """This changes WHICH candidates surface, not just how they look. #211
        measured 140 bets clearing a 3% threshold under best price and 0 the
        other way, because best price is never worse."""
        rows = enrich_recommendation_rows(GAME, self._rows(ev_pct=1.0), sport_slug="mlb", now=NOW)
        # model 55% vs -110 implied 52.38% -> ~2.6 points, up from the seeded 1.0
        self.assertAlmostEqual(rows[0]["ev_pct"], 2.62, places=1)
        self.assertEqual(rows[0]["ev_priced_against"], "draftkings")

    def test_price_improvement_is_what_shopping_is_worth_on_this_bet(self) -> None:
        rows = enrich_recommendation_rows(GAME, self._rows(), sport_slug="mlb", now=NOW)
        # Row was priced at -130; best is -110. Moving book is worth real points.
        self.assertGreater(rows[0]["price_improvement_pct"], 0)

    def test_percent_and_fraction_probabilities_are_both_understood(self) -> None:
        """Sports modules are inconsistent about this on real rows; reading 55
        as a probability of 5500% would produce a nonsense edge."""
        as_fraction = enrich_recommendation_rows(GAME, self._rows(confidence=0.55), sport_slug="mlb", now=NOW)
        as_percent = enrich_recommendation_rows(GAME, self._rows(confidence=55.0), sport_slug="mlb", now=NOW)
        self.assertAlmostEqual(as_fraction[0]["ev_pct"], as_percent[0]["ev_pct"], places=4)

    def test_a_bet_on_another_game_gets_no_quote_rather_than_a_wrong_one(self) -> None:
        """Identity is a HARD filter. An earlier version fell back through
        every narrowing step, so an unmatched event came back with some other
        game's price -- strictly worse than nothing, because #213 records the
        quote at bet time and a wrong one poisons CLV."""
        rows = enrich_recommendation_rows(
            {"event_id": "some-other-game", "game_date": DATE,
             "home_team": "Chicago Cubs", "away_team": "St. Louis Cardinals"},
            self._rows(ev_pct=1.0), sport_slug="mlb", now=NOW,
        )
        self.assertIsNone(rows[0].get("quote"), "attached a quote from an unrelated game")
        self.assertEqual(rows[0]["ev_pct"], 1.0)

    def test_teams_join_when_the_event_ids_are_from_different_id_spaces(self) -> None:
        """The real production case: MLB board rows carry a StatsAPI gamePk,
        quotes carry an OddsAPI hash, so the ids can never match and the team
        pair is the only usable join."""
        rows = enrich_recommendation_rows(
            {"event_id": "824804", "game_date": DATE, "matchup": "BOS @ NYY"},
            self._rows(), sport_slug="mlb", now=NOW,
        )
        self.assertIsNotNone(rows[0].get("quote"), "tri-code matchup failed to join full team names")
        self.assertEqual(rows[0]["quote"]["best_bookmaker"], "draftkings")

    def test_rows_without_a_quote_are_kept_and_left_alone(self) -> None:
        """A missing quote means the odds log has nothing for that market yet --
        not that the pick is invalid. Dropping them would make the board look
        emptier the further back you look."""
        rows = enrich_recommendation_rows(
            {"event_id": "unknown-event", "game_date": "1999-01-01"},
            self._rows(ev_pct=1.0), sport_slug="mlb", now=NOW,
        )
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0].get("quote"))
        self.assertEqual(rows[0]["ev_pct"], 1.0, "original ev must survive untouched")

    def test_a_game_with_no_date_is_a_no_op_not_a_crash(self) -> None:
        rows = enrich_recommendation_rows({}, self._rows(), sport_slug="mlb", now=NOW)
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0].get("quote"))

    def test_enrichment_never_raises(self) -> None:
        """The board rendering without price context is a degradation; the board
        500ing because the odds log was mid-write is an outage."""
        with patch.object(quotes_module, "read_book_quotes", side_effect=OSError("disk gone")):
            rows = enrich_recommendation_rows(GAME, self._rows(), sport_slug="mlb", now=NOW)
        self.assertEqual(len(rows), 1)

    def test_two_clocks_reach_the_row(self) -> None:
        rows = enrich_recommendation_rows(GAME, self._rows(), sport_slug="mlb", now=NOW)
        quote = rows[0]["quote"]
        self.assertIsNotNone(quote["book_age_seconds"])
        self.assertIsNotNone(quote["capture_age_seconds"])
        self.assertNotEqual(quote["book_updated_at"], quote["captured_at"])


class ProductionGameShapeTests(unittest.TestCase):
    """The exact game-dict shape /api/home really serves, copied from a live
    2026-08-06 payload.

    This is the shape that broke it: `gameDate` not `game_date`, and `matchup`
    as a DICT of team objects rather than the "LAA @ BAL" string the candidate
    rows carry. Every earlier test built its own tidy game dict and so proved
    nothing about the real one -- the lookup worked perfectly offline while
    every production candidate came back with quote: null.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch.object(quotes_module, "data_root", lambda: Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        append_book_quotes(
            sport="mlb", date_str=DATE, publish=False, captured_at="2026-08-06T21:58:00Z",
            rows=[
                {**_quote(book, price), "home_team": "Baltimore Orioles",
                 "away_team": "Los Angeles Angels", "event_id": "oddsapi-hash"}
                for book, price in (("fanduel", -130), ("draftkings", -110), ("betmgm", -120))
            ],
        )

    def _game(self) -> dict:
        return {
            "gamePk": 824804,
            "gameDate": "2026-08-06T16:35:00Z",
            "officialDate": DATE,
            "matchup": {
                "home": {"abbr": "BAL", "id": 110, "name": "Baltimore Orioles"},
                "away": {"abbr": "LAA", "id": 108, "name": "Los Angeles Angels"},
                "score": {"away": 0, "home": 0},
            },
        }

    def test_camelcase_date_and_dict_matchup_still_resolve(self) -> None:
        rows = enrich_recommendation_rows(
            self._game(),
            [{"market_label": "Moneyline", "display_pick": "Home ML", "selection": "home",
              "odds": -130, "confidence": 0.55}],
            sport_slug="mlb", now=NOW,
        )
        quote = rows[0].get("quote")
        self.assertIsNotNone(quote, "the real production game shape produced no quote")
        self.assertEqual(quote["best_bookmaker"], "draftkings")
        self.assertEqual(quote["books_quoting"], 3)
        self.assertGreater(rows[0]["price_improvement_pct"], 0)

    def test_a_dict_matchup_is_never_stringified_into_the_matcher(self) -> None:
        """str() on that dict is a blob of JSON containing both team names and
        would match essentially anything."""
        from syndicate.features.shared.quote_enrichment import _team_names

        home, away, matchup = _team_names(self._game())
        self.assertEqual(home, "Baltimore Orioles")
        self.assertEqual(away, "Los Angeles Angels")
        self.assertIsNone(matchup)


if __name__ == "__main__":
    unittest.main()


class GameDateIsASlateDateNotAUtcDateTests(unittest.TestCase):
    """`#321`. A late West Coast game vanished from its own slate.

    Measured on production 2026-08-10: StatsAPI listed 15 games for
    2026-08-09 and the board showed 14, dropping pk 823268 (Houston Astros @
    San Diego Padres) while also rendering every remaining game as final --
    that game was still In Progress.

    Any first pitch at or after 19:00 Central is the NEXT UTC day, so reading
    `gameDate` before `officialDate` and slicing `[:10]` loses exactly the
    late games: the ones still live when the rest of the slate has finished,
    and the ones the board is worth most for.
    """

    def test_official_date_beats_the_utc_gamedate_it_used_to_lose_to(self):
        self.assertEqual(
            _game_date({"gameDate": "2026-08-10T00:20:00Z", "officialDate": "2026-08-09"}),
            "2026-08-09",
        )

    def test_a_utc_timestamp_alone_resolves_to_its_central_calendar_day(self):
        # No officialDate to fall back on: the conversion itself must be right,
        # not merely preferred against a better field.
        self.assertEqual(_game_date({"gameDate": "2026-08-10T00:20:00Z"}), "2026-08-09")
        self.assertEqual(_game_date({"commence_time": "2026-08-10T02:20:00Z"}), "2026-08-09")

    def test_an_afternoon_game_is_unaffected(self):
        # The regression this guards is one-directional; day games never
        # crossed the boundary and must not start moving now.
        self.assertEqual(_game_date({"gameDate": "2026-08-09T16:35:00Z"}), "2026-08-09")

    def test_start_time_is_a_display_string_and_not_a_date(self):
        # Board game dicts carry startTime as "7:20 PM". It only ever passed
        # the old `len >= 10` check by accident.
        self.assertIsNone(_game_date({"startTime": "7:20 PM"}))

    def test_an_unparseable_but_date_shaped_value_still_returns_something(self):
        # Enrichment returning early makes every candidate come back with
        # quote: null (2026-08-06). A slightly wrong date beats that.
        self.assertEqual(_game_date({"gameDate": "2026-13-99T99:99:99Z"}), "2026-13-99")
