"""Cross-platform process liveness, process identity, and exclusive file locks.

WHY THIS EXISTS (`#692`, lane windows-process-liveness). Six call sites asked
"is pid N still running?" with `os.kill(pid, 0)`. On POSIX that is the standard
probe. On Windows it is not a probe at all: signal 0 is `CTRL_C_EVENT`, so the
call goes to `GenerateConsoleCtrlEvent` -- it errors for a detached child (which
then reads as DEAD) or delivers Ctrl-C to a process sharing the console. The
refresh-run lock in `ops_refresh.py` reads "dead" as "stale", marks the active
run failed and admits an overlapping launch. `live_refresh_loop._process_exists`
already did it correctly with OpenProcess/WaitForSingleObject; that code now
lives here and every site calls it.

The identity half (`process_cmdline`) read `/proc/<pid>/cmdline` and returned
None elsewhere, and every caller treats None as "can't verify, assume a match"
-- so on Windows the PID-reuse guard never ran. psutil is used where there is
no procfs; it is optional (requirements-dev.txt), and without it the result is
None exactly as before.

POSIX BEHAVIOUR IS UNCHANGED BY DESIGN. Production is Linux; the probe there is
still `os.kill(pid, 0)` and `/proc/<pid>/cmdline`. What each caller does when
the answer is UNKNOWN differs on purpose (a mutex fails closed, an advisory
check fails open), so that stays the caller's decision via `unknown=`.

Tests drive the Windows branches on Linux by monkeypatching `os.name` and
replacing `_kernel32` / `_msvcrt_module` / `_psutil_module`.
"""

from __future__ import annotations

import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Any, Iterator

# Win32 constants used by the OpenProcess probe.
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_SYNCHRONIZE = 0x00100000
_WAIT_OBJECT_0 = 0x00000000
_WAIT_TIMEOUT = 0x00000102
_ERROR_ACCESS_DENIED = 5
_ERROR_INVALID_PARAMETER = 87  # OpenProcess's answer for a pid that does not exist

# How often a blocking msvcrt lock re-polls. `msvcrt.LK_LOCK` gives up after
# ~10 s and raises, which is not the blocking semantics `fcntl.LOCK_EX` has.
_MSVCRT_LOCK_POLL_SECONDS = 0.05


def is_windows() -> bool:
    return os.name == "nt" or sys.platform.startswith("win")


def _coerce_pid(pid: Any) -> int | None:
    if isinstance(pid, bool):
        return None
    try:
        pid_i = int(pid)
    except (TypeError, ValueError):
        return None
    return pid_i if pid_i > 0 else None


def _kernel32() -> Any:
    import ctypes

    return ctypes.WinDLL("kernel32", use_last_error=True)


def _last_win_error() -> int:
    import ctypes

    return int(ctypes.get_last_error())


def _probe_windows(pid: int) -> bool | None:
    try:
        kernel32 = _kernel32()
        handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION | _SYNCHRONIZE, False, pid)
        if not handle:
            err = _last_win_error()
            if err == _ERROR_ACCESS_DENIED:
                return True  # exists, we may not open it
            if err == _ERROR_INVALID_PARAMETER:
                return False
            return None
        try:
            wait_code = kernel32.WaitForSingleObject(handle, 0)
            if wait_code == _WAIT_TIMEOUT:
                return True
            if wait_code == _WAIT_OBJECT_0:
                return False
            # WAIT_FAILED on a handle we just opened: it exists.
            return True
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return None


def _probe_posix(pid: int) -> bool | None:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by another user
    except (OSError, SystemError, ValueError, OverflowError):
        return None
    return True


def probe_pid(pid: Any) -> bool | None:
    """True = running, False = not running, None = could not tell.

    Never sends a signal on Windows."""
    pid_i = _coerce_pid(pid)
    if pid_i is None:
        return False
    if is_windows():
        return _probe_windows(pid_i)
    return _probe_posix(pid_i)


def pid_is_zombie(pid: Any) -> bool:
    """True only when /proc says the process has exited but is unreaped (state Z)."""
    pid_i = _coerce_pid(pid)
    if pid_i is None or is_windows():
        return False
    try:
        stat = (Path("/proc") / str(pid_i) / "stat").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    # `comm` (field 2) is parenthesised and may contain spaces, so the state
    # (field 3) is the first token after the LAST ')'.
    if ")" not in stat:
        return False
    after_comm = stat.rsplit(")", 1)[1].split()
    return bool(after_comm) and after_comm[0].strip().upper() == "Z"


def pid_is_alive(pid: Any, *, unknown: bool = False, zombie_is_dead: bool = False) -> bool:
    """Liveness for `pid`. `unknown` is what an inconclusive probe returns: a
    mutex that must not be stolen passes True, an advisory check False."""
    if zombie_is_dead and pid_is_zombie(pid):
        return False
    state = probe_pid(pid)
    return unknown if state is None else state


def _psutil_module() -> Any:
    try:
        import psutil  # type: ignore
    except Exception:
        return None
    return psutil


def process_cmdline(pid: Any) -> list[str] | None:
    """argv of `pid`, or None when it cannot be read (gone, no access, or no
    backend). procfs where it exists; psutil otherwise (Windows, macOS)."""
    pid_i = _coerce_pid(pid)
    if pid_i is None:
        return None
    if not is_windows() and os.path.isdir("/proc"):
        try:
            raw = Path(f"/proc/{pid_i}/cmdline").read_bytes()
        except Exception:
            return None
        parts = [part.decode("utf-8", errors="ignore") for part in raw.split(b"\x00") if part]
        return parts or None
    psutil = _psutil_module()
    if psutil is None:
        return None
    try:
        parts = [str(part) for part in psutil.Process(pid_i).cmdline() if part]
    except Exception:
        return None
    return parts or None


def _msvcrt_module() -> Any:
    import msvcrt  # type: ignore

    return msvcrt


def _fcntl_module() -> Any:
    import fcntl  # type: ignore

    return fcntl


def lock_file_exclusive(handle: IO[Any], *, blocking: bool = True) -> None:
    """Exclusive lock on an open file: `fcntl.flock` on POSIX, a 1-byte
    `msvcrt.locking` region at offset 0 on Windows. Raises OSError when a
    non-blocking lock is held elsewhere."""
    if is_windows():
        msvcrt = _msvcrt_module()
        while True:
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                if not blocking:
                    raise
                time.sleep(_MSVCRT_LOCK_POLL_SECONDS)
    fcntl = _fcntl_module()
    flags = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
    fcntl.flock(handle.fileno(), flags)


def unlock_file(handle: IO[Any]) -> None:
    if is_windows():
        msvcrt = _msvcrt_module()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    fcntl = _fcntl_module()
    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def exclusive_file_lock(handle: IO[Any]) -> Iterator[None]:
    """Hold a blocking exclusive lock on `handle` for the body."""
    lock_file_exclusive(handle)
    try:
        yield
    finally:
        try:
            unlock_file(handle)
        except OSError:
            pass
