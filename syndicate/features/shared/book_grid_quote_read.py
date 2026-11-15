"""The book-grid build's quote read, INCREMENTAL: each build parses only the lines appended since the last one.

WHY (todo #790, lane nba-grid-per-build-lookups, 2026-11-15). `book_quotes/<date>.jsonl` is the day's CHANGE LOG
and the grid build re-read all of it, from the first line, on every build: `freshest_rows_for_grid` over
`iter_book_quotes`. That cost grows all day, fastest while games are live. Measured on the fleet:

    NCAAF 11-14   shard 300k -> 776k lines through the evening   build 8.1 s -> 30.3 s   grid flat at ~5,000 rows
    end of day    NCAAF 352 MB  parse+reduce 12.1 s   NBA 168 MB 5.8 s   NCAAB 69 MB 1.8 s   NHL 50 MB 1.6 s

So a build's cost tracked the LOG, not the grid, and most of it re-decided lines earlier builds had already decided.

WHAT IS KEPT BETWEEN BUILDS, AND WHAT IS NOT. Per shard: the byte offset read up to, a `FreshestRowsReducer` (keys
and indices only), and the byte span of every row. NOT the parsed rows: NCAAF's 124,344 kept rows are 322 MB parsed
(tracemalloc on the fleet, 2026-11-15), against refresh-worker's 3.4 GB RSS under a 7,168 MB cap. A build parses the
appended lines, decides them, and re-parses only the KEPT lines from their spans -- so no parsed row outlives a
build, and nothing a build does to its rows can leak into the next one.

THE CONTRACT IS `freshest_rows_for_grid`'s, EXACTLY. Same rows, same order (FILE ORDER is part of it -- see that
function's docstring for the 2,006 permuted and 972 re-anchored rows two earlier reductions produced at identical
byte length), same raw row count. Lines are split the way a text-mode read splits them (universal newlines), decoded
strictly as UTF-8, stripped, and parsed the same way. The one deliberate difference: a trailing line with no newline
yet (a writer mid-append) is left for the next build, where a one-pass read would count it as a bad line now and as
a good row next time.

WHEN IT STARTS OVER FROM BYTE 0. The file was replaced (inode -- the sanitize pass and a whole-file pull both
`os.replace`), shrank, or its first or last-read bytes changed. A `.gz` shard (compacted, so closed) takes the
one-pass read. So does any build when `SYNDICATE_BOOK_GRID_INCREMENTAL_READ` is 0/false/off/no, and every build in
a process after a check failed.

THE CHECK. Every `SYNDICATE_BOOK_GRID_INCREMENTAL_VERIFY_SECONDS` (default 1800; 0 = every build) per shard, the
build also runs the one-pass reference over the same bytes and compares row for row. A mismatch is printed, the
reference rows serve that build, and the incremental read is OFF for the rest of the process -- a reducer that
diverged once has no claim to be trusted between checks.

Every build prints one `BOOK_GRID_QUOTE_READ` line (mode, new lines, kept rows, seconds), because a read that
silently fell back to the full path would look exactly like one that never shipped.
"""

from __future__ import annotations

import io
import json
import mmap
import os
import re
import threading
import time
from array import array
from collections.abc import Iterator
from pathlib import Path
from typing import Any, BinaryIO

from syndicate.features.shared.book_grid import FreshestRowsReducer, freshest_rows_for_grid
from syndicate.features.shared.odds_book_quotes import (
    _report_bad_lines,
    iter_book_quotes,
    resolve_book_quotes_path,
)

ENABLED_ENV = "SYNDICATE_BOOK_GRID_INCREMENTAL_READ"
VERIFY_SECONDS_ENV = "SYNDICATE_BOOK_GRID_INCREMENTAL_VERIFY_SECONDS"
DEFAULT_VERIFY_SECONDS = 1800.0
# Shards a process keeps state for. One per (sport, date) the round builds; the background drain adds other dates.
MAX_ENTRIES = 24
# A date the round stopped building (yesterday, after rollover) is dropped after this long unread.
IDLE_EVICT_SECONDS = 6 * 3600.0
_GUARD_BYTES = 256
_CHUNK_BYTES = 8 * 1024 * 1024
# Universal newlines, as a text-mode read splits: "\r\n", then a lone "\r", then "\n".
_UNIVERSAL_LINE = re.compile(rb"([^\r\n]*)(?:\r\n|\r|\n)")
_OFF_VALUES = {"0", "false", "off", "no"}


