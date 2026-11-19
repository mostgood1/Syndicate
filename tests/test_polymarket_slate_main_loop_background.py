"""The main loop's Polymarket slate call can run off the main thread (todo #851).

MEASURED 2026-11-19 (lane `live-odds-loop-attempt-spacing`), 482 main-loop iterations
in the 00-05Z live windows of 11-15..11-18:
- The slate sweep that live-odds-worker's main loop ran synchronously was 25.9% of
  loop time, 92-233 s each time.
- Every odds-sweep launch comes from that loop, so the sweep pushed the next odds
  sweep back by its full length (attempt spacing p50 100 s, p90 299 s).

`SYNDICATE_POLYMARKET_SLATE_MAIN_LOOP_BACKGROUND` (absent = off = the inline call)
starts a due sweep on a daemon thread instead. These tests pin:
- off != on, through the step the loop really calls;
- the single flight;
- the not-due gate;
- that nothing which pages the venue runs on the calling thread when on.
"""
from __future__ import annotations

import inspect
import threading
import time

import pytest

import scripts.run_live_odds_refresh_worker as worker

ENV = "SYNDICATE_POLYMARKET_SLATE_MAIN_LOOP_BACKGROUND"


@pytest.fixture
def venue(monkeypatch):
    """A fake venue whose sweep blocks until `gate` is set and records the thread it ran on."""
    from syndicate.features.shared import polymarket_us_auth, polymarket_us_markets

    state = {"gate": threading.Event(), "threads": [], "finished": threading.Event()}

    def persist():
        state["threads"].append(threading.get_ident())
        state["gate"].wait(5)
        state["finished"].set()
        return {"status": "ok", "written": True, "count": 1}

    monkeypatch.setattr(polymarket_us_markets, "persist_game_slate", persist)
    monkeypatch.setattr(polymarket_us_auth, "credentials_present", lambda: True)
    monkeypatch.setattr(worker, "_polymarket_daily_book", lambda: None)
    monkeypatch.setattr(worker, "_POLYMARKET_SLATE_LAST_RUN", 0.0)
    monkeypatch.setattr(worker, "_POLYMARKET_SLATE_BG_THREAD", None)
    monkeypatch.delenv("SYNDICATE_POLYMARKET_US_SLATE_REFRESH_ENABLED", raising=False)
    monkeypatch.delenv("SYNDICATE_POLYMARKET_US_SLATE_INTERVAL_SECONDS", raising=False)
    monkeypatch.delenv(ENV, raising=False)
    yield state
    state["gate"].set()
    t = worker._POLYMARKET_SLATE_BG_THREAD
    if t is not None:
        t.join(5)


