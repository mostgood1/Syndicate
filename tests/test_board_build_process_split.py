"""Lane layer2-board-process-split: the board loop in its own process, behind SYNDICATE_BOARD_BUILD_PROCESS.

Reachability first (off != on), then each cross-process seam the design names: the busy signal the MLB-sim gate reads,
the role clock (drain + sim pointer), the child env, the deploy-safety marker, the supervisor's backoff, and a REAL
child process that boots and exits on its lifeline.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pipeline import board_build_process as bbp
from pipeline import intelligence_state

REPO_ROOT = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------------------------------------------ the switch


@pytest.mark.parametrize(
    "raw, expected",
    [(None, False), ("", False), ("0", False), ("false", False), ("off", False), ("no", False), ("junk", False),
     ("1", True), ("true", True), ("on", True), ("YES", True), (" On ", True)],
)
def test_switch_values(raw, expected):
    env = {} if raw is None else {bbp.SWITCH_ENV: raw}
    assert bbp.board_build_process_enabled(env) is expected


def _wire_effects(monkeypatch, *, posix_ready=True):
    """Replace every effect `start_board_loop_for_refresh_worker` can have with a recorder."""
    effects: list[str] = []
    service = intelligence_state._INTELLIGENCE_STATE_SERVICE
    real_guard = service._execution_guard
    monkeypatch.setattr(service, "_execution_guard", real_guard)  # restored after the test

    def _in_thread(*_a, **_k):
        effects.append("in_thread")
        return True

    def _service_start(*_a, **_k):
        effects.append("service_start_in_parent")
        return True

    class _FakeSupervisor:
        instances: list["_FakeSupervisor"] = []

        def __init__(self, *, env=None, **_k):
            self.env = env
            _FakeSupervisor.instances.append(self)

        def start(self):
            effects.append("supervisor")

    import pipeline.venue_odds_loop as venue
    import syndicate.features.shared.game_chip_publisher as chips

    monkeypatch.setattr(intelligence_state, "start_intelligence_state_background_loop", _in_thread)
    monkeypatch.setattr(service, "start", _service_start)
    monkeypatch.setattr(venue, "start_venue_odds_loop", lambda: effects.append("venue"))
    monkeypatch.setattr(chips, "ensure_publisher_thread", lambda: effects.append("chips") or True)
    monkeypatch.setattr(bbp, "BoardProcessSupervisor", _FakeSupervisor)
    monkeypatch.setattr(bbp, "_SUPERVISOR", None)
    monkeypatch.setattr(bbp, "_posix_ready", lambda: (posix_ready, "ok" if posix_ready else "no_fcntl"))

    def _no_popen(*_a, **_k):
        raise AssertionError("no child may be spawned here")

    monkeypatch.setattr(bbp.subprocess, "Popen", _no_popen)
    return effects, _FakeSupervisor, real_guard


def test_switch_absent_is_exactly_the_in_thread_start(monkeypatch):
    monkeypatch.delenv(bbp.SWITCH_ENV, raising=False)
    effects, _sup, real_guard = _wire_effects(monkeypatch)
    assert bbp.start_board_loop_for_refresh_worker() is True
    assert effects == ["in_thread"]
    assert intelligence_state._INTELLIGENCE_STATE_SERVICE._execution_guard is real_guard


def test_switch_on_runs_the_loop_in_a_child_and_keeps_the_rest_in_the_parent(monkeypatch):
    monkeypatch.setenv(bbp.SWITCH_ENV, "1")
    effects, sup, _real_guard = _wire_effects(monkeypatch)
    assert bbp.start_board_loop_for_refresh_worker() is True
    assert effects == ["venue", "chips", "supervisor"]
    assert "in_thread" not in effects and "service_start_in_parent" not in effects
    guard = intelligence_state._INTELLIGENCE_STATE_SERVICE._execution_guard
    assert isinstance(guard, bbp.ParentGuardProbe)
    env = sup.instances[-1].env
    assert env[bbp.CHILD_MARKER_ENV] == "1"
    assert env[bbp.PARENT_PID_ENV] == str(os.getpid())
    assert env["SYNDICATE_GAME_CHIP_PUBLISH_ENABLED"] == "0"
    assert env["SYNDICATE_MLB_SIM_TICK_OWNER"] == "false"
    assert env["SYNDICATE_LOCAL_MEMORY_ROOT_PID"] == str(os.getpid())


def test_off_is_not_on(monkeypatch):
    """The reachability test: the switch changes what refresh-worker starts."""
    monkeypatch.delenv(bbp.SWITCH_ENV, raising=False)
    off, _s, _g = _wire_effects(monkeypatch)
    bbp.start_board_loop_for_refresh_worker()
    monkeypatch.setenv(bbp.SWITCH_ENV, "on")
    on, _s2, _g2 = _wire_effects(monkeypatch)
    bbp.start_board_loop_for_refresh_worker()
    assert off != on
    assert set(off) == {"in_thread"} and set(on) == {"venue", "chips", "supervisor"}


def test_switch_on_without_fcntl_stays_in_thread(monkeypatch, capsys):
    monkeypatch.setenv(bbp.SWITCH_ENV, "1")
    effects, _sup, _g = _wire_effects(monkeypatch, posix_ready=False)
    assert bbp.start_board_loop_for_refresh_worker() is True
    assert effects == ["in_thread"]
    assert "BOARD_PROCESS_MODE mode=thread reason=no_fcntl" in capsys.readouterr().out


def test_refresh_worker_boot_starts_the_loop_through_the_switch():
    """The worker's boot block must call the switch, not the in-thread starter directly -- else `on` is inert."""
    source = (REPO_ROOT / "scripts" / "run_refresh_worker.py").read_text(encoding="utf-8")
    boot = source[source.index('print("[refresh_worker] INTELLIGENCE_LOOP_ENABLED'):]
    boot = boot[: boot.index("INTELLIGENCE_LOOP_START_RESULT")]
    assert "start_board_loop_for_refresh_worker()" in boot
    assert "start_intelligence_state_background_loop()" not in boot


