"""Marking placed orders against the current board.

The failure that matters here is not a crash -- it is a mark that looks right
and is comparing the wrong two numbers. So most of these tests are about
like-for-like: same book, probability space, the fill rather than the request.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.clv_position_join import opening_key_for_row
from syndicate.features.shared.position_marks import (
    REASON_BOOK_GONE,
    REASON_MARKED,
    REASON_MARKET_GONE,
    REASON_NO_TAKEN_PRICE,
    REASON_UNKEYABLE,
    mark_orders_to_board,
    marks_report_line,
)


def _row(price=-110, bookmaker="BetMGM", book_prices=None, **overrides):
    """A board row: ONE row per market, carrying whichever book is best now,
    with every book's price in `quote.book_prices`."""
    row = {
        "sport": "mlb",
        "event_id": "evt-1",
        "market": "batter_hits",
        "segment": None,
        "player_name": "Steven Kwan",
        "side": "Over",
        "line": 0.5,
        "quote": {
            "bookmaker": bookmaker,
            "price": price,
            "book_prices": book_prices if book_prices is not None else {bookmaker: price},
        },
    }
    row.update(overrides)
    return row


def _order(row=None, **overrides):
    row = row if row is not None else _row()
    quote = row.get("quote") or {}
    order = {
        "idempotency_key": "k1",
        "position_key": "p1",
        "selected_date": "2026-08-22",
        "sport": row.get("sport"),
        "event_id": row.get("event_id"),
        "market": row.get("market"),
        "segment": row.get("segment"),
        "player_name": row.get("player_name"),
        "side": row.get("side"),
        "line": row.get("line"),
        "book": quote.get("bookmaker"),
        "requested_price": quote.get("price"),
        "fill_price": quote.get("price"),
        "opening_key": opening_key_for_row(row),
    }
    order.update(overrides)
    return order


def test_a_line_moving_toward_us_is_positive():
    """Took -110, market now -130: the market moved our way."""
    taken = _row(price=-110)
    now = _row(price=-130)
    report = mark_orders_to_board([_order(taken)], [now])
    assert report["marked"] == 1
    assert report["moved_toward"] == 1
    assert report["moved_against"] == 0
    assert report["marks"][0]["clv_pct"] > 0


def test_a_line_moving_away_is_negative():
    report = mark_orders_to_board([_order(_row(price=-130))], [_row(price=-110)])
    assert report["moved_against"] == 1
    assert report["marks"][0]["clv_pct"] < 0


def test_movement_is_probability_points_not_price_arithmetic():
    """-110 -> -130 and +200 -> +180 are both 20 'points' of price and are NOT
    the same movement. Subtracting American odds would call them equal."""
    a = mark_orders_to_board([_order(_row(price=-110))], [_row(price=-130)])
    b = mark_orders_to_board([_order(_row(price=200))], [_row(price=180)])
    assert a["marks"][0]["clv_pct"] != b["marks"][0]["clv_pct"]


def test_a_rotated_best_book_still_marks_at_OUR_book():
    """THE REGRESSION TEST. Production measured `orders=21 marked=0
    reasons={'book_no_longer_quoting': 21}` because the join carried the
    bookmaker, and a board row carries whichever book is best right now. The
    market is still there and our book is still quoting it -- the join simply
    could not see it."""
    taken = _row(price=-110, bookmaker="BetMGM")
    # FanDuel is now best, but BetMGM still quotes the side at -130.
    now = _row(price=-140, bookmaker="FanDuel", book_prices={"FanDuel": -140, "BetMGM": -130})
    report = mark_orders_to_board([_order(taken)], [now])
    assert report["marked"] == 1
    assert report["marks"][0]["current_price"] == -130  # OURS, not FanDuel's -140
    assert report["marks"][0]["current_book"] == "betmgm"


def test_the_best_books_price_is_never_substituted_for_ours():
    """Widening the JOIN must not widen the COMPARISON. If our book has gone,
    the answer is an absence -- taking the best book's price instead would
    reintroduce the best-of-N selection effect as a fake line move."""
    taken = _row(price=-110, bookmaker="BetMGM")
    now = _row(price=-140, bookmaker="FanDuel", book_prices={"FanDuel": -140})
    report = mark_orders_to_board([_order(taken)], [now])
    assert report["marked"] == 0
    assert report["reasons"][REASON_BOOK_GONE] == 1
    assert report["marks"][0]["current_price"] is None


