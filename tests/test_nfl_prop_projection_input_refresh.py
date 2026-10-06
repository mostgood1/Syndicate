"""The NFL prop projection rebuilds when the week's ODDS are newer than it, not only nightly.

Lane `nfl-prop-projection-input-refresh` (2026-10-05). Measured on the fleet that day:
the 05:30Z build covered 2 of the 13 games on the board (125 rows) because the books
posted the Sunday props afterwards, and the 86400 s age rule would not rebuild until the
next night. The builder only projects lines present in the capture when it runs.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest


def _load_refresh_worker():
    repo_root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "run_refresh_worker_for_nfl_prop_input_refresh", repo_root / "scripts" / "run_refresh_worker.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def worker():
    return _load_refresh_worker()


def _files(tmp_path, *, odds_lead_seconds):
    artifact = tmp_path / "nfl_prop_projections_2026_wk4.json"
    artifact.write_text(json.dumps({"sim_rows": [{"a": "x" * 200}] * 100}), encoding="utf-8")
    odds = tmp_path / "oddsapi_player_props_2026_wk4.csv"
    odds.write_text("player,market\n", encoding="utf-8")
    base = 1_790_000_000.0
    os.utime(artifact, (base, base))
    os.utime(odds, (base + odds_lead_seconds, base + odds_lead_seconds))
    return artifact, odds


def _drive(worker, monkeypatch, tmp_path, *, odds_lead_seconds, since_launch, cooldown=3600.0):
    artifact, odds = _files(tmp_path, odds_lead_seconds=odds_lead_seconds)
    launched: list[str] = []
    skipped: list[str] = []
    import syndicate.features.nfl.sources as nfl_sources

    monkeypatch.setattr(nfl_sources, "nfl_props_path", lambda s, w: odds)
    monkeypatch.setattr(worker, "_season_projection_auto_refresh_enabled", lambda: True)
    monkeypatch.setattr(worker, "central_today_iso", lambda: "2026-10-05")
    monkeypatch.setattr(worker, "_active_sports_for_date", lambda d: "nfl")
    monkeypatch.setattr(worker, "_season_projection_process_still_running", lambda s: False)
    monkeypatch.setattr(worker, "_season_projection_target_week", lambda s, y: 4)
    monkeypatch.setattr(worker, "_nfl_prop_projection_artifact_path", lambda s, w: artifact)
    monkeypatch.setattr(
        worker, "_season_projection_should_launch",
        lambda *a, **k: (False, "artifact_fresh age_seconds=40000 interval_seconds=86400"),
    )
    monkeypatch.setattr(worker, "_seconds_since_season_projection_launch", lambda *a, **k: since_launch)
    monkeypatch.setattr(worker, "_season_projection_relaunch_cooldown_seconds", lambda: cooldown)
    monkeypatch.setattr(worker, "_log_season_projection_skip", lambda sport, reason: skipped.append(reason))
    monkeypatch.setattr(worker, "_nfl_prop_projection_script_args", lambda s, w: ["true"])
    monkeypatch.setattr(worker, "_record_season_projection_launch", lambda *a, **k: None)

    class _Proc:
        pid = 4242

    monkeypatch.setattr(worker.subprocess, "Popen", lambda args: launched.append("launched") or _Proc())
    monkeypatch.setattr(worker, "_write_worker_status", lambda **k: None)
    worker._launch_autorun_nfl_prop_projections(
        worker_status_path=tmp_path / "s.json", latest_manifest_path=tmp_path / "m.json", refresh_cycle={},
    )
    return launched, skipped


def test_newer_odds_relaunch_a_fresh_artifact(worker, monkeypatch, tmp_path):
    launched, _ = _drive(worker, monkeypatch, tmp_path, odds_lead_seconds=600, since_launch=7200.0)
    assert launched == ["launched"]


def test_off_is_not_on_older_odds_do_not_relaunch(worker, monkeypatch, tmp_path):
    """Reachability: the same fresh artifact with odds OLDER than it stays put."""
    launched, skipped = _drive(worker, monkeypatch, tmp_path, odds_lead_seconds=-600, since_launch=7200.0)
    assert launched == []
    assert skipped and skipped[0].startswith("artifact_fresh")


def test_newer_odds_are_throttled_by_the_relaunch_cooldown(worker, monkeypatch, tmp_path):
    """`#389`: a build that cannot advance the artifact must not relaunch every tick."""
    launched, skipped = _drive(worker, monkeypatch, tmp_path, odds_lead_seconds=600, since_launch=120.0)
    assert launched == []
    assert skipped and skipped[0].startswith("odds_newer_relaunched_recently")


def test_the_lead_helper_is_none_when_either_file_is_missing(worker, tmp_path, monkeypatch):
    import syndicate.features.nfl.sources as nfl_sources

    artifact, odds = _files(tmp_path, odds_lead_seconds=600)
    monkeypatch.setattr(nfl_sources, "nfl_props_path", lambda s, w: tmp_path / "absent.csv")
    assert worker._nfl_prop_odds_newer_than_artifact(2026, 4, artifact) is None
    monkeypatch.setattr(nfl_sources, "nfl_props_path", lambda s, w: odds)
    assert worker._nfl_prop_odds_newer_than_artifact(2026, 4, tmp_path / "absent.json") is None
    assert worker._nfl_prop_odds_newer_than_artifact(2026, 4, artifact) == pytest.approx(600, abs=1)


# --- A MISSING artifact after a refused launch (lane nfl-prop-missing-odds-relaunch, 2026-10-06) ---
#
# Fleet, 2026-10-06: wk5's first build at 03:39:01Z REFUSED (odds_rows=0), the capture
# landed by 05:12:59Z, and `artifact_missing_after_launch interval_seconds=86400` held
# until a manual publish at 15:09Z. With no artifact, the odds must be compared to the
# LAST LAUNCH instead.

_MISSING = "artifact_missing_after_launch since_launch_seconds=5000 interval_seconds=86400 path=x"


def _drive_missing(worker, monkeypatch, tmp_path, *, odds_age_seconds, since_launch, cooldown=3600.0):
    import time as _time

    import syndicate.features.nfl.sources as nfl_sources

    artifact = tmp_path / "nfl_prop_projections_2026_wk5.json"  # never written: the build refused
    odds = None
    if odds_age_seconds is not None:
        odds = tmp_path / "oddsapi_player_props_2026_wk5.csv"
        odds.write_text("player,market\n", encoding="utf-8")
        stamp = _time.time() - odds_age_seconds
        os.utime(odds, (stamp, stamp))
    launched: list[str] = []
    skipped: list[str] = []
    monkeypatch.setattr(nfl_sources, "nfl_props_path", lambda s, w: odds or (tmp_path / "absent.csv"))
    monkeypatch.setattr(worker, "_season_projection_auto_refresh_enabled", lambda: True)
    monkeypatch.setattr(worker, "central_today_iso", lambda: "2026-10-06")
    monkeypatch.setattr(worker, "_active_sports_for_date", lambda d: "nfl")
    monkeypatch.setattr(worker, "_season_projection_process_still_running", lambda s: False)
    monkeypatch.setattr(worker, "_season_projection_target_week", lambda s, y: 5)
    monkeypatch.setattr(worker, "_nfl_prop_projection_artifact_path", lambda s, w: artifact)
    monkeypatch.setattr(worker, "_season_projection_should_launch", lambda *a, **k: (False, _MISSING))
    monkeypatch.setattr(worker, "_seconds_since_season_projection_launch", lambda *a, **k: since_launch)
    monkeypatch.setattr(worker, "_season_projection_relaunch_cooldown_seconds", lambda: cooldown)
    monkeypatch.setattr(worker, "_log_season_projection_skip", lambda sport, reason: skipped.append(reason))
    monkeypatch.setattr(worker, "_nfl_prop_projection_script_args", lambda s, w: ["true"])
    monkeypatch.setattr(worker, "_record_season_projection_launch", lambda *a, **k: None)

    class _Proc:
        pid = 4243

    monkeypatch.setattr(worker.subprocess, "Popen", lambda args: launched.append("launched") or _Proc())
    monkeypatch.setattr(worker, "_write_worker_status", lambda **k: None)
    worker._launch_autorun_nfl_prop_projections(
        worker_status_path=tmp_path / "s.json", latest_manifest_path=tmp_path / "m.json", refresh_cycle={},
    )
    return launched, skipped


def test_missing_artifact_relaunches_when_odds_land_after_the_refused_launch(worker, monkeypatch, tmp_path):
    """The 10-06 shape: launched 5000 s ago and refused; odds written 600 s ago."""
    launched, _ = _drive_missing(worker, monkeypatch, tmp_path, odds_age_seconds=600, since_launch=5000.0)
    assert launched == ["launched"]


def test_off_is_not_on_odds_older_than_the_launch_do_not_relaunch(worker, monkeypatch, tmp_path):
    """Reachability: the same missing artifact, but the odds predate the launch -- that
    launch already saw them, so relaunching would rebuild the same refusal."""
    launched, skipped = _drive_missing(worker, monkeypatch, tmp_path, odds_age_seconds=6000, since_launch=5000.0)
    assert launched == []
    assert skipped == [_MISSING]


def test_missing_artifact_relaunch_is_held_by_the_cooldown_and_stays_loud(worker, monkeypatch, tmp_path):
    """`#389`: newer odds inside the cooldown do not relaunch, and the reason is left as
    `artifact_missing_after_launch` so the rate-limited MISSING line keeps firing."""
    launched, skipped = _drive_missing(worker, monkeypatch, tmp_path, odds_age_seconds=60, since_launch=1200.0)
    assert launched == []
    assert skipped == [_MISSING]


def test_missing_artifact_with_no_capture_does_not_relaunch(worker, monkeypatch, tmp_path):
    launched, skipped = _drive_missing(worker, monkeypatch, tmp_path, odds_age_seconds=None, since_launch=5000.0)
    assert launched == []
    assert skipped == [_MISSING]


def test_the_launch_lead_helper(worker, tmp_path, monkeypatch):
    import time as _time

    import syndicate.features.nfl.sources as nfl_sources

    odds = tmp_path / "oddsapi_player_props_2026_wk5.csv"
    odds.write_text("player,market\n", encoding="utf-8")
    stamp = _time.time() - 600
    os.utime(odds, (stamp, stamp))
    monkeypatch.setattr(nfl_sources, "nfl_props_path", lambda s, w: odds)
    assert worker._nfl_prop_odds_newer_than_launch(2026, 5, None) is None
    assert worker._nfl_prop_odds_newer_than_launch(2026, 5, 300.0) is None
    assert worker._nfl_prop_odds_newer_than_launch(2026, 5, 5000.0) == pytest.approx(4400, abs=5)
    monkeypatch.setattr(nfl_sources, "nfl_props_path", lambda s, w: tmp_path / "absent.csv")
    assert worker._nfl_prop_odds_newer_than_launch(2026, 5, 5000.0) is None
