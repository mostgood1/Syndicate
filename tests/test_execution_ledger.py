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

    def fetch(*, limit=100, order_ids=None):
        # `order_ids` is part of the reader contract: Kalshi lists the whole
        # book and ignores it, Polymarket has no list of settled orders and
        # reads one at a time by id. Accepted here so this stand-in matches the
        # real signature rather than the one it wishes existed.
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


# --------------------------------------------------------------------------
# Fees, and the bound that makes an undocumented count unit safe
# --------------------------------------------------------------------------


def _kalshi_order(mod, monkeypatch, *, key: str, price: float, stake: float):
    """A live order priced the way Kalshi prices -- probability dollars."""
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "1")
    request = _request(
        position_key=key, venue="kalshi", venue_ticker="KX-TEST-1",
        requested_price=price, requested_stake_dollars=stake,
    )
    record, _ = mod.record_order(request, mode=mod.LIVE)
    return record["idempotency_key"]


def test_fees_reach_the_ledger_from_the_venue(monkeypatch):
    """Kalshi took $0.02 on a $1.08 fill -- ~1.9%, against edges this system
    will act on at 3%. They arrive on every order read; the only reason they
    were absent is that nothing carried them across."""
    from syndicate.features.shared import execution_ledger as mod

    key = _kalshi_order(mod, monkeypatch, key="fees", price=0.54, stake=1.58)
    monkeypatch.setattr(
        mod, "_venue_reader",
        lambda venue: _reader([{"order_id": "ord-f", "client_order_id": key,
                                "status": "executed", "fill_count_fp": 2,
                                "taker_fill_cost_dollars": 1.08,
                                "taker_fees_dollars": 0.02}]),
    )

    assert mod.reconcile_live_orders()["changed"] == 1
    row = mod.find_order(key)
    assert row["fees_dollars"] == 0.02
    # The venue's own charge, not our count * price reconstruction.
    assert row["fill_stake_dollars"] == 1.08


def test_a_fill_larger_than_the_order_is_refused(monkeypatch):
    """`fill_count_fp` carries an undocumented `_fp`. If it is a fixed-point
    scale, a 2-contract fill arrives as some large number and booking it claims
    a position orders of magnitude beyond what the stake could buy. No venue
    can fill more than was asked, so this is a PARSE failure, never a trade."""
    from syndicate.features.shared import execution_ledger as mod

    key = _kalshi_order(mod, monkeypatch, key="scaled", price=0.54, stake=1.58)
    monkeypatch.setattr(
        mod, "_venue_reader",
        lambda venue: _reader([{"order_id": "ord-s", "client_order_id": key,
                                "status": "executed", "fill_count_fp": 2_000_000}]),
    )

    result = mod.reconcile_live_orders()
    assert result["implausible"] == 1
    assert result["changed"] == 0
    # Left untouched -- not booked, and not silently zeroed either.
    assert mod.find_order(key)["status"] == mod.STATUS_SUBMITTED


def test_a_fill_within_the_order_is_booked(monkeypatch):
    """The bound must not refuse honest fills: $1.58 at $0.54 buys 2."""
    from syndicate.features.shared import execution_ledger as mod

    key = _kalshi_order(mod, monkeypatch, key="bounded", price=0.54, stake=1.58)
    monkeypatch.setattr(
        mod, "_venue_reader",
        lambda venue: _reader([{"order_id": "ord-b", "client_order_id": key,
                                "status": "executed", "fill_count_fp": 2,
                                "taker_fill_cost_dollars": 1.08}]),
    )

    assert mod.reconcile_live_orders()["changed"] == 1
    assert mod.find_order(key)["contracts"] == 2


