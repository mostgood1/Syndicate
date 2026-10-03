"""The Polymarket slate sweep is single-flight (lane `layer2-freshness-1h`, 2026-10-03).

Measured on the fleet 02:45-04:08Z: 29 full-catalogue sweeps (~156 pages, ~4 min
each), 3 of them landing under 90 s after the previous write -- the venue-poll
thread and the main loop both passing an unlocked check-then-set gate and paging
the whole catalogue in parallel.
"""
from __future__ import annotations

import threading

import scripts.run_live_odds_refresh_worker as worker


def _fake_venue(monkeypatch, gate: threading.Event, calls: list):
    from syndicate.features.shared import polymarket_us_auth, polymarket_us_markets

    def persist():
        calls.append("sweep")
        gate.wait(5)
        return {"status": "ok", "written": True, "count": 1}

    monkeypatch.setattr(polymarket_us_markets, "persist_game_slate", persist)
    monkeypatch.setattr(polymarket_us_auth, "credentials_present", lambda: True)
    monkeypatch.setattr(worker, "_polymarket_daily_book", lambda: None)
    monkeypatch.setattr(worker, "_POLYMARKET_SLATE_LAST_RUN", 0.0)
    monkeypatch.delenv("SYNDICATE_POLYMARKET_US_SLATE_REFRESH_ENABLED", raising=False)


def test_reachability_a_second_caller_does_not_start_a_parallel_sweep(monkeypatch):
    gate, calls = threading.Event(), []
    _fake_venue(monkeypatch, gate, calls)
    first = threading.Thread(target=worker._polymarket_us_slate_refresh_tick)
    first.start()
    for _ in range(100):
        if calls:
            break
        threading.Event().wait(0.01)
    # The gate stamp is already set by the first caller; force the second past
    # the interval check so ONLY the lock can stop it -- this is the race seen live.
    monkeypatch.setattr(worker, "_POLYMARKET_SLATE_LAST_RUN", 0.0)
    worker._polymarket_us_slate_refresh_tick()  # returns at once: sweep in flight
    assert calls == ["sweep"], "a second sweep started while one was in flight"
    gate.set()
    first.join(5)
    assert not worker._POLYMARKET_SLATE_LOCK.locked(), "the lock must be released after a sweep"


def test_after_a_sweep_the_next_due_caller_sweeps(monkeypatch):
    gate, calls = threading.Event(), []
    gate.set()
    _fake_venue(monkeypatch, gate, calls)
    worker._polymarket_us_slate_refresh_tick()
    monkeypatch.setattr(worker, "_POLYMARKET_SLATE_LAST_RUN", 0.0)  # interval elapsed
    worker._polymarket_us_slate_refresh_tick()
    assert calls == ["sweep", "sweep"]


def test_a_failing_sweep_still_releases_the_lock(monkeypatch):
    from syndicate.features.shared import polymarket_us_auth, polymarket_us_markets

    def boom():
        raise RuntimeError("venue down")

    monkeypatch.setattr(polymarket_us_markets, "persist_game_slate", boom)
    monkeypatch.setattr(polymarket_us_auth, "credentials_present", lambda: True)
    monkeypatch.setattr(worker, "_POLYMARKET_SLATE_LAST_RUN", 0.0)
    worker._polymarket_us_slate_refresh_tick()
    assert not worker._POLYMARKET_SLATE_LOCK.locked()
