from __future__ import annotations

import json
import os
import sys
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
    payload.update(extra)
    print(f"CONTAINER_MEMORY {json.dumps(payload, default=str, sort_keys=True)}", file=sys.stderr, flush=True)
    return payload


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


def log_runtime_memory(stage: str, **extra: Any) -> None:
    log_process_tree_memory(stage, **extra)
    log_container_memory(stage, **extra)


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
