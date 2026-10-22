"""A venue prop's same-book close comes from the quote log, even when history "has" the prop.

Lane `venue-prop-close-coverage`. Settled MLB prop orders on Kalshi / Polymarket
almost never got a same-book closing mark (fleet ledger 2026-10-19: kalshi 49 of
266, polymarket 1 of 95). Odds history keys a prop `player_name|market|selection`
-- no event, no book -- so it can only ever give `book_agnostic_close`, and on
2026-10-03 its Ozzie Albies series started two hours AFTER first pitch
(`no_pregame_observation`). The quote log held thirteen pregame Kalshi quotes
for that exact bet, and was never asked: the fallback fired only on
`no_market_in_history`.

Shapes are the production ones: the history point as the 2026-10-03 payload
carries it, the quote row as `odds_book_quotes` writes a `venue_direct` row.
"""

from __future__ import annotations

from datetime import datetime, timezone

from syndicate.features.shared.clv_join import BOOK_QUOTES_CLOSE_SOURCE, compute_clv_for_date

_DATE = "2026-10-03"
_OPEN_AT = datetime(2026, 10, 2, 12, 16, tzinfo=timezone.utc)
_KICKOFF = "2026-10-03T20:00:00Z"
_EVENT = "1632ced04d65127cf6172d3a2c2e2d16"
_NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
_HISTORY_KEY = "player_name=ozzie albies|market=batter_hits|selection=over"


def _opening(**over):
    row = {
        "sport": "mlb",
        "event_id": _EVENT,
        "home_team": "Los Angeles Dodgers",
        "away_team": "Atlanta Braves",
        "market": "batter_hits",
        "side": "over",
        "line": 0.5,
        "segment": "full",
        "player_name": "Ozzie Albies",
        "commence_time": _KICKOFF,
        "quote": {"price": -122, "bookmaker": "kalshi",
                  "book_prices": {"betonlineag": -130, "draftkings": -123, "kalshi": -122}},
    }
    quote = over.pop("quote", None)
    row.update(over)
    if quote is not None:
        row["quote"] = quote
    return row


def _quote(captured_at, price, **over):
    row = {
        "captured_at": captured_at,
        "snapshot_ts": captured_at,
        "sport": "mlb",
        "date": _DATE,
        "kind": "prop",
        "event_id": _EVENT,
        "commence_time": _KICKOFF,
        "bookmaker": "kalshi",
        "market": "batter_hits",
        "segment": "full",
        "selection": "over",
        "player_name": "Ozzie Albies",
        "line": 0.5,
        "price": price,
        "source": "venue_direct",
    }
    row.update(over)
    return row


def _point(captured_at, price):
    return {
        "captured_at": captured_at,
        "entity": "ozzie albies",
        "event_id": None,
        "line": {"line": 0.5, "price": f"{price:+d}"},
        "last_odds": float(price),
    }


def _history(*points):
    return {"markets": {_HISTORY_KEY: {"history": list(points), "closing_price": None,
                                       "closing_line": 0.5}}}


def _record(tmp_path, *rows):
    from syndicate.features.shared.clv_opening_ledger import record_openings

    record_openings(list(rows), date=_DATE, now=_OPEN_AT, root=tmp_path)


def _loader(rows_by_shard, calls=None):
    def load(sport, shard, event_ids):
        if calls is not None:
            calls.append((sport, shard, event_ids))
        if shard not in rows_by_shard:
            return None
        return [row for row in rows_by_shard[shard] if row.get("event_id") in event_ids]
    return load


def _report(tmp_path, history, rows_by_shard, calls=None):
    return compute_clv_for_date(
        _DATE, "mlb", root=tmp_path, history_payload=history,
        quote_rows=_loader(rows_by_shard, calls), now=_NOW,
    )


# The 2026-10-03 shape: every history point after first pitch.
_POST_KICKOFF_ONLY = _history(_point("2026-10-03T22:13:46+00:00", 310),
                              _point("2026-10-03T22:14:59+00:00", 320))
_KALSHI_PREGAME = [
    _quote("2026-10-02T17:53:03+00:00", -133),
    _quote("2026-10-03T13:59:04+00:00", -156),     # the close
    _quote("2026-10-03T20:40:00+00:00", +400),     # in play, never a close
    _quote("2026-10-03T15:40:11+00:00", -185, bookmaker="betonlineag"),
]


