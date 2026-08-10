"""Precompute the Layer 1 book grid on the worker so web can serve it (`#322`).

WHY THIS EXISTS, IN ONE MEASUREMENT. `/api/board/book-grid` pivoted the raw
`book_quotes` shard on the request path. Measured 2026-08-10:

    MLB shard, 2026-08-09      217,439,783 bytes  (207 MB)
    resident cost              x6.3 = ~1,300 MB, never returned to the OS
    web container              2,048 MB, ~426 MB baseline
                               ~1,726 MB against a measured lethal ~1,548 MB

ONE read is fatal. Web OOM-killed twice that evening, once on the user's own
session and once on a diagnostic. The endpoint also took 22.2 seconds and
returned 2.69 MB for 300 rows.

The shard doubled from the ~90 MB the old comments record because book coverage
went from ~11 books to 44 (Pinnacle for de-vigging, plus exchanges). That is a
GOOD change -- price shopping is worth a measured +2.79 ROI points -- and it is
exactly why the pivot cannot live on a 2 GB web process. `CLAUDE.md`'s rule was
already explicit: workers compute, web reads artifacts.

WHAT IS PERSISTED, AND WHAT IS DELIBERATELY NOT
-----------------------------------------------
`summary` is computed over the WHOLE grid before any bound, so coverage numbers
describe the real surface. `rows` is bounded, because the artifact has to cross
a service boundary and an unbounded one reintroduces the problem one layer over
-- a 207 MB shard can pivot into more grid than any transport here will carry.
`rows_total` and `rows_truncated` say when that happened, so a thin board is
attributable rather than mysterious. A silent truncation would read as "the
grid only has this much", which is the failure this whole file exists to stop.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from syndicate.features.shared.book_grid import book_grid_summary, build_book_grid
from syndicate.features.shared.odds_book_quotes import (
    book_quotes_path,
    read_book_quotes,
    read_quote_last_seen,
)
from syndicate.features.shared.refresh_state_store import data_root

# Bounded on purpose. The endpoint's own max is 2000 and its default is 300, so
# this carries more than any single request can show while staying a file a
# service boundary will actually move.
#
# RAISED 1500 -> 6000 on 2026-08-10, because the original figure came from a
# guess and the guess was 3.4x wrong. It assumed ~9 KB per grid row. Measured by
# building this artifact from the complete production shard for 2026-08-09
# (478,782 quote rows, a 15-game MLB slate at 44 books):
#
#   full grid   5,547 rows   14,494,552 bytes   ->  2,613 bytes/row
#     cap 1500    6.68 MB   keeps  27.0%   <- what shipped, discarding 4,047 rows
#     cap 3000    9.83 MB   keeps  54.1%
#     cap 6000   13.82 MB   keeps 100.0%
#
# So the deployed bound was throwing away 73% of a real day's board while
# reporting `rows_truncated` correctly and nobody reading it. The slice is at
# least PROPORTIONAL -- it kept 336 of 1,251 segment rows (26.9%) against
# 1500/5547 (27.0%) -- so it was not silently dropping whole categories, which
# is the failure this could have been and was not.
#
# 6000 is sized to hold a complete day of the largest slate measured, with the
# truncation signal left intact rather than raised until it can never fire: a
# busier day SHOULD still report `rows_truncated` rather than pretend.
#
# Safe at this size on both transports, checked rather than assumed:
#   - written with os.replace to disk, NOT through write_json_file, so the
#     8,388,608-byte keyvalue ceiling does not apply to it
#   - 13.8 MB is above _PUBLISH_STREAM_MIN_BYTES (4 MB), so it crosses on the
#     streamed publish path and never takes ops.py's three-resident-copy JSON
#     envelope
BOOK_GRID_ARTIFACT_MAX_ROWS = 6000

BOOK_GRID_ARTIFACT_VERSION = 1


def book_grid_artifact_path(sport: str, date_str: str) -> Path:
    slug = str(sport or "").strip().lower()
    return (
        data_root()
        / f"{slug}_source"
        / "data"
        / "book_grid"
        / f"book_grid_{str(date_str).strip()}.json"
    )


def build_book_grid_artifact(
    sport: str, date_str: str, *, max_rows: int = BOOK_GRID_ARTIFACT_MAX_ROWS
) -> dict[str, Any] | None:
    """Pivot the shard and return the artifact payload. WORKER-SIDE ONLY.

    Returns None when there is no shard for this sport/date -- an absent shard
    is not an empty grid, and writing an empty artifact would make the two
    indistinguishable to every reader.
    """
    path = book_quotes_path(sport, date_str)
    if not path.is_file():
        return None
    try:
        shard_bytes = path.stat().st_size
    except OSError:
        shard_bytes = 0

    rows = read_book_quotes(sport, date_str)
    if not rows:
        return None
    try:
        last_seen = read_quote_last_seen(sport, date_str)
    except Exception:
        last_seen = {}

    grid = build_book_grid(rows, last_seen=last_seen)
    # Summary BEFORE the bound: coverage must describe the real surface, not the
    # slice that happened to fit.
    summary = book_grid_summary(grid)
    total = len(grid)
    bounded = grid[: max(1, int(max_rows))]

    return {
        "version": BOOK_GRID_ARTIFACT_VERSION,
        "sport": str(sport or "").strip().lower(),
        "date": str(date_str or "").strip(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_shard_bytes": shard_bytes,
        "source_quote_rows": len(rows),
        "rows_total": total,
        "rows_truncated": max(0, total - len(bounded)),
        "summary": summary,
        "rows": bounded,
    }


def write_book_grid_artifact(sport: str, date_str: str, payload: dict[str, Any]) -> Path:
    path = book_grid_artifact_path(sport, date_str)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, default=str)
    os.replace(tmp, path)
    return path


def read_book_grid_artifact(sport: str, date_str: str) -> dict[str, Any] | None:
    """Read the precomputed grid. WEB-SIDE. Cheap: one file, already bounded.

    Returns None when absent, which the caller must render as a degraded board
    rather than as an empty grid -- see the module docstring.
    """
    path = book_grid_artifact_path(sport, date_str)
    try:
        if not path.is_file():
            return None
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None
