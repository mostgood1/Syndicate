"""A venue-terminal fill the venue no longer serves by id has AGED OUT -- it is not unaccounted for.

MEASURED 2026-11-10/11 on live-odds-worker (lane `kalshi-aged-out-grade`). Key `970ec063` (Kalshi, 1 NO,
filled 2026-10-25 17:14Z) was `filled` / `executed` / remaining 0 from an earlier positive read and stayed
ungraded, so it stayed a reconcile candidate. ~15.7 days after the fill Kalshi stopped serving it from the
orders list AND `GET /portfolio/orders/{id}` (`http_404 ... not_found`), and every pass printed
RECONCILE_SINGLE_READ_FAILED "-- still unaccounted for, so it KEEPS blocking" about an order whose venue state
could no longer change: 276 lines by 23:49Z, `exec:log_errors:orders:kalshi` red from 5:01 PM CT.

WHAT IS NOT RELAXED, and is tested as hard as the fix: a `submitted` row with the same 404 still logs and
still blocks (placing again could double a live position), and nothing but a NAMED 404 counts.
"""

from __future__ import annotations

import pytest

from tests.test_execution_ledger import _live_order, _reader

# Verbatim shape of the fleet's reason string, 2026-11-11T17:48:43Z (order id replaced).
NOT_FOUND = ("KalshiAuthError: http_404: https://external-api.kalshi.com/trade-api/v2/portfolio/orders/ord-old: "
             '{"error":{"code":"not_found","message":"not found"}}')


@pytest.fixture
def mod():
    from syndicate.features.shared import execution_ledger as m
    return m


@pytest.fixture(autouse=True)
def _fresh_announcements(mod):
    mod._AGED_OUT_ANNOUNCED.clear()
    yield
    mod._AGED_OUT_ANNOUNCED.clear()


def _install(monkeypatch, mod, single):
    fetch, view, _c = _reader([])
    monkeypatch.setattr(mod, "_venue_reader", lambda venue: (fetch, view, "book"))
    monkeypatch.setattr(mod, "_venue_single_order_reader", lambda venue: single)


def _set(mod, key, **fields):
    state = mod._load()
    for order in state["orders"]:
        if order["idempotency_key"] == key:
            order.update(fields)
    mod._persist(state)


def _terminal_fill(mod, monkeypatch, key="aged", **fields):
    key = _live_order(mod, monkeypatch, key=key, status=mod.STATUS_FILLED, venue_order_id="ord-old",
                      fill_price=0.43, fill_stake_dollars=0.43)
    _set(mod, key, **{"venue_status": "executed", "venue_remaining_count": 0.0, **fields})
    return key


def _counting(reason):
    calls = []

    def single(order_id):
        calls.append(order_id)
        return {"status": "error", "reason": reason}

    return single, calls


def test_a_terminal_fill_that_404s_is_aged_out_stamped_and_logged_once(mod, monkeypatch, capsys):
    key = _terminal_fill(mod, monkeypatch)
    single, calls = _counting(NOT_FOUND)
    _install(monkeypatch, mod, single)

    first = mod.reconcile_live_orders()
    out = capsys.readouterr().out
    assert calls == ["ord-old"]
    assert first["aged_out"] == 1 and first["not_found"] == 0
    assert "RECONCILE_AGED_OUT key=aged" in out.replace(f"key={key}", "key=aged")
    assert "RECONCILE_SINGLE_READ_FAILED" not in out and "RECONCILE_NOT_FOUND" not in out
    assert " aged_out=1 " in out, "the summary line must count it"
    row = mod.find_order(key)
    assert row["venue_aged_out_at"], "the stamp must be persisted, or the next pass reads it again"
    assert row["status"] == mod.STATUS_FILLED and row.get("outcome") is None, "aged out changes no money field"

    second = mod.reconcile_live_orders()
    out2 = capsys.readouterr().out
    assert calls == ["ord-old"], "an aged-out row must not be read again"
    assert second["aged_out"] == 1 and second["not_found"] == 0
    assert "RECONCILE_AGED_OUT" not in out2, "once per process, not once per pass"
    assert "RECONCILE_SINGLE_READ_FAILED" not in out2


