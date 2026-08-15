"""`#435` -- the lookup path holds latest-per-key, not a whole day of observations.

THE DEFECT, measured in production rather than reasoned from source. The shard
`book_quotes/<date>.jsonl` gains a row per quote OBSERVATION and grows all day.
From `CACHE_EVICT` records, MLB 2026-08-14:

    89.9 -> 108.8 -> 133.2 -> 165.2 -> 184.5 MB, then 2.2 MB the next morning

A read costs 6.3x file bytes resident, so the end-of-day shard is ~1,162MB for
ONE cache entry against a 500MB budget -- and `_evict_book_quotes_over_budget`
is `while len > 1`, so when it is the only entry it can never be evicted. Kills
clustered in the evening and STOPPED at 05:02:59Z when the date rolled over:
a daily ramp, not a leak.

On the 207MB 2026-08-09 shard, 478,782 rows collapse to 36,424 distinct quote
keys -- a 13.1x shrink, i.e. 92.4% of the file is superseded.

THE SAFETY ARGUMENT IS A MEASUREMENT, NOT A CLAIM. `build_book_grid` already
keeps only the freshest row per key (`book_grid.py:156`, `:225`), and its reduce
key equals `_KEY_FIELDS`. So the grid cannot tell the two inputs apart -- pinned
below on synthetic rows, and separately verified byte-for-byte against the real
207MB shard.
"""

from __future__ import annotations

import json

import pytest

from syndicate.features.shared import odds_book_quotes
from syndicate.features.shared.book_grid import build_book_grid


@pytest.fixture(autouse=True)
def _clear_caches():
    odds_book_quotes._BOOK_QUOTES_CACHE.clear()
    odds_book_quotes._BOOK_QUOTES_LATEST_CACHE.clear()
    yield
    odds_book_quotes._BOOK_QUOTES_CACHE.clear()
    odds_book_quotes._BOOK_QUOTES_LATEST_CACHE.clear()


def _quote(**over):
    row = {
        "sport": "mlb",
        "kind": "game",
        "event_id": "e1",
        "bookmaker": "draftkings",
        "segment": "full_game",
        "market": "h2h",
        "selection": "home",
        "player_name": "",
        "line": "",
        "price": -110,
        "commence_time": "2026-08-09T23:00:00Z",
        "snapshot_ts": "2026-08-09T12:00:00Z",
        "captured_at": "2026-08-09T12:00:00Z",
        "home_team": "Baltimore Orioles",
        "away_team": "Los Angeles Angels",
    }
    row.update(over)
    return row


def _write_shard(tmp_path, rows, name="shard.jsonl"):
    path = tmp_path / name
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def _point_at(monkeypatch, path):
    monkeypatch.setattr(odds_book_quotes, "book_quotes_path", lambda sport, date_str: path)


def test_keeps_only_the_freshest_observation_of_each_key():
    rows = [
        _quote(price=-110, snapshot_ts="2026-08-09T12:00:00Z"),
        _quote(price=-120, snapshot_ts="2026-08-09T14:00:00Z"),  # same key, later
        _quote(price=+100, snapshot_ts="2026-08-09T13:00:00Z"),  # same key, middle
    ]
    reduced = odds_book_quotes.reduce_to_latest_per_key(rows)
    assert len(reduced) == 1
    assert reduced[0]["price"] == -120


def test_distinct_keys_all_survive():
    # The reduce must not collapse different books, lines, or selections --
    # those are the price shopping the board exists to do.
    rows = [
        _quote(bookmaker="draftkings"),
        _quote(bookmaker="fanduel"),
        _quote(selection="away"),
        _quote(line="1.5"),
        _quote(market="spreads"),
    ]
    assert len(odds_book_quotes.reduce_to_latest_per_key(rows)) == 5


def test_book_updated_at_wins_over_snapshot_ts():
    # `book_grid._observed_at` prefers `book_updated_at`; `closing_quotes` does
    # NOT. Using the wrong precedence picks a different row than the grid would
    # -- silently, and only for books that report their own update time.
    rows = [
        _quote(price=-110, snapshot_ts="2026-08-09T18:00:00Z", book_updated_at="2026-08-09T10:00:00Z"),
        _quote(price=-125, snapshot_ts="2026-08-09T09:00:00Z", book_updated_at="2026-08-09T17:00:00Z"),
    ]
    reduced = odds_book_quotes.reduce_to_latest_per_key(rows)
    assert len(reduced) == 1
    assert reduced[0]["price"] == -125, "must follow the grid's freshness precedence"


def test_equal_stamps_keep_the_later_line():
    # `>=` not `>`, matching book_grid. In an append-only file the later line is
    # the newer write even when the stamps tie.
    rows = [
        _quote(price=-110, snapshot_ts="2026-08-09T12:00:00Z"),
        _quote(price=-115, snapshot_ts="2026-08-09T12:00:00Z"),
    ]
    assert odds_book_quotes.reduce_to_latest_per_key(rows)[0]["price"] == -115


def test_reduced_rows_produce_an_identical_grid():
    """THE FALSIFICATION TEST. If the grid can tell the inputs apart, the whole
    change is wrong and no amount of memory saved would justify it."""
    rows = []
    for hour in (10, 12, 14):
        for book in ("draftkings", "fanduel", "betmgm"):
            for selection in ("home", "away"):
                rows.append(
                    _quote(
                        bookmaker=book,
                        selection=selection,
                        price=-110 - hour,
                        snapshot_ts=f"2026-08-09T{hour:02d}:00:00Z",
                    )
                )
    reduced = odds_book_quotes.reduce_to_latest_per_key(rows)
    assert len(rows) == 18 and len(reduced) == 6

    from datetime import datetime, timezone

    now = datetime(2026, 8, 9, 20, 0, 0, tzinfo=timezone.utc)
    assert json.dumps(build_book_grid(rows, now=now), sort_keys=True, default=str) == json.dumps(
        build_book_grid(reduced, now=now), sort_keys=True, default=str
    )


