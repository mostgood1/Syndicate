"""WNBA's pregame autorun must not share the combined sweep's refresh lane.

THE STARVATION, measured 2026-09-25 on live-odds-worker.

`_launch_autorun_wnba_pregame_refresh` was the ONE autorun on this service that
passed no `lane=`, so it fell back to `_refresh_lane_key()` -- the shared
`live-odds-worker` lane, which is the combined mlb/nhl/ncaaf sweep's lane. Its
run (stamp 20260925_212433) held that mutex across two sweep attempts at
21:24:58Z and 21:26:24Z. NHL's pregame cadence is 7200s, so losing its slot cost
it the whole interval: the NHL collector produced nothing from 15:44:17Z and the
NHL board carried ZERO rows on a four-game night.

Its three siblings on this service already pass explicit distinct lanes -- WNBA
live, NCAAF lines, NFL lines -- and `run_live_odds_refresh_worker.py` states the
reason outright at the NCAAF one: "EXPLICIT, DISTINCT LANE, same reason WNBA's
live autorun has one ... this can never contend with the combined sweep's lane."

THE TEST THAT MATTERS IS THE REACHABILITY ONE. A lane helper that exists and is
never passed to `launch_refresh_run` is inert and looks identical to a fix, so
`test_the_launch_actually_passes_the_lane` is the load-bearing case here; the
rest only describe the value it passes.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.run_live_odds_refresh_worker as mod  # noqa: E402


def test_the_default_lane_is_distinct_and_namespaced():
    assert mod._wnba_pregame_refresh_lane() == "live-odds-worker-wnba-pregame"


def test_it_is_distinct_from_every_sibling_lane_on_this_service():
    """Two autoruns sharing a lane silently serialise each other -- the bug."""
    lanes = [
        mod._wnba_pregame_refresh_lane(),
        mod._wnba_live_refresh_lane(),
        mod._ncaaf_lines_refresh_lane(),
        mod._nfl_lines_refresh_lane(),
    ]
    assert len(set(lanes)) == len(lanes), f"lane collision: {lanes}"


def test_it_is_distinct_from_the_shared_service_lane():
    """The combined sweep's lane. Sharing it is precisely what starved NHL."""
    from syndicate.features.shared import ops_refresh

    assert mod._wnba_pregame_refresh_lane() != ops_refresh._refresh_lane_key()
    assert mod._wnba_pregame_refresh_lane() != "live-odds-worker"


def test_the_lane_is_overridable(monkeypatch):
    monkeypatch.setenv("SYNDICATE_WNBA_PREGAME_REFRESH_LANE", "custom-lane")
    assert mod._wnba_pregame_refresh_lane() == "custom-lane"


def test_a_blank_override_falls_back_to_the_default(monkeypatch):
    """An empty env var must not produce an empty lane, which would collapse
    onto the legacy shared manifest."""
    monkeypatch.setenv("SYNDICATE_WNBA_PREGAME_REFRESH_LANE", "   ")
    assert mod._wnba_pregame_refresh_lane() == "live-odds-worker-wnba-pregame"


def test_the_launch_actually_passes_the_lane(monkeypatch, tmp_path):
    """THE REACHABILITY TEST. A helper nothing calls is inert."""
    captured: dict = {}

    monkeypatch.setattr(mod, "_wnba_pregame_refresh_enabled", lambda: True)
    monkeypatch.setattr(mod, "_wnba_active_for_date", lambda d: True)
    monkeypatch.setattr(mod, "central_today_iso", lambda: "2026-09-25")
    monkeypatch.setattr(mod, "_wnba_pregame_autorun_status_path", lambda: tmp_path / "s.json")
    monkeypatch.setattr(mod, "read_json_file", lambda p: {})
    monkeypatch.setattr(mod, "write_json_file", lambda p, v: None)
    monkeypatch.setattr(mod, "_report_previous_wnba_pregame_run", lambda s: None)
    monkeypatch.setattr(mod, "launch_refresh_run", lambda **kw: captured.update(kw) or {"ok": True})

    mod._launch_autorun_wnba_pregame_refresh()

    assert captured, "the autorun never reached launch_refresh_run"
    assert captured.get("lane") == "live-odds-worker-wnba-pregame"
    # The rest of the contract must survive the edit untouched. `phase` is
    # load-bearing: pregame EXCLUDES the sim leg, and a full phase here would
    # OOM this 2GB service.
    assert captured.get("phase") == "pregame"
    assert captured.get("sports") == "wnba"