def test_fees_are_charged_against_the_daily_budget(monkeypatch):
    """A cap that counts only stake is a cap the account can exceed."""
    from syndicate.features.shared import execution_guard as guard
    from syndicate.features.shared import execution_ledger as mod

    key = _kalshi_order(mod, monkeypatch, key="budget", price=0.54, stake=1.58)
    mod.complete_order(key, status=mod.STATUS_FILLED, fill_stake_dollars=1.08)
    spent = guard.spent_today("2026-08-22", mode=mod.LIVE)
    assert spent["dollars"] == 1.08

    monkeypatch.setattr(
        mod, "_venue_reader",
        lambda venue: _reader([{"order_id": "ord-g", "client_order_id": key,
                                "status": "executed", "fill_count_fp": 2,
                                "taker_fill_cost_dollars": 1.08,
                                "taker_fees_dollars": 0.02}]),
    )
    mod.reconcile_live_orders()
    assert guard.spent_today("2026-08-22", mode=mod.LIVE)["dollars"] == 1.10


def test_an_unchanged_order_is_still_marked_as_read(monkeypatch):
    """MEASURED 2026-08-24T15:04:08Z. The first version persisted only when
    something MOVED, so `reconciled_at` was discarded in exactly the steady
    state it exists for: a resting order read successfully, agreeing with the
    ledger, and therefore never marked as read. `RECONCILE ... changed=0` and
    `BLOCKED_ON_UNRECONCILED count=1` fired in the same second on the same
    order, and live execution stayed jammed.

    'Nothing changed' and 'nothing was learned' are different facts."""
    from syndicate.features.shared import execution_ledger as mod

    key = _live_order(mod, monkeypatch, key="steady-stamp", status=mod.STATUS_SUBMITTED,
                      venue_order_id="ord-11")
    monkeypatch.setattr(
        mod, "_venue_reader",
        lambda venue: _reader([{"order_id": "ord-11", "client_order_id": key,
                                "status": "resting", "fill_count_fp": 0}]),
    )

    # First pass settles the row into the steady state. The SECOND is the one
    # production was stuck in: read, agreed, and dropped on the floor.
    mod.reconcile_live_orders()
    monkeypatch.setenv("SYNDICATE_EXECUTION_RECONCILE_FRESH_SECONDS", "0.0001")
    assert [o["idempotency_key"] for o in mod.unreconciled_orders()] == [key]

    monkeypatch.delenv("SYNDICATE_EXECUTION_RECONCILE_FRESH_SECONDS")
    result = mod.reconcile_live_orders()
    assert result["changed"] == 0
    assert result["stamped"] == 1
    # The stamp survived the write, which is the whole point.
    assert mod.find_order(key)["reconciled_at"] is not None
    assert mod.unreconciled_orders() == []


def test_a_row_nothing_could_be_said_about_is_not_stamped(monkeypatch):
    """`not_found` and `unknown` learn nothing, so they must not refresh the
    freshness stamp -- that would turn 'we could not read it' into 'we read it
    and it is fine', which is how a stranded order stops blocking without
    anyone having checked it."""
    from syndicate.features.shared import execution_ledger as mod

    key = _live_order(mod, monkeypatch, key="silent", status=mod.STATUS_SUBMITTED,
                      venue_order_id="ord-12")
    monkeypatch.setattr(
        mod, "_venue_reader",
        lambda venue: _reader([{"order_id": "ord-12", "client_order_id": key,
                                "status": "quantum_superposition"}]),
    )

    assert mod.reconcile_live_orders()["stamped"] == 0
    assert [o["idempotency_key"] for o in mod.unreconciled_orders()] == [key]


# --------------------------------------------------------------------------
# Cancelling a resting order the market has left behind
# --------------------------------------------------------------------------


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _resting_row(**overrides):
    row = {
        "idempotency_key": "k1",
        "order_id": "ord-x",
        "ticker": "KXMLBKS-TEST",
        "side": "under",
        "yes_price": 0.46,
        "no_price": 0.54,
        "submitted_at": "2020-01-01T00:00:00Z",
    }
    row.update(overrides)
    return row


def _prices(monkeypatch, *, market: float | None, cancels: list):
    from syndicate.features.shared import execution_ledger as mod

    monkeypatch.setattr(
        mod, "_market_price_for_side",
        lambda ticker, side: market,
    )
    monkeypatch.setattr(
        "syndicate.features.shared.kalshi_orders.cancel_order",
        lambda order_id: (cancels.append(order_id) or {"status": "ok", "order": {}}),
    )


