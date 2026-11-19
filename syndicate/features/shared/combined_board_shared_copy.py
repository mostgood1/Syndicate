"""A combined board built by one web worker, adopted by the others. Lane `board-read-cold-share`.

WHY. `read_combined_intelligence_response` keeps its board in a PER-PROCESS dict. On the fleet,
web runs 2 gunicorn workers, and the memory guard recycles them 13.7 times an hour on a live
evening (11-18 5-11 PM CST, 82 recycles in 6 h). Every new worker starts with an empty dict.
Measured from the fleet web log (`scripts/rail_monitor/coldread_attrib.py`):
- 11-18 5-11 PM CST: 75 of 125 board queries had a cold `board_read` (p50 5.3 s, against
  1-40 ms warm). 69 of the 75 (92%) were the FIRST board read in a freshly booted worker.
- 11-17 5-11 PM CST: 151 of 198 cold (76%) were.
The other worker almost always held a board of the SAME key, fresh by the same rules, built
seconds earlier. Rebuilding it costs 3.9-8.8 s on the request path. Loading a copy costs ~0.7 s.

WHAT. With `SYNDICATE_COMBINED_BOARD_SHARED_COPY` on, every build is also written, streamed by
pickle, to a private directory (`/dev/shm` on the fleet, so no disk I/O). A worker whose own
entry is missing or expired then:
  1. ADOPTS that copy, if it is fresh by the SAME two rules its own cache applies: younger than
     the TTL, and not refused by a newer in-play overlay past the overlay floor;
  2. otherwise takes a cross-process build LEASE, then builds and publishes;
  3. if another live worker holds the lease, it serves the newest copy it has (its own or the
     shared one, <= TTL x 10 old) instead of building the same board twice. The in-process
     single flight already does exactly this between threads (`COMBINED_BOARD_SERVED_STALE`).
     This extends the same rule across processes.
     If no copy that young exists, it builds, as today.

WHY THIS AND NOT A BOOT-TIME WARM. A worker that has built the board sits at anon p50 980 MB
(797-1,225, n 82) against a ~634 MB recycle limit. Warming at boot would put EVERY new worker
over the limit before its first request, and the guard would recycle it at its 120 s minimum
age, so the recycle rate would RISE. Adopting a copy lands the same objects the first request
would have built, minus the build's transients. The copy is streamed in 64 KB pickle frames, so
there is no 40 MB bytes object in the heap on either side.

SAFETY.
- Absent switch = old behaviour: nothing here runs and nothing touches the filesystem.
- The directory is created 0700 and REFUSED unless this uid owns it and nobody else can write
  it, because a pickle is only as trustworthy as whoever could have written it.
- Every failure is a miss, never an error: the caller builds, as it always did.
- A lease is a deadline, not a lock: a builder that dies leaves the key leased for at most
  LEASE_SECONDS (the in-process single flight uses the same 90 s).
"""
from __future__ import annotations

import hashlib
import json
import os
import pickle
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Any

ENV_SWITCH = "SYNDICATE_COMBINED_BOARD_SHARED_COPY"
ENV_DIR = "SYNDICATE_COMBINED_BOARD_SHARED_DIR"
LEASE_SECONDS = 90.0
HEADER_MAX_BYTES = 65536
FORMAT_VERSION = 1
_ON_VALUES = {"1", "true", "yes", "on"}
# A file older than this is never adopted or served (TTL x 10 = 1,800 s on web), so the cleanup
# may remove it. The margin covers a reader that opened it just before.
_CLEANUP_MARGIN_SECONDS = 60.0
_CLEANUP_EVERY_SECONDS = 60.0

_STATE_LOCK = threading.Lock()
_ARMED: dict[str, Any] = {}
_LAST_CLEANUP = 0.0


@dataclass(frozen=True)
class SharedCopy:
    built_at: float
    overlay_mtime: float
    payload: dict
    from_pid: int
    rows: int


@dataclass(frozen=True)
class Lease:
    path: str
    pid: int


def enabled() -> bool:
    """On only when asked for. Absent, empty or anything else = off (the old behaviour)."""
    return str(os.environ.get(ENV_SWITCH) or "").strip().lower() in _ON_VALUES


def _default_dir() -> str:
    uid = os.getuid() if hasattr(os, "getuid") else os.environ.get("USERNAME", "user")
    base = "/dev/shm" if os.path.isdir("/dev/shm") else tempfile.gettempdir()
    return os.path.join(base, f"syndicate-combined-board-{uid}")


def shared_dir() -> str | None:
    """The private directory, created on first use; None when it is unsafe (logged once)."""
    path = str(os.environ.get(ENV_DIR) or "").strip() or _default_dir()
    with _STATE_LOCK:
        known = _ARMED.get(path)
        if known is not None:
            return path if known else None
        ok, why = _prepare_dir(path)
        _ARMED[path] = ok
    if ok:
        print(f"[intelligence_state] COMBINED_BOARD_SHARED_ARMED pid={os.getpid()} dir={path} "
              f"lease_s={LEASE_SECONDS:.0f}", flush=True)
        return path
    print(f"[intelligence_state] COMBINED_BOARD_SHARED_OFF pid={os.getpid()} dir={path} reason={why}", flush=True)
    return None


