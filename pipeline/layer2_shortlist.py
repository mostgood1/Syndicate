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
            from syndicate.features.shared.book_grid import build_book_grid
            from syndicate.features.shared.odds_book_quotes import read_book_quotes, read_quote_last_seen

            quote_rows = read_book_quotes(sport, selected_date)
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
                    # A zero must be attributable -- same contract as
                    # `rows_stale_kickoff` and audit_slate_coverage's THIN.
                    "sweep_state": "pending" if scheduled > 0 else "no_slate",
                }
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
            enrichment: dict[str, object] = {}
            for step, fn in (
                ("game_state", lambda: attach_game_state(grid, sport=sport, selected_date=selected_date)),
                ("projections", lambda: attach_projections(grid, sport=sport, selected_date=selected_date)),
                ("margin_model", lambda: attach_margin_model(grid)),
            ):
                try:
                    enrichment[step] = fn()
                except Exception as exc:  # never let enrichment break the build
                    enrichment[step] = {"error": f"{type(exc).__name__}"}

            result = build_layer2_rows(grid)
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
    try:
        from syndicate.features.shared.layer2_board import layer2_rows_to_board_cards

        shortlist["cards"] = layer2_rows_to_board_cards(shortlist.get("rows") or [])
    except Exception as exc:
        shortlist["cards"] = []
        shortlist["cards_error"] = f"{type(exc).__name__}: {exc}"
    return shortlist
