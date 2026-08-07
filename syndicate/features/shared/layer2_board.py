"""L2-A candidate builder — turns the Layer 1 market grid into ranked bets.

**A WORKER-SIDE BUILDER. It must not be called from a request path.** Its output
belongs in an artifact that web reads; see the integration note at the bottom.
That is CLAUDE.md's load-bearing rule (web reads precomputed artifacts, workers
compute), and `_build_candidate_pool` already enforces it with
`refuse_if_compute_in_request_path`.

There is a second reason, specific to Layer 2 and arguably stronger: **a board
computed per request cannot be settled.** S6 needs a record of what was
recommended and at what price. Recompute it on every read and there is nothing
to grade against, so `settled: 0` stays 0 structurally rather than for want of a
settlement run.

WHY THIS EXISTS. Plan §3 is one row contract, five views. Layer 2 built its own
candidate pool while Layer 1 built a much better one, and they disagreed badly —
measured on production 2026-08-07, MLB:

    Layer 1   2,726 priced market instances   (1,221 prop rows with books)
    Layer 2     229 game candidates           (   18 prop rows)

L2's prop lane saw **18 rows against L1's 1,221**. Not stale — starved. And
props are where the sim differentiates us and where 95.5% of OddsAPI spend goes.

A ROW HERE IS A BET, NOT A MARKET. The grid row holds every side; Layer 2 ranks
one side at a time, because that is the thing you can actually place. So each
grid row fans out to at most one candidate per side.

WHAT IS NOT SOLVED HERE, stated so nobody reads a ranked board as a validated
one: `_SCORE_SIM_WEIGHT = 0.5` is a stated prior nobody has measured, and
`settled: 0` means it has never been checked against outcomes. This makes the
board *flow* and be *correct*; S6 is what would make it *proven*.

INTEGRATION (not yet wired — deliberately):
    `_build_candidate_pool` in `pipeline/intelligence_state.py` is where these
    rows belong, so they flow into the existing state artifact that web already
    reads via `read_intelligence_board_state`. That function is also the exact
    path that OOM-killed refresh-worker repeatedly, so feeding it a much larger
    row set is a memory change and must be measured, not assumed. Build first,
    measure, then wire.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from syndicate.features.shared import opportunity_gate
from syndicate.features.shared.opportunity_signals import (
    blended_score,
    devig,
    expected_value_pct,
)

# Identity carried from the market row onto every candidate. Kept explicit
# rather than copying the whole row: the grid row holds `cells` (every book x
# every side), which is large and has no business in a shortlist payload.
_IDENTITY_FIELDS = (
    "sport",
    "event_id",
    "kind",
    "market",
    "segment",
    "line",
    "player_name",
    "home_team",
    "away_team",
    "commence_time",
)


# The persisted SHORTLIST, per sport. Not a memory bound -- a readability one.
#
# Sized against measurement, and the headroom is deliberate: ~1.0 KB per row
# (11MB / 10,765 rows measured on production 2026-08-07), so 50 rows is ~50 KB
# per sport. Every one of the eight sports is never in season at once -- four
# had a slate on the day this was written -- so the realistic persisted cost is
# ~400 KB against a 2.4 MB state and a 24 MB export budget. An out-of-season
# sport contributes no rows and therefore no budget, automatically -- which is
# what buys the headroom for 100 rather than 50.
#
# NAMED FOR THE JOB IT DOES, per post-mortem rule 9: this bounds HOW MANY ROWS A
# PERSON READS. It is not a memory ceiling, and it must not be reused as one --
# `_MLB_CARDS_CONTEXT_CACHE_MAX_ENTRIES` bounded count while the caller needed
# bytes, and that was invisible for three weeks. The writer logs the bytes it
# actually persisted so the real constraint stays observable.
SHORTLIST_ROWS_PER_SPORT = 100

# Each kind is guaranteed this many slots before merit takes over.
#
# A pure score ranking would not mix: MLB carries 1,221 prop rows against 229
# game rows, so props would plausibly take all 50 and the game board would
# vanish. A hard 25/25 is the opposite error -- it would drop a clearly better
# prop to seat a worse game line. Floor-then-merit gets the mix without paying
# for it in quality, and an unused floor flows to the other kind rather than
# being wasted on a sport that has only one.
SHORTLIST_KIND_FLOOR = 30


def _as_float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _fair_by_side(row: Mapping[str, Any], sides: list[str]) -> tuple[dict[str, float], str | None]:
    """No-vig fair probability per side, and how it was obtained.

    Two-sided is the real thing (#238). The margin model fills one-sided rows
    and is labelled differently on purpose, so a modelled fair can never be
    mistaken for a measured consensus.
    """
    best = row.get("best") or {}
    prices = [(_as_float((best.get(side) or {}).get("price")), side) for side in sides]
    if len(prices) >= 2 and all(price is not None for price, _ in prices):
        probabilities = devig([price for price, _ in prices])
        if probabilities and len(probabilities) == len(prices):
            return ({side: probabilities[i] for i, (_, side) in enumerate(prices)}, "two_sided")

    modelled = row.get("modelled_fair") or {}
    out: dict[str, float] = {}
    for side in sides:
        probability = _as_float((modelled.get(side) or {}).get("fair_probability"))
        if probability is not None:
            out[side] = probability
    return (out, "book_margin_model" if out else None)


def _model_edge_for(row: Mapping[str, Any], side: str) -> float | None:
    """The sim's disagreement with the market, in POINTS OF PROBABILITY.

    Only `edge_vs_market_pct` qualifies. A mean-based `edge_vs_line` (WNBA, and
    soccer away from its one probability line) is in units of the stat — runs,
    rebounds, goals — and adding that to an EV percentage would be adding
    rebounds to percent. Those rows rank on EV alone, which is correct: we have
    no probability-space model view for them.
    """
    projection = row.get("projection")
    if not isinstance(projection, Mapping):
        return None
    edge = _as_float(projection.get("edge_vs_market_pct"))
    if edge is None:
        return None
    # The projection is stated from one side; flip it for the other.
    projected_side = str(projection.get("side") or "").strip().lower()
    if projected_side and projected_side != str(side).strip().lower():
        return -edge
    return edge


def build_layer2_rows(grid: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Fan a market grid out into ranked, gated one-side candidates."""
    candidates: list[dict[str, Any]] = []
    lanes: dict[str, int] = {}
    rows_in = 0
    sides_priced = 0
    scored = 0

    for row in grid:
        rows_in += 1
        sides = [str(side) for side in (row.get("sides") or []) if side]
        if not sides:
            continue
        fair_by_side, fair_method = _fair_by_side(row, sides)
        best = row.get("best") or {}
        game = row.get("game") if isinstance(row.get("game"), Mapping) else None

        for side in sides:
            side_best = best.get(side) or {}
            price = side_best.get("price")
            if price is None:
                continue
            sides_priced += 1
            fair = fair_by_side.get(side)
            quote = {
                "price": price,
                "bookmaker": side_best.get("bookmaker"),
                "book_age_seconds": side_best.get("age_seconds"),
                "books_quoting": side_best.get("books_quoting"),
                "fair_probability": fair,
                "fair_method": fair_method if fair is not None else None,
                "suspect_stale": bool(side_best.get("suspect_stale")),
            }

            candidate: dict[str, Any] = {field: row.get(field) for field in _IDENTITY_FIELDS}
            candidate["side"] = side
            candidate["quote"] = quote
            if game:
                candidate["game"] = dict(game)
                # The gate reads `game_state`/`is_live` at the TOP level; the
                # grid nests it as `game.state`. Without this translation every
                # row looks pregame to the gate, and a settled market ranks --
                # caught by test_dead_market_is_never_ranked, which is exactly
                # the kind of silent contract mismatch #245 exists to prevent.
                candidate["game_state"] = game.get("state")
                candidate["is_live"] = str(game.get("state") or "").strip().lower() == "live"

            # Eligibility BEFORE scoring: a dead market should never be ranked,
            # and the gate is the one place that decision lives (#245).
            opportunity_gate.annotate(candidate, quote)
            lane = str(candidate.get("board_lane") or "unknown")
            lanes[lane] = lanes.get(lane, 0) + 1

            ev = expected_value_pct(price, fair) if fair is not None else None
            model_edge = _model_edge_for(row, side)
            score = blended_score(
                ev_pct=ev,
                model_edge=model_edge,
                books_quoting=side_best.get("books_quoting") or row.get("books_quoting"),
                book_age_seconds=side_best.get("age_seconds"),
            )
            candidate["ev_pct"] = ev
            candidate["model_edge_pct"] = model_edge
            candidate["score"] = score
            if score is not None:
                scored += 1
            candidates.append(candidate)

    opportunities = [
        candidate
        for candidate in candidates
        if candidate.get("board_lane") == opportunity_gate.LANE_OPPORTUNITY
        and candidate.get("score") is not None
    ]
    # Highest blended score first. Rows with no score are excluded above rather
    # than sorted to the bottom: a row with neither EV nor a model view has
    # nothing to rank, and scoring it zero would place it above genuinely
    # negative rows (blended_score's own reasoning).
    opportunities.sort(key=lambda item: item["score"]["score"], reverse=True)

    return {
        "rows_in": rows_in,
        "sides_priced": sides_priced,
        "candidates": len(candidates),
        "scored": scored,
        "opportunities": opportunities,
        "by_lane": lanes,
    }


def _score_of(row: Mapping[str, Any]) -> float:
    score = row.get("score")
    if isinstance(score, Mapping):
        value = _as_float(score.get("score"))
        if value is not None:
            return value
    return float("-inf")


# How far ahead a row may start and still belong on TODAY's shortlist.
#
# MEASURED 2026-08-07, and it is the reason this parameter exists at all: the
# board was serving 1,244 NFL rows for "today" whose games start **34 to 156 days
# out** -- not one NFL game existed on the date being displayed. Meanwhile MLB
# had 2,168 rows today and 1,840 tomorrow. Under a flat per-sport cap NFL would
# spend a full allowance on markets nobody can act on this week.
#
# "Quoted today" is not "playing today", and conflating them is what made an
# empty sport look like a full board. 1 = today and tomorrow, which keeps the
# overnight boundary usable without importing next month.
#
# This does NOT delete forward-looking markets -- plan §4b wants them, and they
# are the softest lines we see. It scopes the SHORTLIST. A Forward view is a
# different projection over the same rows.
SHORTLIST_HORIZON_DAYS = 1


def _within_horizon(row: Mapping[str, Any], now: datetime, horizon_days: int | None) -> bool:
    if horizon_days is None:
        return True
    raw = row.get("commence_time")
    if not raw:
        # No start time is not evidence of being today. Kept rather than dropped,
        # because dropping it would silently hide a whole sport if a feed stopped
        # stamping starts -- and every non-MLB sport currently ships game.state
        # as None, so this path is not hypothetical.
        return True
    try:
        start = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return True
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    return (start.astimezone(timezone.utc).date() - now.date()).days <= int(horizon_days)


def select_shortlist(
    opportunities: Iterable[Mapping[str, Any]],
    *,
    per_sport: int = SHORTLIST_ROWS_PER_SPORT,
    kind_floor: int = SHORTLIST_KIND_FLOOR,
    horizon_days: int | None = SHORTLIST_HORIZON_DAYS,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The rows that get PERSISTED. Everything else lives in the ledger.

    Two consumers wanted opposite things and sizing one number for both got both
    wrong: the board wants a shortlist (#243 cut 230 rows to 34 on purpose),
    while settlement wants breadth because CLV-derived weights converge on
    volume. They are separated -- this bounds the *display* artifact, and the
    append-only ledger carries every gated row for S6.

    Selection is FLOOR-THEN-MERIT per sport: guarantee each kind its floor, then
    fill the remainder purely by score. An unused floor (a sport with no props,
    or none that survived the gate) flows to the other kind instead of shrinking
    the shortlist.
    """
    reference_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    by_sport: dict[str, list[Mapping[str, Any]]] = {}
    beyond_horizon = 0
    for row in opportunities:
        if not _within_horizon(row, reference_now, horizon_days):
            beyond_horizon += 1
            continue
        sport = str(row.get("sport") or "unknown").strip().lower() or "unknown"
        by_sport.setdefault(sport, []).append(row)

    selected: list[dict[str, Any]] = []
    per_sport_report: dict[str, dict[str, Any]] = {}

    for sport, rows in by_sport.items():
        ranked = sorted(rows, key=_score_of, reverse=True)
        game = [row for row in ranked if str(row.get("kind") or "") == "game"]
        prop = [row for row in ranked if str(row.get("kind") or "") == "prop"]
        other = [row for row in ranked if str(row.get("kind") or "") not in {"game", "prop"}]

        floor = max(0, int(kind_floor))
        limit = max(0, int(per_sport))
        picked: list[Mapping[str, Any]] = []
        picked.extend(game[:floor])
        picked.extend(prop[:floor])

        chosen_ids = {id(row) for row in picked}
        remainder = [row for row in ranked + other if id(row) not in chosen_ids]
        remainder.sort(key=_score_of, reverse=True)
        picked.extend(remainder[: max(0, limit - len(picked))])

        picked = sorted(picked, key=_score_of, reverse=True)[:limit]
        selected.extend(dict(row) for row in picked)
        per_sport_report[sport] = {
            "available": len(rows),
            "selected": len(picked),
            "game": sum(1 for row in picked if str(row.get("kind") or "") == "game"),
            "prop": sum(1 for row in picked if str(row.get("kind") or "") == "prop"),
        }

    selected.sort(key=_score_of, reverse=True)
    return {
        "rows": selected,
        "per_sport": per_sport_report,
        # Only sports with a slate consume budget; the rest contribute nothing.
        "active_sports": sorted(per_sport_report.keys()),
        "per_sport_limit": int(per_sport),
        "kind_floor": int(kind_floor),
        "horizon_days": horizon_days,
        # Logged, not silently dropped: a sport vanishing from the shortlist
        # should be attributable to its schedule rather than look like an outage.
        "rows_beyond_horizon": beyond_horizon,
        "persisted_bytes": len(json.dumps(selected, default=str)),
    }
