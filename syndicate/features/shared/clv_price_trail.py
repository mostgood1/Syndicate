"""Per-build price observations for the rows the Layer 2 board published.

WHY THIS EXISTS (lane `layer2-row-parity`, 2026-09-15). The board's movement
cell compares a row against ONE number, the price we first published it at
(`clv_opening_ledger`). Two points cannot show a path, and the sparklines that
did render came from a different pipeline entirely -- the legacy candidates'
fuzzy odds-history join -- measured the same day on the served board to be:

    wrong side    MLB "Under 8.5" / "Under 8.0" rows plotted the OVER price
    wrong game    6 of 14 soccer rows plotted a different fixture
    wrong line    6 of 58 series spanned a line change, drawn as a price move
    no book       one price per side, from whichever book the snapshot met first

This records what the Layer 2 board ITSELF saw, for the exact bets it
published, at each build: the line, and the best price with its book.

THE LINE DRAWS THE LABEL'S OWN PRICE (user decision 2026-09-15, "Plot the
label's price from our open"). The first version plotted the no-vig fair
probability from the first trail point, and on the served board 18:08:02Z 45 of
94 series sloped against their own arrow: every series started after the row's
opening (a different WINDOW), and in 31 of 35 fair-basis disagreements the price
the label states would have matched (a different QUANTITY). So `price_move_series`
now starts at our published price and ends at the price the label shows, with
trail points between: arrow, label, colour and line agree by construction.

THE SAME IDENTITY AS MOVEMENT. Keyed by `layer2_board.movement_join_key`
(event, market, player, segment, side -- no line, no book) and filtered by line
when read, so a line move ends a series rather than being drawn as a price move.

BOUNDED THREE WAYS, because periodic worker work is never free on refresh-worker:
a point is appended only when the line, price or book changed; the in-memory
index keeps the first point plus the latest `_MAX_POINTS_PER_KEY - 1` per key; and
the file stops growing at `_MAX_TRAIL_BYTES`. Files older than `_RETAIN_DAYS` are
removed on write.

NOT PUBLISHED TO WEB. The series rides on the persisted board cards, which web
already reads, so this file never needs to leave the worker's disk.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date as _date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from syndicate.features.shared.opportunity_signals import implied_probability

TRAIL_SUBDIR = "clv_price_trail"

# A tripwire, not a budget: a day of change-only points is a few MB. A dedupe
# failure must cost one truncated file, not a disk.
_MAX_TRAIL_BYTES = 48_000_000
_MAX_POINTS_PER_KEY = 48
_SERIES_MAX_POINTS = 12
_RETAIN_DAYS = 4
# Matches BOTH the legacy whole-day file and an hourly chunk, so pruning and
# loading keep working across the format change in either direction.
_DATE_FILE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:T\d{2})?\.jsonl$")

# ---------------------------------------------------------------------------
# HOURLY CHUNKS, AND WHY THE WHOLE-DAY FILE COULD NOT REACH WEB
# (lane `layer2-line-movement-scoring`, 2026-09-20)
# ---------------------------------------------------------------------------
# This file is written on refresh-worker and read, for analysis, from web. It
# never arrived, and allowlisting it in `HOT_ARTIFACT_PATTERNS` was necessary
# and NOT sufficient. Two independent reasons, both measured:
#
#   1. NOTHING PUSHES IT. `clv_opening_ledger` calls `publish_hot_artifact`
#      itself (`:369-371`); this module had no such call. The generic
#      `sweep_changed_hot_artifacts` does cover the allowlist, but it does not
#      run in refresh-worker's MAIN LOOP -- only from spawned jobs
#      (`run_queued_refresh_job.py`, `run_mlb_daily_sim_job.py`), which run
#      intermittently. Measured on refresh-worker 2026-09-20 16:30Z+:
#      `PUBLISH_OK 339` (per-path direct publishes) against `publishedArtifacts
#      0` and `PUBLISH_SKIPPED_UNCHANGED 0` (the sweep's own counters), while
#      `[clv_price_trail] TRAIL` lines were writing throughout.
#
#   2. IT WOULD BE TOO BIG WHEN ONE DID RUN. The sweep obeys
#      `_PUBLISH_MAX_BYTES` (12 MiB) via `_publish_skip_reason`, whose only
#      exemption is `_FAILED_DIRECT_PUBLISH` -- populated solely by a FAILED
#      DIRECT publish. With no direct call this file could never be exempt, so
#      above the ceiling it is skipped SILENTLY, leaving web a copy truncated
#      in time: the morning without the evening, which looks complete.
#
# WHY NOT SIMPLY COPY `clv_openings` AND ADD A DIRECT CALL. Openings publishes
# `if written` and is FIRST-SIGHTING-ONLY, so it writes often early in the day
# and rarely later; its own comment already says re-pushing *an unchanged ~90KB
# file* every ~20 min is worker work that "is never free on a 4GB container".
# This trail appends whenever an observation CHANGED, which on a live board is
# most rows on most builds, ALL DAY (measured 17:14:36Z: `rows_in=4956
# written=1182 unchanged=3774 keys=6405`). The same pattern would push a file
# growing toward 15-30 MB on ~100+ builds a day, against OPEN lane
# `bandwidth-controlled-transfer` and its spike tripwire.
#
# SO: SEAL AND PUSH ONCE. Points go to the CURRENT hour's chunk; a chunk whose
# hour has passed can never change again, so it is published EXACTLY ONCE and
# never re-pushed. Total outbound becomes the day's SIZE instead of
# builds x size -- roughly 1/100th -- and no chunk approaches 12 MiB, so the
# ceiling stops being reachable rather than being worked around.
#
# The lag this buys is bounded by one hour and is the right trade: the consumer
# is a CLV decomposition harness reading finished history, not the board.
_MAX_CHUNK_BYTES = 8 * 1024 * 1024
_CHUNK_FILE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2})\.jsonl$")
#: Chunks this PROCESS has already pushed. A restart may re-push each sealed
#: chunk once, which is bounded at 24 and vastly cheaper than the per-build
#: re-push this design exists to avoid. Deliberately not persisted: a stale
#: on-disk marker that suppresses a needed publish is the worse failure.
_PUBLISHED_CHUNKS: set[str] = set()


def _reports_root() -> Path:
    from syndicate.features.shared.refresh_state_store import reports_root

    return reports_root()


def price_trail_path(date: str, *, root: Path | str | None = None) -> Path:
    """The LEGACY whole-day path. Still read; no longer written.

    Kept because files written before 2026-09-20 use it and must keep loading,
    and because `_prune_old_files` has to reach them.
    """
    base = Path(root) if root is not None else _reports_root()
    return base / "intelligence" / TRAIL_SUBDIR / f"{str(date).strip()}.jsonl"


def price_trail_dir(date: str, *, root: Path | str | None = None) -> Path:
    return price_trail_path(date, root=root).parent


def price_trail_chunk_path(date: str, hour: int, *, root: Path | str | None = None) -> Path:
    """The hour's chunk: `<date>T<hh>.jsonl`. See the block above `_MAX_CHUNK_BYTES`."""
    return price_trail_dir(date, root=root) / f"{str(date).strip()}T{int(hour):02d}.jsonl"