def test_market_gone_and_book_gone_are_DIFFERENT_facts():
    """Collapsed into one reason, a broken join is indistinguishable from a
    quiet slate -- which is exactly how the bug above survived review."""
    taken = _row(bookmaker="BetMGM")
    off_board = mark_orders_to_board([_order(taken)], [])
    still_there = mark_orders_to_board(
        [_order(taken)], [_row(bookmaker="FanDuel", book_prices={"FanDuel": -140})]
    )
    assert off_board["reasons"] == {REASON_MARKET_GONE: 1}
    assert still_there["reasons"] == {REASON_BOOK_GONE: 1}


def test_book_matching_is_case_insensitive():
    """The ledger stores our book lowercased; the board does not promise to."""
    taken = _row(bookmaker="BetMGM")
    now = _row(price=-130, bookmaker="BETMGM", book_prices={"BETMGM": -130})
    report = mark_orders_to_board([_order(taken)], [now])
    assert report["marked"] == 1


def test_the_fill_price_wins_over_the_request():
    """Marking against the request would credit us with slippage we never got."""
    row = _row(price=-110)
    order = _order(row, requested_price=-110, fill_price=-125)
    report = mark_orders_to_board([order], [_row(price=-110)])
    assert report["marks"][0]["taken_price"] == -125


def test_an_order_with_no_price_at_all_is_its_own_reason():
    order = _order(requested_price=None, fill_price=None)
    report = mark_orders_to_board([order], [_row()])
    assert report["reasons"][REASON_NO_TAKEN_PRICE] == 1


def test_an_order_that_cannot_be_keyed_is_named_not_dropped():
    order = _order(opening_key=None, event_id=None)
    report = mark_orders_to_board([order], [_row()])
    assert report["reasons"][REASON_UNKEYABLE] == 1
    assert len(report["marks"]) == 1


def test_an_order_placed_before_opening_key_existed_still_marks():
    """The derivation covers the back catalogue.

    Orders written before `opening_key` was on the record carry no stamp, and
    `segment` was absent from those records entirely. Board rows carry
    `segment: None`, so both sides key to `segment=` and the join holds -- this
    pins that, because if it ever stops holding every pre-existing order goes
    dark at once.
    """
    row = _row(price=-110)
    legacy = _order(row, opening_key=None)
    legacy.pop("segment")
    report = mark_orders_to_board([legacy], [_row(price=-130)])
    assert report["marked"] == 1
    assert report["marks"][0]["clv_pct"] > 0


def test_every_counter_is_present_when_nothing_was_marked():
    report = mark_orders_to_board([], [])
    for field in ("orders", "board_rows", "marked", "moved_toward", "moved_against", "reasons"):
        assert field in report, field
    assert report["avg_clv_pct"] is None  # not 0.0 -- nothing was averaged


def test_average_is_over_marked_orders_only():
    row = _row(price=-110)
    marked = _order(row, idempotency_key="k1")
    unmarkable = _order(row, idempotency_key="k2", opening_key=None, event_id=None)
    report = mark_orders_to_board([marked, unmarkable], [_row(price=-130)])
    assert report["marked"] == 1
    assert report["avg_clv_pct"] == report["marks"][0]["clv_pct"]


def test_an_unchanged_price_is_neither_toward_nor_against():
    report = mark_orders_to_board([_order(_row(price=-110))], [_row(price=-110)])
    assert report["marked"] == 1
    assert report["moved_toward"] == 0
    assert report["moved_against"] == 0


def test_report_line_names_the_counters_worth_acting_on():
    line = marks_report_line(mark_orders_to_board([_order()], [_row(price=-130)]))
    assert "LIVE_MARKS" in line
    for token in ("orders=", "marked=", "toward=", "against=", "avg_clv_pct=", "reasons="):
        assert token in line, token
