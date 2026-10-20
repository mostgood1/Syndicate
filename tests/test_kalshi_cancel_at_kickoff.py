"""A pregame Kalshi order expires at kickoff (todo #707, D3).

Kalshi orders are good-till-canceled, so a pregame order that rests -- up to six
days for a forward NFL/NCAAF/soccer bet -- would fill after kickoff at its
pregame price. `cancel_pregame_resting_at_kickoff` pulls it, and the executor
calls it every Kalshi tick off the reconcile it already runs. Reachability first
(T3): off leaves the order resting, on cancels it once.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from syndicate.features.shared import execution_ledger as L

_NOW = datetime(2026, 10, 24, 19, 5, tzinfo=timezone.utc)
_KICKOFF = "2026-10-24T19:00:00Z"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    for key in (
        "SYNDICATE_EXECUTION_CANCEL_AT_KICKOFF",
        "SYNDICATE_EXECUTION_MAX_CANCELS",
        "SYNDICATE_EXECUTION_ENABLED",
        "SYNDICATE_EXECUTION_MODE",
        "SYNDICATE_EXECUTION_LIVE_ARMED",
        "SYNDICATE_EXECUTION_VENUE",
        "SYNDICATE_REFRESH_STATE_BACKEND",
    ):
        monkeypatch.delenv(key, raising=False)
    yield


def _resting(**overrides):
    row = {
        "idempotency_key": "k-1",
        "order_id": "venue-order-1",
        "ticker": "KXNCAAFSPREAD-26OCT24AAABBB-AAA14",
        "side": "home",
        "submitted_at": "2026-10-22T15:00:00Z",  # Thursday, pregame
        "commence_time": _KICKOFF,
    }
    row.update(overrides)
    return row


def _recording_cancel(monkeypatch, status="ok"):
    from syndicate.features.shared import kalshi_orders

    calls: list = []

    def cancel(order_id):
        calls.append(order_id)
        return {"status": status, "reason": None if status == "ok" else "http_404"}

    monkeypatch.setattr(kalshi_orders, "cancel_order", cancel)
    return calls


# --------------------------------------------------------------------------
# T3 -- reachability: off != on
# --------------------------------------------------------------------------


def test_T3_off_a_pregame_order_rests_through_kickoff(monkeypatch):
    monkeypatch.setenv("SYNDICATE_EXECUTION_CANCEL_AT_KICKOFF", "off")
    calls = _recording_cancel(monkeypatch)
    result = L.cancel_pregame_resting_at_kickoff([_resting()], now=_NOW)
    assert result["reason"] == "disabled"
    assert calls == []


def test_T3_on_a_pregame_order_is_cancelled_once_at_kickoff(monkeypatch, capsys):
    calls = _recording_cancel(monkeypatch)
    result = L.cancel_pregame_resting_at_kickoff([_resting()], now=_NOW)
    assert calls == ["venue-order-1"]
    assert result["cancelled"] == 1
    assert "CANCEL_AT_KICKOFF key=k-1" in capsys.readouterr().out


def test_T3_the_executor_tick_reaches_the_kickoff_cancel(monkeypatch):
    """The reconcile `run_execution` already does every Kalshi tick hands its
    resting rows to the kickoff cancel. `cancel_stale_resting_orders` runs only
    from the worker's boot dump, so it could never be the kickoff clock."""
    from pipeline import execute_portfolio as runner

    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_VENUE", "kalshi")
    resting = [_resting(commence_time="2026-01-01T00:00:00Z", submitted_at="2025-12-31T00:00:00Z")]
    monkeypatch.setattr(
        L, "reconcile_live_orders",
        lambda venue="kalshi", **_: {"status": "ok", "resting": resting if venue == "kalshi" else []},
    )
    handed: list = []
    monkeypatch.setattr(L, "cancel_pregame_resting_at_kickoff", lambda rows, **_: handed.append(list(rows)) or {})
    runner.run_execution("2026-10-24", venue_scope="kalshi")
    assert handed == [resting]

    # Polymarket's pass does not re-run it: Polymarket expires at kickoff on its own.
    handed.clear()
    runner.run_execution("2026-10-24", venue_scope="polymarket")
    assert handed == []


# --------------------------------------------------------------------------
# Which orders
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "row",
    [
        _resting(submitted_at="2026-10-24T19:02:00Z"),  # sent IN-PLAY: an in-play cell, untouched
        _resting(commence_time="2026-10-24T19:30:00Z"),  # not kicked off yet
        _resting(commence_time=None),  # unreadable kickoff: no action on missing information
        _resting(submitted_at=None),
        _resting(commence_time="not-a-time"),
    ],
)
def test_orders_left_alone(monkeypatch, row):
    calls = _recording_cancel(monkeypatch)
    result = L.cancel_pregame_resting_at_kickoff([row], now=_NOW)
    assert calls == []
    assert result["due"] == 0


def test_a_failed_cancel_is_counted_and_changes_nothing(monkeypatch):
    calls = _recording_cancel(monkeypatch, status="error")
    result = L.cancel_pregame_resting_at_kickoff([_resting()], now=_NOW)
    assert calls == ["venue-order-1"]
    assert result["cancelled"] == 0
    assert result["failed"] == 1


def test_bounded_per_pass(monkeypatch):
    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_CANCELS", "2")
    calls = _recording_cancel(monkeypatch)
    rows = [_resting(idempotency_key=f"k-{i}", order_id=f"o-{i}") for i in range(5)]
    result = L.cancel_pregame_resting_at_kickoff(rows, now=_NOW)
    assert calls == ["o-0", "o-1"]
    assert result["due"] == 5


def test_the_reconcile_resting_row_carries_commence_time():
    # Without it the kickoff predicate can never be true on a real row.
    import inspect

    source = inspect.getsource(L.reconcile_live_orders)
    assert '"commence_time": order.get("commence_time")' in source
