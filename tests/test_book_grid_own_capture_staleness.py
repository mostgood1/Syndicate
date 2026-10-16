"""A quote is current while it was in its BOOK'S own latest capture of the game (lane book-grid-own-capture-staleness).

User 2026-10-16 on the Martinez OVER 2.5 STRIKEOUTS card ("KALSHI · 1 BK"): "we also need to look into this saying
theres only one book pricing this" -- 10 books quoted it; the 15-min rule measured every sportsbook against Kalshi's
more frequent capture (findings_2026-10-16_one_book_staleness.md).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.shared import book_grid
from syndicate.features.shared.odds_book_quotes import quote_key

NOW = datetime(2026, 10, 16, 21, 21, tzinfo=timezone.utc)
SPORTSBOOKS = ("draftkings", "fanduel", "betmgm", "bovada", "betonlineag", "fanatics", "espnbet", "hardrockbet", "mybookieag")


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _q(book, side, price, *, line=2.5, market="strikeouts", moved_min=60, start_in_h=2.0, event="evt-k"):
    return {"sport": "mlb", "kind": "prop", "event_id": event, "segment": "full", "market": market,
            "player_name": "Nick Martinez", "selection": side, "line": line, "price": price, "bookmaker": book,
            "home_team": "Cleveland Guardians", "away_team": "Tampa Bay Rays",
            "commence_time": _iso(NOW + timedelta(hours=start_in_h)),
            "book_updated_at": _iso(NOW - timedelta(minutes=moved_min)),
            "snapshot_ts": _iso(NOW - timedelta(minutes=moved_min))}


def _martinez(start_in_h=2.0):
    rows = []
    for i, book in enumerate(SPORTSBOOKS):
        rows += [_q(book, "over", 110 + i, start_in_h=start_in_h), _q(book, "under", -145 - i, start_in_h=start_in_h)]
    rows += [_q("kalshi", "over", 150, moved_min=19, start_in_h=start_in_h),
             _q("kalshi", "under", -144, moved_min=29, start_in_h=start_in_h)]
    seen = {}
    for r in rows:
        seen[quote_key(r)] = _iso(NOW - timedelta(minutes=19 if r["bookmaker"] == "kalshi" else 52.8))
    return rows, seen


def _best(grid, side="over", line=2.5):
    [row] = [g for g in grid if g.get("market") == "strikeouts" and g.get("line") in (line, -line)]
    return row["best"][side], row


@pytest.fixture(autouse=True)
def _clear(monkeypatch):
    monkeypatch.delenv(book_grid._STALE_BASIS_ENV, raising=False)


def test_martinez_every_book_in_its_own_latest_capture_counts():
    rows, seen = _martinez()
    best, row = _best(book_grid.build_book_grid(rows, now=NOW, last_seen=seen))
    assert best["books_quoting"] == 10 and best["books_quoting_including_stale"] == 10
    assert best["bookmaker"] == "kalshi" and best["price"] == 150          # still the best price -- now against 10
    dk = row["cells"]["draftkings"]["over"]
    assert dk["stale"] is False and dk["seen_lag_behind_own_capture_seconds"] == 0.0
    assert dk["feed_lag_seconds"] == pytest.approx((52.8 - 19) * 60, abs=1)


def test_reachability_the_market_seen_rule_still_collapses_to_one_book(monkeypatch):
    rows, seen = _martinez()
    monkeypatch.setenv(book_grid._STALE_BASIS_ENV, "market_seen")
    best, _row = _best(book_grid.build_book_grid(rows, now=NOW, last_seen=seen))
    assert best["books_quoting"] == 1 and best["bookmaker"] == "kalshi"   # the 10-06 rule, measured on the card


def test_a_line_the_book_stopped_quoting_is_stale():
    # DraftKings' latest look at this game (5 min ago) carried 3.5, not 2.5: its 2.5 was last seen 3 hours ago.
    rows = [_q("draftkings", "over", 120), _q("draftkings", "under", -150), _q("fanduel", "over", 115),
            _q("fanduel", "under", -145), _q("draftkings", "over", 200, line=3.5), _q("draftkings", "under", -260, line=3.5)]
    seen = {quote_key(r): _iso(NOW - timedelta(minutes=5)) for r in rows}
    for r in rows[:2]:
        seen[quote_key(r)] = _iso(NOW - timedelta(hours=3))
    best, row = _best(book_grid.build_book_grid(rows, now=NOW, last_seen=seen))
    assert row["cells"]["draftkings"]["over"]["stale"] is True
    assert "no longer quoted" in row["cells"]["draftkings"]["over"]["reason"]
    assert best["books_quoting"] == 1 and best["bookmaker"] == "fanduel"


def test_a_feed_that_died_is_stale_pregame_after_two_hours():
    rows = [_q("draftkings", "over", 120), _q("draftkings", "under", -150), _q("fanduel", "over", 115),
            _q("fanduel", "under", -145)]
    seen = {quote_key(r): _iso(NOW - timedelta(minutes=2 if r["bookmaker"] == "draftkings" else 180)) for r in rows}
    best, row = _best(book_grid.build_book_grid(rows, now=NOW, last_seen=seen))
    assert row["cells"]["fanduel"]["over"]["stale"] is True and "whole feed" in row["cells"]["fanduel"]["over"]["reason"]
    assert best["books_quoting"] == 1
    seen = {quote_key(r): _iso(NOW - timedelta(minutes=2 if r["bookmaker"] == "draftkings" else 90)) for r in rows}
    best, _row = _best(book_grid.build_book_grid(rows, now=NOW, last_seen=seen))
    assert best["books_quoting"] == 2                                       # 88 min behind pregame: still current


def test_once_the_game_has_started_a_feed_ten_minutes_behind_is_stale():
    rows, seen = _martinez(start_in_h=-0.5)
    best, row = _best(book_grid.build_book_grid(rows, now=NOW, last_seen=seen))
    assert row["cells"]["draftkings"]["over"]["stale"] is True
    assert best["books_quoting"] == 1                                       # live: 34 min behind Kalshi is dead


def test_unknown_seen_age_still_falls_back_to_the_movement_rule():
    rows, _seen = _martinez()
    best, _row = _best(book_grid.build_book_grid(rows, now=NOW, last_seen=None))
    assert best["books_quoting"] == 1                                       # only Kalshi moved recently


def test_a_moved_start_time_reads_the_latest_one():
    # Measured 10-16: TB @ CLE quotes carried both 22:00Z and 00:00Z; the anchor's older copy made a 7 PM game
    # read as live at 5:32 PM and the 10-minute live feed limit marked every sportsbook stale.
    rows, seen = _martinez(start_in_h=1.5)
    for r in rows[:4]:
        r["commence_time"] = _iso(NOW - timedelta(minutes=30))     # an earlier start time on older quotes
    best, _row = _best(book_grid.build_book_grid(rows, now=NOW, last_seen=seen))
    assert best["books_quoting"] == 10
