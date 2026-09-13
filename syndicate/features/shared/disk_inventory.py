"""Read-only inventory of a worker's persistent disk. Deletes nothing, writes nothing.

Lane `refresh-worker-disk-inventory`, 2026-09-13. refresh-worker's 50 GB disk
filled around 07:00Z (`OSError: [Errno 28] No space left on device`, 3,905 lines
since 09-12 23:39Z), so every book grid build and every pull from web failed and
the board froze on pre-07:00Z data. `artifact_retention.py` had forecast "fills
around late September 2026" on 08-12; retention never ran, and the only
compaction (`compress_closed_shards`) touches one closed `book_quotes` shard per
sport per day.

NOTHING ON THE PLATFORM COULD SAY WHAT WAS ON THE DISK. Render gives no shell to
a worker (no SSH key on the account, TCP 22 blocked), the disk attaches to one
service only, and web cannot read it. So the only instrument that can see the
disk is code running on the worker that owns it. This is that instrument, and
nothing more: it measures so that compaction and retention can be chosen from
numbers rather than guessed.

COST DISCIPLINE, because periodic work on this box is never free (`#241`, and
`disk_maintenance.py`'s own note on the retention rglob that stalled the main
poll loop for 10+ minutes):
  - Runs ONCE per process, in its own daemon thread, never on the main loop.
  - `os.scandir` + `lstat` only; no file is opened, so no file contents enter
    the page cache.
  - Bounded by entry count and wall time; yields the GIL every few thousand
    entries.
  - Default ON only for the services named in `SYNDICATE_DISK_INVENTORY_SERVICES`
    (default `refresh-worker`). live-odds-worker's 2 GiB container is not
    walked unless asked for.
  - `SYNDICATE_DISK_INVENTORY=0` disables it anywhere; `=1` forces it anywhere.

The output is a handful of `DISK_INVENTORY_*` lines printed with `flush=True`
(`logger.info` does not reach Render's log collector from a worker).
"""

from __future__ import annotations

import heapq
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

_STATE: dict[str, Any] = {"started": False, "thread": None}

# Orphans of atomic writes: `write_json_file`/`_pull_hot_artifacts_request` write
# `<name>.<pid>.<uuid>.pull.tmp` (or `.tmp`) and `os.replace` it; a write that
# fails partway on a full disk can leave one behind.
_TEMP_NAME = re.compile(r"(\.tmp|\.partial|\.part)$|\.tmp\.[0-9a-f]{6,}$", re.IGNORECASE)
_TEMP_MIN_AGE_SECONDS = 600.0

_DATE_IN_NAME = re.compile(r"(20\d\d)[-_](\d\d)[-_](\d\d)")
_TEXT_SUFFIXES = (".json", ".jsonl", ".csv", ".txt", ".ndjson")
_COMPRESSED_SUFFIXES = (".gz", ".zst", ".bz2", ".xz", ".zip")

_MAX_FAMILIES = 20000
_MAX_DIRS_TRACKED = 50000


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def disk_inventory_wanted(service_slug: str) -> bool:
    """Should this process walk its disk? Explicit env wins; default is by service name."""
    raw = os.environ.get("SYNDICATE_DISK_INVENTORY")
    if raw is not None and raw.strip() != "":
        return _truthy(raw)
    services = os.environ.get("SYNDICATE_DISK_INVENTORY_SERVICES") or "refresh-worker"
    wanted = {part.strip().lower() for part in services.split(",") if part.strip()}
    return str(service_slug or "").strip().lower() in wanted


def _suffix_key(name: str) -> str:
    lower = name.lower()
    for comp in _COMPRESSED_SUFFIXES:
        if lower.endswith(comp):
            inner = os.path.splitext(lower[: -len(comp)])[1]
            return (inner + comp) if inner else comp
    ext = os.path.splitext(lower)[1]
    return ext or "<none>"


def _family_key(relative: str) -> str:
    """A dated file's family: its path with the date replaced, e.g.
    `soccer_source/tracking/book_quotes/<date>.jsonl`."""
    return _DATE_IN_NAME.sub("<date>", relative)


def _file_date_age_days(name: str, now: float) -> float | None:
    match = _DATE_IN_NAME.search(name)
    if not match:
        return None
    try:
        from datetime import datetime, timezone

        stamp = datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)), tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None
    return (now - stamp) / 86400.0


