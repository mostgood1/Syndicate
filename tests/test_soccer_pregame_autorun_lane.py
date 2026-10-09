"""The soccer pregame autorun launches on its OWN refresh lane.

Lane `soccer-live-lane-priority` (2026-10-09). On the shared combined lane a ~40 min
soccer pregame run every 45 min refused every phase=live sweep `lane_busy` (118 on
10-09), so in-play soccer quotes aged past the gate's 300 s ceiling and every live row
went `dead`.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def worker():
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_live_odds_refresh_worker.py"
    spec = importlib.util.spec_from_file_location("test_soccer_pregame_lane_worker", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _launch(worker, monkeypatch):
    calls = []
    monkeypatch.setattr(worker, "_soccer_pregame_refresh_enabled", lambda: True)
    monkeypatch.setattr(worker, "central_today_iso", lambda: "2026-10-09")
    monkeypatch.setattr(worker, "_soccer_active_for_date", lambda date: True)
    monkeypatch.setattr(worker, "read_json_file", lambda path: {})
    monkeypatch.setattr(worker, "write_json_file", lambda path, payload: None)
    monkeypatch.setattr(worker, "_report_previous_soccer_pregame_run", lambda status: None)
    monkeypatch.setattr(worker, "launch_refresh_run",
                        lambda **kwargs: calls.append(kwargs) or {"pid": 1, "run_stamp": "s", "artifacts_dir": "d"})
    worker._launch_autorun_soccer_pregame_refresh()
    assert len(calls) == 1
    return calls[0]


def test_the_autorun_takes_its_own_lane(worker, monkeypatch):
    monkeypatch.delenv("SYNDICATE_SOCCER_PREGAME_REFRESH_LANE", raising=False)
    kwargs = _launch(worker, monkeypatch)
    assert kwargs["lane"] == "live-odds-worker-soccer-pregame"
    assert kwargs["phase"] == "pregame" and kwargs["sports"] == "soccer"


def test_the_lane_name_is_overridable(worker, monkeypatch):
    monkeypatch.setenv("SYNDICATE_SOCCER_PREGAME_REFRESH_LANE", "custom-lane")
    assert _launch(worker, monkeypatch)["lane"] == "custom-lane"


def test_off_is_not_on_combined_restores_the_shared_lane(worker, monkeypatch):
    """Reachability: with the switch set to `combined` the call carries NO lane (the
    shared combined lane, exactly the old call), so the lane above is this change's doing."""
    monkeypatch.setenv("SYNDICATE_SOCCER_PREGAME_REFRESH_LANE", "combined")
    assert "lane" not in _launch(worker, monkeypatch)
