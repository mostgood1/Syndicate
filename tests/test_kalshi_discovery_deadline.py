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
def _clean_stats():
    kc.reset_fetch_markets_stats()
    yield
    kc.reset_fetch_markets_stats()


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


# The memo that used to sit here was DELETED the same day it was written, on a
# measurement: two back-to-back forced ticks produced 206 then 412 cumulative
# `fetch_markets` calls and ZERO cache hits. Within a tick each series is
# fetched once (no redundancy to memoise); across ticks the 120s refresh
# interval outlives any TTL short enough to be safe. Its tests went with it --
# a passing test for a mechanism that cannot fire is worse than no test.


# --------------------------------------------------------------------------
# BOUND 2 -- the aggregate budget. Nothing anywhere measured elapsed time.
# --------------------------------------------------------------------------

def test_budget_stops_the_paging_loop_and_says_so(monkeypatch):
    fake, calls = _stub(delay=0.03, cursor_forever=True)
    monkeypatch.setattr(kc, "_get", fake)
    with kc.request_budget(0.15):
        report = kc.fetch_markets(series_ticker="A", max_pages=500)
    assert report["budget_exceeded"] is True
    assert report["truncated"] is True, "a budget stop must read as truncated"
    assert report["markets"], "must return what it already paid for, not nothing"
    assert len(calls) < 500, "budget did not stop the loop (%d calls)" % len(calls)


def test_budget_off_pages_further_than_budget_on(monkeypatch):
    """off != on for the budget, measured in CALLS rather than asserted."""
    fake_a, calls_a = _stub(delay=0.02, cursor_forever=True)
    monkeypatch.setattr(kc, "_get", fake_a)
    unbudgeted = kc.fetch_markets(series_ticker="A", max_pages=30)
    fake_b, calls_b = _stub(delay=0.02, cursor_forever=True)
    monkeypatch.setattr(kc, "_get", fake_b)
    with kc.request_budget(0.10):
        budgeted = kc.fetch_markets(series_ticker="A", max_pages=30)
    assert len(calls_a) > len(calls_b), "budget is inert (%d vs %d)" % (len(calls_a), len(calls_b))
    assert unbudgeted["budget_exceeded"] is False
    assert budgeted["budget_exceeded"] is True


def test_exhausted_budget_does_not_retry_every_host(monkeypatch):
    """The retry storm the budget exists to prevent: three hosts x a dead
    budget must not become three more requests."""
    fake, calls = _stub()
    monkeypatch.setattr(kc, "_get", fake)
    with kc.request_budget(0.0):
        report = kc.fetch_markets(series_ticker="A")
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
    report = kc.fetch_markets(series_ticker="A")
    assert report["budget_exceeded"] is False
    assert len(calls) == 1


# --------------------------------------------------------------------------
# THE WIRING. A bound nothing calls is the same trap one level up, so these
# pin that `run_kalshi_odds_refresh` actually applies it -- and, more
# importantly, that applying it cannot BLANK SERIES OFF THE BOARD.
#
# The hazard is specific and was found by reading the loop, not by a failure:
# `fetch_markets` returns a PARTIAL result on budget exhaustion rather than
# raising, and the refresh treats an empty-but-successful read as "no open
# markets" and lets the series go dormant for `dormant_interval_seconds`
# (3600s). A budget that stopped mid-fetch would therefore take up to
# `series_per_tick()` = 150 series off the board for an hour.
# --------------------------------------------------------------------------

def _refresh_module():
    from pipeline import kalshi_odds_refresh as kor
    return kor


def _offline(monkeypatch, kor, tmp_path):
    """No venue sockets: stub the transport AND the catalogue step, so these
    tests measure the loop rather than the network."""
    monkeypatch.setattr(kc, "_get", lambda url, timeout=20.0: {"markets": []})
    monkeypatch.setattr(kor, "ensure_series_discovered", lambda *a, **kw: {"status": "skipped"})
    monkeypatch.setattr(kor, "markets_artifact_path", lambda: tmp_path / "state.json")
    monkeypatch.setenv("SYNDICATE_KALSHI_REQUEST_SPACING_MS", "0")


