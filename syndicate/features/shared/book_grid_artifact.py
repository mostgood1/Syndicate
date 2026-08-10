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

ENRICHMENT IS PART OF THE ARTIFACT, NOT OF THE VIEW (`#328`)
------------------------------------------------------------
A raw grid is prices with nothing to judge them against. The three
`board_enrichment` steps -- game state, projections, margin model -- are what
make it a board, and this builder runs all three.

It did not, when it shipped. `#323` moved the pivot here and web began serving
the artifact from an early branch that skipped the `_attach_*` calls the
live-pivot path still made, so the board silently lost Proj, Edge, Date, Game
and one-sided Fair. Nothing failed; the columns were simply never populated, and
a blank column reads as "the model has no opinion" rather than "nobody asked
it". The cost of getting this wrong is not an error, it is a board that looks
complete and is not -- which is the same shape as the truncation problem above,
and the reason both are handled in this file rather than at the view.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from syndicate.features.shared.book_grid import (
    book_grid_summary,
    build_book_grid,
    freshest_rows_for_grid,
)
from syndicate.features.shared.odds_book_quotes import (
    book_quotes_path,
    iter_book_quotes,
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

# 1 -> 2 (#328): rows now carry `game`/`projection`/`modelled_fair`, and the
# payload carries the three coverage dicts plus `market_kinds`.
#
# THE VERSION IS LOAD-BEARING BECAUSE THE TWO SERVICES DEPLOY INDEPENDENTLY.
# `#320` is the standing lesson: the worker wrote a board-snapshot format web
# could not read, from 00:16Z, silently, with no signal on either side. Here the
# window is smaller but real -- web ships the new reader while refresh-worker is
# still writing v1 for up to one build interval (600s), and on a cancelled
# worker deploy it can be much longer, since a cancelled deploy restarts the
# worker onto the OLD commit and neither the deploys API nor the events API says
# so.
#
# So web must not read "v1" as "this slate has no projections". A missing
# enrichment and an absent one are different facts and must not render the same
# way -- see `enriched` / `enrichment_state` in the endpoint.
BOOK_GRID_ARTIFACT_VERSION = 2


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

    # STREAMED AND REDUCED, not read whole (`#331`). `read_book_quotes` returns
    # and caches every parsed row: measured 2026-08-09, that is 478,782 dicts
    # and a 1,216MB peak for the MLB shard. This worker plateaus at 2.65-2.70GB
    # of 4GB, so the whole-shard pivot does not fit in its headroom -- and this
    # tick runs every 10 minutes.
    #
    # `freshest_rows_for_grid` collapses the change log to the rows the pivot can
    # still use, which is PROVEN byte-identical against the full path on the
    # complete 217MB production shard (tests/test_book_grid.py). 155MB peak,
    # 41,233 rows kept of 478,782.
    #
    # The equivalence tests are not ceremony: two earlier attempts at this
    # reduction permuted 2,006 of 5,547 rows and re-anchored 972, at IDENTICAL
    # total byte length, and neither was visible in any count, size or summary
    # check. `build_book_grid` anchors on the first row carrying a given
    # canonical line, so the pivot's output depends on row ORDER -- anything
    # that touches it must be compared grid-to-grid, not by totals.
    raw_quote_rows = 0

    def _counted() -> Any:
        nonlocal raw_quote_rows
        for row in iter_book_quotes(sport, date_str):
            raw_quote_rows += 1
            yield row

    rows = freshest_rows_for_grid(_counted())
    if not rows:
        return None
    try:
        last_seen = read_quote_last_seen(sport, date_str)
    except Exception:
        last_seen = {}

    grid = build_book_grid(rows, last_seen=last_seen)

    # ENRICHMENT, and the reason it is HERE rather than at serve time (#328).
    #
    # `#323` moved the pivot to this worker and web now returns the artifact from
    # an early branch, BEFORE the three `_attach_*` calls the live-pivot path
    # still makes. So the moment the artifact existed, the served board lost
    # every field these produce -- measured on production 2026-08-10 16:5xZ, a
    # served MLB row carried no `game`, no `projection` and no `modelled_fair`,
    # which is Proj, Edge, Date, Game blank on every row of `/market-board/books`
    # and Fair blank on the 441 one-sided rows the margin model exists for.
    #
    # This is `board_enrichment`'s own defect recurring one layer over. Its
    # module docstring records the first instance verbatim -- `layer2_shortlist`
    # built a grid with `read_book_quotes` -> `build_book_grid` and called none
    # of them -- and states the rule that was supposed to prevent the second:
    # "one rule, one place: both the endpoint and the worker now call these". A
    # THIRD producer of grids appeared and inherited neither the calls nor the
    # rule. Any future grid producer must call these three; there is no cheaper
    # way to say it than in the file that builds the grid.
    #
    # Run against the FULL grid, before the bound, for the same reason `summary`
    # is: `build_margin_profile` measures this slate's holds from its two-sided
    # markets, so profiling the truncated slice would fit the model to whatever
    # happened to survive the cut.
    from syndicate.features.shared.board_enrichment import (
        attach_game_state,
        attach_margin_model,
        attach_projections,
    )

    # Same order as the serve-time path, deliberately: projections read rows that
    # game state has already stamped, and the margin model must run last so it
    # only fills rows that still have no fair value.
    game_state_coverage = attach_game_state(grid, sport=sport, selected_date=date_str)
    projection_coverage = attach_projections(grid, sport=sport, selected_date=date_str)
    margin_coverage = attach_margin_model(grid)

    # Market taxonomy, served rather than re-derived on the client -- the serve
    # path computes this and the artifact path did not, so the board's kind
    # selector fell back to an empty map and BOTH tabs claimed all 14 markets.
    # Computed here, pre-bound, for the same reason as everything else above.
    market_kinds: dict[str, str] = {}
    for row in grid:
        market_name = str(row.get("market") or "")
        row_kind = str(row.get("kind") or "")
        if market_name and row_kind:
            market_kinds.setdefault(market_name, row_kind)

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
        # RAW rows in the shard, unchanged in meaning by the `#331` reduction --
        # this field is how a partial shard is spotted, so it must keep counting
        # what the shard holds rather than what the pivot kept. `source_rows_kept`
        # is the reduced figure; the two together say how compressible the day was.
        "source_quote_rows": raw_quote_rows,
        "source_rows_kept": len(rows),
        "rows_total": total,
        "rows_truncated": max(0, total - len(bounded)),
        "summary": summary,
        # The three coverage payloads, persisted rather than recomputed. Each one
        # is how a blank column becomes attributable -- `no_chips_for_date` and
        # "the alias join failed" render identically without them, which is the
        # degraded-looks-legitimate trap `attach_game_state` documents at length.
        "game_state": game_state_coverage,
        "projections": projection_coverage,
        "margin_model": margin_coverage,
        "market_kinds": market_kinds,
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
