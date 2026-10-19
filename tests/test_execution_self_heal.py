"""syndicate/features/shared/execution_self_heal.py -- a Kalshi unknown submit is resolved ONLY on the venue's word."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.shared import execution_ledger as ledger
from syndicate.features.shared import execution_self_heal as heal
from syndicate.features.shared import kalshi_orders

NOW = datetime(2026, 10, 19, 22, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _isolated_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.delenv("SYNDICATE_REFRESH_STATE_BACKEND", raising=False)
    monkeypatch.delenv(heal.SELF_HEAL_ENV, raising=False)
    yield


def _z(minutes_ago: float) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")


def _unknown(key="k-1", venue="kalshi", **kw):
    row = {"idempotency_key": key, "mode": "live", "venue": venue, "status": "failed",
           "error": "KalshiAuthError: http_503: upstream", "venue_order_id": None, "venue_ticker": "KXNFL-T1",
           "requested_stake_dollars": 4.5, "submitted_at": _z(10), "venue_resolved_at": _z(10), "side": "yes",
           "selected_date": "2026-10-19"}
    row.update(kw)
    return row


def _seed(*orders):
    state = ledger._load()
    state["orders"] = list(orders)
    ledger._persist(state)


def _stored(key):
    return next(o for o in ledger._load()["orders"] if o["idempotency_key"] == key)


def _venue_row(client, status="executed", filled="5.00", ticker="KXNFL-T1", order_id="ord-9"):
    return {"order_id": order_id, "client_order_id": client, "ticker": ticker, "status": status,
            "fill_count_fp": filled, "initial_count_fp": "5.00", "remaining_count_fp": "0.00",
            "taker_fill_cost_dollars": "4.500000", "taker_fees_dollars": "0.031500", "yes_price_dollars": "0.9000"}


class Fetch:
    def __init__(self, rows=(), status="ok"):
        self.rows, self.status, self.calls = list(rows), status, 0

    def __call__(self, **kw):
        self.calls += 1
        return {"status": self.status, "orders": self.rows, "reason": "http_503" if self.status != "ok" else None}


def _run(fetch, **kw):
    return heal.auto_resolve_unknown_submits(now=NOW, fetch=fetch, view=kalshi_orders.venue_order_view, **kw)


def test_no_unknown_submit_means_no_venue_call():
    _seed({"idempotency_key": "f", "mode": "live", "venue": "kalshi", "status": "filled"})
    fetch = Fetch()
    out = _run(fetch)
    assert fetch.calls == 0 and out["unknown"] == 0 and out["resolved"] == []


def test_listed_and_filled_becomes_submitted_with_the_venue_id_and_a_resolution():
    _seed(_unknown())
    out = _run(Fetch([_venue_row("k-1")]))
    row = _stored("k-1")
    assert [r["finding"] for r in out["resolved"]] == ["placed"]
    assert row["status"] == "submitted" and row["venue_order_id"] == "ord-9"
    assert row["operator_resolution"]["finding"] == "placed" and "auto (execution_self_heal)" in row["operator_resolution"]["note"]
    assert "was failed: KalshiAuthError: http_503" in row["error"]           # provenance kept


def test_then_the_reconciler_books_the_fill_from_the_venue(monkeypatch):
    """End to end: after self-heal the existing reconciler, not this module, books fill price and stake."""
    _seed(_unknown())
    rows = [_venue_row("k-1")]
    _run(Fetch(rows))
    monkeypatch.setattr(ledger, "_venue_reader", lambda venue: (Fetch(rows), kalshi_orders.venue_order_view, "book"))
    monkeypatch.setattr(ledger, "_venue_single_order_reader", lambda venue: None)
    ledger.reconcile_live_orders(venue="kalshi")
    row = _stored("k-1")
    assert row["status"] == "filled" and row["fill_price"] == pytest.approx(0.9)


def test_dead_and_unfilled_is_not_placed_and_frees_the_retry():
    _seed(_unknown())
    out = _run(Fetch([_venue_row("k-1", status="canceled", filled="0.00")]))
    row = _stored("k-1")
    assert [r["finding"] for r in out["resolved"]] == ["not_placed"]
    assert row["status"] == "rejected" and row["pre_resolution_status"] == "failed"


def test_nothing_changes_without_a_definitive_statement():
    _seed(_unknown("absent"), _unknown("young", submitted_at=_z(0.5), venue_resolved_at=_z(0.5)),
          _unknown("mismatch"), _unknown("weird"), _unknown("pm", venue="polymarket"))
    rows = [_venue_row("mismatch", ticker="KXOTHER-1"), _venue_row("weird", status="mystery", filled="0.00")]
    out = _run(Fetch(rows))
    assert out["resolved"] == []
    assert out["skipped"] == {"too_young": 1, "not_listed": 1, "ticker_mismatch": 1, "state_unknown": 1}
    assert out["polymarket_left_for_human"] == 1
    assert all(_stored(k)["status"] == "failed" and not _stored(k).get("operator_resolution")
               for k in ("absent", "young", "mismatch", "weird", "pm"))


def test_a_failed_read_writes_nothing():
    _seed(_unknown())
    out = _run(Fetch([_venue_row("k-1")], status="error"))
    assert out["status"] == "read_failed" and _stored("k-1")["status"] == "failed"


def test_refusals_and_resolved_rows_are_not_unknown():
    assert not heal.is_unknown_submit(_unknown(error="KalshiAuthError: http_400: bad"))
    assert not heal.is_unknown_submit(_unknown(operator_resolution={"finding": "placed"}))
    assert not heal.is_unknown_submit(_unknown(mode="paper:kalshi"))
    assert not heal.is_unknown_submit(_unknown(venue_order_id="o1"))
    assert heal.is_unknown_submit(_unknown())


def test_tick_budget_caps_a_burst():
    keys = [f"b{i}" for i in range(heal.MAX_RESOLUTIONS_PER_TICK + 2)]
    _seed(*[_unknown(k) for k in keys])
    out = _run(Fetch([_venue_row(k, order_id=f"o-{k}") for k in keys]))
    assert len(out["resolved"]) == heal.MAX_RESOLUTIONS_PER_TICK and out["skipped"]["tick_budget"] == 2


def test_off_switch_and_reachability(monkeypatch):
    """off != on: the same ledger and venue read, opposite outcomes."""
    _seed(_unknown())
    monkeypatch.setenv(heal.SELF_HEAL_ENV, "off")
    fetch = Fetch([_venue_row("k-1")])
    assert _run(fetch) == {"status": "off"} and fetch.calls == 0 and _stored("k-1")["status"] == "failed"
    monkeypatch.setenv(heal.SELF_HEAL_ENV, "on")
    assert _run(fetch)["resolved"] and _stored("k-1")["status"] == "submitted"


def test_dry_run_writes_nothing():
    _seed(_unknown())
    out = _run(Fetch([_venue_row("k-1")]), dry_run=True)
    assert out["resolved"][0]["finding"] == "placed" and _stored("k-1")["status"] == "failed"


def test_the_worker_tick_calls_it():
    """Reachability from the real caller: _run_execution_tick names the hook."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "scripts" / "run_live_odds_refresh_worker.py").read_text(encoding="utf-8")
    tick = source[source.index("def _run_execution_tick"):source.index("def _start_live_lens_reports")]
    assert "auto_resolve_unknown_submits()" in tick
    assert tick.index("auto_resolve_unknown_submits()") < tick.index("run_execution(central_today_iso()")
