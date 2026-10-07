"""A hidden line its own book withdrew is counted as withdrawn, not stale.

Lane `layer2-withdrawn-lines` (2026-10-07): soccer's ~300 and NCAAF's ~1,400 stale-quote rows
were mostly lines a book had stopped offering while it still priced the same event+market
fresh; the stale counter read those as capture failures.
"""
from __future__ import annotations

from datetime import datetime, timezone

from syndicate.features.shared.layer2_board import select_shortlist

_NOW = datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc)


def _row(player, *, book="fanduel", seen=600.0, market="player_shots", event="evt-1"):
    return {
        "sport": "soccer", "kind": "prop", "event_id": event, "market": market, "segment": "full",
        "player_name": player, "side": "over", "line": 1.5,
        "commence_time": "2026-10-10T14:00:00Z", "ev_pct": 1.0,
        "quote": {"price": 120, "bookmaker": book, "quote_seen_age_seconds": seen, "book_age_seconds": seen,
                  "fair_method": "consensus", "books_quoting": 1},
        "score": {"score": 1.0, "value_pct": 1.0},
    }


def test_a_line_the_book_dropped_is_withdrawn_when_it_still_prices_the_event():
    rows = [_row("Player A", seen=60_000.0), _row("Player B", seen=600.0)]
    result = select_shortlist(rows, now=_NOW)
    assert result["rows_withdrawn_line"] == 1
    assert result["rows_withdrawn_line_by_sport"] == {"soccer": 1}
    assert result["rows_stale_quote"] == 0


def test_off_is_not_on_the_book_quiet_on_the_event_is_still_stale():
    """Same stale row, but its book quotes nothing fresh on the event: a capture alarm."""
    rows = [_row("Player A", seen=60_000.0), _row("Player B", book="draftkings", seen=600.0)]
    result = select_shortlist(rows, now=_NOW)
    assert result["rows_withdrawn_line"] == 0
    assert result["rows_stale_quote"] == 1


def test_withdrawn_rows_are_still_hidden():
    rows = [_row("Player A", seen=60_000.0), _row("Player B", seen=600.0)]
    result = select_shortlist(rows, now=_NOW)
    assert {r["player_name"] for r in result["rows"]} == {"Player B"}
