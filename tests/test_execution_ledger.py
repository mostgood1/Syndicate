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


# --------------------------------------------------------------------------
# Correcting pre-send failures written before adapters declared contact
# --------------------------------------------------------------------------


def test_a_presend_failure_is_reclassified_not_deleted(monkeypatch):
    """The row is a real event -- the system decided to bet and the builder
    refused before sending. Deleting it would make the ledger stop being a
    record. Only the STATUS was wrong: `failed` charges the daily budget for
    an order that never left the process ($7.02 of a $40 cap on 2026-08-24)."""
    from syndicate.features.shared import execution_ledger as mod

    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "1")

    def never_sent(_request):
        raise RuntimeError("boom")

    request = _request(position_key="reclass-1")
    record = mod.place_order(request, submit=never_sent, mode=mod.LIVE)
    # Force the pre-fix shape: failed, with a build error.
    mod.complete_order(
        record["idempotency_key"],
        status=mod.STATUS_FAILED,
        error="OrderBuildError: no_live_price: None",
    )

    result = mod.reclassify_presend_failures()
    assert result["reclassified"] == 1

    fixed = mod.find_order(record["idempotency_key"])
    assert fixed["status"] == mod.STATUS_REJECTED
    # The correction is VISIBLE -- one nobody can see is a rewrite.
    assert fixed["reclassified_from"] == mod.STATUS_FAILED
    assert fixed["error"] == "OrderBuildError: no_live_price: None"


def test_a_real_venue_failure_is_left_alone(monkeypatch):
    """A status we cannot PROVE is safe stays `failed`. Only the
    `OrderBuildError` prefix is evidence that no request was sent."""
    from syndicate.features.shared import execution_ledger as mod

    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "1")

    def blew_up(_request):
        raise RuntimeError("connection reset mid-POST")

    request = _request(position_key="reclass-keep")
    record = mod.place_order(request, submit=blew_up, mode=mod.LIVE)
    assert record["status"] == mod.STATUS_FAILED

    mod.reclassify_presend_failures()
    assert mod.find_order(record["idempotency_key"])["status"] == mod.STATUS_FAILED


def test_reclassify_is_idempotent(monkeypatch):
    """A corrected row is no longer `failed`, so a second call changes nothing.
    It runs at every boot, so this is the property that makes that safe."""
    from syndicate.features.shared import execution_ledger as mod

    assert mod.reclassify_presend_failures()["status"] == "ok"
    second = mod.reclassify_presend_failures()
    assert second["reclassified"] == 0


def test_a_deprecated_endpoint_410_is_recoverable(monkeypatch):
    """MEASURED 2026-08-24T08:01Z. A real, correctly built order — Zebby
    Matthews under 4.5 strikeouts, $1.58, valid ticker and price — reached
    Kalshi and died on http_410 `deprecated_v1_order_endpoint`.

    Recorded `failed`, it can never be retried: `place_order` finds the
    idempotency key, returns the record, and never contacts the venue. A dead
    route would poison every position it touched, permanently, and charge the
    day's budget for each. The 410 is proof the route is gone and nothing was
    created behind it, so it reclassifies to `rejected` — uncharged, retryable.
    """
    from syndicate.features.shared import execution_ledger as mod

    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "1")

    def dead_route(_request):
        raise RuntimeError("boom")

    request = _request(position_key="gone-410")
    record = mod.place_order(request, submit=dead_route, mode=mod.LIVE)
    mod.complete_order(
        record["idempotency_key"],
        status=mod.STATUS_FAILED,
        error=(
            'KalshiAuthError: http_410: .../portfolio/orders: '
            '{"error":{"code":"deprecated_v1_order_endpoint"}}'
        ),
    )

    assert mod.reclassify_presend_failures()["reclassified"] >= 1
    assert mod.find_order(record["idempotency_key"])["status"] == mod.STATUS_REJECTED


def test_a_server_error_is_NOT_reclassified(monkeypatch):
    """A 500 may well have been processed. Only the deprecated-endpoint 410 is
    proof of non-delivery; anything else keeps the conservative reading."""
    from syndicate.features.shared import execution_ledger as mod

    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "1")

    def boom(_request):
        raise RuntimeError("x")

    request = _request(position_key="keep-500")
    record = mod.place_order(request, submit=boom, mode=mod.LIVE)
    mod.complete_order(
        record["idempotency_key"],
        status=mod.STATUS_FAILED,
        error="KalshiAuthError: http_500: internal error",
    )

    mod.reclassify_presend_failures()
    assert mod.find_order(record["idempotency_key"])["status"] == mod.STATUS_FAILED