# ---------------------------------------------------------------------------------------------- the child's world


def test_child_command_is_the_deploy_safety_service_marker():
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        import check_deploy_safety as cds
    finally:
        sys.path.pop(0)
    assert bbp.CHILD_CMDLINE_MARKER in cds.SERVICE_CHILD_CMDLINE_MARKERS
    cmd = " ".join(bbp.child_command("/home/amyn/.venvs/syndicate/bin/python"))
    assert cds.is_service_child(cmd)
    assert not cds.is_service_child("/venv/bin/python -m pipeline.board_build_process")  # no --serve: not the server
    assert not cds.is_service_child("/venv/bin/python /home/amyn/Syndicate/scripts/run_refresh_odds_job.py")


def test_child_env_is_the_parents_plus_the_named_keys():
    base = {"PATH": "/usr/bin", "SYNDICATE_GAME_CHIP_PUBLISH_ENABLED": "1", "SYNDICATE_MLB_SIM_TICK_OWNER": "true"}
    env = bbp.child_env(base, parent_pid=4242, parent_booted_at=1_794_960_000.5)
    assert env["PATH"] == "/usr/bin"
    assert env[bbp.PARENT_PID_ENV] == "4242"
    assert float(env[bbp.PARENT_BOOTED_AT_ENV]) == 1_794_960_000.5
    assert env["SYNDICATE_GAME_CHIP_PUBLISH_ENABLED"] == "0"
    assert env["SYNDICATE_MLB_SIM_TICK_OWNER"] == "false"
    assert env["SYNDICATE_LOCAL_MEMORY_ROOT_PID"] == "4242"
    assert base["SYNDICATE_GAME_CHIP_PUBLISH_ENABLED"] == "1"  # the parent's env is not mutated


