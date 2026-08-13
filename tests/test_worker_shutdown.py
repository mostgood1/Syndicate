"""`#409` phase 1 -- record what was in flight when a worker is killed.

refresh-worker installed NO signal handler, so every deploy killed it silently
and a board build 20 minutes into a 23-minute run left nothing behind.

THE TEST THAT MATTERS MOST IS THE EXIT. Installing a handler changes what
SIGTERM does: today the default terminates immediately, and a handler that
records and RETURNS would leave the worker ignoring the signal until Render
SIGKILLs it -- converting a clean stop into a hard kill and making the situation
worse than the bug being fixed.
"""

from __future__ import annotations

import json
import pytest
import signal
import subprocess
import sys
import textwrap

from syndicate.features.shared import worker_shutdown as ws


def test_the_record_names_the_worker_and_the_signal():
    record = ws.build_shutdown_record("refresh-worker", "SIGTERM")
    assert record["worker"] == "refresh-worker"
    assert record["signal"] == "SIGTERM"
    assert isinstance(record["uptime_seconds"], int)
    assert "board_build" in record and "threads" in record


def test_it_detects_a_board_build_from_the_live_stack():
    """Inferred from `sys._current_frames()` rather than from a flag the build
    sets, so it needs no change in intelligence.py -- a file another lane is
    actively editing."""
    seen = {}

    def collect_candidates():  # name matches _BUILD_FRAME_MARKERS
        seen["record"] = ws.build_shutdown_record("refresh-worker", "SIGTERM")

    collect_candidates()
    build = seen["record"]["board_build"]
    assert build["in_flight"] is True
    assert build["frame"] == "collect_candidates"


def test_no_build_running_reports_not_in_flight():
    build = ws.build_shutdown_record("refresh-worker", "SIGTERM")["board_build"]
    assert build["in_flight"] is False
    assert build["frame"] is None


def test_registered_work_appears_with_its_age():
    ws.mark_in_flight("mlb_sim")
    try:
        record = ws.build_shutdown_record("refresh-worker", "SIGTERM")
        assert "mlb_sim" in record["registered_in_flight"]
    finally:
        ws.clear_in_flight("mlb_sim")
    assert "mlb_sim" not in ws.build_shutdown_record("refresh-worker", "SIGTERM")["registered_in_flight"]


def test_building_a_record_never_raises_even_when_helpers_fail(monkeypatch):
    """A worker's job is not to record its own death. Nothing here may throw."""
    monkeypatch.setattr(ws, "_interesting_children", lambda: (_ for _ in ()).throw(RuntimeError("procfs gone")))
    try:
        ws.build_shutdown_record("refresh-worker", "SIGTERM")
    except Exception:
        # _interesting_children is called inside build_shutdown_record; if it
        # propagates that is the bug this asserts against.
        raise AssertionError("build_shutdown_record propagated an exception")


def test_the_handler_EXITS_rather_than_returning(monkeypatch):
    """THE LOAD-BEARING ASSERTION, tested cross-platform by intercepting the exit.

    Installing a handler changes what SIGTERM does. The default terminates
    immediately; a handler that records and RETURNS would leave the worker
    ignoring the signal until Render SIGKILLs it -- strictly worse than the
    no-handler behaviour this replaces. So the handler must call os._exit.
    """
    exits = []
    monkeypatch.setattr(ws.os, "_exit", lambda code: exits.append(code))

    installed = {}
    monkeypatch.setattr(ws.signal, "signal", lambda sig, fn: installed.setdefault(sig, fn))
    ws.install_shutdown_recorder("test-worker")

    handler = installed.get(signal.SIGTERM)
    assert handler is not None, "SIGTERM handler was not installed"
    handler(int(signal.SIGTERM), None)
    assert exits == [0], "handler returned without exiting -- worker would ignore SIGTERM"