def test_a_rejected_order_can_be_retried(monkeypatch):
    """MEASURED 2026-08-24T12:46Z. The dead-route 410 was correctly
    reclassified `rejected` and its $1.58 released — and the next tick still
    said `placed=0 duplicates=1`, because the RECORD still existed and
    `record_order` returned created=False.

    Freeing the budget without freeing the retry is half a fix: the order could
    never be placed again, on a route that now works.
    """
    from syndicate.features.shared import execution_ledger as mod

    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "1")

    request = _request(position_key="retry-me")
    first = mod.place_order(request, submit=lambda _r: (_ for _ in ()).throw(RuntimeError("x")), mode=mod.LIVE)
    mod.complete_order(first["idempotency_key"], status=mod.STATUS_REJECTED, error="dead route")

    calls = []

    def submit(_request):
        calls.append(1)
        return {"status": "filled", "fill_price": 0.4, "fill_stake_dollars": 4.8}

    second = mod.place_order(request, submit=submit, mode=mod.LIVE)
    assert calls, "a rejected order must reach the venue on a retry"
    assert second["status"] == mod.STATUS_FILLED


def test_a_filled_order_is_never_retried(monkeypatch):
    """The whole point of the idempotency key. `filled`, `submitted` and
    `failed` all mean the venue may hold this order — re-sending any of them is
    how one bet becomes two."""
    from syndicate.features.shared import execution_ledger as mod

    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "1")

    request = _request(position_key="no-retry")
    mod.place_order(
        request,
        submit=lambda _r: {"status": "filled", "fill_price": 0.4, "fill_stake_dollars": 4.8},
        mode=mod.LIVE,
    )

    calls = []
    mod.place_order(request, submit=lambda _r: calls.append(1), mode=mod.LIVE)
    assert not calls, "a filled order must never be re-sent"


def test_a_failed_order_is_never_retried(monkeypatch):
    """`failed` means the submit raised and MAY have arrived. Conservative by
    construction — only an explicit reclassification can free it."""
    from syndicate.features.shared import execution_ledger as mod

    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "1")

    request = _request(position_key="failed-stays")

    def boom(_r):
        raise RuntimeError("connection reset mid-POST")

    mod.place_order(request, submit=boom, mode=mod.LIVE)

    calls = []
    mod.place_order(request, submit=lambda _r: calls.append(1), mode=mod.LIVE)
    assert not calls


# --------------------------------------------------------------------------
# Reconciliation: the venue is the authority on our own ledger
# --------------------------------------------------------------------------


def _live_order(mod, monkeypatch, *, key: str, status: str, **fields):
    """A live order in the ledger, forced into a given post-submit state."""
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "1")
    request = _request(position_key=key, venue="kalshi", venue_ticker="KX-TEST-1")
    record, _ = mod.record_order(request, mode=mod.LIVE)
    mod.complete_order(record["idempotency_key"], status=status, **fields)
    return record["idempotency_key"]


def _reader(orders, *, ok: bool = True):
    """Stand in for the Kalshi read side, in the shape `_venue_reader` returns."""
    from syndicate.features.shared.kalshi_orders import venue_order_view

    def fetch(*, limit=100):
        if not ok:
            return {"status": "error", "reason": "KalshiAuthError: http_503"}
        return {"status": "ok", "orders": list(orders)}

    return fetch, venue_order_view


def test_a_phantom_fill_is_corrected_to_submitted(monkeypatch):
    """MEASURED 2026-08-24T13:12Z, and found by the USER looking at the Kalshi
    UI rather than by any log. Our ledger read `filled` at $0.54 for an order
    Kalshi showed as resting with `Filled: 0` -- a position we booked, graded
    and would have reported P&L on, and never held."""
    from syndicate.features.shared import execution_ledger as mod

    key = _live_order(
        mod, monkeypatch, key="phantom", status=mod.STATUS_FILLED,
        fill_price=0.54, fill_stake_dollars=1.08, venue_order_id="ord-1",
    )
    monkeypatch.setattr(
        mod, "_venue_reader",
        lambda venue: _reader([{"order_id": "ord-1", "client_order_id": key,
                                "status": "resting", "filled_count": 0,
                                "remaining_count": 2, "initial_count": 2}]),
    )

    result = mod.reconcile_live_orders()
    assert result["changed"] == 1

    fixed = mod.find_order(key)
    assert fixed["status"] == mod.STATUS_SUBMITTED
    # Every fill field is a number nobody should believe, so none survives.
    assert fixed["fill_price"] is None
    assert fixed["fill_stake_dollars"] is None
    assert fixed["contracts"] == 0
    assert fixed["reconciled_from"] == mod.STATUS_FILLED


