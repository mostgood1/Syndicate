"""One-shot, verified compaction of a worker's persistent disk.

Lane `refresh-worker-disk-inventory`, 2026-09-13. refresh-worker's 48.91 GB disk
was measured at **0.0 MB available** (`DISK_INVENTORY_SUMMARY`, 13:44:21Z), so
every book grid build and every pull from web failed and the board froze. The
user approved exactly three actions -- "Remove verified duplicates", "Gzip
props-history CSVs", "Stop history re-append" -- and this module is the first
two. The third lives in `odds_refresh_tracking._persist_tracking_snapshot`.

WHAT IT TOUCHES, and only this:

1. ORPHAN TEMP FILES older than an hour: the leftovers of atomic writes
   (`*.pull.tmp`, `*.stream.tmp`, `*.tmp`) that failed on the full disk. The
   inventory counted 23 files, 40.3 MB. They are never read: a temp file is
   either renamed over its target or it is garbage.

2. PLAIN `book_quotes` SHARDS THAT ALREADY HAVE A VERIFIED `.gz` TWIN.
   `mlb_source/tracking/book_quotes/<date>.jsonl` held 3.15 GB in 30 files while
   the daily compaction reported `already_compressed: 30`. The reader
   (`odds_book_quotes.resolve_book_quotes_path`) prefers the plain file and falls
   back to `.gz`, so removing a plain shard whose `.gz` holds the SAME NUMBER OF
   LINES loses nothing. A plain shard with MORE lines than its `.gz` (appended
   after compression) is KEPT and reported -- deleting it would lose the tail.

3. CLOSED `odds_*_history_<date>.csv` FILES, gzipped in place.
   `_persist_tracking_snapshot` appends the full snapshot to these on every
   refresh; nothing reads them (no reader in `syndicate/`, `pipeline/` or
   `scripts/`; `mirror_manifest.py:163-195`); they are EXPORT-ONLY, so this disk
   holds the ONLY copy. Gzip keeps every byte. Each file is written to
   `<name>.gz.tmp`, read back and line-counted against the original, renamed,
   and only then is the original removed -- the same contract as
   `compress_closed_shards`, because a copy that half-worked and then deleted its
   input would be indistinguishable from a capture outage weeks later.

ORDER IS LOAD-BEARING: (1) and (2) free space WITHOUT writing anything, and on a
disk at 0 bytes free nothing else can run first. (3) writes a compressed copy
before it removes an original, so it runs only while free space covers that
copy plus a margin, oldest file first, one at a time.

COST: once per process, in its own daemon thread, never on the main loop; reads
are streamed in 8 MiB chunks (zlib releases the GIL while it works). Default ON
only for `SYNDICATE_DISK_COMPACTION_SERVICES` (default `refresh-worker`);
`SYNDICATE_DISK_COMPACTION=0` disables it anywhere, `=1` forces it.
`SYNDICATE_DISK_COMPACTION_DRY_RUN=1` reports without changing anything.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import threading
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

_CHUNK_BYTES = 8 * 1024 * 1024
_STATE: dict[str, Any] = {"started": False, "thread": None}

_TEMP_NAME = re.compile(r"(\.pull\.tmp|\.stream\.tmp|\.tmp)$", re.IGNORECASE)
_TEMP_MIN_AGE_SECONDS = 3600.0

_HISTORY_CSV = re.compile(r"^odds_[a-z0-9_]+_history_(\d{4}-\d{2}-\d{2})\.csv$")
_SHARD_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})\.jsonl$")

# The compressed copy of a CSV is written before the original is removed. Size
# the guard for the worst plausible ratio rather than the measured one, so a
# badly-compressing file cannot fill the disk it is meant to relieve.
_ASSUMED_WORST_RATIO = 0.35
_FREE_MARGIN_BYTES = 256 * 1024 * 1024

Printer = Callable[..., Any]


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def disk_compaction_wanted(service_slug: str) -> bool:
    raw = os.environ.get("SYNDICATE_DISK_COMPACTION")
    if raw is not None and raw.strip() != "":
        return _truthy(raw)
    # The default path DELETES and rewrites files, so it needs Render's own marker as
    # well as the service name: tests/test_disk_maintenance.py sets
    # SYNDICATE_REFRESH_LANE=refresh-worker and calls run_disk_maintenance for real,
    # which without this started compaction against a developer's local data/.
    if not _truthy(os.environ.get("RENDER") or ""):
        return False
    services = os.environ.get("SYNDICATE_DISK_COMPACTION_SERVICES") or "refresh-worker"
    wanted = {part.strip().lower() for part in services.split(",") if part.strip()}
    return str(service_slug or "").strip().lower() in wanted


def _dry_run() -> bool:
    return _truthy(os.environ.get("SYNDICATE_DISK_COMPACTION_DRY_RUN") or "")


def _free_bytes(root: Path) -> int | None:
    try:
        st = os.statvfs(root)
        return int(st.f_bavail * st.f_frsize)
    except (AttributeError, OSError):
        return None


def _count_lines(path: Path, *, compressed: bool | None = None) -> int:
    """Newline count of the DECOMPRESSED content.

    `compressed` is explicit for the verify step: the freshly written copy is
    named `<name>.gz.tmp`, and inferring "compressed" from a `.gz` suffix there
    counts newlines in the raw gzip bytes -- a mismatch every time, so every file
    was kept and nothing was ever compacted (caught by
    `test_closed_history_csv_gzipped_and_original_removed`).
    """
    if compressed is None:
        compressed = path.name.endswith(".gz")
    opener = gzip.open if compressed else open
    lines = 0
    with opener(path, "rb") as handle:
        while True:
            chunk = handle.read(_CHUNK_BYTES)
            if not chunk:
                break
            lines += chunk.count(b"\n")
    return lines


def _log(printer: Printer, action: str, **fields: Any) -> None:
    printer(f"DISK_COMPACTION_FILE {json.dumps({'action': action, **fields}, sort_keys=True, default=str)}", flush=True)


def remove_orphan_temp_files(root: Path, *, apply: bool, now: float | None = None, printer: Printer = print) -> dict[str, Any]:
    now = time.time() if now is None else now
    result = {"removed": 0, "bytes": 0, "kept_recent": 0, "errors": 0}
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if not _TEMP_NAME.search(name):
                continue
            path = Path(dirpath) / name
            try:
                info = path.stat()
            except OSError:
                result["errors"] += 1
                continue
            if (now - info.st_mtime) < _TEMP_MIN_AGE_SECONDS:
                result["kept_recent"] += 1
                continue
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            if apply:
                try:
                    path.unlink()
                except OSError as exc:
                    result["errors"] += 1
                    _log(printer, "temp_remove_failed", path=rel, error=f"{type(exc).__name__}: {exc}")
                    continue
            result["removed"] += 1
            result["bytes"] += int(info.st_size)
            _log(printer, "temp_removed" if apply else "temp_would_remove", path=rel, bytes=int(info.st_size))
    return result


def remove_verified_shard_duplicates(root: Path, *, today: date, apply: bool, printer: Printer = print, min_age_days: int = 2) -> dict[str, Any]:
    result = {"removed": 0, "bytes": 0, "kept_mismatch": 0, "kept_recent": 0, "no_twin": 0, "errors": 0}
    for sport_dir in sorted(root.glob("*_source")):
        shard_dir = sport_dir / "tracking" / "book_quotes"
        if not shard_dir.is_dir():
            continue
        for path in sorted(shard_dir.glob("*.jsonl")):
            match = _SHARD_NAME.match(path.name)
            if not match:
                continue
            try:
                shard_date = date.fromisoformat(match.group(1))
            except ValueError:
                continue
            if (today - shard_date).days < min_age_days:
                result["kept_recent"] += 1
                continue
            twin = path.with_name(path.name + ".gz")
            if not twin.is_file():
                result["no_twin"] += 1
                continue
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            try:
                plain_lines = _count_lines(path)
                packed_lines = _count_lines(twin)
                size = int(path.stat().st_size)
            except (OSError, EOFError, gzip.BadGzipFile) as exc:
                result["errors"] += 1
                _log(printer, "shard_verify_failed", path=rel, error=f"{type(exc).__name__}: {exc}")
                continue
            if plain_lines != packed_lines:
                result["kept_mismatch"] += 1
                _log(printer, "shard_kept_line_mismatch", path=rel, plain_lines=plain_lines, gz_lines=packed_lines)
                continue
            if apply:
                try:
                    path.unlink()
                except OSError as exc:
                    result["errors"] += 1
                    _log(printer, "shard_remove_failed", path=rel, error=f"{type(exc).__name__}: {exc}")
                    continue
            result["removed"] += 1
            result["bytes"] += size
            _log(printer, "shard_duplicate_removed" if apply else "shard_duplicate_would_remove", path=rel, bytes=size, lines=plain_lines)
    return result


def gzip_closed_history_csvs(
    root: Path,
    *,
    today: date,
    apply: bool,
    printer: Printer = print,
    min_age_days: int = 2,
    free_bytes: Callable[[Path], int | None] = _free_bytes,
) -> dict[str, Any]:
    result = {"compressed": 0, "bytes_before": 0, "bytes_after": 0, "kept_recent": 0,
              "skipped_low_space": 0, "verify_failed": 0, "errors": 0}
    candidates: list[tuple[date, Path]] = []
    for sport_dir in sorted(root.glob("*_source")):
        tracking = sport_dir / "tracking"
        if not tracking.is_dir():
            continue
        for path in tracking.glob("odds_*_history_*.csv"):
            match = _HISTORY_CSV.match(path.name)
            if not match:
                continue
            try:
                file_date = date.fromisoformat(match.group(1))
            except ValueError:
                continue
            if (today - file_date).days < min_age_days:
                result["kept_recent"] += 1
                continue
            candidates.append((file_date, path))

    for _file_date, path in sorted(candidates):
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        packed = path.with_name(path.name + ".gz")
        tmp = packed.with_name(packed.name + ".tmp")
        try:
            size = int(path.stat().st_size)
        except OSError:
            result["errors"] += 1
            continue

        if packed.is_file():
            # A previous pass wrote and renamed the .gz but did not remove the
            # original. Same rule as the shards: remove only on equal line count.
            try:
                same = _count_lines(path) == _count_lines(packed)
            except (OSError, EOFError, gzip.BadGzipFile) as exc:
                result["errors"] += 1
                _log(printer, "csv_verify_failed", path=rel, error=f"{type(exc).__name__}: {exc}")
                continue
            if not same:
                result["verify_failed"] += 1
                _log(printer, "csv_kept_existing_gz_mismatch", path=rel)
                continue
            if apply:
                path.unlink()
            result["compressed"] += 1
            result["bytes_before"] += size
            result["bytes_after"] += int(packed.stat().st_size)
            _log(printer, "csv_original_removed_existing_gz" if apply else "csv_would_remove_existing_gz", path=rel, bytes=size)
            continue

        needed = int(size * _ASSUMED_WORST_RATIO) + _FREE_MARGIN_BYTES
        available = free_bytes(path.parent)
        if available is not None and available < needed:
            result["skipped_low_space"] += 1
            _log(printer, "csv_skipped_low_space", path=rel, bytes=size, free_bytes=available, needed_bytes=needed)
            continue

        if not apply:
            result["compressed"] += 1
            result["bytes_before"] += size
            _log(printer, "csv_would_gzip", path=rel, bytes=size)
            continue

        try:
            source_lines = 0
            with path.open("rb") as src, gzip.open(tmp, "wb", compresslevel=6) as dst:
                while True:
                    chunk = src.read(_CHUNK_BYTES)
                    if not chunk:
                        break
                    source_lines += chunk.count(b"\n")
                    dst.write(chunk)
            packed_lines = _count_lines(tmp, compressed=True)
            if packed_lines != source_lines:
                tmp.unlink(missing_ok=True)
                result["verify_failed"] += 1
                _log(printer, "csv_verify_mismatch_original_kept", path=rel, source_lines=source_lines, gz_lines=packed_lines)
                continue
            os.replace(tmp, packed)
            after = int(packed.stat().st_size)
            path.unlink()
        except Exception as exc:  # disk full mid-write, permission, anything: keep the original
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            result["errors"] += 1
            _log(printer, "csv_gzip_failed_original_kept", path=rel, error=f"{type(exc).__name__}: {exc}")
            continue
        result["compressed"] += 1
        result["bytes_before"] += size
        result["bytes_after"] += after
        _log(printer, "csv_gzipped", path=rel, bytes_before=size, bytes_after=after, lines=source_lines)
    return result


def run_disk_compaction(root: str | os.PathLike[str], *, today: date | None = None, apply: bool | None = None, printer: Printer = print) -> dict[str, Any]:
    root_path = Path(root)
    today = today or date.today()
    apply = (not _dry_run()) if apply is None else apply
    started = time.monotonic()
    summary: dict[str, Any] = {"root": str(root_path), "apply": apply, "today": today.isoformat(),
                               "free_bytes_before": _free_bytes(root_path)}
    printer(f"DISK_COMPACTION_STARTED {json.dumps(summary, sort_keys=True, default=str)}", flush=True)
    for name, step in (
        ("temp_files", lambda: remove_orphan_temp_files(root_path, apply=apply, printer=printer)),
        ("shard_duplicates", lambda: remove_verified_shard_duplicates(root_path, today=today, apply=apply, printer=printer)),
        ("history_csvs", lambda: gzip_closed_history_csvs(root_path, today=today, apply=apply, printer=printer)),
    ):
        try:
            summary[name] = step()
        except Exception as exc:  # one step failing must not stop the next
            summary[name] = {"error": f"{type(exc).__name__}: {exc}"}
        summary[f"free_bytes_after_{name}"] = _free_bytes(root_path)
    summary["seconds"] = round(time.monotonic() - started, 1)
    printer(f"DISK_COMPACTION {json.dumps(summary, sort_keys=True, default=str)}", flush=True)
    return summary


def start_disk_compaction_once(root: str | os.PathLike[str], service_slug: str, **kwargs: Any) -> bool:
    """Start the one-shot compaction thread for this process. Never raises."""
    try:
        if _STATE["started"]:
            return False
        if not disk_compaction_wanted(service_slug):
            return False
        _STATE["started"] = True

        def _run() -> None:
            try:
                from syndicate.features.shared.timezone import central_today

                run_disk_compaction(root, today=central_today(), **kwargs)
            except Exception as exc:  # pragma: no cover
                print(f"DISK_COMPACTION_FAILED {type(exc).__name__}: {exc}", flush=True)

        thread = threading.Thread(target=_run, name="disk-compaction", daemon=True)
        _STATE["thread"] = thread
        thread.start()
        return True
    except Exception as exc:  # pragma: no cover
        print(f"DISK_COMPACTION_START_FAILED {type(exc).__name__}: {exc}", flush=True)
        return False