def test_a_venue_prop_history_refuses_gets_its_same_book_close_from_the_quote_log(tmp_path):
    """The reachability test, and the one that fails on the old behaviour:
    history `no_pregame_observation` used to be final for a prop."""
    _record(tmp_path, _opening())
    report = _report(tmp_path, _POST_KICKOFF_ONLY, {_DATE: _KALSHI_PREGAME})
    assert report["resolved"] == 1, report["unresolved_reasons"]
    row = report["rows"][0]
    assert row["close_source"] == BOOK_QUOTES_CLOSE_SOURCE
    assert row["close_book_scope"] == "same_book"
    assert row["close_bookmaker"] == "kalshi"
    assert row["close_price"] == -156.0
    assert report["same_book_n"] == 1
    assert report["book_quotes_fallback"]["replaced_history"] == {"refused": 1}


def test_a_book_agnostic_history_close_gives_way_to_a_same_book_one(tmp_path):
    """History resolves the prop, but without a book; the venue's own close wins."""
    _record(tmp_path, _opening())
    history = _history(_point("2026-10-03T19:30:00+00:00", -150))
    report = _report(tmp_path, history, {_DATE: _KALSHI_PREGAME})
    row = report["rows"][0]
    assert row["close_book_scope"] == "same_book", "was book_agnostic_close"
    assert row["close_bookmaker"] == "kalshi" and row["close_price"] == -156.0


def test_without_a_same_book_quote_the_book_agnostic_history_close_stands(tmp_path):
    """Another book's quote must not displace history: both are biased, and
    history's is the one the report already carried."""
    _record(tmp_path, _opening(quote={"price": -122, "bookmaker": "kalshi"}))
    history = _history(_point("2026-10-03T19:30:00+00:00", -150))
    report = _report(tmp_path, history, {_DATE: [
        _quote("2026-10-03T15:40:11+00:00", -185, bookmaker="betonlineag"),
    ]})
    row = report["rows"][0]
    assert row["close_source"] == "last_pregame_quote"
    assert row["close_book_scope"] == "book_agnostic_close"


def test_a_same_book_close_that_predates_the_opening_does_not_cost_history_its_close(tmp_path):
    """Kalshi's last CHANGE was before we opened, and with no sidecar it cannot be
    confirmed -- downstream that is `quotes_unchanged_since_open`. History keeps it."""
    _record(tmp_path, _opening())
    history = _history(_point("2026-10-03T19:30:00+00:00", -150))
    report = _report(tmp_path, history, {_DATE: [_quote("2026-10-02T09:00:00+00:00", -120)]})
    assert report["resolved"] == 1
    assert report["rows"][0]["close_book_scope"] == "book_agnostic_close"


def test_when_neither_source_has_a_close_history_keeps_its_diagnosis(tmp_path):
    _record(tmp_path, _opening())
    report = _report(tmp_path, _POST_KICKOFF_ONLY, {_DATE: []})
    assert report["resolved"] == 0
    assert report["unresolved_reasons"] == {"no_pregame_observation": 1}


def test_a_polymarket_prop_whose_line_history_disagrees_with_resolves_same_book(tmp_path):
    """`line_mismatch` was 19 kalshi / 6 polymarket rows: the bookless series
    tracks whichever line the feed last carried, not ours."""
    _record(tmp_path, _opening(quote={"price": -115, "bookmaker": "polymarket"}))
    history = {"markets": {_HISTORY_KEY: {"history": [{
        "captured_at": "2026-10-03T19:30:00+00:00", "entity": "ozzie albies",
        "line": {"line": 1.5, "price": "+250"}, "last_odds": 250.0,
    }], "closing_price": None}}}
    report = _report(tmp_path, history, {_DATE: [
        _quote("2026-10-03T19:10:00+00:00", -140, bookmaker="polymarket"),
    ]})
    row = report["rows"][0]
    assert row["close_book_scope"] == "same_book" and row["close_bookmaker"] == "polymarket"


def test_an_in_play_prop_is_not_asked_of_the_quote_log(tmp_path):
    late_open = datetime(2026, 10, 3, 20, 30, tzinfo=timezone.utc)
    from syndicate.features.shared.clv_opening_ledger import record_openings

    record_openings([_opening()], date=_DATE, now=late_open, root=tmp_path)
    calls: list = []
    report = _report(tmp_path, _POST_KICKOFF_ONLY, {_DATE: _KALSHI_PREGAME}, calls)
    assert report["unresolved_reasons"] == {"opened_in_play": 1}
    assert calls == []