def test_reader_returns_reduced_rows_and_caches_them(tmp_path, monkeypatch):
    rows = [
        _quote(price=-110, snapshot_ts="2026-08-09T12:00:00Z"),
        _quote(price=-130, snapshot_ts="2026-08-09T15:00:00Z"),
        _quote(bookmaker="fanduel", price=-105),
    ]
    _point_at(monkeypatch, _write_shard(tmp_path, rows))
    out = odds_book_quotes.read_book_quotes_latest("mlb", "2026-08-09")
    assert len(out) == 2
    assert {r["price"] for r in out} == {-130, -105}
    assert len(odds_book_quotes._BOOK_QUOTES_LATEST_CACHE) == 1
    # served from cache on the second call, same object
    assert odds_book_quotes.read_book_quotes_latest("mlb", "2026-08-09") is out


def test_history_is_still_reachable_through_the_unreduced_reader(tmp_path, monkeypatch):
    # The superseded rows ARE the openings and line movement CLV depends on.
    # This change must not be able to take them away.
    rows = [
        _quote(price=-110, snapshot_ts="2026-08-09T12:00:00Z"),
        _quote(price=-130, snapshot_ts="2026-08-09T15:00:00Z"),
    ]
    _point_at(monkeypatch, _write_shard(tmp_path, rows))
    assert len(odds_book_quotes.read_book_quotes_latest("mlb", "2026-08-09")) == 1
    assert len(odds_book_quotes.read_book_quotes("mlb", "2026-08-09")) == 2
    assert len(list(odds_book_quotes.iter_book_quotes("mlb", "2026-08-09"))) == 2


def test_the_last_entry_CAN_be_evicted(tmp_path, monkeypatch):
    """The other cache stops at `len > 1`, which is how one 184.5MB shard pinned
    ~1,162MB with nothing able to drop it."""
    monkeypatch.setattr(odds_book_quotes, "_BOOK_QUOTES_LATEST_MAX_RSS_BYTES", 1)
    _point_at(monkeypatch, _write_shard(tmp_path, [_quote()]))
    odds_book_quotes.read_book_quotes_latest("mlb", "2026-08-09")
    assert len(odds_book_quotes._BOOK_QUOTES_LATEST_CACHE) == 0, "budget must win over the floor"


def test_a_partial_read_is_never_cached(tmp_path, monkeypatch):
    path = _write_shard(tmp_path, [_quote()])
    _point_at(monkeypatch, path)

    def _boom(*_a, **_k):
        raise OSError("transient")

    monkeypatch.setattr(odds_book_quotes, "iter_book_quotes", _boom)
    assert odds_book_quotes.read_book_quotes_latest("mlb", "2026-08-09") == []
    assert len(odds_book_quotes._BOOK_QUOTES_LATEST_CACHE) == 0


def test_commence_time_comes_from_the_freshest_observation():
    """`#435`. The grid took `commence_time` off `sides_rows[0]` -- whichever row
    it iterated first, which in an append-only shard is the OLDEST report.

    Measured on the MLB 2026-08-09 shard: 12 of 15 events carried more than one
    commence_time, spread up to 7 minutes. It is not cosmetic -- `closing_quotes`
    keeps rows with `observed < commence`, so a stale-early start time DISCARDS
    quotes that were genuinely pregame.

    `max()` of the VALUES was the first attempt and is also wrong: a start
    revised EARLIER (18:20:00 -> 18:16:30) makes the largest value the stale one.
    """
    from datetime import datetime, timezone

    now = datetime(2026, 8, 9, 20, 0, 0, tzinfo=timezone.utc)
    early_report_late_start = _quote(
        snapshot_ts="2026-08-09T10:00:00Z", commence_time="2026-08-09T18:20:00Z", price=-110
    )
    late_report_early_start = _quote(
        snapshot_ts="2026-08-09T16:00:00Z", commence_time="2026-08-09T18:16:30Z", price=-115
    )
    # Both orderings, because the whole defect was that order decided the answer.
    for rows in (
        [early_report_late_start, late_report_early_start],
        [late_report_early_start, early_report_late_start],
    ):
        grid = build_book_grid(rows, now=now)
        assert grid, "expected a grid row"
        assert grid[0]["commence_time"] == "2026-08-09T18:16:30Z", grid[0]["commence_time"]


def test_grid_is_identical_whether_fed_full_or_reduced_rows():
    """The gate for `#435`. Verified separately against the real 207MB shard:
    15 of 15 events byte-identical, 478,782 rows -> 36,424."""
    from datetime import datetime, timezone

    now = datetime(2026, 8, 9, 20, 0, 0, tzinfo=timezone.utc)
    rows = []
    for hour in (9, 11, 13, 15):
        for book in ("draftkings", "fanduel"):
            for selection in ("home", "away"):
                rows.append(
                    _quote(
                        bookmaker=book,
                        selection=selection,
                        price=-100 - hour,
                        snapshot_ts=f"2026-08-09T{hour:02d}:00:00Z",
                        # the revision that broke the first two attempts
                        commence_time="2026-08-09T18:20:00Z" if hour < 13 else "2026-08-09T18:16:30Z",
                    )
                )
    reduced = odds_book_quotes.reduce_to_latest_per_key(rows)
    assert len(rows) == 16 and len(reduced) == 4
    assert json.dumps(build_book_grid(rows, now=now), sort_keys=True, default=str) == json.dumps(
        build_book_grid(reduced, now=now), sort_keys=True, default=str
    )
