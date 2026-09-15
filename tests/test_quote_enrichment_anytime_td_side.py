"""Anytime TD props join the YES side, not whichever side more books quote.

Anytime TD quotes are one-sided rows (`selection="yes"`, no line). The board's
pick is display text -- "Anytime TD" (NFL) or "Anytime TD - 3 books" (NCAAF) --
which matches no quote selection, so `quote_ref_for_bet`'s side filter fell
through and the group with the most books won. Replayed over production on
2026-09-15 it was right on 102 of 102 NCAAF rows only because no "No" side had
been captured. These tests hold a shard where the No has MORE books.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from syndicate.features.shared import odds_book_quotes as quotes_module
from syndicate.features.shared import quote_enrichment
from syndicate.features.shared.odds_book_quotes import append_book_quotes, quote_ref_for_bet

DATE = "2026-09-19"
NOW = datetime(2026, 9, 19, 15, 0, tzinfo=timezone.utc)
PLAYER = "Tylik Hill"


def _prop_quote(book: str, selection: str, price: int) -> dict:
    return {
        "kind": "prop", "event_id": "evt-ncaaf-1", "commence_time": "2026-09-19T19:00:00Z",
        "home_team": "Pittsburgh", "away_team": "Syracuse", "segment": "full",
        "market": "Anytime TD", "selection": selection, "player_name": PLAYER, "line": None,
        "bookmaker": book, "price": price, "book_updated_at": "2026-09-19T14:55:00Z",
    }


@pytest.fixture(autouse=True)
def _shard(tmp_path, monkeypatch):
    monkeypatch.setattr(quotes_module, "data_root", lambda: tmp_path)
    rows = [
        # YES: 2 books.
        _prop_quote("fanduel", "yes", 150),
        _prop_quote("draftkings", "yes", 140),
        # NO: 3 books -- more than the Yes, so an unnarrowed join picks it.
        _prop_quote("fanduel", "no", -200),
        _prop_quote("draftkings", "no", -190),
        _prop_quote("betmgm", "no", -210),
    ]
    for sport in ("ncaaf", "nfl"):
        append_book_quotes(sport=sport, date_str=DATE, rows=rows, publish=False, captured_at="2026-09-19T14:58:00Z")


def _prop_row(sport: str, pick: str, **extra) -> dict:
    row = {"sport_slug": sport, "player_name": PLAYER, "market": "Anytime TD", "pick": pick,
           "line": "-", "odds": "150", "slate_date": DATE}
    row.update(extra)
    return row


def test_precondition_the_display_pick_alone_prices_the_no_side():
    """The frame can be wrong: with the argument the join used to pass, the No wins."""
    quote = quote_ref_for_bet(sport="ncaaf", date_str=DATE, market="Anytime TD",
                              selection="Anytime TD - 3 books", line="-", player_name=PLAYER, now=NOW)
    assert quote is not None
    assert quote["books_quoting"] == 3
    assert quote["best_price"] == -190


@pytest.mark.parametrize("sport,pick", [("ncaaf", "Anytime TD - 3 books"), ("nfl", "Anytime TD")])
def test_prop_row_prices_the_yes_side(sport, pick):
    rows = quote_enrichment.enrich_prop_rows([_prop_row(sport, pick)], date_str="2026-09-15", now=NOW)
    quote = rows[0]["quote"]
    assert quote["books_quoting"] == 2
    assert quote["best_price"] == 150


def test_an_explicit_no_pick_keeps_the_no_side():
    rows = quote_enrichment.enrich_prop_rows([_prop_row("ncaaf", "No Anytime TD")], date_str="2026-09-15", now=NOW)
    assert rows[0]["quote"]["books_quoting"] == 3


def test_candidate_row_prices_the_yes_side():
    game = {"event_id": "not-an-oddsapi-id", "game_date": DATE}
    candidate = {"player_name": PLAYER, "market": "Anytime TD", "pick": "Anytime TD", "odds": "150"}
    rows = quote_enrichment.enrich_candidate_rows(game, [candidate], sport_slug="nfl", now=NOW)
    assert rows[0]["quote"]["books_quoting"] == 2
    assert rows[0]["best_price"] == 150


def test_join_arguments_off_vs_on(monkeypatch):
    """Reachability at the join itself: the selection `quote_ref_for_bet` receives."""
    seen: list = []

    def _capture(**kwargs):
        seen.append(kwargs.get("selection"))
        return None

    monkeypatch.setattr(quotes_module, "quote_ref_for_bet", _capture)
    quote_enrichment.enrich_prop_rows(
        [
            _prop_row("ncaaf", "Anytime TD - 3 books"),
            _prop_row("nfl", "Anytime TD"),
            _prop_row("ncaaf", "No Anytime TD"),
            # Other markets: the hint passes through unchanged.
            _prop_row("ncaaf", "Over 34.5 Receiving Yards - 1 book", market="Receiving Yards", line="34.5"),
            _prop_row("nfl", "Over 1.5 Passing TDs", market="Passing TDs", line="1.5"),
            # Soccer has no Anytime TD market; its goalscorer rows are untouched.
            _prop_row("soccer", "Anytime Goalscorer", market="Anytime Goalscorer"),
        ],
        date_str="2026-09-15",
        now=NOW,
    )
    quote_enrichment.enrich_candidate_rows(
        {"event_id": "x", "game_date": DATE},
        [{"player_name": PLAYER, "market": "Anytime TD", "pick": "Anytime TD"},
         {"player_name": PLAYER, "market": "Rushing Yards", "pick": "Over 60.5 Rushing Yards"}],
        sport_slug="nfl",
        now=NOW,
    )
    assert seen == [
        "yes",
        "yes",
        "No Anytime TD",
        "Over 34.5 Receiving Yards - 1 book",
        "Over 1.5 Passing TDs",
        "Anytime Goalscorer",
        "yes",
        "Over 60.5 Rushing Yards",
    ]