def test_a_stale_resting_order_is_cancelled(monkeypatch):
    """MEASURED 2026-08-24: the Zebby Matthews order rested from ~12:58Z at
    $0.54 for NO while the market moved to $0.56. It could not fill and held
    its own idempotency key hostage, so the marketable-limit path could not
    re-place it either."""
    from syndicate.features.shared import execution_ledger as mod

    cancels = []
    _prices(monkeypatch, market=0.56, cancels=cancels)

    result = mod.cancel_stale_resting_orders([_resting_row()])
    assert result["cancelled"] == 1
    assert cancels == ["ord-x"]


def test_a_young_order_is_left_to_work(monkeypatch):
    """A limit that has not filled is not automatically wrong -- that is what a
    limit is for. Cancelling on the first tick would churn the book and never
    let a good price come to us."""
    from syndicate.features.shared import execution_ledger as mod

    cancels = []
    _prices(monkeypatch, market=0.56, cancels=cancels)

    result = mod.cancel_stale_resting_orders([_resting_row(submitted_at=_now_iso())])
    assert result["cancelled"] == 0
    assert result["too_young"] == 1
    assert cancels == []


def test_an_order_still_at_the_market_is_left_alone(monkeypatch):
    """Age alone is not staleness. An old order at a price that still exists
    can still fill."""
    from syndicate.features.shared import execution_ledger as mod

    cancels = []
    _prices(monkeypatch, market=0.54, cancels=cancels)

    result = mod.cancel_stale_resting_orders([_resting_row()])
    assert result["at_market"] == 1
    assert cancels == []


def test_no_price_means_no_cancel(monkeypatch):
    """Cancelling on an unreadable price is acting on the ABSENCE of
    information, which is the failure this whole layer keeps refusing."""
    from syndicate.features.shared import execution_ledger as mod

    cancels = []
    _prices(monkeypatch, market=None, cancels=cancels)

    result = mod.cancel_stale_resting_orders([_resting_row()])
    assert result["unreadable"] == 1
    assert cancels == []


def test_a_failed_cancel_leaves_the_order_alone(monkeypatch):
    """The order is still resting and can still fill. Marking it dead would
    free a key the venue still holds -- how one bet becomes two."""
    from syndicate.features.shared import execution_ledger as mod

    monkeypatch.setattr(mod, "_market_price_for_side", lambda ticker, side: 0.56)
    monkeypatch.setattr(
        "syndicate.features.shared.kalshi_orders.cancel_order",
        lambda order_id: {"status": "error", "reason": "KalshiAuthError: http_410"},
    )

    result = mod.cancel_stale_resting_orders([_resting_row()])
    assert result["failed"] == 1
    assert result["cancelled"] == 0


def test_the_cancel_pass_is_bounded(monkeypatch):
    """A bad rule must not empty the book before anyone reads a log."""
    from syndicate.features.shared import execution_ledger as mod

    cancels = []
    _prices(monkeypatch, market=0.56, cancels=cancels)
    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_CANCELS", "2")

    rows = [_resting_row(idempotency_key=f"k{i}", order_id=f"ord-{i}") for i in range(5)]
    assert mod.cancel_stale_resting_orders(rows)["cancelled"] == 2
    assert len(cancels) == 2


def test_the_side_decides_which_leg_is_ours():
    """Kalshi hands over both legs; which one we are paying depends on our
    side, and reading the wrong one compares a price to its own complement."""
    from syndicate.features.shared.execution_ledger import _resting_price_for_side

    assert _resting_price_for_side(_resting_row(side="under")) == 0.54
    assert _resting_price_for_side(_resting_row(side="over")) == 0.46


