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

THE EDGE PRICES `liveModelProbOver` AND NOTHING ELSE (`#414`). The re-sim used
to ship a live MEAN and no live probability -- `modelProbOver` beside it was
bit-identical to the PREGAME value on 24 of 28 live rows (`0.3530785` against
`0.3530785`) while `liveProjection` genuinely moved. Pricing that one produced
`#340` in a live label: three props whose over was ALREADY WON still read
0.659/0.655/0.745, giving +36.5%/+32.3%/+15.8%, more than twice the size of the
honest numbers on a board that sorts by edge.

`#414` fixed the cause rather than the symptom. `estimate_live` already
simulated the rest of the game 120 times and discarded every box score it
produced; it now retains them as per-player remaining-stat histograms, so
P(over) is the empirical share of simulated rest-of-games finishing above the
line, given what is already banked. An already-decided prop falls out as exactly
1.0.

A row the re-sim cannot price keeps a NAMED blank edge. There is deliberately no
fallback to `modelProbOver`, because that would silently restore the defect on
exactly the rows the live model could not reach.

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
    # `#416` READER-SIDE COUNTER. The re-sim demonstrably prices props on
    # live-odds-worker (`LIVE_MC_PRICED outcomes={'priced': 71}`) and the board
    # still served `rows_live_edged: 0`. Between those two facts sits exactly one
    # unobserved hop -- whether the PUBLISHED snapshot carries the field -- and
    # it cannot be read from web, which 404s on that path (it lives in the
    # keyvalue store) and whose own recompute is blind (`simContextAvailable:
    # False` on every game).
    #
    # Two counters, because they answer different questions:
    #   `seen`    -- rows in the snapshot carrying a non-null `liveModelProbOver`
    #   `indexed` -- of those, how many also survived indexing
    # `seen == 0` means the writer's value never reached the artifact.
    # `seen > 0 and indexed == 0` means this function is dropping it.
    rows_with_live_prob_seen = 0
    rows_with_live_prob_indexed = 0
    # AND WHAT THE ROW DOES CARRY, when it does not carry that. An absent field
    # is just another null unless you can see the keyspace it is absent from --
    # the `#412` root cause was exactly a right value under an unexpected key.
    sample_prop_keys: list[str] = []
    # BY GAME STATE, because the flat counter cannot be read (`#416`).
    # Measured 2026-08-13 on a 2-live-game tail: `live_prob_seen: 0` of 67 rows,
    # which reads as "the writer never sent it" and may equally be "65 of those
    # rows were never eligible". A FINAL game's props come from
    # `_final_live_prop_rows_from_registry` -- a different path that never
    # computes a live probability and correctly emits null -- so final rows
    # dilute the denominator with guaranteed zeros. Only the `live` row of this
    # table can falsify anything.
    by_state: dict[str, dict[str, int]] = {}

    def _bucket(state: str) -> dict[str, int]:
        return by_state.setdefault(state, {"rows": 0, "with_live_prob": 0, "with_live_projection": 0})

    games = (snapshot or {}).get("games") if isinstance(snapshot, Mapping) else None
    for game in games if isinstance(games, Sequence) else ():
        if not isinstance(game, Mapping):
            continue
        games_seen += 1
        status = game.get("status") if isinstance(game.get("status"), Mapping) else {}
        status_text = f"{status.get('abstract') or ''} {status.get('detailed') or ''}".strip().lower()
        # FINAL IS CHECKED FIRST. A completed game's detailed state can still
        # carry live-ish wording, and mislabelling one final game as live is
        # exactly what would put a guaranteed-null row into the only bucket that
        # can prove anything.
        if any(token in status_text for token in ("final", "game over", "completed")):
            game_state = "final"
        elif any(token in status_text for token in ("live", "in progress", "in_progress")):
            game_state = "live"
            live_games += 1
        elif any(token in status_text for token in ("preview", "pre-game", "pre_game", "scheduled", "warmup")):
            game_state = "pregame"
        else:
            game_state = "unknown"
        bucket = _bucket(game_state)
        for prop in game.get("liveProps") if isinstance(game.get("liveProps"), Sequence) else ():
            if not isinstance(prop, Mapping):
                continue
            rows_seen += 1
            if not sample_prop_keys:
                # Bounded and name-only: this is a diagnostic, not a payload dump.
                sample_prop_keys = sorted(str(k) for k in prop.keys())[:40]
            has_live_prob = prop.get("liveModelProbOver") is not None
            if has_live_prob:
                rows_with_live_prob_seen += 1
            bucket["rows"] += 1
            if has_live_prob:
                bucket["with_live_prob"] += 1
            if prop.get("liveProjection") is not None:
                # Carried alongside on purpose: a live game with projections but
                # no probabilities is the writer half failing, while neither
                # present means the row was never a live-tier candidate at all.
                bucket["with_live_projection"] += 1
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
                # `#414`: the re-sim's own P(over), from its rest-of-game
                # distribution. Read from its OWN key and never from
                # `modelProbOver`, which is the pregame number.
                "live_prob_over": prop.get("liveModelProbOver"),
                "actual_so_far": prop.get("actualSoFar") if prop.get("actualSoFar") is not None else prop.get("actual"),
                "live_edge_hint": prop.get("liveEdge"),
                "side": _norm_side(prop.get("selection")),
            }
            rows_indexed += 1
            if has_live_prob:
                rows_with_live_prob_indexed += 1

    return {
        "index": index,
        "games_seen": games_seen,
        "live_games": live_games,
        "rows_seen": rows_seen,
        "rows_indexed": rows_indexed,
        "skipped_no_live_projection": skipped_no_live_projection,
        "skipped_no_key": skipped_no_key,
        "rows_with_live_prob_seen": rows_with_live_prob_seen,
        "rows_with_live_prob_indexed": rows_with_live_prob_indexed,
        "sample_prop_keys": sample_prop_keys,
        "by_game_state": by_state,
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
    edged = 0
    edge_blocked = 0
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

        # NO LIVE EDGE, AND THE REASON IS MEASURED RATHER THAN ASSUMED.
        #
        # There is a real ordering bug here: `attach_projections` decides the
        # edge and consults `live_edge_unavailable_reason` BEFORE this overlay
        # runs, so `live_aware` is always False when the policy is asked. The
        # policy was written to permit a live-aware edge and the pipeline could
        # never present it one. Fixing that ordering is a two-line change.
        #
        # IT WAS WRITTEN, AND THEN BACKED OUT, because the edge it produced was
        # the `#340` defect wearing a live label. An edge needs a PROBABILITY,
        # and the live re-sim does not ship one:
        #
        #   live-aware rows: lens `modelProbOver` == pregame prob   24
        #                    differs                                 4
        #
        # Bit-identical -- `0.3530785` against `0.3530785`. `liveProjection`
        # genuinely moves (sim 1.107 -> live 0.646); the probability beside it
        # does not. Pricing it against a re-priced live market is exactly what
        # `live_edge_policy` exists to refuse.
        #
        # The tell, and the reason this was caught rather than shipped: three
        # rows whose over was ALREADY WON (1 hit against a 0.5 line) still
        # carried P(over) of 0.659/0.655/0.745, producing edges of +36.5%,
        # +15.8%, +32.3%. Mean |edge| on already-decided rows was 28.2% against
        # 12.0% on undecided ones -- the fabricated numbers were more than twice
        # the size of the real ones and would have sorted straight to the top of
        # a board built to surface the biggest edges. That is the "+23 points on
        # a coin flip" measurement of `#340`, reproduced.
        #
        # Deriving P(over) from the live MEAN is not the way out either: WNBA
        # already refuses that ("inventing P(over) from a mean would put a
        # fabricated number into EV"). The honest state is a projection with a
        # named reason for its blank edge, and it stays that way until the
        # re-sim emits a live probability.
        # THE EDGE, and the ordering bug that made it unreachable.
        #
        # `attach_projections` decides the edge and consults
        # `live_edge_unavailable_reason` BEFORE this overlay runs, so `live_aware`
        # was always False when the policy was asked. The policy was written to
        # permit a live-aware edge and the pipeline could never present it one.
        #
        # THE FIRST ATTEMPT AT THIS SHIPPED NOTHING AND WAS RIGHT TO. It priced
        # `modelProbOver`, which measurement showed was bit-identical to the
        # pregame probability on 24 of 28 rows -- three props whose over was
        # already WON still read 0.659/0.655/0.745, giving +36.5%/+32.3%/+15.8%,
        # more than twice the size of the honest numbers on a board that sorts by
        # edge. `#414` fixed the actual cause: the re-sim now emits a real live
        # P(over) from its own rest-of-game distribution, so an already-won prop
        # resolves to exactly 1.0 instead of 0.66.
        #
        # ONLY `live_prob_over` IS ACCEPTED HERE. Falling back to
        # `model_prob_over` would silently restore the defect on every row the
        # re-sim could not price, which is the failure mode this whole thread has
        # been about.
        # AN ALREADY-DECIDED PROP IS NOT AN EDGE, it is a settled market.
        #
        # With 1 hit banked against a 0.5 line, `#414`'s live probability is
        # exactly 1.0 -- correct, and against a fair value of 0.30 it computes a
        # +70% edge. There is no bet there: the book has settled or pulled that
        # market, and the only way the price still reads 0.30 is that the quote
        # is stale. Left in, these would be the LARGEST edges on the board and
        # would sort straight to the top, which is the same visible failure the
        # pregame-probability defect produced -- reached by a different route.
        #
        # Same rule `live_edge_policy` already applies to a final game: "the
        # market is settled, so there is no price to beat". A decided prop is a
        # final game scoped to one player.
        banked = hit.get("actual_so_far")
        row_line = _as_float(row.get("line"))
        if banked is not None and row_line is not None and (_as_float(banked) or 0.0) > row_line:
            projection["edge_vs_market_pct"] = None
            projection["edge_unavailable_reason"] = (
                "the over is already decided, so the market is settled and there is "
                "no price to beat"
            )
            edge_blocked += 1
            continue

        live_prob = hit.get("live_prob_over")
        fair = projection.get("market_fair_prob_over")
        if live_prob is None or fair is None:
            projection["edge_vs_market_pct"] = None
            projection["edge_unavailable_reason"] = (
                "live re-sim produced no probability for this market, so there is "
                "nothing honest to price against it"
                if live_prob is None
                else "no market fair value to price the live projection against"
            )
            edge_blocked += 1
            continue
        try:
            # Same formula and inputs as `attach_projections`
            # (`(prob_over - market_fair_prob_over) * 100`), deliberately: a second
            # edge definition for live rows is how two implementations of one
            # number drift apart, which is what retired `book_grid`.
            projection["edge_vs_market_pct"] = round((float(live_prob) - float(fair)) * 100.0, 2)
        except (TypeError, ValueError):
            projection["edge_vs_market_pct"] = None
            projection["edge_unavailable_reason"] = "live edge inputs were not numeric"
            edge_blocked += 1
            continue
        projection["live_prob_over"] = live_prob
        projection.pop("edge_unavailable_reason", None)
        edged += 1

    return {
        "supported": True,
        "rows_live_considered": considered,
        "rows_live_projected": matched,
        # PROJECTED AND EDGED ARE DIFFERENT CLAIMS, and the gap between them is
        # the whole reported symptom -- the first cut served 84 projected rows
        # with 0 edges and looked like a success from the projection count
        # alone. This counts the blank edges as a POSITIVE act with a reason
        # attached, so "we chose not to price this" never again reads the same
        # as "the join failed".
        "rows_live_edged": edged,
        "rows_live_edge_withheld": edge_blocked,
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
        # THE ONE UNOBSERVED HOP (`#416`). `snapshot_live_prob_seen == 0` says
        # the writer's probability never reached the published artifact;
        # `seen > 0` with `rows_live_edged == 0` says it arrived and something
        # here dropped it. Those have opposite fixes and, until now, looked
        # identical from the board.
        "snapshot_live_prob_seen": indexed.get("rows_with_live_prob_seen"),
        "snapshot_live_prob_indexed": indexed.get("rows_with_live_prob_indexed"),
        "snapshot_prop_keys": indexed.get("sample_prop_keys"),
        # THE ROW THAT MATTERS IS `live`. Final-game props come from a registry
        # path that never computes a live probability, so their zeros are
        # correct and meaningless -- pooled with the live rows they turn a
        # falsifiable measurement into an unreadable one.
        "snapshot_by_game_state": indexed.get("by_game_state"),
        "miss_no_player": miss_no_player,
        "miss_no_market_alias": miss_no_market_alias,
        "miss_no_line": miss_no_line,
        "unmatched_samples": unmatched_samples,
    }
