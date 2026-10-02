"""live-odds-worker names the signal that stopped it (lane `layer2-freshness-1h`, 2026-10-02).

Three clean mid-sleep exits that day could not be attributed: only the signal
handler sets the stop event, and it logged nothing.
"""
from __future__ import annotations

import signal

import pytest

from scripts import run_live_odds_refresh_worker as worker


@pytest.fixture(autouse=True)
def _clear_stop():
    worker._LIVE_REFRESH_LOOP_STOP.clear()
    yield
    worker._LIVE_REFRESH_LOOP_STOP.clear()


def test_the_handler_logs_the_signal_and_still_stops(capsys):
    worker._handle_stop(signal.SIGTERM, None)
    out = capsys.readouterr().out
    assert "STOP_SIGNAL signal=SIGTERM" in out
    assert "pid=" in out and "ppid=" in out and "utc=" in out
    assert worker._LIVE_REFRESH_LOOP_STOP.is_set()


def test_an_unknown_signal_number_is_logged_raw_and_still_stops(capsys):
    worker._handle_stop(9999, None)
    assert "STOP_SIGNAL signal=9999" in capsys.readouterr().out
    assert worker._LIVE_REFRESH_LOOP_STOP.is_set()


def test_a_logging_failure_never_prevents_the_stop(monkeypatch):
    def _boom(*args, **kwargs):
        raise OSError("stdout gone")

    monkeypatch.setattr("builtins.print", _boom)
    worker._handle_stop(signal.SIGINT, None)
    assert worker._LIVE_REFRESH_LOOP_STOP.is_set()