def incremental_read_enabled() -> bool:
    """On unless the env says 0/false/off/no. ABSENT IS ON: the read is proven identical to the one-pass read."""
    return str(os.environ.get(ENABLED_ENV) or "").strip().lower() not in _OFF_VALUES


def _verify_seconds() -> float:
    raw = str(os.environ.get(VERIFY_SECONDS_ENV) or "").strip()
    try:
        return max(0.0, float(raw)) if raw else DEFAULT_VERIFY_SECONDS
    except ValueError:
        return DEFAULT_VERIFY_SECONDS


class _ShardState:
    """What one shard's reads carry from build to build. Byte spans and keys, never parsed rows."""

    __slots__ = ("path", "identity", "offset", "head", "tail", "reducer", "starts", "lengths", "lines", "bad",
                 "verified_at", "last_used")

    def __init__(self, path: str, identity: tuple[int, int], now: float) -> None:
        self.path = path
        self.identity = identity
        self.offset = 0  # bytes decided: always just past a line terminator
        self.head = b""  # the shard's first bytes, up to _GUARD_BYTES
        self.tail = b""  # the bytes just before `offset`, up to _GUARD_BYTES
        self.reducer = FreshestRowsReducer(intern_keys=True)
        self.starts = array("q")  # row index -> byte offset of its line
        self.lengths = array("q")  # row index -> byte length of its line, terminator excluded
        self.lines = 0  # non-blank lines, as `iter_book_quotes` counts them
        self.bad = 0  # lines that were not a JSON object
        self.verified_at = now
        self.last_used = now

    @property
    def rows(self) -> int:
        return len(self.starts)


_STATES: dict[str, _ShardState] = {}
_LOCK = threading.Lock()
_DISABLED: str | None = None  # set once a check fails; the process then reads every shard one-pass


def reset_state() -> None:
    """Forget every shard's state and re-enable the read. For tests, and for nothing in production."""
    global _DISABLED
    with _LOCK:
        _STATES.clear()
        _DISABLED = None


def _drop(key: str) -> None:
    _STATES.pop(key, None)


def _log(sport: str, date_str: str, **fields: Any) -> None:
    # print, not logger.info: logger.info never reached the role logs (CLAUDE.md).
    body = " ".join(f"{name}={value}" for name, value in fields.items())
    print(f"[book_grid] BOOK_GRID_QUOTE_READ sport={sport} date={date_str} {body}", flush=True)


def _one_pass(sport: str, date_str: str, *, reason: str) -> tuple[list[dict[str, Any]], int]:
    """The reference read: every line of the shard, one pass. What every build did before #790's change."""
    started = time.monotonic()
    count = 0

    def _counted() -> Iterator[dict[str, Any]]:
        nonlocal count
        for row in iter_book_quotes(sport, date_str):
            count += 1
            yield row

    rows = freshest_rows_for_grid(_counted())
    _log(sport, date_str, mode=f"full:{reason}", rows=count, kept=len(rows),
         read_s=f"{time.monotonic() - started:.3f}", entries=len(_STATES))
    return rows, count


def read_grid_quote_rows(sport: str, date_str: str) -> tuple[list[dict[str, Any]], int]:
    """(rows, raw row count): what `freshest_rows_for_grid(iter_book_quotes(sport, date_str))` returns, and how many
    rows it saw -- reading only what was appended since this process last read the shard."""
    path = resolve_book_quotes_path(sport, date_str)
    if path.suffix == ".gz":
        # Compacted, so closed: nothing will be appended. Forget the plain file's state with it.
        with _LOCK:
            _drop(str(path.with_suffix("")))
        return _one_pass(sport, date_str, reason="gz")
    key = str(path)
    if not incremental_read_enabled():
        with _LOCK:
            _drop(key)
        return _one_pass(sport, date_str, reason="env_off")
    if _DISABLED is not None:
        return _one_pass(sport, date_str, reason="disabled_after_mismatch")
    if not path.is_file():
        with _LOCK:
            _drop(key)
        return [], 0
    try:
        with _LOCK:
            return _incremental(sport, date_str, path)
    except Exception as exc:  # noqa: BLE001 -- the one-pass read below raises again for a genuine read error
        with _LOCK:
            _drop(key)
        print(f"[book_grid] BOOK_GRID_QUOTE_READ_ERROR sport={sport} date={date_str} "
              f"{type(exc).__name__}: {exc}", flush=True)
        return _one_pass(sport, date_str, reason="error")


