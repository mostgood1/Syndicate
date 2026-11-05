"""odds_book_quotes: a NaN line is UNCHANGED against a NaN line (#760, lane book-quotes-state-reset).

The NBA and NHL fetchers hand moneylines `line: NaN`. NaN never equals itself, so the dedupe re-appended every
moneyline on every fetch -- 16,206 of NHL 11-04's 39,289 rows -- and its newest row always read as just captured."""
from __future__ import annotations

import json
import math

import pytest

from syndicate.features.shared import odds_book_quotes as obq

DATE = "2026-11-04"


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(obq, "data_root", lambda: tmp_path)
    return tmp_path


def _moneyline(price=-108, selection="away"):
    return {"event_id": "e1", "bookmaker": "draftkings", "market": "h2h", "selection": selection, "line": float("nan"),
            "price": price, "commence_time": "2026-11-05T00:10:00Z", "kind": "game"}


def _append(rows, at):
    return obq.append_book_quotes(sport="nhl", date_str=DATE, rows=rows, captured_at=at, publish=False)


def _shard_rows():
    return [json.loads(line) for line in obq.book_quotes_path("nhl", DATE).read_text().splitlines()]


def test_an_unchanged_nan_line_moneyline_is_not_appended_again(root):
    first = _append([_moneyline(), _moneyline(-112, "home")], "2026-11-04T22:43:49Z")
    again = _append([_moneyline(), _moneyline(-112, "home")], "2026-11-04T22:59:56Z")
    assert first["appended"] == 2 and again["appended"] == 0
    assert [row["captured_at"] for row in _shard_rows()] == ["2026-11-04T22:43:49Z"] * 2
    seen = obq.read_quote_last_seen("nhl", DATE)                    # ...but the LOOK is still recorded
    assert sorted(seen.values()) == ["2026-11-04T22:59:56Z"] * 2


def test_a_nan_line_moneyline_that_moves_is_still_appended(root):
    _append([_moneyline(-108)], "2026-11-04T22:43:49Z")
    moved = _append([_moneyline(-115)], "2026-11-04T22:59:56Z")
    assert moved["appended"] == 1
    assert [row["price"] for row in _shard_rows()] == [-108, -115]
    assert all(math.isnan(row["line"]) for row in _shard_rows())     # the row and its key are left as they were


def test_unchanged_compares_like_equality_everywhere_else():
    nan = float("nan")
    assert obq._unchanged([nan, -108, "t"], [float("nan"), -108])
    assert not obq._unchanged([nan, -108], [nan, -110])
    assert not obq._unchanged([None, -108], [nan, -108])            # None and NaN stay different values
    assert obq._unchanged([5.5, -110], [5.5, -110]) and not obq._unchanged([5.5, -110], [6.0, -110])
    assert not obq._unchanged([], [5.5, -110])                       # a new key is never "unchanged"
