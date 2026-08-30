"""An order absent from the OPEN book is not an order that does not exist.

THE LATCH THIS REMOVES, measured 2026-08-30 on live-odds-worker.

    19:46:53  kalshi candidates=17 not_found=0 stamped=17    healthy
    19:47:28  kalshi candidates=18 not_found=1 stamped=17    <- latch begins
    20:05:12  kalshi candidates=18 not_found=1 stamped=17    unchanged, 4 passes

Every `EXECUTION` line for the next 18 minutes read `status=blocked
reason=unreconciled_orders` on BOTH venues, and the blocking key appeared in 7
log lines of which 7 were `BLOCKED_ON_UNRECONCILED` and NONE was a reconcile
line -- the same signature the module already records for `08e93850`.

THE MECHANISM. `kalshi_orders.fetch_orders` covers "the whole OPEN book", so an
order that FILLED or was CANCELLED is legitimately missing from a completely
successful read. That absence counted `not_found` and hit `continue`, which
skips the freshness stamp at the bottom of the loop. `unreconciled_orders()`
blocks on orders that are `submitted` and not stamped recently, so an order the
book can never show again blocked live execution on every venue FOREVER --
nothing in the system could stamp it.

`fetch_orders`'s own docstring named the missing piece: "The LIST is the primary
instrument for reconciliation and THE SINGLE READ IS THE FALLBACK". The fallback
existed, was documented, and was never called.

WHAT IS NOT RELAXED: an order we still cannot account for AFTER asking about it
directly keeps blocking. That is correct -- placing again could double a live
position -- and the tests for it are as load-bearing as the recovery tests.
"""
from __future__ import annotations

import pytest

from tests.test_execution_ledger import _live_order, _reader


def _reader_with_single(orders, single, *, ok=True, coverage="book"):
    """`_reader`, plus the per-order fallback the reconciler now reaches for."""
    fetch, view, _cov = _reader(orders, ok=ok)
    return fetch, view, coverage, single


@pytest.fixture
def mod():
    from syndicate.features.shared import execution_ledger as m
    return m


def _install(monkeypatch, mod, *, book, single=None, coverage="book"):
    fetch, view, _c = _reader(book)
    monkeypatch.setattr(mod, "_venue_reader", lambda venue: (fetch, view, coverage))
    monkeypatch.setattr(mod, "_venue_single_order_reader",
                        lambda venue: (single if coverage == "book" else None))


# --------------------------------------------------------------------------
# THE LATCH.
# --------------------------------------------------------------------------


def test_an_order_missing_from_the_open_book_is_recovered_and_stamped(mod, monkeypatch, capsys):
    """The whole defect in one test: the book cannot show a filled order, the
    per-order read can, and the stamp is what stops it blocking."""
    key = _live_order(mod, monkeypatch, key="latched", status=mod.STATUS_SUBMITTED,
                      venue_order_id="ord-gone")
    calls = []

    def single(order_id):
        calls.append(order_id)
        return {"status": "ok", "order": {"order_id": "ord-gone", "client_order_id": key,
                                          "status": "executed", "filled_count": 2,
                                          "remaining_count": 0, "initial_count": 2}}

    _install(monkeypatch, mod, book=[], single=single)
    result = mod.reconcile_live_orders()

    assert calls == ["ord-gone"], "the documented fallback read was never called"
    assert result["not_found"] == 0
    assert result["stamped"] == 1, "recovered but unstamped still blocks forever"
    assert "RECONCILE_RECOVERED" in capsys.readouterr().out


def test_a_recovered_order_stops_blocking_live_execution(mod, monkeypatch):
    """The stamp is not bookkeeping -- it is the ONLY input to the block."""
    key = _live_order(mod, monkeypatch, key="unblocks", status=mod.STATUS_SUBMITTED,
                      venue_order_id="ord-gone")
    _install(monkeypatch, mod, book=[], single=lambda oid: {
        "status": "ok", "order": {"order_id": "ord-gone", "client_order_id": key,
                                  "status": "executed", "filled_count": 2,
                                  "remaining_count": 0, "initial_count": 2}})

    assert any(o.get("idempotency_key") == key for o in mod.unreconciled_orders()), (
        "precondition: this order must block BEFORE the reconcile pass"
    )
    mod.reconcile_live_orders()
    assert not any(o.get("idempotency_key") == key for o in mod.unreconciled_orders())