def _stale_reason(state: _ShardState, handle: BinaryIO, identity: tuple[int, int], size: int) -> str | None:
    """Why the kept state can no longer describe this file's first `state.offset` bytes, or None."""
    if identity != state.identity:
        return "replaced"
    if size < state.offset:
        return "shrunk"
    handle.seek(0)
    if handle.read(len(state.head)) != state.head:
        return "head_changed"
    handle.seek(state.offset - len(state.tail))
    if handle.read(len(state.tail)) != state.tail:
        return "tail_changed"
    return None


def _incremental(sport: str, date_str: str, path: Path) -> tuple[list[dict[str, Any]], int]:
    started = time.monotonic()
    key = str(path)
    with open(path, "rb") as handle:
        stat = os.fstat(handle.fileno())
        identity = (int(stat.st_dev), int(stat.st_ino))
        state = _STATES.get(key)
        reason = "new" if state is None else _stale_reason(state, handle, identity, int(stat.st_size))
        if reason is not None:
            state = _ShardState(key, identity, started)
            _STATES[key] = state
        rows_before, offset_before = state.rows, state.offset
        _consume(state, handle)
        read_done = time.monotonic()
        rows = _reparse_kept(state, handle)
        reparse_done = time.monotonic()
        verify = "-"
        verify_s = 0.0
        count = state.rows
        if reparse_done - state.verified_at >= _verify_seconds():
            verify, rows, count = _verify(sport, date_str, state, handle, rows)
            verify_s = time.monotonic() - reparse_done
    state.last_used = time.monotonic()
    _report_bad_lines(path, state.bad, state.lines)
    state.reducer.report()
    _evict(state.last_used)
    _log(sport, date_str, mode="incremental" if reason is None else f"fresh:{reason}",
         new_rows=state.rows - rows_before, new_bytes=state.offset - offset_before, rows=state.rows,
         kept=len(rows), read_s=f"{read_done - started:.3f}", reparse_s=f"{reparse_done - read_done:.3f}",
         verify=verify, verify_s=f"{verify_s:.3f}", entries=len(_STATES))
    return rows, count


def _lines(buf: bytes, end: int) -> Iterator[tuple[int, bytes]]:
    """(offset in `buf`, content) of each line in `buf[:end]`, terminator excluded, split as a text-mode read
    splits. `buf[end - 1]` is a newline, so every line here is complete."""
    if buf.find(b"\r", 0, end) < 0:
        position = 0
        for content in buf[:end].split(b"\n")[:-1]:
            yield position, content
            position += len(content) + 1
        return
    for match in _UNIVERSAL_LINE.finditer(buf, 0, end):
        yield match.start(1), match.group(1)


def _consume(state: _ShardState, handle: BinaryIO) -> None:
    """Decide every complete line after `state.offset`, in file order, and move the offset past the last one."""
    reducer = state.reducer
    starts, lengths = state.starts, state.lengths
    loads = json.loads
    handle.seek(state.offset)
    base = state.offset  # file offset of buf[0]
    buf = b""
    while True:
        block = handle.read(_CHUNK_BYTES)
        if not block:
            break
        buf = buf + block if buf else block
        end = buf.rfind(b"\n") + 1
        if end <= 0:
            continue  # no complete line yet: keep reading
        for position, content in _lines(buf, end):
            # Exactly `iter_book_quotes`' per-line steps: strict UTF-8, strip, skip blank, count, parse.
            line = content.decode("utf-8").strip()
            if not line:
                continue
            state.lines += 1
            try:
                row = loads(line)
            except Exception:  # noqa: BLE001 -- same as the one-pass read: a bad line is counted, not raised
                state.bad += 1
                continue
            if not isinstance(row, dict):
                state.bad += 1
                continue
            index = len(starts)
            starts.append(base + position)
            lengths.append(len(content))
            reducer.add(index, row)
        base += end
        buf = buf[end:]
    # `base` is now just past the last complete line; whatever is left in `buf` is a line still being written.
    if base != state.offset:
        state.offset = base
        handle.seek(0)
        state.head = handle.read(min(_GUARD_BYTES, base))
        guard = min(_GUARD_BYTES, base)
        handle.seek(base - guard)
        state.tail = handle.read(guard)


