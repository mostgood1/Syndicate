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
import re
from collections.abc import Mapping
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


def score_block_for_grid(
    grid: Any, *, sport: str, date_str: str, segment_actuals: Any = None
) -> dict[str, Any]:
    """The `live_gameline_score` payload block. NEVER RAISES.

    `segment_actuals` is the `live_gameline_score.SegmentActualLookup` hook
    for rows whose `segment` is not the full game. None -- the default and
    the only thing the board build passes today -- means such rows are
    reported UNMEASURED rather than graded against the full-game final.

    EXTRACTED SO ITS BRANCHES ARE TESTABLE. This was inline in
    `build_book_grid_artifact`, which cannot run without a source bundle -- so
    the only way to see what a PREGAME board publishes was to read production.
    That is exactly how the missing capability stamp below survived a deploy.

    Three branches, and ALL THREE carry `scorer_capabilities()`:
      * no finals on the grid -- the normal mid-slate state, not a failure;
      * finals present -- the real score;
      * an exception -- reported in the payload, because the board is the
        product and this is instrumentation.
    """
    live_gameline_score: dict[str, Any] = {"enabled": False, "reason": "not_attempted"}
    # STAMPED ONTO EVERY BRANCH BELOW, INCLUDING THE FAILURE ONES.
    #
    # Measured 2026-09-01T16:56:16Z, 56s after the staleness gate went live: a
    # pregame board took the `no_final_games_on_this_grid` branch, which
    # hand-built its dict and carried none of the scorer's own identity. The
    # served block was exactly ['enabled', 'finals_index', 'games_with_outcome',
    # 'reason'] -- so "shipped and had nothing to score" and "did not ship" were
    # the same null, and the deploy could not be verified until a game finished.
    #
    # These are CONSTANTS. They need no records, no finals and no slate, so
    # there was never a reason for them to be conditional on having a sample.
    # Bound OUTSIDE the try: `{}` here means the IMPORT failed, which is a
    # different and honest answer rather than a missing one.
    caps: dict[str, Any] = {}
    try:
        from syndicate.features.shared.live_gameline_ledger import ledger_path, read_records
        from syndicate.features.shared.live_gameline_score import (
            build_final_scores_index,
            finals_from_scores,
            score_ledger_records,
            scorer_capabilities,
        )

        caps = scorer_capabilities()

        # `sport` IS LOAD-BEARING HERE, not decoration: it decides whether a
        # level final is a draw (a real "home did not win") or a corrupt row.
        # Passing nothing is what made soccer's score exclude 17-38% of its
        # matches -- see `build_finals_index`. `finals_diag` rides along on the
        # payload so that exclusion can never again be invisible.
        finals_diag: dict[str, Any] = {}
        # ONE walk of the grid. The scores are what totals and spreads are
        # scored on (contract 3); the home-won view h2h uses is derived
        # from them, so the two can never disagree on which finals exist.
        final_scores = build_final_scores_index(grid, sport=sport, diagnostics=finals_diag)
        finals = finals_from_scores(final_scores)
        if not finals:
            # No final game on this grid is the NORMAL state mid-slate, and it
            # is not a failure. Saying so keeps it distinct from a scorer that
            # ran and found the model worthless.
            live_gameline_score = {"enabled": True, "reason": "no_final_games_on_this_grid",
                                   "games_with_outcome": 0, "finals_index": finals_diag,
                                   **caps}
        else:
            records = read_records(ledger_path(sport, date_str))
            # `caps` first: where `score_ledger_records` reports the same key it
            # is the authority, because it actually ran.
            live_gameline_score = {"enabled": True, **caps,
                                   **score_ledger_records(
                                       records, finals,
                                       final_scores=final_scores,
                                       segment_actuals=segment_actuals,
                                   ),
                                   "finals_index": finals_diag}
    except Exception as exc:  # pragma: no cover - instrumentation must not break the board
        live_gameline_score = {"enabled": True, "error": f"{type(exc).__name__}: {exc}"[:200],
                               **caps}
    return live_gameline_score


LIVE_GAMELINE_BUILD_TAG = "[book_grid] LIVE_GAMELINE_BUILD"
# Below the ~1,200 chars at which Render's logs API cut a payload on 2026-09-02
# (`learnings.md`: the visible half read all zeros and was published as fact).
LIVE_GAMELINE_BUILD_MAX_CHARS = 1000


