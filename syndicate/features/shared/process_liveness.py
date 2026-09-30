"""Is this PID alive, and what is it running? -- one answer for every platform.

Lane `windows-process-liveness` `[2026-09-30]`, todo `#692` owed item 3.

WHY THIS EXISTS. Four modules each carried their own copy of this probe, and
three of them were wrong on Windows in the same way: they called
`os.kill(pid, 0)`. On POSIX, signal 0 is a no-op existence check. On Windows
there is no signal 0 -- `os.kill` maps it to `CTRL_C_EVENT` and calls
`GenerateConsoleCtrlEvent`, which ERRORS for a detached child (read as "dead")
and can actually DELIVER Ctrl-C to a process sharing the caller's console. So
the refresh-run lock (`ops_refresh.py`) marked live runs failed and let a second
run launch over the first. Only `live_refresh_loop._process_exists` got it
right, with `OpenProcess` + `WaitForSingleObject`; that is the implementation
here, now shared.

The cmdline half: `/proc/<pid>/cmdline` does not exist on Windows or macOS, so
the PID-reuse identity check returned None there and failed OPEN. psutil
answers the same question on every platform and is used when it is installed.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

_WIN_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_WIN_SYNCHRONIZE = 0x00100000
_WIN_WAIT_OBJECT_0 = 0x00000000
_WIN_WAIT_TIMEOUT = 0x00000102
_WIN_ERROR_ACCESS_DENIED = 5
_WIN_ERROR_INVALID_PARAMETER = 87  # OpenProcess's answer for "no such pid"


def _is_windows() -> bool:
    return os.name == "nt" or sys.platform.startswith("win")


def _coerce_pid(pid: Any) -> int:
    try:
        return int(pid or 0)
    except Exception:
        return 0


def _windows_pid_is_running(pid: int, *, unknown_is_alive: bool) -> bool:
    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(_WIN_PROCESS_QUERY_LIMITED_INFORMATION | _WIN_SYNCHRONIZE, False, pid)
        if not handle:
            err = ctypes.get_last_error()  # type: ignore[attr-defined]
            if err == _WIN_ERROR_ACCESS_DENIED:
                return True  # exists, owned by someone else
            if err == _WIN_ERROR_INVALID_PARAMETER:
                return False
            return unknown_is_alive
        try:
            code = kernel32.WaitForSingleObject(handle, 0)
            if code == _WIN_WAIT_TIMEOUT:
                return True
            if code == _WIN_WAIT_OBJECT_0:
                return False  # signalled == exited
            return unknown_is_alive
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return unknown_is_alive


def pid_is_running(pid: Any, *, unknown_is_alive: bool = False) -> bool:
    """True if `pid` names a live (non-zombie) process on THIS host.

    `unknown_is_alive` decides the answer when the OS will not say. Callers
    guarding a lock whose theft runs two jobs at once pass True (a skipped run
    is cheaper); callers deciding whether to reap a record pass False.
    """
    pid_i = _coerce_pid(pid)
    if pid_i <= 0:
        return False
    if _is_windows():
        return _windows_pid_is_running(pid_i, unknown_is_alive=unknown_is_alive)
    # A zombie still answers signal 0; it is not running anything.
    stat_path = Path("/proc") / str(pid_i) / "stat"
    try:
        parts = stat_path.read_text(encoding="utf-8", errors="ignore").split()
        if len(parts) >= 3 and parts[2].strip().upper() == "Z":
            return False
    except OSError:
        pass
    try:
        os.kill(pid_i, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, SystemError, ValueError):
        return unknown_is_alive
    return True


def process_cmdline(pid: Any) -> list[str] | None:
    """The argv of `pid`, or None when it cannot be read (gone, or no source).

    /proc first (Linux, no dependency), then psutil (Windows, macOS). None is
    "unknown", never "matches" -- callers decide what unknown means.
    """
    pid_i = _coerce_pid(pid)
    if pid_i <= 0:
        return None
    if not _is_windows():
        try:
            raw = Path(f"/proc/{pid_i}/cmdline").read_bytes()
        except Exception:
            raw = None
        if raw is not None:
            parts = [part.decode("utf-8", errors="ignore") for part in raw.split(b"\x00") if part]
            return parts or None
    try:
        import psutil  # type: ignore[import-not-found]
    except Exception:
        return None
    try:
        parts = [str(part) for part in psutil.Process(pid_i).cmdline() if part]
    except Exception:
        return None
    return parts or None


__all__ = ["pid_is_running", "process_cmdline"]