def test_a_resting_order_that_filled_later_is_booked(monkeypatch):
    """The mirror image, and the one the submit path can NEVER catch: the
    response was written before the fill happened. Without this read the
    position is real and invisible for its whole life."""
    from syndicate.features.shared import execution_ledger as mod

    key = _live_order(mod, monkeypatch, key="late-fill", status=mod.STATUS_SUBMITTED,
                      venue_order_id="ord-2")
    monkeypatch.setattr(
        mod, "_venue_reader",
        lambda venue: _reader([{"order_id": "ord-2", "client_order_id": key,
                                "status": "executed", "filled_count": 2,
                                "average_fill_price": 44}]),
    )

    assert mod.reconcile_live_orders()["changed"] == 1
    filled = mod.find_order(key)
    assert filled["status"] == mod.STATUS_FILLED
    assert filled["contracts"] == 2
    # 44 arrived as CENTS and must be booked as $0.44 -- the 100x error
    # `kalshi_client`'s first live run found on the market read.
    assert filled["fill_price"] == 0.44
    assert filled["fill_stake_dollars"] == 0.88


def test_a_cancelled_order_frees_its_budget(monkeypatch):
    """Cancelled with nothing filled is no exposure and no position, so the
    idempotency key is free again and `rejected` is the status that says so."""
    from syndicate.features.shared import execution_ledger as mod

    key = _live_order(mod, monkeypatch, key="cancelled", status=mod.STATUS_SUBMITTED,
                      venue_order_id="ord-3")
    monkeypatch.setattr(
        mod, "_venue_reader",
        lambda venue: _reader([{"order_id": "ord-3", "client_order_id": key,
                                "status": "canceled", "filled_count": 0}]),
    )

    assert mod.reconcile_live_orders()["changed"] == 1
    assert mod.find_order(key)["status"] == mod.STATUS_REJECTED


def test_a_partial_fill_that_was_cancelled_is_still_a_fill(monkeypatch):
    """The cancelled status describes the REMAINDER. The contracts that traded
    are a position we hold, and reading the status before the count is how a
    real position gets reconciled away to zero."""
    from syndicate.features.shared import execution_ledger as mod

    key = _live_order(mod, monkeypatch, key="partial", status=mod.STATUS_SUBMITTED,
                      venue_order_id="ord-4")
    monkeypatch.setattr(
        mod, "_venue_reader",
        lambda venue: _reader([{"order_id": "ord-4", "client_order_id": key,
                                "status": "canceled", "filled_count": 1,
                                "average_fill_price": 0.46}]),
    )

    assert mod.reconcile_live_orders()["changed"] == 1
    row = mod.find_order(key)
    assert row["status"] == mod.STATUS_FILLED
    assert row["contracts"] == 1


def test_a_failed_read_changes_nothing(monkeypatch):
    """Absence in a FAILED read is not absence at the venue, and the difference
    is a live position deleted out of our own books."""
    from syndicate.features.shared import execution_ledger as mod

    key = _live_order(mod, monkeypatch, key="unreachable", status=mod.STATUS_FILLED,
                      fill_price=0.46, fill_stake_dollars=0.92, venue_order_id="ord-5")
    monkeypatch.setattr(mod, "_venue_reader", lambda venue: _reader([], ok=False))

    result = mod.reconcile_live_orders()
    assert result["status"] == "error"
    assert result["changed"] == 0
    assert mod.find_order(key)["status"] == mod.STATUS_FILLED
    assert mod.find_order(key)["fill_price"] == 0.46


def test_an_order_missing_from_the_list_is_left_alone(monkeypatch):
    """The list is capped, so an older order legitimately ages out of it.
    Only a POSITIVE statement about a specific order may move that order."""
    from syndicate.features.shared import execution_ledger as mod

    key = _live_order(mod, monkeypatch, key="aged-out", status=mod.STATUS_FILLED,
                      fill_price=0.46, fill_stake_dollars=0.92, venue_order_id="ord-6")
    monkeypatch.setattr(
        mod, "_venue_reader",
        lambda venue: _reader([{"order_id": "someone-else", "client_order_id": "other",
                                "status": "resting"}]),
    )

    result = mod.reconcile_live_orders()
    assert result["not_found"] == 1
    assert result["changed"] == 0
    assert mod.find_order(key)["status"] == mod.STATUS_FILLED


