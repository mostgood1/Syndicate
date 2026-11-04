"""The stored Kalshi markets state omits derivable fields and every read restores them.

Lane `kalshi-state-cap`, 2026-11-04. The state had reached 8,386,958 bytes
against the 8,388,608-byte keyvalue cap, and live-odds-worker's writes were
REJECTED from 20:40:56Z. Six of the fourteen lean fields are derived from the
ticker and the asks, and they were 2.93 MB of it. These tests hold the one
property that makes dropping them safe: what readers see does not change.
"""
from __future__ import annotations

import json

import pytest

from pipeline import kalshi_odds_refresh as kor
from syndicate.features.shared.kalshi_client import normalize_market


def _raw(ticker, yes="0.5400", no="0.4800", **extra):
    row = {
        "ticker": ticker,
        "event_ticker": ticker.rsplit("-", 1)[0] if "-" in ticker else None,
        "title": "Campbell at NC State: Total Points",
        "yes_sub_title": "Over 129.5 points scored",
        "no_sub_title": "Over 129.5 points scored",
        "status": "active",
        "yes_ask_dollars": yes,
        "no_ask_dollars": no,
        "close_time": "2026-11-05T02:00:00Z",
    }
    row.update(extra)
    return row


# Shapes read off the fleet's stored state 2026-11-04 22:36Z: a game line, a
# player prop with a four-part ticker, a one-sided book, an empty book, and a
# ticker with no dash at all.
_RAWS = [
    _raw("KXNCAAWBTOTAL-26NOV04CAMPNCST-129"),
    _raw("KXNBAPTS-26NOV04LALBOS-LALLJAMES23-25", yes="0.3100", no="0.7200"),
    _raw("KXNBAGAME-26NOV04LALBOS-BOS", yes="0.9900", no=None),
    _raw("KXNHLGAME-26NOV04WPGSTL-WPG", yes=None, no=None),
    _raw("NODASHTICKER"),
]


def _lean(raw):
    return kor._lean_market(normalize_market(raw))


@pytest.mark.parametrize("raw", _RAWS, ids=[r["ticker"] for r in _RAWS])
def test_a_compacted_row_reads_back_identical(raw):
    lean = _lean(raw)

    assert kor._expand_market(kor._compact_market(lean)) == lean


def test_compaction_drops_every_derivable_field_of_a_normal_row():
    compact = kor._compact_market(_lean(_RAWS[0]))

    assert not set(kor._DERIVED_LEAN_FIELDS) & set(compact), compact
    assert compact["ticker"] == "KXNCAAWBTOTAL-26NOV04CAMPNCST-129"
    assert compact["yes_ask_dollars"] == "0.5400"


def test_compaction_is_what_shrinks_the_payload():
    """off != on, in bytes: the lean row alone is the size that was rejected."""
    lean = [_lean(r) for r in _RAWS[:3]]
    compact = [kor._compact_market(row) for row in lean]

    lean_bytes = len(json.dumps(lean, separators=(",", ":")))
    compact_bytes = len(json.dumps(compact, separators=(",", ":")))

    assert compact_bytes < 0.75 * lean_bytes, (compact_bytes, lean_bytes)


def test_a_field_the_derivation_would_not_reproduce_is_kept():
    """The venue's own event ticker is stored when it is not the ticker's prefix."""
    lean = _lean(_raw("KXNBAPTS-26NOV04LALBOS-LALLJAMES23-25",
                      event_ticker="KXNBAPTS-26NOV04LALBOS"))

    compact = kor._compact_market(lean)

    assert compact["event_ticker"] == "KXNBAPTS-26NOV04LALBOS"
    assert kor._expand_market(compact) == lean


def test_markets_from_state_restores_what_every_reader_reads():
    lean = [_lean(r) for r in _RAWS]
    state = {"series": {"MIXED": {"markets": [kor._compact_market(row) for row in lean]}}}

    assert kor.markets_from_state(state) == lean


def test_a_full_row_written_by_older_code_still_reads():
    lean = [_lean(r) for r in _RAWS]

    assert kor.markets_from_state({"series": {"MIXED": {"markets": lean}}}) == lean


def test_a_compacted_row_re_leaned_by_older_code_heals_on_read():
    """A worker still on the full-row code re-leans a compacted row into Nones
    for the dropped fields; the next read restores them rather than serving None."""
    lean = _lean(_RAWS[0])
    re_leaned = kor._lean_market(kor._compact_market(lean))

    assert re_leaned["yes_american"] is None and re_leaned["series"] is None
    assert kor._expand_market(re_leaned) == lean


def test_the_refresh_reads_stored_rows_back_in_full():
    """The rotation carries unfetched series forward from the stored state; those
    rows must reach the working set (and the daily book) with every field."""
    lean = _lean(_RAWS[0])
    per_series = {"KXNCAAWBTOTAL": {"markets": [kor._compact_market(lean)], "fetched_at": "x"}}

    kor._expand_stored_series(per_series)

    assert per_series["KXNCAAWBTOTAL"]["markets"] == [lean]