def _log_token(value: Any, limit: int = 80) -> str:
    """One whitespace-free token, so a reason with spaces cannot split a field."""
    text = re.sub(r"\s+", "_", str(value if value is not None else "")).strip("_")
    return text[:limit] or "none"


def _log_count(value: Any) -> str:
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return "na"


def _log_dict(value: Any) -> str:
    try:
        text = json.dumps(value if isinstance(value, Mapping) else {},
                          sort_keys=True, separators=(",", ":"), default=str)
    except Exception:
        text = "{}"
    return re.sub(r"\s+", "_", text)


def live_gameline_build_line(
    sport: Any, date_str: Any, grid: Any, coverage: Any, ledger: Any
) -> str:
    """The one per-build log line for the live-gameline attach and ledger write.

    WHY THIS LINE EXISTS. Measured 2026-09-14 on MLB 2026-09-12: the score capped
    at 5 of 15 games with every final present. The ledger held `segment=full`
    rows from only 4 of 139 builds, while refresh-worker's layer2 join logged
    full-game `live_mc` projections for 1-9 games. This build's `live_gamelines`
    and `live_gameline_ledger` counters ride the artifact, which the NEXT build
    overwrites, and nothing printed them -- so the hop between "the join had a
    projection" and "the ledger wrote a row" could not be read after the fact.
    Lane `book-grid-gameline-ledger-log`.

    `full_games` is the number that was missing: distinct GAMES with a
    full-game projection attached on THIS build's grid. Rows are not games (one
    game carries h2h, spreads and totals), and first5 rows never count.

    MACHINE-READ, so its shape is the contract (`learnings.md` 2026-09-06): each
    name once, whitespace-free values, dict-valued fields LAST. When the line
    would exceed `LIVE_GAMELINE_BUILD_MAX_CHARS`, the widest dicts are dropped
    and COUNTED in `clipped` -- the scalars are never the casualty.

    Pure and NEVER RAISES: the board is the product and this is instrumentation.
    """
    try:
        from syndicate.features.shared.live_gameline_join import REFUSAL_KEY
        from syndicate.features.shared.live_gameline_ledger import segment_label

        cov = coverage if isinstance(coverage, Mapping) else {}
        led = ledger if isinstance(ledger, Mapping) else {}
        attached: dict[str, int] = {}
        refused: dict[str, int] = {}
        full_games: set[str] = set()
        for row in grid if isinstance(grid, (list, tuple)) else ():
            if not isinstance(row, Mapping):
                continue
            seg = segment_label(row)
            lg = row.get("live_gameline")
            if isinstance(lg, Mapping):
                attached[seg] = attached.get(seg, 0) + 1
                if seg == "full":
                    game = str(lg.get("game_pk") or row.get("event_id") or "").strip()
                    if game:
                        full_games.add(game)
            elif row.get(REFUSAL_KEY):
                refused[seg] = refused.get(seg, 0) + 1

        if cov.get("error"):
            error = _log_token(cov.get("error"))
        elif led.get("error"):
            error = "ledger:" + _log_token(led.get("error"))
        else:
            error = "none"

        scalars = [
            ("sport", _log_token(sport)),
            ("date", _log_token(date_str)),
            ("index", _log_count(cov.get("index_size"))),
            ("seg_index", _log_count(cov.get("segment_index_size"))),
            ("considered", _log_count(cov.get("rows_live_gameline_considered"))),
            ("projected", _log_count(cov.get("rows_live_gameline_projected"))),
            ("priceable", _log_count(cov.get("rows_live_gameline_priceable"))),
            ("withheld", _log_count(cov.get("rows_live_gameline_withheld"))),
            ("full_games", str(len(full_games))),
            ("candidates", _log_count(led.get("candidates"))),
            ("written", _log_count(led.get("written"))),
            ("skipped_unchanged", _log_count(led.get("skipped_unchanged"))),
            ("truncated_build", _log_count(led.get("truncated_build_cap"))),
            ("truncated_file", _log_count(led.get("truncated_file_cap"))),
            ("error", error),
        ]
        dicts = [
            ("attached_by_segment", _log_dict(attached)),
            ("refused_by_segment", _log_dict(refused)),
            ("written_by_segment", _log_dict(led.get("written_by_segment"))),
            ("skipped_by_segment", _log_dict(led.get("skipped_unchanged_by_segment"))),
            ("withheld_by_reason", _log_dict(cov.get("withheld_by_reason"))),
            ("index_why", _log_dict(cov.get("index_diagnostics"))),
        ]

        def _render(kept: list[tuple[str, str]], clipped: int) -> str:
            head = scalars + ([("clipped", str(clipped))] if clipped else [])
            return " ".join([LIVE_GAMELINE_BUILD_TAG] + [f"{k}={v}" for k, v in head + kept])

        kept = list(dicts)
        line = _render(kept, 0)
        while len(line) > LIVE_GAMELINE_BUILD_MAX_CHARS and kept:
            widest = max(range(len(kept)), key=lambda i: len(kept[i][1]))
            kept.pop(widest)
            line = _render(kept, len(dicts) - len(kept))
        return line[:LIVE_GAMELINE_BUILD_MAX_CHARS]
    except Exception as exc:
        return (f"{LIVE_GAMELINE_BUILD_TAG} sport={_log_token(sport)} "
                f"date={_log_token(date_str)} error=line_failed:{type(exc).__name__}")


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
        attach_live_game_state_from_lens,
        attach_live_gamelines_for_sport,
        attach_live_projections_for_sport,
        attach_margin_model,
        attach_projections,
    )

    # Same order as the serve-time path, deliberately: projections read rows that
    # game state has already stamped, and the margin model must run last so it
    # only fills rows that still have no fair value.
    game_state_coverage = attach_game_state(grid, sport=sport, selected_date=date_str)
    # BEFORE the projections, and that ordering is the point (`#413`).
    # `live_edge_policy` decides whether a row may carry an edge by reading
    # `game.state`, so correcting the state afterwards would leave a settled
    # game's edges standing on the board -- the correction has to land while it
    # can still change an answer, not after.
    lens_state_coverage = attach_live_game_state_from_lens(grid, sport=sport, selected_date=date_str)
    projection_coverage = attach_projections(grid, sport=sport, selected_date=date_str)
    # LIVE TIER, AFTER the pregame one and deliberately not instead of it
    # (`#350`). `attach_projections` reads the pregame `daily_summary`, so every
    # row on an in-progress game carried a model that does not know the score --
    # and `live_edge_policy` therefore withheld its edge. Measured 2026-08-10: 4
    # live MLB games, 862 projected rows, ZERO with an edge, while MLB's live
    # re-sim was producing `liveProjection` for those same games on
    # live-odds-worker. The board read one artifact and the sim wrote another.
    #
    # This overlays the live number ONLY on rows whose game the board says is
    # live, marks them `live_aware`, and the policy then allows their edge. A
    # pregame row is untouched, and a row the join misses keeps its suppression
    # rather than silently gaining a pregame-derived edge.
    #
    # Reads the PUBLISHED snapshot and never triggers the re-sim -- that is
    # `refuse_if_compute_in_request_path` territory and belongs on the live
    # worker's tick.
    live_projection_coverage = attach_live_projections_for_sport(grid, sport=sport, selected_date=date_str)
    # GAME LINES, after the prop live tier and separate from it (Drop 3).
    # `attach_live_projections_for_sport` above is prop-shaped end to end -- its
    # input is `liveModelProbOver` on prop rows and its counter is
    # `rows_live_edged`. Game-line rows (`kind: "game"`, `market: "h2h"`) were
    # never in its scope, so every live moneyline carried a PREGAME win
    # probability and was suppressed by `live_edge_policy` for exactly that.
    #
    # This joins the same live re-sim's `homeWinProb` -- already published on the
    # snapshot's `gameLens` lanes as `source: "live_mc"` -- and prices it ONLY
    # when the edge clears the estimator's own noise. At 120 sims that bar is
    # ~9.1 points at p=0.5, so most rows are refused BY NAME rather than
    # published as noise (recorded decision, spec 8.1: publish, refuse to price).
    live_gameline_coverage = attach_live_gamelines_for_sport(grid, sport=sport, selected_date=date_str)
    # PERSIST the edges this build just computed, before anything downstream can
    # overwrite them. `live_gamelines` is recomputed from scratch every build:
    # measured 2026-08-16 on ONE slate, `rows_live_gameline_edged` read
    # 25 -> 4 -> 1 across three consecutive builds. CLV needs (edge at time T)
    # paired with (price at settlement) and the first half was never written
    # down, so by the time a game settled the row carrying its edge was long
    # gone. This records the OPEN half and computes no CLV.
    #
    # Deduplicated against the last record per market, so the file is a movement
    # history rather than a copy of the board per build, and it NEVER raises --
    # the board is the product, this is instrumentation for a measurement that
    # does not exist yet.
    from syndicate.features.shared.live_gameline_ledger import record_live_gamelines

    live_gameline_ledger = record_live_gamelines(grid, sport=sport, date_str=date_str)
    # PRINTED, not only carried in the payload: the payload is overwritten by
    # the next build, so these two counter sets were unreadable after the fact
    # -- which is what hid the 2026-09-12 loss of full-game rows (see
    # `live_gameline_build_line`). `print(flush=True)`, because `logger.info`
    # never reaches Render's log collector.
    print(
        live_gameline_build_line(
            sport, date_str, grid, live_gameline_coverage, live_gameline_ledger
        ),
        flush=True,
    )

    # SCORE THE LEDGER HERE, because here is the only place the sample and the
    # outcomes are both in hand. Measured 2026-08-17 01:0xZ: the ledger matches
    # zero `HOT_ARTIFACT_PATTERNS`, so nothing off-worker can read it, and a
    # FINISHED game retains no model probability on any served surface -- there
    # is no retrospective path. Riding this already-published artifact avoids a
    # new publish pattern and an edit to `artifact_publisher.py`, which an OPEN
    # lane holds.
    #
    # NEVER RAISES, same rule as the recorder above: the board is the product
    # and this is instrumentation. A failure is reported in the payload rather
    # than logged only, so a silent zero cannot be mistaken for "model scored
    # nothing".
    live_gameline_score = score_block_for_grid(grid, sport=sport, date_str=date_str)

    # RETAIN the score, here, for the same reason it is COMPUTED here: this is
    # the only place the sample and the outcomes are both in hand, and nothing
    # downstream keeps it. The served payload is overwritten by the next build,
    # and the board rolls to the next slate date at midnight Central.
    #
    # This REPLACES a laptop cron (`live-gameline-accuracy-snapshot`, 23:25 CT)
    # that lost 7 of its first 8 nights -- six to sitting disabled, and one to
    # Windows Modern Standby suspending its python child for 9h13m while the
    # scheduler and the model both ran normally (measured 2026-08-28; full chain
    # in `live_gameline_accuracy`'s docstring). Recording on every build also
    # removes the wall-clock DEADLINE that made a single missed run fatal.
    #
    # Appends only when `games_with_outcome` IMPROVES, so the build rate does
    # not multiply the file. Never raises, same rule as the recorder and scorer
    # above.
    #
    # ONE clock read, shared with the payload below, so the retained row's
    # `board_generated_at` is the SAME instant the artifact publishes rather
    # than a second reading microseconds later -- that field is how a retained
    # row is joined back to the build that produced it.
    generated_at = datetime.now(timezone.utc).isoformat()

    from syndicate.features.shared.live_gameline_accuracy import record_live_gameline_score

    live_gameline_accuracy = record_live_gameline_score(
        live_gameline_score,
        sport=sport,
        date_str=date_str,
        board_generated_at=generated_at,
    )

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
    # IN-PLAY ROWS ARE TAKEN BEFORE THE ROW CAP (lane `live-inplay-board-cadence`).
    # Soccer's grid ran 11,677 rows against the 6,000 cap on 2026-09-19, so a
    # live match could be cut from the artifact while it was the one thing a
    # live bettor needed. Held aside for `write_book_grid_artifact`, never
    # added to the payload, so the grid file itself is unchanged.
    _remember_inplay_rows(sport, date_str, generated_at, grid)
    bounded = grid[: max(1, int(max_rows))]

    return {
        "version": BOOK_GRID_ARTIFACT_VERSION,
        "sport": str(sport or "").strip().lower(),
        "date": str(date_str or "").strip(),
        "generated_at": generated_at,
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
        "live_game_state": lens_state_coverage,
        "projections": projection_coverage,
        "live_projections": live_projection_coverage,
        # Separate key from `live_projections` on purpose: they are different
        # joins with different inputs and different failure modes, and folding
        # them together would make one family's zero look like the other's.
        "live_gamelines": live_gameline_coverage,
        # Counters only -- the records themselves are JSONL on the worker's disk.
        "live_gameline_ledger": live_gameline_ledger,
        # The SCORE of those records against realised outcomes. This is the only
        # way the sample leaves the worker: model vs market Brier on identical
        # rows, so "is the model worth anything" is answerable off a served API.
        "live_gameline_score": live_gameline_score,
        # Counters for the RETENTION of the score above -- `written`,
        # `skipped_not_improved`, `previous_best`. Served because the retained
        # file lives on the worker's disk: without these, "the history stopped
        # growing" and "every build saw no new final" are indistinguishable
        # from any surface reachable off-worker, which is precisely the blind
        # spot that let the old collector lose seven nights unnoticed.
        "live_gameline_accuracy": live_gameline_accuracy,
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
    # Best effort and AFTER the grid is on disk: an overlay failure must never
    # cost the grid, which is what every other reader depends on.
    _write_inplay_overlay_best_effort(sport, date_str, payload)
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


# ---------------------------------------------------------------------------
# IN-PLAY OVERLAY (lane `live-inplay-board-cadence`, user 2026-09-19: "we need
# live interval odds for all sports to reach the board faster"; "Build it,
# deploy ASAP").
#
# WHY. The served board's in-play rows come from the Layer 2 shortlist, which
# refresh-worker rewrites about every ~12 min (and a restart discards a build).
# Measured 2026-09-19: 15-25 min from a price move to the page, while this grid
# rebuilt every ~2-3 min with NCAAF in-play prices a median 119 s old. The
# overlay carries ONLY in-play rows whose price is fresh, turned into board
# cards by the SAME chain the shortlist uses (`build_layer2_rows` ->
# `select_shortlist` -> `layer2_rows_to_board_cards`), so line, side, best-book
# re-pick and no-vig fair are the board's own and not a second contract. Web
# merges it at serve time (`intelligence_state._layer2_fallback_recommendations`).
#
# PRICES ONLY. Every in-play row carried `model_edge_pct` None on 2026-09-19 and
# in-play market-fair staking is refused by default, so these cards change what
# a bettor SEES, not what the portfolio stakes: `portfolio_commit` reads
# `read_layer2_shortlist` directly and never this file.
#
# Kill switch: `SYNDICATE_INPLAY_OVERLAY=off` on either service (worker stops
# writing; web stops merging).
# ---------------------------------------------------------------------------

INPLAY_OVERLAY_VERSION = 1
INPLAY_OVERLAY_SPORTS: tuple[str, ...] = ("mlb", "nba", "wnba", "nhl", "nfl", "ncaaf", "ncaab", "soccer")
_INPLAY_OFF_VALUES = frozenset({"off", "0", "false", "no", "disabled"})
# (sport, date) -> (generated_at, rows): the latest build's in-play rows, held
# between `build_book_grid_artifact` and `write_book_grid_artifact`. One entry
# per sport/date, replaced on every build, so it cannot grow.
_INPLAY_ROWS: dict[tuple[str, str], tuple[Any, list[Mapping[str, Any]]]] = {}
# Sport/dates whose last published overlay had cards: an empty overlay is
# published only to CLEAR one of these, so a finished game leaves the board.
_INPLAY_PUBLISHED_NONEMPTY: set[tuple[str, str]] = set()
_INPLAY_READ_CACHE: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}