def test_an_unmapped_venue_status_is_not_guessed(monkeypatch):
    """A status we have never seen is not evidence in either direction.
    Guessing is precisely what produced the phantom fill."""
    from syndicate.features.shared import execution_ledger as mod

    key = _live_order(mod, monkeypatch, key="strange", status=mod.STATUS_SUBMITTED,
                      venue_order_id="ord-7")
    monkeypatch.setattr(
        mod, "_venue_reader",
        lambda venue: _reader([{"order_id": "ord-7", "client_order_id": key,
                                "status": "quantum_superposition"}]),
    )

    result = mod.reconcile_live_orders()
    assert result["unknown"] == 1
    assert result["changed"] == 0
    assert mod.find_order(key)["status"] == mod.STATUS_SUBMITTED


def test_reconciliation_is_idempotent(monkeypatch):
    """It runs on every refresh tick, so a second pass over unchanged orders
    must report zero -- otherwise 'did anything move' is unanswerable."""
    from syndicate.features.shared import execution_ledger as mod

    key = _live_order(mod, monkeypatch, key="steady", status=mod.STATUS_SUBMITTED,
                      venue_order_id="ord-8")
    monkeypatch.setattr(
        mod, "_venue_reader",
        lambda venue: _reader([{"order_id": "ord-8", "client_order_id": key,
                                "status": "resting", "filled_count": 0}]),
    )

    mod.reconcile_live_orders()
    assert mod.reconcile_live_orders()["changed"] == 0


def test_paper_orders_are_never_reconciled(monkeypatch):
    """There is no venue to ask."""
    from syndicate.features.shared import execution_ledger as mod

    request = _request(position_key="paper-1", venue="kalshi")
    record, _ = mod.record_order(request, mode=mod.PAPER)
    monkeypatch.setattr(
        mod, "_venue_reader",
        lambda venue: _reader([{"order_id": "x", "client_order_id": record["idempotency_key"],
                                "status": "executed", "filled_count": 9}]),
    )

    assert mod.reconcile_live_orders()["candidates"] == 0
    assert mod.find_order(record["idempotency_key"])["status"] == mod.STATUS_SUBMITTED


# --------------------------------------------------------------------------
# The stranded-order gate, after reconciliation exists
# --------------------------------------------------------------------------


def test_a_known_resting_order_does_not_block_the_next_run(monkeypatch):
    """`submitted` carries two meanings. 'We do not know what happened' must
    block a new live slate; 'it is sitting on the book unfilled, we just asked'
    must not, or the first limit order that rests for an afternoon jams live
    execution until someone hand-edits the ledger."""
    from syndicate.features.shared import execution_ledger as mod

    key = _live_order(mod, monkeypatch, key="known-resting", status=mod.STATUS_SUBMITTED,
                      venue_order_id="ord-9")
    assert [o["idempotency_key"] for o in mod.unreconciled_orders()] == [key]

    monkeypatch.setattr(
        mod, "_venue_reader",
        lambda venue: _reader([{"order_id": "ord-9", "client_order_id": key,
                                "status": "resting", "filled_count": 0}]),
    )
    mod.reconcile_live_orders()

    assert mod.unreconciled_orders() == []


def test_a_stale_reconciliation_blocks_again(monkeypatch):
    """A reading from yesterday says nothing about now. Blocking is the safe
    direction and stays the default for anything this cannot account for."""
    from syndicate.features.shared import execution_ledger as mod

    key = _live_order(mod, monkeypatch, key="stale", status=mod.STATUS_SUBMITTED,
                      venue_order_id="ord-10")
    monkeypatch.setattr(
        mod, "_venue_reader",
        lambda venue: _reader([{"order_id": "ord-10", "client_order_id": key,
                                "status": "resting", "filled_count": 0}]),
    )
    mod.reconcile_live_orders()
    assert mod.unreconciled_orders() == []

    monkeypatch.setenv("SYNDICATE_EXECUTION_RECONCILE_FRESH_SECONDS", "0.0001")
    assert [o["idempotency_key"] for o in mod.unreconciled_orders()] == [key]


def test_an_unreconciled_order_still_blocks(monkeypatch):
    """The property the gate exists for, unchanged: a submit with no venue
    reading behind it risks doubling and must stop the run."""
    from syndicate.features.shared import execution_ledger as mod

    key = _live_order(mod, monkeypatch, key="never-read", status=mod.STATUS_SUBMITTED)
    assert [o["idempotency_key"] for o in mod.unreconciled_orders()] == [key]
