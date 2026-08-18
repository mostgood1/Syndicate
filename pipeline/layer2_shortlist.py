"""Build the Layer 2 shortlist from the Layer 1 grid, worker-side.

WHY THIS IS A SEPARATE MODULE. `layer2_board.py` turns a grid into ranked
candidates but does not know where grids come from; `_build_candidate_pool`
knows the slate but should not grow another 60 lines of market plumbing. This is
the join, and keeping it out of `intelligence_state.py` means the OOM-sensitive
function gains one call, not a new subsystem.

ARTIFACT-BASED, NOT REQUEST-BASED. Its output goes into the candidate-pool
payload, which is persisted and read by web via `read_intelligence_board_state`.
Web computes nothing. Beyond CLAUDE.md's rule, there is a Layer-2-specific
reason: a board recomputed per request cannot be settled -- there is no record
of what was recommended at what price, so `settled: 0` would stay 0 structurally.

SCOPED TO SPORTS THAT ARE ACTUALLY ON. All eight sports are never active at
once -- 4 today, 7 at the October peak, 6 in December -- and only sports with a
manifest in this build have a shard worth reading. The caller passes the sports
it already resolved, so this never widens the read set.

MEMORY, already measured (postmortem §1.1d, docs/ai_context/): the cost of a
shard is its FIRST read -- ~6.3x file size, never returned to the OS -- and
repeated reads are free. `_collect_candidates` has already read these same
shards earlier in the same build (via `enrich_prop_rows` -> `quote_ref_for_bet`
-> `read_book_quotes`), so this adds grid/candidate structures on top of an
already-paid read, not a new one. That is why this is safe to run here and would
not have been safe as a separate sweep over sports nobody had read.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping


_UNSET = object()


def build_layer2_shortlist(
    selected_date: str,
    sport_slugs: Iterable[str],
    *,
    max_grid_rows_per_sport: int | None = None,
    horizon_days: Any = _UNSET,
) -> dict[str, Any]:
    """Layer 1 grid -> ranked one-side candidates -> persisted shortlist.

    Never raises. A failure here must not take down the candidate pool: Layer 2
    is additive to a board that already works without it, and the whole point of
    wiring it into this function was to avoid a second heavy path.
    """
    from syndicate.features.shared.layer2_board import build_layer2_rows, select_shortlist

    # LOADED ONCE, BEFORE ANY SPORT IS PROCESSED. See `_movement_from_opening`
    # for why this is not read per row: `#372` stalled the whole build by doing
    # exactly that with a ~20MB shard. This reads one small JSONL of the rows
    # THIS board published today.
    #
    # Read BEFORE `record_openings` appends today's rows, deliberately: movement
    # must compare against the FIRST time we published a row, not against the
    # copy being written this instant.
    # KEYED WITHOUT `line` AND `bookmaker`, AND THAT IS THE WHOLE POINT.
    #
    # `_opening_key` puts BOTH in the key, correctly, because CLV must not
    # collapse home -1.5 and home -2.5, nor two books' prices. But **movement
    # IS the detection of line and book change**, so joining on that key can
    # only ever match rows that did NOT move -- the metric becomes conditioned
    # on the absence of the thing it measures.
    #
    # MEASURED across two artifacts 20 minutes apart, 2026-08-16 21:01 -> 21:21:
    #
    #     stable key (event·market·player·segment·side) matched   20
    #     full key   (+ line + bookmaker)               matched   14
    #        of the 20: line changed 6, book changed 5, either 7
    #
    # So ~a third of matchable rows were dropped, and they were precisely the
    # rows with something to report. It also explains why steam never fired: a
    # sharp move is usually accompanied by a line move or a best-book switch,
    # which breaks the key and erases the evidence of the move.
    #
    # The opening RECORD already carries `line`, `price`, `bookmaker` and
    # `book_prices`, so nothing is lost by keying loosely and reading the
    # detail off the record -- `book_prices` is what still makes the price
    # comparison same-book even when the best book has changed.
    #
    # `_opening_key` itself is NOT changed: it is right for the settlement join
    # it was built for, and this is a different question asked of the same data.
    openings_index: dict[str, Any] = {}
    openings_error: str | None = None
    openings_records = 0
    try:
        from syndicate.features.shared.clv_opening_ledger import load_openings
        from syndicate.features.shared.layer2_board import movement_join_key

        for record in load_openings(selected_date) or []:
            if not isinstance(record, Mapping):
                continue
            openings_records += 1
            key = movement_join_key(record)
            # FIRST WRITE WINS -- the ledger is append-only, so a key recurs and
            # the earliest occurrence is the opening by definition. Doubly so
            # now: under the loose key, later records for the same bet are
            # exactly the moved versions we are measuring against.
            if key and key not in openings_index:
                openings_index[key] = record
    except Exception as exc:
        openings_error = f"{type(exc).__name__}: {exc}"

    opportunities: list[dict[str, Any]] = []
    per_sport_stats: dict[str, Any] = {}

    for sport_slug in sport_slugs:
        sport = str(sport_slug or "").strip().lower()
        if not sport:
            continue
        try:
            from syndicate.features.shared.board_enrichment import (
                attach_game_state,
                attach_margin_model,
                attach_projections,
            )

            # THE LIVE JOINS ARE IMPORTED SEPARATELY AND OPTIONALLY.
            #
            # Same cross-file hazard as the card builder below: if
            # `board_enrichment.py` on this worker predates them, naming them in
            # the import block above turns an ImportError into the loss of THIS
            # SPORT'S ENTIRE ENRICHMENT -- game state, projections and margin
            # model all die with it, because they share the try. A missing live
            # tier should cost the live tier and nothing else.
            #
            # They are on every service today (verified 2026-08-16), so this
            # guards a future rollback rather than a present gap. It is here
            # because `c324447d` proved these files do not move together.
            try:
                from syndicate.features.shared.board_enrichment import (
                    attach_live_gamelines_for_sport,
                    attach_live_projections_for_sport,
                )
            except ImportError:
                attach_live_gamelines_for_sport = None  # type: ignore[assignment]
                attach_live_projections_for_sport = None  # type: ignore[assignment]
            from syndicate.features.shared.book_grid import build_book_grid
            from syndicate.features.shared.odds_book_quotes import read_book_quotes_latest, read_quote_last_seen

            # WINDOW-SCOPED, NOT SINGLE-DATE (`#379`).
            #
            # Measured live 2026-08-12: soccer reported `quote_rows: 0` to Layer 2
            # while its Layer 1 board served 3,298 rows with a 60-minute seen-age.
            # Both readings were current and they contradicted each other.
            #
            # Soccer shards by KICKOFF date, not capture date, so today's captures
            # land in `2026-08-15.jsonl`, `2026-08-16.jsonl` and beyond -- and
            # `2026-08-12.jsonl` really is empty, because almost nothing kicks off
            # today. Asking one date for a sport that does not store by that date
            # returns nothing forever, not just on quiet days. Layer 1 has scoped
            # by `resolve_window_dates` since `#329`; Layer 2 never did, so soccer
            # could not reach it on ANY day.
            #
            # Single-date sports resolve to a one-element window, so this is a
            # no-op for mlb/nba/wnba/nhl/ncaab and additive for nfl (5) and
            # ncaaf (3), whose fixtures also span days.
            from syndicate.features.shared.layer1_board import resolve_window_dates

            window_dates = resolve_window_dates(sport, selected_date, window="slate") or [selected_date]
            quote_rows = []
            dates_with_rows: list[str] = []
            # A CORRUPT SHARD AND AN EMPTY ONE MUST NOT RENDER AS THE SAME ZERO.
            #
            # `#379` wrapped this read in a per-date `try/except: continue` so one
            # bad date could not lose the other six -- correct, and still the
            # behaviour below. But the exception it swallows used to propagate to
            # the whole-sport handler, which records `{"error": ...}` into
            # `per_sport_stats` (:387). Nothing recorded it after that, so a sport
            # whose shard raised on EVERY date reported a clean `quote_rows: 0`
            # and was indistinguishable from a sport with no slate.
            #
            # Caught by `test_one_sport_failing_does_not_lose_the_others`, which
            # asserts both halves: the other sport survives AND the failure is
            # visible. The first half passed throughout; only the reporting was
            # lost.
            read_errors: dict[str, str] = {}
            for window_date in window_dates:
                try:
                    # `#435`. LATEST-PER-KEY. `build_book_grid` below already
                    # keeps only the freshest row per key (`book_grid.py:156`,
                    # `:225`) and its reduce key equals `_KEY_FIELDS`, so the
                    # grid cannot tell this from the full shard -- verified
                    # byte-for-byte against the real 207MB 2026-08-09 shard.
                    #
                    # This loop is why it matters here most: it EXTENDS across a
                    # window, so NFL accumulated five shards at once.
                    chunk = read_book_quotes_latest(sport, window_date)
                except Exception as exc:
                    # Recorded, then skipped -- resilience unchanged.
                    read_errors[str(window_date)] = f"{type(exc).__name__}: {exc}"
                    continue
                if chunk:
                    quote_rows.extend(chunk)
                    dates_with_rows.append(window_date)
            if not quote_rows:
                # #296. Zero quotes means one of two things and they must not
                # look alike: the sweep has NOT RUN YET, or it ran and the sport
                # has no slate. The board is quote-driven, so a sport in the
                # first state does not degrade -- it VANISHES, which is
                # indistinguishable from being broken.
                #
                # Measured 2026-08-09 02:58Z: MLB had 15 scheduled games and no
                # quote log at all, because MLB capture for a date begins
                # ~06:43Z (first captured_at on the 08-08 log). So for ~6 hours
                # nightly the biggest sport is simply missing from the board
                # with no marker -- exactly when someone is most likely looking.
                #
                # The schedule is known hours before the odds are, so the chip
                # count is what separates the two. Asked with an empty grid: it
                # loads the same chips and reports `rows_matched: 0`, which is
                # the honest answer here.
                try:
                    scheduled = int(
                        (attach_game_state([], sport=sport, selected_date=selected_date) or {}).get("chips") or 0
                    )
                except Exception:
                    scheduled = 0
                per_sport_stats[sport] = {
                    "quote_rows": 0,
                    "grid_rows": 0,
                    "opportunities": 0,
                    "scheduled_games": scheduled,
                    # WHICH dates were asked. A zero against a 7-day window is a
                    # different fact from a zero against one date, and the old
                    # payload could not tell them apart.
                    "window_dates": list(window_dates),
                    # A zero must be attributable -- same contract as
                    # `rows_stale_kickoff` and audit_slate_coverage's THIN.
                    "sweep_state": "pending" if scheduled > 0 else "no_slate",
                }
                if read_errors:
                    # `error` is the key the whole-sport handler (:387) uses, so a
                    # consumer checks one key regardless of where the failure was
                    # caught. `read_errors` keeps the per-date detail, because
                    # "one date of seven failed" and "all seven failed" are
                    # different operational facts.
                    per_sport_stats[sport]["error"] = (
                        f"quote read failed for {len(read_errors)} of "
                        f"{len(window_dates)} window dates: "
                        + "; ".join(f"{d} -> {e}" for d, e in sorted(read_errors.items()))
                    )
                    per_sport_stats[sport]["read_errors"] = dict(read_errors)
                continue
            # Last-seen turns the grid's single age into two: time since the
            # price MOVED, and time since we LOOKED. Only the second is
            # staleness, and scoring was discounting stable markets for the
            # first. Empty for dates whose state predates the tracking, which
            # leaves `seen_age_seconds` absent and the old behaviour intact.
            last_seen_error: str | None = None
            try:
                last_seen = read_quote_last_seen(sport, selected_date)
            except Exception as exc:
                # Swallowing this is correct -- last-seen is an enhancement and
                # its absence must not fail the build -- but swallowing it
                # SILENTLY is not. Measured 2026-08-09: `quote_seen_age_seconds`
                # was null on 200/200 served rows and `freshness_factor` sat at
                # 0.25 (the harshest discount) on every one, and nothing in the
                # payload could distinguish "the sidecar never reached this
                # service" from "it loaded and matched nothing".
                last_seen = {}
                last_seen_error = f"{type(exc).__name__}: {exc}"
            grid = build_book_grid(quote_rows, max_rows=max_grid_rows_per_sport, last_seen=last_seen)

            # ENRICH BEFORE RANKING. Without these three the persisted board is
            # unusable, and each failure is silent rather than empty:
            #
            #   game state  -> opportunity_gate reads `game_state`/`is_live`.
            #                  Absent, every row looks pregame and a SETTLED
            #                  MARKET CAN RANK.
            #   projections -> `edge_vs_market_pct`, the only probability-space
            #                  model view. Absent, `model_edge_pct` is null on
            #                  every row (#263) and blended_score falls back to
            #                  EV alone -- which under proportional devig is
            #                  `1/overround - 1`, IDENTICAL for every side of a
            #                  market. The board then ranks markets by hold and
            #                  picks a side by tie-break.
            #   margin      -> fair value for one-sided rows; without it they
            #                  carry none at all.
            #
            # Same functions the serve-time endpoint calls, so the board a user
            # reads and the board that is persisted cannot drift.
            #   live        -> the LIVE re-sim's number. Absent, every live row
            #                  on the board shows its PREGAME full-game
            #                  projection beside a live line, which is two
            #                  different quantities. Measured 2026-08-16 19:16Z:
            #                  54 live rows, all carrying
            #                  `projection.source = "game_simulation"` (pregame)
            #                  and none carrying a live one, because THESE TWO
            #                  JOINS WERE NEVER CALLED HERE -- they ran only for
            #                  the serve-time `/api/board/book-grid` endpoint.
            #                  That is the drift this loop's own comment below
            #                  says must not happen.
            enrichment: dict[str, object] = {}
            for step, fn in (
                ("game_state", lambda: attach_game_state(grid, sport=sport, selected_date=selected_date)),
                ("projections", lambda: attach_projections(grid, sport=sport, selected_date=selected_date)),
                ("margin_model", lambda: attach_margin_model(grid)),
                # Same functions the serve-time endpoint calls
                # (`_attach_book_grid_*` in `blueprints/intelligence.py`), for
                # the reason stated above the loop. Both read a PUBLISHED
                # snapshot and neither triggers a re-sim -- that path is
                # `refuse_if_compute_in_request_path` and belongs to
                # live-odds-worker's tick, so this stays a read.
                (
                    "live_projections",
                    (
                        (lambda: attach_live_projections_for_sport(grid, sport=sport, selected_date=selected_date))
                        if attach_live_projections_for_sport is not None
                        else None
                    ),
                ),
                (
                    "live_gamelines",
                    (
                        (lambda: attach_live_gamelines_for_sport(grid, sport=sport, selected_date=selected_date))
                        if attach_live_gamelines_for_sport is not None
                        else None
                    ),
                ),
            ):
                if fn is None:
                    # ABSENT, and say which absence it is. "not on this deploy"
                    # and "ran and matched nothing" need different fixes, and
                    # `#296`'s whole point is that they must not look alike.
                    enrichment[step] = {"supported": False, "reason": "not present on this deploy"}
                    continue
                try:
                    enrichment[step] = fn()
                except Exception as exc:  # never let enrichment break the build
                    enrichment[step] = {"error": f"{type(exc).__name__}"}

            result = build_layer2_rows(grid, openings=openings_index)
            sport_opportunities = list(result.get("opportunities") or [])
            # `sport` is carried on the grid row already, but stamp defensively:
            # select_shortlist buckets per sport and a missing slug would
            # collapse every sport into one bucket.
            for row in sport_opportunities:
                if not str(row.get("sport") or "").strip():
                    row["sport"] = sport
            opportunities.extend(sport_opportunities)
            # BOTH numbers, because either alone is ambiguous. `last_seen_keys`
            # is what this service could READ (0 => the `.state.json` sidecar
            # never crossed to this disk, or predates the 3-element format);
            # `cells_with_seen_age` is what actually JOINED (>0 keys but 0 cells
            # => the sidecar is here and the key shapes disagree). Reporting one
            # without the other cannot tell a delivery gap from a join gap.
            # Counted defensively: an instrument that can raise is worse than no
            # instrument, and this one walks a nested shape it does not own.
            cells_with_seen_age = 0
            try:
                for grid_row in grid:
                    if not isinstance(grid_row, Mapping):
                        continue
                    for by_side in (grid_row.get("cells") or {}).values():
                        if not isinstance(by_side, Mapping):
                            continue
                        for cell in by_side.values():
                            if isinstance(cell, Mapping) and cell.get("seen_age_seconds") is not None:
                                cells_with_seen_age += 1
            except Exception:
                cells_with_seen_age = -1  # walked and failed, distinct from a real 0
            per_sport_stats[sport] = {
                "quote_rows": len(quote_rows),
                "window_dates": list(window_dates),
                "dates_with_rows": list(dates_with_rows),
                # Stated even when rows DID come back: a window that lost 3 of 7
                # dates to unreadable shards still serves a board, and silently
                # serving a partial one is the failure mode this whole block
                # exists to prevent.
                **(
                    {
                        "error": (
                            f"quote read failed for {len(read_errors)} of "
                            f"{len(window_dates)} window dates: "
                            + "; ".join(f"{d} -> {e}" for d, e in sorted(read_errors.items()))
                        ),
                        "read_errors": dict(read_errors),
                    }
                    if read_errors
                    else {}
                ),
                "grid_rows": int(result.get("rows_in") or 0),
                # Stated on BOTH branches on purpose: a consumer that has to
                # infer "swept" from the absence of a key cannot tell it from a
                # payload written before this field existed.
                "sweep_state": "swept",
                "scheduled_games": int(
                    ((enrichment.get("game_state") or {}) if isinstance(enrichment.get("game_state"), dict) else {}).get("chips")
                    or 0
                ),
                "last_seen_keys": len(last_seen),
                "cells_with_seen_age": cells_with_seen_age,
                **({"last_seen_error": last_seen_error} if last_seen_error else {}),
                # Visible on purpose: "rows_with_projection: 0" is the signal that
                # #263 has regressed, and it is invisible from a row count.
                "enrichment": enrichment,
                "rows_with_model_edge": sum(
                    1 for row in sport_opportunities if row.get("model_edge_pct") is not None
                ),
                "sides_priced": int(result.get("sides_priced") or 0),
                "candidates": int(result.get("candidates") or 0),
                "scored": int(result.get("scored") or 0),
                "opportunities": len(sport_opportunities),
                "by_lane": result.get("by_lane") or {},
                # `#444`. BOTH halves of the bettable-book restriction, for the
                # reason every other rejection counter in this pipeline is
                # reported: a rule that trims silently cannot be told apart
                # from a thin slate.
                #
                # ADDED AFTER THE FILTER SHIPPED, which is the whole lesson.
                # `build_layer2_rows` returned these from the same commit that
                # introduced the rule -- and they still reached nobody, because
                # THIS dict is an explicit key list and a new key on the
                # producer does not appear in it. Measured on the served
                # payload 2026-08-16 18:52:57Z: the filter was demonstrably
                # working (best-book-outside-the-list 27 -> 0) and both of its
                # counters read `None` at every level of the payload. The
                # filter worked and was invisible.
                #
                # `#397`'s discipline says add the counter in the same commit
                # as the rule. It is not enough: the counter has to be added
                # everywhere the payload is ASSEMBLED, and on this path that is
                # three places, not one.
                "no_bettable_book": int(result.get("no_bettable_book") or 0),
                "repriced_to_bettable": int(result.get("repriced_to_bettable") or 0),
            }
        except Exception as exc:
            per_sport_stats[sport] = {"error": f"{type(exc).__name__}: {exc}"}
            continue

    # Selection policy is layer2_board's, not re-specified here: 100 per sport,
    # floor 30 per kind, remainder on merit, unused floor flowing to the other
    # kind. That floor is load-bearing -- without it MLB's 1,221 prop rows would
    # plausibly take all 100 slots from its 229 game rows, and a hard 50/50
    # would drop a better prop to seat a worse game line.
    #
    # `horizon_days` is the ONE knob passed through: the default (1 = today and
    # tomorrow) scopes the shortlist, and None gives the Forward view over the
    # same rows. Sentinel rather than None-as-default, because None is a
    # MEANINGFUL value here and a plain `horizon_days=None` default would make
    # the Forward view unreachable while looking like it was the default.
    try:
        if horizon_days is _UNSET:
            shortlist = select_shortlist(opportunities)
        else:
            shortlist = select_shortlist(opportunities, horizon_days=horizon_days)
    except Exception as exc:
        return {
            "rows": [],
            "error": f"select_shortlist failed: {type(exc).__name__}: {exc}",
            "per_sport_ingest": per_sport_stats,
        }

    # `per_sport_ingest`, NOT `per_sport`: select_shortlist already returns a
    # per_sport report (what was SELECTED per sport) and overwriting it would
    # silently destroy the selection accounting. These stats are the other half
    # -- what came IN per sport -- and the two together are what makes a sport
    # showing zero rows attributable to its slate rather than to a broken read.
    shortlist["per_sport_ingest"] = per_sport_stats
    shortlist["opportunities_considered"] = len(opportunities)

    # BOARD CARDS ARE BUILT HERE, ON THE WORKER, AND PERSISTED.
    #
    # They were briefly translated at serve time instead, inside
    # `_hydrate_board_response_payload`. That was wrong twice over: it put a
    # per-request transformation over every shortlist row into the web service,
    # which reads artifacts and does not compute; and it meant the artifact was
    # not what the board actually showed, which defeats the reason L2-A is
    # worker-side at all -- settlement needs a record of what was RECOMMENDED,
    # and a card derived per request is not recorded anywhere.
    #
    # Web now reads `cards` and slices them by sport. A slice is a read-time
    # narrowing of persisted data, which is what
    # slice_intelligence_board_state_for_request already does; a field mapping
    # is not.
    # MOVEMENT IS JOINED FROM THE OPENING LEDGER, AND THE LOAD HAPPENS HERE --
    # ONCE PER BUILD, OUTSIDE THE PER-ROW LOOP.
    #
    # That placement IS the fix for `#372`. The previous movement
    # implementation called `load_odds_history_payload_for_sport` inside the
    # per-row card builder; the MLB shard is ~20MB and `#370` made a miss load a
    # second one, which stalled the whole shortlist build -- 70 minutes of no
    # `LAYER2_SHORTLIST` line, no exception, no failure log. The disabled
    # function's own docstring named the remedy: use the place that already
    # holds the data.
    #
    # `load_openings` reads one small JSONL of the rows THIS BOARD published
    # today (~100/sport), which `record_openings` writes a few lines below. So
    # the read is of our own output, not of the full quote history, and
    # `_movement_from_opening` does no IO at all.
    #
    # Read BEFORE `record_openings` runs, deliberately: that call appends
    # today's rows, and movement must compare against the FIRST time we
    # published a row, not against the copy we are writing this instant.
    # THE CALLER MUST TOLERATE AN OLDER CALLEE, AND THIS COST A PRODUCTION
    # INCIDENT TO LEARN (2026-08-16 20:34Z).
    #
    # These two files deploy as separate blobs onto a long-lived worker, so
    # there is no instant at which they are guaranteed to be the same vintage.
    # Deploy `c324447d` shipped THIS file carrying `openings=` while
    # `layer2_board.py` on the worker still had the one-argument signature:
    # `TypeError: unexpected keyword argument 'openings'` -> caught by the
    # `except` below -> `cards = []` -> and because `layer2_is_primary` is True
    # with `legacy_candidate_count` 0, **a blank board**, announced only by a
    # `cards_error` string nobody reads.
    #
    # The guard for that was a message to the deploying session. A message is
    # not a guard. So: ASK THE CALLEE WHAT IT ACCEPTS, then call it that way.
    # `inspect.signature` rather than `except TypeError`, because a bare
    # TypeError retry cannot tell "that parameter does not exist" from a real
    # TypeError raised INSIDE the function, and would silently drop movement on
    # a genuine bug.
    #
    # Degrading to a board WITHOUT movement is the correct failure: movement is
    # an enrichment, the rows are already correct, and a board that ranks
    # without a movement term is the board that shipped for months.
    cards_compat_note = None
    try:
        import inspect

        from syndicate.features.shared.layer2_board import layer2_rows_to_board_cards

        rows_for_cards = shortlist.get("rows") or []
        try:
            accepts = "openings" in inspect.signature(layer2_rows_to_board_cards).parameters
        except (TypeError, ValueError):
            accepts = False
        if accepts:
            shortlist["cards"] = layer2_rows_to_board_cards(rows_for_cards, openings=openings_index)
        else:
            # Older `layer2_board.py` on this worker. Build the board it CAN
            # build rather than no board at all, and say so -- an unexplained
            # empty movement column is `#368`'s defect over again.
            shortlist["cards"] = layer2_rows_to_board_cards(rows_for_cards)
            cards_compat_note = (
                "layer2_board.layer2_rows_to_board_cards has no `openings` parameter on this "
                "deploy; cards built WITHOUT movement/steam. Ship layer2_board.py alongside "
                "pipeline/layer2_shortlist.py to restore it."
            )
    except Exception as exc:
        shortlist["cards"] = []
        shortlist["cards_error"] = f"{type(exc).__name__}: {exc}"
    if cards_compat_note:
        shortlist["cards_compat_note"] = cards_compat_note

    # Both numbers, so "no movement on the board" is attributable: 0 openings
    # loaded is a different fact from openings loaded and nothing having moved.
    # BOTH numbers, because either alone is unattributable -- the third time
    # this lesson has been paid for in this file. `openings_records` is what the
    # ledger HELD; `openings_loaded` is how many distinct bets that collapsed
    # to. Thin movement is then separable into "the ledger is sparse" (records
    # low) versus "the key does not join" (records high, matched low), which is
    # exactly the distinction I had to infer by hand at 21:02Z because neither
    # number was published.
    shortlist["openings_records"] = openings_records
    shortlist["openings_loaded"] = len(openings_index)
    # The join's own hit rate, computed over the rows actually published. A
    # coverage number that lives only in my head is how "movement is thin" went
    # three hours without a cause.
    try:
        # Imported HERE, not reused from the loader block above: those names are
        # bound inside a `try` that can fail, and a NameError raised while
        # computing an instrument would take the build down for the sake of a
        # counter.
        from syndicate.features.shared.layer2_board import (
            _movement_is_tracked,
            movement_join_key as _movement_key,
        )

        published = shortlist.get("rows") or []
        eligible = [r for r in published if _movement_is_tracked(r.get("market"))]
        matched = sum(1 for r in eligible if _movement_key(r) in openings_index)
        shortlist["movement_eligible_rows"] = len(eligible)
        shortlist["movement_rows_matched"] = matched
    except Exception:
        # An instrument that can break the build is worse than no instrument.
        shortlist["movement_eligible_rows"] = -1
        shortlist["movement_rows_matched"] = -1
    if openings_error:
        shortlist["openings_error"] = openings_error

    # RECORD THE OPENING PRICE OF EVERY ROW WE ARE ABOUT TO PUBLISH (audit §7 #1).
    #
    # The comment above says settlement needs a record of what was RECOMMENDED.
    # It does, and until now that record existed in exactly one place --
    # `evaluation_ledger_chunks/<date>.jsonl` -- which is unreadable in
    # practice. Measured 2026-08-14: its 2026-08-05 chunk is 367,229,260 bytes
    # and refresh-worker SKIPS it (`SKIP_OVERSIZED_LEDGER_CHUNK ...
    # ceiling=256000000`), and 19 of the 21 dates in the window do not exist at
    # all. Meanwhile the CLOSE for those same markets is recoverable for ~100%
    # of them from odds history. So the opening was the missing half, and every
    # build that published rows without recording them lost that day's CLV
    # permanently. Unrecorded is unrecoverable.
    #
    # HERE rather than in `intelligence_state`, because both the heavy path and
    # `_refresh_layer2_shortlist_only` reach the board through this function --
    # wiring the two call sites separately is how one of them silently stops
    # recording. First-sighting-only, so this appends the number of NEW markets
    # per day (kilobytes), not one row per tick.
    #
    # Never raises, per this function's contract: a board that already works
    # must not be taken down by instrumentation added beside it.
    try:
        from syndicate.features.shared.clv_opening_ledger import (
            opening_ledger_enabled,
            record_openings,
        )

        if opening_ledger_enabled():
            shortlist["clv_openings"] = record_openings(
                shortlist.get("rows") or [], date=str(selected_date or "")
            )
    except Exception as exc:
        shortlist["clv_openings_error"] = f"{type(exc).__name__}: {exc}"
    return shortlist
