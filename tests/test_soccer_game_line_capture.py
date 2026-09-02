"""Soccer venue GAME lines may be captured; every other sport stays props-only.

The props-only bound exists because `_KEY_FIELDS` carries no `source`, so a
directly-captured venue row and OddsAPI's copy of the same market share a key
and ALTERNATE. That premise is sport-specific and MEASURABLY FALSE for soccer:

    mlb    2026-08-31   2,350 polymarket GAME rows (collision is real)
    soccer 08-31..09-05  0 exchange rows of ANY kind in 92,795, six dates
    soccer 2026-09-01    0 of 6,205, re-read after 51 Kalshi soccer matches
                         existed -- so the zero is current, not stale

Soccer venue matches are ALL game lines (a club is not a player), so the bound
discarded 51 of 51 matched Kalshi soccer markets on 2026-09-01T23:41Z.
"""

from __future__ import annotations

from syndicate.features.shared.odds_book_quotes import (
    quote_rows_from_kalshi_matches,
    quote_rows_from_polymarket_matches,
    sport_allows_game_line_capture,
)


def _kalshi_game():
    return {"board_event_id": "e1", "market": "h2h", "board_side": "home",
            "kalshi_american": 120, "line": None, "player_name": None}


def _kalshi_prop():
    return {"board_event_id": "e1", "market": "strikeouts", "board_side": "over",
            "kalshi_american": -110, "line": 5.5, "player_name": "Lake Bachar"}


def _poly_game():
    return {"event_id": "e1", "market": "h2h", "side": "home",
            "polymarket_american": 120, "line": None, "player_name": None}


class TestThePredicate:
    def test_soccer_is_the_only_sport_allowed_game_line_capture(self):
        assert sport_allows_game_line_capture("soccer")
        for sport in ("mlb", "nba", "wnba", "nhl", "nfl", "ncaaf", "ncaab", ""):
            assert not sport_allows_game_line_capture(sport), sport

    def test_the_predicate_is_case_and_whitespace_insensitive(self):
        assert sport_allows_game_line_capture("  Soccer ")


class TestKalshi:
    def test_a_game_line_is_DROPPED_by_default(self):
        """The bound still holds everywhere it was measured to matter."""
        assert quote_rows_from_kalshi_matches([_kalshi_game()]) == []

    def test_a_game_line_is_KEPT_when_the_sport_opts_in(self):
        rows = quote_rows_from_kalshi_matches([_kalshi_game()], allow_game_lines=True)
        assert len(rows) == 1
        assert rows[0]["kind"] == "game"
        assert rows[0]["player_name"] is None
        assert rows[0]["bookmaker"] == "kalshi"
        assert rows[0]["market"] == "h2h"

    def test_props_are_unaffected_in_both_modes(self):
        """off != on must differ ONLY for game lines."""
        off = quote_rows_from_kalshi_matches([_kalshi_prop()])
        on = quote_rows_from_kalshi_matches([_kalshi_prop()], allow_game_lines=True)
        assert off == on
        assert len(off) == 1 and off[0]["kind"] == "prop"

    def test_a_priceless_match_is_still_refused_when_opted_in(self):
        """The opt-in widens WHICH markets qualify, not what counts as a price."""
        broken = dict(_kalshi_game(), kalshi_american=None)
        assert quote_rows_from_kalshi_matches([broken], allow_game_lines=True) == []


class TestPolymarket:
    def test_a_game_line_is_DROPPED_by_default(self):
        assert quote_rows_from_polymarket_matches([_poly_game()]) == []

    def test_a_game_line_is_KEPT_when_the_sport_opts_in(self):
        rows = quote_rows_from_polymarket_matches([_poly_game()], allow_game_lines=True)
        assert len(rows) == 1
        assert rows[0]["kind"] == "game" and rows[0]["bookmaker"] == "polymarket"

    def test_both_venues_read_ONE_predicate(self):
        """Two literals that must agree is the drift this module keeps paying
        for -- both call sites resolve the sport through the same function."""
        allow = sport_allows_game_line_capture("soccer")
        assert quote_rows_from_kalshi_matches([_kalshi_game()], allow_game_lines=allow)
        assert quote_rows_from_polymarket_matches([_poly_game()], allow_game_lines=allow)


def test_the_source_stamp_is_STILL_not_in_the_dedup_key():
    """The REAL remedy remains unbuilt, and this relaxation does not pretend
    otherwise: it rests on soccer having nothing to collide with, not on the
    key being able to tell two sources apart."""
    from syndicate.features.shared.odds_book_quotes import _KEY_FIELDS

    assert "source" not in _KEY_FIELDS