def price_trail_files(date: str, *, root: Path | str | None = None) -> list[Path]:
    """Every file holding this date's trail, legacy and chunked, in time order.

    Sorting by NAME is sorting by time here: `2026-09-20.jsonl` precedes
    `2026-09-20T00.jsonl`, and the chunks are zero-padded. The legacy file
    coming first is correct -- it is the older format, so its points are older.
    """
    directory = price_trail_dir(date, root=root)
    stamp = str(date).strip()
    try:
        entries = [
            entry
            for entry in directory.iterdir()
            if entry.is_file() and _DATE_FILE_RE.match(entry.name) and entry.name.startswith(stamp)
        ]
    except OSError:
        return []
    return sorted(entries, key=lambda item: item.name)


def price_trail_enabled() -> bool:
    """On unless `SYNDICATE_CLV_PRICE_TRAIL` is explicitly off.

    Absent means ON, deliberately: this is display enrichment with its own size
    tripwire, and the off switch exists so it can be removed without a deploy.
    """
    raw = str(os.environ.get("SYNDICATE_CLV_PRICE_TRAIL") or "").strip().lower()
    return raw not in {"0", "off", "false", "no"}


def _as_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out


def _line_key(value: Any) -> float | None:
    number = _as_float(value)
    return None if number is None else round(number, 3)