def test_the_handler_still_exits_when_recording_blows_up(monkeypatch):
    """A failure to record must not become a failure to die."""
    exits = []
    monkeypatch.setattr(ws.os, "_exit", lambda code: exits.append(code))
    monkeypatch.setattr(ws, "build_shutdown_record", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    installed = {}
    monkeypatch.setattr(ws.signal, "signal", lambda sig, fn: installed.setdefault(sig, fn))
    ws.install_shutdown_recorder("test-worker")
    installed[signal.SIGTERM](int(signal.SIGTERM), None)
    assert exits == [0]


@pytest.mark.skipif(sys.platform.startswith("win"), reason=(
    "Windows send_signal(SIGTERM) calls TerminateProcess and never runs Python "
    "handlers, so this asserts nothing here. The end-to-end signal path is "
    "therefore UNVERIFIED on this dev platform and only verified by "
    "construction until it runs on Render (Linux)."))
def test_end_to_end_a_signalled_process_records_and_dies():
    script = textwrap.dedent(
        """
        import os, sys, time
        sys.path.insert(0, os.getcwd())
        from syndicate.features.shared.worker_shutdown import install_shutdown_recorder
        install_shutdown_recorder("test-worker")
        print("READY", flush=True)
        time.sleep(60)
        print("SHOULD NOT REACH HERE", flush=True)
        """
    )
    proc = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    try:
        assert proc.stdout is not None
        assert "READY" in proc.stdout.readline()
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=20)
        rest = proc.stdout.read()
        assert "SHOULD NOT REACH HERE" not in rest
        assert "WORKER_SHUTDOWN" in rest, rest[:400]
    finally:
        if proc.poll() is None:
            proc.kill(); proc.wait(timeout=10)


def test_the_shutdown_line_is_parseable_json():
    record = ws.build_shutdown_record("refresh-worker", "SIGTERM")
    line = f"[worker_shutdown] WORKER_SHUTDOWN {json.dumps(record, sort_keys=True, default=str)}"
    payload = json.loads(line.split("WORKER_SHUTDOWN", 1)[1].strip())
    assert payload["worker"] == "refresh-worker"


def test_the_handler_exits_even_on_a_BASEexception(monkeypatch):
    """The gap `except Exception` leaves open, raised in review by oversight.

    KeyboardInterrupt from a second signal arriving mid-handler, SystemExit,
    anything outside the Exception hierarchy -- each would escape a plain
    `except Exception` and skip the exit, putting us back in the SIGKILL case
    this module exists to avoid. `sys._current_frames()` inspection is the
    riskiest thing in the handler and it runs in a signal context.
    """
    for blowup in (KeyboardInterrupt, SystemExit, GeneratorExit):
        exits = []
        monkeypatch.setattr(ws.os, "_exit", lambda code: exits.append(code))
        monkeypatch.setattr(
            ws, "build_shutdown_record",
            lambda *a, **k: (_ for _ in ()).throw(blowup("mid-handler")),
        )
        installed = {}
        monkeypatch.setattr(ws.signal, "signal", lambda sig, fn: installed.setdefault(sig, fn))
        ws.install_shutdown_recorder("test-worker")
        installed[signal.SIGTERM](int(signal.SIGTERM), None)
        assert exits == [0], f"{blowup.__name__} escaped the handler and skipped the exit"


def test_the_handler_exits_even_if_the_failure_print_also_fails(monkeypatch):
    """Belt and braces: the fallback logging path must not become the thing
    that prevents the exit."""
    exits = []
    monkeypatch.setattr(ws.os, "_exit", lambda code: exits.append(code))
    monkeypatch.setattr(ws, "build_shutdown_record", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    import builtins

    real_print = builtins.print
    monkeypatch.setattr(builtins, "print", lambda *a, **k: (_ for _ in ()).throw(OSError("stdout gone")))
    installed = {}
    monkeypatch.setattr(ws.signal, "signal", lambda sig, fn: installed.setdefault(sig, fn))
    try:
        ws.install_shutdown_recorder("test-worker")
        installed[signal.SIGTERM](int(signal.SIGTERM), None)
    finally:
        monkeypatch.setattr(builtins, "print", real_print)
    assert exits == [0]
