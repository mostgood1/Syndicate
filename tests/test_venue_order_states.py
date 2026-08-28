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