def _prepare_dir(path: str) -> tuple[bool, str]:
    try:
        os.makedirs(path, mode=0o700, exist_ok=True)
        st = os.stat(path)
    except OSError as exc:
        return False, f"mkdir_failed:{type(exc).__name__}"
    if os.name == "posix":
        if st.st_uid != os.getuid():
            return False, "not_owner"
        if st.st_mode & 0o077:
            return False, f"mode_{st.st_mode & 0o777:o}"
    return True, "ok"


def _key_text(cache_key: Any) -> str:
    return repr(cache_key)


def _paths(directory: str, cache_key: Any) -> tuple[str, str]:
    digest = hashlib.sha256(_key_text(cache_key).encode("utf-8")).hexdigest()[:24]
    return os.path.join(directory, f"{digest}.board"), os.path.join(directory, f"{digest}.lease")


def _python_tag() -> str:
    return f"{sys.version_info[0]}.{sys.version_info[1]}"


def _read_header(handle) -> dict | None:
    line = handle.readline(HEADER_MAX_BYTES)
    if not line.endswith(b"\n"):
        return None
    try:
        header = json.loads(line.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return header if isinstance(header, dict) else None


def _header_matches(header: dict | None, cache_key: Any) -> bool:
    return (
        isinstance(header, dict)
        and header.get("v") == FORMAT_VERSION
        and header.get("key") == _key_text(cache_key)
        and header.get("py") == _python_tag()
        and isinstance(header.get("built_at"), (int, float))
    )


def _load(cache_key: Any, accept) -> SharedCopy | None:
    """Open the copy, read ONLY its header, and load the board only when `accept(header)` says so.

    One open handle for both reads: `os.replace` swaps the directory entry, never the inode an
    open handle reads, so the header and the board always come from the same write."""
    directory = shared_dir()
    if directory is None:
        return None
    board_path, _ = _paths(directory, cache_key)
    try:
        with open(board_path, "rb") as handle:
            header = _read_header(handle)
            if not _header_matches(header, cache_key) or not accept(header):
                return None
            payload = pickle.load(handle)
    except FileNotFoundError:
        return None
    except Exception as exc:  # noqa: BLE001 -- a bad copy is a miss; the caller builds
        print(f"[intelligence_state] COMBINED_BOARD_SHARED_READ_FAILED {type(exc).__name__}: {exc}", flush=True)
        return None
    if not isinstance(payload, dict):
        return None
    return SharedCopy(
        built_at=float(header["built_at"]),
        overlay_mtime=float(header.get("overlay_mtime") or 0.0),
        payload=payload,
        from_pid=int(header.get("pid") or 0),
        rows=int(header.get("rows") or 0),
    )


def overlay_refuses(newest_overlay: float, built_overlay: float, age_s: float, min_age_s: float) -> bool:
    """The in-process cache's overlay rule (`_combined_board_overlay_state`), applied to a copy."""
    return newest_overlay > built_overlay and age_s >= min_age_s


def adopt_fresh(cache_key: Any, *, newer_than: float | None, newest_overlay: float, ttl_s: float,
                overlay_min_age_s: float, now: float | None = None) -> SharedCopy | None:
    """The shared copy, if it is newer than `newer_than` (this worker's own entry) and as fresh
    as this worker's cache would demand of its own entry."""
    now = time.time() if now is None else now

    def accept(header: dict) -> bool:
        built_at = float(header["built_at"])
        if newer_than is not None and built_at <= newer_than:
            return False
        age = now - built_at
        if age >= ttl_s:
            return False
        return not overlay_refuses(newest_overlay, float(header.get("overlay_mtime") or 0.0), age, overlay_min_age_s)

    return _load(cache_key, accept)


def stale_copy(cache_key: Any, *, newer_than: float | None, max_age_s: float,
               now: float | None = None) -> SharedCopy | None:
    """The shared copy if it is newer than `newer_than` and no older than `max_age_s`: what to
    serve while another worker rebuilds."""
    now = time.time() if now is None else now

    def accept(header: dict) -> bool:
        built_at = float(header["built_at"])
        if newer_than is not None and built_at <= newer_than:
            return False
        return now - built_at <= max_age_s

    return _load(cache_key, accept)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name != "posix":
        # os.kill(pid, 0) TERMINATES the process on Windows. The lease age alone decides there.
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _read_lease(path: str) -> dict | None:
    try:
        with open(path, "rb") as handle:
            info = json.loads(handle.read(4096).decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return info if isinstance(info, dict) else None


def _lease_is_live_elsewhere(info: dict | None, now: float) -> bool:
    if not isinstance(info, dict):
        return False
    pid = int(info.get("pid") or 0)
    started = float(info.get("started_at") or 0.0)
    return pid != os.getpid() and (now - started) < LEASE_SECONDS and _pid_alive(pid)


def acquire_lease(cache_key: Any, *, now: float | None = None) -> Lease | None:
    """The build lease for this key, or None when ANOTHER live worker holds it.

    A lease left by this process (a build that raised), by a dead pid, or older than
    LEASE_SECONDS is taken over. The caller already owns the in-process single flight, so no
    other thread of this process can be building the key."""
    directory = shared_dir()
    if directory is None:
        return None
    _, lease_path = _paths(directory, cache_key)
    now = time.time() if now is None else now
    body = json.dumps({"pid": os.getpid(), "started_at": now, "key": _key_text(cache_key)}).encode("utf-8")
    for _ in range(2):
        try:
            fd = os.open(lease_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if _lease_is_live_elsewhere(_read_lease(lease_path), now):
                return None
            try:
                os.unlink(lease_path)
            except OSError:
                pass
            continue
        except OSError:
            return None
        with os.fdopen(fd, "wb") as handle:
            handle.write(body)
        return Lease(path=lease_path, pid=os.getpid())
    return None


def held_elsewhere(cache_key: Any, *, now: float | None = None) -> bool:
    directory = shared_dir()
    if directory is None:
        return False
    _, lease_path = _paths(directory, cache_key)
    return _lease_is_live_elsewhere(_read_lease(lease_path), time.time() if now is None else now)


def release_lease(lease: Lease | None) -> None:
    if lease is None:
        return
    info = _read_lease(lease.path)
    if isinstance(info, dict) and int(info.get("pid") or 0) == lease.pid:
        try:
            os.unlink(lease.path)
        except OSError:
            pass


def publish(cache_key: Any, *, built_at: float, overlay_mtime: float, payload: dict, rows: int,
            lease: Lease | None) -> bool:
    """Write this worker's build for the others, then release the lease. Never raises.

    Skipped when the copy already there is NEWER, so a slow builder cannot replace a fresher
    board. Written to a temp file and swapped in with `os.replace`, so a reader never sees half
    a board."""
    directory = shared_dir()
    if directory is None:
        release_lease(lease)
        return False
    board_path, _ = _paths(directory, cache_key)
    tmp_path = f"{board_path}.{os.getpid()}.{threading.get_ident()}.tmp"
    started = time.perf_counter()
    try:
        try:
            with open(board_path, "rb") as handle:
                existing = _read_header(handle)
            if _header_matches(existing, cache_key) and float(existing["built_at"]) > built_at:
                return False
        except FileNotFoundError:
            pass
        header = {"v": FORMAT_VERSION, "key": _key_text(cache_key), "py": _python_tag(), "pid": os.getpid(),
                  "built_at": built_at, "overlay_mtime": float(overlay_mtime or 0.0), "rows": int(rows)}
        with open(tmp_path, "wb") as handle:
            handle.write(json.dumps(header).encode("utf-8") + b"\n")
            # Streamed in protocol-5 frames: no whole-board bytes object is ever built.
            pickle.dump(payload, handle, protocol=5)
            size = handle.tell()
        os.replace(tmp_path, board_path)
    except Exception as exc:  # noqa: BLE001 -- sharing is an optimisation; the board is already cached here
        print(f"[intelligence_state] COMBINED_BOARD_SHARED_PUBLISH_FAILED {type(exc).__name__}: {exc}", flush=True)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        return False
    finally:
        release_lease(lease)
    print(f"[intelligence_state] COMBINED_BOARD_SHARED_PUBLISHED pid={os.getpid()} rows={rows} "
          f"mb={size / 1e6:.1f} write_s={time.perf_counter() - started:.2f}", flush=True)
    _cleanup(directory, keep_seconds=_cleanup_keep_seconds())
    return True


def _cleanup_keep_seconds() -> float:
    try:
        ttl = float(os.environ.get("SYNDICATE_INTELLIGENCE_COMBINED_BOARD_CACHE_SECONDS") or 15)
    except ValueError:
        ttl = 15.0
    return max(ttl, 1.0) * 10.0 + _CLEANUP_MARGIN_SECONDS


def _cleanup(directory: str, *, keep_seconds: float, now: float | None = None) -> int:
    """Remove copies no reader may use any more, abandoned temp files and expired leases."""
    global _LAST_CLEANUP
    now = time.time() if now is None else now
    with _STATE_LOCK:
        if now - _LAST_CLEANUP < _CLEANUP_EVERY_SECONDS:
            return 0
        _LAST_CLEANUP = now
    removed = 0
    try:
        names = os.listdir(directory)
    except OSError:
        return 0
    for name in names:
        if not name.endswith((".board", ".tmp", ".lease")):
            continue
        path = os.path.join(directory, name)
        limit = LEASE_SECONDS * 2 if name.endswith(".lease") else keep_seconds
        try:
            if now - os.stat(path).st_mtime > limit:
                os.unlink(path)
                removed += 1
        except OSError:
            continue
    return removed


def _reset_for_tests() -> None:
    global _LAST_CLEANUP
    with _STATE_LOCK:
        _ARMED.clear()
        _LAST_CLEANUP = 0.0
