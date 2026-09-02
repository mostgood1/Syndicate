"""Lane `kalshi-discovery-deadline`: the two bounds on Kalshi market fetching.

WHAT WAS MEASURED FIRST, because every obvious answer was wrong (2026-09-02,
`_get` instrumented at the leaf so import style could not bypass the counter):

    one intelligence build  ->  254 requests, 58.3s network, 103.3s wall
    of which                    248 per-series /markets fetches
                                150 DISTINCT series -- 98 (40%) were repeats
    standalone discover()   ->  40 pages, 30.3s, truncated=True EVERY time,
                                201 singles out of 40,000 markets

So the cost is FAN-OUT ACROSS SERIES. It is NOT pagination depth (21 of 266
calls followed a cursor), NOT host retries (`fetch_markets` breaks on first
success; every observed call hit `_BASE_URLS[0]` with zero failures), and NOT
the per-request timeout (20s, never approached -- median ~0.24s). An earlier
hypothesis that these multiplied to ~1,200s was arithmetic on a loop shape that
does not exist: `pages` is declared outside the `for base` loop and never reset,
so `max_pages` is global across hosts.

These tests pin what the bounds must do, and each is written so the PRE-FIX
code fails it. A test that merely asserted "fetch_markets returns a dict" would
have passed throughout.
"""
from __future__ import annotations

import time

import pytest

from syndicate.features.shared import kalshi_client as kc


@pytest.fixture(autouse=True)
def _clean_cache():
    kc.reset_markets_cache()
    yield
    kc.reset_markets_cache()


def _stub(pages_by_call=None, delay=0.0, cursor_forever=False):
    """A fake transport. Records every URL so call COUNT is a measurement."""
    calls = []

    def fake_get(url, *, timeout=20.0):
        calls.append(url)
        if delay:
            time.sleep(delay)
        payload = {"markets": [{"ticker": "T%d" % len(calls), "title": "t"}]}
        if cursor_forever:
            payload["cursor"] = "c%d" % len(calls)
        return payload

    return fake_get, calls


# --------------------------------------------------------------------------
# BOUND 1 -- the memo. 40% of a real build's series fetches were repeats.
# --------------------------------------------------------------------------

def test_repeat_series_fetch_is_served_from_cache(monkeypatch):
    fake, calls = _stub()
    monkeypatch.setattr(kc, "_get", fake)
    first = kc.fetch_markets(series_ticker="KXMLBHRR")
    second = kc.fetch_markets(series_ticker="KXMLBHRR")
    assert len(calls) == 1, "second identical fetch went to the venue again"
    assert second["cache_hit"] is True
    assert first["markets"] == second["markets"]
    assert kc.markets_cache_stats()["hits"] == 1


def test_off_does_not_equal_on(monkeypatch):
    """Reachability, the model-engine standard's first rule. A cache that is
    present but never consulted looks identical to one that works."""
    fake, calls = _stub()
    monkeypatch.setattr(kc, "_get", fake)
    kc.fetch_markets(series_ticker="A", use_cache=False)
    kc.fetch_markets(series_ticker="A", use_cache=False)
    uncached = len(calls)
    kc.reset_markets_cache()
    calls.clear()
    kc.fetch_markets(series_ticker="A")
    kc.fetch_markets(series_ticker="A")
    cached = len(calls)
    assert uncached == 2 and cached == 1, "cache is inert (%d vs %d)" % (uncached, cached)


def test_distinct_series_are_not_conflated(monkeypatch):
    """The 150 distinct series must still each be fetched -- a cache that
    collapsed them would be fast and WRONG."""
    fake, calls = _stub()
    monkeypatch.setattr(kc, "_get", fake)
    for ticker in ("A", "B", "C"):
        kc.fetch_markets(series_ticker=ticker)
    assert len(calls) == 3
    assert kc.markets_cache_stats()["hits"] == 0


def test_ttl_zero_disables_the_cache(monkeypatch):
    monkeypatch.setenv("SYNDICATE_KALSHI_MARKETS_CACHE_TTL_SECONDS", "0")
    fake, calls = _stub()
    monkeypatch.setattr(kc, "_get", fake)
    kc.fetch_markets(series_ticker="A")
    kc.fetch_markets(series_ticker="A")
    assert len(calls) == 2


