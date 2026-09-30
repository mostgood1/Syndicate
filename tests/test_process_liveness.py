"""`process_liveness` -- the one liveness/identity/lock helper every site uses (#692).

The Windows branches are driven on any host by monkeypatching `os.name` /
`sys.platform` as the helper module sees them and replacing `_kernel32`, `_psutil_module` and `_msvcrt_module`
with fakes, so Linux CI executes them. Each Windows test also turns `os.kill`
into a failure: signal 0 on Windows is CTRL_C_EVENT, and never sending it is
the point of the change.
"""

from __future__ import annotations

import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from syndicate.features.shared import process_liveness as pl


WAIT_OBJECT_0 = 0x0
WAIT_TIMEOUT = 0x102


class FakeKernel32:
    def __init__(self, *, handle=1, last_error=0, wait_code=WAIT_TIMEOUT):
        self.handle = handle
        self.last_error = last_error
        self.wait_code = wait_code
        self.opened: list[int] = []
        self.closed: list[int] = []

    def OpenProcess(self, access, inherit, pid):  # noqa: N802 - Win32 name
        self.opened.append(pid)
        return self.handle

    def WaitForSingleObject(self, handle, timeout):  # noqa: N802
        return self.wait_code

    def CloseHandle(self, handle):  # noqa: N802
        self.closed.append(handle)
        return 1


def _no_kill(*_args, **_kwargs):
    raise AssertionError("os.kill must never be called on the Windows branch")


class _Platform:
    """`os` / `sys` as the helper sees them, with `name` / `platform` (and
    `kill`) overridden. Patched on the helper module only: flipping the real
    `os.name` breaks `pathlib` inside pytest's own failure reporting."""

    def __init__(self, real, **overrides):
        self._real = real
        self.__dict__.update(overrides)

    def __getattr__(self, attr):
        return getattr(self._real, attr)


@pytest.fixture
def as_windows(monkeypatch):
    monkeypatch.setattr(pl, "os", _Platform(os, name="nt", kill=_no_kill))
    monkeypatch.setattr(pl, "sys", _Platform(sys, platform="win32"))

    def install(kernel32: FakeKernel32) -> FakeKernel32:
        monkeypatch.setattr(pl, "_kernel32", lambda: kernel32)
        monkeypatch.setattr(pl, "_last_win_error", lambda: kernel32.last_error)
        return kernel32

    return install


@pytest.fixture
def as_posix(monkeypatch):
    def install(kill):
        monkeypatch.setattr(pl, "os", _Platform(os, name="posix", kill=kill))
        monkeypatch.setattr(pl, "sys", _Platform(sys, platform="linux"))

    return install


def _raising(exc):
    def kill(pid, sig):
        assert sig == 0
        raise exc

    return kill


# --- Windows liveness ----------------------------------------------------


def test_windows_running_process_reads_alive_without_signalling(as_windows):
    k = as_windows(FakeKernel32(wait_code=WAIT_TIMEOUT))
    assert pl.probe_pid(4242) is True
    assert k.opened == [4242] and k.closed == [1]


def test_windows_exited_process_reads_dead(as_windows):
    as_windows(FakeKernel32(wait_code=WAIT_OBJECT_0))
    assert pl.probe_pid(4242) is False


def test_windows_no_such_pid_reads_dead(as_windows):
    as_windows(FakeKernel32(handle=0, last_error=87))
    assert pl.probe_pid(4242) is False


def test_windows_access_denied_reads_alive(as_windows):
    as_windows(FakeKernel32(handle=0, last_error=5))
    assert pl.probe_pid(4242) is True


def test_windows_unexplained_open_failure_is_unknown_and_caller_decides(as_windows):
    as_windows(FakeKernel32(handle=0, last_error=6))
    assert pl.probe_pid(4242) is None
    assert pl.pid_is_alive(4242, unknown=True) is True
    assert pl.pid_is_alive(4242, unknown=False) is False


