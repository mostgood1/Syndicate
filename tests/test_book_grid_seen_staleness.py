"""Staleness reads when we last SAW a book, not when it last MOVED (lane published-negative-ev, 2026-10-06).

On a quiet pregame market one book ticking made every unmoved-but-current book "stale", so
`books_quoting` (fresh only) collapsed to 1-2 although 4+ books were captured. A price seen in the
latest snapshot is current whether or not it moved.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.shared import book_grid
from syndicate.features.shared.odds_book_quotes import quote_key

NOW = datetime(2026, 10, 6, 16, 0, tzinfo=timezone.utc)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _quote(book, side, price, moved_ago_min):
    return {"sport": "nfl", "kind": "game", "event_id": "evt-1", "segment": "full_game", "market": "h2h",
            "player_name": "", "selection": side, "line": None, "price": price, "bookmaker": book,
            "home_team": "A", "away_team": "B", "commence_time": _iso(NOW + timedelta(days=2)),
            "book_updated_at": _iso(NOW - timedelta(minutes=moved_ago_min)),
            "snapshot_ts": _iso(NOW - timedelta(minutes=moved_ago_min))}


def _rows():
    # draftkings moved 1 minute ago; fanduel has not moved for 2 hours but is in the latest snapshot.
    return [_quote("draftkings", "home", -110, 1), _quote("draftkings", "away", -110, 1),
            _quote("fanduel", "home", -105, 120), _quote("fanduel", "away", -115, 120)]


def _seen(rows, ago_min):
    return {quote_key(r): _iso(NOW - timedelta(minutes=ago_min)) for r in rows}


def _home_best(grid):
    [row] = [g for g in grid if g.get("market") == "h2h"]
    best = row.get("best") or row.get("best_price") or {}
    return best.get("home") if isinstance(best, dict) else None


@pytest.fixture(autouse=True)
def _clear(monkeypatch):
    monkeypatch.delenv(book_grid._STALE_BASIS_ENV, raising=False)


def test_reachability_a_seen_but_unmoved_book_counts_under_seen_and_not_under_moved(monkeypatch):
    rows = _rows()
    seen = _seen(rows, 2)
    new = _home_best(book_grid.build_book_grid(rows, now=NOW, last_seen=seen))
    monkeypatch.setenv(book_grid._STALE_BASIS_ENV, "moved")
    old = _home_best(book_grid.build_book_grid(rows, now=NOW, last_seen=seen))
    assert old["books_quoting"] == 1 and old["books_quoting_including_stale"] == 2
    assert new["books_quoting"] == 2
    # fanduel's -105 is the better home price and is current: it now wins
    assert new["bookmaker"] == "fanduel" and old["bookmaker"] == "draftkings"


def test_a_book_we_have_not_seen_for_hours_is_still_stale():
    rows = _rows()
    seen = {**_seen(rows[:2], 2), **_seen(rows[2:], 180)}
    best = _home_best(book_grid.build_book_grid(rows, now=NOW, last_seen=seen))
    assert best["books_quoting"] == 1 and best["bookmaker"] == "draftkings"


def test_unknown_seen_age_falls_back_to_the_movement_rule():
    best = _home_best(book_grid.build_book_grid(_rows(), now=NOW, last_seen=None))
    assert best["books_quoting"] == 1
