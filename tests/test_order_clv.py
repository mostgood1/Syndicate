"""Grading placed orders against the close -- Stage C's gate input.

The dangerous failure here is not a crash. It is a number that looks like a
result: a blended same-book/different-book average, a market "average" over two
bets, or the opening's CLV silently standing in for ours. Most of these tests
are about those.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.order_clv import (
    REASON_NO_CLOSE,
    REASON_NO_ENTRY_PRICE,
    REASON_RESOLVED,
    REASON_UNKEYABLE,
    SCOPE_SAME_BOOK,
    clv_for_orders,
    order_clv_report_line,
)

DATE = "2026-08-22"


def _order(key="k1", opening_key="ok1", **overrides):
    order = {
        "idempotency_key": key,
        "position_key": "p1",
        "opening_key": opening_key,
        "sport": "mlb",
        "market": "batter_hits",
        "side": "Over",
        "line": 0.5,
        "player_name": "Steven Kwan",
        "book": "betmgm",
        "requested_price": -110,
        "fill_price": -110,
        "requested_stake_dollars": 5.0,
        "fill_stake_dollars": 5.0,
    }
    order.update(overrides)
    return order


def _clv_row(key="ok1", close_price=-130, **overrides):
    row = {
        "key": key,
        "sport": "mlb",
        "market": "batter_hits",
        "open_price": -105,
        "close_price": close_price,
        "close_source": "last_pregame_quote",
        "clv_pct": 4.0,
    }
    row.update(overrides)
    return row


def test_clv_is_graded_from_OUR_entry_not_the_opening():
    """The opening is what the market first published. We bet later, at a
    different price, and only the second is evidence about the bettor."""
    report = clv_for_orders([_order(fill_price=-110)], date=DATE, clv_rows=[_clv_row()])
    row = report["rows"][0]
    assert row["entry_price"] == -110
    assert row["reason"] == REASON_RESOLVED
    # The opening's own CLV is carried, not substituted.
    assert row["open_clv_pct"] == 4.0
    assert row["clv_pct"] != row["open_clv_pct"]


def test_beating_the_close_is_positive():
    report = clv_for_orders([_order(fill_price=-110)], date=DATE,
                            clv_rows=[_clv_row(close_price=-130)])
    assert report["rows"][0]["clv_pct"] > 0
    assert report["rows"][0]["beat_close"] is True


def test_losing_to_the_close_is_negative():
    report = clv_for_orders([_order(fill_price=-130)], date=DATE,
                            clv_rows=[_clv_row(close_price=-110)])
    assert report["rows"][0]["clv_pct"] < 0
    assert report["rows"][0]["beat_close"] is False


def test_the_fill_price_wins_over_the_request():
    """Grading the request would credit us with slippage we never got."""
    report = clv_for_orders(
        [_order(requested_price=-110, fill_price=-125)], date=DATE, clv_rows=[_clv_row()]
    )
    assert report["rows"][0]["entry_price"] == -125


# --- the ways a number could look real and not be -------------------------


def test_scopes_are_never_blended_into_one_average():
    """different_book_close measured +6.206 avg vs +2.716 book_agnostic on 150
    real openings. One blended number would be higher than either bet deserved."""
    orders = [_order(key="k1", opening_key="ok1"), _order(key="k2", opening_key="ok2")]
    rows = [
        _clv_row(key="ok1", close_price=-130),  # no scope stamp -> same_book
        _clv_row(key="ok2", close_price=-200, close_book_scope="different_book_close"),
    ]
    report = clv_for_orders(orders, date=DATE, clv_rows=rows)
    scopes = {entry["close_book_scope"]: entry for entry in report["by_scope"]}
    assert set(scopes) == {SCOPE_SAME_BOOK, "different_book_close"}
    assert scopes[SCOPE_SAME_BOOK]["n"] == 1
    assert scopes["different_book_close"]["n"] == 1


def test_an_unstamped_scope_means_same_book_not_unknown():
    """`close_book_scope` is only stamped when a FALLBACK was used, so absent is
    the CLEANEST case. Defaulting it to 'unknown' would relabel the best rows as
    the worst."""
    report = clv_for_orders([_order()], date=DATE, clv_rows=[_clv_row()])
    assert report["rows"][0]["close_book_scope"] == SCOPE_SAME_BOOK


def test_market_aggregates_are_split_by_scope_too():
    """A per-market average that blends scopes is the same bias one level down."""
    orders = [_order(key="k1", opening_key="ok1"), _order(key="k2", opening_key="ok2")]
    rows = [
        _clv_row(key="ok1"),
        _clv_row(key="ok2", close_book_scope="different_book_close"),
    ]
    report = clv_for_orders(orders, date=DATE, clv_rows=rows)
    # Same sport+market, two scopes -> two rows, not one blended row.
    assert len(report["by_market"]) == 2
    assert all(entry["n"] == 1 for entry in report["by_market"])


def test_every_aggregate_carries_n():
    """A market with n=2 must never be readable as a result."""
    report = clv_for_orders([_order()], date=DATE, clv_rows=[_clv_row()])
    for entry in report["by_market"] + report["by_scope"]:
        assert "n" in entry
        assert entry["n"] >= 1


def test_markets_are_not_pooled_across_sports():
    orders = [
        _order(key="k1", opening_key="ok1", sport="mlb"),
        _order(key="k2", opening_key="ok2", sport="wnba"),
    ]
    rows = [_clv_row(key="ok1"), _clv_row(key="ok2", sport="wnba")]
    report = clv_for_orders(orders, date=DATE, clv_rows=rows)
    assert {entry["sport"] for entry in report["by_market"]} == {"mlb", "wnba"}


# --- absences stay named --------------------------------------------------


def test_a_market_with_no_close_is_named_not_dropped():
    report = clv_for_orders([_order()], date=DATE, clv_rows=[])
    assert report["reasons"][REASON_NO_CLOSE] == 1
    assert report["resolved"] == 0
    assert len(report["rows"]) == 1


def test_an_order_with_no_price_is_its_own_reason():
    report = clv_for_orders(
        [_order(requested_price=None, fill_price=None)], date=DATE, clv_rows=[_clv_row()]
    )
    assert report["reasons"][REASON_NO_ENTRY_PRICE] == 1


def test_an_unkeyable_order_is_named():
    report = clv_for_orders(
        [_order(opening_key=None, event_id=None, market=None)], date=DATE, clv_rows=[_clv_row()]
    )
    assert report["reasons"][REASON_UNKEYABLE] == 1


def test_an_order_predating_opening_key_still_grades_via_the_derivation():
    order = _order(opening_key=None, event_id="evt-1", segment=None)
    from syndicate.features.shared.clv_position_join import opening_key_for_position

    report = clv_for_orders(
        [order], date=DATE, clv_rows=[_clv_row(key=opening_key_for_position(order))]
    )
    assert report["resolved"] == 1


def test_counters_are_present_when_nothing_resolved():
    report = clv_for_orders([], date=DATE, clv_rows=[])
    assert report["orders"] == 0
    assert report["resolved"] == 0
    assert report["by_market"] == []
    assert report["by_scope"] == []


def test_report_line_headlines_same_book_only_and_carries_n():
    """The blended number would be higher and would not mean anything."""
    orders = [_order(key="k1", opening_key="ok1"), _order(key="k2", opening_key="ok2")]
    rows = [
        _clv_row(key="ok1", close_price=-130),
        _clv_row(key="ok2", close_price=-300, close_book_scope="different_book_close"),
    ]
    line = order_clv_report_line(clv_for_orders(orders, date=DATE, clv_rows=rows))
    assert "ORDER_CLV" in line
    assert "same_book_n=1" in line
    for token in ("date=", "orders=", "resolved=", "markets=", "reasons="):
        assert token in line, token


def test_report_line_survives_having_no_same_book_rows():
    rows = [_clv_row(close_book_scope="different_book_close")]
    line = order_clv_report_line(clv_for_orders([_order()], date=DATE, clv_rows=rows))
    assert "same_book_n=0" in line