def test_windows_ctypes_failure_is_unknown(as_windows, monkeypatch):
    as_windows(FakeKernel32())

    def boom():
        raise OSError("no kernel32")

    monkeypatch.setattr(pl, "_kernel32", boom)
    assert pl.probe_pid(4242) is None


@pytest.mark.parametrize("pid", [None, 0, -3, "x", True])
def test_invalid_pid_is_dead_on_both_platforms(pid, as_windows):
    as_windows(FakeKernel32())
    assert pl.pid_is_alive(pid, unknown=True) is False


# --- POSIX liveness (unchanged semantics) --------------------------------


def test_posix_probe_keeps_os_kill_semantics(as_posix):
    as_posix(lambda pid, sig: None)
    assert pl.probe_pid(7) is True
    as_posix(_raising(ProcessLookupError()))
    assert pl.probe_pid(7) is False
    as_posix(_raising(PermissionError()))
    assert pl.probe_pid(7) is True
    as_posix(_raising(OSError("?")))
    assert pl.probe_pid(7) is None
    assert pl.pid_is_alive(7, unknown=True) is True


def test_zombie_is_dead_only_when_asked(as_posix, monkeypatch):
    as_posix(lambda pid, sig: None)
    monkeypatch.setattr(pl, "pid_is_zombie", lambda pid: True)
    assert pl.pid_is_alive(7) is True
    assert pl.pid_is_alive(7, zombie_is_dead=True) is False


def test_zombie_parse_from_proc_stat(as_posix, monkeypatch, tmp_path):
    as_posix(lambda pid, sig: None)
    stat = tmp_path / "7" / "stat"
    stat.parent.mkdir()
    stat.write_text("7 (py thon) Z 1 7 7 0", encoding="utf-8")
    real_path = pl.Path
    monkeypatch.setattr(pl, "Path", lambda p: tmp_path if p == "/proc" else real_path(p))
    assert pl.pid_is_zombie(7) is True
    stat.write_text("7 (python) S 1 7 7 0", encoding="utf-8")
    assert pl.pid_is_zombie(7) is False


# --- real processes on whatever host runs the suite ----------------------


def test_real_self_is_alive_and_reaped_child_is_dead():
    assert pl.pid_is_alive(os.getpid()) is True
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait(timeout=30)
    assert pl.pid_is_alive(child.pid) is False


# --- process identity ----------------------------------------------------


def test_windows_cmdline_comes_from_psutil(as_windows, monkeypatch):
    as_windows(FakeKernel32())
    seen = []

    def process(pid):
        seen.append(pid)
        return SimpleNamespace(cmdline=lambda: ["python", "run_refresh_odds_job.py", ""])

    monkeypatch.setattr(pl, "_psutil_module", lambda: SimpleNamespace(Process=process))
    assert pl.process_cmdline(4242) == ["python", "run_refresh_odds_job.py"]
    assert seen == [4242]


def test_windows_cmdline_without_psutil_is_none(as_windows, monkeypatch):
    as_windows(FakeKernel32())
    monkeypatch.setattr(pl, "_psutil_module", lambda: None)
    assert pl.process_cmdline(4242) is None


def test_windows_cmdline_psutil_error_is_none(as_windows, monkeypatch):
    as_windows(FakeKernel32())

    def process(pid):
        raise RuntimeError("NoSuchProcess")

    monkeypatch.setattr(pl, "_psutil_module", lambda: SimpleNamespace(Process=process))
    assert pl.process_cmdline(4242) is None


def test_real_own_cmdline_readable_when_a_backend_exists():
    if not os.path.isdir("/proc") and pl._psutil_module() is None:
        pytest.skip("no procfs and no psutil on this host")
    cmd = pl.process_cmdline(os.getpid())
    assert cmd and "python" in os.path.basename(cmd[0]).lower()


# --- file locks ----------------------------------------------------------