def row_trail_point(row: Mapping[str, Any], *, epoch: int) -> tuple | None:
    """`(epoch, line, price, book)` for one published row, or None when unpriced."""
    quote = row.get("quote") if isinstance(row.get("quote"), Mapping) else {}
    price = _as_float(quote.get("price"))
    if price is None:
        return None
    return (int(epoch), _line_key(row.get("line")), price, str(quote.get("bookmaker") or "").strip().lower())


def _trim(bucket: list) -> None:
    # KEEP THE FIRST POINT. It is the nearest thing to our opening that the trail
    # has, and dropping it would start every long-lived series mid-move.
    if len(bucket) > _MAX_POINTS_PER_KEY:
        del bucket[1 : len(bucket) - (_MAX_POINTS_PER_KEY - 1)]


def load_price_trail(date: str, *, root: Path | str | None = None) -> dict[str, list[tuple]]:
    """`key -> [(epoch, line, price, book), ...]` in time order. Empty on any miss.

    Files written before 2026-09-15 ~18:30Z also carry an `f` (fair) field; it is
    ignored, so an old file still loads.
    """
    trail: dict[str, list[tuple]] = {}
    # EVERY file for the date -- the legacy whole-day one AND every hourly
    # chunk. `_trim` is applied once at the end rather than per file, because
    # trimming mid-way through the day's files would drop points that a later
    # chunk's arrival makes non-trailing.
    paths = price_trail_files(date, root=root)
    if not paths:
        return trail
    for path in paths:
        try:
            handle = path.open("r", encoding="utf-8")
        except OSError:
            continue
        with handle:
            for raw in handle:
                text = raw.strip()
                if not text:
                    continue
                try:
                    record = json.loads(text)
                except ValueError:
                    # A torn final line from a killed write is skipped, not fatal.
                    continue
                if not isinstance(record, Mapping):
                    continue
                key = record.get("k")
                stamp = record.get("t")
                price = _as_float(record.get("p"))
                if not isinstance(key, str) or not isinstance(stamp, (int, float)) or price is None:
                    continue
                bucket = trail.setdefault(key, [])
                bucket.append(
                    (int(stamp), _line_key(record.get("l")), price, str(record.get("b") or ""))
                )
    # SORT THEN TRIM, ONCE, ACROSS ALL FILES. Within one file the points are
    # already in time order, but a legacy whole-day file and the chunks can
    # interleave, and `_trim` keeps the FIRST point plus the latest N -- which
    # is only the right set once every point is present and ordered.
    for bucket in trail.values():
        bucket.sort(key=lambda point: point[0])
        _trim(bucket)
    return trail


def _day_bytes_on_disk(date: str, *, root: Path | str | None = None) -> int:
    """Total bytes this date occupies across the legacy file and every chunk."""
    total = 0
    for path in price_trail_files(date, root=root):
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return total


def _publish_sealed_chunks(
    date: str, *, current_hour: int, root: Path | str | None = None
) -> list[str]:
    """Push each chunk whose hour has passed, exactly once per process.

    THE DIRECT CALL THIS MODULE WAS MISSING, and it is deliberately NOT the
    shape `clv_openings` uses. That one re-pushes a whole growing file whenever
    it wrote anything; this pushes a SEALED chunk, once, and never again --
    bounding outbound at the day's size rather than builds x size. The reasoning
    is in the block above `_MAX_CHUNK_BYTES`.

    Why a direct call at all when the allowlist already covers the pattern:
    `sweep_changed_hot_artifacts` does not run in refresh-worker's main loop,
    only from intermittently spawned jobs, so the sweep cannot be relied on to
    move this file. A direct publish also earns the `_FAILED_DIRECT_PUBLISH`
    retry, which the sweep-only path never had for this artifact.

    NEVER RAISES. Losing a push costs analysis visibility; letting it propagate
    would cost the board, which is the same trade `record_openings` makes.
    """
    pushed: list[str] = []
    try:
        for path in price_trail_files(date, root=root):
            match = _CHUNK_FILE_RE.match(path.name)
            if not match:
                continue  # the legacy whole-day file is never pushed from here
            if int(match.group(2)) >= int(current_hour):
                continue  # still open: it can still gain points
            token = str(path)
            if token in _PUBLISHED_CHUNKS:
                continue
            from syndicate.features.shared.artifact_publisher import publish_hot_artifact

            if bool(publish_hot_artifact(path)):
                # Marked ONLY on success, so a failed push is retried on the
                # next build instead of being suppressed by its own attempt --
                # the rule `publish_hot_artifact` documents for itself.
                _PUBLISHED_CHUNKS.add(token)
                pushed.append(path.name)
    except Exception:  # noqa: BLE001 -- publishing must never break the board
        return pushed
    return pushed


