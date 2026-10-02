"""live-odds-worker stops within seconds of SIGTERM, not after its idle sleep.

Measured 2026-10-02 on the local fleet: SIGTERM at ~16:38:30Z, exit at
16:53:25Z. The main loop ended each pass with `time.sleep(sleep_seconds)` (900s
idle), and a caught signal does not cut a time.sleep short (PEP 475), so the
stop flag `_handle_stop` set went unread for the rest of the sleep.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
import threading
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "run_live_odds_refresh_worker.py"


@pytest.fixture(scope="module")
def worker():
    spec = importlib.util.spec_from_file_location("run_live_odds_refresh_worker", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_live_odds_refresh_worker"] = module
    spec.loader.exec_module(module)
    return module


def _main_calls() -> set[str]:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    names = set()
    for node in ast.walk(main):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            names.add(f"{node.func.value.id}.{node.func.attr}")
    return names


def test_main_loop_sleeps_on_the_stop_event_not_time_sleep():
    calls = _main_calls()
    assert "time.sleep" not in calls
    assert "_LIVE_REFRESH_LOOP_STOP.wait" in calls


def test_the_stop_handler_wakes_a_long_wait_at_once(worker):
    """Behaviour, not spelling: the event the loop waits on is the one the
    SIGTERM handler sets, so a 900s wait returns as soon as the handler runs."""
    stop = worker._LIVE_REFRESH_LOOP_STOP
    stop.clear()
    try:
        threading.Timer(0.2, worker._handle_stop, args=(15, None)).start()
        started = time.monotonic()
        woke = stop.wait(900)
        assert woke is True
        assert time.monotonic() - started < 5
    finally:
        stop.clear()
