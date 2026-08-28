"""One status vocabulary, and one honest coverage flag.

Both properties here are about the same failure shape: a reader that answers
confidently when it does not know. An unmapped status silently blocks live
execution on every venue; a truncated page that calls itself the whole book
turns "we asked about what we already believed" into "we agree with the venue".
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import kalshi_orders, polymarket_us_orders
from syndicate.features.shared.venue_order_states import (
    VENUE_DEAD_STATUSES,
    VENUE_FILLED_STATUSES,
    VENUE_RESTING_STATUSES,
    classify,
)


# --------------------------------------------------------------------------
# The vocabulary
# --------------------------------------------------------------------------


def test_the_three_sets_are_disjoint():
    """THE PRECONDITION FOR WIDENING TO THE UNION BEING SAFE.

    Merging two venues' sets can only ever move a word out of `unknown` -- it
    can never re-map one that was already mapped -- PROVIDED no word appears in
    two sets. Asserted rather than assumed, because the whole argument for the
    merge rests on it.
    """
    assert not (VENUE_FILLED_STATUSES & VENUE_RESTING_STATUSES)
    assert not (VENUE_FILLED_STATUSES & VENUE_DEAD_STATUSES)
    assert not (VENUE_RESTING_STATUSES & VENUE_DEAD_STATUSES)


def test_both_venues_read_the_same_vocabulary():
    """The drift this module exists to end. Identity, not equality: two sets
    that happen to match today would drift again tomorrow."""
    assert kalshi_orders._VENUE_FILLED_STATUSES is VENUE_FILLED_STATUSES
    assert kalshi_orders._VENUE_RESTING_STATUSES is VENUE_RESTING_STATUSES
    assert kalshi_orders._VENUE_DEAD_STATUSES is VENUE_DEAD_STATUSES
    assert polymarket_us_orders._VENUE_FILLED_STATUSES is VENUE_FILLED_STATUSES
    assert polymarket_us_orders._VENUE_RESTING_STATUSES is VENUE_RESTING_STATUSES
    assert polymarket_us_orders._VENUE_DEAD_STATUSES is VENUE_DEAD_STATUSES


@pytest.mark.parametrize(
    "word,expected",
    [
        # The four that used to differ BY VENUE off the same word.
        ("complete", "filled"),
        ("live", "resting"),
        ("new", "resting"),
        ("failed", "dead"),
        ("voided", "dead"),
        # Measured on the wire, both venues.
        ("executed", "filled"),
        ("canceled", "dead"),
        ("resting", "resting"),
    ],
)
def test_one_word_means_one_thing_everywhere(word, expected):
    assert classify(word) == expected
    assert classify(word.upper()) == expected
    assert classify(f"  {word} ") == expected


@pytest.mark.parametrize("word", ["", None, "wat", "order_state_something_new"])
def test_anything_unrecognised_is_unknown_not_a_guess(word):
    """`unknown` is the value that makes reconciliation leave a row untouched.
    A guess in either direction is how a real position gets written off, or a
    phantom one booked. Note the last case: a status this venue has never shown
    us must NOT be tailed down to `new` and read as resting -- prefix handling
    is the venue module's job and `classify` must not do it loosely."""
    assert classify(word) == "unknown"


# --------------------------------------------------------------------------
# Coverage
# --------------------------------------------------------------------------


def _kalshi_read(monkeypatch, n, limit):
    payload = {"orders": [{"order_id": f"o{i}", "status": "resting"} for i in range(n)]}
    monkeypatch.setattr(kalshi_orders, "signed_request", lambda *a, **k: payload, raising=False)
    import syndicate.features.shared.kalshi_auth as auth

    monkeypatch.setattr(auth, "signed_request", lambda *a, **k: payload)
    return kalshi_orders.fetch_orders(limit=limit)


def test_a_short_page_is_the_whole_book(monkeypatch):
    read = _kalshi_read(monkeypatch, n=78, limit=100)
    assert read["status"] == "ok"
    assert read["coverage"] == "book"


def test_a_full_page_will_not_claim_to_be_the_whole_book(monkeypatch):
    """`n == limit` cannot tell "exactly that many" from "more, cut off", and
    this read has no pagination. Claiming `book` there is an unknown taking the
    permissive branch -- it would license an orphan scan over a partial book,
    where every order past the cut reads as an orphan we do not hold."""
    read = _kalshi_read(monkeypatch, n=100, limit=100)
    assert read["status"] == "ok"
    assert read["coverage"] == "page"


def test_the_orphan_scan_is_skipped_on_a_partial_read(monkeypatch):
    """The consequence that makes the flag worth having. `reconcile_live_orders`
    gates the scan on `coverage == "book"`, so a degraded flag must reach it as
    `orphans: None` rather than an empty list -- "we did not look" and "we
    looked and found none" are the two facts this must never merge."""
    import syndicate.features.shared.execution_ledger as el

    monkeypatch.setattr(
        el,
        "_venue_reader",
        lambda venue: (
            lambda **kw: {"status": "ok", "orders": [], "coverage": "page"},
            lambda raw: {"state": "unknown"},
            "book",
        ),
    )
    monkeypatch.setattr(el, "_load", lambda: {"orders": []})
    out = el.reconcile_live_orders(venue="kalshi")
    assert out["coverage"] == "page"
    assert out["orphans"] is None


# --------------------------------------------------------------------------
# The cursor walk
#
# Written against a field name that was MEASURED, not guessed:
#   ORDERS_ENVELOPE keys=['cursor', 'orders'] n=78 limit=100   2026-08-28T02:24:18Z
# --------------------------------------------------------------------------