def test_role_clock_keeps_a_parent_started_sim_alive_in_the_child(monkeypatch):
    """Without the role clock, a sim the parent started before the child booted reads `killed_by_restart` and the
    child CLEARS its shared pointer. With it, the sim is running."""
    from syndicate.features.shared import live_refresh_loop as lrl

    now = time.time()
    role_booted = now - 600.0
    sim_started = now - 120.0  # after the role booted, before this "child" did
    meta = {"pid": 4242, "started_at": datetime.fromtimestamp(sim_started, timezone.utc).isoformat().replace("+00:00", "Z"),
            "command": "python daily_update.py"}
    retired: list[str] = []
    monkeypatch.setattr(lrl, "read_json_file", lambda _p: dict(meta))
    monkeypatch.setattr(lrl, "_process_exists", lambda _pid: True)
    monkeypatch.setattr(lrl, "_process_matches_lock", lambda _pid, _cmd: True)
    monkeypatch.setattr(lrl, "_mlb_sim_progress_is_stalled", lambda _m: False)
    monkeypatch.setattr(lrl, "_retire_stale_active_pointer", lambda _m, *, state, detail: retired.append(state))

    monkeypatch.setattr(lrl, "_PROCESS_STARTED_AT", datetime.fromtimestamp(now - 5.0, timezone.utc))  # child's own boot
    assert lrl._shared_mlb_sim_still_running() is False
    assert retired == ["killed_by_restart"]  # the hazard, demonstrated

    retired.clear()
    from syndicate.features.shared import deploy_drain

    monkeypatch.setattr(deploy_drain, "_PROCESS_BOOTED_AT", deploy_drain._PROCESS_BOOTED_AT)  # restored after
    bbp.apply_role_clock(role_booted)
    assert lrl._shared_mlb_sim_still_running() is True
    assert retired == []


def test_role_clock_keeps_a_drain_requested_before_the_child_booted(monkeypatch):
    from syndicate.features.shared import deploy_drain, live_refresh_loop
    import syndicate.features.shared.refresh_state_store as store

    now = time.time()
    payload = {"owner": "deployer", "requested_at": now - 60.0, "expires_at": now + 3600.0}
    monkeypatch.setattr(store, "read_json_file", lambda _p: dict(payload))
    monkeypatch.setattr(live_refresh_loop, "_PROCESS_STARTED_AT", live_refresh_loop._PROCESS_STARTED_AT)
    monkeypatch.setattr(deploy_drain, "_PROCESS_BOOTED_AT", now - 5.0)  # a child (re)started after the request
    assert deploy_drain.drain_active() is False
    bbp.apply_role_clock(now - 600.0)  # the role booted before it
    assert deploy_drain.drain_active() is True


# ----------------------------------------------------------------------------------------------- the busy signal


def test_parent_probe_reads_idle_when_no_child_ever_built(tmp_path):
    assert bbp.child_board_busy(tmp_path / "board_build_busy.lock") is False
    probe = bbp.ParentGuardProbe(path=tmp_path / "board_build_busy.lock")
    assert probe.locked() is False
    assert probe.acquire(blocking=False) is True
    assert probe.locked() is True  # the parent's own lock still counts
    probe.release()


@pytest.mark.skipif(bbp.fcntl is None, reason="flock is POSIX-only; the switch refuses without it")
def test_child_guard_is_seen_busy_by_the_parent_and_idle_after(tmp_path):
    path = tmp_path / "board_build_busy.lock"
    guard = bbp.CrossProcessGuard(threading.Lock(), path)
    probe = bbp.ParentGuardProbe(path=path)
    assert guard.acquire(blocking=False) is True
    assert guard.locked() is True
    assert probe.locked() is True  # a separate open file description -> flock conflicts
    assert guard.acquire(blocking=False) is False  # the inner lock is still the authority
    guard.release()
    assert probe.locked() is False