def test_off_restores_the_read_every_pass_behaviour(mod, monkeypatch, capsys):
    """Reachability: off != on. With the switch off the measured loop comes back exactly."""
    monkeypatch.setenv(mod.AGED_OUT_ENV, "off")
    key = _terminal_fill(mod, monkeypatch)
    single, calls = _counting(NOT_FOUND)
    _install(monkeypatch, mod, single)

    for _ in range(2):
        result = mod.reconcile_live_orders()
        assert result["aged_out"] == 0 and result["not_found"] == 1
    out = capsys.readouterr().out
    assert calls == ["ord-old", "ord-old"]
    assert out.count("RECONCILE_SINGLE_READ_FAILED") == 2
    assert "RECONCILE_AGED_OUT" not in out
    assert not mod.find_order(key).get("venue_aged_out_at")


def test_a_submitted_row_with_the_same_404_still_logs_and_still_blocks(mod, monkeypatch, capsys):
    """The doubling guard. A submitted order we cannot read might be a live position."""
    key = _live_order(mod, monkeypatch, key="unsure", status=mod.STATUS_SUBMITTED, venue_order_id="ord-old")
    single, calls = _counting(NOT_FOUND)
    _install(monkeypatch, mod, single)

    result = mod.reconcile_live_orders()
    out = capsys.readouterr().out
    assert calls == ["ord-old"]
    assert result["aged_out"] == 0 and result["not_found"] == 1
    assert "RECONCILE_SINGLE_READ_FAILED" in out and "RECONCILE_AGED_OUT" not in out
    assert not mod.find_order(key).get("venue_aged_out_at")
    assert any(o.get("idempotency_key") == key for o in mod.unreconciled_orders())


@pytest.mark.parametrize("reason", [
    "KalshiAuthError: http_503: service unavailable",
    "TimeoutError: timed out",
    "KalshiAuthError: http_404: https://x/portfolio/orders/ord-old: <html>gateway</html>",
    "unreadable",
])
def test_only_a_named_404_not_found_ages_a_row_out(mod, monkeypatch, capsys, reason):
    key = _terminal_fill(mod, monkeypatch)
    single, _calls = _counting(reason)
    _install(monkeypatch, mod, single)

    result = mod.reconcile_live_orders()
    assert result["aged_out"] == 0 and result["not_found"] == 1
    assert "RECONCILE_SINGLE_READ_FAILED" in capsys.readouterr().out
    assert not mod.find_order(key).get("venue_aged_out_at")


@pytest.mark.parametrize("fields", [
    {"venue_status": "resting"},          # a partial fill still working at the venue
    {"venue_remaining_count": 3.0},       # remainder not done
    {"venue_remaining_count": None},      # unknown remainder is not zero
])
def test_a_fill_that_is_not_venue_terminal_is_never_aged_out(mod, monkeypatch, capsys, fields):
    key = _terminal_fill(mod, monkeypatch, **fields)
    single, _calls = _counting(NOT_FOUND)
    _install(monkeypatch, mod, single)

    result = mod.reconcile_live_orders()
    assert result["aged_out"] == 0
    assert "RECONCILE_SINGLE_READ_FAILED" in capsys.readouterr().out
    assert not mod.find_order(key).get("venue_aged_out_at")


def test_after_a_restart_an_aged_out_row_is_named_once_and_still_not_read(mod, monkeypatch, capsys):
    key = _terminal_fill(mod, monkeypatch, venue_aged_out_at="2026-11-11T18:00:00Z")
    single, calls = _counting(NOT_FOUND)
    _install(monkeypatch, mod, single)

    mod.reconcile_live_orders()
    mod.reconcile_live_orders()
    out = capsys.readouterr().out
    assert calls == []
    assert out.count("RECONCILE_AGED_OUT") == 1
    assert mod.find_order(key)["venue_aged_out_at"] == "2026-11-11T18:00:00Z"


def test_the_404_predicate_reads_the_measured_reason(mod):
    assert mod._is_venue_not_found(NOT_FOUND)
    assert not mod._is_venue_not_found("KalshiAuthError: http_404: <html>")
    assert not mod._is_venue_not_found("code not_found but http_500")
    assert not mod._is_venue_not_found(None)