def _pages(monkeypatch, pages):
    """Serve a scripted sequence of envelopes, recording the URLs asked for."""
    import syndicate.features.shared.kalshi_auth as auth

    calls = []
    seq = list(pages)

    def fake(method, url, *a, **k):
        calls.append(url)
        if not seq:
            raise AssertionError("more requests than scripted pages")
        nxt = seq.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    monkeypatch.setattr(auth, "signed_request", fake)
    return calls


def _order_rows(*ids):
    return [{"order_id": i, "status": "resting"} for i in ids]


def test_the_walk_follows_the_cursor_and_concatenates(monkeypatch):
    calls = _pages(monkeypatch, [
        {"orders": _order_rows("a", "b"), "cursor": "CUR1"},
        {"orders": _order_rows("c"), "cursor": ""},
    ])
    read = kalshi_orders.fetch_orders(limit=2)
    assert read["status"] == "ok"
    assert [o["order_id"] for o in read["orders"]] == ["a", "b", "c"]
    assert read["pages"] == 2
    # The cursor is passed back, URL-encoded, on the second request only.
    assert "cursor=" not in calls[0]
    assert "cursor=CUR1" in calls[1]


def test_an_empty_cursor_means_WHOLE_BOOK_even_on_a_full_final_page(monkeypatch):
    """The venue saying "no more" outranks the row count. Before pagination,
    `n == limit` was all we had and a full page had to be assumed truncated;
    an empty cursor is the venue stating otherwise."""
    _pages(monkeypatch, [{"orders": _order_rows("a", "b"), "cursor": ""}])
    read = kalshi_orders.fetch_orders(limit=2)
    assert len(read["orders"]) == 2      # exactly the limit
    assert read["coverage"] == "book"


def test_no_cursor_field_at_all_falls_back_to_the_old_heuristic(monkeypatch):
    """If the venue stops sending the field we are as blind as before, and must
    degrade rather than inherit the stronger guarantee."""
    _pages(monkeypatch, [{"orders": _order_rows("a", "b")}])
    read = kalshi_orders.fetch_orders(limit=2)
    assert read["coverage"] == "page"


def test_hitting_the_page_bound_is_NOT_a_whole_book(monkeypatch):
    """A venue handing back a fresh cursor forever must not spin the call, and
    the bound must not be reported as completeness."""
    monkeypatch.setattr(kalshi_orders, "_MAX_ORDER_PAGES", 3)
    _pages(monkeypatch, [
        {"orders": _order_rows("a"), "cursor": "C1"},
        {"orders": _order_rows("b"), "cursor": "C2"},
        {"orders": _order_rows("c"), "cursor": "C3"},
    ])
    read = kalshi_orders.fetch_orders(limit=10)
    assert read["pages"] == 3
    assert read["coverage"] == "page"


def test_a_repeated_cursor_stops_the_walk(monkeypatch):
    _pages(monkeypatch, [
        {"orders": _order_rows("a"), "cursor": "SAME"},
        {"orders": _order_rows("b"), "cursor": "SAME"},
    ])
    read = kalshi_orders.fetch_orders(limit=10)
    assert read["coverage"] == "page"
    assert [o["order_id"] for o in read["orders"]] == ["a", "b"]


def test_the_walk_dedupes_a_book_that_shifted_underneath_it(monkeypatch):
    """Overlap is legitimate when the book changes mid-walk. Counting an order
    twice would inflate every count downstream."""
    _pages(monkeypatch, [
        {"orders": _order_rows("a", "b"), "cursor": "C1"},
        {"orders": _order_rows("b", "c"), "cursor": ""},
    ])
    read = kalshi_orders.fetch_orders(limit=10)
    assert [o["order_id"] for o in read["orders"]] == ["a", "b", "c"]


def test_a_FIRST_page_failure_is_an_error_not_an_empty_book(monkeypatch):
    """The contract every venue reader here keeps: an empty `orders` on a failed
    read would say "the venue holds nothing", which is licence to write off a
    live position."""
    _pages(monkeypatch, [RuntimeError("http_500")])
    read = kalshi_orders.fetch_orders(limit=10)
    assert read["status"] == "error"
    assert "orders" not in read


def test_a_LATER_page_failure_keeps_what_was_read_but_drops_the_guarantee(monkeypatch):
    """The pages already read are real orders and can still correct the rows
    they name. What is lost is completeness -- which is what `coverage` is for,
    so the partial result is returned as `page` rather than discarded."""
    _pages(monkeypatch, [
        {"orders": _order_rows("a"), "cursor": "C1"},
        RuntimeError("http_500"),
    ])
    read = kalshi_orders.fetch_orders(limit=10)
    assert read["status"] == "ok"
    assert [o["order_id"] for o in read["orders"]] == ["a"]
    assert read["coverage"] == "page"


def test_a_partial_walk_still_suppresses_the_orphan_scan(monkeypatch):
    """The consequence that makes the flag worth having, end to end."""
    import syndicate.features.shared.execution_ledger as el

    _pages(monkeypatch, [
        {"orders": _order_rows("a"), "cursor": "C1"},
        RuntimeError("boom"),
    ])
    monkeypatch.setattr(el, "_load", lambda: {"orders": []})
    monkeypatch.setattr(
        el, "_venue_reader",
        lambda venue: (kalshi_orders.fetch_orders, lambda raw: {"state": "unknown"}, "book"),
    )
    out = el.reconcile_live_orders(venue="kalshi")
    assert out["coverage"] == "page"
    assert out["orphans"] is None
