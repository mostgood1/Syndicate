"""Join the LIVE re-sim's projections onto board rows for in-progress games.

WHY THIS EXISTS. The board suppresses every edge on a live game, correctly,
because `attach_projections` reads the PREGAME `daily_summary` and a pregame
model priced against a re-priced market yields the score, not an edge (`#340`,
and the 2026-07-12 measurement behind it: a +23-point "edge" on a coin-flip).

But a live-aware projection ALREADY EXISTS and nothing joins it. MLB's live lens
runs a vendored 120-sim-per-live-game Monte Carlo on live-odds-worker's tick and
emits, per prop: `liveProjection`, `modelProbOver`, `actualSoFar`. Measured
2026-08-10: 4 live MLB games, 862 projected rows, **0 with an edge** -- while the
re-sim was producing live numbers for those same games on another service.

So this is a JOIN, not a model. The board reads one artifact and the live sim
writes another, which is the same cross-artifact blindness that hid the starved
shard (`#331`) and the sidecar.

WHAT THIS DOES NOT DO
---------------------
It never triggers the re-sim. `_live_projection_enhancement_payload` is
explicitly `refuse_if_compute_in_request_path` -- "the one genuinely heavy piece
of live-lens compute" -- so this reads the PUBLISHED snapshot and nothing else.
An absent snapshot yields zero coverage and a stated reason, never a recompute.

It also does not decide whether an edge is allowed. That stays in
`live_edge_policy`, which this feeds by marking a projection live-derived.

THE JOIN IS INSTRUMENTED ON PURPOSE. Market naming differs between the board
(OddsAPI keys: `batter_hits`) and the live lens (its own families), and an
unmeasured join is how settlement ended up at 20.6% with nobody noticing. Every
miss is counted BY REASON so a low rate is attributable on sight rather than
looking like "the sim had no opinion".
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

# Board market key -> the live lens' own market family. The board speaks
# OddsAPI; the live lens speaks the sim's vocabulary. Kept explicit rather than
# fuzzy-matched: a wrong alias silently prices the wrong market, which is worse
# than not joining at all.
_MARKET_ALIASES: dict[str, tuple[str, ...]] = {
    "batter_hits": ("hits", "batter_hits", "h"),
    "batter_home_runs": ("home_runs", "batter_home_runs", "hr"),
    "batter_total_bases": ("total_bases", "batter_total_bases", "tb"),
    "batter_rbis": ("rbis", "batter_rbis", "rbi"),
    "batter_runs_scored": ("runs", "runs_scored", "batter_runs_scored"),
    "batter_hits_runs_rbis": ("hits_runs_rbis", "batter_hits_runs_rbis", "hrr"),
    "batter_stolen_bases": ("stolen_bases", "batter_stolen_bases", "sb"),
    "batter_walks": ("walks", "batter_walks", "bb"),
    "batter_strikeouts": ("batter_strikeouts", "strikeouts_batter"),
    "pitcher_strikeouts": ("strikeouts", "pitcher_strikeouts", "k"),
    "strikeouts": ("strikeouts", "pitcher_strikeouts", "k"),
    "pitcher_outs": ("outs", "pitcher_outs"),
    "outs": ("outs", "pitcher_outs"),
    "pitcher_earned_runs": ("earned_runs", "pitcher_earned_runs", "er"),
    "earned_runs": ("earned_runs", "pitcher_earned_runs", "er"),
    "pitcher_hits_allowed": ("hits_allowed", "pitcher_hits_allowed"),
    "hits_allowed": ("hits_allowed", "pitcher_hits_allowed"),
    "pitcher_walks": ("walks_allowed", "pitcher_walks"),
    "walks_allowed": ("walks_allowed", "pitcher_walks"),
}

_LINE_TOLERANCE = 1e-6


def _build_canonical_markets() -> dict[str, str]:
    """Collapse every alias family to one canonical name, both directions.

    `_MARKET_ALIASES` is a one-way expansion: `batter_hits -> (hits, h)`. That is
    enough when only the board looks up, and it silently fails the moment the
    other side of the join speaks the alias -- `hits` is not a key, so
    `_market_candidates("hits")` returns `("hits",)` and never reaches
    `batter_hits`. The snapshot speaks BOTH vocabularies (measured 2026-08-13:
    `prop` was `hits` on 39 rows and `batter_hits` on 6, for the same market), so
    the map has to be symmetric or the join depends on which name a row happened
    to use.

    Union by family, so direction stops mattering. Families that share no member
    stay separate on purpose: `batter_strikeouts` must NOT merge with the
    pitcher's `strikeouts`, and they do not, because neither family lists the
    other's names.
    """
    parent: dict[str, str] = {}

    def find(name: str) -> str:
        parent.setdefault(name, name)
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            # Longest name wins as the class representative purely for
            # determinism -- the value is never displayed, only compared.
            keep, drop = (ra, rb) if (len(ra), ra) >= (len(rb), rb) else (rb, ra)
            parent[drop] = keep

    for key, aliases in _MARKET_ALIASES.items():
        for alias in aliases:
            union(key, alias)
    return {name: find(name) for name in parent}


_CANONICAL_MARKETS = _build_canonical_markets()


def _norm_name(value: Any) -> str:
    """Player identity for joining: lowercase, punctuation stripped.

    Deliberately NOT a fuzzy match. `J.D. Martinez` vs `JD Martinez` must join;
    `Will Smith` (catcher) vs `Will Smith` (pitcher) is a real collision that a
    fuzzy matcher would hide, and the per-event scoping below is what separates
    them.
    """
    text = str(value or "").strip().lower()
    text = re.sub(r"[.'`]", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _norm_market(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _market_candidates(board_market: Any) -> tuple[str, ...]:
    key = _norm_market(board_market)
    if not key:
        return ()
    aliases = _MARKET_ALIASES.get(key)
    return (key,) + tuple(a for a in (aliases or ()) if a != key)


def _canonical_market(value: Any) -> str:
    """The alias family a market name belongs to, or the name itself."""
    key = _norm_market(value)
    if not key:
        return ""
    return _CANONICAL_MARKETS.get(key, key)


def _snapshot_market(prop: Mapping[str, Any]) -> str:
    """The market a live-lens prop row is actually about.

    `prop` FIRST, AND THIS IS THE WHOLE BUG (`#412`). `market` is a DISPLAY
    GROUPING, not a market: measured on production 2026-08-13, `hitter_props`
    covered hits, total_bases, runs_scored and rbis simultaneously --

        market                prop                    rows
        hitter_props          hits                      39
        hitter_props          total_bases               29
        hitter_total_bases    batter_total_bases        20
        hitter_rbis           batter_rbis               15

    -- so keying on `market` both (a) collided 39 unrelated rows onto one key and
    (b) matched no board market, because the board speaks OddsAPI
    (`batter_hits`). The result was `miss_no_market_alias = 1385 of 1385`: the
    join missed literally every row while the correct key sat in the next field.

    `market` is kept only as a fallback for rows that carry no `prop` at all.
    """
    for field in ("prop", "market"):
        name = _canonical_market(prop.get(field))
        if name:
            return name
    return ""


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _norm_side(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text.startswith("o"):
        return "over"
    if text.startswith("u"):
        return "under"
    return text


def build_live_prop_index(snapshot: Mapping[str, Any] | None) -> dict[str, Any]:
    """Index the published live-lens snapshot by (player, market, line).

    Side is NOT part of the key. The re-sim emits one distribution per
    player-market-line; `modelProbOver` is the over probability and the under is
    its complement, so keying on side would halve coverage for no gain.
    """
    index: dict[tuple[str, str, float], dict[str, Any]] = {}
    games_seen = 0
    rows_seen = 0
    rows_indexed = 0
    live_games = 0
    skipped_no_live_projection = 0
    skipped_no_key = 0

    games = (snapshot or {}).get("games") if isinstance(snapshot, Mapping) else None
    for game in games if isinstance(games, Sequence) else ():
        if not isinstance(game, Mapping):
            continue
        games_seen += 1
        status = game.get("status") if isinstance(game.get("status"), Mapping) else {}
        status_text = f"{status.get('abstract') or ''} {status.get('detailed') or ''}".strip().lower()
        if any(token in status_text for token in ("live", "in progress", "in_progress")):
            live_games += 1
        for prop in game.get("liveProps") if isinstance(game.get("liveProps"), Sequence) else ():
            if not isinstance(prop, Mapping):
                continue
            rows_seen += 1
            player = _norm_name(prop.get("playerName"))
            market = _snapshot_market(prop)
            line = _as_float(prop.get("line"))
            projection = prop.get("liveProjection")
            if not player or not market or line is None:
                skipped_no_key += 1
                continue
            if projection is None:
                # `liveProjection` IS the live-awareness evidence, and nothing
                # else here is. Measured 2026-08-13: 63 of 144 snapshot rows
                # carried `modelProbOver` while `liveProjection`, `modelMean`
                # and `actualSoFar` were ALL null -- a pregame probability
                # sitting in a live-lens row. Indexing those would mark them
                # `live_aware` and hand `live_edge_policy` exactly the pregame
                # edge it exists to suppress, which is worse than no coverage.
                skipped_no_live_projection += 1
                continue
            index[(player, market, line)] = {
                "live_projection": projection,
                "model_prob_over": prop.get("modelProbOver"),
                "actual_so_far": prop.get("actualSoFar") if prop.get("actualSoFar") is not None else prop.get("actual"),
                "live_edge_hint": prop.get("liveEdge"),
                "side": _norm_side(prop.get("selection")),
            }
            rows_indexed += 1

    return {
        "index": index,
        "games_seen": games_seen,
        "live_games": live_games,
        "rows_seen": rows_seen,
        "rows_indexed": rows_indexed,
        "skipped_no_live_projection": skipped_no_live_projection,
        "skipped_no_key": skipped_no_key,
    }


def attach_live_projections(grid: Sequence[Mapping[str, Any]], indexed: Mapping[str, Any]) -> dict[str, Any]:
    """Overlay live projections onto LIVE rows. Returns a coverage payload.

    Only touches rows whose game the board says is live. A pregame row keeps its
    pregame projection untouched -- this adds a live tier, it does not replace
    the model everywhere.
    """
    index = indexed.get("index") if isinstance(indexed, Mapping) else None
    if not isinstance(index, dict):
        return {"supported": False, "reason": "no live snapshot", "rows_live_projected": 0}

    matched = 0
    considered = 0
    miss_no_player = 0
    miss_no_market_alias = 0
    miss_no_line = 0
    unmatched_samples: list[dict[str, Any]] = []

    for row in grid:
        if not isinstance(row, Mapping):
            continue
        game = row.get("game") if isinstance(row.get("game"), Mapping) else {}
        state = str(game.get("state") or "").strip().lower()
        if state not in {"live", "in_progress"}:
            continue
        if str(row.get("kind") or "") != "prop":
            continue
        considered += 1

        player = _norm_name(row.get("player_name"))
        if not player:
            miss_no_player += 1
            continue
        line = _as_float(row.get("line"))
        if line is None:
            miss_no_line += 1
            continue

        hit = None
        for candidate in _market_candidates(row.get("market")):
            hit = index.get((player, _canonical_market(candidate), line))
            if hit is not None:
                break
        if hit is None:
            miss_no_market_alias += 1
            if len(unmatched_samples) < 5:
                unmatched_samples.append(
                    {
                        "player": player,
                        "board_market": row.get("market"),
                        "tried": list(_market_candidates(row.get("market"))),
                        "line": line,
                    }
                )
            continue

        projection = dict(row.get("projection") or {})
        # KEEP THE PREGAME NUMBER RATHER THAN OVERWRITING IT (`#412`). The three
        # numbers a live row needs are the live projection, the pregame sim's
        # projection, and what has ACTUALLY happened so far -- and this used to
        # write the first over the second, so the board could never show the
        # move from "we projected 6.5" to "now 4.2, with 3 already in the book".
        # Only stamp them once: a second tick must not record the live number as
        # the sim's.
        projection.setdefault("sim_projected", projection.get("projected"))
        projection.setdefault("sim_basis", projection.get("basis"))
        projection.setdefault("sim_source", projection.get("source"))
        projection.update(
            {
                "basis": "live_resim",
                "projected": hit["live_projection"],
                "live_projected": hit["live_projection"],
                "model_prob_over": hit.get("model_prob_over"),
                "actual_so_far": hit.get("actual_so_far"),
                "source": "mlb_live_lens_monte_carlo",
                # The policy reads THIS, not the game state -- a live projection
                # against a live market is exactly what should be ranked.
                "live_aware": True,
            }
        )
        # `row` is a live dict in the grid; the caller owns persistence.
        row["projection"] = projection  # type: ignore[index]
        matched += 1

    return {
        "supported": True,
        "rows_live_considered": considered,
        "rows_live_projected": matched,
        "live_games_in_snapshot": indexed.get("live_games"),
        "snapshot_rows_seen": indexed.get("rows_seen"),
        "snapshot_rows_indexed": indexed.get("rows_indexed"),
        # THE CEILING, stated. The snapshot indexes far fewer rows than the
        # board carries (2026-08-13: 81 indexable against 1385 live board rows),
        # so a low `rows_live_projected` is mostly the live lens' own coverage
        # and NOT a broken join. Without these two numbers the two look
        # identical and have completely different fixes.
        "snapshot_skipped_no_live_projection": indexed.get("skipped_no_live_projection"),
        "snapshot_skipped_no_key": indexed.get("skipped_no_key"),
        "miss_no_player": miss_no_player,
        "miss_no_market_alias": miss_no_market_alias,
        "miss_no_line": miss_no_line,
        "unmatched_samples": unmatched_samples,
    }