def test_the_ledger_is_not_written_by_the_cancel(monkeypatch):
    """The next reconciliation pass reads the venue, sees `canceled`, and moves
    the row through the one path allowed to change a status -- the venue's own
    word. Writing it here would be believing our own API call over the book."""
    from syndicate.features.shared import execution_ledger as mod

    key = _live_order(mod, monkeypatch, key="uncancelled", status=mod.STATUS_SUBMITTED,
                      venue_order_id="ord-c")
    cancels = []
    _prices(monkeypatch, market=0.56, cancels=cancels)

    mod.cancel_stale_resting_orders([_resting_row(idempotency_key=key, order_id="ord-c")])
    assert mod.find_order(key)["status"] == mod.STATUS_SUBMITTED


# --------------------------------------------------------------------------
# The reconciliation latch: a venue with no reader can never be cleared
# --------------------------------------------------------------------------


def test_polymarket_has_a_venue_reader():
    """A venue that can PLACE but cannot be READ is a latch, not a gap.

    `_venue_reader` said "Only Kalshi has one", so a Polymarket order recorded
    `submitted` could never be corrected -- and an unreconciled order blocks
    live mode on EVERY venue. Measured 2026-08-25T16:40:00Z, from one resting
    Polymarket order:

        BLOCKED_ON_UNRECONCILED count=1 keys=['1984a57ed28e1cd5ccad8b16']
        EXECUTION status=blocked reason=unreconciled_orders scope=kalshi
        EXECUTION status=blocked reason=unreconciled_orders scope=polymarket

    Nothing in the system could lift that, because the only thing that lifts it
    is the read that did not exist.
    """
    import syndicate.features.shared.execution_ledger as mod

    # LIVE venues only -- paper orders never reconcile (the candidate filter
    # requires mode == LIVE), so a paper book needs no reader.
    for venue in ("polymarket", "kalshi"):
        fetch, view = mod._venue_reader(venue)
        assert fetch is not None, f"{venue} can be placed on but never reconciled"
        assert view is not None


def test_every_venue_we_can_place_on_can_also_be_read():
    """The invariant behind the test above, stated once so a THIRD venue cannot
    reintroduce the latch by being added to the submit side alone."""
    import pipeline.execute_portfolio as runner
    import syndicate.features.shared.execution_ledger as mod

    for venue in ("kalshi", "polymarket"):
        if runner._venue_submitter(venue) is None:
            continue
        fetch, _ = mod._venue_reader(venue)
        assert fetch is not None, f"{venue} has a submitter but no reader"


def test_a_cancelled_polymarket_order_reads_as_dead_not_unknown():
    """The user cancels at the venue; the ledger must be able to see it.

    Polymarket prefixes its enums (`ORDER_STATUS_CANCELED`), so a bare-string
    match falls through to `unknown` -- and `unknown` deliberately changes
    nothing, which would leave the order blocking live mode forever.
    """
    from syndicate.features.shared.polymarket_us_orders import venue_order_view

    for status in ("CANCELED", "ORDER_STATUS_CANCELED", "cancelled", "ORDER_STATUS_REJECTED"):
        assert venue_order_view({"status": status})["state"] == "dead", status


def test_a_partially_filled_then_cancelled_order_is_a_FILL():
    """The cancelled status describes the remainder; the contracts that traded
    are a position we hold. Size outranks status, or a real position gets
    reconciled away to zero."""
    from syndicate.features.shared.polymarket_us_orders import venue_order_view

    view = venue_order_view({"status": "ORDER_STATUS_CANCELED", "filledQuantity": "1.5"})
    assert view["state"] == "filled"
    assert view["filled_count"] == 1.5


def test_a_resting_polymarket_order_is_resting_not_dead():
    from syndicate.features.shared.polymarket_us_orders import venue_order_view

    for status in ("ORDER_STATUS_OPEN", "pending", "ORDER_STATUS_LIVE"):
        assert venue_order_view({"status": status})["state"] == "resting", status


def test_an_unmapped_polymarket_status_is_unknown_not_guessed():
    """`unknown` is a real answer. A status we have never seen must leave the
    row untouched rather than be collapsed into traded or not-traded."""
    from syndicate.features.shared.polymarket_us_orders import venue_order_view

    assert venue_order_view({"status": "ORDER_STATUS_SOMETHING_NEW"})["state"] == "unknown"