def build_disk_inventory(
    root: str | os.PathLike[str],
    *,
    top_n: int = 40,
    max_entries: int = 3_000_000,
    time_budget_seconds: float = 1200.0,
    yield_every: int = 2000,
    max_depth: int = 3,
    compactable_min_age_days: float = 2.0,
    now: float | None = None,
) -> dict[str, Any]:
    """Walk `root` without opening any file. Returns aggregates only."""
    started = time.monotonic()
    now = time.time() if now is None else now
    root_path = Path(root)
    report: dict[str, Any] = {"root": str(root_path), "truncated": False, "errors": 0}

    try:
        st = os.statvfs(root_path)
        report["filesystem"] = {
            "total_bytes": st.f_blocks * st.f_frsize,
            "free_bytes": st.f_bfree * st.f_frsize,
            "available_bytes": st.f_bavail * st.f_frsize,
            "used_bytes": (st.f_blocks - st.f_bfree) * st.f_frsize,
            "inodes_total": st.f_files,
            "inodes_free": st.f_ffree,
        }
    except (AttributeError, OSError) as exc:
        report["filesystem"] = {"unavailable": f"{type(exc).__name__}: {exc}"}

    dir_bytes: dict[int, dict[str, list[int]]] = {depth: {} for depth in range(1, max_depth + 1)}
    by_ext: dict[str, list[int]] = {}
    families: dict[str, list[int]] = {}
    largest: list[tuple[int, str]] = []
    temp_orphans: list[tuple[int, str]] = []
    temp_count = 0
    temp_bytes = 0
    age_buckets = {"lt_1d": 0, "1_7d": 0, "7_30d": 0, "gt_30d": 0}
    files = 0
    dirs = 0
    total_bytes = 0
    entries = 0

    stack: list[Path] = [root_path]
    while stack:
        current = stack.pop()
        try:
            iterator = os.scandir(current)
        except OSError:
            report["errors"] += 1
            continue
        with iterator:
            for entry in iterator:
                entries += 1
                if entries % yield_every == 0:
                    time.sleep(0.001)
                    if entries >= max_entries or (time.monotonic() - started) > time_budget_seconds:
                        report["truncated"] = True
                        stack.clear()
                        break
                try:
                    if entry.is_dir(follow_symlinks=False):
                        dirs += 1
                        stack.append(Path(entry.path))
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    info = entry.stat(follow_symlinks=False)
                except OSError:
                    report["errors"] += 1
                    continue
                size = int(info.st_size)
                files += 1
                total_bytes += size
                try:
                    relative = os.path.relpath(entry.path, root_path).replace(os.sep, "/")
                except ValueError:
                    relative = entry.name
                parts = relative.split("/")

                for depth in range(1, max_depth + 1):
                    if len(parts) <= depth:
                        break
                    key = "/".join(parts[:depth])
                    bucket = dir_bytes[depth]
                    slot = bucket.get(key)
                    if slot is None:
                        if len(bucket) >= _MAX_DIRS_TRACKED:
                            continue
                        slot = bucket[key] = [0, 0]
                    slot[0] += size
                    slot[1] += 1

                ext = _suffix_key(entry.name)
                slot = by_ext.setdefault(ext, [0, 0])
                slot[0] += size
                slot[1] += 1

                if len(largest) < top_n:
                    heapq.heappush(largest, (size, relative))
                elif size > largest[0][0]:
                    heapq.heapreplace(largest, (size, relative))

                age_days = (now - float(info.st_mtime)) / 86400.0
                if age_days < 1:
                    age_buckets["lt_1d"] += size
                elif age_days < 7:
                    age_buckets["1_7d"] += size
                elif age_days < 30:
                    age_buckets["7_30d"] += size
                else:
                    age_buckets["gt_30d"] += size

                if _TEMP_NAME.search(entry.name) and (now - float(info.st_mtime)) > _TEMP_MIN_AGE_SECONDS:
                    temp_count += 1
                    temp_bytes += size
                    if len(temp_orphans) < top_n:
                        heapq.heappush(temp_orphans, (size, relative))
                    elif size > temp_orphans[0][0]:
                        heapq.heapreplace(temp_orphans, (size, relative))

                lower = entry.name.lower()
                if lower.endswith(_TEXT_SUFFIXES):
                    file_age = _file_date_age_days(entry.name, now)
                    if file_age is not None and file_age >= compactable_min_age_days:
                        family = _family_key(relative)
                        slot = families.get(family)
                        if slot is None:
                            if len(families) >= _MAX_FAMILIES:
                                continue
                            slot = families[family] = [0, 0]
                        slot[0] += size
                        slot[1] += 1

    def _top(mapping: dict[str, list[int]]) -> list[dict[str, Any]]:
        ranked = sorted(mapping.items(), key=lambda kv: -kv[1][0])[:top_n]
        return [{"path": key, "bytes": value[0], "files": value[1]} for key, value in ranked]

    report.update(
        {
            "seconds": round(time.monotonic() - started, 1),
            "entries": entries,
            "files": files,
            "dirs": dirs,
            "bytes": total_bytes,
            "top_dirs": {str(depth): _top(dir_bytes[depth]) for depth in dir_bytes},
            "largest_files": [{"path": path, "bytes": size} for size, path in sorted(largest, reverse=True)],
            "by_extension": _top(by_ext),
            "age_bytes": age_buckets,
            "temp_orphans": {
                "count": temp_count,
                "bytes": temp_bytes,
                "largest": [{"path": path, "bytes": size} for size, path in sorted(temp_orphans, reverse=True)],
            },
            "compactable_text_families": _top(families),
        }
    )
    return report


