"""The first-pitch freeze (lane mlb-pregame-sim-freeze).

The property under test is the one the backtest depends on: once a game starts,
its frozen pregame sim never changes, however many re-sims follow.
"""
from __future__ import annotations

import json
import os
import time

import pytest

from syndicate.features.mlb import pregame_freeze as pf


def _sim(data_dir, date, idx, pk, status, marker, gn=1, mtime=None):
    d = data_dir / "daily" / "sims" / date
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"sim_{idx}_AWY_at_HOM_pk{pk}_g{gn}.json"
    p.write_text(json.dumps({"game_pk": pk, "marker": marker,
                             "schedule": {"game_number": gn, "status": {"detailed": status}}}), encoding="utf-8")
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


def _frozen(data_dir, date, pk, gn=1):
    p = pf.frozen_dir(data_dir, date) / f"sim_pk{pk}_g{gn}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def test_pregame_sims_are_frozen_and_started_ones_are_not(tmp_path):
    for i, status in enumerate(["Scheduled", "Pre-Game", "Warmup", "In Progress", "Final"]):
        _sim(tmp_path, "2026-10-03", i, 100 + i, status, "m")
    c = pf.freeze_pregame_sims(tmp_path, "2026-10-03")
    assert c["frozen_new"] == 3 and c["not_pregame"] == 2
    assert _frozen(tmp_path, "2026-10-03", 100)["_freeze"]["status_at_sim"] == "Scheduled"
    assert _frozen(tmp_path, "2026-10-03", 103) is None


def test_a_post_start_resim_never_replaces_the_frozen_copy(tmp_path):
    t0 = time.time() - 3600
    _sim(tmp_path, "2026-10-03", 0, 777, "Pre-Game", "pregame", mtime=t0)
    pf.freeze_pregame_sims(tmp_path, "2026-10-03")
    frozen_bytes = (pf.frozen_dir(tmp_path, "2026-10-03") / "sim_pk777_g1.json").read_bytes()
    # the vendor's started-game repair rewrites the same file, later, post-start
    _sim(tmp_path, "2026-10-03", 0, 777, "In Progress", "resim", mtime=t0 + 1800)
    c = pf.freeze_pregame_sims(tmp_path, "2026-10-03")
    assert c["not_pregame"] == 1 and c["frozen_updated"] == 0
    assert (pf.frozen_dir(tmp_path, "2026-10-03") / "sim_pk777_g1.json").read_bytes() == frozen_bytes


def test_the_latest_pregame_copy_wins_and_reruns_are_idempotent(tmp_path):
    t0 = time.time() - 7200
    _sim(tmp_path, "2026-10-03", 0, 5, "Scheduled", "early", mtime=t0)
    pf.freeze_pregame_sims(tmp_path, "2026-10-03")
    _sim(tmp_path, "2026-10-03", 0, 5, "Pre-Game", "late", mtime=t0 + 600)
    c = pf.freeze_pregame_sims(tmp_path, "2026-10-03")
    assert c["frozen_updated"] == 1
    assert _frozen(tmp_path, "2026-10-03", 5)["marker"] == "late"
    c = pf.freeze_pregame_sims(tmp_path, "2026-10-03")
    assert c["unchanged"] == 1 and c["frozen_updated"] == 0


def test_keyed_by_game_not_by_the_shifting_slate_index(tmp_path):
    t0 = time.time() - 7200
    _sim(tmp_path, "2026-10-03", 3, 9, "Scheduled", "a", mtime=t0)
    pf.freeze_pregame_sims(tmp_path, "2026-10-03")
    # next run lists the game at a different index; the old file is gone
    (tmp_path / "daily" / "sims" / "2026-10-03" / "sim_3_AWY_at_HOM_pk9_g1.json").unlink()
    _sim(tmp_path, "2026-10-03", 1, 9, "Pre-Game", "b", mtime=t0 + 60)
    pf.freeze_pregame_sims(tmp_path, "2026-10-03")
    files = sorted(p.name for p in pf.frozen_dir(tmp_path, "2026-10-03").iterdir())
    assert files == ["sim_pk9_g1.json"]
    assert _frozen(tmp_path, "2026-10-03", 9)["marker"] == "b"


def test_doubleheader_halves_are_frozen_separately(tmp_path):
    _sim(tmp_path, "2026-10-03", 0, 1, "Scheduled", "g1", gn=1)
    _sim(tmp_path, "2026-10-03", 1, 2, "Scheduled", "g2", gn=2)
    pf.freeze_pregame_sims(tmp_path, "2026-10-03")
    assert _frozen(tmp_path, "2026-10-03", 1, 1)["marker"] == "g1"
    assert _frozen(tmp_path, "2026-10-03", 2, 2)["marker"] == "g2"


def test_bad_files_are_counted_not_raised(tmp_path):
    d = tmp_path / "daily" / "sims" / "2026-10-03"
    d.mkdir(parents=True)
    (d / "sim_0_x.json").write_text("{not json", encoding="utf-8")
    c = pf.freeze_pregame_sims(tmp_path, "2026-10-03")
    assert c["unreadable"] == 1
    assert pf.freeze_pregame_sims(tmp_path, "2026-01-01")["seen"] == 0  # no dir


def test_the_wrapper_freezes_on_the_env_resolved_data_root(tmp_path, monkeypatch, capsys):
    """Reachability: the wrapper's helper resolves the SAME data root the vendor
    sim writes to (MLB_BETTING_DATA_ROOT) and emits its log line."""
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "run_mlb_daily_sim_job", Path(__file__).resolve().parents[1] / "scripts" / "run_mlb_daily_sim_job.py")
    job = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(job)
    monkeypatch.setenv("MLB_BETTING_DATA_ROOT", str(tmp_path))
    _sim(tmp_path, "2026-10-03", 0, 42, "Scheduled", "m")
    job._freeze_pregame("before", "2026-10-03", tmp_path / "unused_vendor_cwd")
    assert _frozen(tmp_path, "2026-10-03", 42)["marker"] == "m"
    assert "MLB_PREGAME_FREEZE phase=before date=2026-10-03" in capsys.readouterr().out
