"""Lane board-split-memory-guard (todo #850): the board child's memory under the split, three switches.

(a) SYNDICATE_BOARD_PROCESS_RAW_LIFELINE      -- a recycle exits rc 75, not SIGABRT at interpreter shutdown.
(b) SYNDICATE_BOARD_PROCESS_CEILING_CREDIT_MB -- the role's declared ceiling credits the second interpreter;
    SYNDICATE_BOARD_PROCESS_PARENT_TRIM_SECONDS -- the parent malloc_trims on a clock.
(c) SYNDICATE_BOARD_PROCESS_RECYCLE_AFTER_BUILD -- recycle right after a completed build when the next would be refused.

Reachability first for each (off != on, through the real code path), then the rules.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from pipeline import board_build_process as bbp
from pipeline import intelligence_state
from syndicate.features.shared import memory_observability as mo
from syndicate.features.shared import worker_recycle

REPO_ROOT = Path(__file__).resolve().parents[1]
MB = 1024 * 1024


# ============================================================================================ (a) the lifeline exit


_CHILD_SCRIPT = textwrap.dedent(
    """
    import sys, threading, time
    from pipeline import board_build_process as bbp
    bbp._start_lifeline(0, threading.Event())   # the REAL lifeline; parent_pid 0 = the ppid watch never fires
    time.sleep(0.5)                               # the reader is now blocked on the open pipe
    sys.exit(75)                                  # what _serve_main's recycle return becomes
    """
)


def _run_child_exit(raw: bool) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env.pop(bbp.RAW_LIFELINE_ENV, None)
    if raw:
        env[bbp.RAW_LIFELINE_ENV] = "1"
    proc = subprocess.Popen([sys.executable, "-c", _CHILD_SCRIPT], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, cwd=str(REPO_ROOT), env=env)
    try:
        rc = proc.wait(timeout=60.0)  # stdin stays OPEN: the parent is alive, as on the fleet
        err = proc.stderr.read().decode("utf-8", "replace")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            try:
                stream.close()
            except Exception:
                pass
    return subprocess.CompletedProcess(proc.args, rc, "", err)


def test_lifeline_off_is_not_on_through_a_real_exit():
    """Reachability, end to end: the same rc-75 exit with the real `_start_lifeline`, switch off vs on.

    Off is the 11-18 fleet failure (4 of 4 recycles): CPython aborts at shutdown on the stdin BufferedReader lock.
    """
    off = _run_child_exit(raw=False)
    on = _run_child_exit(raw=True)
    assert on.returncode == 75, on.stderr[-800:]
    assert off.returncode != 75, off.stderr[-800:]
    if os.name == "posix":
        assert off.returncode == -6  # SIGABRT, exactly the fleet's BOARD_PROCESS_EXITED rc=-6
        assert "_enter_buffered_busy" in off.stderr
    assert "_enter_buffered_busy" not in on.stderr


def test_lifeline_reader_off_reads_the_buffer_on_reads_fd0(monkeypatch):
    calls: list[str] = []

    class _Buf:
        def read(self, n):
            calls.append(f"buffer:{n}")
            return b""

    class _Stdin:
        buffer = _Buf()

    monkeypatch.setattr(bbp.sys, "stdin", _Stdin())
    monkeypatch.setattr(bbp.os, "read", lambda fd, n: calls.append(f"fd{fd}:{n}") or b"")
    assert bbp.lifeline_reader({})() == b""
    assert bbp.lifeline_reader({bbp.RAW_LIFELINE_ENV: "1"})() == b""
    assert calls == ["buffer:1", "fd0:1"]


def test_raw_lifeline_still_fires_on_parent_eof():
    """The point of the lifeline survives the switch: closing the pipe still reaches PARENT_GONE."""
    env = bbp.child_env(dict(os.environ), parent_pid=os.getpid(), parent_booted_at=time.time() - 60.0)
    env[bbp.DRY_RUN_ENV] = "1"
    env[bbp.RAW_LIFELINE_ENV] = "1"
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
        proc.stdin.close()
        proc.wait(timeout=30.0)
        lines.append(proc.stdout.read())
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
    assert any("BOARD_PROCESS_PARENT_GONE why=stdin_eof" in ln for ln in lines), lines


# ================================================================================ (b) the ceiling credit and the trim


def _fleet_memory(monkeypatch, *, tree_mb: float, limit_mb: int = 7168):
    """The fleet's shape: no cgroup ceiling, a declared local one, the role tree's RSS as `current`."""
    monkeypatch.setenv(mo.LOCAL_MEMORY_LIMIT_ENV, str(limit_mb))
    monkeypatch.delenv(bbp.CEILING_CREDIT_APPLIED_ENV, raising=False)
    monkeypatch.delenv(bbp.CEILING_CREDIT_ENV, raising=False)
    monkeypatch.setattr(mo, "_read_cgroup_memory_max_bytes", lambda: None)
    monkeypatch.setattr(mo, "_local_process_tree_rss_bytes", lambda: int(tree_mb * MB))


def test_ceiling_credit_off_is_not_on_through_the_guard(monkeypatch, capsys):
    """Reachability through the heavy guard's OWN function: 11-18 9 PM CST's tree (5,400 MB) vs the 1,900 MB floor."""
    floor = intelligence_state._MIN_SAFE_MEMORY_HEADROOM_BYTES
    _fleet_memory(monkeypatch, tree_mb=5400.0)
    assert bbp.apply_ceiling_credit() is None  # switch absent: nothing
    off = intelligence_state._abort_if_memory_critical("test_stage", floor)
    monkeypatch.setenv(bbp.CEILING_CREDIT_ENV, "768")
    applied = bbp.apply_ceiling_credit()
    on = intelligence_state._abort_if_memory_critical("test_stage", floor)
    assert off is True and on is False
    assert applied == {"from_mb": 7168, "to_mb": 7936, "credit_mb": 768}
    out = capsys.readouterr().out
    assert "MEMORY_GUARD_ABORT stage=test_stage floor_mb=1900" in out
    assert "BOARD_PROCESS_CEILING_CREDIT from_mb=7168 to_mb=7936 credit_mb=768" in out


def test_ceiling_credit_still_refuses_a_tree_that_is_really_full(monkeypatch):
    """The credit is the second interpreter's cost, not a waiver: 6,200 MB still leaves < 1,900 MB under 7,936."""
    floor = intelligence_state._MIN_SAFE_MEMORY_HEADROOM_BYTES
    _fleet_memory(monkeypatch, tree_mb=6200.0)
    monkeypatch.setenv(bbp.CEILING_CREDIT_ENV, "768")
    bbp.apply_ceiling_credit()
    assert intelligence_state._abort_if_memory_critical("test_stage", floor) is True


