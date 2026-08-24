"""Stage B: the ledger, and the properties that stop it placing money twice."""

from __future__ import annotations

import pytest

from syndicate.features.shared import execution_ledger as ledger
from syndicate.features.shared.execution_ledger import (
    LIVE,
    PAPER,
    STATUS_FAILED,
    STATUS_FILLED,
    STATUS_REJECTED,
    STATUS_SUBMITTED,
    OrderRequest,
    complete_order,
    execution_mode,
    idempotency_key,
    ledger_summary,
    place_order,
    record_order,
    unreconciled_orders,
)


@pytest.fixture(autouse=True)
def _isolated_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.delenv("SYNDICATE_EXECUTION_MODE", raising=False)
    monkeypatch.delenv("SYNDICATE_EXECUTION_LIVE_ARMED", raising=False)
    monkeypatch.delenv("SYNDICATE_REFRESH_STATE_BACKEND", raising=False)
    yield


def _request(**overrides) -> OrderRequest:
    base = {
        "position_key": "abc123",
        "selected_date": "2026-08-22",
        "venue": "paper",
        "sport": "mlb",
        "event_id": "evt-1",
        "market": "h2h",
        "side": "home",
        "requested_price": -110.0,
        "requested_stake_dollars": 12.50,
    }
    base.update(overrides)
    return OrderRequest(**base)


# --------------------------------------------------------------------------
# Mode: safe by default, in the direction that spends nothing
# --------------------------------------------------------------------------


def test_the_default_mode_is_paper():
    assert execution_mode() == PAPER


@pytest.mark.parametrize("value", ["", "LIVE ", "live", "1", "yes", "nonsense", "volatile_lru"])
def test_only_an_exact_live_resolves_to_live(value, monkeypatch):
    """An unrecognised value must resolve to the mode that spends NO money.

    The 2026-08-22 `SYNDICATE_REFRESH_STATE_BACKEND` incident is the
    counter-example: there an unrecognised value silently meant "local disk".
    Here the fallback direction is the safe one, so a typo cannot arm this.
    """
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", value)
    expected = LIVE if value.strip().lower() == "live" else PAPER
    assert execution_mode() == expected


# --------------------------------------------------------------------------
# Idempotency -- the property that stops double-placing real money
# --------------------------------------------------------------------------


def test_the_same_bet_yields_the_same_key():
    assert idempotency_key(_request()) == idempotency_key(_request())


@pytest.mark.parametrize(
    "mutation",
    [
        {"position_key": "other"},
        {"selected_date": "2026-08-23"},
        {"venue": "kalshi"},
        {"market": "totals"},
        {"side": "away"},
        {"line": -1.5},
        {"player_name": "Someone Else"},
    ],
)
def test_a_different_bet_yields_a_different_key(mutation):
    assert idempotency_key(_request(**mutation)) != idempotency_key(_request())


def test_a_moved_price_is_the_same_order_not_a_new_one():
    """A quote refresh must not look like a new bet, or a re-priced slate would
    place every position again."""
    assert idempotency_key(_request(requested_price=-104.0)) == idempotency_key(_request())


def test_recording_the_same_order_twice_creates_one_record():
    first, created_first = record_order(_request())
    second, created_second = record_order(_request())
    assert created_first is True
    assert created_second is False
    assert first["idempotency_key"] == second["idempotency_key"]
    assert ledger_summary()["orders"] == 1


def test_a_replayed_slate_places_nothing_new():
    for _ in range(3):
        place_order(_request())
    assert ledger_summary()["orders"] == 1


def test_a_second_place_never_reaches_the_venue(monkeypatch):
    """`submit` must not be called for an order that already exists -- the
    refusal has to happen BEFORE the venue, not after."""
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "1")
    calls = []

    def _submit(request):
        calls.append(request)
        return {"status": STATUS_FILLED, "fill_price": -110.0, "fill_stake_dollars": 12.5}

    place_order(_request(), submit=_submit)
    place_order(_request(), submit=_submit)
    assert len(calls) == 1


# --------------------------------------------------------------------------
# Write-ahead -- the record exists before anything is sent
# --------------------------------------------------------------------------


def test_the_order_is_recorded_before_the_venue_is_called(monkeypatch):
    """A crash between submit and record double-places. So at the moment
    `submit` runs, the record must already be on disk in `submitted`."""
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "1")
    seen = {}

    def _submit(request):
        stored = ledger.find_order(idempotency_key(request))
        seen["status_at_submit_time"] = None if stored is None else stored.get("status")
        return {"status": STATUS_FILLED}

    place_order(_request(), submit=_submit)
    assert seen["status_at_submit_time"] == STATUS_SUBMITTED


def test_a_submit_that_raises_leaves_the_order_recorded_and_failed(monkeypatch):
    """The order is NOT deleted. A submit that raised may still have reached the
    venue, so the record is the only thing that makes reconciliation possible."""
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "1")

    def _submit(request):
        raise RuntimeError("connection reset")

    record = place_order(_request(), submit=_submit)
    assert record["status"] == STATUS_FAILED
    assert "connection reset" in record["error"]
    assert ledger_summary()["orders"] == 1


def test_an_order_stranded_in_submitted_is_reported_for_reconciliation():
    record, _ = record_order(_request())
    stranded = unreconciled_orders()
    assert [o["idempotency_key"] for o in stranded] == [record["idempotency_key"]]
    complete_order(record["idempotency_key"], status=STATUS_FILLED, fill_price=-110.0)
    assert unreconciled_orders() == []


