"""Per-build price observations for the rows the Layer 2 board published.

WHY THIS EXISTS (lane `layer2-row-parity`, 2026-09-15). The board's movement
cell compares a row against ONE number, the price we first published it at
(`clv_opening_ledger`). Two points cannot draw a sparkline, and the sparklines
that did render came from a different pipeline entirely -- the legacy
candidates' fuzzy odds-history join -- measured the same day on the served
board to be:

    wrong side    MLB "Under 8.5" / "Under 8.0" rows plotted the OVER price
    wrong game    6 of 14 soccer rows plotted a different fixture
    wrong line    6 of 58 series spanned a line change, drawn as a price move
    no book       one price per side, from whichever book the snapshot met first

This records what the Layer 2 board ITSELF saw, for the exact bets it
published, at each build: the line, the no-vig fair probability for the side,
and the best price with its book. The sparkline is drawn from that.

THE SAME IDENTITY AS MOVEMENT. Keyed by `layer2_board.movement_join_key`
(event, market, player, segment, side -- no line, no book) and filtered by line
when read, so a line move ENDS a series instead of being drawn as a price move.

BOUNDED THREE WAYS, because periodic worker work is never free on refresh-worker:
a point is appended only when the observation changed (line, price, book, or the
fair probability by at least `_FAIR_EPSILON`); the in-memory index keeps the
first point plus the latest `_MAX_POINTS_PER_KEY - 1` per key; and the file stops
growing at `_MAX_TRAIL_BYTES`. Files older than `_RETAIN_DAYS` are removed on
write.

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
# 0.15 percentage points. Below this a fair-probability change is devig noise
# between two builds quoting the same prices, and recording it would grow the file
# every build for movement nobody can see at 16 px tall.
_FAIR_EPSILON = 0.0015
_RETAIN_DAYS = 4
_DATE_FILE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.jsonl$")


def _reports_root() -> Path:
    from syndicate.features.shared.refresh_state_store import reports_root

    return reports_root()


def price_trail_path(date: str, *, root: Path | str | None = None) -> Path:
    base = Path(root) if root is not None else _reports_root()
    return base / "intelligence" / TRAIL_SUBDIR / f"{str(date).strip()}.jsonl"


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
    """`(epoch, line, fair, price, book)` for one published row, or None when unpriced."""
    quote = row.get("quote") if isinstance(row.get("quote"), Mapping) else {}
    price = _as_float(quote.get("price"))
    fair = _as_float(quote.get("fair_probability"))
    if fair is not None and not 0.0 < fair < 1.0:
        fair = None
    if price is None and fair is None:
        return None
    return (
        int(epoch),
        _line_key(row.get("line")),
        None if fair is None else round(fair, 4),
        price,
        str(quote.get("bookmaker") or "").strip().lower(),
    )


def _trim(bucket: list) -> None:
    # KEEP THE FIRST POINT. It is the nearest thing to our opening that the trail
    # has, and dropping it would start every long-lived series mid-move.
    if len(bucket) > _MAX_POINTS_PER_KEY:
        del bucket[1 : len(bucket) - (_MAX_POINTS_PER_KEY - 1)]


def load_price_trail(date: str, *, root: Path | str | None = None) -> dict[str, list[tuple]]:
    """`key -> [(epoch, line, fair, price, book), ...]` in time order. Empty on any miss."""
    trail: dict[str, list[tuple]] = {}
    path = price_trail_path(date, root=root)
    try:
        handle = path.open("r", encoding="utf-8")
    except OSError:
        return trail
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
            if not isinstance(key, str) or not isinstance(stamp, (int, float)):
                continue
            bucket = trail.setdefault(key, [])
            bucket.append(
                (
                    int(stamp),
                    _line_key(record.get("l")),
                    _as_float(record.get("f")),
                    _as_float(record.get("p")),
                    str(record.get("b") or ""),
                )
            )
            _trim(bucket)
    return trail


def _same_observation(previous: tuple | None, current: tuple) -> bool:
    if previous is None:
        return False
    _, line_a, fair_a, price_a, book_a = previous
    _, line_b, fair_b, price_b, book_b = current
    if line_a != line_b or price_a != price_b or book_a != book_b:
        return False
    if (fair_a is None) != (fair_b is None):
        return False
    return fair_a is None or abs(fair_a - fair_b) < _FAIR_EPSILON


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
        if _same_observation(last_same_line, point):
            unchanged += 1
            continue
        bucket.append(point)
        _trim(bucket)
        pending.append({"k": key, "t": epoch, "l": point[1], "f": point[2], "p": point[3], "b": point[4]})

    path = price_trail_path(date, root=root)
    written = 0
    truncated = False
    error = None
    if pending:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            size = path.stat().st_size if path.exists() else 0
            with path.open("a", encoding="utf-8") as handle:
                for record in pending:
                    line = json.dumps(record, separators=(",", ":")) + "\n"
                    encoded = len(line.encode("utf-8"))
                    if size + encoded > _MAX_TRAIL_BYTES:
                        truncated = True
                        break
                    handle.write(line)
                    size += encoded
                    written += 1
        except OSError as exc:
            error = f"{type(exc).__name__}: {exc}"
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


def price_trail_series(
    points: Iterable[tuple] | None,
    *,
    line: Any,
    book: Any,
    current: tuple | None = None,
) -> dict[str, Any] | None:
    """The pick's probability over time at ONE line, or None when there is nothing to draw.

    A RISING series means the market moved TOWARD the pick (user decision
    2026-09-15: green on the board means exactly that). Probability is the
    plotted unit because it is continuous across even money and rises when a
    price shortens, whatever its sign.

    Prefers the no-vig FAIR probability, which is the same across books and so
    cannot jump when the best book changes hands. Falls back to the implied
    probability of ONE book's price -- the row's current book -- when the fair
    never moved. Returns None unless the chosen series holds 2+ distinct values:
    a flat line would draw movement that did not happen.
    """
    line_key = _line_key(line)
    pts = [p for p in (points or ()) if p[1] == line_key]
    if current is not None and current[1] == line_key and (not pts or current[0] > pts[-1][0]):
        pts.append(current)
    if len(pts) < 2:
        return None
    basis = None
    values: list[tuple[int, float]] = []
    fair = [(p[0], p[2]) for p in pts if p[2] is not None]
    if len({round(v, 4) for _, v in fair}) >= 2:
        basis, values = "fair", fair
    else:
        book_key = str(book or "").strip().lower()
        priced = []
        for p in pts:
            if p[4] != book_key:
                continue
            prob = implied_probability(p[3])
            if prob is not None:
                priced.append((p[0], prob))
        if len({round(v, 4) for _, v in priced}) >= 2:
            basis, values = "price", priced
    if basis is None:
        return None
    values = _downsample(values, _SERIES_MAX_POINTS)
    start = values[0][0]
    series = [[int(round((t - start) / 60.0)), int(round(v * 10000))] for t, v in values]
    if len({v for _, v in series}) < 2:
        return None
    return {
        "movement_series": series,
        "movement_series_start": datetime.fromtimestamp(start, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "movement_series_basis": basis,
    }
