from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

try:
    import psutil
except Exception:  # pragma: no cover - psutil is optional in some local environments
    psutil = None


_BYTES_PER_MB = 1024 * 1024
_BYTES_PER_KB = 1024
_PROCFS_ROOT = Path("/proc")


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
    # Only inactive_file and slab_reclaimable are treated as available.
    # active_file is reclaimable too but under more pressure, and shmem is not
    # reclaimable at all, so both stay counted as used -- this is deliberately
    # the conservative reading of "reclaimable", not the largest one.
    stat = _read_container_memory_stat()
    reclaimable_bytes = 0
    if stat:
        reclaimable_bytes = max(0, stat.get("inactive_file", 0) + stat.get("slab_reclaimable", 0))
    effective_headroom_bytes = raw_headroom_bytes + reclaimable_bytes

    snapshot: dict[str, Any] = {
        "current_mb": round(current_bytes / 1024 / 1024, 1),
        "max_mb": round(max_bytes / 1024 / 1024, 1),
        "headroom_mb": round(effective_headroom_bytes / 1024 / 1024, 1),
        "min_required_mb": round(min_required / 1024 / 1024, 1),
        "sufficient": effective_headroom_bytes >= min_required,
    }
    if stat:
        # Kept so a future reader can see both numbers rather than having to
        # rediscover why they differ -- and so that if the gap ever stops
        # being file cache, that is visible in the same line.
        snapshot["stat_mb"] = {key: round(value / 1024 / 1024, 1) for key, value in sorted(stat.items())}
        snapshot["reclaimable_file_mb"] = round(reclaimable_bytes / 1024 / 1024, 1)
        snapshot["headroom_including_file_cache_mb"] = round(raw_headroom_bytes / 1024 / 1024, 1)
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
        reclaimable_bytes = max(0, stat.get("inactive_file", 0) + stat.get("slab_reclaimable", 0))
        payload["memory_anon_mb"] = _bytes_to_mb(stat.get("anon")) if "anon" in stat else None
        payload["memory_inactive_file_mb"] = _bytes_to_mb(stat.get("inactive_file")) if "inactive_file" in stat else None
        payload["memory_reclaimable_mb"] = _bytes_to_mb(reclaimable_bytes)
        if isinstance(memory_current_bytes, int):
            unreclaimable_bytes = max(0, memory_current_bytes - reclaimable_bytes)
            payload["memory_unreclaimable_mb"] = _bytes_to_mb(unreclaimable_bytes)
            if isinstance(memory_max_bytes, int) and memory_max_bytes > 0:
                payload["memory_unreclaimable_pct_of_max"] = round(100.0 * unreclaimable_bytes / memory_max_bytes, 1)
    payload.update(extra)
    print(f"CONTAINER_MEMORY {json.dumps(payload, default=str, sort_keys=True)}", file=sys.stderr, flush=True)
    return payload


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
