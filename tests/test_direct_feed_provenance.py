"""A directly-observed venue price reaches the grid; the aggregator's copy does not.

THE RULE IS "ONE PRICE SOURCE PER VENUE", NOT "NO EXCHANGES". The 2026-08-25
user decision dropped kalshi/polymarket rows by NAME, which was correct while the
shard carried only OddsAPI's copy of them.

Measured 2026-09-01 that stopped being true: a second lane began writing Kalshi's
OWN prices into `book_quotes`, and a row carries no provenance -- the schema is
away_team, book_updated_at, bookmaker, captured_at, commence_time, date,
event_id, home_team, kind, line, market, player_name, price, segment, selection,
snapshot_ts, sport, where `kind` is game/prop. So the name-only rule discarded the
direct price too, and Layer 1 / the book-grid saw no exchange at all.
"""
from __future__ import annotations

import pytest

from syndicate.features.shared.book_shortlist import (
    QUOTE_SOURCE_FIELD,
    QUOTE_SOURCE_VENUE_DIRECT,
    drop_from_grid,
    is_direct_feed_book,
    is_venue_direct_row,
)


# --------------------------------------------------------------- reachability
@pytest.mark.parametrize("book", ["kalshi", "polymarket", "Kalshi", " POLYMARKET "])
def test_an_untagged_exchange_row_is_still_dropped(book):
    """TODAY'S BEHAVIOUR, unchanged. Every existing writer emits untagged rows,
    so this is what guarantees the change is additive rather than a policy shift."""
    assert drop_from_grid({"bookmaker": book}) is True


def test_the_old_rule_would_have_dropped_the_direct_row_too():
    """The defect being fixed: name alone cannot tell the two sources apart."""
    direct = {"bookmaker": "kalshi", QUOTE_SOURCE_FIELD: QUOTE_SOURCE_VENUE_DIRECT}
    assert is_direct_feed_book(direct["bookmaker"]) is True, "the old rule drops this"
    assert drop_from_grid(direct) is False, "the new rule keeps it"


# ------------------------------------------------------------------ behaviour
@pytest.mark.parametrize("book", ["kalshi", "polymarket"])
def test_a_venue_direct_row_survives(book):
    assert drop_from_grid({"bookmaker": book, QUOTE_SOURCE_FIELD: QUOTE_SOURCE_VENUE_DIRECT}) is False


@pytest.mark.parametrize("book", ["fanduel", "draftkings", "novig", "prophetx", ""])
def test_non_direct_feed_books_are_never_dropped(book):
    """novig and prophetx come THROUGH the aggregator and must be unaffected."""
    assert drop_from_grid({"bookmaker": book}) is False
    assert drop_from_grid({"bookmaker": book, QUOTE_SOURCE_FIELD: QUOTE_SOURCE_VENUE_DIRECT}) is False


def test_absent_provenance_is_not_venue_direct():
    """Unknown must not default to the permissive branch."""
    for row in ({}, {"bookmaker": "kalshi"}, {QUOTE_SOURCE_FIELD: None},
                {QUOTE_SOURCE_FIELD: ""}, {QUOTE_SOURCE_FIELD: "oddsapi"}):
        assert is_venue_direct_row(row) is False


def test_a_malformed_row_does_not_raise():
    for row in (None, "kalshi", 7, []):
        assert drop_from_grid(row) is False


# -------------------------------------------------------------------- wiring
def test_the_grid_keeps_a_direct_row_and_counts_both_sides(capsys):
    """End to end through the real grid builder, and the counters must be a RATE."""
    from syndicate.features.shared import book_grid

    common = {
        "sport": "wnba", "date": "2026-09-18", "kind": "game",
        "event_id": "e1", "home_team": "Atlanta Dream", "away_team": "Minnesota Lynx",
        "market": "h2h", "segment": "full", "selection": "home",
        "commence_time": "2026-09-18T23:00:00Z",
        "snapshot_ts": "2026-09-18T22:00:00Z", "book_updated_at": "2026-09-18T22:00:00Z",
    }
    rows = [
        {**common, "bookmaker": "fanduel", "price": 118},
        {**common, "bookmaker": "kalshi", "price": 120},                       # aggregator copy
        {**common, "bookmaker": "kalshi", "price": 124,
         QUOTE_SOURCE_FIELD: QUOTE_SOURCE_VENUE_DIRECT},                       # the venue itself
    ]
    kept = book_grid.freshest_rows_for_grid(rows)
    books = {str(r.get("bookmaker") or "").lower() for r in kept}
    assert "kalshi" in books, "the directly-observed price must reach the grid"
    assert "fanduel" in books
    out = capsys.readouterr().out
    assert "AGGREGATOR_DUPLICATE_DROPPED" in out
    assert "kept_direct=1" in out, "kept must print beside dropped, or the pair is not a rate"


