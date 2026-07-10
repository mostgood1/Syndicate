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


def log_process_tree_memory(stage: str, **extra: Any) -> dict[str, Any]:
    payload = {"stage": str(stage or "").strip() or "unknown"}
    payload.update(extra)
    payload.update(get_process_tree_memory_snapshot())
    print(f"PROCESS_TREE_MEMORY {json.dumps(payload, default=str, sort_keys=True)}", file=sys.stderr, flush=True)
    return payload


def log_container_memory(stage: str, **extra: Any) -> dict[str, Any]:
    memory_current_bytes = _read_container_memory_current_bytes()
    payload = {
        "stage": str(stage or "").strip() or "unknown",
        "memory_current_mb": _bytes_to_mb(memory_current_bytes),
    }
    payload.update(extra)
    print(f"CONTAINER_MEMORY {json.dumps(payload, default=str, sort_keys=True)}", file=sys.stderr, flush=True)
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