@pytest.mark.parametrize("raw", [None, "", "0", "-5", "junk"])
def test_ceiling_credit_absent_zero_or_junk_changes_nothing(raw):
    env = {mo.LOCAL_MEMORY_LIMIT_ENV: "7168"}
    if raw is not None:
        env[bbp.CEILING_CREDIT_ENV] = raw
    before = dict(env)
    assert bbp.apply_ceiling_credit(env) is None
    assert env == before


def test_ceiling_credit_once_per_tree_and_never_on_a_host_without_a_local_ceiling(capsys):
    env = {mo.LOCAL_MEMORY_LIMIT_ENV: "7168", bbp.CEILING_CREDIT_ENV: "768"}
    assert bbp.apply_ceiling_credit(env)["to_mb"] == 7936
    assert bbp.apply_ceiling_credit(env) is None  # the child inherits the marker: no double credit
    assert env[mo.LOCAL_MEMORY_LIMIT_ENV] == "7936"
    assert env[bbp.CEILING_CREDIT_APPLIED_ENV] == "7168+768"
    cgroup_host = {bbp.CEILING_CREDIT_ENV: "768"}
    assert bbp.apply_ceiling_credit(cgroup_host) is None
    assert mo.LOCAL_MEMORY_LIMIT_ENV not in cgroup_host
    assert "BOARD_PROCESS_CEILING_CREDIT skipped reason=no_local_limit" in capsys.readouterr().out


