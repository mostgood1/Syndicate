"""An order with no recorded opening is graded from the quote log on its own identity.

Lane `venue-order-opening-gap`. 78 settled MLB paper orders on the fleet ledger
(2026-10-22) had no opening in any file within +-3 days -- the 32 MiB openings
ceiling cut 10-11's file at 14:03Z, and `venue_scope` keys a venue order on a
(line, book) the board recorded only when that venue was its best book. Each was
stamped `no_close_for_market` with `no_close_reason` None, while the quote log
held the order's own book quoting the exact bet until first pitch.

Shapes are production's: the order as the fleet ledger holds the 10-03 Kalshi
first-5 total, the quote row as `odds_book_quotes` writes one.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from syndicate.features.shared import clv_join
from syndicate.features.shared.order_clv import (
    OPENING_FROM_ORDER,
    REASON_NO_CLOSE,
    REASON_RESOLVED,
    SCOPE_DIFFERENT_BOOK,
    SCOPE_SAME_BOOK,
    clv_for_orders,
)

_DATE = "2026-10-03"
_EVENT = "5d13b613a334039f0694d8c95af28728"
_KICKOFF = "2026-10-03T17:01:00Z"
_NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
_KEY = (
    f"event_id={_EVENT}|market=totals|player=|segment=first5|side=over|line=3.5|bookmaker=kalshi"
)


def _order(**over):
    order = {
        "idempotency_key": "eaed7679b7f266b466352e28",
        "opening_key": _KEY,
        "sport": "mlb",
        "venue": "paper:kalshi",
        "event_id": _EVENT,
        "market": "totals",
        "segment": "first5",
        "side": "over",
        "line": 3.5,
        "player_name": None,
        "book": "kalshi",
        "commence_time": _KICKOFF,
        "submitted_at": "2026-10-02T21:11:31.740043Z",
        "requested_price": -108.0,
        "fill_price": -108.0,
        "fill_stake_dollars": 1.87,
        "selected_date": _DATE,
        "status": "filled",
        "outcome": "lost",
    }
    order.update(over)
    return order


def _quote(captured_at, price, **over):
    row = {
        "captured_at": captured_at,
        "snapshot_ts": captured_at,
        "sport": "mlb",
        "kind": "game",
        "event_id": _EVENT,
        "commence_time": _KICKOFF,
        "bookmaker": "kalshi",
        "market": "totals",
        "segment": "first5",
        "selection": "over",
        "player_name": None,
        "line": 3.5,
        "price": price,
        "source": "venue_direct",
    }
    row.update(over)
    return row


def _loader(*rows, calls=None):
    def load(sport, shard_date, event_ids):
        if calls is not None:
            calls.append((sport, shard_date, event_ids))
        return [row for row in rows if row["event_id"] in event_ids] if shard_date == _DATE else None

    return load


def _grade(orders, *quotes, calls=None, **kw):
    kw.setdefault("clv_rows", [])
    kw.setdefault("unresolved_rows", [])
    kw.setdefault("now", _NOW)
    return clv_for_orders(
        orders, date=_DATE, quote_rows=_loader(*quotes, calls=calls), **kw
    )


def test_an_opening_less_order_takes_its_own_books_pregame_close():
    # The case that was `no_close_for_market` / None on the fleet ledger.
    report = _grade(
        [_order()],
        _quote("2026-10-02T20:00:00Z", -105),
        _quote("2026-10-03T15:30:00Z", -125),
        _quote("2026-10-03T17:30:00Z", +150),  # in play: never a close
    )
    (row,) = report["rows"]
    assert row["reason"] == REASON_RESOLVED
    assert row["close_price"] == -125
    assert row["close_book_scope"] == SCOPE_SAME_BOOK
    assert row["opening_source"] == OPENING_FROM_ORDER
    assert row["close_source"] == clv_join.BOOK_QUOTES_CLOSE_SOURCE
    # Graded from OUR fill, and there is no opening CLV to carry.
    assert row["clv_pct"] == pytest.approx(clv_join.clv_pct_from_prices(-108.0, -125))
    assert row["clv_pct"] > 0
    assert row["open_clv_pct"] is None


def test_only_another_books_quote_is_a_different_book_close():
    report = _grade([_order()], _quote("2026-10-03T15:30:00Z", -125, bookmaker="draftkings"))
    (row,) = report["rows"]
    assert row["reason"] == REASON_RESOLVED
    assert row["close_book_scope"] == SCOPE_DIFFERENT_BOOK


def test_a_close_last_changed_before_the_fill_is_refused_by_name():
    report = _grade([_order()], _quote("2026-10-02T20:00:00Z", -105))
    (row,) = report["rows"]
    assert row["reason"] == REASON_NO_CLOSE
    assert row["no_close_reason"] == "no_opening:quotes_unchanged_since_open"
    assert report["no_close_reasons"] == {"no_opening:quotes_unchanged_since_open": 1}


def test_an_in_play_fill_has_no_pregame_close():
    report = _grade(
        [_order(submitted_at="2026-10-03T17:20:00Z")], _quote("2026-10-03T15:30:00Z", -125)
    )
    (row,) = report["rows"]
    assert row["no_close_reason"] == "no_opening:opened_in_play"


def test_a_game_that_has_not_started_has_no_close():
    report = _grade(
        [_order()],
        _quote("2026-10-03T15:30:00Z", -125),
        now=datetime(2026, 10, 3, 16, 0, tzinfo=timezone.utc),
    )
    assert report["rows"][0]["no_close_reason"] == "no_opening:not_started"


def test_no_matching_quote_is_named_not_None():
    report = _grade([_order()], _quote("2026-10-03T15:30:00Z", -125, line=4.5))
    assert report["rows"][0]["no_close_reason"] == "no_opening:quotes_no_matching_quote"


def test_an_order_without_a_submit_clock_is_refused_not_guessed():
    report = _grade([_order(submitted_at=None)], _quote("2026-10-03T15:30:00Z", -125))
    assert report["rows"][0]["no_close_reason"] == "no_opening:order_lacks_identity"


def test_an_order_whose_opening_the_resolver_refused_keeps_that_reason():
    # The opening EXISTS and was refused for a reason with its own remedy; the
    # quote pass is for orders the resolver never saw, not a second opinion.
    calls: list = []
    report = _grade(
        [_order()],
        _quote("2026-10-03T15:30:00Z", -125),
        calls=calls,
        unresolved_rows=[{"key": _KEY, "reason": "segment_absent_from_history"}],
    )
    assert report["rows"][0]["no_close_reason"] == "segment_absent_from_history"
    assert calls == []


def test_an_order_whose_opening_resolved_is_untouched():
    calls: list = []
    report = _grade(
        [_order()],
        _quote("2026-10-03T15:30:00Z", -125),
        calls=calls,
        clv_rows=[{"key": _KEY, "close_price": -140, "clv_pct": 1.0}],
    )
    (row,) = report["rows"]
    assert row["close_price"] == -140
    assert "opening_source" not in row
    assert calls == []


def test_injected_clv_rows_without_quote_rows_read_no_quote_log(monkeypatch):
    # The caller chose its close source: unchanged behaviour, and no disk read.
    def boom(*_a, **_k):
        raise AssertionError("quote log read")

    monkeypatch.setattr(clv_join, "read_quote_rows_for_events", boom)
    report = clv_for_orders([_order()], date=_DATE, clv_rows=[], unresolved_rows=[])
    (row,) = report["rows"]
    assert row["reason"] == REASON_NO_CLOSE
    assert row["no_close_reason"] is None


def test_one_shard_read_serves_every_opening_less_order():
    calls: list = []
    orders = [
        _order(),
        _order(idempotency_key="b", side="under", opening_key=_KEY.replace("side=over", "side=under")),
    ]
    report = _grade(
        orders,
        _quote("2026-10-03T15:30:00Z", -125),
        _quote("2026-10-03T15:30:00Z", +105, selection="under"),
        calls=calls,
    )
    assert report["resolved"] == 2
    assert len(calls) == 1


def test_the_production_path_reaches_the_quote_log(monkeypatch):
    """REACHABILITY: no injection at all, as `stamp_closing_marks` calls it.

    `compute_clv_for_date` finds no opening (the truncated file) and the default
    loader is the quote log -- the configuration the fleet runs.
    """
    monkeypatch.setattr(
        clv_join, "compute_clv_for_date", lambda date, sport, root=None: {"rows": [], "unresolved_rows": []}
    )
    monkeypatch.setattr(
        clv_join, "read_quote_rows_for_events", _loader(_quote("2026-10-03T15:30:00Z", -125))
    )
    monkeypatch.setattr(clv_join, "read_quote_state_for_keys", lambda *a: None)
    report = clv_for_orders([_order()], date=_DATE, now=_NOW)
    (row,) = report["rows"]
    assert row["reason"] == REASON_RESOLVED
    assert row["opening_source"] == OPENING_FROM_ORDER


def test_the_closing_mark_records_that_the_fill_was_the_open():
    from syndicate.features.shared.paper_settlement import stamp_closing_marks

    order = _order()
    out = stamp_closing_marks(
        [order],
        _DATE,
        closer=lambda rows, date: _grade(rows, _quote("2026-10-03T15:30:00Z", -125)),
        now=_NOW,
    )
    assert out["resolved"] == 1
    mark = order["closing_mark"]
    assert mark["clv_pct"] > 0
    assert mark["close_book_scope"] == SCOPE_SAME_BOOK
    assert mark["opening_source"] == OPENING_FROM_ORDER
