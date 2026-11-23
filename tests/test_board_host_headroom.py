"""Lane board-split-memory-guard (todo #850, findings section 18): the board child's host headroom switch.

SYNDICATE_BOARD_PROCESS_HOST_OVERDRAFT_MB=<n> lets a headroom gate in the board CHILD overdraw the role's declared
ceiling by at most n MB while the host's MemAvailable covers the gate's floor + a reserve (default 2048 MB). Absent =
today's guard. Reachability first (off != on through the real heavy guard, through `_serve_main`, and in a real child
process), then each refusal rule. The figures are fleet readings: 11-23 02:39:25Z's refusal (tree 6,339.3 MB against
7,936, short 303.3), 11-21 22:23:37Z's (6,607.0, short 571.0) and 11-21 00:23Z's host (5,348 MB available).
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from pipeline import board_build_process as bbp
from pipeline import intelligence_state
from syndicate.features.shared import memory_observability as mo

REPO_ROOT = Path(__file__).resolve().parents[1]
MB = 1024 * 1024
FLOOR = intelligence_state._MIN_SAFE_MEMORY_HEADROOM_BYTES
CHILD = {bbp.CHILD_MARKER_ENV: "1"}


@pytest.fixture(autouse=True)
def _no_hook_leaks():
    mo.set_headroom_override(None)
    yield
    mo.set_headroom_override(None)


def _fleet(monkeypatch, tmp_path: Path, *, tree_mb: float, host_mb: float | None, limit_mb: int = 7936) -> None:
    """The fleet's shape: no cgroup, a declared local ceiling, the role tree's RSS as `current`, a host meminfo."""
    monkeypatch.setenv(mo.LOCAL_MEMORY_LIMIT_ENV, str(limit_mb))
    monkeypatch.setattr(mo, "_read_cgroup_memory_max_bytes", lambda: None)
    monkeypatch.setattr(mo, "_local_process_tree_rss_bytes", lambda: int(tree_mb * MB))
    meminfo = tmp_path / "meminfo"
    if host_mb is None:
        meminfo = tmp_path / "no_such_meminfo"
    else:
        meminfo.write_text(
            f"MemTotal:       16124372 kB\nMemFree:          512000 kB\nMemAvailable:   {int(host_mb * 1024)} kB\n",
            encoding="ascii",
        )
    monkeypatch.setattr(bbp, "_MEMINFO_PATH", meminfo)


def _on(overdraft: str = "1024", **extra: str) -> dict[str, str]:
    return {**CHILD, bbp.HOST_OVERDRAFT_ENV: overdraft, **extra}


# ===================================================================================================== reachability


def test_off_is_not_on_through_the_heavy_guard(monkeypatch, tmp_path, capsys):
    """The heavy guard's OWN function, on 11-23 02:39:25Z's refusal with 11-21's evening host."""
    _fleet(monkeypatch, tmp_path, tree_mb=6339.3, host_mb=5348.0)
    assert bbp.install_host_headroom_override(dict(CHILD)) is None  # switch absent: nothing registered
    off = intelligence_state._abort_if_memory_critical("pre_source_state_fingerprint", FLOOR)
    off_out = capsys.readouterr().out
    installed = bbp.install_host_headroom_override(_on())
    on = intelligence_state._abort_if_memory_critical("pre_source_state_fingerprint", FLOOR)
    on_out = capsys.readouterr().out
    assert off is True and on is False
    assert installed == {"overdraft_mb": 1024, "reserve_mb": 2048}
    assert "MEMORY_GUARD_ABORT stage=pre_source_state_fingerprint floor_mb=1900" in off_out
    assert "host_available_mb" not in off_out  # off: the old line, byte for byte
    assert "MEMORY_GUARD_ABORT" not in on_out  # a grant is never counted as a refusal
    line = next(ln for ln in on_out.splitlines() if "MEMORY_GUARD_HOST_OVERRIDE" in ln)
    assert "stage=pre_source_state_fingerprint caller=_abort_if_memory_critical floor_mb=1900" in line
    assert "headroom_mb=1596.7 shortfall_mb=303.3 host_available_mb=5348.0 overdraft_mb=1024 reserve_mb=2048" in line


def _serve_main_under_fakes(monkeypatch, tmp_path) -> int:
    """The REAL `_serve_main` with the loop, the lease and the store faked; the loop "dies" after a few polls."""
    import syndicate.features.shared.refresh_state_store as store
    import syndicate.features.shared.worker_shutdown as worker_shutdown

    monkeypatch.delenv(bbp.DRY_RUN_ENV, raising=False)
    monkeypatch.delenv(bbp.RECYCLE_AFTER_BUILD_ENV, raising=False)
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

    class _AliveThenDead:
        def is_alive(self):
            polls["n"] += 1
            return polls["n"] < 5

    class _Service:
        def __init__(self):
            self._execution_guard = threading.Lock()
            self._thread = None

        def start(self):
            self._thread = _AliveThenDead()

    monkeypatch.setattr(intelligence_state, "_INTELLIGENCE_STATE_SERVICE", _Service())
    return bbp._serve_main()


