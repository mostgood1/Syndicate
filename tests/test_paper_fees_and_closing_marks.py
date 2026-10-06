"""Paper P&L net of the venue's fee, and the close stamped onto each settled order.

Reachability first (CLAUDE.md "off != on"): every behaviour below is asserted
through the real seams -- `place_order`'s paper branch, `PaperLedgerBatch`, and
`settle_orders` -- not only through the helpers, because a correct helper that
nothing calls is the failure this repo names most often.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.shared import execution_ledger as ledger
from syndicate.features.shared import paper_settlement as settle
from syndicate.features.shared import venue_fees
from syndicate.features.shared.execution_ledger import (
    OrderRequest,
    PaperLedgerBatch,
    paper_fill_fee_fields,
    place_order,
)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "file")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "paper")
    (tmp_path / "intelligence").mkdir(parents=True, exist_ok=True)
    yield


DATE = "2026-10-03"


def _request(*, key="p1", book="kalshi", venue="paper", price=-110.0, stake=10.0,
             market="totals", side="over", line=8.5, ticker=None):
    return OrderRequest(
        position_key=key,
        selected_date=DATE,
        venue=venue,
        sport="mlb",
        event_id=f"evt-{key}",
        market=market,
        side=side,
        requested_price=price,
        requested_stake_dollars=stake,
        line=line,
        book=book,
        game_pk="777",
        venue_ticker=ticker,
    )


def _resolver(value):
    def resolve(_order):
        return {"current_value": value, "is_final": True, "started": True}

    return resolve


def _no_close(rows, _date):
    return {"rows": [
        {"idempotency_key": r.get("idempotency_key"), "reason": "no_close_for_market",
         "clv_pct": None, "close_price": None}
        for r in rows
    ]}


def _orders():
    return ledger._load().get("orders") or []


# --- FEES: reachability ------------------------------------------------------


def test_an_exchange_paper_fill_records_a_fee_through_place_order():
    row = place_order(_request(book="kalshi"))
    assert row["fees_dollars"] is not None and row["fees_dollars"] > 0
    assert row["fee_basis"] == "kalshi_series_from_market"
    # Persisted, not just returned.
    stored = _orders()[0]
    assert stored["fees_dollars"] == row["fees_dollars"]


def test_the_batch_paper_path_charges_the_same_fee():
    batch = PaperLedgerBatch(mode="paper")
    row = batch.place(_request(book="kalshi"))
    batch.flush()
    single = paper_fill_fee_fields(_request(book="kalshi"))
    assert row["fees_dollars"] == single["fees_dollars"] > 0
    assert _orders()[0]["fees_dollars"] == single["fees_dollars"]


def test_a_sportsbook_paper_fill_records_zero_not_none():
    row = place_order(_request(book="fanduel"))
    assert row["fees_dollars"] == 0.0
    assert row["fee_basis"] == "none"


# --- FEES: one schedule, venue_fees' own ------------------------------------


# ProphetX is not here: its fee (2% of net winnings) is charged at SETTLEMENT on a win, so a fill
# records 0.0 under `PROPHETX_SETTLEMENT_BASIS` -- see tests/test_venue_fees_prophetx_novig.py.
@pytest.mark.parametrize("book", ["kalshi", "polymarket", "novig",
                                  "fanduel", "draftkings", "betmgm", "bovada", "betrivers"])
def test_the_paper_fee_is_exactly_venue_fees_and_no_second_table(book):
    price, stake = -110.0, 10.0
    prob = ledger._price_as_probability(price)
    per_contract, basis, bound = venue_fees.taker_fee_per_contract(
        book, prob, sport="mlb", market="totals", segment=None)
    expected = venue_fees.ceil_to_fee_precision(stake / prob * per_contract) if per_contract else 0.0
    fields = paper_fill_fee_fields(_request(book=book, price=price, stake=stake))
    assert fields == {"fees_dollars": expected, "fee_basis": basis, "fee_is_upper_bound": bound}


def test_a_kalshi_mlb_total_is_charged_the_half_rate_series():
    fields = paper_fill_fee_fields(_request(book="kalshi", price=0.5, stake=10.0))
    # 20 contracts * 0.07 * 0.5 * 0.25 = 0.175
    assert fields["fees_dollars"] == pytest.approx(0.175)
    assert fields["fee_is_upper_bound"] is False


def test_a_scoped_shadow_book_takes_its_venue_from_the_prefix_when_book_is_absent():
    fields = paper_fill_fee_fields(_request(book=None, venue="paper:polymarket", price=0.5, stake=10.0))
    assert fields["fee_basis"] == "polymarket_measured_notional"
    assert fields["fees_dollars"] == pytest.approx(0.3)  # 20 contracts * 0.015


def test_an_unpriceable_fill_records_unknown_not_zero():
    fields = paper_fill_fee_fields(_request(price=5.0))  # ambiguous unit
    assert fields["fees_dollars"] is None
    assert fields["fee_basis"] == ledger.FEE_BASIS_UNPRICEABLE


# --- FEES: settlement nets them, gross stays visible ------------------------


def test_settled_exchange_pnl_is_net_of_fee_and_gross_is_kept():
    row = place_order(_request(book="kalshi", price=-110.0, stake=10.0))
    fee = row["fees_dollars"]
    settle.settle_orders(DATE, resolver=_resolver(10.0), closer=_no_close)  # over 8.5 wins
    order = _orders()[0]
    assert order["outcome"] == "won"
    assert order["pnl_gross_dollars"] == pytest.approx(9.0909, abs=1e-4)
    assert order["pnl_dollars"] == pytest.approx(order["pnl_gross_dollars"] - fee, abs=1e-4)
    assert order["pnl_dollars"] < order["pnl_gross_dollars"]


def test_settled_sportsbook_pnl_equals_gross():
    place_order(_request(book="draftkings"))
    settle.settle_orders(DATE, resolver=_resolver(2.0), closer=_no_close)  # over loses
    order = _orders()[0]
    assert order["outcome"] == "lost"
    assert order["pnl_dollars"] == order["pnl_gross_dollars"] == -10.0


def test_an_order_filled_before_the_change_is_graded_exactly_as_before():
    """A pre-change paper row carries `fees_dollars=None` and no basis. It must
    grade with no fee -- nothing retroactively charges it."""
    place_order(_request(book="kalshi"))
    state = ledger._load()
    row = state["orders"][0]
    row["fees_dollars"] = None
    row.pop("fee_basis", None)
    row.pop("fee_is_upper_bound", None)
    ledger._persist(state)
    settle.settle_orders(DATE, resolver=_resolver(10.0), closer=_no_close)
    order = _orders()[0]
    assert order["pnl_dollars"] == order["pnl_gross_dollars"]
    assert order["fees_dollars"] is None


# --- CLOSING MARK ------------------------------------------------------------


def test_default_closer_is_reached_from_settle_orders(monkeypatch):
    """off != on: with no injected closer, settlement must call the real join."""
    calls = []

    def spy(orders, *, date, **_):
        calls.append((len(orders), date))
        return {"rows": []}

    from syndicate.features.shared import order_clv

    monkeypatch.setattr(order_clv, "clv_for_orders", spy)
    place_order(_request(book="fanduel"))
    settle.settle_orders(DATE, resolver=_resolver(10.0))
    assert calls == [(1, DATE)]


def test_a_settled_order_gets_clv_when_a_close_is_available():
    place_order(_request(book="fanduel", price=-110.0))

    def closer(rows, _date):
        return {"rows": [{
            "idempotency_key": rows[0]["idempotency_key"], "reason": "resolved",
            "clv_pct": 2.31, "close_price": -125.0, "close_source": "odds_history",
            "close_book_scope": "same_book", "close_captured_at": "2026-10-03T23:05:00Z",
        }]}

    result = settle.settle_orders(DATE, resolver=_resolver(10.0), closer=closer)
    mark = _orders()[0]["closing_mark"]
    assert mark["clv_pct"] == 2.31
    assert mark["close_price"] == -125.0
    assert mark["close_source"] == "odds_history"
    assert mark["reason"] == "resolved"
    assert result["closing_marks"]["resolved"] == 1


def test_no_close_is_stamped_as_None_with_its_reason_never_zero():
    place_order(_request(book="fanduel"))
    settle.settle_orders(DATE, resolver=_resolver(10.0), closer=_no_close)
    mark = _orders()[0]["closing_mark"]
    assert "clv_pct" in mark and mark["clv_pct"] is None
    assert mark["reason"] == "no_close_for_market"
    assert mark["attempts"] == 1


def test_an_unsettled_order_gets_no_closing_mark():
    place_order(_request(book="fanduel"))
    calls = []
    settle.settle_orders(
        DATE,
        resolver=lambda _o: {"current_value": 3.0, "is_final": False, "started": True},
        closer=lambda rows, d: calls.append(rows) or {"rows": []},
    )
    assert calls == []
    assert "closing_mark" not in _orders()[0]


def test_a_resolved_mark_is_never_recomputed():
    place_order(_request(book="fanduel"))
    calls = []

    def closer(rows, _date):
        calls.append(len(rows))
        return {"rows": [{"idempotency_key": r["idempotency_key"], "reason": "resolved",
                          "clv_pct": 1.0, "close_price": -115.0} for r in rows]}

    settle.settle_orders(DATE, resolver=_resolver(10.0), closer=closer)
    settle.settle_orders(DATE, resolver=_resolver(10.0), closer=closer)
    assert calls == [1]


def test_an_unresolved_close_is_retried_on_a_bounded_schedule():
    orders = [{"idempotency_key": "k", "outcome": "won", "status": "filled"}]
    t0 = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
    calls = []

    def closer(rows, _date):
        calls.append(1)
        return _no_close(rows, _date)

    settle.stamp_closing_marks(orders, DATE, closer=closer, now=t0)
    settle.stamp_closing_marks(orders, DATE, closer=closer, now=t0 + timedelta(minutes=5))
    assert len(calls) == 1  # too soon
    for hour in range(1, 10):
        settle.stamp_closing_marks(orders, DATE, closer=closer, now=t0 + timedelta(hours=hour))
    assert len(calls) == settle._CLOSE_MAX_ATTEMPTS
    assert orders[0]["closing_mark"]["attempts"] == settle._CLOSE_MAX_ATTEMPTS


def test_a_closer_failure_stamps_nothing_and_never_raises():
    orders = [{"idempotency_key": "k", "outcome": "won", "status": "filled"}]

    def boom(_rows, _date):
        raise RuntimeError("odds history unreadable")

    result = settle.stamp_closing_marks(orders, DATE, closer=boom)
    assert result["stamped"] == 0
    assert "closing_mark" not in orders[0]
