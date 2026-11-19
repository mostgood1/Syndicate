"""The venue's quote at submit and the fill time on the ledger row (lane fill-quote-logging, 2026-11-19).

Ledger-only instrumentation: nothing here changes which orders are placed, how they are sized, or how they are
held or exited. See `execution_ledger.note_submit_quote` and `execution_ledger._stamp_filled_at`.
"""
from __future__ import annotations

import pytest

from syndicate.features.shared import execution_ledger as ledger
from syndicate.features.shared.execution_ledger import (
    LIVE,
    PAPER,
    STATUS_FAILED,
    STATUS_FILLED,
    STATUS_SUBMITTED,
    OrderRequest,
    idempotency_key,
    place_order,
)

QUOTE = {"source": "kalshi_live_market", "yes_bid": 0.43, "yes_ask": 0.45, "no_bid": 0.55, "no_ask": 0.57,
         "yes_bid_size": 120.0, "yes_ask_size": 80.0, "contract_side": "yes", "price_used": 0.45}


@pytest.fixture(autouse=True)
def _isolated_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.delenv("SYNDICATE_EXECUTION_MODE", raising=False)
    monkeypatch.delenv("SYNDICATE_EXECUTION_LIVE_ARMED", raising=False)
    monkeypatch.delenv("SYNDICATE_REFRESH_STATE_BACKEND", raising=False)
    ledger._SUBMIT_QUOTES.clear()
    yield
    ledger._SUBMIT_QUOTES.clear()


def _armed(monkeypatch):
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "1")


def _request(**overrides) -> OrderRequest:
    base = {"position_key": "fq-1", "selected_date": "2026-11-19", "venue": "kalshi", "sport": "nba",
            "event_id": "evt-1", "market": "h2h", "side": "home", "requested_price": 0.45,
            "requested_stake_dollars": 4.5, "venue_ticker": "KX-TEST-1"}
    base.update(overrides)
    return OrderRequest(**base)


class _Adapter:
    """A two-phase adapter whose BUILD notes the quote, as `_kalshi_price_for` does inside the real build."""

    def __init__(self, *, refuse=None, send_raises=None, status=STATUS_FILLED):
        self.refuse, self.send_raises, self.status = refuse, send_raises, status

    def build(self, request):
        ledger.note_submit_quote(request, QUOTE)
        if self.refuse is not None:
            raise self.refuse

        def send():
            if self.send_raises is not None:
                raise self.send_raises
            return {"status": self.status, "fill_price": 0.45, "fill_stake_dollars": 4.5}

        return send

    def __call__(self, request):
        return self.build(request)()


def test_a_live_fill_keeps_the_quote_noted_at_build_and_its_fill_time(monkeypatch):
    _armed(monkeypatch)
    record = place_order(_request(), submit=_Adapter(), mode=LIVE)
    row = ledger.find_order(record["idempotency_key"])
    assert row["status"] == STATUS_FILLED
    assert row["venue_quote_at_submit"] == QUOTE
    assert row["venue_filled_at"] == row["venue_resolved_at"]
    assert row["venue_filled_at_basis"] == "submit_response"
    assert ledger._SUBMIT_QUOTES == {}


def test_a_resting_submit_keeps_the_quote_but_has_no_fill_time_yet(monkeypatch):
    _armed(monkeypatch)
    record = place_order(_request(), submit=_Adapter(status=STATUS_SUBMITTED), mode=LIVE)
    row = ledger.find_order(record["idempotency_key"])
    assert row["venue_quote_at_submit"] == QUOTE
    assert not row.get("venue_filled_at")


def test_a_refused_build_leaves_no_quote_behind_and_no_row(monkeypatch):
    _armed(monkeypatch)
    record = place_order(_request(), submit=_Adapter(refuse=RuntimeError("slippage")), mode=LIVE)
    assert record.get("recorded") is False
    assert ledger._SUBMIT_QUOTES == {}
    assert ledger.find_order(idempotency_key(_request())) is None


def test_a_send_that_raises_keeps_the_quote_on_the_failed_row_without_a_fill_time(monkeypatch):
    _armed(monkeypatch)
    record = place_order(_request(), submit=_Adapter(send_raises=RuntimeError("reset mid-POST")), mode=LIVE)
    row = ledger.find_order(record["idempotency_key"])
    assert row["status"] == STATUS_FAILED
    assert row["venue_quote_at_submit"] == QUOTE
    assert not row.get("venue_filled_at")
    assert ledger._SUBMIT_QUOTES == {}


def test_a_paper_fill_is_left_alone():
    record = place_order(_request(venue="paper"), mode=PAPER)
    row = ledger.find_order(record["idempotency_key"])
    assert row["status"] == STATUS_FILLED
    # Present (shape parity with a live row) but never filled in on paper.
    assert row["venue_quote_at_submit"] is None
    assert row["venue_filled_at"] is None and row["venue_filled_at_basis"] is None


def test_the_quote_store_is_bounded():
    for i in range(ledger._SUBMIT_QUOTES_MAX + 25):
        ledger.note_submit_quote(_request(position_key=f"k{i}"), QUOTE)
    assert len(ledger._SUBMIT_QUOTES) == ledger._SUBMIT_QUOTES_MAX


def _reader(orders):
    from syndicate.features.shared.kalshi_orders import venue_order_view

    def fetch(*, limit=100, order_ids=None):
        return {"status": "ok", "orders": list(orders), "coverage": "book"}

    return fetch, venue_order_view, "book"


def _live_row(monkeypatch, *, key, status, **fields):
    _armed(monkeypatch)
    record, _ = ledger.record_order(_request(position_key=key), mode=LIVE)
    ledger.complete_order(record["idempotency_key"], status=status, **fields)
    return record["idempotency_key"]