def test_serve_main_off_is_not_on(monkeypatch, tmp_path, capsys):
    """`_serve_main` registers the hook only with the switch, and its switches line says so."""
    _fleet(monkeypatch, tmp_path, tree_mb=6339.3, host_mb=5348.0)
    monkeypatch.setenv(bbp.CHILD_MARKER_ENV, "1")
    monkeypatch.delenv(bbp.HOST_OVERDRAFT_ENV, raising=False)
    assert _serve_main_under_fakes(monkeypatch, tmp_path) == bbp.LOOP_DIED_EXIT_CODE
    off_installed = mo.headroom_override_installed()
    off_out = capsys.readouterr().out
    monkeypatch.setenv(bbp.HOST_OVERDRAFT_ENV, "768")
    assert _serve_main_under_fakes(monkeypatch, tmp_path) == bbp.LOOP_DIED_EXIT_CODE
    on_installed = mo.headroom_override_installed()
    on_out = capsys.readouterr().out
    assert off_installed is False and on_installed is True
    off_switches = next(ln for ln in off_out.splitlines() if "BOARD_PROCESS_CHILD_SWITCHES" in ln)
    on_switches = next(ln for ln in on_out.splitlines() if "BOARD_PROCESS_CHILD_SWITCHES" in ln)
    assert "host_overdraft_mb" not in off_switches
    assert on_switches.endswith("host_overdraft_mb=768 host_reserve_mb=2048")
    assert "BOARD_PROCESS_HOST_HEADROOM installed" in on_out and "host_available_mb=5348.0" in on_out


def _real_dry_run_child(overdraft: str | None) -> list[str]:
    env = bbp.child_env(dict(os.environ), parent_pid=os.getpid(), parent_booted_at=time.time() - 60.0)
    env[bbp.DRY_RUN_ENV] = "1"
    env[bbp.RAW_LIFELINE_ENV] = "1"
    env.pop(bbp.HOST_OVERDRAFT_ENV, None)
    if overdraft is not None:
        env[bbp.HOST_OVERDRAFT_ENV] = overdraft
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
    return lines


def test_a_real_child_process_off_is_not_on():
    """A real `pipeline.board_build_process --serve` child (dry run: it builds nothing) registers the hook only when on."""
    off = _real_dry_run_child(None)
    on = _real_dry_run_child("512")
    assert any("BOARD_PROCESS_CHILD_READY" in ln for ln in off), off
    assert not any("BOARD_PROCESS_HOST_HEADROOM" in ln for ln in off), off
    assert any("BOARD_PROCESS_HOST_HEADROOM installed" in ln and "overdraft_mb=512 reserve_mb=2048" in ln for ln in on), on


# ======================================================================================================== the rules


@pytest.mark.parametrize(
    "headroom, host, overdraft, reserve, want",
    [
        (1596.7, 5348.0, 1024, 2048, (True, "granted")),  # 11-23 02:39Z on 11-21's evening host
        (1596.7, None, 1024, 2048, (False, "host_unreadable")),
        (None, 5348.0, 1024, 2048, (False, "no_declared_headroom")),
        (1329.0, 5348.0, 512, 2048, (False, "overdraft_exceeded")),  # 11-21 22:23Z: short 571 > 512
        (1388.0, 5348.0, 512, 2048, (True, "granted")),  # short exactly 512
        (1596.7, 3947.9, 1024, 2048, (False, "host_below_floor_plus_reserve")),
        (1596.7, 3948.0, 1024, 2048, (True, "granted")),  # host exactly floor + reserve
        (1596.7, 5348.0, 1024, 4000, (False, "host_below_floor_plus_reserve")),
    ],
)
def test_decision_rules(headroom, host, overdraft, reserve, want):
    got = bbp.host_headroom_decision(headroom_mb=headroom, floor_mb=1900.0, host_mb=host, overdraft_mb=overdraft,
                                     reserve_mb=reserve)
    assert got == want


def test_the_overdraft_cap_still_refuses_through_the_guard(monkeypatch, tmp_path, capsys):
    """11-21 22:23:37Z (short 571) under a 512 MB overdraft: refused, and the refusal now names the host and the reason."""
    _fleet(monkeypatch, tmp_path, tree_mb=6607.0, host_mb=5348.0)
    bbp.install_host_headroom_override(_on("512"))
    assert intelligence_state._abort_if_memory_critical("pre_source_state_fingerprint", FLOOR) is True
    line = next(ln for ln in capsys.readouterr().out.splitlines() if "MEMORY_GUARD_ABORT" in ln)
    assert "'host_override_reason': 'overdraft_exceeded'" in line
    assert "'host_available_mb': 5348.0" in line and "'declared_shortfall_mb': 571.0" in line
    assert "'sufficient': False" in line and "'declared_sufficient': False" in line


