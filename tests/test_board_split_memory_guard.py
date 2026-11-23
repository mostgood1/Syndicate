"""Lane board-split-memory-guard (todo #850): the board child's memory under the split, three switches.

(a) SYNDICATE_BOARD_PROCESS_RAW_LIFELINE      -- a recycle exits rc 75, not SIGABRT at interpreter shutdown.
(b) SYNDICATE_BOARD_PROCESS_CEILING_CREDIT_MB -- the role's declared ceiling credits the second interpreter;
    SYNDICATE_BOARD_PROCESS_PARENT_TRIM_SECONDS -- the parent malloc_trims on a clock.
(c) SYNDICATE_BOARD_PROCESS_RECYCLE_AFTER_BUILD -- recycle right after a completed build when the next would be refused.
(d) the parent's ratchet (2026-11-21): SYNDICATE_BOARD_PROCESS_RECURRING_JOBS_MARGIN_MB -- the post-build check counts
    recurring jobs; SYNDICATE_BOARD_PROCESS_PARENT_RECYCLE_MB -- the split's parent exits at the main loop's recycle point.

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


# The switch-off child ABORTS on purpose (SIGABRT). On the fleet host WSL pipes every core dump to `wsl-capture-crash`,
# which wrote a 25-27 MB dump a night to Windows' wsl-crashes folder (findings section 15). That folder keeps the
# latest 10, so this test was pushing real crash dumps out. A pipe core pattern ignores RLIMIT_CORE, but the kernel
# writes no dump at all for a process that is not dumpable. The child reads the flag back so the test can assert it.
_CHILD_SCRIPT = textwrap.dedent(
    """
    import sys, threading, time
    if sys.platform.startswith("linux"):
        import ctypes
        _libc = ctypes.CDLL(None, use_errno=True)
        _libc.prctl(4, 0, 0, 0, 0)                  # PR_SET_DUMPABLE 0: the abort below writes no core dump
        sys.stderr.write("LIFELINE_TEST_DUMPABLE=%d\\n" % _libc.prctl(3, 0, 0, 0, 0))  # PR_GET_DUMPABLE
        sys.stderr.flush()
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
    if sys.platform.startswith("linux"):
        assert "LIFELINE_TEST_DUMPABLE=0" in off.stderr  # the deliberate abort leaves no core dump
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


# ======================================================== (d) the parent's ratchet: recurring-jobs margin + parent recycle
# User "Yes, build it" 2026-11-21 (findings §9-§12). Each switch absent = everything above unchanged.


def _margin_decision(margin: float, **over):
    args = dict(
        snapshot={"sufficient": False, "max_mb": 7936.0, "current_mb": 6268.4, "headroom_mb": 1667.6},
        pair_rss_mb=5870.5,  # 11-20 23:01:33Z: held=transient_jobs, then 3 refusals and a streak recycle
        floor_mb=1900.0,
        uptime_s=16141.0,
        min_uptime_s=1800.0,
        recycle_enabled=True,
        children=[],
        draining=False,
        jobs_margin_mb=margin,
    )
    args.update(over)
    return bbp.post_build_recycle_decision(**args)


def test_jobs_margin_off_is_not_on_on_the_11_20_hold():
    off = _margin_decision(0.0)
    on = _margin_decision(400.0)
    assert off[:2] == (False, "transient_jobs")
    assert "jobs_margin_mb" not in off[2]
    assert on[:2] == (True, "recycle")
    assert on[2]["jobs_margin_mb"] == 400.0 and on[2]["basis"] == "pair_plus_recurring_jobs"


def test_jobs_margin_anticipates_a_refusal_while_the_snapshot_is_still_sufficient():
    sufficient = {"sufficient": True, "max_mb": 7936.0, "current_mb": 5900.0, "headroom_mb": 2036.0}
    assert _margin_decision(0.0, snapshot=sufficient, pair_rss_mb=5800.0)[1] == "headroom_ok"
    assert _margin_decision(400.0, snapshot=sufficient, pair_rss_mb=5800.0)[:2] == (True, "recycle")
    # a pair that carries a typical job holds, sufficient or not
    assert _margin_decision(400.0, snapshot=sufficient, pair_rss_mb=5000.0)[1] == "headroom_ok"
    assert _margin_decision(400.0, pair_rss_mb=5000.0)[1] == "transient_jobs"


