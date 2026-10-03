"""refresh-worker's job cap counts only ITS OWN job processes.

Lane `refresh-worker-soccer-loop-silent`, 2026-10-03. `_running_job_process_count`
walked all of `/proc`. On the one-host local fleet that counted live-odds-worker's
`run_refresh_odds_job.py` processes against refresh-worker's cap of 1: 17 of 18
ticks throttled between 16:15 and 17:26Z, and 0 refresh-worker jobs among the
counted ones in 6 ownership samples. Soccer got no tick. The fake `/proc` below
copies the fleet shape at 17:5xZ: two live-odds jobs, one orphaned live-odds job
(its parent is `/init`, but its environ still names its role) and one of our own.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

JOB = "/home/amyn/.venvs/syndicate/bin/python /home/amyn/Syndicate/scripts/run_refresh_odds_job.py --manifest-path x"


@pytest.fixture()
def worker():
    spec = importlib.util.spec_from_file_location(
        "rw_job_scope", Path(__file__).resolve().parents[1] / "scripts" / "run_refresh_worker.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["rw_job_scope"] = module
    spec.loader.exec_module(module)
    return module


def _proc(root: Path, pid: int, cmdline: str, service: str | None, *, environ_readable: bool = True) -> None:
    entry = root / str(pid)
    entry.mkdir(parents=True)
    (entry / "cmdline").write_bytes(cmdline.replace(" ", "\x00").encode())
    if environ_readable:
        env = ["PATH=/usr/bin"] + ([f"RENDER_SERVICE_NAME={service}"] if service is not None else [])
        (entry / "environ").write_bytes("\x00".join(env).encode())


@pytest.fixture()
def fleet_proc(tmp_path):
    root = tmp_path / "proc"
    _proc(root, 1, "/init", None)
    _proc(root, 897298, JOB, "local-live-odds-worker")  # orphan, reparented to /init
    _proc(root, 900420, JOB, "local-live-odds-worker")
    _proc(root, 900726, JOB, "local-live-odds-worker")
    _proc(root, 901000, JOB, "local-refresh-worker")
    (root / "self").mkdir()  # non-numeric entries are skipped
    return root


def test_counts_only_this_services_jobs(worker, fleet_proc, monkeypatch):
    monkeypatch.setenv("RENDER_SERVICE_NAME", "local-refresh-worker")
    assert worker._running_job_process_count(fleet_proc) == 1


def test_reachability_scoped_differs_from_host_wide(worker, fleet_proc, monkeypatch):
    # off != on: the same /proc reads 4 with no service name of our own (the old,
    # host-wide behaviour) and 1 once the name scopes it. The production failure
    # was the 4: at max=1 every tick throttled.
    monkeypatch.delenv("RENDER_SERVICE_NAME", raising=False)
    host_wide = worker._running_job_process_count(fleet_proc)
    monkeypatch.setenv("RENDER_SERVICE_NAME", "local-refresh-worker")
    scoped = worker._running_job_process_count(fleet_proc)
    assert (host_wide, scoped) == (4, 1)


def test_the_other_worker_sees_its_own_three(worker, fleet_proc, monkeypatch):
    monkeypatch.setenv("RENDER_SERVICE_NAME", "local-live-odds-worker")
    assert worker._running_job_process_count(fleet_proc) == 3, "the orphan must still count for its own role"


def test_unknown_owner_still_counts(worker, tmp_path, monkeypatch):
    # Unknown must not read LOW: low is the direction that spawns (#2026-08-08, 79 processes).
    root = tmp_path / "proc"
    _proc(root, 10, JOB, None)  # environ readable, no service name
    _proc(root, 11, JOB, None, environ_readable=False)  # environ unreadable
    _proc(root, 12, JOB, "")  # empty name
    monkeypatch.setenv("RENDER_SERVICE_NAME", "local-refresh-worker")
    assert worker._running_job_process_count(root) == 3


def test_non_job_processes_never_count(worker, tmp_path, monkeypatch):
    root = tmp_path / "proc"
    _proc(root, 20, "/home/amyn/.venvs/syndicate/bin/python scripts/run_refresh_worker.py", "local-refresh-worker")
    _proc(root, 21, "python scripts/refresh_odds_sources.py --date 2026-10-03", "local-refresh-worker")
    monkeypatch.setenv("RENDER_SERVICE_NAME", "local-refresh-worker")
    assert worker._running_job_process_count(root) == 0
