"""`wnba-live-odds-capture-gap`. WNBA's own live-phase refresh, isolated.

WHY THIS EXISTS. The pregame autorun (`test_wnba_pregame_autorun.py`) keeps
WNBA's odds fresh before tip-off; nothing kept them fresh AFTER it. Measured
live 2026-08-20: the general combined `phase=live` sweep (`sports=mlb,wnba,
soccer`, one launch per ~60-70s tick) genuinely takes several minutes to run,
so almost every tick's `launch_refresh_run` collided with its OWN still-running
prior launch (`ValueError: A refresh run is already active`, repeating for
16+ minutes straight against a single service's own lane). A real WNBA game's
odds sat frozen at a single pregame quote for 2+ hours because of it, despite
`_build_wnba_steps` firing correctly on paper every cycle.

The fix mirrors the pregame autorun's own shape exactly: an independent,
WNBA-only live trigger with its own cadence and an EXPLICIT, distinct refresh
lane, so it can never contend with the general combined sweep's lane no
matter how badly that one is still starved.
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
        "SYNDICATE_ENABLE_WNBA_LIVE_REFRESH_AUTORUN",
        "SYNDICATE_WNBA_LIVE_REFRESH_INTERVAL_SECONDS",
        "SYNDICATE_WNBA_LIVE_REFRESH_LANE",
    ):
        monkeypatch.delenv(key, raising=False)
    yield


# --------------------------------------------------------------------------
# The safety properties. These matter more than the happy path.
# --------------------------------------------------------------------------


def test_it_is_OFF_unless_explicitly_enabled(mod, monkeypatch):
    """DEFAULT OFF, deliberately -- same convention as every other autorun
    in this file. New periodic worker work is never free (`#241`)."""
    assert mod._wnba_live_refresh_enabled() is False
    called = []
    monkeypatch.setattr(mod, "launch_refresh_run", lambda **kw: called.append(kw))
    mod._launch_autorun_wnba_live_refresh()
    assert called == [], "a disabled autorun must not launch anything"


@pytest.mark.parametrize("value", ["1", "true", "yes", "on", "TRUE"])
def test_the_enable_flag_accepts_the_same_spellings_as_the_pregame_autorun(mod, monkeypatch, value):
    monkeypatch.setenv("SYNDICATE_ENABLE_WNBA_LIVE_REFRESH_AUTORUN", value)
    assert mod._wnba_live_refresh_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "  "])
def test_anything_else_is_off(mod, monkeypatch, value):
    monkeypatch.setenv("SYNDICATE_ENABLE_WNBA_LIVE_REFRESH_AUTORUN", value)
    assert mod._wnba_live_refresh_enabled() is False


def test_it_does_nothing_when_no_wnba_game_is_actually_live(mod, monkeypatch):
    """The pregame gate checks "WNBA active today"; this one must check
    something stronger -- there is nothing to refresh live-side when nothing
    is live, and firing anyway is pure waste on a service already tight on
    memory."""
    monkeypatch.setenv("SYNDICATE_ENABLE_WNBA_LIVE_REFRESH_AUTORUN", "1")
    monkeypatch.setattr(mod, "_wnba_has_live_game", lambda d: False)
    called = []
    monkeypatch.setattr(mod, "launch_refresh_run", lambda **kw: called.append(kw))
    mod._launch_autorun_wnba_live_refresh()
    assert called == []


def test_it_requests_LIVE_phase_wnba_only_FAST_mode_and_its_OWN_lane(mod, monkeypatch, tmp_path):
    """THE MOST IMPORTANT ASSERTION IN THIS FILE.

    Four load-bearing, independently-checked properties:
      - phase="live": this is the whole point, refreshing DURING the game.
      - sports="wnba": must not widen to other sports (that recreates the
        exact combined-sweep starvation this exists to route around).
      - mode="fast": `test_wnba_pregame_autorun.py`'s own warning applies
        doubly here -- "a full-phase autorun here would OOM the service",
        against a refresh leg measured at ~1.3-1.5GB RSS -- and this one is
        meant to repeat every few minutes for as long as a game is live, not
        once per ~4h. `mode="full"` would enter the SmartSim prediction
        branch on every single one of those repeats.
      - lane=<something distinct>: THE fix. Reusing the default/unscoped
        lane would let this collide with the general combined sweep's own
        (already self-colliding) lane, reproducing the exact starvation
        being fixed.
    """
    monkeypatch.setenv("SYNDICATE_ENABLE_WNBA_LIVE_REFRESH_AUTORUN", "1")
    monkeypatch.setattr(mod, "_wnba_has_live_game", lambda d: True)
    monkeypatch.setattr(mod, "_wnba_live_autorun_status_path", lambda: tmp_path / "s.json")
    monkeypatch.setattr(mod, "read_json_file", lambda p: {})
    monkeypatch.setattr(mod, "write_json_file", lambda p, v: None)
    seen = {}
    monkeypatch.setattr(mod, "launch_refresh_run", lambda **kw: seen.update(kw) or {})
    mod._launch_autorun_wnba_live_refresh()
    assert seen.get("phase") == "live"
    assert seen.get("sports") == "wnba", "must not widen to other sports"
    assert seen.get("mode") == "fast", "full mode would pay the SmartSim cost on every repeat"
    assert seen.get("skip_mirror") is True
    lane = seen.get("lane")
    assert lane, "must pass an explicit lane -- default/unscoped would contend with the combined sweep"
    assert lane != "global", "must not collapse onto the legacy shared lane"


def test_the_lane_is_stable_across_calls_and_overridable(mod, monkeypatch):
    default_lane = mod._wnba_live_refresh_lane()
    assert default_lane == mod._wnba_live_refresh_lane(), "must be deterministic, not random per call"
    monkeypatch.setenv("SYNDICATE_WNBA_LIVE_REFRESH_LANE", "custom-lane")
    assert mod._wnba_live_refresh_lane() == "custom-lane"


def test_the_cadence_gate_suppresses_a_second_launch(mod, monkeypatch, tmp_path):
    monkeypatch.setenv("SYNDICATE_ENABLE_WNBA_LIVE_REFRESH_AUTORUN", "1")
    monkeypatch.setattr(mod, "_wnba_has_live_game", lambda d: True)
    monkeypatch.setattr(mod, "_wnba_live_autorun_status_path", lambda: tmp_path / "s.json")
    monkeypatch.setattr(mod, "write_json_file", lambda p, v: None)
    # A run that happened one second ago, against the 240s default interval.
    monkeypatch.setattr(mod, "read_json_file", lambda p: {"epoch": mod.time.time() - 1.0, "reported": True})
    called = []
    monkeypatch.setattr(mod, "launch_refresh_run", lambda **kw: called.append(kw))
    mod._launch_autorun_wnba_live_refresh()
    assert called == [], "inside the interval, it must not relaunch"


def test_a_stale_marker_allows_the_next_launch(mod, monkeypatch, tmp_path):
    monkeypatch.setenv("SYNDICATE_ENABLE_WNBA_LIVE_REFRESH_AUTORUN", "1")
    monkeypatch.setattr(mod, "_wnba_has_live_game", lambda d: True)
    monkeypatch.setattr(mod, "_wnba_live_autorun_status_path", lambda: tmp_path / "s.json")
    monkeypatch.setattr(mod, "write_json_file", lambda p, v: None)
    monkeypatch.setattr(mod, "read_json_file", lambda p: {"epoch": mod.time.time() - 99999.0, "reported": True})
    called = []
    monkeypatch.setattr(mod, "launch_refresh_run", lambda **kw: called.append(kw) or {})
    mod._launch_autorun_wnba_live_refresh()
    assert len(called) == 1


def test_a_launch_failure_is_recorded_and_reported_not_swallowed(mod, monkeypatch, tmp_path, capsys):
    """`#433`: a launch that is fire-and-forget by design must still be
    OBSERVABLE, or a real failure here reproduces the exact silence this
    whole lane exists to fix."""
    monkeypatch.setenv("SYNDICATE_ENABLE_WNBA_LIVE_REFRESH_AUTORUN", "1")
    monkeypatch.setattr(mod, "_wnba_has_live_game", lambda d: True)
    monkeypatch.setattr(mod, "_wnba_live_autorun_status_path", lambda: tmp_path / "s.json")
    monkeypatch.setattr(mod, "read_json_file", lambda p: {})
    written = {}
    monkeypatch.setattr(mod, "write_json_file", lambda p, v: written.update(v))

    def _boom(**kw):
        raise RuntimeError("launch exploded")

    monkeypatch.setattr(mod, "launch_refresh_run", _boom)
    mod._launch_autorun_wnba_live_refresh()
    assert "RuntimeError" in str(written.get("error")), "the failure must persist"
    assert "WNBA_LIVE_AUTORUN_FAILED" in capsys.readouterr().out, "and must be visible"


def test_a_contention_error_preserves_the_original_epoch(mod, monkeypatch, tmp_path):
    """`#472`'s fix, same shape: a lost mutex race must not cost a full
    cadence window -- only a real launch attempt should reset the clock."""
    monkeypatch.setenv("SYNDICATE_ENABLE_WNBA_LIVE_REFRESH_AUTORUN", "1")
    monkeypatch.setattr(mod, "_wnba_has_live_game", lambda d: True)
    monkeypatch.setattr(mod, "_wnba_live_autorun_status_path", lambda: tmp_path / "s.json")
    original_epoch = mod.time.time() - 99999.0
    monkeypatch.setattr(mod, "read_json_file", lambda p: {"epoch": original_epoch, "reported": True})
    written = {}
    monkeypatch.setattr(mod, "write_json_file", lambda p, v: written.update(v))

    def _contended(**kw):
        raise ValueError("A refresh run is already active (pid=1). Cancel it before starting a new run.")

    monkeypatch.setattr(mod, "launch_refresh_run", _contended)
    mod._launch_autorun_wnba_live_refresh()
    assert written.get("epoch") == original_epoch, "contention must not reset the cadence clock"


def test_the_previous_run_is_reported_BEFORE_the_cadence_gate(mod, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("SYNDICATE_ENABLE_WNBA_LIVE_REFRESH_AUTORUN", "1")
    monkeypatch.setattr(mod, "_wnba_has_live_game", lambda d: True)
    monkeypatch.setattr(mod, "_wnba_live_autorun_status_path", lambda: tmp_path / "s.json")
    monkeypatch.setattr(mod, "write_json_file", lambda p, v: None)
    monkeypatch.setattr(
        mod, "read_json_file",
        lambda p: {"epoch": mod.time.time() - 1.0, "reported": True, "date": "2026-08-19", "error": "Boom: x"},
    )
    monkeypatch.setattr(mod, "launch_refresh_run", lambda **kw: {})
    mod._launch_autorun_wnba_live_refresh()
    out = capsys.readouterr().out
    assert "WNBA_LIVE_AUTORUN_PREV" in out and "FAILED" in out


def test_it_is_wired_into_the_tick_loop_and_cannot_take_the_tick_down(mod):
    """Presence is not reachability -- the call must exist AND be
    independently guarded, same check `test_wnba_pregame_autorun.py` runs
    for its own autorun."""
    src = (_REPO / "scripts" / "run_live_odds_refresh_worker.py").read_text(encoding="utf-8")
    assert "_launch_autorun_wnba_live_refresh()" in src, "defined but never called"
    assert "WNBA_LIVE_AUTORUN_ERROR" in src, "its call site needs its own try/except"
    assert src.count("_launch_autorun_wnba_live_refresh") >= 2, "definition plus call site"


def test_default_interval_is_240_seconds(mod, monkeypatch):
    assert mod._wnba_live_refresh_interval_seconds() == 240
    monkeypatch.setenv("SYNDICATE_WNBA_LIVE_REFRESH_INTERVAL_SECONDS", "600")
    assert mod._wnba_live_refresh_interval_seconds() == 600