def test_a_resting_order_that_fills_later_gets_its_fill_time_once(monkeypatch):
    key = _live_row(monkeypatch, key="late", status=STATUS_SUBMITTED, venue_order_id="ord-2")
    assert not ledger.find_order(key).get("venue_filled_at")
    monkeypatch.setattr(ledger, "_venue_reader", lambda venue: _reader([
        {"order_id": "ord-2", "client_order_id": key, "status": "executed", "filled_count": 2,
         "average_fill_price": 44}]))
    assert ledger.reconcile_live_orders()["changed"] == 1
    first = ledger.find_order(key)
    assert first["status"] == STATUS_FILLED
    assert first["venue_filled_at"] and first["venue_filled_at_basis"] == "reconcile_observed"
    ledger.reconcile_live_orders()
    assert ledger.find_order(key)["venue_filled_at"] == first["venue_filled_at"]


def test_a_phantom_fill_loses_its_fill_time(monkeypatch):
    key = _live_row(monkeypatch, key="phantom", status=STATUS_FILLED, fill_price=0.54,
                    fill_stake_dollars=1.08, venue_order_id="ord-1")
    assert ledger.find_order(key)["venue_filled_at_basis"] == "submit_response"
    monkeypatch.setattr(ledger, "_venue_reader", lambda venue: _reader([
        {"order_id": "ord-1", "client_order_id": key, "status": "resting", "filled_count": 0,
         "remaining_count": 2, "initial_count": 2}]))
    assert ledger.reconcile_live_orders()["changed"] == 1
    row = ledger.find_order(key)
    assert row["status"] == STATUS_SUBMITTED
    assert row["venue_filled_at"] is None
    assert row["venue_filled_at_basis"] == "cleared_submitted"


def test_the_executor_price_read_notes_both_legs_and_the_size_at_the_touch(monkeypatch):
    from pipeline import execute_portfolio as ep
    from syndicate.features.shared import kalshi_client

    market = {"ticker": "KX-TEST-1", "event_ticker": "KX-EV", "yes_bid_dollars": "0.4300",
              "yes_ask_dollars": "0.4500", "no_bid_dollars": "0.5500", "no_ask_dollars": "0.5700",
              "yes_bid_size_fp": "120.00", "yes_ask_size_fp": "80.00", "last_price_dollars": "0.4400",
              "volume_24h_fp": "1500.00", "open_interest_fp": "900.00"}
    monkeypatch.setattr(kalshi_client, "fetch_market", lambda ticker: {"status": "ok", "market": market})
    request = _request()
    price = ep._kalshi_price_for(request)
    quote = ledger._SUBMIT_QUOTES[idempotency_key(request)]
    assert quote["source"] == "kalshi_live_market"
    assert quote["price_used"] == price
    assert (quote["yes_bid"], quote["yes_ask"], quote["no_bid"], quote["no_ask"]) == (0.43, 0.45, 0.55, 0.57)
    assert (quote["yes_bid_size"], quote["yes_ask_size"]) == (120.0, 80.0)
    assert quote["last_price"] == 0.44 and quote["volume_24h"] == 1500.0 and quote["open_interest"] == 900.0
    assert quote["contract_side"] in ("yes", "no") and quote["fetched_at"].endswith("Z")


def test_a_quote_that_cannot_be_kept_never_stops_the_price_read(monkeypatch):
    from pipeline import execute_portfolio as ep
    from syndicate.features.shared import kalshi_client

    monkeypatch.setattr(kalshi_client, "fetch_market", lambda ticker: {"status": "ok", "market": {
        "yes_ask_dollars": "0.4500", "no_ask_dollars": "0.5700"}})

    def broken(request, quote):
        raise RuntimeError("store unavailable")

    monkeypatch.setattr(ledger, "note_submit_quote", broken)
    assert ep._kalshi_price_for(_request()) is not None


def test_the_polymarket_resolver_notes_the_slate_quote_it_priced_from(monkeypatch):
    """Polymarket is priced from the persisted slate (`_polymarket_resolve_market`'s docstring), so its quote is
    the slate's `outcomePrices` with the slate's age, labelled as such. Same fixture shape as
    tests/test_execute_portfolio.py's `_polymarket_row` / `_artifact_env`."""
    import time

    import pipeline.execute_portfolio as runner
    from syndicate.features.shared import refresh_state_store

    monkeypatch.setenv("SYNDICATE_POLYMARKET_YES_LEG_CORROBORATE", "0")  # the fixture row states no yes leg
    fetched = time.time()
    row = {"slug": "aec-mlb-tex-chw-2026-08-24", "outcomes": ["White Sox", "Rangers"],
           "outcomePrices": ["0.55", "0.45"], "orderPriceMinTickSize": "0.001", "minimumTradeQty": "1",
           "orderable": True}
    monkeypatch.setattr(refresh_state_store, "read_json_file",
                        lambda path: {"fetched_at": fetched, "markets": [row], "count": 1})
    request = _request(venue="polymarket", sport="mlb", market="h2h", side="home", home_team="CHW",
                       away_team="TEX", requested_price=0.55, venue_ticker="aec-mlb-tex-chw-2026-08-24")
    resolved = runner._polymarket_resolve_market(request)
    assert resolved is not None
    quote = ledger._SUBMIT_QUOTES[idempotency_key(request)]
    assert quote["source"] == "polymarket_slate_artifact"
    assert quote["outcomes"] == ["White Sox", "Rangers"] and quote["outcome_index"] == 0
    assert quote["price_used"] == resolved[1] and quote["quoted"] == 0.55
    assert quote["outcome_prices"] == ["0.55", "0.45"]
    assert quote["slate_age_s"] is not None and quote["slate_age_s"] < 60