def _prune_old_files(date: str, root: Path | str | None) -> int:
    try:
        cutoff = _date.fromisoformat(str(date).strip()) - timedelta(days=_RETAIN_DAYS)
    except ValueError:
        return 0
    directory = price_trail_path(date, root=root).parent
    removed = 0
    try:
        entries = list(directory.iterdir())
    except OSError:
        return 0
    for entry in entries:
        match = _DATE_FILE_RE.match(entry.name)
        if not match:
            continue
        try:
            if _date.fromisoformat(match.group(1)) < cutoff:
                entry.unlink()
                removed += 1
        except (ValueError, OSError):
            continue
    return removed


def record_price_trail(
    rows: Iterable[Mapping[str, Any]],
    *,
    date: str,
    trail: dict[str, list[tuple]] | None = None,
    now: datetime | None = None,
    root: Path | str | None = None,
    key_fn: Callable[[Mapping[str, Any]], str | None] | None = None,
) -> dict[str, Any]:
    """Append this build's changed observations. Never raises into the caller's data.

    `trail` is the index the caller loaded before the build; passing it avoids a
    second read and is updated in place. Returns counters even when nothing was
    written, so "ran and nothing changed" is distinguishable from "never ran".
    """
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    epoch = int(stamp.timestamp())
    if key_fn is None:
        from syndicate.features.shared.layer2_board import movement_join_key as key_fn
    if trail is None:
        trail = load_price_trail(date, root=root)
    rows_in = unkeyable = unpriced = unchanged = 0
    pending: list[dict[str, Any]] = []
    for row in rows or ():
        rows_in += 1
        if not isinstance(row, Mapping):
            unkeyable += 1
            continue
        key = key_fn(row)
        if not key:
            unkeyable += 1
            continue
        point = row_trail_point(row, epoch=epoch)
        if point is None:
            unpriced += 1
            continue
        bucket = trail.setdefault(key, [])
        last_same_line = next((p for p in reversed(bucket) if p[1] == point[1]), None)
        if last_same_line is not None and last_same_line[1:] == point[1:]:
            unchanged += 1
            continue
        bucket.append(point)
        _trim(bucket)
        pending.append({"k": key, "t": epoch, "l": point[1], "p": point[2], "b": point[3]})

    # THE CURRENT HOUR'S CHUNK, never the whole-day file. See `_MAX_CHUNK_BYTES`.
    path = price_trail_chunk_path(date, stamp.hour, root=root)
    written = 0
    truncated = False
    error = None
    if pending:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            size = path.stat().st_size if path.exists() else 0
            # The DAY's total still honours the original tripwire, summed across
            # chunks -- the ceiling moved, it was not removed. A per-chunk bound
            # alone would permit 24x the old maximum.
            day_size = _day_bytes_on_disk(date, root=root)
            with path.open("a", encoding="utf-8") as handle:
                for record in pending:
                    line = json.dumps(record, separators=(",", ":")) + "\n"
                    encoded = len(line.encode("utf-8"))
                    if size + encoded > _MAX_CHUNK_BYTES or day_size + encoded > _MAX_TRAIL_BYTES:
                        truncated = True
                        break
                    handle.write(line)
                    size += encoded
                    day_size += encoded
                    written += 1
        except OSError as exc:
            error = f"{type(exc).__name__}: {exc}"
    # PUBLISH THE SEALED CHUNKS, NOT THIS ONE. An hour that has passed can never
    # gain another point, so it is pushed exactly once and never re-pushed --
    # which is the whole reason this file is chunked at all.
    published = _publish_sealed_chunks(date, current_hour=stamp.hour, root=root)
    pruned = _prune_old_files(date, root) if written else 0
    report = {
        "date": str(date),
        "rows_in": rows_in,
        "points_written": written,
        "unchanged": unchanged,
        "unkeyable_rows": unkeyable,
        "unpriced_rows": unpriced,
        "keys": len(trail),
        "truncated_at_ceiling": truncated,
        "files_pruned": pruned,
        # THE SIZE, BECAUSE THE TRANSPORT HAS A CAP AND NOTHING REPORTED IT
        # (lane `layer2-line-movement-scoring`, 2026-09-20).
        #
        # This file is bounded at `_MAX_TRAIL_BYTES` (48 MB), but the artifact
        # export refuses any single file over **8 MB**
        # (`SYNDICATE_ARTIFACT_EXPORT_MAX_FILE_BYTES`). Those two numbers differ
        # by 6x, so a trail can be perfectly valid on the worker and silently
        # untransferable -- and until now no counter, log line or artifact field
        # said which side of 8 MB it was on. Allowlisting it in
        # `HOT_ARTIFACT_PATTERNS` PERMITS the transfer (`#208`); this is what
        # lets anyone check the transfer can actually happen.
        #
        # Read AFTER the append, so it is the size a pull would see, and
        # `None` rather than 0 when the file does not exist -- absent and empty
        # are different facts and a bare 0 cannot tell them apart.
        "bytes_on_disk": (path.stat().st_size if path.exists() else None),
        # THE DAY'S TOTAL, not just this chunk: the chunk is 1/24th by
        # construction and would always look reassuring. This is the number to
        # compare against `_MAX_TRAIL_BYTES`, and the one that answers whether
        # the whole-day file would have crossed the 12 MiB publish ceiling.
        "day_bytes_on_disk": _day_bytes_on_disk(date, root=root),
        "chunk": path.name,
        # WHICH SEALED CHUNKS WERE PUSHED THIS BUILD. Empty is the normal
        # steady state (each is pushed once, so most builds push nothing) and
        # is NOT the same as "publishing is broken" -- `chunks_on_disk` is the
        # denominator that tells them apart.
        "chunks_published": published,
        "chunks_on_disk": sum(1 for p in price_trail_files(date, root=root) if _CHUNK_FILE_RE.match(p.name)),
    }
    if error:
        report["error"] = error
    print(
        "[clv_price_trail] TRAIL date=%s rows_in=%d written=%d unchanged=%d keys=%d truncated=%s%s"
        % (date, rows_in, written, unchanged, len(trail), truncated, f" error={error}" if error else ""),
        flush=True,
    )
    return report


