"""Kalshi fills are read at their TRUE size: a fraction of a contract is a fill, not zero (todo #783).

MEASURED 2026-11-11 (lane `kalshi-fractional-fills`). `venue_order_view` read `fill_count_fp` through
`_int_or_none`, and `int(float('0.01'))` is 0. Since 2026-10-25: 7 live take-profit exits recorded `dead` / 0
and 10 live entries recorded `rejected` with a real fill; entry `f67174cb` filled 1.06 is recorded 1. The order
below is take-profit exit `x403f59b5` (venue order `01a17426`, 17:41:00Z 10-25), reproduced from Kalshi's own
fill: 0.01 YES @ 0.42, fee $0.0002, the rest cancelled.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import kalshi_orders as ko

MEASURED_SLIVER = {
    "order_id": "01a17426-c3e0-7b31-8d51-dfce681519a8",
    "status": "canceled",
    "fill_count_fp": "0.01",
    "remaining_count_fp": "0.00",
    "initial_count_fp": "1.00",
    "taker_fill_cost_dollars": "0.004200",
    "taker_fees_dollars": "0.000200",
    "yes_price_dollars": "0.4200",
}


@pytest.fixture(autouse=True)
def _default_switch(monkeypatch):
    monkeypatch.delenv(ko.FRACTIONAL_COUNTS_ENV, raising=False)


def test_the_measured_sliver_is_a_fill():
    view = ko.venue_order_view(MEASURED_SLIVER)
    assert view["state"] == "filled", "a filled-then-cancelled sliver is a position, not a dead order"
    assert view["filled_count"] == pytest.approx(0.01)
    assert view["fill_price"] == pytest.approx(0.42)
    assert view["fees_dollars"] == pytest.approx(0.0002)
    assert view["open_at_venue"] is False


def test_off_restores_the_truncation_that_lost_it():
    """Reachability: off != on. Off is the measured defect, exactly."""
    import os

    os.environ[ko.FRACTIONAL_COUNTS_ENV] = "off"
    try:
        view = ko.venue_order_view(MEASURED_SLIVER)
    finally:
        del os.environ[ko.FRACTIONAL_COUNTS_ENV]
    assert view["state"] == "dead" and view["filled_count"] == 0


def test_whole_counts_stay_ints_so_whole_contract_rows_are_unchanged():
    view = ko.venue_order_view({**MEASURED_SLIVER, "status": "executed", "fill_count_fp": "3.00",
                                "taker_fill_cost_dollars": "1.260000"})
    assert view["filled_count"] == 3 and isinstance(view["filled_count"], int)
    assert view["fill_price"] == pytest.approx(0.42)


@pytest.mark.parametrize("order, expected", [
    ({"status": "canceled", "initial_count_fp": "1.00", "remaining_count_fp": "0.99"}, 0.01),
    ({"status": "canceled", "taker_fill_count": "0.55", "maker_fill_count": "0"}, 0.55),
    ({"status": "executed", "fill_count_fp": "1.06"}, 1.06),
])
def test_every_count_route_keeps_the_fraction(order, expected):
    view = ko.venue_order_view(order)
    assert view["state"] == "filled" and view["filled_count"] == pytest.approx(expected)


@pytest.mark.parametrize("raw", [None, "", "abc", "nan", "inf"])
def test_an_unreadable_count_is_none_not_zero(raw):
    assert ko._count_or_none(raw) is None


def test_the_submit_response_keeps_a_sliver_and_its_stake():
    class Req:
        pass

    out = ko._order_result(Req(), {"count": "1.00"}, {"order": {"status": "canceled", "filled_count": "0.01",
                                                                 "order_id": "o1"}}, price_dollars=0.42)
    assert out["status"] == "filled" and out["contracts"] == pytest.approx(0.01)
    assert out["fill_stake_dollars"] == pytest.approx(0.0042), "0.01 x $0.42 is not $0.00"
    whole = ko._order_result(Req(), {"count": "2.00"}, {"order": {"status": "executed", "filled_count": 2,
                                                                   "order_id": "o2"}}, price_dollars=0.457)
    assert whole["contracts"] == 2 and whole["fill_stake_dollars"] == 0.91, "whole contracts still round to cents"


def test_the_reconciler_books_a_partly_filled_resting_order_at_its_true_size(monkeypatch):
    """Entry `91822817` (11-08): 0.03 filled, the rest still resting, and the ledger said `submitted`."""
    from syndicate.features.shared import execution_ledger as el
    from tests.test_execution_ledger import _live_order, _reader

    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(__import__("tempfile").mkdtemp()))
    key = _live_order(el, monkeypatch, key="sliver-entry", status=el.STATUS_SUBMITTED, venue_order_id="ord-r")
    book = [{"client_order_id": key, "order_id": "ord-r", "status": "resting", "fill_count_fp": "0.03",
             "remaining_count_fp": "0.97", "initial_count_fp": "1.00", "taker_fill_cost_dollars": "0.020100",
             "taker_fees_dollars": "0.001000", "yes_price_dollars": "0.6700"}]
    fetch, view, _c = _reader(book)
    monkeypatch.setattr(el, "_venue_reader", lambda venue: (fetch, view, "book"))
    el.reconcile_live_orders()
    row = el.find_order(key)
    assert row["status"] == el.STATUS_FILLED
    assert row["contracts"] == pytest.approx(0.03)
    assert row["fill_stake_dollars"] == pytest.approx(0.0201)
    assert row["venue_open"] is True, "the remainder is still working at the venue"


# --------------------------------------------------------------------------
# scripts/kalshi_fractional_repair.py -- old rows rebuilt from Kalshi's own fills.
# --------------------------------------------------------------------------


def _fills_get(fills):
    def get(path):
        assert path.startswith("/portfolio/fills"), path
        return {"fills": fills, "cursor": ""}
    return get


ENTRY_FILL = {"order_id": "ord-e", "count_fp": "0.55", "side": "yes", "action": "buy", "yes_price_dollars": "0.4500",
              "no_price_dollars": "0.5500", "fee_cost": "0.010000", "created_time": "2026-10-27T00:39:04Z"}
EXIT_FILL = {"order_id": "ord-x", "count_fp": "0.01", "side": "yes", "action": "buy", "yes_price_dollars": "0.4200",
             "no_price_dollars": "0.5800", "fee_cost": "0.000200", "created_time": "2026-10-25T17:41:00Z"}
WHOLE_FILL = {"order_id": "ord-w", "count_fp": "2.00", "yes_price_dollars": "0.5", "no_price_dollars": "0.5"}


def _rows():
    entry = {"idempotency_key": "e" * 24, "mode": "live", "venue": "kalshi", "status": "rejected", "contracts": 0,
             "venue_order_id": "ord-e", "side": "yes", "market": "h2h", "line": None, "error": "venue_canceled"}
    graded = {"idempotency_key": "g" * 24, "mode": "live", "venue": "kalshi", "status": "filled", "contracts": 1,
              "venue_order_id": "ord-g", "side": "no", "market": "h2h", "outcome": "won"}
    exit_row = {"exit_key": "x" + "1" * 23, "entry_key": "9" * 24, "mode": "live", "status": "dead",
                "filled_contracts": 0, "leg": "no", "venue_order_id": "ord-x", "ticker": "KX-T", "selected_date": "2026-10-25"}
    return entry, graded, exit_row


def test_repair_plan_rebuilds_rows_from_the_fills_and_leaves_the_rest(monkeypatch):
    from scripts import kalshi_fractional_repair as tool

    entry, graded, exit_row = _rows()
    fills = [ENTRY_FILL, EXIT_FILL, WHOLE_FILL, {**ENTRY_FILL, "order_id": "ord-g", "count_fp": "1.06"},
             {**ENTRY_FILL, "order_id": "ord-manual", "count_fp": "53.87"}]
    out = tool.plan(get=_fills_get(fills), orders=[entry, graded], exit_rows={"ord-x": ("archive", exit_row)})
    assert out["fractional_orders"] == 4, "whole-contract orders are not candidates"
    [e] = out["entries"]
    assert e["key"] == "e" * 24 and e["set"]["status"] == "filled"
    assert e["set"]["contracts"] == pytest.approx(0.55) and e["set"]["fill_price"] == pytest.approx(0.45)
    assert e["set"]["fill_stake_dollars"] == pytest.approx(0.2475) and e["set"]["fees_dollars"] == pytest.approx(0.01)
    assert e["from"]["status"] == "rejected" and e["fills"][0]["order_id"] == "ord-e"
    [x] = out["exits"]
    assert x["where"] == "archive" and x["set"]["filled_contracts"] == pytest.approx(0.01)
    assert x["set"]["fill_price"] == pytest.approx(0.58), "the NO we held sold at 1 - 0.42"
    assert [l["why"] for l in out["left"]] == ["graded:won"]
    assert out["not_ours"] == 1


def test_repair_apply_refuses_before_the_aged_out_fix_is_loaded(monkeypatch):
    from scripts import kalshi_fractional_repair as tool
    from syndicate.features.shared import execution_ledger as el

    monkeypatch.delattr(el, "_venue_terminal_fill", raising=False)
    with pytest.raises(SystemExit, match="kalshi-aged-out-grade"):
        tool.apply({"entries": [], "exits": []}, note="x", settle_seconds=0)


def test_repair_apply_writes_entries_archive_and_document_with_an_audit(monkeypatch, tmp_path):
    from scripts import kalshi_fractional_repair as tool
    from syndicate.features.shared import execution_exits as ee
    from syndicate.features.shared import execution_ledger as el
    from tests.test_execution_ledger import _live_order

    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.setattr(el, "_venue_terminal_fill", lambda order: False, raising=False)
    key = _live_order(el, monkeypatch, key="frac-entry", status=el.STATUS_REJECTED, venue_order_id="ord-e")
    state = el._load()
    for order in state["orders"]:
        if order["idempotency_key"] == key:
            order.update(side="yes", market="h2h", line=None, contracts=0)
    el._persist(state)
    _entry, _graded, exit_row = _rows()
    ee._archive([exit_row], prefix="exits")
    doc_row = {**exit_row, "exit_key": "x" + "2" * 23, "venue_order_id": "ord-d"}
    ee._persist({"version": 1, "watch": {}, "exits": {doc_row["exit_key"]: doc_row}})

    fills = [{**ENTRY_FILL}, EXIT_FILL, {**EXIT_FILL, "order_id": "ord-d"}]
    the_plan = tool.plan(get=_fills_get(fills))
    assert [i["key"] for i in the_plan["entries"]] == [key]
    assert sorted(i["where"] for i in the_plan["exits"]) == ["archive", "document"]

    done = tool.apply(the_plan, note="user yes", settle_seconds=0)
    assert done == {"entries": 1, "exits_archive": 1, "exits_document": 1, "exits_document_reapplied": 0}
    row = el.find_order(key)
    assert row["status"] == "filled" and row["contracts"] == pytest.approx(0.55)
    assert row["fractional_repair"]["from"]["status"] == "rejected" and row["fractional_repair"]["note"] == "user yes"
    archived = {r["exit_key"]: r for r in ee.archived_exit_rows()}[exit_row["exit_key"]]
    assert archived["status"] == "filled" and archived["filled_contracts"] == pytest.approx(0.01)
    doc = ee.load_state()["exits"][doc_row["exit_key"]]
    assert doc["status"] == "filled" and doc["fractional_repair"]["from"]["status"] == "dead"
    assert tool.plan(get=_fills_get(fills))["entries"] == [], "a second run finds nothing left to repair"