@pytest.mark.parametrize(
    "over, reason",
    [
        ({"pair_rss_mb": None}, "recycle"),  # unknown pair: the rule without the margin (insufficient -> on)
        ({"pair_rss_mb": None, "snapshot": {"sufficient": True, "max_mb": 7936.0}}, "headroom_ok"),
        ({"recycle_enabled": False}, "disabled"),
        ({"snapshot": None}, "headroom_unknown"),
        ({"uptime_s": 900.0}, "min_uptime"),
        ({"children": [1]}, "children_running"),
        ({"draining": True}, "drain_requested"),
    ],
)
def test_jobs_margin_keeps_every_other_rule(over, reason):
    assert _margin_decision(400.0, **over)[1] == reason


def test_gather_reads_the_margin_switch(monkeypatch):
    """Reachability: the env key reaches the decision through `_gather_post_build_decision`."""
    from syndicate.features.shared import deploy_drain

    snap = {"sufficient": False, "max_mb": 7936.0, "current_mb": 6268.4, "headroom_mb": 1667.6}
    monkeypatch.setattr(mo, "memory_headroom_snapshot", lambda _floor: dict(snap))
    monkeypatch.setattr(bbp, "_pair_rss_mb", lambda _pid: 5870.5)
    monkeypatch.setattr(worker_recycle, "child_process_pids", lambda _pid: [])
    monkeypatch.setattr(deploy_drain, "drain_active", lambda: False)
    monkeypatch.setattr(intelligence_state, "_MIN_SAFE_MEMORY_HEADROOM_BYTES", 1900 * MB)
    monkeypatch.delenv("SYNDICATE_REFRESH_WORKER_RECYCLE_AFTER_REFUSALS", raising=False)
    started = time.monotonic() - 3600.0
    monkeypatch.delenv(bbp.RECURRING_JOBS_MARGIN_ENV, raising=False)
    off = bbp._gather_post_build_decision(1, started, trim=False)
    monkeypatch.setenv(bbp.RECURRING_JOBS_MARGIN_ENV, "400")
    on = bbp._gather_post_build_decision(1, started, trim=False)
    assert off[1] == "transient_jobs" and on[1] == "recycle"
    assert on[2]["jobs_margin_mb"] == 400.0


HEAD_A = "a" * 40
HEAD_B = "b" * 40


def _parent_decision(**over):
    args = dict(
        threshold_mb=1500,
        parent_rss_mb=2166.0,  # 11-21 9 AM floor
        utc_hour=10,
        window=(9, 12),
        uptime_s=40000.0,
        min_uptime_s=21600.0,
        other_children=[],
        board_building=False,
        draining=False,
        boot_head=HEAD_A,
        disk_head=HEAD_A,
    )
    args.update(over)
    return bbp.parent_recycle_decision(**args)


@pytest.mark.parametrize(
    "over, reason",
    [
        ({}, "recycle"),
        ({"threshold_mb": 0}, "disabled"),
        ({"parent_rss_mb": None}, "rss_unknown"),
        ({"parent_rss_mb": 1400.0}, "below_threshold"),
        ({"utc_hour": 23}, "outside_window"),  # 5 PM CST: never mid-evening
        ({"utc_hour": 12}, "outside_window"),  # the window is [start, end)
        ({"uptime_s": 3600.0}, "min_uptime"),
        ({"other_children": None}, "children_unknown"),
        ({"other_children": [4242]}, "children_running"),
        ({"board_building": True}, "board_building"),
        ({"draining": True}, "drain_requested"),
        ({"disk_head": None}, "code_unknown"),
        ({"boot_head": None}, "code_unknown"),
        ({"disk_head": HEAD_B}, "code_on_disk_changed"),  # an ff that was not deployed: never load it
    ],
)
def test_parent_recycle_decision_rules(over, reason):
    recycle, got, detail = _parent_decision(**over)
    assert got == reason
    assert recycle is (reason == "recycle")
    assert detail["threshold_mb"] == over.get("threshold_mb", 1500)


@pytest.mark.parametrize(
    "raw, window, inside, outside",
    [
        (None, (9, 12), [9, 11], [8, 12, 23]),
        ("08-13", (8, 13), [8, 12], [7, 13]),
        ("22-03", (22, 3), [22, 23, 0, 2], [3, 21]),
        ("junk", (9, 12), [9], [12]),
        ("5-5", (9, 12), [9], [5]),
        ("25-3", (9, 12), [9], [3]),
    ],
)
def test_parent_recycle_window(raw, window, inside, outside):
    env = {} if raw is None else {bbp.PARENT_RECYCLE_HOURS_ENV: raw}
    got = bbp.parent_recycle_window(env)
    assert got == window
    assert all(bbp._hour_in_window(h, got) for h in inside)
    assert not any(bbp._hour_in_window(h, got) for h in outside)


