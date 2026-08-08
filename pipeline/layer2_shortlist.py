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
            from syndicate.features.shared.book_grid import build_book_grid
            from syndicate.features.shared.odds_book_quotes import read_book_quotes

            quote_rows = read_book_quotes(sport, selected_date)
            if not quote_rows:
                per_sport_stats[sport] = {"quote_rows": 0, "grid_rows": 0, "opportunities": 0}
                continue
            grid = build_book_grid(quote_rows, max_rows=max_grid_rows_per_sport)
            result = build_layer2_rows(grid)
            sport_opportunities = list(result.get("opportunities") or [])
            # `sport` is carried on the grid row already, but stamp defensively:
            # select_shortlist buckets per sport and a missing slug would
            # collapse every sport into one bucket.
            for row in sport_opportunities:
                if not str(row.get("sport") or "").strip():
                    row["sport"] = sport
            opportunities.extend(sport_opportunities)
            per_sport_stats[sport] = {
                "quote_rows": len(quote_rows),
                "grid_rows": int(result.get("rows_in") or 0),
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
    return shortlist
