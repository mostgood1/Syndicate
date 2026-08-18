"""Phase 2: the WNBA full refresh finally has a scheduled caller.

WHY THIS EXISTS. Phase 1 of the migration off the daily-update GHA cron moved
NFL/NCAAF/NCAAB to refresh-worker's weekly autorun. WNBA was never re-homed, so
NOTHING called `refresh_wnba_oddsapi_props.main()` on any cadence. Measured
2026-08-17: `MAIN_ENTRY` 0 hits over 8h on BOTH workers, `GAME_CARDS_CENSUS` 0
over ~2 days with the emitter confirmed present in both deployed SHAs. The GHA
cron cannot cover it either -- `RUN_FULL_PIPELINE` is read from
`github.event.inputs`, which is empty on the `schedule` trigger.

The consequence was that a shipped and correct `game_cards` coverage fix could
not be measured at all, because its code path was never entered.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location(
        "live_odds_worker_under_test", _REPO / "scripts" / "run_live_odds_refresh_worker.py"
    )
    m = importlib.util.module_from_spec(spec)
    sys.modules["live_odds_worker_under_test"] = m
    spec.loader.exec_module(m)
    return m


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for key in (
        "SYNDICATE_ENABLE_WNBA_PREGAME_REFRESH_AUTORUN",
        "SYNDICATE_WNBA_PREGAME_REFRESH_INTERVAL_SECONDS",
    ):
        monkeypatch.delenv(key, raising=False)
    yield


# --------------------------------------------------------------------------
# The safety properties. These matter more than the happy path.
# --------------------------------------------------------------------------


def test_it_is_OFF_unless_explicitly_enabled(mod, monkeypatch):
    """DEFAULT OFF, deliberately.

    New periodic worker work is never free -- `#241` caused a production restart
    loop -- and this lands on a 2GB service that already OOMs under WNBA load.
    Absent must mean off, the opposite of `_mlb_refresh_tick_owner_here`.
    """
    assert mod._wnba_pregame_refresh_enabled() is False
    called = []
    monkeypatch.setattr(mod, "launch_refresh_run", lambda **kw: called.append(kw))
    mod._launch_autorun_wnba_pregame_refresh()
    assert called == [], "a disabled autorun must not launch anything"


@pytest.mark.parametrize("value", ["1", "true", "yes", "on", "TRUE"])
def test_the_enable_flag_accepts_the_same_spellings_as_soccer(mod, monkeypatch, value):
    monkeypatch.setenv("SYNDICATE_ENABLE_WNBA_PREGAME_REFRESH_AUTORUN", value)
    assert mod._wnba_pregame_refresh_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "  "])
def test_anything_else_is_off(mod, monkeypatch, value):
    monkeypatch.setenv("SYNDICATE_ENABLE_WNBA_PREGAME_REFRESH_AUTORUN", value)
    assert mod._wnba_pregame_refresh_enabled() is False


def test_it_requests_PREGAME_phase_and_wnba_only(mod, monkeypatch, tmp_path):
    """THE MOST IMPORTANT ASSERTION IN THIS FILE.

    `phase="pregame"` is load-bearing, not copied from soccer. This worker is
    2GB and already carries WNBA SmartSim + live-lens load; `render.yaml`
    records sim workers cut to 1 and the WNBA sim count cut 500 -> 250 -> 100
    fighting for that memory, against a WNBA refresh leg measured at ~1.3-1.5GB
    RSS. Pregame excludes the sim leg. **A full-phase autorun here would OOM the
    service**, so this pins the phase rather than trusting a reviewer to notice.
    """
    monkeypatch.setenv("SYNDICATE_ENABLE_WNBA_PREGAME_REFRESH_AUTORUN", "1")
    monkeypatch.setattr(mod, "_wnba_active_for_date", lambda d: True)
    monkeypatch.setattr(mod, "_wnba_pregame_autorun_status_path", lambda: tmp_path / "s.json")
    monkeypatch.setattr(mod, "read_json_file", lambda p: {})
    monkeypatch.setattr(mod, "write_json_file", lambda p, v: None)
    seen = {}
    monkeypatch.setattr(mod, "launch_refresh_run", lambda **kw: seen.update(kw) or {})
    mod._launch_autorun_wnba_pregame_refresh()
    assert seen.get("phase") == "pregame", "full phase would OOM this 2GB worker"
    assert seen.get("sports") == "wnba", "must not widen to other sports"
    assert seen.get("skip_mirror") is True


def test_it_does_nothing_when_wnba_is_out_of_season(mod, monkeypatch):
    monkeypatch.setenv("SYNDICATE_ENABLE_WNBA_PREGAME_REFRESH_AUTORUN", "1")
    monkeypatch.setattr(mod, "_wnba_active_for_date", lambda d: False)
    called = []
    monkeypatch.setattr(mod, "launch_refresh_run", lambda **kw: called.append(kw))
    mod._launch_autorun_wnba_pregame_refresh()
    assert called == []


def test_the_cadence_gate_suppresses_a_second_launch(mod, monkeypatch, tmp_path):
    monkeypatch.setenv("SYNDICATE_ENABLE_WNBA_PREGAME_REFRESH_AUTORUN", "1")
    monkeypatch.setattr(mod, "_wnba_active_for_date", lambda d: True)
    monkeypatch.setattr(mod, "_wnba_pregame_autorun_status_path", lambda: tmp_path / "s.json")
    monkeypatch.setattr(mod, "write_json_file", lambda p, v: None)
    # A run that happened one second ago, against the 4h default interval.
    monkeypatch.setattr(mod, "read_json_file", lambda p: {"epoch": mod.time.time() - 1.0, "reported": True})
    called = []
    monkeypatch.setattr(mod, "launch_refresh_run", lambda **kw: called.append(kw))
    mod._launch_autorun_wnba_pregame_refresh()
    assert called == [], "inside the interval, it must not relaunch"


def test_a_stale_marker_allows_the_next_launch(mod, monkeypatch, tmp_path):
    monkeypatch.setenv("SYNDICATE_ENABLE_WNBA_PREGAME_REFRESH_AUTORUN", "1")
    monkeypatch.setattr(mod, "_wnba_active_for_date", lambda d: True)
    monkeypatch.setattr(mod, "_wnba_pregame_autorun_status_path", lambda: tmp_path / "s.json")
    monkeypatch.setattr(mod, "write_json_file", lambda p, v: None)
    monkeypatch.setattr(mod, "read_json_file", lambda p: {"epoch": mod.time.time() - 99999.0, "reported": True})
    called = []
    monkeypatch.setattr(mod, "launch_refresh_run", lambda **kw: called.append(kw) or {})
    mod._launch_autorun_wnba_pregame_refresh()
    assert len(called) == 1


def test_a_launch_failure_is_recorded_and_reported_not_swallowed(mod, monkeypatch, tmp_path, capsys):
    """`#433`: soccer odds stopped for FOUR DAYS with no visible error, because
    `launch_refresh_run` spawns detached with stdout/stderr to DEVNULL. A silent
    WNBA autorun would reproduce exactly the invisibility this lane exists to
    fix, so a failure must both persist and print."""
    monkeypatch.setenv("SYNDICATE_ENABLE_WNBA_PREGAME_REFRESH_AUTORUN", "1")
    monkeypatch.setattr(mod, "_wnba_active_for_date", lambda d: True)
    monkeypatch.setattr(mod, "_wnba_pregame_autorun_status_path", lambda: tmp_path / "s.json")
    monkeypatch.setattr(mod, "read_json_file", lambda p: {})
    written = {}
    monkeypatch.setattr(mod, "write_json_file", lambda p, v: written.update(v))

    def _boom(**kw):
        raise RuntimeError("launch exploded")

    monkeypatch.setattr(mod, "launch_refresh_run", _boom)
    mod._launch_autorun_wnba_pregame_refresh()
    assert "RuntimeError" in str(written.get("error")), "the failure must persist"
    assert "WNBA_PREGAME_AUTORUN_FAILED" in capsys.readouterr().out, "and must be visible"


def test_the_previous_run_is_reported_BEFORE_the_cadence_gate(mod, monkeypatch, tmp_path, capsys):
    """Reporting after the gate would surface the previous outcome up to 4 hours
    late -- most of the way back to the silence being fixed."""
    monkeypatch.setenv("SYNDICATE_ENABLE_WNBA_PREGAME_REFRESH_AUTORUN", "1")
    monkeypatch.setattr(mod, "_wnba_active_for_date", lambda d: True)
    monkeypatch.setattr(mod, "_wnba_pregame_autorun_status_path", lambda: tmp_path / "s.json")
    monkeypatch.setattr(mod, "write_json_file", lambda p, v: None)
    # Inside the interval, so the gate returns early -- the report must still fire.
    monkeypatch.setattr(
        mod, "read_json_file",
        lambda p: {"epoch": mod.time.time() - 1.0, "reported": True, "date": "2026-08-18", "error": "Boom: x"},
    )
    monkeypatch.setattr(mod, "launch_refresh_run", lambda **kw: {})
    mod._launch_autorun_wnba_pregame_refresh()
    out = capsys.readouterr().out
    assert "WNBA_PREGAME_AUTORUN_PREV" in out and "FAILED" in out


def test_it_is_wired_into_the_tick_loop_and_cannot_take_soccer_down(mod):
    """Presence is not reachability -- four inert fixes turned up this session
    by skipping this check. The call must exist AND be independently guarded."""
    src = (_REPO / "scripts" / "run_live_odds_refresh_worker.py").read_text(encoding="utf-8")
    assert "_launch_autorun_wnba_pregame_refresh()" in src, "defined but never called"
    assert "WNBA_PREGAME_AUTORUN_ERROR" in src, "its call site needs its own try/except"
    assert src.count("_launch_autorun_wnba_pregame_refresh") >= 2, "definition plus call site"