def test_an_unreadable_host_refuses(monkeypatch, tmp_path, capsys):
    _fleet(monkeypatch, tmp_path, tree_mb=6339.3, host_mb=None)
    bbp.install_host_headroom_override(_on())
    assert intelligence_state._abort_if_memory_critical("pre_source_state_fingerprint", FLOOR) is True
    assert "'host_override_reason': 'host_unreadable'" in capsys.readouterr().out


def test_a_sufficient_snapshot_never_asks_the_hook_and_is_unchanged(monkeypatch, tmp_path):
    _fleet(monkeypatch, tmp_path, tree_mb=5000.0, host_mb=5348.0)
    before = mo.memory_headroom_snapshot(FLOOR)
    calls: list[int] = []
    mo.set_headroom_override(lambda snap, floor, ctx: calls.append(floor) or {"host_override": True})
    after = mo.memory_headroom_snapshot(FLOOR)
    assert before == after and before["sufficient"] is True and calls == []


def test_a_broken_hook_grants_nothing(monkeypatch, tmp_path):
    _fleet(monkeypatch, tmp_path, tree_mb=6339.3, host_mb=5348.0)

    def _boom(*_a):
        raise RuntimeError("broken")

    mo.set_headroom_override(_boom)
    snap = mo.memory_headroom_snapshot(FLOOR)
    assert snap["sufficient"] is False and snap["host_override"] is False and snap["host_override_error"] == "RuntimeError"
    assert intelligence_state._abort_if_memory_critical("x", FLOOR) is True


def test_only_host_override_true_grants(monkeypatch, tmp_path):
    """A hook cannot grant by returning `sufficient`; only `host_override: True` (exactly True) flips the verdict."""
    _fleet(monkeypatch, tmp_path, tree_mb=6339.3, host_mb=5348.0)
    for extra in ({"sufficient": True}, {"host_override": "yes"}, {"host_override": 1}, None, "granted"):
        mo.set_headroom_override(lambda *_a, _e=extra: _e)
        assert mo.memory_headroom_snapshot(FLOOR)["sufficient"] is False, extra


def test_install_refuses_outside_the_board_child(capsys):
    assert bbp.install_host_headroom_override({bbp.HOST_OVERDRAFT_ENV: "1024"}) is None
    assert mo.headroom_override_installed() is False
    assert "BOARD_PROCESS_HOST_HEADROOM held=not_board_child overdraft_mb=1024" in capsys.readouterr().out


@pytest.mark.parametrize("raw", [None, "", "0", "-5", "junk"])
def test_overdraft_absent_zero_or_junk_is_off(raw):
    env = dict(CHILD) if raw is None else _on(raw)
    assert bbp.install_host_headroom_override(env) is None
    assert mo.headroom_override_installed() is False


@pytest.mark.parametrize(
    "overdraft, reserve, want",
    [
        ("768", None, {"overdraft_mb": 768, "reserve_mb": 2048}),
        ("768", "0", {"overdraft_mb": 768, "reserve_mb": 2048}),  # a zero reserve is the default, never zero
        ("768", "junk", {"overdraft_mb": 768, "reserve_mb": 2048}),
        ("768", "3000", {"overdraft_mb": 768, "reserve_mb": 3000}),
        ("10000", None, {"overdraft_mb": bbp.HOST_OVERDRAFT_MAX_MB, "reserve_mb": 2048}),  # a typo is capped
    ],
)
def test_overdraft_and_reserve_values(overdraft, reserve, want):
    extra = {} if reserve is None else {bbp.HOST_RESERVE_ENV: reserve}
    assert bbp.install_host_headroom_override(_on(overdraft, **extra)) == want


def test_host_available_mb_reads_meminfo_or_none(tmp_path):
    good = tmp_path / "good"
    good.write_text("MemTotal: 16124372 kB\nMemAvailable:    6934032 kB\n", encoding="ascii")
    junk = tmp_path / "junk"
    junk.write_text("MemAvailable: lots kB\n", encoding="ascii")
    none = tmp_path / "none"
    none.write_text("MemTotal: 1 kB\n", encoding="ascii")
    assert round(bbp.host_available_mb(good), 1) == 6771.5
    assert bbp.host_available_mb(junk) is None
    assert bbp.host_available_mb(none) is None
    assert bbp.host_available_mb(tmp_path / "missing") is None
