from __future__ import annotations

import contextlib
import gc
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any

try:
    import psutil
except Exception:  # pragma: no cover - psutil is optional in some local environments
    psutil = None


_BYTES_PER_MB = 1024 * 1024
_BYTES_PER_KB = 1024
_PROCFS_ROOT = Path("/proc")
# A smaps mapping header: "7f3c-7f4d rw-p 00000000 00:00 0    [heap]".
# Anchored so a field line ("Anonymous:  12 kB") can never match it.
_SMAPS_HEADER_RE = re.compile(r"^[0-9a-fA-F]+-[0-9a-fA-F]+\s+\S{4}\s+\S+\s+\S+\s+\d+")


def _bytes_to_mb(value: int | float | None) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value) / float(_BYTES_PER_MB), 3)
    except Exception:
        return None


def _current_process_rss_bytes() -> int | None:
    if psutil is not None:
        try:
            return int(psutil.Process().memory_info().rss)
        except Exception:
            pass
    try:
        import ctypes
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        process = ctypes.windll.kernel32.OpenProcess(0x1000 | 0x0400, False, os.getpid())
        if not process:
            return None
        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        if ctypes.windll.psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb):
            return int(counters.WorkingSetSize)
    except Exception:
        pass
    try:
        with open("/proc/self/status", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        return int(parts[1]) * 1024
    except Exception:
        pass
    return None


def _read_container_memory_current_bytes() -> int | None:
    candidates = (
        Path("/sys/fs/cgroup/memory.current"),
        Path("/sys/fs/cgroup/memory/memory.usage_in_bytes"),
    )
    for candidate in candidates:
        try:
            if not candidate.exists() or not candidate.is_file():
                continue
            raw = candidate.read_text(encoding="utf-8", errors="ignore").strip()
            if not raw:
                continue
            return int(raw)
        except Exception:
            continue
    return None


def container_memory_current_mb() -> float | None:
    """The cgroup's current memory, as ONE file read. `#327`.

    Exists so a hot loop can sample memory without paying for
    `get_all_process_memory_snapshot()`, which walks every process in the
    container. That cost is fine a few times a minute and ruinous per-artifact
    inside a 94-file publish sweep.

    WHY THE CHEAP READ IS ALSO THE RIGHT ONE HERE: `container_memory_mb` is the
    cgroup figure the OOM killer acts on, and during the `#327` excursion it
    diverged from `accounted_rss_mb` by ~800MB. For "did this stage take the
    container near its cap", this is the number that matters -- the process
    walk buys attribution, not accuracy.
    """
    return _bytes_to_mb(_read_container_memory_current_bytes())


def _read_container_memory_max_bytes() -> int | None:
    # memory.current alone can't say how close a container is to being
    # OOM-killed -- it includes reclaimable page cache and looks alarming
    # even when nothing is actually at risk. This reads the cgroup's own
    # configured ceiling so callers can compute real headroom instead of
    # guessing from the raw usage number.
    candidates = (
        Path("/sys/fs/cgroup/memory.max"),
        Path("/sys/fs/cgroup/memory/memory.limit_in_bytes"),
    )
    for candidate in candidates:
        try:
            if not candidate.exists() or not candidate.is_file():
                continue
            raw = candidate.read_text(encoding="utf-8", errors="ignore").strip()
            if not raw or raw == "max":
                continue
            value = int(raw)
            # cgroup v1's unset limit_in_bytes reads as a huge sentinel
            # (commonly 2^63-1 rounded to page size) rather than "max".
            if value >= (1 << 62):
                continue
            return value
        except Exception:
            continue
    return None


_MEMORY_STAT_KEYS_OF_INTEREST = (
    "anon",
    "file",
    "inactive_file",
    "active_file",
    "inactive_anon",
    "active_anon",
    "slab",
    "slab_reclaimable",
    "slab_unreclaimable",
    "shmem",
    "sock",
    "kernel_stack",
)


def _read_container_memory_stat() -> dict[str, int]:
    """The cgroup's own `key value` breakdown of memory.current.

    #79. The comment on _read_container_memory_max_bytes above already says
    memory.current "includes reclaimable page cache and looks alarming even
    when nothing is actually at risk" -- and memory_headroom_snapshot then
    computes headroom as max - current anyway. On refresh-worker 2026-07-26
    that reads 3309MB of 4096 with only 451MB accounted to any process, so the
    board build refuses to start every cycle (#79) on 2860MB nobody owns.

    This reads the breakdown so that gap can be attributed rather than
    guessed at. Diagnostic only -- `sufficient` is deliberately still computed
    from max - current, because if the unaccounted memory turns out to be
    anonymous rather than file cache then the guard is correct as written and
    relaxing it walks back into the 4GiB OOM (#75).
    """
    candidates = (
        Path("/sys/fs/cgroup/memory.stat"),
        Path("/sys/fs/cgroup/memory/memory.stat"),
    )
    for candidate in candidates:
        try:
            if not candidate.exists() or not candidate.is_file():
                continue
            values: dict[str, int] = {}
            for line in candidate.read_text(encoding="utf-8", errors="ignore").splitlines():
                parts = line.split()
                if len(parts) != 2:
                    continue
                # cgroup v1 prefixes the hierarchical rollups with "total_";
                # prefer the plain key but accept either so one reader covers
                # both layouts.
                key = parts[0][6:] if parts[0].startswith("total_") else parts[0]
                if key not in _MEMORY_STAT_KEYS_OF_INTEREST or key in values:
                    continue
                try:
                    values[key] = int(parts[1])
                except ValueError:
                    continue
            if values:
                return values
        except Exception:
            continue
    return {}


def _reclaimable_file_bytes(stat: dict[str, int]) -> int:
    """Clean page cache the kernel drops rather than OOM-killing over.

    `#417`. `active_file` is included. It was excluded until 2026-08-13 on the
    reasoning that it is "evictable but only under real pressure", which is
    true and is not a reason to exclude it: pressure is exactly the situation
    the guard exists for. Excluding it made the reading swing by the size of
    whatever the kernel had most recently touched.
    """
    if not stat:
        return 0
    return max(
        0,
        stat.get("inactive_file", 0) + stat.get("active_file", 0) + stat.get("slab_reclaimable", 0),
    )


def _unreclaimable_bytes(stat: dict[str, int], current_bytes: int | None = None) -> int | None:
    """What an OOM kill actually responds to. Returns None when unmeasurable.

    `#417`. Two independent bases, and this deliberately takes the LARGER:

    - `anon + shmem + slab_unreclaimable` -- proven unreclaimable, a LOWER
      bound. Everything it omits is treated as free.
    - `current - reclaimable_file` -- everything not proven reclaimable, an
      UPPER bound. This is the basis `#318` already used for the log line.

    They differ by whatever `memory.stat` does not attribute (~5MB on the
    `#417` refresh-worker samples, but there is no guarantee it stays small;
    `#327` has an unattributed allocator open at 493-878MB by a different
    measure). Taking the max means unaccounted memory counts against the
    guard rather than being silently credited as available -- the difference
    between a lower bound and an upper bound is exactly the permissive-on-
    unknown shape this codebase keeps getting caught by.

    Returns None when there is no usable breakdown, so callers degrade to the
    older arithmetic instead of reading "nothing is unreclaimable, the
    container is empty" off an unparseable file.

    `anon` is required. `shmem` and `slab_unreclaimable` default to 0 when
    absent; cgroup v2 emits `memory.stat` as one block, so `anon` present with
    `shmem` missing is not a shape this file can observe, and the max() above
    covers the gap regardless. `anon` and `shmem` do not overlap in cgroup v2
    -- shared memory is accounted under `file` -- so this sums rather than
    double counts. `kernel_stack` and `sock` are unreclaimable too and are not
    named here: both are small, both are already carried in `stat_mb`, and the
    residual basis picks them up anyway.
    """
    if not stat or "anon" not in stat:
        return None
    proven = stat.get("anon", 0) + stat.get("shmem", 0) + stat.get("slab_unreclaimable", 0)
    if current_bytes is None:
        return max(0, proven)
    residual_basis = current_bytes - _reclaimable_file_bytes(stat)
    return max(0, proven, residual_basis)


def memory_headroom_snapshot(min_required_bytes: int) -> dict[str, Any] | None:
    # Shared by any caller that wants to defer heavy in-process work rather
    # than guess from elapsed time or trigger type -- originally lived only in
    # live_refresh_loop.py's odds-refresh gate; extracted here so the MLB
    # live-lens loop's estimate_live gate can reuse the same real,
    # currently-measured cgroup headroom instead of duplicating this logic.
    # Returns None when headroom can't be measured at all (e.g. local dev
    # without cgroups) -- callers should treat that the same as "not
    # sufficient," the safe default.
    current_bytes = _read_container_memory_current_bytes()
    max_bytes = _read_container_memory_max_bytes()
    if current_bytes is None or max_bytes is None or max_bytes <= 0:
        return None
    min_required = max(0, int(min_required_bytes))
    raw_headroom_bytes = max_bytes - current_bytes

    # #79 step 2. Headroom used to be max - memory.current, and cgroup v2's
    # memory.current counts reclaimable page cache -- which the kernel drops
    # on demand rather than OOM-killing over. The comment on
    # _read_container_memory_max_bytes above has said so all along; the
    # calculation just never acted on it.
    #
    # Measured on refresh-worker 2026-07-26T22:47Z, which had been refusing to
    # build the board every cycle:
    #   current 3228.3 / max 4096 -> headroom 867.7 against a 900 floor
    #   anon           662.5   <- the only unreclaimable memory
    #   inactive_file 2476.3   <- clean, evictable
    #   shmem            0.0   <- so none of the cache is pinned
    # Real headroom was 3393.7MB, not 867.7MB, and the board build (measured
    # idling ~700MB, spiking past 1479MB) fits nearly three times over. This
    # is also the "2.7GB plateau" the 2026-07-26 handoff left open: not a
    # leak, page cache from the 1.24GB odds-events file (#76), which is
    # exactly why tracemalloc could never see it.
    #
    stat = _read_container_memory_stat()
    reclaimable_bytes = _reclaimable_file_bytes(stat)

    # #417 step 3. The step-2 note below has the right idea and the wrong
    # quantity. Crediting only `inactive_file` back was described as "the
    # conservative reading of reclaimable" -- but excluding `active_file` is
    # not conservative, it is UNSTABLE. Both buckets hold clean, evictable page
    # cache; which one a page sits in is kernel LRU bookkeeping, and the kernel
    # moves pages between them on its own.
    #
    # Measured on refresh-worker 2026-08-13, 300 consecutive
    # MEMORY_GUARD_ABORT cycles that served a 4h12m-stale board:
    #   time       anon   active_file  inactive_file  headroom  current
    #   10:37:27  1641.1       553.9         757.7     1895.3   2993.7
    #   11:02:03  1648.9       797.4         218.0     1643.5   2705.3
    # At ~11:02 the kernel promoted ~243MB inactive_file -> active_file. Total
    # file cache SHRANK (1289 -> 1015MB) and memory in use FELL (2993.7 ->
    # 2705.3MB), yet headroom dropped 251.8MB and never recovered. `anon` moved
    # +7.8MB. Across all 300 samples anon drifted +18.9MB total -- flat, so
    # this was never a leak and never real pressure.
    #
    # The rule that follows, and the reason this is an axis change rather than
    # a retuned constant: IF USAGE GOING DOWN CAN MAKE A GUARD STRICTER, THE
    # GUARD IS READING THE WRONG QUANTITY. Guard on what an OOM kill responds
    # to -- unreclaimable memory -- and the LRU shuffle stops being visible to
    # the decision at all.
    #
    # This is deliberately NOT a relaxation of #75/#279's protection. Anonymous
    # memory still counts against headroom in full; the container that is
    # genuinely full of anon is still refused, which is what those OOM kills
    # were about. What changes is that clean page cache stops being able to
    # veto a build it would have been dropped for.
    unreclaimable_bytes = _unreclaimable_bytes(stat, current_bytes)
    if unreclaimable_bytes is None:
        # No usable breakdown (local dev without cgroups, or an unreadable
        # memory.stat). Degrade to the previous arithmetic rather than to
        # anything rosier -- failing back to known-conservative behaviour is
        # what keeps a bad read from re-opening #75.
        effective_headroom_bytes = raw_headroom_bytes + reclaimable_bytes
    else:
        effective_headroom_bytes = max_bytes - unreclaimable_bytes

    snapshot: dict[str, Any] = {
        "current_mb": round(current_bytes / 1024 / 1024, 1),
        "max_mb": round(max_bytes / 1024 / 1024, 1),
        "headroom_mb": round(effective_headroom_bytes / 1024 / 1024, 1),
        "min_required_mb": round(min_required / 1024 / 1024, 1),
        "sufficient": effective_headroom_bytes >= min_required,
    }
    # Named for what it is, and kept beside the verdict so an abort line says
    # which basis produced it. `basis` is the discriminator to read first: a
    # refusal on basis=reclaimable_cache means the breakdown was unreadable,
    # not that memory was tight.
    snapshot["basis"] = "reclaimable_cache" if unreclaimable_bytes is None else "unreclaimable"
    if unreclaimable_bytes is not None:
        snapshot["unreclaimable_mb"] = round(unreclaimable_bytes / 1024 / 1024, 1)
    if stat:
        # Kept so a future reader can see both numbers rather than having to
        # rediscover why they differ -- and so that if the gap ever stops
        # being file cache, that is visible in the same line.
        snapshot["stat_mb"] = {key: round(value / 1024 / 1024, 1) for key, value in sorted(stat.items())}
        snapshot["reclaimable_file_mb"] = round(reclaimable_bytes / 1024 / 1024, 1)
        # #417's second defect. This was `headroom_including_file_cache_mb`,
        # which is the opposite of what it holds: raw `max - current` EXCLUDES
        # the file cache, and `headroom_mb` is the number that accounts for it.
        # The name cost real time during the 08-13 incident -- a reader saw
        # `headroom_including_file_cache_mb: 1107.7` against `min_required
        # 1900` and computed a 792MB deficit when the guard had actually
        # compared 1621.7, a deficit of 278MB. Renamed rather than aliased:
        # nothing outside this module's own tests reads it, and leaving the old
        # key in place would preserve the exact misreading it caused.
        snapshot["headroom_excluding_file_cache_mb"] = round(raw_headroom_bytes / 1024 / 1024, 1)
    return snapshot


def _process_cmdline(value: Any) -> list[str]:
    if not value:
        return []
    try:
        return [str(item) for item in value]
    except Exception:
        return []


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except Exception:
        return None


def _append_process_enum_error(errors: list[str], label: str, exc: Exception) -> None:
    errors.append(f"{label}:{type(exc).__name__}: {exc}")


def _procfs_pid_list() -> list[int]:
    try:
        if not _PROCFS_ROOT.exists():
            return []
        pids = [int(entry.name) for entry in _PROCFS_ROOT.iterdir() if entry.name.isdigit()]
        pids.sort()
        return pids
    except Exception:
        return []


def _procfs_process_snapshot(pid: int, *, force_include: bool = False) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    process_dir = _PROCFS_ROOT / str(pid)
    name: str | None = None
    ppid: int | None = None
    cmdline: list[str] = []
    rss_bytes: int | None = None

    try:
        with open(process_dir / "status", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                if line.startswith("Name:"):
                    name = line.split(":", 1)[1].strip() or name
                elif line.startswith("PPid:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        ppid = _safe_int(parts[1])
                elif line.startswith("VmRSS:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        rss_value = _safe_int(parts[1])
                        if rss_value is not None:
                            rss_bytes = rss_value * _BYTES_PER_KB
    except Exception as exc:
        _append_process_enum_error(errors, f"procfs_status:{pid}", exc)

    try:
        raw_cmdline = (process_dir / "cmdline").read_bytes()
        cmdline = [part.decode("utf-8", errors="ignore") for part in raw_cmdline.split(b"\0") if part]
    except Exception as exc:
        _append_process_enum_error(errors, f"procfs_cmdline:{pid}", exc)

    try:
        comm = (process_dir / "comm").read_text(encoding="utf-8", errors="ignore").strip()
        if not name:
            name = comm
    except Exception as exc:
        _append_process_enum_error(errors, f"procfs_comm:{pid}", exc)

    if pid == os.getpid():
        if ppid is None:
            ppid = os.getppid()
        if not cmdline:
            cmdline = list(sys.argv)
        if rss_bytes is None:
            rss_bytes = _current_process_rss_bytes()
        if not name:
            name = Path(sys.argv[0]).name or "current_process"
    elif pid == os.getppid() and not name:
        name = "parent_process"

    if not force_include and not any((name, ppid is not None, cmdline, rss_bytes is not None)):
        return None, errors

    record = {
        "pid": int(pid),
        "ppid": int(ppid if ppid is not None else -1),
        "name": str(name or ("current_process" if pid == os.getpid() else "parent_process" if pid == os.getppid() else f"pid:{pid}")),
        "cmdline": cmdline or ([] if pid != os.getpid() else list(sys.argv)),
        "rss_mb": _bytes_to_mb(rss_bytes),
        "_rss_bytes": rss_bytes,
    }
    return record, errors


def _psutil_enumeration_debug() -> dict[str, Any]:
    debug: dict[str, Any] = {
        "psutil_available": psutil is not None,
        "psutil_pid_count": None,
        "psutil_iterated_count": 0,
        "procfs_pid_count": None,
        "procfs_iterated_count": 0,
        "first_pids": [],
        "error_count": 0,
        "errors": [],
    }

    if psutil is None:
        debug["errors"].append("psutil_unavailable:ImportError")
        debug["error_count"] = 1
        return debug

    try:
        pids = psutil.pids()
        debug["psutil_pid_count"] = len(pids)
    except Exception as exc:
        _append_process_enum_error(debug["errors"], "psutil.pids", exc)

    access_denied_exc = getattr(psutil, "AccessDenied", PermissionError)
    no_such_process_exc = getattr(psutil, "NoSuchProcess", ProcessLookupError)
    zombie_process_exc = getattr(psutil, "ZombieProcess", RuntimeError)

    try:
        for process in psutil.process_iter():
            try:
                info = process.as_dict(attrs=["pid", "ppid", "name", "cmdline", "memory_info"], ad_value=None)
                pid = _safe_int(info.get("pid") or getattr(process, "pid", None))
                if pid is not None:
                    debug["psutil_iterated_count"] += 1
                    if len(debug["first_pids"]) < 5:
                        debug["first_pids"].append(pid)
            except (access_denied_exc, no_such_process_exc, zombie_process_exc) as exc:
                _append_process_enum_error(debug["errors"], f"psutil.process_iter:{getattr(process, 'pid', 'unknown')}", exc)
            except Exception as exc:
                _append_process_enum_error(debug["errors"], f"psutil.process_iter:{getattr(process, 'pid', 'unknown')}", exc)
    except Exception as exc:
        _append_process_enum_error(debug["errors"], "psutil.process_iter", exc)

    debug["error_count"] = len(debug["errors"])
    return debug


def get_process_tree_memory_snapshot() -> dict[str, Any]:
    self_rss_bytes = _current_process_rss_bytes()
    children: list[dict[str, Any]] = []
    tree_rss_bytes = int(self_rss_bytes or 0)

    if psutil is not None:
        try:
            current_process = psutil.Process()
            for child in current_process.children(recursive=True):
                try:
                    rss_bytes = int(child.memory_info().rss)
                    tree_rss_bytes += rss_bytes
                    children.append(
                        {
                            "pid": int(child.pid),
                            "name": str(child.name()),
                            "rss_mb": _bytes_to_mb(rss_bytes),
                        }
                    )
                except Exception as child_exc:
                    child_name = None
                    try:
                        child_name = str(child.name())
                    except Exception:
                        child_name = None
                    children.append(
                        {
                            "pid": int(getattr(child, "pid", -1) or -1),
                            "name": child_name,
                            "rss_mb": None,
                            "error": f"{type(child_exc).__name__}: {child_exc}",
                        }
                    )
        except Exception as exc:
            children.append({"pid": None, "name": None, "rss_mb": None, "error": f"{type(exc).__name__}: {exc}"})

    return {
        "self_rss_mb": _bytes_to_mb(self_rss_bytes),
        "tree_rss_mb": _bytes_to_mb(tree_rss_bytes),
        "child_count": len(children),
        "children": children,
    }


def get_all_process_memory_snapshot() -> dict[str, Any]:
    debug = _psutil_enumeration_debug()
    processes_by_pid: dict[int, dict[str, Any]] = {}
    process_errors: list[str] = []

    procfs_pids = _procfs_pid_list()
    debug["procfs_pid_count"] = len(procfs_pids)
    debug["first_pids"] = procfs_pids[:5]

    if procfs_pids:
        for pid in procfs_pids:
            record, errors = _procfs_process_snapshot(pid)
            process_errors.extend(errors)
            if record is None:
                continue
            processes_by_pid[int(record["pid"])] = record
        debug["procfs_iterated_count"] = len(processes_by_pid)

    if not processes_by_pid and psutil is not None:
        try:
            for process in psutil.process_iter():
                try:
                    info = process.as_dict(attrs=["pid", "ppid", "name", "cmdline", "memory_info"], ad_value=None)
                    memory_info = info.get("memory_info")
                    rss_bytes = None
                    try:
                        rss_value = getattr(memory_info, "rss", None) if memory_info is not None else None
                        if rss_value is not None:
                            rss_bytes = int(rss_value)
                    except Exception as exc:
                        _append_process_enum_error(process_errors, f"psutil_memory_info:{getattr(process, 'pid', 'unknown')}", exc)

                    pid = _safe_int(info.get("pid") or getattr(process, "pid", None))
                    if pid is None:
                        continue
                    processes_by_pid[pid] = {
                        "pid": pid,
                        "ppid": int(info.get("ppid") or -1),
                        "name": str(info.get("name") or ""),
                        "cmdline": _process_cmdline(info.get("cmdline")),
                        "rss_mb": _bytes_to_mb(rss_bytes),
                        "_rss_bytes": rss_bytes,
                    }
                except Exception as exc:
                    _append_process_enum_error(process_errors, f"psutil_process:{getattr(process, 'pid', 'unknown')}", exc)
        except Exception as exc:
            _append_process_enum_error(process_errors, "psutil_process_iter_fallback", exc)

    required_pids = [os.getpid(), os.getppid()]
    for required_pid in required_pids:
        if required_pid in processes_by_pid:
            continue
        record, errors = _procfs_process_snapshot(required_pid, force_include=True)
        process_errors.extend(errors)
        if record is None:
            current_rss_bytes = _current_process_rss_bytes() if required_pid == os.getpid() else None
            record = {
                "pid": int(required_pid),
                "ppid": int(os.getppid() if required_pid == os.getpid() else -1),
                "name": "current_process" if required_pid == os.getpid() else "parent_process",
                "cmdline": list(sys.argv) if required_pid == os.getpid() else [],
                "rss_mb": _bytes_to_mb(current_rss_bytes),
                "_rss_bytes": current_rss_bytes,
            }
        processes_by_pid[int(record["pid"])] = record

    processes = list(processes_by_pid.values())
    processes.sort(key=lambda item: int(item.get("_rss_bytes") or 0), reverse=True)
    accounted_rss_bytes = 0
    for process in processes:
        rss_bytes = process.pop("_rss_bytes", None)
        if isinstance(rss_bytes, int):
            accounted_rss_bytes += rss_bytes

    container_memory_bytes = _read_container_memory_current_bytes()
    container_memory_max_bytes = _read_container_memory_max_bytes()
    payload = {
        "process_count": len(processes),
        "accounted_rss_mb": _bytes_to_mb(accounted_rss_bytes),
        "container_memory_mb": _bytes_to_mb(container_memory_bytes),
        "container_memory_max_mb": _bytes_to_mb(container_memory_max_bytes),
        "container_memory_headroom_mb": None,
        "container_memory_pct_of_max": None,
        # `#566`. THE SAME FIX THIS MODULE ALREADY MADE FOR `CONTAINER_MEMORY`,
        # applied to the OTHER line people read.
        #
        # `log_container_memory`'s docstring records it exactly: the breakdown
        # "was simply never wired into the line that gets logged, which is the
        # one people actually read." That was fixed for `CONTAINER_MEMORY` and
        # left undone here -- and `ALL_PROCESS_MEMORY` is the line a deploy
        # preflight reads, because it is the one carrying the process list.
        #
        # MEASURED BY BEING TAKEN IN 2026-08-25. Across one session I quoted
        # `container_memory_pct_of_max` at 93.2%, 96.8% and 99.8% off THIS line
        # and reported a memory emergency to the user four times. There was
        # none: zero `oomKilled` events in the preceding two days, and anonymous
        # memory over the same window ran 1135-1760 MB of 4096 -- **28-43%**.
        # The 99.8% was clean page cache the kernel drops before it OOM-kills
        # anything, which is what `#79` and `#417` already established twice.
        #
        # A reader who has both numbers cannot make that mistake; a reader who
        # has only the first one reliably does. Same procfs read the guard
        # beside it already performs, so this costs nothing new.
        "container_memory_unreclaimable_mb": None,
        "container_memory_unreclaimable_pct_of_max": None,
        "unexplained_memory_mb": None,
        "processes": processes,
        "process_enum_debug": {
            **debug,
            "error_count": len(process_errors) + int(debug.get("error_count") or 0),
            "errors": [*debug.get("errors", []), *process_errors],
            "first_pids": [int(pid) for pid in (debug.get("first_pids") or [])[:5]],
        },
    }
    if isinstance(container_memory_bytes, int):
        payload["unexplained_memory_mb"] = _bytes_to_mb(container_memory_bytes - accounted_rss_bytes)
        if isinstance(container_memory_max_bytes, int) and container_memory_max_bytes > 0:
            payload["container_memory_headroom_mb"] = _bytes_to_mb(container_memory_max_bytes - container_memory_bytes)
            payload["container_memory_pct_of_max"] = round(100.0 * container_memory_bytes / container_memory_max_bytes, 1)
        # DEGRADES TO None, NEVER TO THE MISLEADING FIGURE. An unreadable
        # `memory.stat` (local dev, no cgroups) must leave these absent rather
        # than fall back to `container_memory_mb` -- a reader who sees a number
        # here is entitled to assume it is the anonymous one, and quietly
        # serving them the page-cache-inclusive figure under this name would be
        # worse than the omission this whole change is fixing.
        try:
            unreclaimable_bytes = _unreclaimable_bytes(_read_container_memory_stat(), container_memory_bytes)
        except Exception:  # noqa: BLE001 - telemetry must never raise
            unreclaimable_bytes = None
        if isinstance(unreclaimable_bytes, int):
            payload["container_memory_unreclaimable_mb"] = _bytes_to_mb(unreclaimable_bytes)
            if isinstance(container_memory_max_bytes, int) and container_memory_max_bytes > 0:
                payload["container_memory_unreclaimable_pct_of_max"] = round(
                    100.0 * unreclaimable_bytes / container_memory_max_bytes, 1
                )
    return payload


def log_process_tree_memory(stage: str, **extra: Any) -> dict[str, Any]:
    payload = {"stage": str(stage or "").strip() or "unknown"}
    payload.update(extra)
    payload.update(get_process_tree_memory_snapshot())
    print(f"PROCESS_TREE_MEMORY {json.dumps(payload, default=str, sort_keys=True)}", file=sys.stderr, flush=True)
    return payload


def log_container_memory(stage: str, **extra: Any) -> dict[str, Any]:
    """`memory.current` AND the anon/cache split that says whether it matters.

    `#318`. This logger reported `memory.current` alone, and on a 2GiB service
    that is not a reading anyone can act on. Measured on web 2026-08-09
    21:00:47Z, seconds before an `oomKilled`:

        CONTAINER_MEMORY  memory_current_mb 1877.1  memory_pct_of_max 91.7
        PROCESS_TREE_MEMORY  self_rss_mb 189.1  child_count 0

    91.7% of the limit with 189MB accounted to any process. Those two lines are
    equally consistent with a runaway leak and with a container that is simply
    warm with evictable page cache, and nothing else on the service could tell
    them apart -- so six OOM kills in 69 minutes were diagnosed by guessing at
    which requests looked expensive.

    `_read_container_memory_stat()` has read `anon`/`inactive_file` since `#79`
    and `memory_headroom_snapshot` already uses it for exactly this reason.
    It was simply never wired into the line that gets logged, which is the one
    people actually read. That is the whole change: no new capability, no
    behaviour change, one more small procfs read beside the two this function
    already does.

    Read `memory_unreclaimable_mb` first. `memory_current_mb` counts clean page
    cache the kernel will drop before it ever OOM-kills anything; the anonymous
    figure is the part that cannot be reclaimed and is therefore the part that
    kills the container.
    """
    payload = container_memory_payload(stage, **extra)
    _note_stage_seen(payload.get("stage"))
    print(f"CONTAINER_MEMORY {json.dumps(payload, default=str, sort_keys=True)}", file=sys.stderr, flush=True)
    return payload


def container_memory_payload(stage: str, **extra: Any) -> dict[str, Any]:
    """The `CONTAINER_MEMORY` payload, WITHOUT printing it.

    Split out of `log_container_memory` for `#435`'s watchdog. The docstring
    above records that `memory_reclaimable_mb` was once computed a second time
    independently, so a fix to the guard left the line humans read quietly
    contradicting the decision it explained. A sampler that rebuilt this payload
    would reintroduce exactly that -- on the one reading taken while the process
    is dying. One builder, two callers.
    """
    memory_current_bytes = _read_container_memory_current_bytes()
    memory_max_bytes = _read_container_memory_max_bytes()
    payload = {
        "stage": str(stage or "").strip() or "unknown",
        "memory_current_mb": _bytes_to_mb(memory_current_bytes),
        "memory_max_mb": _bytes_to_mb(memory_max_bytes),
        "memory_headroom_mb": None,
        "memory_pct_of_max": None,
    }
    if isinstance(memory_current_bytes, int) and isinstance(memory_max_bytes, int) and memory_max_bytes > 0:
        payload["memory_headroom_mb"] = _bytes_to_mb(memory_max_bytes - memory_current_bytes)
        payload["memory_pct_of_max"] = round(100.0 * memory_current_bytes / memory_max_bytes, 1)
    # Absent keys stay None rather than 0. A cgroup this cannot parse must not
    # report "0MB anonymous, plenty of room" -- that is the permissive-on-
    # unknown shape that turns a failed read into a false all-clear.
    stat = _read_container_memory_stat()
    if stat:
        # #417. These go through the same two helpers the GUARD uses. They were
        # a second, independent copy of the reclaimable expression until
        # 2026-08-13, which meant a fix to the guard would have left this line
        # -- the one humans actually read when triaging an abort -- quietly
        # contradicting the decision it was being read to explain.
        reclaimable_bytes = _reclaimable_file_bytes(stat)
        payload["memory_anon_mb"] = _bytes_to_mb(stat.get("anon")) if "anon" in stat else None
        payload["memory_inactive_file_mb"] = _bytes_to_mb(stat.get("inactive_file")) if "inactive_file" in stat else None
        payload["memory_reclaimable_mb"] = _bytes_to_mb(reclaimable_bytes)
        if isinstance(memory_current_bytes, int):
            unreclaimable_bytes = _unreclaimable_bytes(stat, memory_current_bytes)
            if unreclaimable_bytes is None:
                unreclaimable_bytes = max(0, memory_current_bytes - reclaimable_bytes)
            payload["memory_unreclaimable_mb"] = _bytes_to_mb(unreclaimable_bytes)
            if isinstance(memory_max_bytes, int) and memory_max_bytes > 0:
                payload["memory_unreclaimable_pct_of_max"] = round(100.0 * unreclaimable_bytes / memory_max_bytes, 1)
    payload.update(extra)
    return payload


# `#435`. THE WATCHDOG, AND WHY A TIMER RATHER THAN MORE STAGE MARKERS.
#
# Six OOM kills were sampled on 2026-08-14/15 for the last instrumented line
# before death:
#
#     00:41:16  cards_context_end               mlb     anon 4047.6MB  100.0%
#     00:04:47  cards_context_page_cache_hit            anon  537.5MB   22.7%  <-
#     23:51:04  board_contract_games_normalized nfl     anon 3443.5MB   99.1%
#     23:34:15  (ALL_PROCESS_MEMORY)                    pid39 3755.5MB  99.6%
#     23:11:56  board_contract_games_normalized soccer  anon 4062.4MB  100.0%
#     22:48:35  (ALL_PROCESS_MEMORY)                    pid39 1389.7MB  71.9%  <-
#
# Every existing sample is taken at a stage BOUNDARY, so the two marked kills --
# 22.7% and 71.9% seconds before death -- are invisible: multi-GB allocations
# INSIDE one stage, which are precisely the ones that would name the allocator.
# Adding more boundary markers cannot fix that; only sampling on a clock can.
#
# The lines at >=99% name the VICTIM, not the allocator. That is the whole point
# of `last_stage` + `seconds_since_stage` below: they turn "4GB at 00:40:59" into
# "the excursion began N seconds into stage X", which is the sentence nobody has
# been able to write about this bug.
#
# COST, because `learnings.md` says worker periodic work is never free (`#241`
# put the worker in a restart loop): one cgroup file read per tick, and the
# EMIT is gated -- silent below the floor unless the number is moving. At rest
# this is a sleeping thread and two file reads every few seconds. It is a daemon
# thread so it can never hold the process open, and every path is wrapped: an
# instrument must not be the reason a worker dies.
_WATCHDOG_STATE: dict[str, Any] = {"thread": None, "last_stage": None, "last_stage_at": None}


def _note_stage_seen(stage: Any) -> None:
    """Record the most recent stage label, for the watchdog to attribute to."""
    try:
        _WATCHDOG_STATE["last_stage"] = stage
        _WATCHDOG_STATE["last_stage_at"] = time.monotonic()
    except Exception:  # pragma: no cover - defensive, must never raise
        pass


def _env_float(name: str, default: float) -> float:
    try:
        raw = os.environ.get(name, "").strip()
        return float(raw) if raw else default
    except Exception:
        return default


def memory_watchdog_enabled() -> bool:
    """Default ON, with a kill-switch.

    Deliberately not opt-in. An opt-in diagnostic needs an env change to take
    effect, and on Render that means a single-key write AND a deploy (a restart
    does not re-inject env vars) -- i.e. the instrument arrives one incident
    later than the incident. Default-on ships with the code; `=0` disables it
    without one.
    """
    raw = os.environ.get("SYNDICATE_MEMORY_WATCHDOG", "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _watchdog_should_emit(payload: dict[str, Any], last_emitted_mb: float | None) -> bool:
    """Emit above the floor, or when the number has MOVED by the delta.

    Two triggers because the two failure shapes differ: a slow ratchet is caught
    by the floor, and the 22.7%-to-dead-in-2.6s shape is caught by the delta
    before it ever reaches the floor.
    """
    floor_pct = _env_float("SYNDICATE_MEMORY_WATCHDOG_FLOOR_PCT", 60.0)
    delta_mb = _env_float("SYNDICATE_MEMORY_WATCHDOG_DELTA_MB", 200.0)
    metric = payload.get("memory_unreclaimable_mb")
    if metric is None:
        metric = payload.get("memory_anon_mb")
    pct = payload.get("memory_pct_of_max")
    if metric is None:
        # TWO DIFFERENT UNKNOWNS, and conflating them floods the log.
        #
        # Split unreadable but `memory.current` fine -> a real anomaly on a real
        # cgroup, and the sample matters most exactly then: emit.
        #
        # NOTHING readable -> not a cgroup at all (any dev machine). Emitting
        # every tick forever is noise, not evidence, and it would bury the
        # signal this instrument exists to surface. Say so ONCE and go quiet.
        if pct is None:
            if _WATCHDOG_STATE.get("unmeasurable_reported"):
                return False
            _WATCHDOG_STATE["unmeasurable_reported"] = True
            return True
        return True
    if isinstance(pct, (int, float)) and pct >= floor_pct:
        return True
    if last_emitted_mb is None:
        return False
    return abs(float(metric) - last_emitted_mb) >= delta_mb


def watchdog_excursion_climb_mb_per_s(previous_mb: float | None, current_mb: float | None,
                                      elapsed_s: float | None) -> float | None:
    """Climb rate between two watchdog samples, or None if it cannot be computed."""
    if previous_mb is None or current_mb is None:
        return None
    if not isinstance(elapsed_s, (int, float)) or elapsed_s <= 0:
        return None
    return (float(current_mb) - float(previous_mb)) / float(elapsed_s)


def watchdog_should_dump_allocations(*, climb_mb_per_s: float | None, anon_mb: float | None,
                                     already_dumped: bool) -> bool:
    """Fire the tracemalloc dump ONCE, while the excursion is actually happening.

    `#435`. The dump already exists and has never once fired during an excursion:
    it is on a 600s timer, and the excursion measured 2026-08-15 01:38 lasted 35
    seconds end to end. A timer cannot catch that; a climb detector can.

    ONCE PER BOOT, deliberately. tracemalloc keeps a traceback per live
    allocation and this process is at its ceiling -- a dump per sample would
    become the thing that kills it, and the first dump is the one taken while
    anon is climbing, which is the one worth having.
    """
    if already_dumped:
        return False
    if climb_mb_per_s is None or anon_mb is None:
        return False
    floor_mb = _env_float("SYNDICATE_MEMORY_WATCHDOG_DUMP_FLOOR_MB", 2000.0)
    rate_mb_s = _env_float("SYNDICATE_MEMORY_WATCHDOG_DUMP_RATE_MB_S", 25.0)
    # BOTH conditions. Rate alone fires on ordinary warm-up; floor alone fires on
    # a process sitting high but stable, which is the state this worker is in for
    # most of its life and is NOT the moment worth a traceback dump.
    return float(anon_mb) >= floor_mb and float(climb_mb_per_s) >= rate_mb_s


def _watchdog_maybe_dump_allocations(payload: dict[str, Any], climb_mb_per_s: float | None) -> None:
    """Emit the allocation-site census if we are inside an excursion."""
    try:
        anon_mb = payload.get("memory_unreclaimable_mb")
        if anon_mb is None:
            anon_mb = payload.get("memory_anon_mb")
        if not watchdog_should_dump_allocations(
            climb_mb_per_s=climb_mb_per_s,
            anon_mb=anon_mb,
            already_dumped=bool(_WATCHDOG_STATE.get("allocations_dumped")),
        ):
            return
        _WATCHDOG_STATE["allocations_dumped"] = True
        # THE DUMP MUST NOT RUN ON THE SAMPLER THREAD. Measured the hard way
        # 2026-08-15 02:11-02:16: with tracing at nframe=3 the worker emitted
        # its MEMORY_WATCHDOG_STARTED line and then **not one sample** before
        # dying 5.5 minutes later, where the previous build emitted 567. The
        # kill cadence went from ~16-22 min to 3-10 min across the same change.
        # `tracemalloc.take_snapshot()` walks every live traced allocation in C
        # holding the GIL; on this heap that is millions of objects, so the
        # sampler was starved by the one call it makes -- and because the print
        # happens AFTER the snapshot returns, it looked like the trigger had
        # simply never fired. An instrument that blocks its own measurement is
        # worse than no instrument, because its silence reads as "nothing
        # happened".
        #
        # Off-thread and daemon: if it never finishes, it dies with the process
        # and the sampler keeps sampling either way.
        try:
            import threading

            threading.Thread(
                target=_watchdog_dump_allocations_now,
                args=(dict(payload), climb_mb_per_s),
                name="memory-watchdog-dump",
                daemon=True,
            ).start()
            return
        except Exception:
            pass  # fall through and do it inline rather than lose the dump
        _watchdog_dump_allocations_now(payload, climb_mb_per_s)
    except Exception as exc:  # pragma: no cover - defensive, must never raise
        print(
            f"[memory_observability] WATCHDOG_ALLOCATION_DUMP_FAILED {type(exc).__name__}: {exc}",
            flush=True,
        )


def stop_allocation_tracing(reason: str) -> bool:
    """Stop tracing and free the per-allocation tracebacks. Never raises.

    Tracing is a WINDOW, not a setting. Every allocation carries tracebacks while
    it is on, so leaving it armed after the one dump has been taken is pure cost
    on a process that is already OOM-killing.
    """
    try:
        import tracemalloc

        was_tracing = tracemalloc.is_tracing()
        if was_tracing:
            tracemalloc.stop()
        _TRACEMALLOC_STATE["started"] = False
        _TRACEMALLOC_STATE["reason"] = f"stopped:{reason}"
        print(
            "[memory_observability] TRACEMALLOC_STOPPED "
            + json.dumps({"reason": reason, "was_tracing": bool(was_tracing)}, sort_keys=True),
            flush=True,
        )
        return bool(was_tracing)
    except Exception as exc:  # pragma: no cover - defensive, must never raise
        print(
            f"[memory_observability] TRACEMALLOC_STOP_FAILED {type(exc).__name__}: {exc}",
            flush=True,
        )
        return False


def _watchdog_dump_allocations_now(payload: dict[str, Any], climb_mb_per_s: float | None) -> None:
    """The dump itself. Always called with the decision already made."""
    try:
        anon_mb = payload.get("memory_unreclaimable_mb")
        if anon_mb is None:
            anon_mb = payload.get("memory_anon_mb")
        if not allocation_tracing_enabled():
            # Say so ONCE, with the numbers that would have been captured. An
            # instrument that is off must announce it at the moment it would
            # have fired -- otherwise its silence reads as "nothing to report".
            print(
                f"[memory_observability] WATCHDOG_EXCURSION_NO_TRACING "
                f"anon_mb={anon_mb} climb_mb_per_s={round(climb_mb_per_s, 1)} "
                f"last_stage={payload.get('last_stage')} "
                f"(set SYNDICATE_TRACEMALLOC_DIAG=1 to capture sites)",
                flush=True,
            )
            return
        snapshot = allocation_snapshot()
        print(
            f"WATCHDOG_EXCURSION_ALLOCATIONS "
            f"{json.dumps({'climb_mb_per_s': round(climb_mb_per_s, 1), 'anon_mb': anon_mb, 'last_stage': payload.get('last_stage'), 'snapshot': snapshot}, default=str, sort_keys=True)}",
            file=sys.stderr,
            flush=True,
        )
        # THE WINDOW CLOSES ITSELF. We take exactly one dump per boot, so once it
        # is printed every further traced allocation is pure cost on a process
        # that OOMs -- and on 2026-08-15 02:11-02:16 that cost was measurable:
        # kill cadence 3-10 min against 16-22, and the sampler starved outright.
        #
        # Ending it here rather than by hand is the point. The previous window
        # stayed open until a human noticed, deployed twice and wrote an env
        # var; this one ends microseconds after the data exists, whether or not
        # anyone is watching. `#241` is the standing reminder that periodic work
        # on this worker is never free.
        stop_allocation_tracing("dump_complete")
    except Exception as exc:  # pragma: no cover - defensive, must never raise
        print(
            f"[memory_observability] WATCHDOG_ALLOCATION_DUMP_FAILED {type(exc).__name__}: {exc}",
            flush=True,
        )


_UNTRACKED_CENSUS_MAX_PER_PROCESS = 3
_UNTRACKED_CENSUS_STATE: dict[str, int] = {"count": 0}


def log_untracked_bytes_census(reason: str) -> dict[str, Any] | None:
    """Size the `str`/`bytes` the heap census CANNOT see, attributed to holders.

    `#435`. `log_heap_census` measured 415,596 GC-tracked objects totalling
    ~135MB shallow while `anon` was 1709MB. That is not a near miss, it is three
    orders of magnitude, and the reason is structural: `gc.get_objects()` returns
    only CYCLIC-GC-TRACKED objects, and `str`/`bytes`/`int`/`float` hold no
    references so they are never tracked. In a JSON pipeline those ARE the bytes.

    So this walks the tracked objects and sizes their `str`/`bytes` REFERENTS --
    the strings hanging off dicts and lists -- which is where parsed JSON lives.

    DEDUPLICATED BY id(). Interned and shared strings are referenced from many
    places; counting each reference would inflate the total to something
    comfortably larger than the container, which would look like an answer and
    be arithmetic.

    Attribution is by HOLDER TYPE, not by string content, because the actionable
    question is which structure is holding them. The biggest individual strings
    are named separately -- one 400MB blob and four million 100-byte quote keys
    are different bugs with different fixes.
    """
    if _UNTRACKED_CENSUS_STATE["count"] >= _UNTRACKED_CENSUS_MAX_PER_PROCESS:
        return None
    try:
        import gc

        _UNTRACKED_CENSUS_STATE["count"] += 1
        gc.collect()
        seen: set[int] = set()
        by_holder: dict[str, list[int]] = {}
        biggest: list[tuple[int, str, str]] = []
        total_bytes = 0
        scanned = 0

        for obj in gc.get_objects():
            try:
                holder = type(obj).__name__
                for ref in gc.get_referents(obj):
                    if not isinstance(ref, (str, bytes, bytearray)):
                        continue
                    ident = id(ref)
                    if ident in seen:
                        continue
                    seen.add(ident)
                    size = sys.getsizeof(ref)
                    total_bytes += size
                    scanned += 1
                    bucket = by_holder.setdefault(holder, [0, 0])
                    bucket[0] += size
                    bucket[1] += 1
                    # 1MB, not 50MB: at this scale the interesting object is a
                    # cached payload, not a monolith. Ten of these is a lead.
                    if size > 1 * _BYTES_PER_MB:
                        biggest.append((size, holder, repr(ref)[:160]))
            except Exception:
                continue

        anon_mb = None
        stat = _read_container_memory_stat()
        if stat and "anon" in stat:
            anon_mb = _bytes_to_mb(stat.get("anon"))
        total_mb = round(total_bytes / _BYTES_PER_MB, 1)
        payload = {
            "reason": str(reason or "")[:80],
            "census_index": _UNTRACKED_CENSUS_STATE["count"],
            "anon_mb": anon_mb,
            "str_bytes_total_mb": total_mb,
            # THE HEADLINE NUMBER. If this is small, the memory is not in Python
            # objects at all and the next look is C-level (numpy/pandas buffers,
            # allocator retention) rather than anywhere in this file.
            "explained_pct_of_anon": (
                round(100.0 * total_mb / anon_mb, 1) if anon_mb else None
            ),
            "distinct_str_bytes": scanned,
            "top_holders_mb": sorted(
                ((name, round(v[0] / _BYTES_PER_MB, 1), v[1]) for name, v in by_holder.items()),
                key=lambda row: row[1],
                reverse=True,
            )[:15],
            "biggest_individual": [
                (round(size / _BYTES_PER_MB, 1), holder, text)
                for size, holder, text in sorted(biggest, reverse=True)[:10]
            ],
        }
        print(f"UNTRACKED_BYTES_CENSUS {json.dumps(payload, default=str)}", flush=True)
        return payload
    except Exception as exc:
        print(f"UNTRACKED_BYTES_CENSUS_FAILED {type(exc).__name__}: {exc}", flush=True)
        return None


def watchdog_should_heap_census(*, anon_mb: float | None, already_censused: bool) -> bool:
    """Fire ONE heap census once the process is holding the memory in question.

    `#435`. `log_heap_census` is the RIGHT instrument for "what is in the anon"
    and it has never fired in production: its only call site is inside
    `_build_candidate_pool` behind `min_container_mb=1200`, and five hours of
    logs contain zero `HEAP_CENSUS` lines. Waiting on a call site is what kept it
    silent, so this triggers on the CONDITION instead -- the same change that
    made the watchdog itself work.

    Unlike tracemalloc (ruled out 2026-08-15: it silenced this sampler at both
    nframe=3 and nframe=2) a census is a ONE-SHOT walk, not per-allocation
    bookkeeping. It holds the GIL once for the walk rather than taxing every
    allocation, and `_HEAP_CENSUS_MAX_PER_PROCESS` already caps it.
    """
    if already_censused or anon_mb is None:
        return False
    return float(anon_mb) >= _env_float("SYNDICATE_MEMORY_WATCHDOG_CENSUS_MB", 1500.0)


def watchdog_should_peak_smaps(*, anon_mb: float | None, fired_count: int) -> bool:
    """Fire an SMAPS read INSIDE the excursion, not at the baseline.

    Pure predicate, separated from the hook so it can be falsified offline --
    the thing this file's history says goes wrong is instruments that look
    installed and never fire.

    Deliberately gated on the LEVEL (anon past a high-water threshold) and NOT
    on `climb_mb_per_s`. Rate is the wrong quantity to gate on: it encodes an
    assumption that the excursion is fast, and the first slow one walks straight
    past. Level answers the question actually being asked -- "are we now holding
    substantially more than baseline" -- and is true for a slow excursion too.

    Fires up to `_PEAK_SMAPS_MAX_PER_PROCESS` times rather than once, because
    the open question is which regions GROW; a single peak sample cannot answer
    that, and the baseline sample it would be compared against was taken by a
    different trigger at a different threshold.
    """
    if anon_mb is None:
        return False
    if fired_count >= _PEAK_SMAPS_MAX_PER_PROCESS:
        return False
    return float(anon_mb) >= _env_float("SYNDICATE_MEMORY_WATCHDOG_PEAK_SMAPS_MB", 2600.0)


def _watchdog_maybe_peak_smaps(payload: dict[str, Any]) -> None:
    """Off-thread SMAPS read once we are inside an excursion."""
    try:
        anon_mb = payload.get("memory_unreclaimable_mb")
        if anon_mb is None:
            anon_mb = payload.get("memory_anon_mb")
        if not watchdog_should_peak_smaps(
            anon_mb=anon_mb, fired_count=int(_PEAK_SMAPS_STATE.get("count", 0))
        ):
            return
        _PEAK_SMAPS_STATE["count"] = int(_PEAK_SMAPS_STATE.get("count", 0)) + 1
        # OFF THE SAMPLER THREAD, for the reason recorded against the allocation
        # dump: the kernel walks page tables to answer smaps, and a blocked
        # sampler is indistinguishable from a calm system. Measured 2026-08-15,
        # tracing on this thread took the worker from 567 samples to zero and
        # cut the kill cadence from ~16-22 min to 3-10 min. An instrument must
        # not be the reason a worker dies.
        import threading

        threading.Thread(
            target=log_smaps_anon_breakdown,
            args=(f"watchdog_PEAK_anon_{int(float(anon_mb))}mb",),
            name="watchdog-peak-smaps",
            daemon=True,
        ).start()
    except Exception as exc:  # pragma: no cover - defensive, must never raise
        print(f"[memory_observability] PEAK_SMAPS_HOOK_FAILED {type(exc).__name__}: {exc}", flush=True)


# Raised 3 -> 8 on 2026-08-17. The baseline censuses consume one of these via
# `_run_censuses`, and the peak trigger added below wants several more. At 3 the
# peak samples would have been silently discarded by the cap check in
# `log_smaps_anon_breakdown` -- which `return None`s with no line, so the
# instrument would have looked installed and produced nothing. That is the
# failure this file's own history is full of.
_SMAPS_MAX_PER_PROCESS = 8
_SMAPS_STATE: dict[str, int] = {"count": 0}

# PEAK SMAPS. Separate budget and separate state from the baseline censuses, so
# the two can never starve each other.
#
# WHY THIS EXISTS. Measured 2026-08-17: the existing censuses fire once, at
# `SYNDICATE_MEMORY_WATCHDOG_CENSUS_MB` (default 1500MB anon), which is the
# process's ELEVATED BASELINE -- they fired at anon 1610MB and 1700MB while the
# excursions that actually kill peak at 3700-4000MB. So every census we have
# describes what the process HOLDS, not what the excursion ALLOCATES, and the
# two had been read as if they were the same thing.
#
# What those baseline censuses did establish, and why SMAPS specifically is the
# instrument to re-fire rather than the object walks:
#     UNTRACKED_BYTES_CENSUS  explained_pct_of_anon = 13.7%
#     SMAPS_ANON              anon_mmap 1848.2MB, >64MB regions = 1293.0MB,
#                             largest single region 515.0MB
# ~87% of anon is invisible to the Python object census and sits in anonymous
# mmap regions far larger than pymalloc's 1MB arenas. The object walks have
# already answered their question ("no, it is not Python containers"); repeating
# them at the peak would cost a multi-second GIL hold to re-learn it. SMAPS is a
# single procfs read with no object walk, and it measures exactly the quantity
# that turned out to dominate.
#
# THRESHOLD. Default 2600MB sits clearly above the ~1700MB baseline and inside
# the climb, leaving ~1.5GB before the 4096MB ceiling -- at the measured
# 100-260 MB/s that is roughly 6-15 seconds for the read to complete before the
# kill. Env-tunable because that margin is an estimate, not a measurement.
_PEAK_SMAPS_MAX_PER_PROCESS = 3
_PEAK_SMAPS_STATE: dict[str, int] = {"count": 0}

# STACK DUMP AT THE EXCURSION. The instrument of last resort, and the only one
# left that does not depend on the allocating code volunteering a log line.
#
# WHY IT IS NEEDED, measured 2026-08-16/17 across seven excursions: nothing in
# the logs distinguishes an excursion from a quiet window.
#   - Zero stage markers across a 16s excursion (4 consecutive UNCAPPED windows).
#   - Artifact-pull activity at the SAME rate in excursion and control arms
#     (pulled_hot 1/7 vs 1/6).
#   - Thread activity classified by owner: excursion 00:31 (artifact=12,
#     live-lens=7) is IDENTICAL to control 00:36 (artifact=12, live-lens=7).
#   - Two excursions were essentially SILENT: 23:42 produced 8 rows and 00:08
#     produced 6, all of them this watchdog's own samples, while anon climbed at
#     25-160 MB/s.
# The allocating code emits nothing. Log correlation cannot name it, and three
# independent attempts to do so were each refuted by their own control.
#
# WHY faulthandler AND NOT tracemalloc. `state.md:556` rules tracemalloc out at
# any frame count -- it starved this sampler and drove the kill cadence from
# ~16-22 min to 3-10 min. `faulthandler.dump_traceback` is a different animal: it
# walks existing frame objects and writes them to a file descriptor. No
# per-allocation bookkeeping, no object graph, no snapshot. The pattern is
# already proven in this repo at `scripts/refresh_odds_sources.py:447`.
#
# `all_threads=True` IS THE POINT, not a detail. `_WATCHDOG_STATE` is
# process-global with no thread-locals, so `last_stage` names the last thread to
# SPEAK, not the one allocating -- an entire evening's attribution was built on
# that and had to be retracted. A dump names every thread's stack at once, so
# thread attribution stops being an inference.
#
# ON THE SAMPLER THREAD, DELIBERATELY, against the usual rule. The rule
# (`:877`, `:1491`) exists for work that holds the GIL for SECONDS -- census
# walks over millions of objects. A frame-object walk is milliseconds. And
# deferring it to a new thread would let the stacks MOVE before capture, which
# defeats the instrument: the whole value is the stack AT the moment anon is
# climbing.
#
# WHAT IT CANNOT DO, stated so the next reader does not over-read it: a stack
# shows where threads ARE, not what they ALLOCATED. If the cost is spread across
# many short calls, three samples may show three unrelated stacks. That is why
# it fires more than once -- a stable stack across samples is the signal; a
# scattered one is its own (negative) answer.
_STACK_DUMP_MAX_PER_PROCESS = 3
_STACK_DUMP_STATE: dict[str, int] = {"count": 0}


def watchdog_should_stack_dump(*, anon_mb: float | None, fired_count: int) -> bool:
    """Fire a stack dump INSIDE an excursion. Pure predicate, falsifiable offline.

    Gated on LEVEL, not `climb_mb_per_s`, for the same reason as the peak SMAPS
    trigger: rate encodes an assumption that excursions are fast, and the first
    slow one walks straight past it. The 2600MB level is the one already proven
    to catch this -- peak SMAPS fired on it twice, on two separate excursions.
    """
    if anon_mb is None:
        return False
    if fired_count >= _STACK_DUMP_MAX_PER_PROCESS:
        return False
    return float(anon_mb) >= _env_float("SYNDICATE_MEMORY_WATCHDOG_STACK_DUMP_MB", 2600.0)


def _watchdog_maybe_stack_dump(payload: dict[str, Any]) -> None:
    """Dump every thread's stack once we are inside an excursion."""
    try:
        anon_mb = payload.get("memory_unreclaimable_mb")
        if anon_mb is None:
            anon_mb = payload.get("memory_anon_mb")
        if not watchdog_should_stack_dump(
            anon_mb=anon_mb, fired_count=int(_STACK_DUMP_STATE.get("count", 0))
        ):
            return
        n = int(_STACK_DUMP_STATE.get("count", 0)) + 1
        _STACK_DUMP_STATE["count"] = n
        # A header line so the dump can be located and correlated. faulthandler
        # writes raw frames with no context of its own -- without this the dump
        # is an orphan block of tracebacks in the middle of the log.
        print(
            f"WATCHDOG_STACK_DUMP_BEGIN n={n} anon_mb={anon_mb} "
            f"last_stage={payload.get('last_stage')} climb_mb_per_s={payload.get('climb_mb_per_s')}",
            file=sys.stderr,
            flush=True,
        )
        # TWO WRITERS, AND THE FALLBACK IS NOT DECORATION.
        #
        # `faulthandler.dump_traceback` writes to a real file DESCRIPTOR, so it
        # raises `io.UnsupportedOperation: fileno` against any wrapped stderr.
        # Caught by this instrument's own tests, where it printed a BEGIN header
        # and then NOTHING -- an instrument that looks installed and emits no
        # evidence, which is the failure mode this module's history is made of
        # and which I have now hit three times in one session.
        #
        # Production stderr normally has a real fd, so faulthandler is preferred:
        # it is the cheaper writer and it can dump even a thread blocked in C.
        # But "normally" is not a guarantee -- anything that wraps stderr (a
        # logging shim, a capture harness, a future supervisor) silently removes
        # the only instrument that can see this bug. `sys._current_frames()` is
        # pure Python, needs no fd, and covers every thread; it cannot see into
        # C frames, which is the trade for always working.
        wrote = False
        try:
            import faulthandler

            faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
            wrote = True
        except Exception as exc:
            print(
                f"WATCHDOG_STACK_DUMP_FAULTHANDLER_UNAVAILABLE {type(exc).__name__}: {exc} "
                "-- falling back to sys._current_frames()",
                file=sys.stderr,
                flush=True,
            )
        if not wrote:
            import threading as _threading
            import traceback as _traceback

            names = {t.ident: t.name for t in _threading.enumerate()}
            for thread_id, frame in sys._current_frames().items():
                print(
                    f"\nThread 0x{thread_id:x} ({names.get(thread_id, 'unknown')}):",
                    file=sys.stderr,
                )
                for line in _traceback.format_stack(frame):
                    print(line.rstrip(), file=sys.stderr)
            wrote = True
        print(f"WATCHDOG_STACK_DUMP_END n={n} wrote={wrote}", file=sys.stderr, flush=True)
        if n == _STACK_DUMP_MAX_PER_PROCESS:
            print(
                f"WATCHDOG_STACK_DUMP_EXHAUSTED max={_STACK_DUMP_MAX_PER_PROCESS} "
                "-- further excursions on this boot dump nothing",
                file=sys.stderr,
                flush=True,
            )
    except Exception as exc:  # pragma: no cover - an instrument must never kill the worker
        try:
            print(f"[memory_observability] STACK_DUMP_FAILED {type(exc).__name__}: {exc}", flush=True)
        except Exception:
            pass

# Anonymous mmap regions, bucketed by SIZE. pymalloc takes 1MB arenas by mmap and
# glibc routes anything over MMAP_THRESHOLD (128KB default) the same way, so the
# size distribution is what separates them -- there is no name to key on.
#
# Deliberately NOT "regions of exactly 1MB are pymalloc arenas": the kernel
# COALESCES adjacent anonymous mappings with identical flags into one VMA, so 934
# arenas can appear as far fewer, much larger regions. Buckets describe what is
# there; they do not assert who allocated it.
_SMAPS_BUCKETS_BYTES = (
    (64 * 1024, "<64KB"),
    (1024 * 1024, "64KB-1MB"),
    (8 * 1024 * 1024, "1-8MB"),
    (64 * 1024 * 1024, "8-64MB"),
    (float("inf"), ">64MB"),
)


def parse_smaps(text: str) -> dict[str, Any]:
    """Group `/proc/self/smaps` anonymous bytes by mapping kind.

    `#435` step: 673MB of a 1,607MB rest-state floor is anon that pymalloc never
    allocated (arenas 934MB against anon 1,607MB). `malloc_info` cannot see it --
    it reported `arena_coverage_pct` 13.9% and labelled itself
    `arena_not_representative`, because it reports arena bookkeeping and not
    mmap'd chunks. The Python censuses cannot see non-Python allocations at all.

    This asks the kernel instead, using the same accounting that decides the OOM
    kill. `Anonymous:` per mapping is the field that matters; `Rss` includes
    file-backed pages that the cgroup counts under `file`, not `anon`, and
    conflating them is how a page-cache plateau once got called a leak.

    Split out from the reader so it can be tested on a fixture rather than only
    against a live process -- every other instrument in this investigation was
    calibrated before it was trusted, and the two that were not produced wrong
    answers.
    """
    totals: dict[str, int] = {}
    buckets: dict[str, int] = {}
    regions: list[tuple[int, str]] = []
    current_path = ""
    current_size = 0
    current_anon = 0
    seen_header = False

    def _flush() -> None:
        nonlocal current_anon, current_size, current_path
        if not seen_header or current_anon <= 0:
            return
        path = current_path
        if path in {"[heap]", "[stack]"}:
            kind = path.strip("[]")
        elif path.startswith("["):
            kind = "special"
        elif path:
            kind = "file_backed"
        else:
            kind = "anon_mmap"
            for limit, label in _SMAPS_BUCKETS_BYTES:
                if current_size < limit:
                    buckets[label] = buckets.get(label, 0) + current_anon
                    break
        totals[kind] = totals.get(kind, 0) + current_anon
        regions.append((current_anon, path or f"anon:{round(current_size / _BYTES_PER_MB, 1)}MB"))

    for line in text.splitlines():
        if _SMAPS_HEADER_RE.match(line):
            _flush()
            seen_header = True
            parts = line.split(None, 5)
            current_path = parts[5].strip() if len(parts) > 5 else ""
            span = parts[0].split("-")
            try:
                current_size = int(span[1], 16) - int(span[0], 16)
            except Exception:
                current_size = 0
            current_anon = 0
        elif line.startswith("Anonymous:"):
            try:
                current_anon = int(line.split()[1]) * _BYTES_PER_KB
            except Exception:
                current_anon = 0
    _flush()

    return {
        "by_kind_mb": {k: round(v / _BYTES_PER_MB, 1) for k, v in sorted(totals.items(), key=lambda kv: -kv[1])},
        "anon_mmap_by_size_mb": {k: round(v / _BYTES_PER_MB, 1) for k, v in sorted(buckets.items(), key=lambda kv: -kv[1])},
        "total_anon_mb": round(sum(totals.values()) / _BYTES_PER_MB, 1),
        "region_count": len(regions),
        "largest_regions_mb": [
            (round(anon / _BYTES_PER_MB, 1), path[:70]) for anon, path in sorted(regions, reverse=True)[:8]
        ],
    }


_SMAPS_UNAVAILABLE: dict[str, bool] = {"logged": False}


def log_smaps_anon_breakdown(reason: str, *, budget: tuple[dict, int] | None = None,
                             quiet: bool = False) -> dict[str, Any] | None:
    """Read `/proc/self/smaps` and report where the anon actually lives.

    Cost: the kernel walks page tables to answer this, so it is not free -- but
    it is a single read with no per-allocation bookkeeping, which is the property
    `tracemalloc` lacked when it silenced the sampler at both nframe=3 and 2.
    Capped per process like the other censuses, and run off the sampler thread.
    """
    # `#632`: a caller may bring its own budget. The alarm census's 8 are for
    # a memory emergency and must not be spent by routine trend sampling.
    budget_state, budget_max = (budget if budget is not None
                                else (_SMAPS_STATE, _SMAPS_MAX_PER_PROCESS))
    if budget_state["count"] >= budget_max:
        # SAY SO. This used to `return None` in silence, which makes a capped-out
        # instrument indistinguishable from one that ran and found nothing --
        # the exact shape of "never record a detector's zero as a pass when the
        # data gave it no chance to fire". A missing SMAPS_ANON must be
        # attributable to the cap, not left for a reader to infer.
        if not quiet:
            print(
                f"SMAPS_SKIPPED_CAPPED reason={str(reason or '')[:60]} "
                f"count={budget_state['count']} max={budget_max}",
                flush=True,
            )
        return None
    try:
        path = _PROCFS_ROOT / "self" / "smaps"
        if not path.exists():
            # LATCHED, and silent for a `quiet` caller. This print sits BEFORE the
            # budget increment, so on a host without procfs nothing ever caps it
            # -- a trend sampling every 200 requests would say this forever. The
            # emission-count test caught it as 4 lines where 2 were expected,
            # which is the same duplication the arena trend was caught by twice.
            if not quiet and not _SMAPS_UNAVAILABLE["logged"]:
                _SMAPS_UNAVAILABLE["logged"] = True
                print("[memory_observability] SMAPS_UNAVAILABLE (not a Linux procfs)", flush=True)
            return None
        budget_state["count"] += 1
        payload = parse_smaps(path.read_text(encoding="utf-8", errors="ignore"))
        payload["reason"] = str(reason or "")[:80]
        payload["smaps_index"] = budget_state["count"]

        # RECONCILIATION, and it is the point rather than a nicety. smaps and the
        # cgroup are INDEPENDENT kernel accountings of the same bytes. If they
        # disagree materially the parse is wrong, and a breakdown that does not
        # add up must not be read as attribution -- this investigation has twice
        # acted on a number that was internally consistent and wrong.
        stat = _read_container_memory_stat()
        cgroup_anon_mb = _bytes_to_mb(stat.get("anon")) if stat and "anon" in stat else None
        payload["cgroup_anon_mb"] = cgroup_anon_mb
        if cgroup_anon_mb:
            delta = payload["total_anon_mb"] - cgroup_anon_mb
            payload["reconciles_within_pct"] = round(100.0 * abs(delta) / cgroup_anon_mb, 1)
            payload["reconciles"] = abs(delta) <= max(64.0, 0.10 * cgroup_anon_mb)
        # `quiet` for TREND sampling: the reading rides inside the attribution
        # emission as `smaps_trend`, and a second full line per emission is the
        # duplication `test_it_emits_only_every_nth_request` counts.
        if not quiet:
            print(f"SMAPS_ANON {json.dumps(payload, default=str, sort_keys=True)}", flush=True)
        return payload
    except Exception as exc:
        print(f"SMAPS_ANON_FAILED {type(exc).__name__}: {exc}", flush=True)
        return None


_PYMALLOC_STATS_MAX_PER_PROCESS = 3
_PYMALLOC_STATS_STATE: dict[str, int] = {"count": 0}


def log_pymalloc_arena_stats(reason: str, *, budget: tuple[dict, int] | None = None,
                             raw: bool = True, quiet: bool = False) -> dict[str, Any] | None:
    """PYMALLOC's arena accounting -- the last place the missing anon can be.

    `#435`, and this is the measurement the other three point at. Established:

      anon                              1858.3 MB
      GC-tracked containers              ~135 MB  (415,596 objects)
      str/bytes hanging off them         ~136 MB  (1,704,754 strings, avg 84B)
      glibc `malloc_info` system_current  237.5 MB, coverage 13.9%, and the
                                          binding itself reads
                                          "arena_not_representative"

    So ~85% of anon is neither reachable Python data nor glibc arena memory.
    pymalloc is what is left: it serves every allocation under 512 bytes -- which
    is ALL 2.1M of the small objects above -- from 1MB arenas it takes by mmap,
    invisible to `malloc_info`. An arena is only returned to the OS when it is
    COMPLETELY empty, so a burst of millions of short-lived JSON strings that
    leaves one survivor per arena pins the lot.

    `sys._debugmallocstats()` prints the arena counts to stderr. It is the only
    supported way to see this; there is no structured API. Parsed loosely here
    and the raw table left in the log, because the derived number
    (`arenas * 1MB` against live bytes) is the whole answer and a parse that
    silently misses a line must not turn into a confident zero.
    """
    # `#632`: a caller may supply its OWN budget. The watchdog's 3 exist for an
    # ALARM census and must never be spent by routine trend sampling -- if the
    # trend ate them, the one census that fires when anon is already critical
    # would find its budget gone. Separate counters, never shared.
    budget_state, budget_max = (budget if budget is not None
                                else (_PYMALLOC_STATS_STATE, _PYMALLOC_STATS_MAX_PER_PROCESS))
    if budget_state["count"] >= budget_max:
        return None
    try:
        import os
        import re
        import tempfile

        budget_state["count"] += 1
        # FD-LEVEL CAPTURE, and the first version of this got it wrong.
        # `_debugmallocstats` writes from C to fd 2, so `redirect_stderr` (which
        # only rebinds `sys.stderr`) captured NOTHING -- measured
        # `captured_chars: 0` locally before this shipped. Only dup2 sees it.
        #
        # This briefly points the process's fd 2 at a temp file, so a concurrent
        # thread logging in that window lands there instead of the collector.
        # The window is milliseconds and the alternative is no measurement at
        # all; worth knowing if a sample looks missing around a PYMALLOC_STATS.
        text = ""
        sys.stderr.flush()
        saved_fd = os.dup(2)
        try:
            with tempfile.TemporaryFile(mode="w+b") as tmp:
                os.dup2(tmp.fileno(), 2)
                try:
                    sys._debugmallocstats()
                finally:
                    sys.stderr.flush()
                    os.dup2(saved_fd, 2)
                tmp.seek(0)
                text = tmp.read().decode("utf-8", errors="replace")
        finally:
            os.close(saved_fd)

        def _num(value: str) -> int | None:
            try:
                return int(value.replace(",", "").strip())
            except Exception:
                return None

        arenas = None
        arena_bytes = None
        bytes_in_use = None
        unused_pool_bytes = None
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("# arenas allocated current"):
                arenas = _num(stripped.split("=")[-1])
            elif "bytes/arena" in stripped and "=" in stripped:
                # `2 arenas * 1048576 bytes/arena  =  2,097,152` -- the total
                # comes straight off the line, so the arena SIZE never has to be
                # assumed (it changed between CPython versions).
                arena_bytes = _num(stripped.split("=")[-1])
            elif stripped.startswith("# bytes in allocated blocks"):
                bytes_in_use = _num(stripped.split("=")[-1])
            elif re.match(r"^\d+ unused pools \*", stripped) and "=" in stripped:
                unused_pool_bytes = _num(stripped.split("=")[-1])
        arena_mb = _bytes_to_mb(arena_bytes) if isinstance(arena_bytes, int) else None
        live_mb = _bytes_to_mb(bytes_in_use) if isinstance(bytes_in_use, int) else None
        payload = {
            "reason": str(reason or "")[:80],
            "stats_index": budget_state["count"],
            "arenas_currently_allocated": arenas,
            "arena_mb": arena_mb,
            "bytes_in_allocated_blocks_mb": live_mb,
            "unused_pools_mb": (
                _bytes_to_mb(unused_pool_bytes) if isinstance(unused_pool_bytes, int) else None
            ),
            # THE NUMBER. Arenas held minus bytes live = memory pymalloc is
            # sitting on that no Python object is using.
            "retained_by_pymalloc_mb": (
                round(arena_mb - live_mb, 1)
                if isinstance(arena_mb, float) and isinstance(live_mb, float)
                else None
            ),
            "captured_chars": len(text),
        }
        # `quiet` for TREND sampling: the reading is published inside the
        # attribution emission as `arena_trend`, so a second line here is pure
        # duplication -- and one extra line per emission is exactly what
        # `test_it_emits_only_every_nth_request` counts, and rightly so.
        if not quiet:
            print(f"PYMALLOC_STATS {json.dumps(payload, default=str)}", flush=True)
        # `raw=False` for TREND sampling: this block is ~4,000 characters. The
        # alarm census emits it 3 times per process, where that is worth it; a
        # trend samples 60 times, and 60 of these would flood the very log the
        # instrument is read in. `test_it_emits_only_every_nth_request` exists
        # to prevent exactly that, and it is what caught this.
        if text and raw and not quiet:
            # The raw table, once. A loose parse that misses a renamed line must
            # not be the only record -- the counts above are derived, this is not.
            print("PYMALLOC_STATS_RAW\n" + text[:4000], flush=True)
        return payload
    except Exception as exc:
        print(f"PYMALLOC_STATS_FAILED {type(exc).__name__}: {exc}", flush=True)
        return None


_ARENA_TREND_STATE: dict[str, Any] = {"count": 0, "last": None}
_ARENA_TREND_MAX_DEFAULT = 60


def _arena_trend_budget() -> int:
    raw_value = str(os.environ.get("SYNDICATE_ARENA_TREND_SAMPLES") or "").strip()
    if not raw_value:
        return _ARENA_TREND_MAX_DEFAULT
    try:
        return int(raw_value)
    except ValueError:
        return _ARENA_TREND_MAX_DEFAULT


def sample_arena_trend(reason: str) -> dict[str, Any] | None:
    """One arena reading for a TIME SERIES, not for an alarm.

    `#632`. Four per-request explanations for the anon climb have now been ruled
    out by measurement, and the last one ruled itself out on a fact that reframes
    the question: **CPython returns freed objects to pymalloc's ARENAS, not to
    the OS.** So the quantity that matters is not which request allocated, but
    how much the process holds from the OS that is no longer holding live data.

    `log_pymalloc_arena_stats` already reports both halves -- `arena_mb` against
    `bytes_in_allocated_blocks_mb` -- and the gap between them IS fragmentation:
    memory the OS has given us and Python cannot hand back, because an arena is
    only returned when it is COMPLETELY empty and one survivor pins the whole
    megabyte.

    **If `arena_mb` climbs while `bytes_in_allocated_blocks_mb` stays flat, the
    ~173 MB/h is fragmentation and not retention, and no amount of freeing
    objects will return it.** That is a different defect with different fixes,
    and it is the fork every remaining hypothesis rests on.

    BUDGETED SEPARATELY from the watchdog's alarm census, and capped: this walks
    every arena and briefly repoints fd 2, so it is emphatically not free --
    `#241` is the precedent for periodic work that was assumed to be. It runs
    only where the caller already pays for measurement, off the emission path
    that fires every 200 solo requests.
    """
    payload = log_pymalloc_arena_stats(
        reason, budget=(_ARENA_TREND_STATE, _arena_trend_budget()), raw=False, quiet=True)
    if payload is not None:
        _ARENA_TREND_STATE["last"] = {
            "arenas": payload.get("arenas_currently_allocated"),
            "arena_mb": payload.get("arena_mb"),
            "live_mb": payload.get("bytes_in_allocated_blocks_mb"),
        }
        arena_mb = payload.get("arena_mb")
        live_mb = payload.get("bytes_in_allocated_blocks_mb")
        if isinstance(arena_mb, (int, float)) and isinstance(live_mb, (int, float)):
            # THE number: what the OS has given us that Python is not using.
            _ARENA_TREND_STATE["last"]["fragmentation_mb"] = round(arena_mb - live_mb, 3)
    return payload


_SMAPS_TREND_STATE: dict[str, Any] = {"count": 0, "last": None}
_SMAPS_TREND_MAX_DEFAULT = 60


def _smaps_trend_budget() -> int:
    raw_value = str(os.environ.get("SYNDICATE_SMAPS_TREND_SAMPLES") or "").strip()
    if not raw_value:
        return _SMAPS_TREND_MAX_DEFAULT
    try:
        return int(raw_value)
    except ValueError:
        return _SMAPS_TREND_MAX_DEFAULT


def sample_smaps_trend(reason: str) -> dict[str, Any] | None:
    """One anon-by-REGION-SIZE reading for a time series.

    `#632`, and this is the only instrument left that can see the memory.
    Measured: **pymalloc arenas are 40% of worker RSS and did not move**, and
    `#435` found glibc `malloc_info` blind too (13.9% coverage,
    `arena_not_representative`). Both are structurally incapable of seeing a
    large DIRECT mmap -- and anything over 512 bytes bypasses pymalloc entirely,
    which a 28 MB JSON payload certainly does.

    `parse_smaps` buckets anon by mapping SIZE (`<64KB`, `64KB-1MB`, `1-8MB`,
    `8-64MB`, `>64MB`). A payload-shaped allocation lands in `8-64MB`, so the
    question `#632` has been circling for four probes finally has a form the data
    can answer: **which bucket grows?**

    It also reconciles against the cgroup's own anon and publishes
    `reconciles_within_pct`. That matters more than it sounds: smaps and the
    cgroup are INDEPENDENT accountings of the same bytes, so a breakdown that
    does not add up must not be read as attribution. This investigation has twice
    acted on a number that was internally consistent and wrong.

    Budgeted separately from the alarm census, capped, and sampled off the
    emission path -- the kernel walks page tables for this, so it is not free.
    """
    payload = log_smaps_anon_breakdown(
        reason, budget=(_SMAPS_TREND_STATE, _smaps_trend_budget()), quiet=True)
    if payload is not None:
        _SMAPS_TREND_STATE["last"] = {
            "total_anon_mb": payload.get("total_anon_mb"),
            "by_size_mb": payload.get("anon_mmap_by_size_mb"),
            # BY KIND, and the first clean series is why. Split by pid over
            # ~27 min, 65-70% of each worker's climb was in anon that is NOT an
            # anonymous mmap at all -- so the size buckets, which only cover
            # anon_mmap, could see barely a third of the growth and the rest was
            # a residual I had to compute by subtraction. `parse_smaps` already
            # returns this; recording only the buckets threw the majority term
            # away. heap vs stack vs file_backed answers WHERE the other 2/3 is.
            "by_kind_mb": payload.get("by_kind_mb"),
            "cgroup_anon_mb": payload.get("cgroup_anon_mb"),
            "reconciles": payload.get("reconciles"),
            "reconciles_within_pct": payload.get("reconciles_within_pct"),
        }
    return payload


def _run_censuses(reason: str) -> None:
    """Both censuses, in order, on one thread. Neither may stop the other.

    The tracked census answers "is it Python containers" (measured: no, 135MB of
    415k objects against 1709MB anon) and the untracked one answers "is it the
    strings hanging off them". Run together they either account for the anon or
    prove it is below Python entirely -- and that is the fork the next fix
    depends on, so a failure in the first must not skip the second.
    """
    try:
        log_heap_census(reason)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[memory_observability] HEAP_CENSUS_THREAD_FAILED {type(exc).__name__}: {exc}", flush=True)
    try:
        log_untracked_bytes_census(reason)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[memory_observability] UNTRACKED_CENSUS_THREAD_FAILED {type(exc).__name__}: {exc}", flush=True)
    try:
        log_pymalloc_arena_stats(reason)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[memory_observability] PYMALLOC_STATS_THREAD_FAILED {type(exc).__name__}: {exc}", flush=True)
    try:
        log_smaps_anon_breakdown(reason)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[memory_observability] SMAPS_THREAD_FAILED {type(exc).__name__}: {exc}", flush=True)


def _watchdog_maybe_heap_census(payload: dict[str, Any]) -> None:
    """Census the heap once we are holding the memory we are trying to explain."""
    try:
        anon_mb = payload.get("memory_unreclaimable_mb")
        if anon_mb is None:
            anon_mb = payload.get("memory_anon_mb")
        if not watchdog_should_heap_census(
            anon_mb=anon_mb, already_censused=bool(_WATCHDOG_STATE.get("heap_censused"))
        ):
            return
        _WATCHDOG_STATE["heap_censused"] = True
        # OFF-THREAD, for the reason the dump is: a walk of millions of objects
        # holds the GIL, and a blocked sampler is indistinguishable from a calm
        # system. Measured 2026-08-15 02:11-02:55.
        import threading

        threading.Thread(
            target=_run_censuses,
            args=(f"watchdog_anon_{int(float(anon_mb))}mb",),
            name="memory-watchdog-census",
            daemon=True,
        ).start()
    except Exception as exc:  # pragma: no cover - defensive, must never raise
        print(
            f"[memory_observability] WATCHDOG_HEAP_CENSUS_FAILED {type(exc).__name__}: {exc}",
            flush=True,
        )


def _watchdog_loop(interval_seconds: float) -> None:  # pragma: no cover - thread body
    last_emitted_mb: float | None = None
    previous_mb: float | None = None
    previous_at: float | None = None
    while True:
        try:
            time.sleep(interval_seconds)
            payload = container_memory_payload("watchdog")
            last_stage = _WATCHDOG_STATE.get("last_stage")
            last_stage_at = _WATCHDOG_STATE.get("last_stage_at")
            payload["last_stage"] = last_stage
            payload["seconds_since_stage"] = (
                round(time.monotonic() - last_stage_at, 1)
                if isinstance(last_stage_at, (int, float))
                else None
            )
            # Climb rate is computed on EVERY sample, before the emit gate --
            # the excursion must be detectable even in the ticks the gate
            # suppresses, or the dump trigger inherits the gate's blind spots.
            current_mb = payload.get("memory_unreclaimable_mb")
            if current_mb is None:
                current_mb = payload.get("memory_anon_mb")
            now = time.monotonic()
            climb = watchdog_excursion_climb_mb_per_s(
                previous_mb,
                current_mb,
                (now - previous_at) if isinstance(previous_at, (int, float)) else None,
            )
            if climb is not None:
                payload["climb_mb_per_s"] = round(climb, 1)
            _watchdog_maybe_dump_allocations(payload, climb)
            _watchdog_maybe_heap_census(payload)
            # Placed with the other census hooks, and like them BEFORE the emit
            # gate: `_watchdog_should_emit` suppresses samples when the number
            # is not moving, and a trigger downstream of it would inherit that
            # blind spot -- the same reason the climb rate above is computed on
            # every sample rather than every emitted one.
            _watchdog_maybe_peak_smaps(payload)
            # Placed LAST of the census hooks and still before the emit gate.
            # Last because the cheaper readings should already be on the wire if
            # this one throws; before the gate for the same reason as the others
            # -- `_watchdog_should_emit` suppresses samples when the number is
            # not moving, and a trigger downstream of it inherits that blind spot.
            _watchdog_maybe_stack_dump(payload)
            if current_mb is not None:
                previous_mb = float(current_mb)
                previous_at = now
            if not _watchdog_should_emit(payload, last_emitted_mb):
                continue
            metric = current_mb
            if metric is not None:
                last_emitted_mb = float(metric)
            print(
                f"MEMORY_WATCHDOG {json.dumps(payload, default=str, sort_keys=True)}",
                file=sys.stderr,
                flush=True,
            )
        except Exception:
            # Never die, never spin. A crashed sampler would remove the only
            # instrument that can see the excursion, silently.
            try:
                time.sleep(interval_seconds)
            except Exception:
                return


def start_memory_watchdog(interval_seconds: float | None = None) -> bool:
    """Start the sampler once. Returns True if a thread is running because of us."""
    try:
        if not memory_watchdog_enabled():
            print("[memory_observability] MEMORY_WATCHDOG_DISABLED", flush=True)
            return False
        if _WATCHDOG_STATE.get("thread") is not None:
            return False
        import threading

        interval = interval_seconds if interval_seconds is not None else _env_float(
            "SYNDICATE_MEMORY_WATCHDOG_INTERVAL_SECONDS", 2.0
        )
        interval = max(0.5, interval)
        thread = threading.Thread(
            target=_watchdog_loop,
            args=(interval,),
            name="memory-watchdog",
            daemon=True,
        )
        _WATCHDOG_STATE["thread"] = thread
        thread.start()
        print(
            f"[memory_observability] MEMORY_WATCHDOG_STARTED interval_s={interval} "
            f"floor_pct={_env_float('SYNDICATE_MEMORY_WATCHDOG_FLOOR_PCT', 60.0)} "
            f"delta_mb={_env_float('SYNDICATE_MEMORY_WATCHDOG_DELTA_MB', 200.0)}",
            flush=True,
        )
        return True
    except Exception as exc:  # pragma: no cover - defensive, must never raise
        print(
            f"[memory_observability] MEMORY_WATCHDOG_START_FAILED {type(exc).__name__}: {exc}",
            flush=True,
        )
        return False


# #327. The ring buffer behind /api/ops/intelligence/memory-diagnostics.
#
# THIS LIVES HERE, ONCE, ON PURPOSE. There used to be two functions named
# `_diag_log_all_process_memory` -- `pipeline/intelligence_state.py` (which
# logged AND persisted) and `scripts/run_refresh_worker.py` (which only
# logged). The call site `_diag_log_all_process_memory("post_mlb_sim_tick")`
# read exactly like the one that persists, so nobody checking "is this stage
# instrumented?" had reason to look twice.
#
# The cost was measured, not hypothetical: over 15:59-16:38Z there were 172
# pid-38 samples in the logs and 39 in the ring buffer -- a lane had been
# reading 23% of them, and the missing 77% carried the highest values
# (`post_mlb_sim_tick` max 1867.4MB against `post_pool_assembled` max 1044.1).
# The single largest memory excursion on the service was invisible to the
# instrument built to find memory excursions.
#
# Same shape as `#317`'s two board-snapshot write sites and `#105` before it,
# and `#317` had to learn it twice: when a near-duplicate helper means only one
# copy gets the fix, EXTRACT rather than patch the second copy.
PROCESS_MEMORY_CHECKPOINT_MAX_RECORDS = 300


def process_memory_checkpoint_path() -> Path:
    from syndicate.features.shared.refresh_state_store import reports_root

    return reports_root() / "live_refresh_loop" / "memory_diagnostics.json"


def dump_process_memory_checkpoint(stage: str, payload: dict[str, Any]) -> None:
    """Append one sample to the bounded ring buffer.

    Confirmed live: this background thread's stderr does not reliably reach
    Render's log collector before a SIGKILL once memory pressure is severe --
    checkpoints that provably executed (container-level memory deltas between
    them) never appeared in the platform logs. Routes through
    write_json_file/read_json_file so it is readable from the WEB service:
    refresh-worker has no HTTP server of its own.

    THE CAP IS SIZED, NOT GUESSED. Measured 2026-08-10 before this extraction:
    60 records at 1,233 bytes each = 74KB, covering 36.1 minutes at
    `intelligence_state`'s ~9 stages per cycle. Wiring the worker's stages in
    multiplies the write rate roughly 6x (26 `live_lens_tick_*` and 6
    `post_mlb_sim_tick` per 5 minutes), which at 60 records would have collapsed
    the window to ~6 minutes -- fixing the blind spot while quietly destroying
    the history that made it findable. 300 records restores ~30 minutes at
    ~370KB, which is 4.4% of the 8,388,608 keyvalue ceiling.
    """
    try:
        from syndicate.features.shared.refresh_state_store import read_json_file, write_json_file

        path = process_memory_checkpoint_path()
        existing = read_json_file(path)
        records = list(existing.get("records") or []) if isinstance(existing, dict) else []
        records.append({"stage": stage, "wall_clock": time.time(), "pid": os.getpid(), **payload})
        records = records[-PROCESS_MEMORY_CHECKPOINT_MAX_RECORDS:]
        write_json_file(path, {"records": records})
    except Exception as exc:  # noqa: BLE001
        print(f"[memory_observability] DIAG_MEMORY_DUMP_FAILED stage={stage} {type(exc).__name__}: {exc}", flush=True)


# #327. The per-stage high-water mark, and WHY it exists rather than a bigger ring.
#
# The ring is a time series, so its cost scales with the SAMPLE RATE and its
# coverage shrinks as you instrument more stages. Wiring `live_lens_tick_*` in
# adds ~6.6 samples/min, which takes 300 records from ~36 minutes of history to
# ~20-23 -- while the excursions being hunted arrive 11-42 minutes apart
# (measured, n=4). Instrumenting more would have shrunk the window below the
# thing it must observe. Buying the window back means ~900 records (~1.1MB)
# rewritten ~15x/min on a memory-constrained worker.
#
# A high-water record is O(DISTINCT STAGES), not O(samples). It never ages out,
# so a once-per-75-minutes excursion cannot be lost to rotation, and it costs
# nothing to keep more of. Different question, and the right one for `#327`:
# the ring answers "what happened lately", this answers "what is the worst this
# stage has ever been".
#
# Separate artifact from the ring ON PURPOSE: a write here must not rewrite the
# ring's ~370KB, and the common path writes NOTHING AT ALL -- see below.
PROCESS_MEMORY_HIGH_WATER_MAX_STAGES = 200


def process_memory_high_water_path() -> Path:
    from syndicate.features.shared.refresh_state_store import reports_root

    return reports_root() / "live_refresh_loop" / "memory_high_water.json"


def _high_water_metric(payload: dict[str, Any]) -> float | None:
    """Rank by what actually kills the container, falling back to process RSS.

    `container_memory_mb` is the cgroup figure the OOM killer acts on;
    `accounted_rss_mb` is the sum this process can see. Preferring the former
    matters because the two diverged by ~800MB during the `#327` excursion.
    """
    for key in ("container_memory_mb", "accounted_rss_mb"):
        value = payload.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def update_process_memory_high_water(stage: str, payload: dict[str, Any]) -> bool:
    """Record this sample if it is the worst yet for `stage`. Returns True if written.

    **Writes only on a new peak.** Most samples are not peaks, so the steady
    state is one read and no write -- which is what makes it affordable to call
    from a high-rate loop the ring cannot absorb. A stage's FIRST sample always
    peaks, so every instrumented stage gets a record immediately: that alone
    answers "is this stage reaching the instrument at all?", which is the
    question `#327` existed to ask and could not.

    Deliberately NOT reset on boot. The point is to survive long enough to
    catch a rare event, so `pid` and `observed_at` are stored and staleness is
    left visible to the reader rather than silently discarded.
    """
    metric = _high_water_metric(payload)
    if metric is None:
        return False
    try:
        from syndicate.features.shared.refresh_state_store import read_json_file, write_json_file

        path = process_memory_high_water_path()
        existing = read_json_file(path)
        stages = dict(existing.get("stages") or {}) if isinstance(existing, dict) else {}
        previous = stages.get(stage)
        if isinstance(previous, dict):
            try:
                if float(previous.get("peak_mb")) >= metric:
                    return False
            except (TypeError, ValueError):
                pass
        if stage not in stages and len(stages) >= PROCESS_MEMORY_HIGH_WATER_MAX_STAGES:
            # Bounded against unbounded stage cardinality (stage names embed the
            # sport, so the set grows with the sport list). Dropping the lowest
            # peak keeps the interesting end.
            def _peak(item: Any) -> float:
                try:
                    return float(item.get("peak_mb"))
                except (TypeError, ValueError, AttributeError):
                    return -1.0
            lowest = min(stages, key=lambda k: _peak(stages[k]))
            stages.pop(lowest, None)
        stages[stage] = {
            "stage": stage,
            "peak_mb": metric,
            "container_memory_mb": payload.get("container_memory_mb"),
            "accounted_rss_mb": payload.get("accounted_rss_mb"),
            "container_memory_pct_of_max": payload.get("container_memory_pct_of_max"),
            "observed_at": time.time(),
            "pid": os.getpid(),
            "processes": payload.get("processes"),
        }
        write_json_file(path, {"stages": stages})
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[memory_observability] HIGH_WATER_UPDATE_FAILED stage={stage} {type(exc).__name__}: {exc}", flush=True)
        return False


def log_and_persist_process_memory(stage: str, *, append_to_ring: bool = True, **extra: Any) -> dict[str, Any] | None:
    """Log a process-memory sample to stderr, and persist it so web can read it.

    The one entry point. Every caller that wants a stage visible from web must
    use THIS -- `log_all_process_memory` alone writes stderr only, which is
    exactly the gap `#327` records. **And a name is not a census: three
    emitters existed when I unified the two that shared a name.**

    `append_to_ring=False` records the high-water mark but keeps the sample out
    of the time-series ring. That is for high-rate loops (`live_lens_tick_*`,
    ~6.6/min) whose samples would rotate the ring below the 11-42 minute
    inter-arrival gap of the excursions being hunted. Those stages become
    VISIBLE without making the ring blind.
    """
    try:
        payload = log_all_process_memory(stage, **extra)
        if append_to_ring:
            dump_process_memory_checkpoint(stage, payload)
        update_process_memory_high_water(stage, payload)
        return payload
    except Exception as exc:  # noqa: BLE001
        print(f"[memory_observability] DIAG_MEMORY_LOG_FAILED stage={stage} {type(exc).__name__}: {exc}", flush=True)
        return None


def log_all_process_memory(stage: str, **extra: Any) -> dict[str, Any]:
    payload = {"stage": str(stage or "").strip() or "unknown"}
    payload.update(extra)
    snapshot = get_all_process_memory_snapshot()
    debug_payload = snapshot.pop("process_enum_debug", None)
    payload.update(snapshot)
    if debug_payload is not None:
        print(f"PROCESS_ENUM_DEBUG {json.dumps(debug_payload, default=str, sort_keys=True)}", file=sys.stderr, flush=True)
    print(f"ALL_PROCESS_MEMORY {json.dumps(payload, default=str, sort_keys=True)}", file=sys.stderr, flush=True)
    return payload


_HEAP_CENSUS_STATE: dict[str, int] = {"count": 0}
_HEAP_CENSUS_MAX_PER_PROCESS = 4


def log_heap_census(reason: str, *, min_container_mb: float = 0.0) -> dict[str, Any] | None:
    """What is this process actually holding, by object type?

    #257. Eight mechanisms for refresh-worker's OOM were reasoned from source
    across three sessions and all eight were wrong. This asks the process
    instead of the code.

    `gc.get_objects()`, deliberately NOT `tracemalloc`. tracemalloc tracks
    allocation SITES, is blind to memory pymalloc has already handed back to its
    arenas, and has misled this incident three separate times (including
    inflating one probe by 2.4x). This answers the different and correct
    question: what is reachable right now.

    Shallow `sys.getsizeof` undercounts nested containers, so the COUNTS are the
    primary signal -- 2GB of anything must appear as tens of millions of
    objects, and the type distribution alone separates quote dicts from game
    contexts from ledger rows. Any single object over 50MB is named outright,
    because one huge list is a different bug from ten million small dicts.

    Capped per process: walking the whole heap is not free, and this is
    instrumentation meant to be deleted once it has answered.
    """
    if _HEAP_CENSUS_STATE["count"] >= _HEAP_CENSUS_MAX_PER_PROCESS:
        return None
    try:
        current_mb = _bytes_to_mb(_read_container_memory_current_bytes())
        if min_container_mb and (current_mb is None or current_mb < float(min_container_mb)):
            return None

        import collections
        import gc

        _HEAP_CENSUS_STATE["count"] += 1
        gc.collect()
        counts: Any = collections.Counter()
        shallow: Any = collections.Counter()
        huge: list[tuple[int, str, str]] = []
        for obj in gc.get_objects():
            try:
                name = type(obj).__name__
                counts[name] += 1
                size = sys.getsizeof(obj)
                shallow[name] += size
                if size > 50 * _BYTES_PER_MB:
                    huge.append((size, name, repr(obj)[:140]))
            except Exception:
                continue
        payload = {
            "reason": str(reason or "")[:80],
            "census_index": _HEAP_CENSUS_STATE["count"],
            "container_mb": current_mb,
            "gc_tracked_objects": int(sum(counts.values())),
            "top_by_count": counts.most_common(20),
            "top_by_shallow_mb": [
                (name, round(total / _BYTES_PER_MB, 1)) for name, total in shallow.most_common(20)
            ],
            "individually_huge_mb": [
                (round(size / _BYTES_PER_MB, 1), name, text)
                for size, name, text in sorted(huge, reverse=True)[:10]
            ],
        }
        # print(..., flush=True) rather than logger.info -- see #37, logger.info
        # never reaches Render's collector, which is a large part of why this
        # incident stayed invisible.
        print(f"HEAP_CENSUS {json.dumps(payload, default=str)}", flush=True)
        return payload
    except Exception as exc:  # pragma: no cover - diagnostic must never raise
        print(f"HEAP_CENSUS_FAILED {type(exc).__name__}: {exc}", flush=True)
        return None


def log_runtime_memory(stage: str, **extra: Any) -> None:
    log_process_tree_memory(stage, **extra)
    log_container_memory(stage, **extra)


# #285. `gc.collect()` returns memory to PYTHON. It does not return it to the
# KERNEL, and the cgroup guards in this repo measure the kernel's number. That
# gap is the whole of this helper.
#
# THE SAMPLE PAIR that motivates it, measured on refresh-worker 2026-08-09
# under `#290`'s control condition (the hydrated overview blocked on every
# cycle, so it is excluded by construction):
#
#     01:03:43   container 2564.9 MB   gc_objects 381,063
#     01:05:22   container 2654.2 MB   gc_objects 308,068
#                container  +89.3 MB   gc_objects  -72,995
#
# A collection ran, 73,000 objects went away, and the resident set went UP.
#
# `malloc_trim(0)` asks glibc to hand back the pages it is holding that are
# ALREADY FREE. It cannot touch a live object, so it is safe by construction:
# the worst case is that nothing is free and it costs a few milliseconds.
#
# It is also the DISCRIMINATOR `#285` was left needing. That item closed with
# two hypotheses the heap census provably cannot separate, because
# `gc.get_objects()` never enumerates `str`/`bytes`/`ndarray` (verified on 3.11,
# all three untracked) -- which on a Monte Carlo platform is most of what the
# workload is made of:
#
#   (1) allocator retention -- freed by Python, never returned to the OS.
#   (2) live str/bytes/ndarray held by references the census cannot walk.
#
# The before/after in this line settles it in one cycle and needs no new
# instrument: anon drops => (1), and this call is also the remedy. anon holds
# => (2), and the work becomes finding what holds the buffers. Log BOTH the
# cgroup `anon` and this process's RSS -- anon is what the guards read, RSS is
# what attributes the change to this process rather than a sibling.
#
# Why cgroup `anon` and not `container_memory_mb`: `memory.current` includes
# reclaimable page cache, ~1.4GB of it here, and reading the raw number as
# pressure has now misled this incident twice. [[memory.current is page cache]]
#
# Deliberately NOT `MALLOC_ARENA_MAX`: that is an env var, it only helps if (1)
# is true, and a null result from it would be uninformative rather than
# exculpating -- it never tests (2). It is the correct follow-on once this has
# said which world we are in, not the first move.
#
# UPDATE 2026-08-10 -- THAT FOLLOW-ON IS NOW EARNED, and the sequencing above
# is why it is worth doing rather than a guess. The trim ran 24 times in a
# 46-minute window and answered:
#
#   returned to the kernel BY TRIM :  1109.6 MB
#   returned to the kernel BY GC   :  - 104.3 MB   (gc released >0.05MB on 2/24)
#
# The collection returned NEGATIVE memory -- anon rose during `gc.collect()`
# more often than it fell. Hypothesis (1) is confirmed and is not a hypothesis.
#
# But it is only about half the problem. Measured at T+27..T+40 on the
# 2026-08-10 03:46:11Z boot, with the trim live:
#
#   anon at guard   1108-1263    (failing boot: 1477-1525)
#   pid RSS         1119-1126    (failing boot plateau: 1494-1577)
#   ratchet         ~+11 MB/min  (was ~+24)
#
# Slowed, not stopped -- and by the time the guard fires, `by_trim` is down to
# 0.0-2.9MB. There is nothing left to hand back. The trim releases everything
# already free three times a cycle and RSS still climbs, so the residual CANNOT
# be free-but-unreturned memory. It is live objects, or free memory too
# fragmented for `malloc_trim` to return whole pages -- and only the second of
# those responds to capping arenas.
#
# So `mallopt(M_ARENA_MAX, 2)` is a probe for ONE named mechanism, not a
# generic knob: glibc gives each thread its own arena (up to 8x cores), each
# grows independently, and free space in one is unusable by another. Fewer
# arenas means less stranded-but-free space. If anon still climbs after this,
# fragmentation is excluded too and the remaining explanation is live
# retention -- which is when the root-walking sizer becomes the work.
#
# Via ctypes rather than the env var deliberately: the env var needs a config
# change to take effect, and `render.yaml` is the one file whose push applies
# to production (`#284`). This is code, so it ships on the deploy that carries
# it and cannot be silently undone by a blueprint sync (`#312`).
_MALLOC_ARENA_STATE: dict[str, Any] = {"resolved": False, "applied": False, "reason": ""}

# glibc `malloc.h`: M_ARENA_MAX is -8. Not exposed by Python anywhere, so the
# literal is the interface.
_M_ARENA_MAX = -8


def configure_malloc_arenas(max_arenas: int = 2) -> bool:
    """Cap glibc's per-thread arenas. Once per process, as early as possible.

    MUST be called before the workload spawns threads. `mallopt` only governs
    arenas created AFTER it returns -- arenas that already exist are untouched,
    so calling this late caps nothing that matters. That is also why it is worth
    calling even though Python has already allocated at import time: the growth
    this targets happens during the sim/overview work, long after startup.

    Returns True only if glibc accepted it. Never raises: on every non-glibc
    machine in this repo -- Windows, no WSL -- this takes the unavailable branch
    on every call, exactly as `_resolve_malloc_trim` does.

    THE `MALLOC_ARENA_INIT` LINE IS THE POINT, for the same reason the trim's
    is. `mallopt` returns 1 for success and 0 for failure and glibc will happily
    return 0 without explanation; a rejected call and a call that worked but did
    not help are both silence from outside. Six fixes shipped deployed-and-inert
    on 2026-08-09/10 with passing tests. Grep `MALLOC_ARENA_INIT` after the
    deploy and the branch is named rather than inferred from a better number.
    """
    if _MALLOC_ARENA_STATE["resolved"]:
        return bool(_MALLOC_ARENA_STATE["applied"])
    _MALLOC_ARENA_STATE["resolved"] = True
    rc: int | None = None
    if not sys.platform.startswith("linux"):
        _MALLOC_ARENA_STATE["reason"] = f"platform={sys.platform}"
    else:
        try:
            import ctypes
            import ctypes.util

            for candidate in ("libc.so.6", ctypes.util.find_library("c"), None):
                try:
                    libc = ctypes.CDLL(candidate, use_errno=True)
                except Exception:
                    continue
                mallopt = getattr(libc, "mallopt", None)
                if mallopt is None:
                    continue
                mallopt.argtypes = [ctypes.c_int, ctypes.c_int]
                mallopt.restype = ctypes.c_int
                rc = int(mallopt(_M_ARENA_MAX, int(max_arenas)))
                # 1 = accepted, 0 = refused. Hold the CDLL for the same
                # lifetime reason the trim does.
                _MALLOC_ARENA_STATE["applied"] = rc == 1
                _MALLOC_ARENA_STATE["libc"] = libc
                if rc != 1:
                    _MALLOC_ARENA_STATE["reason"] = f"mallopt_returned_{rc}"
                break
            else:
                _MALLOC_ARENA_STATE["reason"] = "symbol_not_found"
        except Exception as exc:  # pragma: no cover - defensive, must never raise
            _MALLOC_ARENA_STATE["reason"] = f"{type(exc).__name__}: {exc}"
    payload = {
        "applied": bool(_MALLOC_ARENA_STATE["applied"]),
        "max_arenas": int(max_arenas),
        "rc": rc,
        "platform": sys.platform,
        "pid": os.getpid(),
        # Reported because glibc's DEFAULT is 8x cores -- naming what we moved
        # away from is what makes the number interpretable later.
        "cpu_count": os.cpu_count(),
        "env_malloc_arena_max": os.environ.get("MALLOC_ARENA_MAX"),
        "unavailable_reason": _MALLOC_ARENA_STATE["reason"] or None,
    }
    print(f"MALLOC_ARENA_INIT {json.dumps(payload, default=str, sort_keys=True)}", flush=True)
    return bool(_MALLOC_ARENA_STATE["applied"])
_MALLOC_TRIM_STATE: dict[str, Any] = {"resolved": False, "fn": None, "libc": None, "unavailable_reason": ""}


def _resolve_malloc_trim() -> Any:
    """Bind glibc's `malloc_trim`, once, or say out loud why it could not.

    Returns None on anything that is not glibc -- Windows, musl, a libc without
    the symbol. Callers must treat None as "no trim happened", never as an
    error: this is an optimisation, and every non-Linux developer machine in
    this repo takes that branch on every call.

    THE ONE-TIME `MALLOC_TRIM_INIT` LINE IS NOT DECORATION. This binding cannot
    be executed anywhere in this repo's development environment -- Windows, no
    WSL, no Docker -- so the first proof that it works at all is a production
    log line. Without this line a failed `dlopen` and a successful trim that
    happened to release nothing look identical from outside: both are silence.
    That is the exact shape of today's deployed-and-inert fix, a concurrency
    cap that could not fire, and a reader pointed at a source nothing writes.
    Grep `MALLOC_TRIM_INIT` after the deploy and the branch is named.
    """
    if _MALLOC_TRIM_STATE["resolved"]:
        return _MALLOC_TRIM_STATE["fn"]
    _MALLOC_TRIM_STATE["resolved"] = True
    library = None
    if not sys.platform.startswith("linux"):
        _MALLOC_TRIM_STATE["unavailable_reason"] = f"platform={sys.platform}"
    else:
        try:
            import ctypes
            import ctypes.util

            candidates = ["libc.so.6", ctypes.util.find_library("c"), None]
            for candidate in candidates:
                try:
                    libc = ctypes.CDLL(candidate, use_errno=True)
                except Exception:
                    continue
                trim = getattr(libc, "malloc_trim", None)
                if trim is None:
                    continue
                trim.argtypes = [ctypes.c_size_t]
                trim.restype = ctypes.c_int
                _MALLOC_TRIM_STATE["fn"] = trim
                # Hold the CDLL too. The function pointer's lifetime is tied to
                # the library object's and `libc` is a local -- free insurance,
                # and it makes the dependency explicit rather than relying on
                # ctypes never calling dlclose.
                _MALLOC_TRIM_STATE["libc"] = libc
                library = candidate or "<main program>"
                break
            else:
                _MALLOC_TRIM_STATE["unavailable_reason"] = "symbol_not_found"
        except Exception as exc:  # pragma: no cover - defensive, must never raise
            _MALLOC_TRIM_STATE["unavailable_reason"] = f"{type(exc).__name__}: {exc}"
    payload = {
        "available": _MALLOC_TRIM_STATE["fn"] is not None,
        "library": library,
        "platform": sys.platform,
        "pid": os.getpid(),
        "unavailable_reason": _MALLOC_TRIM_STATE["unavailable_reason"] or None,
    }
    print(f"MALLOC_TRIM_INIT {json.dumps(payload, default=str, sort_keys=True)}", flush=True)
    return _MALLOC_TRIM_STATE["fn"]


def release_freed_memory_to_os(reason: str, *, collect_first: bool = True) -> dict[str, Any] | None:
    """Return already-freed heap pages to the kernel; log what moved.

    Never raises. Returns None when no trim was attempted (non-glibc), so a
    caller can tell "trimmed nothing" from "could not trim" -- those are
    different findings and collapsing them is how a null result gets read as
    evidence.

    `collect_first` runs a full `gc.collect()` first, because `malloc_trim`
    releases only what Python has ALREADY freed and uncollected cycle garbage
    is not yet free. The two are measured separately in the emitted line
    (`anon_after_gc_mb` between before and after) precisely so this does not
    become one undifferentiated number: the collect is expected to move anon by
    roughly nothing -- that is what the 01:03/01:05 sample pair above showed --
    and if it ever does move it, that is a finding about hypothesis (2) and
    must not be silently credited to the trim.
    """
    trim = _resolve_malloc_trim()
    label = str(reason or "").strip() or "unspecified"
    if trim is None:
        return None
    import time as _time

    stat_before = _read_container_memory_stat()
    anon_before = stat_before.get("anon") if stat_before else None
    rss_before = _current_process_rss_bytes()
    anon_after_gc = anon_before
    gc_collected = None
    gc_elapsed_ms = None
    if collect_first:
        try:
            import gc

            gc_started_at = _time.perf_counter()
            gc_collected = int(gc.collect())
            gc_elapsed_ms = round((_time.perf_counter() - gc_started_at) * 1000.0, 1)
            stat_after_gc = _read_container_memory_stat()
            anon_after_gc = stat_after_gc.get("anon") if stat_after_gc else anon_before
        except Exception:
            anon_after_gc = anon_before
    started_at = _time.perf_counter()
    try:
        rc = int(trim(0))
    except Exception as exc:  # pragma: no cover - defensive, must never raise
        print(f"MALLOC_TRIM reason={label} error={type(exc).__name__}: {exc}", flush=True)
        return None
    elapsed_ms = round((_time.perf_counter() - started_at) * 1000.0, 1)
    stat_after = _read_container_memory_stat()
    anon_after = stat_after.get("anon") if stat_after else None
    rss_after = _current_process_rss_bytes()
    payload: dict[str, Any] = {
        "reason": label,
        # glibc returns 1 when it actually released memory, 0 when it could
        # not. Reported rather than swallowed: rc=1 with a flat anon means
        # something else grew during the call, which is a different story from
        # rc=0 (nothing was free to give back) and points at hypothesis (2).
        "rc": rc,
        "elapsed_ms": elapsed_ms,
        "gc_collected": gc_collected,
        "gc_elapsed_ms": gc_elapsed_ms,
        "anon_before_mb": _bytes_to_mb(anon_before),
        "anon_after_gc_mb": _bytes_to_mb(anon_after_gc),
        "anon_after_mb": _bytes_to_mb(anon_after),
        # Attributed, not lumped: the trim's own contribution is measured from
        # the post-gc reading, so a drop caused by the collection can never be
        # reported as evidence for allocator retention.
        "anon_released_by_trim_mb": _bytes_to_mb(anon_after_gc - anon_after) if (anon_after_gc is not None and anon_after is not None) else None,
        "anon_released_mb": _bytes_to_mb(anon_before - anon_after) if (anon_before is not None and anon_after is not None) else None,
        "rss_before_mb": _bytes_to_mb(rss_before),
        "rss_after_mb": _bytes_to_mb(rss_after),
        "rss_released_mb": _bytes_to_mb(rss_before - rss_after) if (rss_before is not None and rss_after is not None) else None,
    }
    # print(..., flush=True), not logger.info -- #37, logger.info never reaches
    # Render's log collector and this line is the entire experiment.
    print(f"MALLOC_TRIM {json.dumps(payload, default=str, sort_keys=True)}", flush=True)
    return payload


def log_dataframe_memory(name: str, df: Any) -> None:
    rows = None
    columns = None
    deep_memory_bytes = None

    try:
        rows = int(len(df)) if df is not None else None
    except Exception:
        rows = None

    try:
        columns = int(len(getattr(df, "columns", []))) if df is not None else None
    except Exception:
        columns = None

    try:
        if df is not None and hasattr(df, "memory_usage"):
            usage = df.memory_usage(index=True, deep=True)
            deep_memory_bytes = int(usage.sum() if hasattr(usage, "sum") else usage)
    except Exception:
        deep_memory_bytes = None

    payload = {
        "name": str(name or "").strip() or "unnamed",
        "rows": rows,
        "columns": columns,
        "deep_memory_mb": _bytes_to_mb(deep_memory_bytes),
    }
    print(f"DATAFRAME_MEMORY {json.dumps(payload, default=str, sort_keys=True)}", file=sys.stderr, flush=True)


def log_list_memory(name: str, list_obj: Any) -> None:
    payload = {
        "name": str(name or "").strip() or "unnamed",
        "list_id": id(list_obj) if list_obj is not None else None,
        "length": None,
    }
    try:
        payload["length"] = int(len(list_obj)) if list_obj is not None else None
    except Exception:
        payload["length"] = None
    print(f"LIST_MEMORY {json.dumps(payload, default=str, sort_keys=True)}", file=sys.stderr, flush=True)


# --- `#423` step 1: glibc arena accounting -----------------------------------
#
# WHAT THIS ANSWERS, AND WHY IT IS STEP 1. Two candidates survive for
# refresh-worker's anon growth: live objects, or free memory too fragmented for
# `malloc_trim` to hand back. `malloc_info` separates them directly -- it
# reports, per arena, how much the allocator holds from the OS and how much of
# that is sitting in free chunks. Large free-but-held => fragmentation. Small
# free with large system => live retention.
#
# It costs one libc call and no per-allocation bookkeeping, which is why it
# comes before `tracemalloc`. `tracemalloc` stores a traceback per allocation
# and this worker already reaches its ceiling every ~1.1h; an instrument that
# can push the process over is not a first move (`#241`: worker periodic work
# is never free).
#
# THE INIT LINE IS NOT DECORATION -- same reasoning `_resolve_malloc_trim`
# records. None of this can execute on any dev machine in this repo (Windows,
# no WSL), so the first proof it works is a production log line. Without
# `MALLOC_INFO_INIT`, a failed `dlopen` and a successful call are both silence.
_MALLOC_INFO_STATE: dict[str, Any] = {"resolved": False, "fn": None, "libc": None,
                                      "unavailable_reason": ""}


def parse_malloc_info_xml(xml_text: str, anon_mb: float | None = None) -> dict[str, Any] | None:
    """Reduce `malloc_info` XML to the numbers that decide the question.

    Pure and side-effect free ON PURPOSE: the libc call cannot be exercised off
    Linux, so this half is where the tests live. Everything below is parsing,
    and parsing is what silently returns a plausible wrong number.

    Reads the TOP-LEVEL totals -- the direct children of `<malloc>`, which
    aggregate every arena -- not the per-`<heap>` ones. They are the same tag
    names at both levels, so an `iter()` here would double count.
    """
    try:
        import xml.etree.ElementTree as ET

        root = ET.fromstring(xml_text)
    except Exception:
        return None
    if root.tag != "malloc":
        return None

    def top(tag: str, type_: str) -> int | None:
        for child in root:                     # direct children only
            if child.tag == tag and child.get("type") == type_:
                try:
                    return int(child.get("size") or 0)
                except (TypeError, ValueError):
                    return None
        return None

    system_current = top("system", "current")
    fast = top("total", "fast")
    rest = top("total", "rest")
    mmapped = top("total", "mmap")
    if system_current is None:
        return None

    # `fast` and `rest` are both FREE chunks the allocator is holding: fastbins
    # and everything else. Their sum is what a perfect `malloc_trim` could
    # theoretically reach; what it actually returns is bounded by whole pages.
    free_held = (fast or 0) + (rest or 0)
    out: dict[str, Any] = {
        "arenas": sum(1 for child in root if child.tag == "heap"),
        "system_current_mb": round(system_current / 1024 / 1024, 1),
        "free_held_mb": round(free_held / 1024 / 1024, 1),
        "in_use_mb": round(max(0, system_current - free_held) / 1024 / 1024, 1),
        "mmapped_mb": round((mmapped or 0) / 1024 / 1024, 1),
    }
    if system_current > 0:
        out["free_held_pct"] = round(100.0 * free_held / system_current, 1)
    # THE COVERAGE GUARD, AND WHY IT EXISTS. First production reading,
    # refresh-worker 2026-08-14 01:22:54Z:
    #
    #   system_current 215.1MB, free_held 60.9%  ->  printed "fragmentation"
    #   cgroup `anon` at the same instant         ->  ~1893MB
    #
    # The allocator accounted for 11% of the process's anonymous memory, and
    # the verdict described the fragmentation of that 11% as though it were a
    # statement about the whole. It is a correct number about the wrong
    # population -- the same shape as every other misread this codebase keeps
    # recording. Whatever holds the other ~1680MB is not a glibc arena
    # (`mmapped` was 0.7MB), so no arena metric can speak to it.
    #
    # So the verdict is now CONDITIONAL on the arena being representative.
    # `anon_mb` is optional because the parser stays pure and testable; when a
    # caller cannot supply it, say `coverage_unknown` rather than guess.
    if out.get("free_held_pct") is not None:
        coverage_pct = None
        if isinstance(anon_mb, (int, float)) and anon_mb > 0:
            coverage_pct = round(100.0 * out["system_current_mb"] / float(anon_mb), 1)
            out["arena_coverage_pct"] = coverage_pct
        if coverage_pct is None:
            out["reads_as"] = "coverage_unknown"
        elif coverage_pct < 50.0:
            # Below half, the arena simply is not where the memory lives, and
            # neither branch below can be concluded from it.
            out["reads_as"] = "arena_not_representative"
        else:
            out["reads_as"] = ("fragmentation" if out["free_held_pct"] >= 25.0
                           else "live_retention")
    return out


def _resolve_malloc_info() -> Any:
    """Bind `malloc_info` + `open_memstream`, once, or say why it could not.

    Returns None off glibc. Callers must treat None as "no reading available",
    never as an error -- every developer machine in this repo takes that branch.
    """
    if _MALLOC_INFO_STATE["resolved"]:
        return _MALLOC_INFO_STATE["fn"]
    _MALLOC_INFO_STATE["resolved"] = True
    if not sys.platform.startswith("linux"):
        _MALLOC_INFO_STATE["unavailable_reason"] = f"platform={sys.platform}"
    else:
        try:
            import ctypes
            import ctypes.util

            for candidate in ("libc.so.6", ctypes.util.find_library("c"), None):
                try:
                    libc = ctypes.CDLL(candidate, use_errno=True)
                except Exception:
                    continue
                info = getattr(libc, "malloc_info", None)
                memstream = getattr(libc, "open_memstream", None)
                if info is None or memstream is None:
                    continue
                info.argtypes = [ctypes.c_int, ctypes.c_void_p]
                info.restype = ctypes.c_int
                memstream.argtypes = [ctypes.POINTER(ctypes.c_char_p),
                                      ctypes.POINTER(ctypes.c_size_t)]
                memstream.restype = ctypes.c_void_p
                _MALLOC_INFO_STATE["fn"] = info
                _MALLOC_INFO_STATE["libc"] = libc   # keep the CDLL alive
                break
            else:
                _MALLOC_INFO_STATE["unavailable_reason"] = "symbol_not_found"
        except Exception as exc:
            _MALLOC_INFO_STATE["unavailable_reason"] = f"{type(exc).__name__}: {exc}"
    print(
        "[memory_observability] MALLOC_INFO_INIT "
        + json.dumps({"bound": _MALLOC_INFO_STATE["fn"] is not None,
                      "reason": _MALLOC_INFO_STATE["unavailable_reason"] or None},
                     sort_keys=True),
        flush=True,
    )
    return _MALLOC_INFO_STATE["fn"]


def malloc_arena_snapshot() -> dict[str, Any] | None:
    """One arena reading, or None where glibc is unavailable.

    Note the reading is very slightly self-perturbing: `open_memstream` and the
    XML buffer are themselves allocations. They are kilobytes against the
    hundreds of megabytes in question, and they inflate `free_held` rather than
    `in_use`, i.e. toward the fragmentation verdict. Worth knowing before a
    borderline call is read as decisive.
    """
    info = _resolve_malloc_info()
    if info is None:
        return None
    try:
        import ctypes

        libc = _MALLOC_INFO_STATE["libc"]
        buf = ctypes.c_char_p()
        size = ctypes.c_size_t()
        stream = libc.open_memstream(ctypes.byref(buf), ctypes.byref(size))
        if not stream:
            return None
        try:
            info(0, stream)
            libc.fflush(ctypes.c_void_p(stream))
            xml_text = ctypes.string_at(buf, size.value).decode("utf-8", "replace")
        finally:
            libc.fclose(ctypes.c_void_p(stream))
            if buf:
                libc.free(buf)
        # Pair the arena reading with the cgroup number it must be judged
        # against. Without this the verdict is computed over whatever slice of
        # memory glibc happens to own -- 11% of it, in the first production
        # reading.
        anon_mb = None
        stat = _read_container_memory_stat()
        if stat and isinstance(stat.get("anon"), int):
            anon_mb = stat["anon"] / 1024 / 1024
        return parse_malloc_info_xml(xml_text, anon_mb=anon_mb)
    except Exception as exc:
        print(f"[memory_observability] MALLOC_INFO_FAILED {type(exc).__name__}: {exc}",
              flush=True)
        return None


# --- `#423` step 2: allocation-site tracing ----------------------------------
#
# WHY THIS IS SAFE TO REACH FOR NOW, AND WAS NOT BEFORE. Two instruments failed
# this lane by being blind to the memory that matters: the gc census reported
# 143KB of a 546MB process (`gc.get_objects` never enumerates
# str/bytes/ndarray), and glibc's arenas hold 11-24% of `anon` while plateauing
# at ~393MB as `anon` climbs. `tracemalloc` was checked against BOTH before any
# of this was written -- local test, numpy float64 and python bytes both at
# exactly 100% traced-vs-RSS. It can see NumPy buffers. That is the whole
# reason this step exists.
#
# START POSITION IS LOAD-BEARING. `tracemalloc` only records allocations made
# AFTER it starts. Starting it at a periodic stage call would miss everything
# already resident and report a confident, tiny number -- the same failure mode
# as the gc census, arrived at differently. It must start at boot or not at all.
#
# DEFAULT OFF. It stores a traceback per live allocation on a process that
# reaches its 4GB ceiling hourly, and `#241` is on record as a worker whose
# periodic work caused a production restart loop. `nframe=1` keeps the per
# allocation cost to one frame; the snapshot itself is rate limited separately
# because `take_snapshot()` walks every traced block.
_TRACEMALLOC_STATE: dict[str, Any] = {"started": False, "reason": ""}


def allocation_tracing_enabled() -> bool:
    return str(os.environ.get("SYNDICATE_TRACEMALLOC_DIAG") or "").strip() in {"1", "true", "yes", "on"}


def start_allocation_tracing(nframe: int = 1) -> bool:
    """Begin tracing at boot, or say why not. Safe to call twice."""
    if _TRACEMALLOC_STATE["started"]:
        return True
    if not allocation_tracing_enabled():
        _TRACEMALLOC_STATE["reason"] = "disabled"
    else:
        try:
            import tracemalloc

            if not tracemalloc.is_tracing():
                tracemalloc.start(max(1, int(nframe)))
            _TRACEMALLOC_STATE["started"] = tracemalloc.is_tracing()
        except Exception as exc:
            _TRACEMALLOC_STATE["reason"] = f"{type(exc).__name__}: {exc}"
    print(
        "[memory_observability] TRACEMALLOC_INIT "
        + json.dumps({"started": _TRACEMALLOC_STATE["started"],
                      "nframe": nframe,
                      "reason": _TRACEMALLOC_STATE["reason"] or None}, sort_keys=True),
        flush=True,
    )
    return bool(_TRACEMALLOC_STATE["started"])


def allocation_snapshot(top_n: int = 8) -> dict[str, Any] | None:
    """Traced total against cgroup `anon`, plus the largest sites.

    The RATIO is the point, not the top list. Both directions of gap have
    benign readings and neither is automatically a defect -- see the lane:

      traced > anon   expected. Lazy zero pages: `np.zeros` reports its full
                      requested size while RSS has not moved. Measured locally
                      at +400MB traced against ~0 RSS.
      traced < anon   TWO causes, distinguish before concluding. Object boxing
                      under nframe=1 (measured: RSS +818.7MB, traced +230.2MB
                      for six million boxed ints), OR genuine blindness. Retry
                      with a larger nframe before calling it blindness.
    """
    if not _TRACEMALLOC_STATE["started"]:
        return None
    try:
        import tracemalloc

        if not tracemalloc.is_tracing():
            return None
        traced_bytes, peak_bytes = tracemalloc.get_traced_memory()
        out: dict[str, Any] = {
            "traced_mb": round(traced_bytes / 1024 / 1024, 1),
            "peak_mb": round(peak_bytes / 1024 / 1024, 1),
        }
        stat = _read_container_memory_stat()
        anon = stat.get("anon") if stat else None
        if isinstance(anon, int) and anon > 0:
            anon_mb = anon / 1024 / 1024
            out["anon_mb"] = round(anon_mb, 1)
            out["traced_pct_of_anon"] = round(100.0 * (traced_bytes / 1024 / 1024) / anon_mb, 1)
        snapshot = tracemalloc.take_snapshot().filter_traces((
            tracemalloc.Filter(False, tracemalloc.__file__),
            tracemalloc.Filter(False, __file__),
        ))
        sites = []
        for stat_row in snapshot.statistics("lineno")[:max(1, int(top_n))]:
            frame = stat_row.traceback[0] if stat_row.traceback else None
            sites.append({
                "site": f"{frame.filename.split('/')[-1]}:{frame.lineno}" if frame else "?",
                "mb": round(stat_row.size / 1024 / 1024, 1),
                "count": stat_row.count,
            })
        out["top"] = sites
        return out
    except Exception as exc:
        print(f"[memory_observability] TRACEMALLOC_SNAPSHOT_FAILED {type(exc).__name__}: {exc}", flush=True)
        return None

# ---------------------------------------------------------------------------
# `#632`. PER-REQUEST ANONYMOUS-MEMORY ATTRIBUTION, AND WHY IT REFUSES MOST ROWS
# ---------------------------------------------------------------------------
#
# What is established (`state.md [web-anon-leak]`): web's `memory_anon_mb` climbs
# to a peak of 1,823.8 MB of a 2,048 MB limit and NEVER falls except at a
# restart. It is real anonymous memory, not the page cache `#566` warns about.
# What is NOT established is WHAT allocates it -- and the cheap answer is already
# dead: a per-route correlation over 13 windows read +0.499 for
# `/api/ops/artifacts/stream` and collapsed to **+0.139** when one outlier window
# was removed, with no dose-response.
#
# THE CONSTRAINT THAT SHAPES THIS. Web runs ONE gunicorn worker with
# `GUNICORN_THREADS=4` (`render.yaml`), so up to four requests are in flight at
# once and a before/after delta around any one of them includes whatever the
# other three allocated. **A number attributed under concurrency is not a weak
# measurement, it is a wrong one**, and it would be wrong in the direction that
# blames whichever route is most frequent.
#
# So this attributes a delta ONLY when the request was provably ALONE for its
# entire life, and counts the rest as `skipped_concurrent`. On a busy service
# that refuses most rows. That is the design, not a shortfall: a smaller honest
# sample beats a larger one that launders concurrency into a route name.
#
# COST, AND WHY IT IS SAFE TO CARRY DISABLED. The whole recorder is behind
# `SYNDICATE_REQUEST_MEMORY_PROFILE`, DEFAULT OFF, because this service is
# already being OOM-killed and `#241` is the precedent for periodic work that
# was assumed free. When off, `note_request_start` returns `None` before
# touching the cgroup. When on, a SOLO request costs two `container_memory_stat`
# reads and a CONTENDED one costs zero -- the contention check happens first.

_REQUEST_MEMORY_LOCK: Any = None
_REQUEST_MEMORY_STATE: dict[str, Any] = {
    "inflight": 0,
    "seq": 0,
    "since_emit": 0,
    "routes": {},
    "skipped_concurrent": 0,
    "skipped_background": 0,
    "unreadable": 0,
}

# `#632`. THE LAST CONTAMINATION SOURCE: THIS PROCESS'S OWN BACKGROUND THREADS.
#
# `inflight` proves no other REQUEST overlapped a window. It says nothing about
# `syndicate/app.py`'s live-refresh and intelligence-state loops, which run in
# the SAME process and allocate and free on their own schedule. Measured
# 2026-09-04 with per-process attribution already in place, that residue was
# large enough to be the whole answer: one worker attributed **+395.8 MB against
# +225.9 MB of actual process growth (175%)** while the other read 37%, and a
# route went **-49.46 MB across 252 solo requests**. A negative retained total is
# not a small error, it is a different quantity.
#
# So background work gets the SAME treatment requests already get, for the same
# reason: a counter that must be zero at both ends, and a sequence that must not
# have moved in between. `seq` is what catches an iteration that started AND
# finished inside one request -- `inflight` alone would read 0 at both ends and
# call that window clean.
_BACKGROUND_MEMORY_STATE: dict[str, Any] = {"inflight": 0, "seq": 0}

# `#632`. IS THE GARBAGE COLLECTOR THE THIRD SOURCE? INSTRUMENTATION, NOT A GATE.
#
# Two explanations for the impossible attribution have now been eliminated by
# measurement rather than argument: cross-worker contamination (fixed by moving
# to per-process anon) and background loops (FALSIFIED -- neither loop runs on
# web; `SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP` and
# `SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP` are both false and web
# has logged zero loop lines).
#
# What remains is not concurrency at all. `note_request_start`/`end` DIFFERENCE
# the process's anon, and in a garbage-collected runtime that window contains
# whatever the collector happens to free -- garbage produced by REQUESTS THAT
# ENDED EARLIER. A request that triggers a gen-2 pass is charged a large negative
# it did not cause; one that runs while garbage accumulates is charged a positive
# that is really deferred cost. That is the exact observed signature: route
# totals going negative (-49.46 MB across 252 solo requests) and a solo-sample
# sum EXCEEDING total process growth (175%).
#
# THIS ONLY RECORDS. It splits the attributed deltas by whether a generation-2
# collection ran inside the window, and publishes both halves. If the negatives
# concentrate in the collected half, the collector is the source and a gate is
# justified; if they do not, this is cheap and I have not built the wrong thing
# twice. `gc.get_stats()` is a list of per-generation dicts and reading it is a
# few microseconds -- affordable on a request path, unlike anything that
# allocates.
_GC_SPLIT_STATE: dict[str, Any] = {
    "with_gc2_n": 0, "with_gc2_mb": 0.0,
    "no_gc2_n": 0, "no_gc2_mb": 0.0,
}


_GLOBAL_REASSIGN_STATE: dict[str, Any] = {}


def note_global_reassign(label: str, alloc_mb: float | None, free_mb: float | None) -> None:
    """Record what reassigning one long-lived global cost and refunded.

    `#632`. The negatives are NOT the garbage collector: measured 2026-09-04, the
    only gen-2-overlapping request read **+32.344 MB (positive)** while the
    non-overlapping group swung to **-30.108 MB**. CPython frees on refcount
    zero, with no collector involved -- so a statement that drops the last
    reference to a large object allocated by an EARLIER request refunds that
    memory inside the CURRENT request's window, and the instrument charges the
    refund to whoever happened to be running.

    `LAST_RESULT` is exactly that shape: a module-level global in
    `blueprints/intelligence.py`, reassigned on every query, holding a copy of
    the intelligence payload. Each query allocates a new one and frees the
    previous one in the same breath.

    ALLOC AND FREE ARE RECORDED SEPARATELY on purpose. If only the net were
    taken, a new value the same size as the old would read ~0 and the mechanism
    would be invisible -- which is precisely how it has stayed hidden through
    three rounds of this investigation.
    """
    row = _GLOBAL_REASSIGN_STATE.setdefault(
        str(label), {"n": 0, "alloc_mb": 0.0, "free_mb": 0.0,
                     "max_alloc_mb": 0.0, "max_free_mb": 0.0})
    row["n"] += 1
    if alloc_mb is not None:
        row["alloc_mb"] = round(row["alloc_mb"] + alloc_mb, 3)
        row["max_alloc_mb"] = round(max(row["max_alloc_mb"], alloc_mb), 3)
    if free_mb is not None:
        row["free_mb"] = round(row["free_mb"] + free_mb, 3)
        row["max_free_mb"] = round(min(row["max_free_mb"], free_mb), 3)


def measure_global_reassign(label: str):
    """Returns (probe, finish). Cheap enough for a request path: two
    `smaps_rollup` reads, no allocation. Returns (None, None) when the profile
    is off so callers pay nothing."""
    if not request_memory_profile_enabled():
        return None, None
    return _process_anon_mb(), label


def finish_global_reassign(before: float | None, label: str | None,
                           mid: float | None) -> None:
    """Close the pair opened by `measure_global_reassign`."""
    if before is None or label is None:
        return
    after = _process_anon_mb()
    alloc = (mid - before) if (mid is not None) else None
    free = (after - mid) if (mid is not None and after is not None) else None
    note_global_reassign(label, alloc, free)


def _gc_gen2_collections() -> int:
    """Cumulative generation-2 collection count, or -1 when unreadable."""
    try:
        stats = gc.get_stats()
        if isinstance(stats, list) and len(stats) >= 3:
            return int(stats[2].get("collections") or 0)
    except Exception:
        pass
    return -1


def _request_memory_lock() -> Any:
    global _REQUEST_MEMORY_LOCK
    if _REQUEST_MEMORY_LOCK is None:
        import threading

        _REQUEST_MEMORY_LOCK = threading.Lock()
    return _REQUEST_MEMORY_LOCK


def request_memory_profile_enabled() -> bool:
    """Default OFF. Absent means off, and so does any value that is not a
    recognised truthy token -- an unreadable setting must not switch on new
    per-request work on a 2GB service that is already dying."""
    raw = str(os.environ.get("SYNDICATE_REQUEST_MEMORY_PROFILE") or "").strip().lower()
    return raw in {"on", "1", "true", "yes"}


def note_background_work_start() -> None:
    """Mark the start of a background-loop iteration.

    Cheap enough to call unconditionally: two integer updates under a lock the
    request path already holds microseconds at a time, against loop iterations
    that are seconds apart. It is NOT gated on
    `request_memory_profile_enabled()` on purpose -- the flag can be turned on
    between a loop's start and its end, and a gated pair would then decrement a
    counter it never incremented and strand `inflight` at a negative value that
    `max(0, ...)` would silently absorb into "always contended".
    """
    with _request_memory_lock():
        _BACKGROUND_MEMORY_STATE["inflight"] += 1
        _BACKGROUND_MEMORY_STATE["seq"] += 1


def note_background_work_end() -> None:
    """Mark the end of a background-loop iteration. Always paired in a finally."""
    with _request_memory_lock():
        _BACKGROUND_MEMORY_STATE["inflight"] = max(
            0, int(_BACKGROUND_MEMORY_STATE["inflight"]) - 1)


@contextlib.contextmanager
def background_work():
    """Wrap a background-loop iteration so per-request attribution can exclude it.

    Wrap the WORKING part of an iteration and leave the sleep outside it: a loop
    that marked itself busy while sleeping would exclude every request on a
    service whose loops are mostly idle, and attribution would go to zero without
    saying so.
    """
    note_background_work_start()
    try:
        yield
    finally:
        note_background_work_end()


def _anon_mb() -> float | None:
    """Anonymous MB only. `memory_current_mb` includes page cache and reading it
    here would rebuild `#566`'s mistake one layer down."""
    stat = _read_container_memory_stat()
    if not stat or "anon" not in stat:
        return None
    return _bytes_to_mb(stat.get("anon"))


_PROCESS_ANON_UNAVAILABLE = False


def _process_anon_mb() -> float | None:
    """THIS PROCESS's anonymous memory, from `/proc/self/smaps_rollup`.

    WHY THIS EXISTS, measured 2026-09-03. `_anon_mb()` reads the CONTAINER
    cgroup, but `_REQUEST_MEMORY_STATE["inflight"]` is module state and therefore
    counts only requests in THIS gunicorn worker. At `WEB_CONCURRENCY=2` the
    guarantee and the measurement covered different scopes, so a request that was
    provably alone IN ITS OWN WORKER was still charged whatever the sibling
    worker and every merge subprocess allocated during its window.

    That is not a theoretical gap. It produced an attributed share of **61-150%**
    depending on framing -- and a share above 100% is arithmetically impossible
    for a true partition. Two direct sightings: a CUMULATIVE route total FELL
    (`/api/ops/artifacts/publish` 211.59 -> 167.13 MB while its own `solo_n` rose
    405 -> 502), and the two workers disagreed in SIGN on the same route one
    minute apart (+102.50 vs -64.35 MB).

    The obvious alternative was to run ONE worker so the cgroup matched the
    counter. That was tried and it **evicted the container in 22 minutes**
    (`server_failed`, `['evicted','unhealthy']`, 2026-09-03T23:37:08Z): one
    worker x 4 threads is 4 concurrent slots, and `/healthz` queued behind slow
    artifact requests. So the worker count is not available to us and the
    INSTRUMENT is what has to change.

    WHY `smaps_rollup` AND NOT `parse_smaps`. `parse_smaps` walks every mapping
    in `/proc/self/smaps`, which is fine for a periodic census and far too
    expensive on a per-request path. `smaps_rollup` is the kernel's own
    pre-aggregated version -- a handful of lines, one read -- and reports the
    SAME `Anonymous:` field, which is the accounting that decides an OOM kill.
    `Rss` is deliberately not used: it counts file-backed pages the cgroup files
    under `file`, and conflating the two is how a page-cache plateau once got
    called a leak (`#566`).

    Returns None when the file cannot be read, and the caller then declines to
    attribute rather than silently falling back to the container reading --
    falling back would quietly restore the very defect this removes.
    """
    global _PROCESS_ANON_UNAVAILABLE
    if _PROCESS_ANON_UNAVAILABLE:
        return None
    try:
        with open("/proc/self/smaps_rollup", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                if line.startswith("Anonymous:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        return float(parts[1]) / 1024.0        # kB -> MB
        return None
    except FileNotFoundError:
        # Pre-4.14 kernel or a platform without it. Say so ONCE and stop trying:
        # this runs per request and a missing file must not cost a syscall each
        # time. Attribution then reports every request as `unreadable`, which is
        # visible in the payload -- unlike a silent fallback.
        _PROCESS_ANON_UNAVAILABLE = True
        print("[memory_observability] SMAPS_ROLLUP_UNAVAILABLE -- per-request "
              "attribution disabled; it will not fall back to the container cgroup",
              flush=True)
        return None
    except Exception:
        return None


# `#632`: `pid` IS NOT A PROCESS IDENTITY. Measured 2026-09-04: pid 79's
# `solo_attributed` went 800 -> 200 at 19:55:32 because a gunicorn worker
# respawned and the OS reused the pid, and differencing across that boundary
# produced -117% coverage.
#
# DERIVED LAZILY, PER PID, and that is the whole design. The first attempt
# generated it at import -- and gunicorn FORKS ITS WORKERS AFTER THE IMPORT, so
# every worker inherited the identical token. Measured 2026-09-04 20:24-20:26:
# pid 99 and pid 98 emitted the SAME token `6178fc632433`, which merged two
# workers into one apparent series -- the exact defect the token was added to
# fix, made worse, because a shared token looks like continuity rather than
# like a collision.
#
# Re-deriving whenever `os.getpid()` changes covers both directions: a forked
# child sees the parent's recorded pid, disagrees, and mints its own; and a
# respawned worker that the OS gave a recycled pid gets a fresh token because
# its module state starts empty.
_PROC_TOKEN_STATE: dict[str, Any] = {"pid": None, "token": None}


def _proc_token() -> str:
    pid = os.getpid()
    if _PROC_TOKEN_STATE["pid"] != pid:
        _PROC_TOKEN_STATE.update({"pid": pid, "token": uuid.uuid4().hex[:12]})
    return str(_PROC_TOKEN_STATE["token"])

_PER_REQUEST_SMAPS_STATE: dict[str, Any] = {"count": 0, "routes": {}}
_PER_REQUEST_SMAPS_MAX_DEFAULT = 120


def _per_request_smaps_routes() -> frozenset[str]:
    """Which routes to sample. EMPTY BY DEFAULT, and that is the safety model.

    `#632`. The kernel walks page tables to answer smaps, so this cannot run on
    every request -- `#241` is the precedent for periodic work assumed free that
    put a production service into a restart loop. An explicit allowlist means
    the instrument is inert until someone names a route, and the blast radius is
    that route only.
    """
    raw_value = str(os.environ.get("SYNDICATE_SMAPS_PER_REQUEST_ROUTES") or "").strip()
    if not raw_value:
        return frozenset()
    return frozenset(part.strip() for part in raw_value.split(",") if part.strip())


def _per_request_smaps_budget() -> int:
    raw_value = str(os.environ.get("SYNDICATE_SMAPS_PER_REQUEST_SAMPLES") or "").strip()
    if not raw_value:
        return _PER_REQUEST_SMAPS_MAX_DEFAULT
    try:
        return int(raw_value)
    except ValueError:
        return _PER_REQUEST_SMAPS_MAX_DEFAULT


def _sample_request_buckets() -> tuple[dict[str, float], float] | None:
    """One size-bucket reading plus what it COST, in ms.

    The cost is returned rather than assumed. Every guess about the price of
    periodic work in this repo has been wrong in the expensive direction, so the
    instrument reports its own overhead and the ledger can carry a number.
    """
    try:
        path = _PROCFS_ROOT / "self" / "smaps"
        if not path.exists():
            return None
        started = time.perf_counter()
        parsed = parse_smaps(path.read_text(encoding="utf-8", errors="ignore"))
        elapsed_ms = (time.perf_counter() - started) * 1000.0
    except Exception:
        return None
    buckets = dict(parsed.get("anon_mmap_by_size_mb") or {})
    buckets["__total__"] = float(parsed.get("total_anon_mb") or 0.0)
    return buckets, elapsed_ms


def note_request_start(route: str | None = None) -> dict[str, Any] | None:
    """Call at request entry. Returns a token to hand back, or None.

    None means "do not attribute this request" -- either the profile is off, or
    another request was already in flight, or the cgroup could not be read."""
    if not request_memory_profile_enabled():
        return None
    with _request_memory_lock():
        state = _REQUEST_MEMORY_STATE
        solo = state["inflight"] == 0
        state["inflight"] += 1
        state["seq"] += 1
        seq = state["seq"]
        background_busy = _BACKGROUND_MEMORY_STATE["inflight"] != 0
        background_seq = _BACKGROUND_MEMORY_STATE["seq"]
        if not solo:
            state["skipped_concurrent"] += 1
            return None
        if background_busy:
            # A loop iteration is running right now; this window is its window too.
            state["skipped_background"] += 1
            return None
    before = _process_anon_mb()
    if before is None:
        with _request_memory_lock():
            _REQUEST_MEMORY_STATE["unreadable"] += 1
        return {"attribute": False, "seq": seq}
    token = {"attribute": True, "seq": seq, "anon_before_mb": before,
             "background_seq": background_seq, "gc2_before": _gc_gen2_collections()}
    # PER-REQUEST BUCKETS, only for an explicitly named route and only while
    # budget remains. `route` is passed in because the caller is the only layer
    # that knows it at ENTRY -- the attribution table learns it at teardown,
    # which is too late to decide whether to take a BEFORE reading.
    if route and route in _per_request_smaps_routes():
        if _PER_REQUEST_SMAPS_STATE["count"] < _per_request_smaps_budget():
            sampled = _sample_request_buckets()
            if sampled is not None:
                token["buckets_before"], token["sample_ms_before"] = sampled
                token["sampled_route"] = route
    return token


def note_request_end(token: dict[str, Any] | None, route: str,
                     emit_every: int = 200) -> dict[str, Any] | None:
    """Call at request teardown. Returns the summary payload when it emits one.

    The in-flight count is decremented even when the token says not to
    attribute, because a leaked counter would make every later request look
    contended and the instrument would go quietly blind."""
    if not request_memory_profile_enabled():
        return None
    with _request_memory_lock():
        state = _REQUEST_MEMORY_STATE
        state["inflight"] = max(0, state["inflight"] - 1)
        alone_throughout = (
            token is not None
            and bool(token.get("attribute"))
            and state["inflight"] == 0
            and state["seq"] == token.get("seq")
            # Both halves are needed. `inflight == 0` catches an iteration still
            # running; the `seq` comparison catches one that started AND finished
            # inside this request, which `inflight` alone reads as clean.
            and _BACKGROUND_MEMORY_STATE["inflight"] == 0
            and _BACKGROUND_MEMORY_STATE["seq"] == token.get("background_seq")
        )
        if token is not None and bool(token.get("attribute")) and not alone_throughout:
            if (_BACKGROUND_MEMORY_STATE["inflight"] != 0
                    or _BACKGROUND_MEMORY_STATE["seq"] != token.get("background_seq")):
                state["skipped_background"] += 1
    if token is None:
        return None
    if not alone_throughout:
        with _request_memory_lock():
            _REQUEST_MEMORY_STATE["skipped_concurrent"] += 1
        return None
    after = _process_anon_mb()
    if after is None:
        with _request_memory_lock():
            _REQUEST_MEMORY_STATE["unreadable"] += 1
        return None
    delta = after - float(token.get("anon_before_mb") or 0.0)
    # Split, do not exclude: the point is to find out whether the collector
    # explains the negatives, and excluding them would hide the evidence.
    gc2_before = token.get("gc2_before")
    gc2_after = _gc_gen2_collections()
    collected = (isinstance(gc2_before, int) and gc2_before >= 0
                 and gc2_after >= 0 and gc2_after > gc2_before)
    key = str(route or "unknown")
    # The AFTER sample, placed here deliberately: every early return above has
    # already fired, so a window that was not solo throughout, or whose anon was
    # unreadable, is DISCARDED by the code path rather than by a check I had to
    # remember to write. And outside `_request_memory_lock` -- this read walks
    # page tables and must never hold the lock every request takes twice.
    if token.get("buckets_before") is not None:
        try:
            _finish_per_request_smaps(token, key)
        except Exception:
            pass
    with _request_memory_lock():
        state = _REQUEST_MEMORY_STATE
        row = state["routes"].setdefault(key, {"solo_n": 0, "total_mb": 0.0, "max_mb": 0.0})
        row["solo_n"] += 1
        row["total_mb"] = round(row["total_mb"] + delta, 3)
        row["max_mb"] = round(max(row["max_mb"], delta), 3)
        # The UNTRUNCATED total. `routes` is capped at `top` for display, so
        # summing it under-reports whenever a process serves more distinct
        # routes than the cap -- pid 80 had `distinct_routes=13, len=12` and
        # differencing it read 4842% unexplained. Reconciliation must never
        # depend on a list that is truncated for readability.
        state["attributed_total_mb"] = round(
            float(state.get("attributed_total_mb") or 0.0) + delta, 3)
        if collected:
            _GC_SPLIT_STATE["with_gc2_n"] += 1
            _GC_SPLIT_STATE["with_gc2_mb"] = round(_GC_SPLIT_STATE["with_gc2_mb"] + delta, 3)
        else:
            _GC_SPLIT_STATE["no_gc2_n"] += 1
            _GC_SPLIT_STATE["no_gc2_mb"] = round(_GC_SPLIT_STATE["no_gc2_mb"] + delta, 3)
        state["since_emit"] += 1
        if state["since_emit"] < max(1, int(emit_every)):
            return None
        state["since_emit"] = 0
    # OUTSIDE the lock: this walks every arena and must not hold the lock that
    # every request takes at start and end.
    try:
        sample_arena_trend("attribution_emit")
    except Exception:
        pass
    try:
        sample_smaps_trend("attribution_emit")
    except Exception:
        pass
    with _request_memory_lock():
        payload = request_memory_attribution_payload()
    print(f"REQUEST_MEMORY_ATTRIBUTION {json.dumps(payload, default=str, sort_keys=True)}", flush=True)
    return payload


def _finish_per_request_smaps(token: dict[str, Any], route: str) -> None:
    """AFTER reading, delta per bucket, recorded against the route.

    Reports both the delta and the instrument's own cost. A sampled request that
    is not solo throughout is DISCARDED rather than recorded: another request
    overlapping the window makes the delta unattributable, and recording it
    anyway is how a number that means nothing enters a ledger.
    """
    before = token.get("buckets_before")
    if not isinstance(before, dict):
        return
    sampled = _sample_request_buckets()
    if sampled is None:
        return
    after, ms_after = sampled
    keys = set(before) | set(after)
    deltas = {k: round(after.get(k, 0.0) - before.get(k, 0.0), 3) for k in keys}
    entry = _PER_REQUEST_SMAPS_STATE["routes"].setdefault(
        route, {"n": 0, "sum_8_64mb": 0.0, "max_8_64mb": 0.0,
                "sum_total_mb": 0.0, "sum_ms": 0.0})
    entry["n"] += 1
    big = float(deltas.get("8-64MB", 0.0))
    entry["sum_8_64mb"] = round(entry["sum_8_64mb"] + big, 3)
    entry["max_8_64mb"] = round(max(entry["max_8_64mb"], big), 3)
    entry["sum_total_mb"] = round(entry["sum_total_mb"] + float(deltas.get("__total__", 0.0)), 3)
    entry["sum_ms"] = round(entry["sum_ms"] + float(token.get("sample_ms_before") or 0.0) + ms_after, 2)
    _PER_REQUEST_SMAPS_STATE["count"] += 1
    print(
        "PER_REQUEST_SMAPS " + json.dumps({
            "route": route[:80],
            "pid": os.getpid(),
            "d_8_64mb": big,
            "d_total_mb": deltas.get("__total__", 0.0),
            "d_1_8mb": deltas.get("1-8MB", 0.0),
            "sample_ms": round(float(token.get("sample_ms_before") or 0.0) + ms_after, 2),
            "index": _PER_REQUEST_SMAPS_STATE["count"],
        }, sort_keys=True),
        flush=True,
    )


def request_memory_attribution_payload(top: int = 12) -> dict[str, Any]:
    """The accumulated attribution, ranked by TOTAL retained MB.

    Ranked on the total rather than the mean because the question is which route
    accounts for the most unreturned memory over a shift, not which single call
    is fattest -- a rare huge allocation that is freed is not this defect."""
    state = _REQUEST_MEMORY_STATE
    rows = sorted(state["routes"].items(), key=lambda kv: -kv[1]["total_mb"])[: max(1, int(top))]
    return {
        # `anon_mb_now` KEEPS ITS MEANING (the container cgroup) so emissions
        # recorded before this change stay comparable. What changed is what
        # `total_mb` is a delta OF, and that is stated outright rather than left
        # for a reader to infer: `attribution_basis` distinguishes the two
        # regimes in the log, where nothing else would.
        "attribution_basis": "process_anon_smaps_rollup",
        # Reconciliation triple: differencing these two across a window, on ONE
        # `proc_token`, gives attributed vs the process's own climb -- and the
        # RESIDUAL, which is the number that was never recoverable before.
        "attributed_total_mb": round(float(_REQUEST_MEMORY_STATE.get("attributed_total_mb") or 0.0), 3),
        "proc_token": _proc_token(),
        # WHICH WORKER. `#632`: gunicorn runs 2 workers and both emit into one
        # log stream, so a series read without this is TWO interleaved series.
        # Measured 2026-09-04: five consecutive emissions alternated between
        # processes, and only luck put the same worker at both ends of the
        # comparison. This is the same cross-worker error that the per-process
        # anon fix already corrected once at the cgroup level -- it came back
        # one level up, at the TIME SERIES, and a bucket value that happens to
        # differ per worker is an inference, not an identifier.
        "pid": os.getpid(),
        "anon_mb_now": _anon_mb(),
        "process_anon_mb_now": _process_anon_mb(),
        "routes": [dict(route=r, **vals) for r, vals in rows],
        "distinct_routes": len(state["routes"]),
        "skipped_concurrent": state["skipped_concurrent"],
        # Requests declined because a background loop iteration overlapped them.
        # Published beside `skipped_concurrent` so a reader can see how much of
        # the traffic each exclusion is responsible for -- a top-routes table
        # with no denominator invites treating the solo sample as the whole
        # service, and there are now two ways to leave it.
        "skipped_background": state["skipped_background"],
        # `#632`: the attributed deltas split by whether a gen-2 collection ran
        # inside the window. If `with_gc2_mb` is strongly negative while
        # `no_gc2_mb` is positive, the collector is the third source.
        "gc2_split": dict(_GC_SPLIT_STATE),
        "gc2_collections_total": _gc_gen2_collections(),
        # `#632`: arenas held from the OS vs bytes actually live in them. The
        # difference is fragmentation -- memory no free() can return.
        "arena_trend": dict(_ARENA_TREND_STATE.get("last") or {}),
        "arena_trend_samples": _ARENA_TREND_STATE["count"],
        # `#632`: anon by mapping SIZE. The only view that can see a large direct
        # mmap, which is where the growth has to be if pymalloc cannot see it.
        # Per-request sampling on named routes. `{}` unless a route allowlist
        # is set, which is the default.
        "per_request_smaps": {
            k: dict(v) for k, v in (_PER_REQUEST_SMAPS_STATE["routes"] or {}).items()
        },
        "per_request_smaps_samples": _PER_REQUEST_SMAPS_STATE["count"],
        "smaps_trend": dict(_SMAPS_TREND_STATE.get("last") or {}),
        "smaps_trend_samples": _SMAPS_TREND_STATE["count"],
        # `#632`: what reassigning long-lived globals allocated and refunded.
        # A large `free_mb` here means the negatives belong to a PREVIOUS
        # request's object being released inside this one's window.
        "global_reassign": {k: dict(v) for k, v in _GLOBAL_REASSIGN_STATE.items()},
        "unreadable": state["unreadable"],
        # A reader must be able to see how much of the traffic this DECLINED to
        # attribute. A top-routes table with no denominator invites treating the
        # solo sample as the whole service.
        "solo_attributed": sum(v["solo_n"] for v in state["routes"].values()),
    }


def reset_request_memory_attribution() -> None:
    """Tests only. Module-level accumulators otherwise leak across cases and the
    second test reads the first one's numbers."""
    _REQUEST_MEMORY_STATE.update(
        {"inflight": 0, "seq": 0, "since_emit": 0, "routes": {},
         "skipped_concurrent": 0, "skipped_background": 0, "unreadable": 0}
    )
    _BACKGROUND_MEMORY_STATE.update({"inflight": 0, "seq": 0})
    _GC_SPLIT_STATE.update({"with_gc2_n": 0, "with_gc2_mb": 0.0,
                            "no_gc2_n": 0, "no_gc2_mb": 0.0})
    _GLOBAL_REASSIGN_STATE.clear()
    _PER_REQUEST_SMAPS_STATE.update({"count": 0, "routes": {}})
    _REQUEST_MEMORY_STATE["attributed_total_mb"] = 0.0
    _ARENA_TREND_STATE.update({"count": 0, "last": None})
    _SMAPS_TREND_STATE.update({"count": 0, "last": None})
