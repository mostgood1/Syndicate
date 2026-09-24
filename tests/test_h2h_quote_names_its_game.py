"""A moneyline quote must NAME its fixture, even though its key stays bare.

WHY. `venue_quote_fanin` has two guards that need `Quote.game`:

    _quote_is_for_another_game        refuse a quote that names a DIFFERENT game
    _unconfirmed_on_a_contested_key   on a contested key, require BOTH names

Both adapters resolved the fixture ONLY for `_ROLE_KEYED_MARKETS`
(totals/spreads), because only those want it inside the key. The same `None`
then landed on `Quote.game`, so an h2h quote could not name its fixture at all
-- and `polymarket_us_outcome`'s own comment already claimed the opposite:
"`game` is still carried so the fan-in can reject a bare-key match that lands
on the wrong fixture."

The premise for excluding h2h -- "its side IS the club, so it cannot collide
across fixtures" -- holds within one date and fails on the grid, which spans
more than today (served board 2026-09-23: mlb `available` 1846 against
`available_today` 1097), and fails on a doubleheader within one date.

SAFETY, NOT COVERAGE. The key is byte-identical to what both adapters
published before, so no match that works today is lost. What changes is that a
club-keyed quote landing on the WRONG fixture can now be refused. The
`AMBIGUOUS_UNNAMED_REJECTED 0 -> 164` reading first offered as evidence for
this does NOT support it and is retracted: it pre-dates the deploy it was
attributed to by 15 minutes, with no deploy on either worker in the window.
"""

from __future__ import annotations

import time

import pytest

from syndicate.features.shared import venue_quote_adapters as adapters
from syndicate.features.shared.venue_quote_adapters import quote_key
from syndicate.features.shared.venue_quote_fanin import Quote, apply_venue_quotes_to_grid


# ---------------------------------------------------------------------------
# KALSHI
# ---------------------------------------------------------------------------

_TB_NYY = [{"event_id": "evt-tb-nyy",
            "home_team": "New York Yankees",
            "away_team": "Tampa Bay Rays"}]


def _kalshi_moneyline_payload():
    """A real `KXMLBGAME` shape: the series is the full-game moneyline and the
    title grammar is `_MONEYLINE` -- "<team> wins?"."""
    return {
        "fetched_at": "2026-09-23T23:15:00Z",
        "series": {"KXMLBGAME": {"markets": [{
            "ticker": "KXMLBGAME-26SEP231905TBNYY-NYY",
            "series": "KXMLBGAME",
            "title": "New York Yankees wins?",
            "yes_ask_dollars": 0.62,
            "no_ask_dollars": 0.41,
        }]}},
    }


def test_a_kalshi_moneyline_NAMES_its_game_while_its_key_stays_bare(monkeypatch):
    """off != on for the identity, and the key is unchanged in BOTH arms.

    Asserting only that the game appears would pass just as happily if the
    qualifier had been made unconditional -- which would change the key and
    break every board lookup. Both halves are asserted.
    """
    monkeypatch.setattr(adapters, "_artifact", lambda parts: (_kalshi_moneyline_payload(), time.time()))

    off = adapters.kalshi_outcome("mlb", "2026-09-23").quotes
    on = adapters.kalshi_outcome("mlb", "2026-09-23", games=_TB_NYY).quotes

    assert off, "the adapter produced no quotes at all -- fixture is wrong, not the code"
    assert len(on) == len(off) == 1

    # THE IDENTITY: absent without a schedule to resolve against, present with one.
    assert off[0].game is None
    assert on[0].game == "new york yankees+tampa bay rays"

    # THE KEY: bare, and identical in both arms. This is what the board asks for.
    assert off[0].key == "mlb|h2h|new york yankees"
    assert on[0].key == "mlb|h2h|new york yankees"
    assert "|@" not in on[0].key, f"h2h key gained a fixture qualifier: {on[0].key}"


def test_a_kalshi_TOTAL_still_carries_its_game_INSIDE_the_key(monkeypatch):
    """The role-keyed families are untouched -- they qualify, as before."""
    payload = {
        "fetched_at": "2026-08-25T20:15:00Z",
        "series": {"KXMLBTOTAL": {"markets": [{
            "ticker": "KXMLBTOTAL-26AUG251840BOSMIA-7",
            "series": "KXMLBTOTAL",
            "title": "Over 7.5 runs scored?",
            "yes_ask_dollars": 0.54,
            "no_ask_dollars": 0.48,
        }]}},
    }
    monkeypatch.setattr(adapters, "_artifact", lambda parts: (payload, time.time()))
    games = [{"event_id": "e", "home_team": "Miami Marlins", "away_team": "Boston Red Sox"}]
    on = adapters.kalshi_outcome("mlb", "2026-08-25", games=games).quotes

    assert on, "fixture produced no totals quotes"
    assert all("|@boston red sox+miami marlins" in q.key for q in on), [q.key for q in on]
    assert {q.game for q in on} == {"boston red sox+miami marlins"}