class FakeMsvcrt:
    LK_UNLCK = 0
    LK_LOCK = 1
    LK_NBLCK = 2

    def __init__(self, busy_attempts=0):
        self.busy_attempts = busy_attempts
        self.calls: list[int] = []

    def locking(self, fd, mode, nbytes):
        assert nbytes == 1
        self.calls.append(mode)
        if mode == self.LK_NBLCK and self.busy_attempts:
            self.busy_attempts -= 1
            raise OSError(36, "Resource deadlock avoided")


def test_windows_lock_polls_until_free_then_unlocks(as_windows, monkeypatch, tmp_path):
    as_windows(FakeKernel32())
    fake = FakeMsvcrt(busy_attempts=2)
    monkeypatch.setattr(pl, "_msvcrt_module", lambda: fake)
    monkeypatch.setattr(pl, "_fcntl_module", lambda: pytest.fail("fcntl on the Windows branch"))
    monkeypatch.setattr(pl, "_MSVCRT_LOCK_POLL_SECONDS", 0)
    with open(tmp_path / "x.lock", "a+") as handle:
        with pl.exclusive_file_lock(handle):
            assert fake.calls == [fake.LK_NBLCK] * 3
        assert fake.calls[-1] == fake.LK_UNLCK


def test_windows_nonblocking_lock_raises_when_held(as_windows, monkeypatch, tmp_path):
    as_windows(FakeKernel32())
    monkeypatch.setattr(pl, "_msvcrt_module", lambda: FakeMsvcrt(busy_attempts=1))
    with open(tmp_path / "x.lock", "a+") as handle:
        with pytest.raises(OSError):
            pl.lock_file_exclusive(handle, blocking=False)


def test_posix_lock_uses_flock(as_posix, monkeypatch, tmp_path):
    as_posix(lambda pid, sig: None)
    calls = []
    fake = SimpleNamespace(LOCK_EX=2, LOCK_NB=4, LOCK_UN=8, flock=lambda fd, op: calls.append(op))
    monkeypatch.setattr(pl, "_fcntl_module", lambda: fake)
    monkeypatch.setattr(pl, "_msvcrt_module", lambda: pytest.fail("msvcrt on the POSIX branch"))
    with open(tmp_path / "x.lock", "a+") as handle:
        with pl.exclusive_file_lock(handle):
            pass
        pl.lock_file_exclusive(handle, blocking=False)
    assert calls == [2, 8, 2 | 4]


def test_real_lock_excludes_a_second_handle(tmp_path):
    path = tmp_path / "x.lock"
    with open(path, "a+") as first, open(path, "a+") as second:
        with pl.exclusive_file_lock(first):
            with pytest.raises(OSError):
                pl.lock_file_exclusive(second, blocking=False)
        pl.lock_file_exclusive(second, blocking=False)
        pl.unlock_file(second)


# --- every call site routes through the helper ---------------------------


def test_ops_refresh_sites_use_the_windows_probe(as_windows, monkeypatch):
    from syndicate.features.shared import ops_refresh

    k = as_windows(FakeKernel32(wait_code=WAIT_TIMEOUT))
    assert ops_refresh._pid_is_running(4242) is True
    k.wait_code = WAIT_OBJECT_0
    assert ops_refresh._pid_is_running(4242) is False
    monkeypatch.setattr(
        pl,
        "_psutil_module",
        lambda: SimpleNamespace(Process=lambda pid: SimpleNamespace(cmdline=lambda: ["notepad.exe"])),
    )
    # Before #692 this read None on Windows and failed OPEN (True): a reused
    # pid looked like the original refresh run.
    assert ops_refresh._process_matches_expected_command(4242, ["python", "run_refresh_odds_job.py"]) is False
    assert ops_refresh._process_matches_expected_command(4242, ["notepad.exe"]) is True