# --------------------------------------------------------------------------
# Paper mode is the live path with one boolean changed
# --------------------------------------------------------------------------


def test_paper_fills_at_the_decision_price_and_says_it_is_paper():
    record = place_order(_request())
    assert record["mode"] == PAPER
    assert record["status"] == STATUS_FILLED
    assert record["fill_price"] == pytest.approx(-110.0)
    assert record["fill_stake_dollars"] == pytest.approx(12.50)
    assert record["venue_order_id"] is None


def test_paper_never_calls_a_venue_even_if_one_is_wired():
    calls = []
    place_order(_request(), submit=lambda request: calls.append(request))
    assert calls == []


def test_a_paper_record_is_shaped_exactly_like_a_live_one(monkeypatch):
    """The point of paper mode: nothing downstream can tell them apart except
    by `mode`, which is what makes a paper run evidence about the live one."""
    paper = place_order(_request())
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "1")
    live = place_order(
        _request(event_id="evt-2"),
        submit=lambda request: {"status": STATUS_FILLED, "fill_price": -108.0, "venue_order_id": "v-1"},
    )
    assert set(paper) == set(live)
    assert paper["mode"] == PAPER and live["mode"] == LIVE


# --------------------------------------------------------------------------
# Two switches for real money
# --------------------------------------------------------------------------


def test_live_mode_without_the_arm_places_nothing(monkeypatch):
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    calls = []
    record = place_order(_request(), submit=lambda request: calls.append(request))
    assert record["status"] == STATUS_REJECTED
    assert "LIVE_ARMED" in record["error"]
    assert calls == []


def test_live_mode_with_no_venue_adapter_places_nothing(monkeypatch):
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "1")
    record = place_order(_request(), submit=None)
    assert record["status"] == STATUS_REJECTED
    assert "no venue adapter" in record["error"]


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------


def test_the_ledger_path_carries_no_date_token():
    """A dated path takes the store's 10-day TTL. A record of money placed must
    not expire."""
    import re

    from syndicate.features.shared.refresh_state_store import _default_keyvalue_ttl_seconds

    path = ledger._ledger_path()
    assert not re.search(r"20\d{2}[-_]?\d{2}[-_]?\d{2}", str(path))
    assert _default_keyvalue_ttl_seconds(path) is None


def test_an_unreadable_ledger_refuses_rather_than_looking_empty(monkeypatch):
    """THE ONE PLACE THIS MODULE REFUSES INSTEAD OF DEGRADING. An empty read
    would make every existing order look unplaced and invite a duplicate of the
    entire slate."""
    def _boom(_path):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(ledger, "read_json_file", _boom)
    with pytest.raises(ledger.LedgerError):
        record_order(_request())


def test_only_lean_fields_are_persisted():
    """Never the candidate's full payload -- that is what made the other
    ledger's records large enough to cause a 4.9GB-chunk incident."""
    record, _ = record_order(_request())
    assert set(record) == set(ledger._LEAN_FIELDS)


def test_the_summary_counts_money_only_for_filled_orders():
    place_order(_request())
    record, _ = record_order(_request(event_id="evt-2"))  # left in `submitted`
    summary = ledger_summary("2026-08-22")
    assert summary["orders"] == 2
    assert summary["by_status"][STATUS_FILLED] == 1
    assert summary["by_status"][STATUS_SUBMITTED] == 1
    assert summary["filled_stake_dollars"] == pytest.approx(12.50)
    assert summary["unreconciled"] == 1
    del record


# --------------------------------------------------------------------------
# An order that never reached the venue is REJECTED, not FAILED
# --------------------------------------------------------------------------


def test_a_pre_send_refusal_is_rejected_not_failed(monkeypatch, tmp_path):
    """MEASURED 2026-08-24T00:34Z: two orders that never left the process were
    recorded `failed` and charged $7.02 against a $40 daily cap.

    `failed` means "may have reached the venue" -- it blocks the next run as
    unreconciled and burns budget. An adapter that raises BEFORE sending says
    so with `venue_contacted = False`, and that must produce `rejected`, the
    status for a refusal made without a venue call. A systematic build error
    would otherwise spend a whole day's budget without one request reaching
    Kalshi, and the day would end looking like it had traded.
    """
    from syndicate.features.shared import execution_ledger as mod
    from syndicate.features.shared.kalshi_orders import OrderBuildError

    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "1")

    def never_sent(_request):
        raise OrderBuildError("no_live_price: None")

    request = _request(position_key="pre-send-1")
    record = mod.place_order(request, submit=never_sent, mode=mod.LIVE)
    assert record["status"] == mod.STATUS_REJECTED
    assert "no_live_price" in record["error"]


def test_an_exception_that_says_nothing_is_still_failed(monkeypatch):
    """Fail SAFE. An adapter that blew up mid-request may well have sent it, so
    silence about `venue_contacted` must keep the conservative reading."""
    from syndicate.features.shared import execution_ledger as mod

    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "1")

    def blew_up(_request):
        raise RuntimeError("connection reset mid-POST")

    request = _request(position_key="ambiguous-1")
    record = mod.place_order(request, submit=blew_up, mode=mod.LIVE)
    assert record["status"] == mod.STATUS_FAILED
