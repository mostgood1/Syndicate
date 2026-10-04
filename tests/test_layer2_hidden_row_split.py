"""Rows hidden by the 1h quote-age gate, split (lane `layer2-hidden-row-split`, 2026-10-04).

Measured on the fleet's quote keys that day: 90% of NFL's 8,641 keys last seen > 1h
(90% of NHL's 84) were SUPERSEDED LINES -- the same book+side quoted fresh at another
number. `rows_beyond_quote_age` alone could not tell those from real staleness.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.shared.layer2_board import select_shortlist

_NOW = datetime(2026, 10, 4, 15, 0, tzinfo=timezone.utc)


def _row(*, sport="nhl", event="e1", market="totals", side="over", line=5.5, seen, player=None):
    return {
        "sport": sport, "kind": "game", "event_id": event, "market": market, "segment": "full",
        "side": side, "line": line, "player_name": player, "ev_pct": 1.0,
        "commence_time": (_NOW + timedelta(hours=3)).isoformat().replace("+00:00", "Z"),
        "quote": {"quote_seen_age_seconds": seen, "book_age_seconds": seen},
        "score": {"score": 1.0},
    }


@pytest.fixture(autouse=True)
def _no_overrides(monkeypatch):
    for key in list(__import__("os").environ):
        if key.startswith("SYNDICATE_SHORTLIST_MAX_QUOTE_AGE_SECONDS"):
            monkeypatch.delenv(key, raising=False)


def test_reachability_an_old_line_beside_a_fresh_one_is_superseded():
    out = select_shortlist([_row(line=5.5, seen=7200.0), _row(line=6.5, seen=600.0)], now=_NOW)
    assert out["rows_beyond_quote_age"] == 1
    assert out["rows_superseded_line"] == 1 and out["rows_stale_quote"] == 0
    assert out["rows_superseded_line_by_sport"] == {"nhl": 1} and out["rows_stale_quote_by_sport"] == {}


def test_a_hidden_row_with_no_fresh_line_is_a_stale_quote():
    out = select_shortlist([_row(line=5.5, seen=7200.0)], now=_NOW)
    assert out["rows_stale_quote"] == 1 and out["rows_superseded_line"] == 0
    assert out["rows_stale_quote_by_sport"] == {"nhl": 1}


def test_a_fresh_line_on_another_side_or_game_does_not_supersede():
    rows = [
        _row(side="over", line=5.5, seen=7200.0),
        _row(side="under", line=6.5, seen=600.0),          # other side
        _row(event="e2", side="over", line=6.5, seen=600.0),  # other game
        _row(market="spreads", side="over", line=6.5, seen=600.0),  # other market
    ]
    out = select_shortlist(rows, now=_NOW)
    assert out["rows_stale_quote"] == 1 and out["rows_superseded_line"] == 0


def test_props_group_by_player():
    rows = [
        _row(market="SOG", player="A Player", line=2.5, seen=7200.0),
        _row(market="SOG", player="B Player", line=3.5, seen=600.0),
        _row(market="SOG", player="C Player", line=1.5, seen=7200.0),
        _row(market="SOG", player="C Player", line=2.5, seen=600.0),
    ]
    out = select_shortlist(rows, now=_NOW)
    assert out["rows_stale_quote"] == 1 and out["rows_superseded_line"] == 1


def test_the_split_always_sums_to_the_total():
    rows = [_row(line=4.5 + i, seen=7200.0 if i % 2 else 300.0, event=f"e{i // 3}") for i in range(12)]
    out = select_shortlist(rows, now=_NOW)
    assert out["rows_superseded_line"] + out["rows_stale_quote"] == out["rows_beyond_quote_age"] > 0
