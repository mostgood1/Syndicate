"""The Polymarket boot work runs OFF the main thread (lane `layer2-freshness-1h`, 2026-10-03).

MEASURED on the fleet, restart 2026-10-02 23:09:05Z: before the main loop, the
slate probe (23:09:14-23:14:01) and the slate writer (23:14:05-23:17:59) each paged
the full ~78k-row Polymarket catalogue, so `loop_start` came at 23:18:17 and the
first odds sweep at 23:22:16 -- and every restart aged pregame rows past the 1h gate.
"""
from __future__ import annotations

import ast
from pathlib import Path

import scripts.run_live_odds_refresh_worker as worker

SOURCE = (Path(__file__).resolve().parents[1] / "scripts" / "run_live_odds_refresh_worker.py").read_text(encoding="utf-8-sig")


def _main_calls_before_loop() -> list[str]:
    tree = ast.parse(SOURCE)
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    loop = next(n for n in ast.walk(main) if isinstance(n, ast.While))
    names = []
    for node in ast.walk(main):
        if isinstance(node, ast.Call) and node.lineno < loop.lineno:
            fn = node.func
            names.append(fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", ""))
    return names


def test_reachability_main_no_longer_pages_the_catalogue_before_the_loop():
    before = _main_calls_before_loop()
    assert "start_venue_boot_then_poll" in before
    for slow in ("_polymarket_us_slate_probe_at_boot", "_polymarket_us_slate_refresh_tick", "start_venue_poll_loop"):
        assert slow not in before, f"{slow} runs synchronously before the main loop again"


def test_the_writer_runs_first_and_the_poll_last(monkeypatch):
    order = []
    monkeypatch.setattr(worker, "_polymarket_us_slate_refresh_tick", lambda: order.append("writer"))
    monkeypatch.setattr(worker, "_polymarket_us_slate_probe_at_boot", lambda: order.append("probe"))
    monkeypatch.setattr(worker, "_polymarket_spread_sign_audit_at_boot", lambda: order.append("spread_audit"))
    monkeypatch.setattr(worker, "_polymarket_offset_boundary_probe_at_boot", lambda: order.append("offset_probe"))
    monkeypatch.setattr(worker, "start_venue_poll_loop", lambda: order.append("poll") or False)
    worker._venue_boot_sequence()
    assert order == ["writer", "probe", "spread_audit", "offset_probe", "poll"]


def test_a_failing_step_does_not_cost_the_poll(monkeypatch, capsys):
    order = []

    def boom():
        raise RuntimeError("venue down")

    monkeypatch.setattr(worker, "_polymarket_us_slate_refresh_tick", boom)
    monkeypatch.setattr(worker, "_polymarket_us_slate_probe_at_boot", lambda: order.append("probe"))
    monkeypatch.setattr(worker, "_polymarket_spread_sign_audit_at_boot", lambda: None)
    monkeypatch.setattr(worker, "_polymarket_offset_boundary_probe_at_boot", lambda: None)
    monkeypatch.setattr(worker, "start_venue_poll_loop", lambda: order.append("poll") or False)
    worker._venue_boot_sequence()
    assert order == ["probe", "poll"]
    assert "VENUE_BOOT_STEP_FAILED step=boom RuntimeError: venue down" in capsys.readouterr().out


def test_the_starter_returns_without_waiting(monkeypatch):
    import threading
    import time

    gate = threading.Event()
    monkeypatch.setattr(worker, "_venue_boot_sequence", lambda: gate.wait(5))
    t0 = time.monotonic()
    assert worker.start_venue_boot_then_poll() is True
    assert time.monotonic() - t0 < 1.0, "the boot sequence must not block main()"
    gate.set()
