"""`local_production.py down` stops the roles' detached odds-refresh jobs.

Lane `down-reaps-odds-jobs` (2026-10-08). `ops_refresh` launches each
`run_refresh_odds_job.py` in its own session, so `down`'s `killpg` of a role
never reached it: both full downs on the fleet that night left one running,
reparented. These tests run REAL detached processes, because the defect is
about process groups and a mock cannot have one.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

psutil = pytest.importorskip("psutil")

from scripts import local_production as lp

# The leader starts a grandchild (the shape refresh_odds_sources gives the real
# job), writes its pid, and sleeps. Extra argv after `-c` only shapes cmdline.
_LEADER = (
    "import subprocess, sys, time;"
    "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)']);"
    "open(sys.argv[2], 'w').write(str(c.pid));"
    "time.sleep(120)"
)


def _spawn_detached_job(manifest: Path, pid_out: Path) -> subprocess.Popen:
    kwargs: dict = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    # Under `-c`, sys.argv is ['-c', <script path the matcher keys on>, <pid file>,
    # '--manifest-path', <manifest>]: the same cmdline shape as the real job.
    cmd =[sys.executable, "-c", _LEADER, "scripts/run_refresh_odds_job.py", str(pid_out), "--manifest-path", str(manifest)]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
    deadline = time.time() + 20
    while time.time() < deadline and not (pid_out.is_file() and pid_out.read_text().strip()):
        time.sleep(0.1)
    assert pid_out.is_file(), "detached test job never started its grandchild"
    return proc


def _alive(pid: int) -> bool:
    try:
        p = psutil.Process(pid)
        return p.is_running() and p.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def _cleanup(*pids: int) -> None:
    for pid in pids:
        try:
            psutil.Process(pid).kill()
        except Exception:
            pass


@pytest.fixture()
def fleet(tmp_path):
    settings = lp.Settings(home=tmp_path / "home", port=12345)
    manifest = settings.data_root / "reports" / "refresh_status" / "2026-10-08" / "20261008_013831" / "refresh_status_manifest.json"
    manifest.parent.mkdir(parents=True)
    return settings, manifest


def _down_args(settings: lp.Settings, *, keep: bool) -> argparse.Namespace:
    return argparse.Namespace(
        home=str(settings.home), port=settings.port, host=settings.host, state=settings.state,
        redis_url=settings.redis_url, timeout=5.0, unclaimed_ok="", keep_odds_jobs=keep,
    )


# --- the matcher -----------------------------------------------------------

def test_matcher_takes_only_this_fleets_odds_jobs(tmp_path):
    root = tmp_path / "home" / "data"
    inside = str(root / "reports" / "refresh_status" / "x" / "refresh_status_manifest.json")
    outside = str(tmp_path / "elsewhere" / "refresh_status_manifest.json")
    procs = [
        (1, ["python", "/srv/Syndicate/scripts/run_refresh_odds_job.py", "--manifest-path", inside, "--", "python", "refresh_odds_sources.py"]),
        (2, ["python", "/srv/Syndicate/scripts/run_refresh_odds_job.py", f"--manifest-path={inside}"]),
        (3, ["python", "/srv/Syndicate/scripts/run_refresh_odds_job.py", "--manifest-path", outside]),   # another home
        (4, ["python", "/srv/Syndicate/scripts/run_refresh_odds_job.py"]),                              # no manifest
        (5, ["python", "/srv/Syndicate/scripts/refresh_odds_sources.py", "--manifest-path", inside]),   # a child, not a job leader
        (6, ["python", "scripts/daily_mlb_sim.py", "--manifest-path", inside]),                         # other detached work
        (7, ["python", r"C:\Syndicate\scripts\run_refresh_odds_job.py", "--manifest-path", inside]),   # Windows-style path
    ]
    assert lp.fleet_odds_job_pids(root, procs) == [1, 2, 7]


# --- real processes ----------------------------------------------------------

def test_reap_stops_the_detached_job_and_its_grandchild(fleet, tmp_path):
    settings, manifest = fleet
    job = _spawn_detached_job(manifest, tmp_path / "child.pid")
    child = int((tmp_path / "child.pid").read_text())
    try:
        assert _alive(job.pid) and _alive(child)
        reaped = lp._reap_fleet_odds_jobs(settings, timeout=10)
        assert reaped == [job.pid]
        job.wait(timeout=10)
        deadline = time.time() + 10
        while time.time() < deadline and _alive(child):
            time.sleep(0.1)
        assert not _alive(child), "the job's grandchild survived the reap"
    finally:
        _cleanup(job.pid, child)


def test_reap_leaves_a_job_outside_the_data_root(fleet, tmp_path):
    settings, _ = fleet
    other = tmp_path / "other-home" / "data" / "refresh_status_manifest.json"
    other.parent.mkdir(parents=True)
    job = _spawn_detached_job(other, tmp_path / "child.pid")
    child = int((tmp_path / "child.pid").read_text())
    try:
        assert lp._reap_fleet_odds_jobs(settings, timeout=5) == []
        assert _alive(job.pid) and _alive(child)
    finally:
        _cleanup(job.pid, child)


@pytest.mark.parametrize("keep", [False, True])
def test_down_reaps_unless_told_to_keep(fleet, tmp_path, keep, capsys):
    """Reachability, off != on, through `cmd_down` itself (the no-pidfile exit)."""
    settings, manifest = fleet
    job = _spawn_detached_job(manifest, tmp_path / "child.pid")
    child = int((tmp_path / "child.pid").read_text())
    try:
        assert lp.cmd_down(_down_args(settings, keep=keep)) == 0
        out = capsys.readouterr().out
        if keep:
            assert "kept 1 detached odds job" in out
            assert _alive(job.pid) and _alive(child)
        else:
            assert f"stopped detached odds job pid={job.pid} run=20261008_013831" in out
            job.wait(timeout=10)
            assert not _alive(job.pid)
    finally:
        _cleanup(job.pid, child)