def _downsample(values: list[tuple[int, float]], limit: int) -> list[tuple[int, float]]:
    if len(values) <= limit:
        return values
    step = (len(values) - 1) / float(limit - 1)
    picked = [values[round(i * step)] for i in range(limit)]
    picked[-1] = values[-1]
    return picked


def price_move_series(
    points: Iterable[tuple] | None,
    *,
    line: Any,
    price_from: Any,
    price_to: Any,
    opened_epoch: int | None,
    now_epoch: int,
    book: Any = None,
) -> dict[str, Any] | None:
    """The price the movement LABEL states, as implied probability, from our publish to now.

    First point is `price_from` at `opened_epoch`; last point is `price_to` at
    `now_epoch`; between them, trail points at the same line -- and, when `book`
    is given (the label's pair is same-book), only points quoted at that book.
    With `book=None` the label's pair is best-of-N, so every point's best price is
    used. Because both ends ARE the label's pair, the line's direction always
    matches `movement_vs_pick`: rising = the price shortened = toward the pick.

    Implied probability is the plotted unit because it is continuous across even
    money and rises when a price shortens, whatever its sign. Returns None unless
    the series holds 2+ distinct values: a flat line would draw movement that did
    not happen.
    """
    start = implied_probability(price_from)
    end = implied_probability(price_to)
    if start is None or end is None or opened_epoch is None:
        return None
    opened = int(opened_epoch)
    finish = max(int(now_epoch), opened + 60)
    line_key = _line_key(line)
    book_key = str(book).strip().lower() if book else None
    values: list[tuple[int, float]] = [(opened, start)]
    for point in sorted(points or (), key=lambda p: p[0]):
        if point[0] <= opened or point[0] >= finish or point[1] != line_key:
            continue
        if book_key is not None and point[3] != book_key:
            continue
        prob = implied_probability(point[2])
        if prob is not None:
            values.append((point[0], prob))
    values.append((finish, end))
    values = _downsample(values, _SERIES_MAX_POINTS)
    series = [[int(round((t - opened) / 60.0)), int(round(v * 10000))] for t, v in values]
    if len({v for _, v in series}) < 2:
        return None
    return {
        "movement_series": series,
        "movement_series_start": datetime.fromtimestamp(opened, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "movement_series_basis": "same_book" if book_key else "best_price",
    }