class _FakeProc:
    def __init__(self, pid):
        self.pid = pid


class _FakeSup:
    def __init__(self, pid):
        self._proc = _FakeProc(pid)


def _parent_live_inputs(monkeypatch, *, rss=2166.0, children=None, busy=False, drain=False, heads=None):
    """The parent check's live reads, faked at their sources (the REAL gather + decision + recycler run)."""
    from syndicate.features.shared import deploy_drain

    heads = list(heads or [HEAD_A])
    monkeypatch.setattr(bbp, "_own_rss_mb", lambda: rss)
    monkeypatch.setattr(bbp, "_role_booted_at", lambda: time.time() - 40000.0)
    monkeypatch.setattr(worker_recycle, "child_process_pids", lambda _pid: list(children or []))
    monkeypatch.setattr(bbp, "child_board_busy", lambda *_a: busy)
    if isinstance(drain, Exception):
        def _raise():
            raise drain
        monkeypatch.setattr(deploy_drain, "drain_active", _raise)
    else:
        monkeypatch.setattr(deploy_drain, "drain_active", lambda: drain)
    monkeypatch.setattr(bbp, "_git_head", lambda *a, **k: heads.pop(0) if len(heads) > 1 else heads[0])


def _parent_env(**extra):
    env = {bbp.PARENT_RECYCLE_HOURS_ENV: "0-24"}  # every hour, so the test does not depend on the clock
    env.update(extra)
    return env


def test_parent_recycle_off_is_not_on_through_maybe_recycle(monkeypatch, capsys):
    """Reachability through the worker main loop's own call: same inputs; absent registers nothing and never exits."""
    _parent_live_inputs(monkeypatch)
    worker_recycle._reset_for_tests()
    try:
        assert bbp.install_parent_self_recycle(_FakeSup(777), _parent_env()) is None
        assert worker_recycle.maybe_recycle(parent_pid=os.getpid(), uptime_seconds=40000.0) is False
        on = bbp.install_parent_self_recycle(_FakeSup(777), _parent_env(**{bbp.PARENT_RECYCLE_ENV: "1500"}))
        assert isinstance(on, bbp.ParentSelfRecycler)
        assert worker_recycle.maybe_recycle(parent_pid=os.getpid(), uptime_seconds=40000.0) is True
    finally:
        worker_recycle._reset_for_tests()
    out = capsys.readouterr().out
    assert "BOARD_PROCESS_PARENT_RECYCLE_ARMED" in out and "threshold_mb=1500" in out and "window_utc=00-24" in out
    assert "BOARD_PROCESS_PARENT_RECYCLE pid=" in out
    assert "[worker_recycle] RECYCLE_EXIT reason=board_parent_rss" in out


def test_parent_recycle_ignores_the_board_child_but_not_a_job(monkeypatch):
    worker_recycle._reset_for_tests()
    try:
        _parent_live_inputs(monkeypatch, children=[777])  # only the board child
        bbp.install_parent_self_recycle(_FakeSup(777), _parent_env(**{bbp.PARENT_RECYCLE_ENV: "1500"}))
        assert worker_recycle.maybe_recycle(parent_pid=os.getpid(), uptime_seconds=40000.0) is True
        _parent_live_inputs(monkeypatch, children=[777, 4242])  # plus an odds job
        assert worker_recycle.maybe_recycle(parent_pid=os.getpid(), uptime_seconds=40000.0) is False
    finally:
        worker_recycle._reset_for_tests()


def test_parent_recycle_never_loads_code_an_ff_put_on_disk(monkeypatch, capsys):
    worker_recycle._reset_for_tests()
    try:
        _parent_live_inputs(monkeypatch, heads=[HEAD_A, HEAD_B])  # booted on A; the checkout is now B
        bbp.install_parent_self_recycle(_FakeSup(777), _parent_env(**{bbp.PARENT_RECYCLE_ENV: "1500"}))
        for _ in range(3):
            assert worker_recycle.maybe_recycle(parent_pid=os.getpid(), uptime_seconds=40000.0) is False
    finally:
        worker_recycle._reset_for_tests()
    out = capsys.readouterr().out
    assert out.count("BOARD_PROCESS_PARENT_RECYCLE_CHECK held=code_on_disk_changed") == 1  # once per reason change