def test_a_failed_polymarket_read_is_an_error_never_an_empty_book(monkeypatch):
    """An empty `orders` on a FAILED read says "the venue holds nothing", and
    reconciliation would take that as licence to write off a live position."""
    from syndicate.features.shared import polymarket_us_auth
    from syndicate.features.shared.polymarket_us_orders import fetch_orders

    def boom(*a, **kw):
        raise RuntimeError("venue unreachable")

    monkeypatch.setattr(polymarket_us_auth, "signed_request", boom)
    result = fetch_orders()
    assert result["status"] == "error"
    assert "orders" not in result


def test_an_unrecognised_polymarket_payload_is_named_not_empty(monkeypatch):
    from syndicate.features.shared import polymarket_us_auth
    from syndicate.features.shared.polymarket_us_orders import fetch_orders

    monkeypatch.setattr(
        polymarket_us_auth, "signed_request", lambda *a, **kw: {"unexpected": []}
    )
    result = fetch_orders()
    assert result["status"] == "error"
    assert result["reason"] == "no_orders_array"


def test_the_state_field_is_what_carries_a_polymarket_order_status():
    """MEASURED 2026-08-25T17:05:58Z on the first real per-order read: the
    payload has no `status` key at all. It is `state`.

      ORDERS_READ n=1 mode=per_order asked=1 statuses=['']
        keys=[...,'cumQuantity','id','leavesQuantity','marketSlug',
              'outcomeSide','price','quantity','side','state','tif','type']

    Reading the wrong key gave `unknown`, which correctly changes nothing --
    and so the order stayed blocking live execution on both venues.
    """
    from syndicate.features.shared.polymarket_us_orders import venue_order_view

    assert venue_order_view({"state": "ORDER_STATE_CANCELED"})["state"] == "dead"
    assert venue_order_view({"state": "ORDER_STATE_OPEN"})["state"] == "resting"
    # `status` still works if the venue ever adds it -- kept, not replaced.
    assert venue_order_view({"status": "ORDER_STATUS_CANCELED"})["state"] == "dead"


def test_the_measured_polymarket_fill_fields_are_the_ones_read():
    """`cumQuantity` is cumulative filled and `avgPx` the average price, both
    from the measured key list. `leavesQuantity` is the UNFILLED remainder and
    must never be read as a fill."""
    from syndicate.features.shared.polymarket_us_orders import venue_order_view

    view = venue_order_view({
        "state": "ORDER_STATE_FILLED",
        "cumQuantity": "2.86",
        "leavesQuantity": "0",
        "avgPx": "0.495",
        "marketSlug": "aec-mlb-tex-cws-2026-08-25",
        "id": "o-1",
    })
    assert view["filled_count"] == 2.86
    assert view["fill_price"] == 0.495
    assert view["ticker"] == "aec-mlb-tex-cws-2026-08-25"
    assert view["order_id"] == "o-1"


def test_leaves_quantity_alone_is_not_a_fill():
    """A wholly unfilled resting order carries leavesQuantity == quantity. If
    that were read as a fill we would book a position we do not hold -- the
    2026-08-24 phantom fill, in a new place."""
    from syndicate.features.shared.polymarket_us_orders import venue_order_view

    view = venue_order_view({
        "state": "ORDER_STATE_OPEN", "cumQuantity": "0", "leavesQuantity": "2.86",
    })
    assert view["state"] == "resting"
    assert not view["filled_count"]


# --------------------------------------------------------------------------
# Fractional contracts: Kalshi sells whole ones, Polymarket does not
# --------------------------------------------------------------------------