def test_budget_stops_the_series_loop_early(monkeypatch, tmp_path):
    kor = _refresh_module()
    _offline(monkeypatch, kor, tmp_path)
    seen = []

    def slow_series(series, *a, **kw):
        seen.append(series)
        time.sleep(0.05)
        return {"markets": [{"ticker": series + "-1"}], "strategy": "series_filter"}

    monkeypatch.setattr(kor, "fetch_series_markets", slow_series)
    monkeypatch.setenv("SYNDICATE_KALSHI_REFRESH_BUDGET_SECONDS", "0.30")
    kor.run_kalshi_odds_refresh(force=True)
    assert seen, "nothing ran at all"
    assert len(seen) < 150, "budget did not stop the loop (%d series)" % len(seen)


def test_unattempted_series_are_not_stamped(monkeypatch, tmp_path):
    """The safety property. A series the budget skipped must keep its old
    stamp so it stays DUE -- stamping it would mark it a successful empty read
    and take it off the board for an hour."""
    kor = _refresh_module()
    _offline(monkeypatch, kor, tmp_path)
    state_path = tmp_path / "state.json"

    def slow_series(series, *a, **kw):
        time.sleep(0.05)
        return {"markets": [{"ticker": series + "-1"}], "strategy": "series_filter"}

    monkeypatch.setattr(kor, "fetch_series_markets", slow_series)
    monkeypatch.setenv("SYNDICATE_KALSHI_REFRESH_BUDGET_SECONDS", "0.30")
    kor.run_kalshi_odds_refresh(force=True)

    from syndicate.features.shared.refresh_state_store import read_json_file

    per_series = (read_json_file(state_path) or {}).get("series") or {}
    stamped = [s for s, v in per_series.items() if v.get("attempted_at")]
    wanted = kor.sports_series()
    assert stamped, "nothing was recorded"
    assert len(stamped) < len(wanted), (
        "every series was stamped despite the budget stopping the loop -- "
        "unattempted series would go dormant"
    )


def test_a_budget_truncated_fetch_is_not_an_empty_book(monkeypatch):
    """`strategy` must NOT be series_filter, or `read_succeeded` goes True and
    the series is recorded as legitimately empty."""
    kor = _refresh_module()
    monkeypatch.setattr(
        kor, "fetch_series",
        lambda *a, **kw: {"markets": [], "budget_exceeded": True, "count": 0},
        raising=False,
    )
    from syndicate.features.shared import kalshi_client as _kc
    monkeypatch.setattr(_kc, "fetch_series",
                        lambda *a, **kw: {"markets": [], "budget_exceeded": True, "count": 0})
    result = kor.fetch_series_markets("KXTEST")
    assert result["strategy"] == "budget", result
    assert result["strategy"] != "series_filter"


def test_budget_zero_disables_the_wrapper(monkeypatch):
    kor = _refresh_module()
    monkeypatch.setenv("SYNDICATE_KALSHI_REFRESH_BUDGET_SECONDS", "0")
    assert kor.refresh_budget_seconds() == 0
    calls = {"n": 0}

    def fake_unbounded(*, force=False):
        calls["n"] += 1
        assert kc.budget_remaining() is None, "budget applied despite being disabled"
        return {"status": "ok"}

    monkeypatch.setattr(kor, "_run_kalshi_odds_refresh_unbounded", fake_unbounded)
    kor.run_kalshi_odds_refresh()
    assert calls["n"] == 1


def test_budget_is_applied_when_enabled(monkeypatch):
    """off != on for the WIRING itself, not just the mechanism."""
    kor = _refresh_module()
    monkeypatch.setenv("SYNDICATE_KALSHI_REFRESH_BUDGET_SECONDS", "12")
    seen = {}

    def fake_unbounded(*, force=False):
        seen["remaining"] = kc.budget_remaining()
        return {"status": "ok"}

    monkeypatch.setattr(kor, "_run_kalshi_odds_refresh_unbounded", fake_unbounded)
    kor.run_kalshi_odds_refresh()
    assert seen["remaining"] is not None and 0 < seen["remaining"] <= 12
