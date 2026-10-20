"""NBA in-play prices on their own fast lane (lane `nba-live-board`, user 2026-10-20: "layer 2 board isnt showing actuals
for NBA live props or live sim projections"). Measured that afternoon: no BOS @ DET quote seen in 15 minutes while the
game was in play -- the shared live sweep was refused `lane_busy` for 10+ minutes at a time, and the NBA live phase ran
without --force-refresh, so the props refresh re-served the pregame snapshot."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from syndicate.features.shared import live_refresh_loop

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def worker(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("nba_live_worker_under_test", ROOT / "scripts" / "run_live_odds_refresh_worker.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    store: dict = {}
    monkeypatch.setattr(mod, "reports_root", lambda: tmp_path)
    monkeypatch.setattr(mod, "read_json_file", lambda path: store.get(str(path)))
    monkeypatch.setattr(mod, "write_json_file", lambda path, doc: store.__setitem__(str(path), dict(doc)))
    monkeypatch.setattr(mod, "central_today_iso", lambda: "2026-10-20")
    monkeypatch.setattr(live_refresh_loop, "_nba_has_live_game", lambda day: True)
    calls: list = []
    monkeypatch.setattr(mod, "launch_refresh_run", lambda **kw: calls.append(kw) or {"runStamp": "r1"})
    monkeypatch.delenv("SYNDICATE_ENABLE_NBA_LIVE_REFRESH_AUTORUN", raising=False)
    mod._calls, mod._store = calls, store
    return mod


def test_a_live_nba_game_launches_a_forced_nba_only_live_run_on_its_own_lane(worker):
    worker._launch_autorun_nba_live_refresh()
    assert len(worker._calls) == 1
    kw = worker._calls[0]
    assert (kw["sports"], kw["phase"], kw["mode"]) == ("nba", "live", "fast")
    assert kw["force_refresh"] is True and kw["force_refresh_sports"] == "nba"     # never the pregame snapshot again
    assert kw["lane"] == "live-odds-worker-nba-live"                               # not the shared sweep's lane


def test_it_waits_its_interval_and_skips_when_no_game_is_live(worker, monkeypatch):
    worker._launch_autorun_nba_live_refresh()
    worker._launch_autorun_nba_live_refresh()                                      # inside 240 s: no second run
    assert len(worker._calls) == 1
    worker._store.clear()
    monkeypatch.setattr(live_refresh_loop, "_nba_has_live_game", lambda day: False)
    worker._launch_autorun_nba_live_refresh()
    assert len(worker._calls) == 1


def test_a_busy_lane_keeps_the_last_epoch_so_the_next_tick_retries(worker, monkeypatch):
    worker._launch_autorun_nba_live_refresh()
    path = str(worker._nba_live_autorun_status_path())
    first_epoch = worker._store[path]["epoch"]

    def busy(**kw):
        raise ValueError("A refresh run is already active (pid 1)")

    monkeypatch.setattr(worker, "launch_refresh_run", busy)
    monkeypatch.setattr(worker, "_is_refresh_run_contention_error", lambda exc: True)
    worker._store[path]["epoch"] = first_epoch - 1000                              # interval elapsed
    worker._launch_autorun_nba_live_refresh()
    assert worker._store[path]["epoch"] == first_epoch - 1000 and "already active" in worker._store[path]["error"]


def test_the_off_switch_and_the_tick_wiring(worker, monkeypatch):
    monkeypatch.setenv("SYNDICATE_ENABLE_NBA_LIVE_REFRESH_AUTORUN", "0")
    worker._launch_autorun_nba_live_refresh()
    assert worker._calls == []
    source = (ROOT / "scripts" / "run_live_odds_refresh_worker.py").read_text(encoding="utf-8")
    tick = source[source.index("def _launch_inplay_capture_autoruns"):]
    assert "_launch_autorun_nba_live_refresh()" in tick[:2500]
