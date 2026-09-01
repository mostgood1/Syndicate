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