def _reparse_kept(state: _ShardState, handle: BinaryIO) -> list[dict[str, Any]]:
    """The kept rows, parsed from their own bytes, in file order."""
    kept = state.reducer.kept_indices()
    if not kept:
        return []
    starts, lengths = state.starts, state.lengths
    loads = json.loads
    with mmap.mmap(handle.fileno(), state.offset, access=mmap.ACCESS_READ) as view:
        return [loads(view[starts[i]:starts[i] + lengths[i]].decode("utf-8").strip()) for i in kept]


class _Prefix(io.RawIOBase):
    """The first `limit` bytes of an open binary handle, as a raw stream. Closing it leaves the handle open."""

    def __init__(self, handle: BinaryIO, limit: int) -> None:
        super().__init__()
        handle.seek(0)
        self._handle = handle
        self._left = limit

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Any) -> int:
        if self._left <= 0:
            return 0
        data = self._handle.read(min(len(buffer), self._left))
        buffer[: len(data)] = data
        self._left -= len(data)
        return len(data)


def _reference_rows(handle: BinaryIO, limit: int, counts: dict[str, int]) -> Iterator[dict[str, Any]]:
    """`iter_book_quotes`' loop, line for line, over the first `limit` bytes: a text-mode read, not this module's
    splitter, so the check tests the splitter too."""
    text = io.TextIOWrapper(io.BufferedReader(_Prefix(handle, limit), buffer_size=1 << 20), encoding="utf-8")
    for line in text:
        line = line.strip()
        if not line:
            continue
        counts["lines"] += 1
        try:
            parsed = json.loads(line)
        except Exception:  # noqa: BLE001
            counts["bad"] += 1
            continue
        if isinstance(parsed, dict):
            counts["rows"] += 1
            yield parsed
        else:
            counts["bad"] += 1


def _verify(sport: str, date_str: str, state: _ShardState, handle: BinaryIO,
            rows: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]], int]:
    """Run the one-pass reference over the same bytes and compare. Returns (result, rows to serve, their raw count)."""
    global _DISABLED
    counts = {"lines": 0, "bad": 0, "rows": 0}
    reference = freshest_rows_for_grid(_reference_rows(handle, state.offset, counts), report=False)
    state.verified_at = time.monotonic()
    same = (reference == rows and counts["rows"] == state.rows
            and counts["lines"] == state.lines and counts["bad"] == state.bad)
    if same:
        return "match", rows, state.rows
    first = next((i for i, (a, b) in enumerate(zip(reference, rows)) if a != b), min(len(reference), len(rows)))
    _DISABLED = f"{sport}/{date_str}"
    _STATES.clear()
    print(
        f"[book_grid] BOOK_GRID_QUOTE_READ_VERIFY sport={sport} date={date_str} result=MISMATCH "
        f"kept_incremental={len(rows)} kept_reference={len(reference)} first_difference={first} "
        f"rows_incremental={state.rows} rows_reference={counts['rows']} "
        f"lines_incremental={state.lines} lines_reference={counts['lines']} "
        f"bad_incremental={state.bad} bad_reference={counts['bad']} action=incremental_read_off_for_process",
        flush=True,
    )
    return "MISMATCH", reference, counts["rows"]


def _evict(now: float) -> None:
    for key in [k for k, s in _STATES.items() if now - s.last_used > IDLE_EVICT_SECONDS]:
        print(f"[book_grid] BOOK_GRID_QUOTE_READ_EVICT path={key} reason=idle", flush=True)
        _drop(key)
    while len(_STATES) > MAX_ENTRIES:
        key = min(_STATES, key=lambda k: _STATES[k].last_used)
        print(f"[book_grid] BOOK_GRID_QUOTE_READ_EVICT path={key} reason=count", flush=True)
        _drop(key)