def test_a_fractional_fill_books_its_real_dollar_value(monkeypatch):
    """MEASURED 2026-08-25T18:21:25Z, the first real Polymarket fill:

      RECONCILED ... submitted->filled contracts=2.65 fill_price=0.52
      EXECUTED ... spent={'dollars': 1.04}

    2.65 x 0.52 is $1.38. The reconciler computed `int(contracts) * price`,
    so `int(2.65) * 0.52` = `2 * 0.52` = 1.04 -- a 25% UNDER-count of real
    money against a daily cap, silently, on every fractional fill.

    Under-counting is the dangerous direction: the cap exists to bound what
    the account can lose, and a cap fed a number smaller than reality lets the
    account exceed it.
    """
    import syndicate.features.shared.execution_ledger as mod

    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "1")
    request = _request(position_key="frac", venue="polymarket",
                       requested_price=-108.0, requested_stake_dollars=1.38)
    record, _ = mod.record_order(request, mode=mod.LIVE)
    key = record["idempotency_key"]
    mod.complete_order(key, status=mod.STATUS_SUBMITTED, venue_order_id="o-frac")

    from syndicate.features.shared.polymarket_us_orders import venue_order_view

    def fetch(*, limit=100, order_ids=None):
        return {"status": "ok", "orders": [{
            "id": "o-frac", "state": "ORDER_STATE_FILLED",
            "cumQuantity": "2.65", "avgPx": "0.52",
            "marketSlug": "tsc-mlb-tb-det-2026-08-25-7pt5",
        }]}

    monkeypatch.setattr(mod, "_venue_reader", lambda venue: (fetch, venue_order_view))
    mod.reconcile_live_orders(venue="polymarket")

    order = mod.find_order(key)
    assert order["contracts"] == 2.65
    assert order["fill_stake_dollars"] == pytest.approx(1.38, abs=0.01)


def test_the_fill_size_bound_is_computed_for_AMERICAN_odds_too():
    """"A fill cannot be larger than the order" required `0 < price < 1` and
    returned None otherwise. Every Polymarket order carries American odds, so
    the guard was never computed on the venue we actually trade -- present,
    documented, and inert. Same shape as the slippage guard."""
    import syndicate.features.shared.execution_ledger as mod

    bound = mod._requested_contracts(
        {"requested_stake_dollars": 1.38, "requested_price": -108.0}
    )
    assert bound is not None, "the bound is still inert on American odds"
    # -108 is a 0.5192 probability, so $1.38 buys at most ~2.66 contracts --
    # which must ADMIT the real 2.65 fill rather than refuse it.
    assert bound == pytest.approx(2.66, abs=0.02)
    assert bound >= 2.65


def test_the_bound_is_unfloored_so_a_real_fractional_fill_is_not_refused():
    """`contracts_for_stake` floors to WHOLE contracts -- right for Kalshi,
    wrong here. A real 2.65 fill against a floor of 2 would be refused as
    `implausible` and left unbooked, turning a guard against phantom positions
    into a cause of missing real ones."""
    import syndicate.features.shared.execution_ledger as mod

    bound = mod._requested_contracts(
        {"requested_stake_dollars": 1.38, "requested_price": 0.52}
    )
    assert bound > 2.65


def test_an_unreadable_price_still_yields_no_bound():
    """No bound is better than a wrong one -- that reasoning was always right,
    it was the input reading that was too narrow."""
    import syndicate.features.shared.execution_ledger as mod

    for bad in (None, "", 5.0, -3.0, 0.0):
        assert mod._requested_contracts(
            {"requested_stake_dollars": 1.38, "requested_price": bad}
        ) is None, bad


def test_a_whole_contract_kalshi_fill_is_unchanged(monkeypatch):
    """The control. Kalshi sells whole contracts, so float and int agree and
    nothing about its accounting moves."""
    import syndicate.features.shared.execution_ledger as mod

    key = _live_order(mod, monkeypatch, key="whole", status=mod.STATUS_SUBMITTED,
                      venue_order_id="o-whole")
    monkeypatch.setattr(
        mod, "_venue_reader",
        lambda venue: _reader([{"order_id": "o-whole", "client_order_id": key,
                                "status": "executed", "filled_count": 3,
                                "average_fill_price": 0.50}]),
    )
    mod.reconcile_live_orders()
    assert mod.find_order(key)["fill_stake_dollars"] == pytest.approx(1.50, abs=0.01)