def _wire_start(monkeypatch, *, posix_ready=True):
    """Every effect of `start_board_loop_for_refresh_worker` replaced with a recorder (as in the split's own tests)."""
    effects: list[str] = []
    service = intelligence_state._INTELLIGENCE_STATE_SERVICE
    monkeypatch.setattr(service, "_execution_guard", service._execution_guard)  # restored after the test

    class _FakeSupervisor:
        instances: list["_FakeSupervisor"] = []

        def __init__(self, *, env=None, **_k):
            self.env = env
            _FakeSupervisor.instances.append(self)

        def start(self):
            effects.append("supervisor")

    import pipeline.venue_odds_loop as venue
    import syndicate.features.shared.game_chip_publisher as chips

    monkeypatch.setattr(intelligence_state, "start_intelligence_state_background_loop", lambda *a, **k: effects.append("in_thread") or True)
    monkeypatch.setattr(venue, "start_venue_odds_loop", lambda: effects.append("venue"))
    monkeypatch.setattr(chips, "ensure_publisher_thread", lambda: effects.append("chips") or True)
    monkeypatch.setattr(bbp, "BoardProcessSupervisor", _FakeSupervisor)
    monkeypatch.setattr(bbp, "_SUPERVISOR", None)
    monkeypatch.setattr(bbp, "_posix_ready", lambda: (posix_ready, "ok" if posix_ready else "no_fcntl"))
    monkeypatch.setattr(bbp, "start_parent_trim", lambda *a, **k: effects.append("parent_trim"))
    monkeypatch.setattr(bbp.subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no spawn")))
    return effects, _FakeSupervisor


def test_process_mode_credits_the_ceiling_before_the_child_env_is_built(monkeypatch):
    monkeypatch.setenv(bbp.SWITCH_ENV, "1")
    _fleet_memory(monkeypatch, tree_mb=5400.0)
    effects, sup = _wire_start(monkeypatch)
    bbp.start_board_loop_for_refresh_worker()
    off_env = dict(sup.instances[-1].env)
    assert off_env[mo.LOCAL_MEMORY_LIMIT_ENV] == "7168"

    _fleet_memory(monkeypatch, tree_mb=5400.0)
    monkeypatch.setenv(bbp.CEILING_CREDIT_ENV, "768")
    _effects2, sup2 = _wire_start(monkeypatch)
    bbp.start_board_loop_for_refresh_worker()
    on_env = sup2.instances[-1].env
    assert on_env[mo.LOCAL_MEMORY_LIMIT_ENV] == "7936"  # the child reads the credited ceiling
    assert os.environ[mo.LOCAL_MEMORY_LIMIT_ENV] == "7936"  # and so do the parent's own gates
    assert on_env[bbp.CEILING_CREDIT_APPLIED_ENV] == "7168+768"
    assert "parent_trim" in effects


def test_thread_mode_gets_no_credit_and_no_parent_trim(monkeypatch):
    """The credit belongs to the split: in-thread (switch off, or no fcntl) the ceiling is untouched."""
    for split_raw, posix in ((None, True), ("1", False)):
        if split_raw is None:
            monkeypatch.delenv(bbp.SWITCH_ENV, raising=False)
        else:
            monkeypatch.setenv(bbp.SWITCH_ENV, split_raw)
        _fleet_memory(monkeypatch, tree_mb=5400.0)
        monkeypatch.setenv(bbp.CEILING_CREDIT_ENV, "768")
        effects, _sup = _wire_start(monkeypatch, posix_ready=posix)
        bbp.start_board_loop_for_refresh_worker()
        assert effects == ["in_thread"]
        assert os.environ[mo.LOCAL_MEMORY_LIMIT_ENV] == "7168"


def test_parent_trim_off_is_not_on(monkeypatch):
    monkeypatch.setattr(bbp, "_PARENT_TRIM_THREAD", None)
    monkeypatch.setattr(bbp, "_PARENT_TRIM_MIN_SECONDS", 1)
    trimmed = threading.Event()
    assert bbp.start_parent_trim({}, trim=trimmed.set) is None
    assert bbp.start_parent_trim({bbp.PARENT_TRIM_ENV: "0"}, trim=trimmed.set) is None
    thread = bbp.start_parent_trim({bbp.PARENT_TRIM_ENV: "1"}, trim=trimmed.set)
    try:
        assert thread is not None and thread.name == "board-process-parent-trim"
        assert trimmed.wait(5.0)
    finally:
        bbp._PARENT_TRIM_STOP.set()
        thread.join(timeout=5.0)
        bbp._PARENT_TRIM_STOP.clear()


def test_parent_trim_default_is_a_trim_without_gc(monkeypatch):
    calls = []
    monkeypatch.setattr(mo, "release_freed_memory_to_os", lambda reason, **k: calls.append((reason, k)))
    monkeypatch.setattr(bbp, "_PARENT_TRIM_THREAD", None)
    monkeypatch.setattr(bbp, "_PARENT_TRIM_MIN_SECONDS", 1)
    thread = bbp.start_parent_trim({bbp.PARENT_TRIM_ENV: "1"})
    try:
        deadline = time.time() + 5.0
        while not calls and time.time() < deadline:
            time.sleep(0.05)
    finally:
        bbp._PARENT_TRIM_STOP.set()
        thread.join(timeout=5.0)
        bbp._PARENT_TRIM_STOP.clear()
    assert calls and calls[0] == ("board_split_parent_periodic", {"collect_first": False})


# ================================================================================== (c) recycle after a completed build


def _decision(**over):
    args = dict(
        snapshot={"sufficient": False, "max_mb": 7168.0, "current_mb": 5400.0, "headroom_mb": 1768.0},
        pair_rss_mb=5400.0,
        floor_mb=1900.0,
        uptime_s=3600.0,
        min_uptime_s=1800.0,
        recycle_enabled=True,
        children=[],
        draining=False,
    )
    args.update(over)
    return bbp.post_build_recycle_decision(**args)


@pytest.mark.parametrize(
    "over, reason",
    [
        ({}, "recycle"),
        ({"recycle_enabled": False}, "disabled"),
        ({"snapshot": None}, "headroom_unknown"),
        ({"snapshot": {"sufficient": True, "max_mb": 7168.0}}, "headroom_ok"),
        ({"pair_rss_mb": 4800.0}, "transient_jobs"),  # 7,168 - 4,800 >= 1,900: an odds/sim job made the shortfall
        ({"pair_rss_mb": None}, "recycle"),  # unknown pair: the guard's own verdict stands
        ({"uptime_s": 900.0}, "min_uptime"),
        ({"children": None}, "children_unknown"),
        ({"children": [123]}, "children_running"),
        ({"draining": True}, "drain_requested"),
    ],
)
def test_post_build_decision_rules(over, reason):
    recycle, got, detail = _decision(**over)
    assert got == reason
    assert recycle is (reason == "recycle")
    assert detail["floor_mb"] == 1900.0


class _Counter:
    def __init__(self):
        self.n = 0

    def __call__(self):
        return self.n


def _recycler(guard, verdicts, counter):
    calls: list[bool] = []

    def decide(trim):
        calls.append(trim)
        verdict = verdicts[min(len(calls) - 1, len(verdicts) - 1)]
        return (verdict == "recycle", verdict, {"v": verdict})

    return bbp.PostBuildRecycler(guard, decide=decide, completed=counter, acquire_timeout_s=0.2), calls


def test_post_build_recycler_waits_for_a_completed_build():
    counter = _Counter()
    guard = threading.Lock()
    rec, calls = _recycler(guard, ["recycle"], counter)
    assert rec.poll() is False and calls == []  # nothing completed since boot: no check at all
    counter.n += 1
    assert rec.poll() is True
    assert calls == [False, True]  # cheap pass, then the re-read under the guard (with the trim)
    assert guard.locked()  # HELD: no build may start in the exiting process


def test_post_build_recycler_settles_when_headroom_is_fine():
    counter = _Counter()
    guard = threading.Lock()
    rec, calls = _recycler(guard, ["headroom_ok"], counter)
    counter.n += 1
    assert rec.poll() is False and rec.pending is False and not guard.locked()
    assert rec.poll() is False and calls == [False]  # settled until the next completed build


def test_post_build_recycler_waits_out_a_running_build_then_recycles():
    counter = _Counter()
    guard = threading.Lock()
    rec, _calls = _recycler(guard, ["recycle"], counter)
    counter.n += 1
    guard.acquire()  # a build is running
    try:
        assert rec.poll() is False and rec.pending is True
    finally:
        guard.release()
    assert rec.poll() is True and guard.locked()


def test_post_build_recycler_releases_when_the_trim_freed_enough(capsys):
    counter = _Counter()
    guard = threading.Lock()
    rec, calls = _recycler(guard, ["recycle", "headroom_ok"], counter)
    counter.n += 1
    assert rec.poll() is False
    assert calls == [False, True] and not guard.locked() and rec.pending is False
    assert "BOARD_PROCESS_RECYCLE" not in capsys.readouterr().out


def test_post_build_recycler_keeps_a_held_check_pending_and_logs_once(capsys):
    counter = _Counter()
    guard = threading.Lock()
    rec, _calls = _recycler(guard, ["children_running"], counter)
    counter.n += 1
    assert rec.poll() is False and rec.poll() is False
    assert rec.pending is True and not guard.locked()
    assert capsys.readouterr().out.count("BOARD_PROCESS_POST_BUILD_CHECK held=children_running pending=1") == 1


def test_make_post_build_recycler_off_is_none(monkeypatch):
    class _Service:
        _execution_guard = threading.Lock()

    assert bbp.make_post_build_recycler(_Service(), parent_pid=1, started_monotonic=0.0, env={}) is None
    on = bbp.make_post_build_recycler(_Service(), parent_pid=1, started_monotonic=0.0,
                                      env={bbp.RECYCLE_AFTER_BUILD_ENV: "1"})
    assert isinstance(on, bbp.PostBuildRecycler)


def _serve_main_under_fakes(monkeypatch, tmp_path, *, after_build: bool) -> tuple[int, list[str]]:
    """Drive the REAL `_serve_main` with the loop, the lease and the store faked, and builds completing."""
    import syndicate.features.shared.refresh_state_store as store
    import syndicate.features.shared.worker_shutdown as worker_shutdown

    if after_build:
        monkeypatch.setenv(bbp.RECYCLE_AFTER_BUILD_ENV, "1")
    else:
        monkeypatch.delenv(bbp.RECYCLE_AFTER_BUILD_ENV, raising=False)
    monkeypatch.delenv(bbp.DRY_RUN_ENV, raising=False)
    monkeypatch.setenv(bbp.PARENT_PID_ENV, "1")
    monkeypatch.setenv(bbp.PARENT_BOOTED_AT_ENV, repr(time.time() - 60.0))
    monkeypatch.setattr(bbp, "_SERVE_POLL_SECONDS", 0.01)
    monkeypatch.setattr(bbp, "_start_lifeline", lambda *_a: None)
    monkeypatch.setattr(bbp, "apply_role_clock", lambda *_a: None)
    monkeypatch.setattr(bbp, "_acquire_builder_lease", lambda _gone: object())
    monkeypatch.setattr(bbp, "busy_lock_path", lambda: tmp_path / "busy.lock")
    monkeypatch.setattr(store, "assert_refresh_state_backend_ready", lambda **_k: None)
    monkeypatch.setattr(worker_shutdown, "install_shutdown_recorder", lambda *_a: None)

    polls = {"n": 0}
    stop = threading.Event()

    class _AliveThenDead:
        def is_alive(self):
            polls["n"] += 1
            return polls["n"] < 60  # the loop "dies" after ~60 polls, so the off path ends (rc 70)

    class _Service:
        def __init__(self):
            self._execution_guard = threading.Lock()
            self._thread = None

        def start(self):
            self._thread = _AliveThenDead()

    service = _Service()
    monkeypatch.setattr(intelligence_state, "_INTELLIGENCE_STATE_SERVICE", service)
    completed = {"n": 0}
    monkeypatch.setattr(worker_recycle, "heavy_builds_completed", lambda: completed["n"] + (1 if polls["n"] >= 5 else 0))
    decided: list[bool] = []

    def _decide(_parent_pid, _started, *, trim):
        decided.append(trim)
        return True, "recycle", {}

    monkeypatch.setattr(bbp, "_gather_post_build_decision", _decide)
    rc = bbp._serve_main()
    stop.set()
    return rc, [str(d) for d in decided]


def test_serve_main_off_is_not_on(monkeypatch, tmp_path):
    """Reachability through `_serve_main` itself: same builds, same verdict; off never asks, on recycles rc 75."""
    off_rc, off_decided = _serve_main_under_fakes(monkeypatch, tmp_path, after_build=False)
    on_rc, on_decided = _serve_main_under_fakes(monkeypatch, tmp_path, after_build=True)
    assert off_rc == bbp.LOOP_DIED_EXIT_CODE and off_decided == []
    assert on_rc == bbp.RECYCLE_EXIT_CODE and on_decided == ["False", "True"]


def test_heavy_builds_completed_counts_only_completed_builds():
    worker_recycle._reset_for_tests()
    try:
        assert worker_recycle.heavy_builds_completed() == 0
        worker_recycle.note_heavy_build_refused("pre_source_state_fingerprint")
        assert worker_recycle.heavy_builds_completed() == 0
        worker_recycle.note_heavy_build_completed()
        assert worker_recycle.heavy_builds_completed() == 1
    finally:
        worker_recycle._reset_for_tests()