def _wait_for(pred, seconds=5.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


# ---------------------------------------------------------------------------
# off != on, through the step the main loop calls
# ---------------------------------------------------------------------------


def test_off_absent_runs_the_sweep_inline_on_the_calling_thread(venue):
    venue["gate"].set()
    assert worker._main_loop_polymarket_slate_step() == "inline"
    assert venue["threads"] == [threading.get_ident()], "off must page the venue on the main loop's own thread"
    assert venue["finished"].is_set(), "off returns only after the sweep is done (today's behaviour)"
    assert worker._POLYMARKET_SLATE_BG_THREAD is None


def test_on_returns_before_the_sweep_ends_and_the_sweep_runs_on_another_thread(venue, monkeypatch):
    monkeypatch.setenv(ENV, "1")
    started = time.monotonic()
    assert worker._main_loop_polymarket_slate_step() == "background"
    assert time.monotonic() - started < 1.0, "the step must not wait for the sweep"
    assert not venue["finished"].is_set(), "the sweep is still in flight when the step returns"
    assert _wait_for(lambda: venue["threads"]), "the background sweep never started"
    assert venue["threads"][0] != threading.get_ident(), "on must never page the venue on the calling thread"
    venue["gate"].set()
    worker._POLYMARKET_SLATE_BG_THREAD.join(5)
    assert venue["finished"].is_set()
    assert not worker._POLYMARKET_SLATE_LOCK.locked(), "the writer's lock is released after a background sweep"


def test_off_and_on_differ_on_the_same_due_sweep(venue, monkeypatch):
    """The reachability pair in one place: the same due sweep, opposite threads."""
    venue["gate"].set()
    assert worker._main_loop_polymarket_slate_step() == "inline"
    off_thread = venue["threads"][-1]
    monkeypatch.setattr(worker, "_POLYMARKET_SLATE_LAST_RUN", 0.0)  # due again
    monkeypatch.setenv(ENV, "on")
    assert worker._main_loop_polymarket_slate_step() == "background"
    worker._POLYMARKET_SLATE_BG_THREAD.join(5)
    on_thread = venue["threads"][-1]
    assert off_thread == threading.get_ident() != on_thread


# ---------------------------------------------------------------------------
# single flight and the gate, when on
# ---------------------------------------------------------------------------


def test_on_a_second_step_while_the_background_sweep_runs_does_not_start_another(venue, monkeypatch):
    monkeypatch.setenv(ENV, "1")
    assert worker._main_loop_polymarket_slate_step() == "background"
    assert _wait_for(lambda: venue["threads"])
    first_thread = worker._POLYMARKET_SLATE_BG_THREAD
    monkeypatch.setattr(worker, "_POLYMARKET_SLATE_LAST_RUN", 0.0)  # only the in-flight check can stop it
    assert worker._main_loop_polymarket_slate_step() == "in_flight"
    assert worker._POLYMARKET_SLATE_BG_THREAD is first_thread
    venue["gate"].set()
    first_thread.join(5)
    assert len(venue["threads"]) == 1, "a second sweep started while one was in flight"


def test_on_the_venue_poll_holding_the_lock_is_in_flight_and_starts_no_thread(venue, monkeypatch):
    monkeypatch.setenv(ENV, "1")
    assert worker._POLYMARKET_SLATE_LOCK.acquire(blocking=False)
    try:
        assert worker._main_loop_polymarket_slate_step() == "in_flight"
    finally:
        worker._POLYMARKET_SLATE_LOCK.release()
    assert worker._POLYMARKET_SLATE_BG_THREAD is None
    assert venue["threads"] == []


def test_on_not_due_starts_no_thread(venue, monkeypatch):
    monkeypatch.setenv(ENV, "1")
    monkeypatch.setattr(worker, "_POLYMARKET_SLATE_LAST_RUN", time.time())  # just swept
    assert worker._main_loop_polymarket_slate_step() == "not_due"
    assert worker._POLYMARKET_SLATE_BG_THREAD is None
    assert venue["threads"] == []


def test_on_the_due_check_uses_the_writers_own_interval(venue, monkeypatch):
    monkeypatch.setenv(ENV, "1")
    monkeypatch.setenv("SYNDICATE_POLYMARKET_US_SLATE_INTERVAL_SECONDS", "600")
    monkeypatch.setattr(worker, "_POLYMARKET_SLATE_LAST_RUN", time.time() - 300)  # due at 180 s, not at 600 s
    assert worker._main_loop_polymarket_slate_step() == "not_due"
    assert worker._polymarket_us_slate_interval_seconds() == 600


def test_a_background_failure_is_printed_not_lost(monkeypatch, capsys):
    monkeypatch.setenv(ENV, "1")
    monkeypatch.setattr(worker, "_POLYMARKET_SLATE_LAST_RUN", 0.0)
    monkeypatch.setattr(worker, "_POLYMARKET_SLATE_BG_THREAD", None)

    def boom():
        raise RuntimeError("venue down")

    monkeypatch.setattr(worker, "_polymarket_us_slate_refresh_tick", boom)
    assert worker._main_loop_polymarket_slate_step() == "background"
    worker._POLYMARKET_SLATE_BG_THREAD.join(5)
    assert "POLYMARKET_SLATE_BACKGROUND_FAILED RuntimeError: venue down" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# the switch and the wiring
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw,expected", [
    (None, False), ("", False), ("0", False), ("off", False), ("false", False), ("no", False), ("maybe", False),
    ("1", True), ("on", True), ("true", True), ("yes", True), (" ON ", True),
])
def test_switch_values(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv(ENV, raising=False)
    else:
        monkeypatch.setenv(ENV, raw)
    assert worker._polymarket_slate_main_loop_background_enabled() is expected


def test_the_main_loop_reaches_the_writer_only_through_the_step():
    """If the loop also called the writer directly, the switch would not move the sweep off the loop."""
    source = inspect.getsource(worker.main)
    _, _, inside_loop = source.partition("while not _LIVE_REFRESH_LOOP_STOP.is_set():")
    assert inside_loop
    assert inside_loop.count("_main_loop_polymarket_slate_step()") == 1
    assert "_polymarket_us_slate_refresh_tick()" not in inside_loop


def test_the_writer_and_the_step_share_one_interval_resolver():
    assert "_polymarket_us_slate_interval_seconds()" in inspect.getsource(worker._polymarket_us_slate_refresh_tick)
    assert "_polymarket_us_slate_interval_seconds()" in inspect.getsource(worker._main_loop_polymarket_slate_step)