# --------------------------------------------------------------------------
# THE SAFE DIRECTION, which is not relaxed anywhere.
# --------------------------------------------------------------------------


def test_an_unreadable_order_keeps_blocking(mod, monkeypatch, capsys):
    """Asking and getting no answer is still an unknown. Blocking is correct:
    placing again could double a live position."""
    key = _live_order(mod, monkeypatch, key="unreadable", status=mod.STATUS_SUBMITTED,
                      venue_order_id="ord-x")
    _install(monkeypatch, mod, book=[],
             single=lambda oid: {"status": "error", "reason": "http_503"})

    result = mod.reconcile_live_orders()
    assert result["not_found"] == 1 and result["stamped"] == 0
    assert "RECONCILE_SINGLE_READ_FAILED" in capsys.readouterr().out
    assert any(o.get("idempotency_key") == key for o in mod.unreconciled_orders())


def test_an_order_with_no_venue_id_is_named_not_silent(mod, monkeypatch, capsys):
    """A lost submit response leaves nothing to fetch BY. It must keep blocking
    AND say why -- a halt nobody can attribute is how twelve hours went by."""
    _live_order(mod, monkeypatch, key="noid", status=mod.STATUS_SUBMITTED,
                venue_order_id="")
    called = []
    _install(monkeypatch, mod, book=[], single=lambda oid: called.append(oid))

    result = mod.reconcile_live_orders()
    assert called == [], "there is no id to read by; it must not be attempted"
    assert result["not_found"] == 1
    assert "RECONCILE_NO_VENUE_ID" in capsys.readouterr().out


def test_a_per_order_venue_does_not_get_a_second_identical_read(mod, monkeypatch):
    """Polymarket already reads by id, so a `not_found` there has already asked.
    Retrying would double every request for no new information."""
    _live_order(mod, monkeypatch, key="poly", status=mod.STATUS_SUBMITTED,
                venue_order_id="ord-p")
    called = []
    _install(monkeypatch, mod, book=[], coverage="per_order",
             single=lambda oid: called.append(oid))

    assert mod.reconcile_live_orders()["not_found"] == 1
    assert called == []


def test_the_recovery_budget_binds_and_says_so(mod, monkeypatch, capsys):
    """A book read returning nothing must not fan out into one request per
    candidate every cycle -- and a truncation nobody can see reads as full
    coverage."""
    monkeypatch.setattr(mod, "_NOT_FOUND_SINGLE_READ_BUDGET", 2)
    for i in range(5):
        _live_order(mod, monkeypatch, key=f"b{i}", status=mod.STATUS_SUBMITTED,
                    venue_order_id=f"ord-{i}")
    calls = []
    _install(monkeypatch, mod, book=[],
             single=lambda oid: (calls.append(oid), {"status": "error", "reason": "x"})[1])

    result = mod.reconcile_live_orders()
    assert len(calls) == 2, "the budget did not bind"
    assert result["recovery_skipped"] == 3
    assert "recovery_skipped=3" in capsys.readouterr().out


# --------------------------------------------------------------------------
# off != on. WITHOUT the fallback the code takes the pre-fix path exactly:
# `seen is None` -> not_found -> `continue` -> no stamp -> blocks forever.
# --------------------------------------------------------------------------


def test_without_the_fallback_the_order_latches_forever(mod, monkeypatch):
    """THE REGRESSION GUARD. If this ever passes while the recovery tests above
    also pass, the fallback has been disconnected and the latch is back.

    Deliberately asserts the BROKEN behaviour, because the value of the fix is
    exactly the difference between this test and
    `test_a_recovered_order_stops_blocking_live_execution`, which sets up the
    identical order and venue state.
    """
    key = _live_order(mod, monkeypatch, key="prefix", status=mod.STATUS_SUBMITTED,
                      venue_order_id="ord-gone")
    fetch, view, _c = _reader([])                       # book cannot show it
    monkeypatch.setattr(mod, "_venue_reader", lambda venue: (fetch, view, "book"))
    monkeypatch.setattr(mod, "_venue_single_order_reader", lambda venue: None)

    result = mod.reconcile_live_orders()
    assert result["not_found"] == 1
    assert result["stamped"] == 0
    # ...and it is STILL blocking, which is the 18 minutes of dead execution.
    assert any(o.get("idempotency_key") == key for o in mod.unreconciled_orders())