def inplay_overlay_enabled() -> bool:
    raw = str(os.environ.get("SYNDICATE_INPLAY_OVERLAY") or "").strip().lower()
    return raw not in _INPLAY_OFF_VALUES


def _env_seconds(name: str, default: int) -> int:
    raw = str(os.environ.get(name) or "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        return default
    return value if value > 0 else default


def inplay_overlay_max_price_age_seconds() -> int:
    """A row older than this at grid build is NOT in-play-fresh (default 300 s)."""
    return _env_seconds("SYNDICATE_INPLAY_OVERLAY_MAX_PRICE_AGE_SECONDS", 300)


def inplay_overlay_max_file_age_seconds() -> int:
    """Web ignores an overlay written longer ago than this (default 360 s): a
    dead tick must degrade to the shortlist, not freeze stale prices as live."""
    return _env_seconds("SYNDICATE_INPLAY_OVERLAY_MAX_FILE_AGE_SECONDS", 360)


def book_grid_inplay_artifact_path(sport: str, date_str: str) -> Path:
    """Beside the grid, so the existing `book_grid_*.json` publish pattern and
    the 7-day `book_grid` retention rule cover it with no allowlist edit
    (`artifact_retention._artifact_date` reads its date the same way)."""
    return book_grid_artifact_path(sport, date_str).with_name(f"book_grid_inplay_{str(date_str).strip()}.json")


def _row_age_seconds(row: Mapping[str, Any]) -> float | None:
    for key in ("seen_age_seconds", "age_seconds"):
        value = row.get(key)
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if parsed == parsed and parsed >= 0:
            return parsed
    return None


def is_inplay_fresh_row(row: Any, *, max_age_seconds: float) -> bool:
    """A live game's row whose price was seen within `max_age_seconds` of the build."""
    if not isinstance(row, Mapping):
        return False
    game = row.get("game")
    if not isinstance(game, Mapping) or str(game.get("state") or "").strip().lower() != "live":
        return False
    age = _row_age_seconds(row)
    return age is not None and age <= max_age_seconds


def select_inplay_rows(grid: Any, *, max_age_seconds: float | None = None) -> list[Mapping[str, Any]]:
    limit = float(max_age_seconds if max_age_seconds is not None else inplay_overlay_max_price_age_seconds())
    return [row for row in (grid or []) if is_inplay_fresh_row(row, max_age_seconds=limit)]


def _remember_inplay_rows(sport: Any, date_str: Any, generated_at: Any, grid: Any) -> None:
    """Called by the builder BEFORE its row cap. Never raises."""
    try:
        if not inplay_overlay_enabled():
            return
        key = (str(sport or "").strip().lower(), str(date_str or "").strip())
        _INPLAY_ROWS[key] = (generated_at, select_inplay_rows(grid))
    except Exception:
        pass


def build_inplay_overlay(
    sport: str, date_str: str, rows: list[Mapping[str, Any]], *, grid_generated_at: Any = None
) -> dict[str, Any]:
    """The overlay payload: board cards for these in-play rows, built by the
    shortlist's own chain. Raises on a card-builder failure; the writer catches."""
    from syndicate.features.shared.layer2_board import (
        build_layer2_rows,
        layer2_rows_to_board_cards,
        select_shortlist,
    )

    slug = str(sport or "").strip().lower()
    cards: list[dict[str, Any]] = []
    opportunities: list[dict[str, Any]] = []
    if rows:
        result = build_layer2_rows(rows)
        opportunities = [dict(item) for item in (result.get("opportunities") or []) if isinstance(item, Mapping)]
        for item in opportunities:
            if not str(item.get("sport") or "").strip():
                item["sport"] = slug
        chosen = ((select_shortlist(opportunities) or {}).get("rows") or []) if opportunities else []
        for card in layer2_rows_to_board_cards(chosen):
            if not isinstance(card, Mapping):
                continue
            tagged = dict(card)
            tagged["source"] = "layer2_inplay_overlay"
            tagged["inplay_overlay"] = True
            tagged["price_grid_generated_at"] = grid_generated_at
            cards.append(tagged)
    return {
        "version": INPLAY_OVERLAY_VERSION,
        "sport": slug,
        "date": str(date_str or "").strip(),
        "grid_generated_at": grid_generated_at,
        "written_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "max_price_age_seconds": inplay_overlay_max_price_age_seconds(),
        "rows_inplay": len(rows or []),
        "opportunities": len(opportunities),
        "cards": cards,
    }


def write_book_grid_inplay_overlay(sport: str, date_str: str, overlay: Mapping[str, Any]) -> Path:
    path = book_grid_inplay_artifact_path(sport, date_str)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(overlay, handle, ensure_ascii=False, default=str)
    os.replace(tmp, path)
    return path


def _publish_inplay_overlay(path: Path) -> bool:
    try:
        from syndicate.features.shared.artifact_publisher import publish_hot_artifact

        return bool(publish_hot_artifact(path, timeout_seconds=30))
    except Exception:
        return False


def _write_inplay_overlay_best_effort(sport: str, date_str: str, payload: Mapping[str, Any]) -> None:
    """Build, write and publish this sport/date's overlay. NEVER raises.

    Rows come from the builder's pre-cap stash when it matches this payload's
    build, else from the (capped) payload rows. An overlay with no cards is
    written and published only when the previous one had cards, so a game that
    ends leaves the board instead of lingering until the file ages out.
    """
    import time as _time

    started = _time.monotonic()
    key = (str(sport or "").strip().lower(), str(date_str or "").strip())
    try:
        if not inplay_overlay_enabled():
            return
        stashed = _INPLAY_ROWS.pop(key, None)
        generated_at = payload.get("generated_at") if isinstance(payload, Mapping) else None
        if stashed is not None and stashed[0] == generated_at:
            rows = stashed[1]
        else:
            rows = select_inplay_rows((payload or {}).get("rows") if isinstance(payload, Mapping) else [])
        if not rows and key not in _INPLAY_PUBLISHED_NONEMPTY:
            return
        overlay = build_inplay_overlay(key[0], key[1], rows, grid_generated_at=generated_at)
        path = write_book_grid_inplay_overlay(key[0], key[1], overlay)
        published = _publish_inplay_overlay(path)
        if overlay["cards"]:
            _INPLAY_PUBLISHED_NONEMPTY.add(key)
        else:
            _INPLAY_PUBLISHED_NONEMPTY.discard(key)
        print(
            f"[book_grid] INPLAY_OVERLAY sport={key[0]} date={key[1]} rows_inplay={overlay['rows_inplay']} "
            f"opportunities={overlay['opportunities']} cards={len(overlay['cards'])} published={published} "
            f"elapsed_ms={(_time.monotonic() - started) * 1000:.0f}",
            flush=True,
        )
    except Exception as exc:  # noqa: BLE001 -- an overlay must never cost the grid
        print(f"[book_grid] INPLAY_OVERLAY_FAILED sport={key[0]} date={key[1]} {type(exc).__name__}: {exc}", flush=True)


def read_book_grid_inplay_overlay(sport: str, date_str: str) -> dict[str, Any] | None:
    """WEB-SIDE. The overlay for one sport/date, cached per process by the file's
    (mtime, size), so a board rebuild costs one stat per sport when nothing moved."""
    path = book_grid_inplay_artifact_path(sport, date_str)
    try:
        stat = path.stat()
    except OSError:
        return None
    signature = (int(stat.st_mtime_ns), int(stat.st_size))
    cached = _INPLAY_READ_CACHE.get(str(path))
    if cached is not None and cached[0] == signature:
        return cached[1]
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    _INPLAY_READ_CACHE[str(path)] = (signature, payload)
    return payload


def inplay_overlay_cards(date_str: str, *, now: datetime | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """WEB-SIDE. Every fresh overlay card for this date, plus what was skipped and why.

    An overlay whose `written_at` is older than `inplay_overlay_max_file_age_seconds()`
    is skipped: the tick that feeds it died or the worker restarted, and the board
    must fall back to the shortlist rather than present stale prices as live.
    """
    report: dict[str, Any] = {"sports": {}, "newest_written_at": None}
    if not inplay_overlay_enabled():
        report["disabled"] = True
        return [], report
    moment = now or datetime.now(timezone.utc)
    limit = inplay_overlay_max_file_age_seconds()
    cards: list[dict[str, Any]] = []
    for sport in INPLAY_OVERLAY_SPORTS:
        overlay = read_book_grid_inplay_overlay(sport, date_str)
        if not overlay:
            continue
        written = str(overlay.get("written_at") or "")
        try:
            written_dt = datetime.fromisoformat(written.replace("Z", "+00:00"))
        except ValueError:
            report["sports"][sport] = "unreadable_written_at"
            continue
        age = (moment - written_dt).total_seconds()
        if age > limit:
            report["sports"][sport] = f"stale_{int(age)}s"
            continue
        sport_cards = [dict(card) for card in (overlay.get("cards") or []) if isinstance(card, Mapping)]
        report["sports"][sport] = len(sport_cards)
        cards.extend(sport_cards)
        if report["newest_written_at"] is None or written > report["newest_written_at"]:
            report["newest_written_at"] = written
    return cards, report


def inplay_overlay_identity(card: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
    """What an overlay card REPLACES: the same game, market, segment and player.
    Deliberately NOT the line or side, so a moved line replaces the old one."""

    def norm(value: Any) -> str:
        return str(value or "").strip().lower()

    return (
        norm(card.get("sport") or card.get("sport_slug")),
        norm(card.get("event_id") or card.get("game_pk")),
        norm(card.get("market") or card.get("market_key")),
        norm(card.get("segment")) or "full",
        norm(card.get("player_name")),
    )