# ---------------------------------------------------------------------------
# POLYMARKET -- the same defect, the same fix
# ---------------------------------------------------------------------------


def _pm_slate(*markets):
    return {"fetched_at": "2026-08-24T18:00:00Z", "markets": list(markets)}


def _pm_moneyline(slug, outcomes, prices=("0.55", "0.45")):
    return {"slug": slug, "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_MONEYLINE",
            "outcomes": str(list(outcomes)).replace("'", '"'),
            "outcomePrices": str(list(prices)).replace("'", '"')}


def test_a_polymarket_moneyline_NAMES_its_game_while_its_key_stays_bare(monkeypatch):
    payload = _pm_slate(_pm_moneyline("aec-mlb-chc-ari-2026-08-24",
                                      ["Chicago Cubs", "Arizona Diamondbacks"]))
    monkeypatch.setattr(adapters, "_artifact", lambda _p: (payload, time.time()))

    quotes = adapters.polymarket_us_outcome("mlb", "2026-08-24").quotes
    assert quotes, "fixture produced no polymarket quotes"

    # Keys stay bare -- the club IS the side, and that is what the board asks.
    assert all("|@" not in q.key for q in quotes), [q.key for q in quotes]
    assert {q.key for q in quotes} == {
        "mlb|h2h|chicago cubs",
        "mlb|h2h|arizona diamondbacks",
    }
    # ...and every one of them now names the fixture it belongs to.
    assert all(q.game for q in quotes), [(q.key, q.game) for q in quotes]
    assert len({q.game for q in quotes}) == 1


# ---------------------------------------------------------------------------
# THE POINT OF ALL OF IT: a club-keyed quote can no longer price the wrong game
# ---------------------------------------------------------------------------


def _grid_row(home, away, event_id, *, book_age=206.0):
    return {
        "sport": "mlb", "market": "h2h", "line": None, "sides": ["home"],
        "home_team": home, "away_team": away, "event_id": event_id,
        "game": {"state": "live"},
        "best": {"home": {"price": -110, "bookmaker": "draftkings", "age_seconds": book_age}},
    }


def _club_quote(game, *, american=-122, age=23.0):
    return Quote(
        key=str(quote_key("mlb", "h2h", "new york yankees", None)),
        source="kalshi", sport="mlb", market="h2h", side="new york yankees",
        probability=0.55, american=american, line=None,
        fetched_at=time.time() - age, venue_ref="KXMLBGAME-x", game=game,
    )


def test_a_named_club_quote_prices_ITS_game_and_not_the_other_one():
    """The Yankees play both rows; only one is the fixture the quote names.

    Before the fix `game` was None here, `_quote_is_for_another_game` could not
    prove a mismatch, and the SAME quote priced both rows.
    """
    tonight = _grid_row("New York Yankees", "Tampa Bay Rays", "evt-tb-nyy")
    tomorrow = _grid_row("New York Yankees", "Boston Red Sox", "evt-bos-nyy")
    quote = _club_quote("new york yankees+tampa bay rays")

    result = apply_venue_quotes_to_grid(
        [tonight, tomorrow], "mlb", "2026-09-23",
        collected={"quotes": {quote.key: quote}, "by_source": {}},
    )

    assert result["repriced"] == 1, result
    assert tonight["best"]["home"]["price_source"] == "kalshi"
    assert tonight["best"]["home"]["age_seconds"] == pytest.approx(23.0, abs=3.0)
    # The other fixture keeps its own book price and its own age.
    assert "price_source" not in tomorrow["best"]["home"]
    assert tomorrow["best"]["home"]["price"] == -110
    assert tomorrow["best"]["home"]["age_seconds"] == pytest.approx(206.0)


def test_an_UNNAMED_club_quote_still_prices_both_which_is_what_the_fix_removes():
    """The pre-fix behaviour, pinned so the regression is visible if it returns.

    `game=None` is the shape both adapters produced for every h2h quote. It
    cannot be refused by `_quote_is_for_another_game` -- that guard is
    deliberately incapable of removing a match it cannot prove wrong -- so one
    Kalshi contract prices two different fixtures.
    """
    tonight = _grid_row("New York Yankees", "Tampa Bay Rays", "evt-tb-nyy")
    tomorrow = _grid_row("New York Yankees", "Boston Red Sox", "evt-bos-nyy")

    result = apply_venue_quotes_to_grid(
        [tonight, tomorrow], "mlb", "2026-09-23",
        collected={"quotes": {_club_quote(None).key: _club_quote(None)}, "by_source": {}},
    )

    assert result["repriced"] == 2, (
        "an unnamed club quote no longer reaches both fixtures -- if this is "
        "now 1, something else started refusing it and this test's premise "
        "needs re-deriving rather than the assertion being flipped"
    )