# ------------------------------------------------------- the writing side
def test_the_kalshi_capture_stamps_provenance(tmp_path, monkeypatch):
    """END TO END: capture -> shard -> grid. The only assertion that proves it.

    Each half passes on its own while the chain stays broken -- the capture
    appends rows (true), and the grid keeps stamped rows (true), and the board
    still shows nothing because nobody stamped. So this asserts on what reaches
    the GRID, not on either half in isolation.
    """
    from syndicate.features.shared import book_grid, odds_book_quotes
    from pipeline import kalshi_odds_refresh

    appended: dict = {}

    def _fake_append(*, sport, date_str, rows, captured_at, publish=True, extra=None):
        appended["rows"] = [dict(r, **(extra or {})) for r in rows]
        appended["extra"] = extra
        return {"appended": len(rows)}

    monkeypatch.setattr(odds_book_quotes, "append_book_quotes", _fake_append)
    monkeypatch.setattr(
        odds_book_quotes, "quote_rows_from_kalshi_matches",
        lambda matches: [{
            "sport": "wnba", "date": "2026-09-18", "kind": "game", "event_id": "e1",
            "home_team": "Atlanta Dream", "away_team": "Minnesota Lynx",
            "market": "h2h", "segment": "full", "selection": "home",
            "commence_time": "2026-09-18T23:00:00Z",
            "snapshot_ts": "2026-09-18T22:00:00Z",
            "book_updated_at": "2026-09-18T22:00:00Z",
            "bookmaker": "kalshi", "price": 124,
        }],
    )

    kalshi_odds_refresh._capture_kalshi_quotes(
        report={"matches": [{"board_event_id": "e1"}]},
        board_rows=[{"event_id": "e1", "sport": "wnba"}],
        selected_date="2026-09-18",
    )

    assert appended.get("extra") == {QUOTE_SOURCE_FIELD: QUOTE_SOURCE_VENUE_DIRECT}, (
        "the capture must stamp provenance, or the grid discards its rows"
    )
    # and the stamped row must actually survive the grid
    kept = book_grid.freshest_rows_for_grid(appended["rows"])
    assert any(str(r.get("bookmaker") or "").lower() == "kalshi" for r in kept), (
        "a stamped, directly-observed Kalshi price must reach the grid"
    )


# ------------------------------------------------------- polymarket, same bound
def test_polymarket_builder_is_props_only():
    """A GAME market must be refused: `_KEY_FIELDS` has no source field, so a
    direct row and OddsAPI's copy share a dedup key and ALTERNATE rather than
    merge -- every alternation reads as a price change that never happened.

    Measured: mlb 2026-08-31 has 2,350 polymarket GAME rows and 0 prop; soccer
    2026-08-31 and wnba 2026-08-30 have zero exchange rows of any kind. So props
    have nothing to collide with, and game markets have plenty.
    """
    from syndicate.features.shared.odds_book_quotes import quote_rows_from_polymarket_matches

    game = {"event_id": "e1", "market": "h2h", "side": "home", "line": None,
            "player_name": None, "polymarket_american": 124, "polymarket_slug": "s"}
    assert quote_rows_from_polymarket_matches([game]) == []


def test_polymarket_builder_emits_a_prop_row():
    from syndicate.features.shared.odds_book_quotes import quote_rows_from_polymarket_matches

    prop = {"event_id": "e1", "market": "player_points", "side": "over", "line": 18.5,
            "player_name": "A Player", "polymarket_american": -115, "polymarket_slug": "sl"}
    rows = quote_rows_from_polymarket_matches([prop])
    assert len(rows) == 1
    row = rows[0]
    assert row["bookmaker"] == "polymarket" and row["kind"] == "prop"
    assert row["price"] == -115 and row["line"] == 18.5
    assert row["selection"] == "over" and row["player_name"] == "A Player"
    assert row["venue_ticker"] == "sl", "traceable back to the market that quoted it"


def test_polymarket_builder_skips_rows_with_no_price():
    """A quote with no price records nothing; defaulting one invents a number."""
    from syndicate.features.shared.odds_book_quotes import quote_rows_from_polymarket_matches

    assert quote_rows_from_polymarket_matches([
        {"event_id": "e1", "market": "player_points", "player_name": "P",
         "polymarket_american": None},
        {"event_id": "e1", "market": "", "player_name": "P", "polymarket_american": -110},
        None, "junk",
    ]) == []


def test_the_source_stamp_is_NOT_in_the_dedup_key():
    """The bound above is load-bearing precisely because of this.

    The provenance stamp travels in `extra`, which puts it on the ROW, not in
    the KEY. Relaxing the props bound to a source check is only safe once
    `source` is in `_KEY_FIELDS` -- which it is not.
    """
    from syndicate.features.shared.odds_book_quotes import _KEY_FIELDS
    from syndicate.features.shared.book_shortlist import QUOTE_SOURCE_FIELD

    assert QUOTE_SOURCE_FIELD not in _KEY_FIELDS
