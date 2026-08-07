"""S3 / L1-B: the sim's prop projections, joined to market lines.

This is the differentiator. OddsJam shows what the books think; this shows what
the model thinks next to it, per line. The reference surface is
player-props.com's `Line | Over | Under | Projected | Edge Proj | Edge Eff%`.

READS THE DAILY SUMMARY ARTIFACT DIRECTLY, and that is the whole point.
`build_mlb_market_board` would also produce projections, but it calls
`build_cards_page_context` -- the call whose own docstring records that it
OOM-killed the 2GB refresh-worker, and the call `#253` had to bound. This reads
one ~2.3MB JSON the sim already wrote. S3 stays a serve-time join, like S1.

WHAT THE SIM ACTUALLY GIVES US, which is better than a point estimate
---------------------------------------------------------------------
Pitchers carry full DISTRIBUTIONS (`so_dist`, `outs_dist`, ...), so P(over any
line) is exact rather than assumed-normal. Hitters carry cumulative
threshold probabilities (`hits_1plus`, `total_bases_2plus`, ...), which map
onto half-point lines exactly: a 0.5 line *is* "1 or more".

So `model_prob` is a real modelled probability, not a projection run through a
distributional guess. That distinction is why `edge_pct` here can be compared
against a no-vig market probability honestly.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

# market (as it appears in book_quotes) -> the pitcher distribution that scores it
_PITCHER_DISTS: dict[str, tuple[str, str]] = {
    "strikeouts": ("so_dist", "so_mean"),
    "outs": ("outs_dist", "outs_mean"),
    "hits_allowed": ("hits_dist", "hits_mean"),
    "earned_runs": ("earned_runs_dist", "er_mean"),
    "walks_allowed": ("walks_dist", "walks_mean"),
    "batters_faced": ("batters_faced_dist", "batters_faced_mean"),
    "pitches": ("pitches_dist", "pitches_mean"),
}

# market -> (likelihood bucket prefix, mean field). The bucket for a line is
# derived: line 0.5 -> "<prefix>_1plus", 1.5 -> "_2plus", and so on.
_HITTER_BUCKETS: dict[str, tuple[str, str]] = {
    "batter_hits": ("hits", "h_mean"),
    "batter_total_bases": ("total_bases", "tb_mean"),
    "batter_rbis": ("rbi", "rbi_mean"),
    "batter_runs_scored": ("runs", "runs_mean"),
    "batter_hits_runs_rbis": ("hits_runs_rbis", "hrr_mean"),
    "batter_doubles": ("doubles", "doubles_mean"),
    "batter_triples": ("triples", "triples_mean"),
    "batter_stolen_bases": ("sb", "sb_mean"),
}

_HR_MARKET = "batter_home_runs"


def _norm_name(value: Any) -> str:
    """Normalised player name for joining sim output to quote rows.

    Accents and punctuation differ between feeds -- the same fold `#218`'s team
    matching needed. Kept deliberately simple: lowercase, strip non-letters, and
    collapse whitespace.
    """
    text = str(value or "").strip().lower()
    text = text.replace(".", " ").replace("'", "").replace("-", " ")
    text = re.sub(r"[^a-z ]", " ", text)
    return " ".join(text.split())


def _dist_mean(dist: Mapping[str, Any]) -> float | None:
    total = 0.0
    weighted = 0.0
    for raw_value, raw_count in (dist or {}).items():
        try:
            value = float(raw_value)
            count = float(raw_count)
        except (TypeError, ValueError):
            continue
        if count <= 0:
            continue
        total += count
        weighted += value * count
    return round(weighted / total, 3) if total > 0 else None


def _dist_prob_over(dist: Mapping[str, Any], line: float) -> float | None:
    """P(outcome > line) straight off the simulated distribution.

    Exact, not a normal approximation. A whole-number line is a push on the
    line itself, so strictly-greater is the right comparison and the push mass
    is deliberately excluded from BOTH sides rather than split.
    """
    total = 0.0
    over = 0.0
    for raw_value, raw_count in (dist or {}).items():
        try:
            value = float(raw_value)
            count = float(raw_count)
        except (TypeError, ValueError):
            continue
        if count <= 0:
            continue
        total += count
        if value > line:
            over += count
    return round(over / total, 4) if total > 0 else None


def _bucket_for_line(prefix: str, line: float) -> str | None:
    """`total_bases` + line 1.5 -> `total_bases_2plus`.

    Only half-point lines map cleanly: "over 1.5" is exactly "2 or more". A
    whole-number line carries push mass that a `Nplus` bucket cannot express, so
    it returns None rather than silently answering the wrong question.
    """
    if abs(line - round(line)) < 0.01:
        return None
    threshold = int(math.floor(line)) + 1
    if threshold < 1:
        return None
    return f"{prefix}_{threshold}plus"


class PropProjectionIndex:
    """Lookup from (player, market, line) to what the sim projected."""

    def __init__(self) -> None:
        self._pitchers: dict[str, dict[str, Any]] = {}
        self._hitters: dict[tuple[str, str], dict[str, Any]] = {}
        self._hitter_means: dict[str, dict[str, float]] = {}
        self.games = 0

    # -- build ----------------------------------------------------------
    def ingest_game(self, game: Mapping[str, Any], *, pitcher_names: Mapping[str, str] | None = None) -> None:
        self.games += 1

        # `starter_names` is keyed by SIDE ({"away": "...", "home": "..."})
        # while `pitcher_props` is keyed by PITCHER ID, and nothing in the
        # daily summary links the two -- verified by walking the whole game
        # payload for either id. Guessing from dict order would silently give
        # one starter the other's distribution, which is worse than a blank
        # cell: it is a confident wrong number next to a real price.
        #
        # So the id->name map is supplied by the caller from the roster
        # snapshot (`.away.starter` / `.home.starter` carry {id, name}). When
        # no snapshot exists for the date, pitcher props simply do not project
        # and `coverage` says so.
        id_to_name = {str(k): str(v) for k, v in (pitcher_names or {}).items()}

        for pitcher_id, payload in (game.get("pitcher_props") or {}).items():
            if not isinstance(payload, Mapping):
                continue
            name = _norm_name(id_to_name.get(str(pitcher_id)))
            if not name:
                continue
            self._pitchers[name] = dict(payload)

        for bucket_name, rows in (game.get("hitter_props_likelihood_topn") or {}).items():
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                name = _norm_name(row.get("name"))
                if not name:
                    continue
                self._hitters[(name, str(bucket_name))] = dict(row)
                means = self._hitter_means.setdefault(name, {})
                for key, value in row.items():
                    if isinstance(key, str) and key.endswith("_mean"):
                        try:
                            means[key] = float(value)
                        except (TypeError, ValueError):
                            continue

        hr_payload = game.get("hitter_hr_likelihood_all") or {}
        for row in (hr_payload.get("overall") or []) if isinstance(hr_payload, Mapping) else []:
            if not isinstance(row, Mapping):
                continue
            name = _norm_name(row.get("name"))
            if name:
                self._hitters[(name, "hr_1plus")] = dict(row)

    # -- query ----------------------------------------------------------
    def project(self, *, player_name: Any, market: Any, line: Any) -> dict[str, Any] | None:
        """Projection + modelled P(over) for one market line, or None.

        None is returned rather than a guess whenever the sim cannot answer:
        no such player, no such market, or a whole-number line on a
        threshold-only (hitter) market. A blank cell is honest; an invented
        projection next to a real price is not.
        """
        name = _norm_name(player_name)
        if not name:
            return None
        market_key = str(market or "").strip().lower()
        try:
            line_value = float(line)
        except (TypeError, ValueError):
            return None

        if market_key in _PITCHER_DISTS:
            payload = self._pitchers.get(name)
            if not payload:
                return None
            dist_key, mean_key = _PITCHER_DISTS[market_key]
            dist = payload.get(dist_key)
            if not isinstance(dist, Mapping):
                return None
            projected = payload.get(mean_key)
            try:
                projected = round(float(projected), 3)
            except (TypeError, ValueError):
                projected = _dist_mean(dist)
            return {
                "projected": projected,
                "model_prob_over": _dist_prob_over(dist, line_value),
                "source": "pitcher_distribution",
                "basis": dist_key,
            }

        if market_key == _HR_MARKET:
            row = self._hitters.get((name, "hr_1plus"))
            if not row or abs(line_value - 0.5) > 0.01:
                return None
            prob = row.get("p_hr_1plus_cal", row.get("p_hr_1plus"))
            return {
                "projected": row.get("hr_mean"),
                "model_prob_over": round(float(prob), 4) if prob is not None else None,
                "source": "hitter_threshold",
                "basis": "hr_1plus",
            }

        if market_key in _HITTER_BUCKETS:
            prefix, mean_key = _HITTER_BUCKETS[market_key]
            bucket = _bucket_for_line(prefix, line_value)
            if bucket is None:
                return None
            row = self._hitters.get((name, bucket))
            if not row:
                return None
            prob = None
            for key, value in row.items():
                # The probability field is named for its own threshold
                # (p_h_2plus, p_tb_3plus, ...), so pick the calibrated one if
                # present rather than hard-coding every spelling.
                if isinstance(key, str) and key.startswith("p_") and key.endswith("_cal"):
                    prob = value
                    break
            if prob is None:
                for key, value in row.items():
                    if isinstance(key, str) and key.startswith("p_"):
                        prob = value
                        break
            projected = row.get(mean_key)
            if projected is None:
                projected = (self._hitter_means.get(name) or {}).get(mean_key)
            return {
                "projected": round(float(projected), 3) if projected is not None else None,
                "model_prob_over": round(float(prob), 4) if prob is not None else None,
                "source": "hitter_threshold",
                "basis": bucket,
            }

        return None


def starter_ids_from_roster_snapshots(snapshot_dir: Path | str) -> dict[str, str]:
    """pitcher_id -> name, from a date's roster snapshots.

    The daily summary cannot supply this (see `ingest_game`). Roster snapshots
    can: each carries `.away.starter` and `.home.starter` as {id, name}. One
    small read per game, ~53KB each, and entirely optional -- a missing
    directory yields an empty map and pitcher props go unprojected rather than
    mis-projected.
    """
    mapping: dict[str, str] = {}
    directory = Path(snapshot_dir)
    if not directory.is_dir():
        return mapping
    for path in sorted(directory.glob("roster_*_pk*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for side in ("away", "home"):
            starter = ((payload.get(side) or {}) if isinstance(payload, Mapping) else {}).get("starter")
            if not isinstance(starter, Mapping):
                continue
            pitcher_id = starter.get("id")
            name = starter.get("name")
            if pitcher_id is not None and name:
                mapping[str(pitcher_id)] = str(name)
    return mapping


def load_prop_projections(
    summary_path: Path | str, *, roster_snapshot_dir: Path | str | None = None
) -> PropProjectionIndex:
    """Build the index from one daily-summary artifact.

    `roster_snapshot_dir` is optional and only unlocks PITCHER props. Without
    it hitter props still project; the coverage report distinguishes the two so
    a thin result is attributable rather than mysterious.
    """
    index = PropProjectionIndex()
    path = Path(summary_path)
    if not path.is_file():
        return index
    try:
        # Streaming would not help here: this is a single JSON object, not a
        # JSONL shard, so it must be parsed whole. It is ~2.3MB -- three orders
        # of magnitude under the ledger chunks `#254` had to stream.
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return index
    pitcher_names = (
        starter_ids_from_roster_snapshots(roster_snapshot_dir) if roster_snapshot_dir else {}
    )
    index.pitcher_name_map_size = len(pitcher_names)
    for game in (payload.get("outputs") or []) if isinstance(payload, Mapping) else []:
        if isinstance(game, Mapping):
            index.ingest_game(game, pitcher_names=pitcher_names)
    return index


def _implied(price: Any) -> float | None:
    try:
        value = float(price)
    except (TypeError, ValueError):
        return None
    if value == 0:
        return None
    return (100.0 / (value + 100.0)) if value > 0 else (abs(value) / (abs(value) + 100.0))


def _no_vig_over_probability(row: Mapping[str, Any]) -> float | None:
    """The market's TRUE probability of the over, vig removed.

    Comparing a model probability against a raw book price overstates the edge
    by roughly half the hold -- that is #238's whole finding (median hold 6.25%,
    so every EV was ~3.1 points optimistic). The correction needs BOTH sides, so
    this returns None on a one-sided market rather than pretending.

    Uses the CONSENSUS price per side, not the best: the best price is the most
    generous book, and de-vigging against it would understate the market's real
    view and manufacture edge.
    """
    consensus = row.get("consensus") or {}
    sides = [str(side) for side in (row.get("sides") or [])]
    over_side = next((s for s in sides if s.lower() in {"over", "yes"}), None)
    under_side = next((s for s in sides if s.lower() in {"under", "no"}), None)
    if not over_side or not under_side:
        return None
    over_implied = _implied(consensus.get(over_side))
    under_implied = _implied(consensus.get(under_side))
    if over_implied is None or under_implied is None:
        return None
    total = over_implied + under_implied
    if total <= 0:
        return None
    return round(over_implied / total, 4)


def attach_projections(grid_rows: list[dict[str, Any]], index: PropProjectionIndex) -> dict[str, Any]:
    """Stamp `projection` onto each grid row that the sim can answer for.

    Returns coverage, because "we joined projections" and "the projections
    joined to anything" are different claims -- and the second is the one that
    matters. A surface reporting zero coverage is a working surface over broken
    inputs, which is exactly the distinction the settlement work needed and did
    not have.
    """
    attached = 0
    considered = 0
    with_edge = 0
    for row in grid_rows:
        player = row.get("player_name")
        if not player:
            continue
        considered += 1
        projection = index.project(
            player_name=player, market=row.get("market"), line=row.get("line")
        )
        if projection is None:
            continue
        model_prob = projection.get("model_prob_over")
        fair = _no_vig_over_probability(row)
        projection["market_fair_prob_over"] = fair
        projection["edge_vs_market_pct"] = (
            round((float(model_prob) - float(fair)) * 100.0, 2)
            if model_prob is not None and fair is not None
            else None
        )
        row["projection"] = projection
        attached += 1
        if projection["edge_vs_market_pct"] is not None:
            with_edge += 1
    return {
        "player_rows": considered,
        "rows_with_projection": attached,
        "rows_with_edge": with_edge,
        "pct_projected": round(100.0 * attached / considered, 1) if considered else 0.0,
        # Projected-but-no-edge means the market was one-sided, so no-vig could
        # not be computed. Reported separately because "the sim has a view" and
        # "we can price that view honestly" are different claims.
        "pct_with_edge": round(100.0 * with_edge / considered, 1) if considered else 0.0,
        "pitcher_names_resolved": getattr(index, "pitcher_name_map_size", 0),
    }