@pytest.mark.parametrize(
    "inputs, reason",
    [
        ({"rss": 1400.0}, None),  # below the threshold: silent
        ({"busy": True}, "board_building"),
        ({"drain": True}, "drain_requested"),
        ({"drain": RuntimeError("unreadable")}, "drain_requested"),  # unknown is not "no drain"
        ({"heads": [None]}, "code_unknown"),
    ],
)
def test_parent_recycle_holds(monkeypatch, capsys, inputs, reason):
    worker_recycle._reset_for_tests()
    try:
        _parent_live_inputs(monkeypatch, **inputs)
        bbp.install_parent_self_recycle(_FakeSup(777), _parent_env(**{bbp.PARENT_RECYCLE_ENV: "1500"}))
        assert worker_recycle.maybe_recycle(parent_pid=os.getpid(), uptime_seconds=40000.0) is False
    finally:
        worker_recycle._reset_for_tests()
    out = capsys.readouterr().out
    if reason is None:
        assert "BOARD_PROCESS_PARENT_RECYCLE_CHECK" not in out
    else:
        assert f"BOARD_PROCESS_PARENT_RECYCLE_CHECK held={reason}" in out


def test_a_broken_registered_check_never_exits(capsys):
    worker_recycle._reset_for_tests()
    try:
        worker_recycle.register_recycle_check("broken", lambda: 1 / 0)
        assert worker_recycle.maybe_recycle(parent_pid=os.getpid(), uptime_seconds=40000.0) is False
    finally:
        worker_recycle._reset_for_tests()
    assert "RECYCLE_CHECK_FAILED check=broken ZeroDivisionError" in capsys.readouterr().out


def test_the_streak_recycle_still_wins_and_runs_first(monkeypatch):
    """A refusal streak exits as before (reason heavy_build_refused); the registered check is not even asked."""
    asked: list[int] = []
    worker_recycle._reset_for_tests()
    try:
        monkeypatch.setenv("SYNDICATE_REFRESH_WORKER_RECYCLE_AFTER_REFUSALS", "3")
        for _ in range(3):
            worker_recycle.note_heavy_build_refused("pre_source_state_fingerprint")
        worker_recycle.register_recycle_check("x", lambda: asked.append(1) or False)
        assert worker_recycle.maybe_recycle(parent_pid=os.getpid(), uptime_seconds=40000.0,
                                            children_fn=lambda _p: [], drain_active_fn=lambda: False) is True
        assert asked == []
    finally:
        worker_recycle._reset_for_tests()


def test_process_mode_arms_the_parent_recycle_only_when_switched_on(monkeypatch):
    worker_recycle._reset_for_tests()
    try:
        monkeypatch.setenv(bbp.SWITCH_ENV, "1")
        _fleet_memory(monkeypatch, tree_mb=5400.0)
        monkeypatch.setattr(bbp, "_git_head", lambda *a, **k: HEAD_A)
        monkeypatch.delenv(bbp.PARENT_RECYCLE_ENV, raising=False)
        _wire_start(monkeypatch)
        bbp.start_board_loop_for_refresh_worker()
        assert bbp.PARENT_RECYCLE_CHECK_NAME not in worker_recycle._extra_checks
        monkeypatch.setenv(bbp.PARENT_RECYCLE_ENV, "1500")
        _fleet_memory(monkeypatch, tree_mb=5400.0)
        _wire_start(monkeypatch)
        bbp.start_board_loop_for_refresh_worker()
        assert bbp.PARENT_RECYCLE_CHECK_NAME in worker_recycle._extra_checks
        # thread mode (no fcntl): never armed, whatever the switch says
        worker_recycle._reset_for_tests()
        _fleet_memory(monkeypatch, tree_mb=5400.0)
        effects, _sup = _wire_start(monkeypatch, posix_ready=False)
        bbp.start_board_loop_for_refresh_worker()
        assert effects == ["in_thread"]
        assert bbp.PARENT_RECYCLE_CHECK_NAME not in worker_recycle._extra_checks
    finally:
        worker_recycle._reset_for_tests()


def test_git_head_reads_a_sha_or_none():
    class _Out:
        def __init__(self, rc, out):
            self.returncode, self.stdout = rc, out

    assert bbp._git_head(run=lambda *a, **k: _Out(0, HEAD_A + "\n")) == HEAD_A
    assert bbp._git_head(run=lambda *a, **k: _Out(128, "")) is None
    assert bbp._git_head(run=lambda *a, **k: _Out(0, "not-a-sha")) is None
    assert bbp._git_head(run=lambda *a, **k: (_ for _ in ()).throw(OSError("no git"))) is None
    real = bbp._git_head()  # this checkout
    assert real is None or len(real) == 40
