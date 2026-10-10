"""Soccer in-play captures get their own fast lane.

Lane `soccer-live-lane-priority` (2026-10-10). With EPL and Bundesliga in play, 86-87%
of the loop's soccer-including sweeps were refused `lane_busy` by the loop's OWN live
sweeps (11-23 min each), so in-play soccer prices aged past the gate's 300 s ceiling.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, _ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ros():
    return _load("test_soccer_live_fast_ros", "scripts/refresh_odds_sources.py")


@pytest.fixture(scope="module")
def worker():
    return _load("test_soccer_live_fast_worker", "scripts/run_live_odds_refresh_worker.py")


def _soccer_steps(ros, monkeypatch, tmp_path):
    monkeypatch.setattr(ros, "_soccer_live_scope", lambda date: {"epl": ["e1"]})
    monkeypatch.setattr(ros, "soccer_active_leagues_for_date", lambda date: ["epl", "la_liga"], raising=False)
    monkeypatch.setattr(ros, "_local_source_bundle_root", lambda sport: tmp_path)
    args = argparse.Namespace(date="2026-10-10", soccer_date="", soccer_leagues=None, soccer_week=None,
                              soccer_season=None, mode="fast", phase="live")
    return ros._build_soccer_steps(args)


def test_a_fast_live_run_is_only_the_in_play_captures(ros, monkeypatch, tmp_path):
    names = {s.name for s in ros._filter_steps(_soccer_steps(ros, monkeypatch, tmp_path), "live", "fast")}
    assert {"soccer_epl_odds_live", "soccer_epl_props_live"} <= names
    slow = [n for n in names if n.endswith(("_artifacts", "_history", "_players", "_rosters", "_history_current", "_picks"))]
    assert slow == [], slow
    assert "soccer_sim_input_checklist" not in names


def test_off_is_not_on_a_full_live_run_still_builds_the_artifacts(ros, monkeypatch, tmp_path):
    """The fleet's own sweeps run mode=full: they must keep every slow step, so the
    narrowing above is the fast mode's doing and not a lost step."""
    names = {s.name for s in ros._filter_steps(_soccer_steps(ros, monkeypatch, tmp_path), "live", "full")}
    assert "soccer_la_liga_artifacts" in names
    assert "soccer_epl_odds_live" in names


def _autorun(worker, monkeypatch, *, enabled, in_play, last_epoch=0.0):
    calls = []
    if enabled:
        monkeypatch.setenv("SYNDICATE_ENABLE_SOCCER_LIVE_REFRESH_AUTORUN", "1")
    else:
        monkeypatch.delenv("SYNDICATE_ENABLE_SOCCER_LIVE_REFRESH_AUTORUN", raising=False)
    monkeypatch.delenv("SYNDICATE_SOCCER_LIVE_REFRESH_LANE", raising=False)
    monkeypatch.setattr(worker, "central_today_iso", lambda: "2026-10-10")
    monkeypatch.setattr(worker, "_soccer_in_play_leagues", lambda date: list(in_play))
    monkeypatch.setattr(worker, "read_json_file", lambda path: {"epoch": last_epoch} if last_epoch else {})
    monkeypatch.setattr(worker, "write_json_file", lambda path, payload: None)
    monkeypatch.setattr(worker, "launch_refresh_run", lambda **kw: calls.append(kw) or {"run_stamp": "s"})
    worker._launch_autorun_soccer_live_refresh()
    return calls


def test_the_autorun_is_off_by_default(worker, monkeypatch):
    assert _autorun(worker, monkeypatch, enabled=False, in_play=["epl"]) == []


def test_enabled_with_a_match_in_play_it_launches_fast_live_soccer_on_its_own_lane(worker, monkeypatch):
    calls = _autorun(worker, monkeypatch, enabled=True, in_play=["epl"])
    assert len(calls) == 1
    kw = calls[0]
    assert (kw["sports"], kw["phase"], kw["mode"], kw["lane"]) == ("soccer", "live", "fast", "live-odds-worker-soccer-live")


def test_nothing_in_play_launches_nothing(worker, monkeypatch):
    assert _autorun(worker, monkeypatch, enabled=True, in_play=[]) == []


def test_the_interval_gate_holds(worker, monkeypatch):
    import time
    assert _autorun(worker, monkeypatch, enabled=True, in_play=["epl"], last_epoch=time.time()) == []