_MAX_LINE_CHARS = 7000


def emit_disk_inventory(report: dict[str, Any], *, printer=print) -> int:
    """Print the report as several bounded `DISK_INVENTORY_*` lines. Returns the line count."""
    lines = 0
    summary = {key: report.get(key) for key in (
        "root", "filesystem", "seconds", "entries", "files", "dirs", "bytes", "truncated", "errors", "age_bytes")}
    summary["temp_orphans"] = {k: (report.get("temp_orphans") or {}).get(k) for k in ("count", "bytes")}
    printer(f"DISK_INVENTORY_SUMMARY {json.dumps(summary, sort_keys=True, default=str)}", flush=True)
    lines += 1

    def _chunked(tag: str, rows: list[Any], extra: dict[str, Any] | None = None) -> None:
        nonlocal lines
        chunk: list[Any] = []
        part = 0
        for row in rows:
            candidate = chunk + [row]
            text = json.dumps({**(extra or {}), "part": part, "rows": candidate}, sort_keys=True, default=str)
            if chunk and len(text) > _MAX_LINE_CHARS:
                printer(f"{tag} {json.dumps({**(extra or {}), 'part': part, 'rows': chunk}, sort_keys=True, default=str)}", flush=True)
                lines += 1
                part += 1
                chunk = [row]
            else:
                chunk = candidate
        if chunk:
            printer(f"{tag} {json.dumps({**(extra or {}), 'part': part, 'rows': chunk}, sort_keys=True, default=str)}", flush=True)
            lines += 1

    for depth, rows in (report.get("top_dirs") or {}).items():
        _chunked("DISK_INVENTORY_DIRS", rows, {"depth": int(depth)})
    _chunked("DISK_INVENTORY_FILES", report.get("largest_files") or [])
    _chunked("DISK_INVENTORY_EXT", report.get("by_extension") or [])
    _chunked("DISK_INVENTORY_COMPACTABLE", report.get("compactable_text_families") or [])
    _chunked("DISK_INVENTORY_TEMP", (report.get("temp_orphans") or {}).get("largest") or [])
    printer("DISK_INVENTORY_END", flush=True)
    return lines + 1


def start_disk_inventory_once(root: str | os.PathLike[str], service_slug: str, **kwargs: Any) -> bool:
    """Start the one-shot inventory thread for this process. Never raises.

    Returns True only when this call started it.
    """
    try:
        if _STATE["started"]:
            return False
        if not disk_inventory_wanted(service_slug):
            return False
        _STATE["started"] = True

        def _run() -> None:
            try:
                print(f"DISK_INVENTORY_STARTED root={root} service={service_slug}", flush=True)
                report = build_disk_inventory(root, **kwargs)
                emit_disk_inventory(report)
            except Exception as exc:  # pragma: no cover - an instrument must never raise
                print(f"DISK_INVENTORY_FAILED {type(exc).__name__}: {exc}", flush=True)

        thread = threading.Thread(target=_run, name="disk-inventory", daemon=True)
        _STATE["thread"] = thread
        thread.start()
        return True
    except Exception as exc:  # pragma: no cover
        print(f"DISK_INVENTORY_START_FAILED {type(exc).__name__}: {exc}", flush=True)
        return False