def test_expired_entry_refetches(monkeypatch):
    monkeypatch.setenv("SYNDICATE_KALSHI_MARKETS_CACHE_TTL_SECONDS", "0.05")
    fake, calls = _stub()
    monkeypatch.setattr(kc, "_get", fake)
    kc.fetch_markets(series_ticker="A")
    time.sleep(0.08)
    kc.fetch_markets(series_ticker="A")
    assert len(calls) == 2
    assert kc.markets_cache_stats()["evictions"] == 1


# --------------------------------------------------------------------------
# BOUND 2 -- the aggregate budget. Nothing anywhere measured elapsed time.
# --------------------------------------------------------------------------

def test_budget_stops_the_paging_loop_and_says_so(monkeypatch):
    fake, calls = _stub(delay=0.03, cursor_forever=True)
    monkeypatch.setattr(kc, "_get", fake)
    with kc.request_budget(0.15):
        report = kc.fetch_markets(series_ticker="A", max_pages=500, use_cache=False)
    assert report["budget_exceeded"] is True
    assert report["truncated"] is True, "a budget stop must read as truncated"
    assert report["markets"], "must return what it already paid for, not nothing"
    assert len(calls) < 500, "budget did not stop the loop (%d calls)" % len(calls)


def test_budget_off_pages_further_than_budget_on(monkeypatch):
    """off != on for the budget, measured in CALLS rather than asserted."""
    fake_a, calls_a = _stub(delay=0.02, cursor_forever=True)
    monkeypatch.setattr(kc, "_get", fake_a)
    unbudgeted = kc.fetch_markets(series_ticker="A", max_pages=30, use_cache=False)
    fake_b, calls_b = _stub(delay=0.02, cursor_forever=True)
    monkeypatch.setattr(kc, "_get", fake_b)
    with kc.request_budget(0.10):
        budgeted = kc.fetch_markets(series_ticker="A", max_pages=30, use_cache=False)
    assert len(calls_a) > len(calls_b), "budget is inert (%d vs %d)" % (len(calls_a), len(calls_b))
    assert unbudgeted["budget_exceeded"] is False
    assert budgeted["budget_exceeded"] is True


def test_exhausted_budget_does_not_retry_every_host(monkeypatch):
    """The retry storm the budget exists to prevent: three hosts x a dead
    budget must not become three more requests."""
    fake, calls = _stub()
    monkeypatch.setattr(kc, "_get", fake)
    with kc.request_budget(0.0):
        report = kc.fetch_markets(series_ticker="A", use_cache=False)
    assert len(calls) == 0
    assert report["budget_exceeded"] is True
    assert len(kc._BASE_URLS) == 3, "guard: this test is about the multi-host loop"


def test_a_truncated_result_is_never_cached(monkeypatch):
    """Serving a budget-truncated listing to a caller that had time is the
    `#435`-class failure: a partial presented as whole."""
    fake, calls = _stub(delay=0.03, cursor_forever=True)
    monkeypatch.setattr(kc, "_get", fake)
    with kc.request_budget(0.10):
        kc.fetch_markets(series_ticker="A", max_pages=500)
    calls.clear()
    kc.fetch_markets(series_ticker="A", max_pages=500)
    assert calls, "a budget-truncated listing was cached and served as complete"


def test_nested_budget_keeps_the_tighter_deadline():
    with kc.request_budget(30.0) as outer:
        with kc.request_budget(0.05) as inner:
            assert inner.deadline <= outer.deadline
        # restored, and not silently extended
        assert kc._current_budget() is outer


def test_no_budget_means_no_behaviour_change(monkeypatch):
    """Every existing caller passes no budget and must be untouched."""
    fake, calls = _stub()
    monkeypatch.setattr(kc, "_get", fake)
    assert kc._current_budget() is None
    report = kc.fetch_markets(series_ticker="A", use_cache=False)
    assert report["budget_exceeded"] is False
    assert len(calls) == 1