@pytest.mark.skipif(bbp.fcntl is None, reason="flock is POSIX-only")
def test_intelligence_pipeline_busy_reads_the_child_through_the_probe(tmp_path, monkeypatch):
    path = tmp_path / "board_build_busy.lock"
    service = intelligence_state._INTELLIGENCE_STATE_SERVICE
    monkeypatch.setattr(service, "_execution_guard", bbp.ParentGuardProbe(path=path))
    assert intelligence_state.intelligence_pipeline_busy() is False
    child_guard = bbp.CrossProcessGuard(threading.Lock(), path)
    child_guard.acquire(blocking=False)
    try:
        assert intelligence_state.intelligence_pipeline_busy() is True
    finally:
        child_guard.release()
    assert intelligence_state.intelligence_pipeline_busy() is False


# -------------------------------------------------------------------------------------------------- the supervisor


class _FakeProc:
    def __init__(self, pid, rc):
        self.pid = pid
        self.rc = rc
        self.stdin = None

    def wait(self, timeout=None):
        return self.rc


def test_supervisor_respawns_with_backoff_and_resets_after_a_long_run(monkeypatch, capsys):
    clock = [0.0]
    sleeps: list[float] = []
    rcs = iter([1, 1, 1, bbp.RECYCLE_EXIT_CODE])
    pids = iter(range(100, 200))
    spawned_envs = []

    def _popen(cmd, **kwargs):
        assert cmd[-3:] == ["-m", "pipeline.board_build_process", "--serve"]
        assert kwargs["stdin"] == subprocess.PIPE and kwargs["stdout"] is None
        spawned_envs.append(kwargs["env"])
        return _FakeProc(next(pids), next(rcs))

    sup = bbp.BoardProcessSupervisor(env={"X": "1"}, popen=_popen, clock=lambda: clock[0], sleep=sleeps.append)
    backoff = bbp._BACKOFF_FIRST_S
    for _ in range(3):  # three quick crashes
        backoff = sup.run_once(backoff)
    assert sleeps == [5.0, 10.0, 20.0]
    clock[0] = 0.0

    def _long_wait(self, timeout=None):
        clock[0] += 700.0
        return self.rc

    monkeypatch.setattr(_FakeProc, "wait", _long_wait)
    backoff = sup.run_once(backoff)  # a recycle after 700 s up: the backoff resets
    assert sleeps[-1] == 5.0 and backoff == 5.0
    assert [e[1] for e in sup.exits] == [1, 1, 1, bbp.RECYCLE_EXIT_CODE]
    assert all(env == {"X": "1"} for env in spawned_envs)
    out = capsys.readouterr().out
    assert "BOARD_PROCESS_EXITED pid=103 rc=75 reason=recycle" in out


# --------------------------------------------------------------------------------------------- a REAL child process


def test_real_child_boots_and_exits_when_its_parent_pipe_closes():
    """The lifeline, end to end: spawn the actual module, wait for READY, close stdin, it must exit."""
    env = bbp.child_env(dict(os.environ), parent_pid=os.getpid(), parent_booted_at=time.time() - 60.0)
    env[bbp.DRY_RUN_ENV] = "1"
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.Popen(bbp.child_command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            cwd=str(REPO_ROOT), env=env, text=True, bufsize=1)
    lines: list[str] = []
    try:
        deadline = time.time() + 180.0
        while time.time() < deadline:
            line = proc.stdout.readline()
            if not line:
                break
            lines.append(line)
            if "BOARD_PROCESS_CHILD_READY" in line:
                break
        assert any("BOARD_PROCESS_CHILD_READY" in ln and "dry_run=1" in ln for ln in lines), lines
        proc.stdin.close()
        proc.wait(timeout=30.0)
        rest = proc.stdout.read()
        lines.append(rest)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
    assert proc.returncode is not None
    assert any("BOARD_PROCESS_PARENT_GONE why=stdin_eof" in ln for ln in lines), lines
