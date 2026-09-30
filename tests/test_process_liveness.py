"""syndicate/features/shared/process_liveness.py -- and the callers that now use it.

The Windows branches are the point of the module, and CI is Linux, so they are
driven here through a fake `kernel32` and a fake `msvcrt`.
"""

from __future__ import annotations

import os
import subprocess
import sys
import types
from contextlib import contextmanager

import pytest

from syndicate.features.shared import process_liveness as pl


# ---------------------------------------------------------------- POSIX ----


def test_this_process_is_alive_and_nonsense_pids_are_not():
    assert pl.pid_is_running(os.getpid())
    for bad in (0, -1, None, "", "abc"):
        assert not pl.pid_is_running(bad)


def test_an_exited_child_reads_dead():
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    assert not pl.pid_is_running(child.pid)


@pytest.mark.skipif(not os.path.exists("/proc/self/cmdline"), reason="needs /proc")
def test_cmdline_of_this_process():
    argv = pl.process_cmdline(os.getpid())
    assert argv and "python" in os.path.basename(argv[0]).lower()
    assert pl.process_cmdline(0) is None


def test_unknown_oserror_honours_the_callers_choice(monkeypatch):
    def boom(pid, sig):
        raise OSError("weird")

    monkeypatch.setattr(pl.os, "kill", boom)
    assert pl.pid_is_running(12345, unknown_is_alive=True) is True
    assert pl.pid_is_running(12345, unknown_is_alive=False) is False


# -------------------------------------------------------------- Windows ----


class _FakeKernel32:
    def __init__(self, *, open_ok=True, last_error=0, wait=0x102):
        self.open_ok, self.last_error, self.wait = open_ok, last_error, wait
        self.closed = False

    def OpenProcess(self, access, inherit, pid):  # noqa: N802
        return 42 if self.open_ok else 0

    def WaitForSingleObject(self, handle, ms):  # noqa: N802
        return self.wait

    def CloseHandle(self, handle):  # noqa: N802
        self.closed = True


@contextmanager
def _windows(monkeypatch, kernel32):
    fake_ctypes = types.SimpleNamespace(
        WinDLL=lambda name, use_last_error=True: kernel32,
        get_last_error=lambda: kernel32.last_error,
    )
    monkeypatch.setitem(sys.modules, "ctypes", fake_ctypes)
    monkeypatch.setattr(pl, "_is_windows", lambda: True)

    def no_kill(*_a, **_k):
        raise AssertionError("os.kill(pid, 0) must never run on Windows: it is CTRL_C_EVENT there")

    monkeypatch.setattr(pl.os, "kill", no_kill)
    yield


def test_windows_running_process(monkeypatch):
    k = _FakeKernel32(wait=pl._WIN_WAIT_TIMEOUT)
    with _windows(monkeypatch, k):
        assert pl.pid_is_running(1234) is True
    assert k.closed


def test_windows_exited_process(monkeypatch):
    with _windows(monkeypatch, _FakeKernel32(wait=pl._WIN_WAIT_OBJECT_0)):
        assert pl.pid_is_running(1234) is False


def test_windows_no_such_pid(monkeypatch):
    k = _FakeKernel32(open_ok=False, last_error=pl._WIN_ERROR_INVALID_PARAMETER)
    with _windows(monkeypatch, k):
        assert pl.pid_is_running(1234, unknown_is_alive=True) is False


def test_windows_access_denied_means_it_exists(monkeypatch):
    k = _FakeKernel32(open_ok=False, last_error=pl._WIN_ERROR_ACCESS_DENIED)
    with _windows(monkeypatch, k):
        assert pl.pid_is_running(1234) is True


def test_windows_unknown_error_honours_the_callers_choice(monkeypatch):
    k = _FakeKernel32(open_ok=False, last_error=1234)
    with _windows(monkeypatch, k):
        assert pl.pid_is_running(1234, unknown_is_alive=True) is True
        assert pl.pid_is_running(1234, unknown_is_alive=False) is False


def test_windows_cmdline_comes_from_psutil(monkeypatch):
    fake_psutil = types.SimpleNamespace(
        Process=lambda pid: types.SimpleNamespace(cmdline=lambda: ["python.exe", "scripts/run_refresh_worker.py"])
    )
    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)
    monkeypatch.setattr(pl, "_is_windows", lambda: True)
    assert pl.process_cmdline(1234) == ["python.exe", "scripts/run_refresh_worker.py"]


def test_windows_cmdline_without_psutil_is_unknown(monkeypatch):
    monkeypatch.setitem(sys.modules, "psutil", None)  # import raises
    monkeypatch.setattr(pl, "_is_windows", lambda: True)
    assert pl.process_cmdline(1234) is None


# ---------------------------------------------------------------- callers ----


def test_callers_delegate_to_the_shared_probe(monkeypatch):
    from syndicate import app as syndicate_app
    from syndicate.features.shared import live_refresh_loop, ops_refresh

    seen = []

    def fake(pid, *, unknown_is_alive=False):
        seen.append((pid, unknown_is_alive))
        return True

    monkeypatch.setattr(pl, "pid_is_running", fake)
    monkeypatch.setattr(ops_refresh, "pid_is_running", fake)
    assert ops_refresh._pid_is_running(11)
    assert live_refresh_loop._process_exists(22)
    assert syndicate_app._pid_is_running(33)
    # The bootstrap lock treats unknown as ALIVE (stealing a live lock runs two
    # syncs); the refresh-run and sim locks treat it as dead.
    assert seen == [(11, False), (22, False), (33, True)]


def test_ops_refresh_windows_branch_no_longer_calls_os_kill(monkeypatch):
    from syndicate.features.shared import ops_refresh

    # `_windows` makes os.kill raise. Never patch os.name here: it is the ONE
    # shared os module, and pathlib then refuses to build a PosixPath.
    with _windows(monkeypatch, _FakeKernel32(wait=pl._WIN_WAIT_TIMEOUT)):
        assert ops_refresh._pid_is_running(4321) is True


# ------------------------------------------------ portfolio_books lock ----


def test_portfolio_books_lock_is_real_on_windows(monkeypatch, tmp_path):
    from syndicate.features.shared import portfolio_books as pb

    calls = []
    fake_msvcrt = types.SimpleNamespace(
        LK_NBLCK=2, LK_UNLCK=0, locking=lambda fd, mode, n: calls.append((mode, n))
    )
    monkeypatch.setitem(sys.modules, "fcntl", None)  # `import fcntl` raises ImportError
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
    with pb._exclusive(tmp_path / "books.json"):
        assert calls == [(2, 1)]
    assert calls == [(2, 1), (0, 1)]


def test_portfolio_books_lock_waits_then_gives_up(monkeypatch, tmp_path):
    from syndicate.features.shared import portfolio_books as pb

    def always_busy(fd, mode, n):
        if mode == 2:
            raise OSError("locked")

    fake_msvcrt = types.SimpleNamespace(LK_NBLCK=2, LK_UNLCK=0, locking=always_busy)
    monkeypatch.setitem(sys.modules, "fcntl", None)
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
    monkeypatch.setattr(pb, "_WINDOWS_LOCK_TIMEOUT_SECONDS", 0.2)
    with pytest.raises(OSError):
        with pb._exclusive(tmp_path / "books.json"):
            pass