def test_live_refresh_loop_sites_use_the_helper(as_windows, monkeypatch):
    from syndicate.features.shared import live_refresh_loop

    k = as_windows(FakeKernel32(wait_code=WAIT_TIMEOUT))
    assert live_refresh_loop._process_exists(4242) is True
    k.handle, k.last_error = 0, 87
    assert live_refresh_loop._process_exists(4242) is False
    monkeypatch.setattr(
        pl,
        "_psutil_module",
        lambda: SimpleNamespace(Process=lambda pid: SimpleNamespace(cmdline=lambda: ["notepad.exe"])),
    )
    assert live_refresh_loop._process_matches_lock(4242, ["python", "sim.py"]) is False


def test_app_bootstrap_lock_fails_closed_on_unknown(as_windows):
    import syndicate.app as app_module

    as_windows(FakeKernel32(handle=0, last_error=6))
    assert app_module._pid_is_running(4242) is True
    as_windows(FakeKernel32(handle=0, last_error=87))
    assert app_module._pid_is_running(4242) is False


def test_run_queued_refresh_job_uses_the_helper(as_windows):
    import importlib

    job = importlib.import_module("scripts.run_queued_refresh_job")
    as_windows(FakeKernel32(wait_code=WAIT_TIMEOUT))
    assert job._pid_is_running(4242) is True
    assert job._pid_is_running(None) is False


def test_run_refresh_worker_uses_the_helper(as_windows):
    import importlib.util
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "scripts" / "run_refresh_worker.py"
    spec = importlib.util.spec_from_file_location("test_process_liveness_run_refresh_worker", script)
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    k = as_windows(FakeKernel32(wait_code=WAIT_TIMEOUT))
    assert worker._pid_is_running(4242) is True
    k.wait_code = WAIT_OBJECT_0
    assert worker._pid_is_running(4242) is False
    assert worker._pid_is_running(None) is False


def test_book_quote_shard_lock_uses_msvcrt_on_windows(as_windows, monkeypatch, tmp_path):
    from syndicate.features.shared import odds_book_quotes

    as_windows(FakeKernel32())
    fake = FakeMsvcrt()
    monkeypatch.setattr(pl, "_msvcrt_module", lambda: fake)
    with odds_book_quotes.shard_append_lock(tmp_path / "shard.jsonl"):
        assert fake.calls == [fake.LK_NBLCK]
    assert fake.calls == [fake.LK_NBLCK, fake.LK_UNLCK]


def test_book_quote_shard_lock_never_blocks_the_write(as_windows, monkeypatch, tmp_path):
    from syndicate.features.shared import odds_book_quotes

    as_windows(FakeKernel32())

    def unavailable():
        raise ImportError("no msvcrt")

    monkeypatch.setattr(pl, "_msvcrt_module", unavailable)
    ran = []
    with odds_book_quotes.shard_append_lock(tmp_path / "shard.jsonl"):
        ran.append(True)
    assert ran == [True]


def test_portfolio_books_lock_uses_msvcrt_on_windows(as_windows, monkeypatch, tmp_path):
    from syndicate.features.shared import portfolio_books

    as_windows(FakeKernel32())
    fake = FakeMsvcrt()
    monkeypatch.setattr(pl, "_msvcrt_module", lambda: fake)
    with portfolio_books._exclusive(tmp_path / "portfolio_books.json"):
        assert fake.calls == [fake.LK_NBLCK]
    assert fake.calls == [fake.LK_NBLCK, fake.LK_UNLCK]


def test_no_raw_signal_zero_probe_left_in_the_repo():
    """Every liveness site calls the helper; a new `os.kill(<pid>, 0)` CALL fails
    here. Parsed, not grepped, so prose that names the call is not an offender."""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    offenders = []
    for base in ("syndicate", "scripts", "pipeline"):
        for path in (root / base).rglob("*.py"):
            if path.name == "process_liveness.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "kill"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "os"
                    and len(node.args) == 2
                    and isinstance(node.args[1], ast.Constant)
                    and node.args[1].value == 0
                ):
                    offenders.append(f"{path.relative_to(root).as_posix()}:{node.lineno}")
    assert offenders == []