def test_a_game_market_history_resolves_still_never_reads_the_log(tmp_path):
    """The widening is for props only: a game market history places keeps B3's
    byte-for-byte guarantee."""
    _record(tmp_path, _opening(market="h2h", side="home", line=None, player_name=None,
                               quote={"price": -120, "bookmaker": "betmgm"}))
    key = (f"event_id={_EVENT}|home_team=Los Angeles Dodgers|away_team=Atlanta Braves"
           "|market=h2h|bookmaker=betmgm")
    history = {"markets": {key: {"history": [{
        "captured_at": "2026-10-03T19:00:00+00:00", "entity": "Los Angeles Dodgers",
        "last_odds": -150.0, "line": {"home_odds": "-150", "away_odds": "+125"},
    }], "closing_price": None, "closing_line": None}}}
    calls: list = []
    report = _report(tmp_path, history, {_DATE: []}, calls)
    assert report["rows"][0]["close_source"] == "last_pregame_quote"
    assert calls == []


# --------------------------------------------------------------------------
# Game markets at a book history does not track. History pairs OUR DraftKings
# price with DraftKings' close -- same-book for the opening, but the order
# filled at the venue, so the venue's own close outranks it.
# --------------------------------------------------------------------------

_DK_KEY = (f"event_id={_EVENT}|home_team=Los Angeles Dodgers|away_team=Atlanta Braves"
           "|market=h2h|bookmaker=draftkings")
_DK_HISTORY = {"markets": {_DK_KEY: {"history": [{
    "captured_at": "2026-10-03T19:00:00+00:00", "entity": "Los Angeles Dodgers",
    "last_odds": -150.0, "line": {"home_odds": "-150", "away_odds": "+125"},
}], "closing_price": None, "closing_line": None}}}


def _game_opening(**over):
    fields = {"market": "h2h", "side": "home", "line": None, "player_name": None,
              "quote": {"price": -140, "bookmaker": "kalshi",
                        "book_prices": {"draftkings": -145, "kalshi": -140}}}
    fields.update(over)
    return _opening(**fields)


def _game_quote(captured_at, price, **over):
    return _quote(captured_at, price, kind="game", market="h2h", selection="home",
                  player_name=None, line=None, **over)


def test_a_venue_game_market_takes_its_own_books_close_over_a_priced_other_book(tmp_path):
    _record(tmp_path, _game_opening())
    report = _report(tmp_path, _DK_HISTORY, {_DATE: [_game_quote("2026-10-03T19:20:00+00:00", -155)]})
    row = report["rows"][0]
    assert row["close_bookmaker"] == "kalshi", "was DraftKings' close via book_prices"
    assert row["matched_bookmaker"] == "kalshi" and row["close_price"] == -155.0
    assert row["open_price"] == -140, "our own price, not the DraftKings override"
    assert report["book_quotes_fallback"]["replaced_history"] == {"same_book_other_book": 1}


def test_without_the_venues_own_close_the_priced_other_book_pair_stands(tmp_path):
    _record(tmp_path, _game_opening())
    report = _report(tmp_path, _DK_HISTORY, {_DATE: [
        _game_quote("2026-10-03T19:20:00+00:00", -160, bookmaker="fanduel"),
    ]})
    row = report["rows"][0]
    assert row["close_source"] == "last_pregame_quote"
    assert row["matched_bookmaker"] == "draftkings" and row["close_book_scope"] == "same_book"


def test_a_different_book_history_close_gives_way_to_the_venues_own(tmp_path):
    _record(tmp_path, _game_opening(quote={"price": -140, "bookmaker": "kalshi"}))
    report = _report(tmp_path, _DK_HISTORY, {_DATE: [_game_quote("2026-10-03T19:20:00+00:00", -155)]})
    row = report["rows"][0]
    assert row["close_book_scope"] == "same_book", "was different_book_close"
    assert row["close_bookmaker"] == "kalshi"


def test_an_equal_rank_quote_close_never_displaces_history(tmp_path):
    """Both sources offer the DraftKings pair; history's is the one the report
    already carried, and a tie must not churn it."""
    _record(tmp_path, _game_opening())
    report = _report(tmp_path, _DK_HISTORY, {_DATE: [
        _game_quote("2026-10-03T19:20:00+00:00", -170, bookmaker="draftkings"),
    ]})
    row = report["rows"][0]
    assert row["close_source"] == "last_pregame_quote" and row["close_price"] == -150.0
    assert report["book_quotes_fallback"]["replaced_history"] == {}
