"""Kalshi V2 cancel names the order's exchange shard (2026-10-20).

The V2 cancel docs: `exchange_index` -- "If omitted, auto-routes when
market_ticker is provided, otherwise defaults to 0" -- and "An order_id alone
cannot identify the exchange shard". The fleet sent a bare DELETE, so an order
resting on any shard but 0 came back 404 and stayed on the book (SAS/OKC +20.5,
2026-10-20 22:04Z). Both auto-cancels call `cancel_order(order_id)` with the id
alone, so the shard is looked up from the order itself.
"""

from __future__ import annotations

import urllib.parse

import pytest

from syndicate.features.shared import kalshi_orders as mod

BASE = "https://example.test/trade-api/v2"


@pytest.fixture(autouse=True)
def _base(monkeypatch):
    monkeypatch.setenv("KALSHI_API_BASE", BASE)
    for name in ("KALSHI_ORDER_CANCEL_PATH", "KALSHI_ORDER_SUBACCOUNT"):
        monkeypatch.delenv(name, raising=False)


def _venue(monkeypatch, order=None, delete_reply=None, read_error=None):
    calls = []

    def fake(method, url, **_kwargs):
        calls.append((method, url))
        if method == "GET":
            if read_error:
                raise RuntimeError(read_error)
            return {"order": order or {}}
        if method == "DELETE":
            return delete_reply if delete_reply is not None else {
                "order_id": "abc", "client_order_id": "c1", "reduced_by": "3.00", "ts_ms": 1}
        raise AssertionError(method)

    monkeypatch.setattr("syndicate.features.shared.kalshi_auth.signed_request", fake)
    return calls


def _query(url):
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))


def test_order_id_alone_reads_the_order_then_cancels_on_its_shard(monkeypatch):
    calls = _venue(monkeypatch, order={"order_id": "abc", "exchange_index": 3,
                                       "ticker": "KXNBASPREAD-26OCT20OKCSAS-SAS21", "status": "resting"})
    result = mod.cancel_order("abc")
    assert [m for m, _ in calls] == ["GET", "DELETE"]
    assert calls[0][1] == f"{BASE}/portfolio/orders/abc"           # the read needs no shard
    method, url = calls[1]
    assert url.startswith(f"{BASE}/portfolio/events/orders/abc?")
    assert _query(url) == {"exchange_index": "3", "market_ticker": "KXNBASPREAD-26OCT20OKCSAS-SAS21"}
    assert result == {"status": "ok", "order": {"order_id": "abc", "client_order_id": "c1",
                                                "reduced_by": "3.00", "ts_ms": 1},
                      "reduced_by": "3.00", "exchange_index": 3}


def test_the_bare_delete_is_never_sent(monkeypatch):
    """Reachability: before this change the DELETE carried no query at all."""
    calls = _venue(monkeypatch, order={"exchange_index": 0, "ticker": "T"})
    mod.cancel_order("abc")
    deletes = [url for m, url in calls if m == "DELETE"]
    assert deletes and all("?" in url and "exchange_index=0" in url for url in deletes)


def test_a_caller_that_knows_the_shard_skips_the_read(monkeypatch):
    calls = _venue(monkeypatch)
    mod.cancel_order("abc", exchange_index=1, market_ticker="T")
    assert [m for m, _ in calls] == ["DELETE"]
    assert _query(calls[0][1]) == {"exchange_index": "1", "market_ticker": "T"}


def test_a_ticker_without_a_shard_auto_routes(monkeypatch):
    """Docs: omitted `exchange_index` auto-routes when `market_ticker` is given."""
    calls = _venue(monkeypatch, order={"ticker": "T"})          # read gives no shard
    result = mod.cancel_order("abc")
    assert result["status"] == "ok"
    assert _query(calls[-1][1]) == {"market_ticker": "T"}


@pytest.mark.parametrize("bad", [-1, "-1", "", "x", None, True])
def test_auto_or_garbage_is_not_a_shard(bad):
    assert mod._shard_of(bad) is None


def test_no_shard_and_no_ticker_is_refused_not_guessed_as_zero(monkeypatch):
    calls = _venue(monkeypatch, order={"status": "resting"})
    result = mod.cancel_order("abc")
    assert result == {"status": "error", "reason": "cancel_shard_unknown"}
    assert [m for m, _ in calls] == ["GET"]                       # nothing deleted


def test_an_unreadable_order_is_not_cancelled_blind(monkeypatch):
    calls = _venue(monkeypatch, read_error="http_404")
    result = mod.cancel_order("abc")
    assert result["status"] == "error"
    assert result["reason"].startswith("shard_lookup_failed:") and "http_404" in result["reason"]
    assert [m for m, _ in calls] == ["GET"]


def test_a_failed_delete_is_named_with_the_shard(monkeypatch):
    def fake(method, url, **_kwargs):
        if method == "GET":
            return {"order": {"exchange_index": 3, "ticker": "T"}}
        raise RuntimeError("http_404")

    monkeypatch.setattr("syndicate.features.shared.kalshi_auth.signed_request", fake)
    result = mod.cancel_order("abc")
    assert result["status"] == "error" and "http_404" in result["reason"]
    assert result["exchange_index"] == 3


def test_subaccount_only_when_configured(monkeypatch):
    assert "subaccount" not in _query(mod._order_cancel_url("abc", exchange_index=3))
    monkeypatch.setenv("KALSHI_ORDER_SUBACCOUNT", "2")
    assert _query(mod._order_cancel_url("abc", exchange_index=3)) == {"subaccount": "2", "exchange_index": "3"}
