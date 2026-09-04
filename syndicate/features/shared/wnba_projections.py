"""WNBA projections for the Layer 1 board (S3, extending it past MLB).

Audited 2026-08-07 against production: WNBA rendered **0.0% projections on all
15 markets** while identity, line and odds were 100%. The board was complete in
every column except the one that is the reason we exist. Same for NFL and
soccer; MLB was the only wired sport.

THE SOURCE IS ALREADY THERE. `props_recommendations_<date>.csv` carries a
per-player `model` block of MEAN projections:

    {'pts': 12.71, 'reb': 5.09, 'ast': 4.27, 'threes': 1.38,
     'pra': 22.07, 'pr': 17.8, 'pa': 16.98, 'ra': 9.36, ...}

WHAT THIS DELIBERATELY DOES NOT PRODUCE, and why it matters. MLB's join emits
`model_prob_over` and `edge_vs_market_pct` -- a probability-space edge against
the market's no-vig price. It can, because MLB's sim ships a full outcome
DISTRIBUTION (`_dist_prob_over` reads it straight off). WNBA ships **means
only**. Turning a mean into P(over) needs a distributional assumption
(Poisson? negative binomial? what variance?) that nobody here has measured.

So this emits `projected` and `edge_vs_line` (the plan's "Edge Proj" column,
literally projection minus line) and leaves the probability fields **null**.
A blank is recoverable; a fabricated probability propagates into EV, the
blended score and eventually a stake. The board already has one rule for this
and it is `#242`: an absent value must never render as a real one.

`#263`, 2026-08-19: THE PREMISE ABOVE WAS ONLY PARTLY TRUE. WNBA's
`props_recommendations_<date>.csv` ships means only, but the SAME sim that
produces those means also runs a ~100-draw Monte Carlo per player per stat and
persists the resulting EMPIRICAL PMF -- a `hitProb` ladder, `P(actual >= T)`
for every observed total `T` -- in a separate artifact,
`cards_sim_detail_<date>.json`, that nothing in the Layer 2 path had ever
read. (`syndicate/features/shared/basketball_market_board.py` comes closest
-- it joins odds to sim and computes a probability -- but only as a Normal
approximation of mean/sd, never reaching this ladder, and has no live caller
anywhere in the codebase: built, tested, unwired.)

This repo's own rule (2026-08-16 FORBIDDEN entry, "letting a FITTED MODEL
judge when a model-free measurement is available") says the empirical ladder
outranks a reconstructed Normal CDF wherever both exist -- so `#263`'s fix
reads the REAL distribution rather than the more common fallback of turning
mean+sd into an assumed shape. `n_sims` here is ~100, not MLB's 1000 -- tail
probabilities are noisier, stated rather than hidden.
"""

from __future__ import annotations

import ast
import csv
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from syndicate.features.shared.live_edge_policy import live_edge_unavailable_reason
from syndicate.features.shared.prop_projections import _norm_name
# `#263`. REUSED, not a sixth edge computation -- the identical helper
# `wnba_game_projections.py` already built for the sim-probability-at-a-line
# case (spreads/totals). Nothing about it is game-specific: it takes a
# projection dict, the row, and a probability, and does the SAME
# fair-vs-model comparison every sport's game/prop join goes through.
from syndicate.features.shared.wnba_game_projections import _attach_sim_probability_edge
from syndicate.features.shared.probability_refusal import refuse_published_certainty

# Board market key -> key inside the CSV's `model` dict.
#
# `player_double_double` and `player_triple_double` are deliberately ABSENT: they
# are binary outcomes, and the model block carries no probability for them. A
# mean cannot answer "will they get a double-double", so those two markets keep
# an honest blank rather than a number derived from nothing.
_MARKET_TO_MODEL_KEY: dict[str, str] = {
    "player_points": "pts",
    "player_rebounds": "reb",
    "player_assists": "ast",
    "player_threes": "threes",
    "player_steals": "stl",
    "player_blocks": "blk",
    "player_turnovers": "tov",
    "player_points_rebounds_assists": "pra",
    "player_points_rebounds": "pr",
    "player_points_assists": "pa",
    "player_rebounds_assists": "ra",
}

_UNSUPPORTED_MARKETS = {"player_double_double", "player_triple_double"}


@dataclass
class WnbaProjectionIndex:
    """Normalised player name -> {model key: mean}."""

    by_player: dict[str, dict[str, float]] = field(default_factory=dict)
    source_path: str = ""
    players: int = 0

    def mean_for(self, player_name: Any, market: str) -> float | None:
        model_key = _MARKET_TO_MODEL_KEY.get(str(market or "").strip().lower())
        if not model_key:
            return None
        model = self.by_player.get(_norm_name(player_name))
        if not model:
            return None
        value = model.get(model_key)
        return float(value) if isinstance(value, (int, float)) else None


@dataclass
class WnbaPropDistributionIndex:
    """`#263`. Normalised player name -> {model key: hitProb ladder}.

    The ladder is `cards_sim_detail_<date>.json`'s own
    `players[side][i]["prop_ladders"][stat]["ladder"]` -- a list of
    `{"total": T, "hitProb": P(actual >= T), ...}`, taken as-is. Never
    reshaped into a mean/sd pair: that would throw away the real distribution
    shape to reconstruct a worse Normal approximation of it.
    """

    by_player: dict[str, dict[str, list[dict[str, Any]]]] = field(default_factory=dict)
    source_path: str = ""
    players: int = 0

    def ladder_for(self, player_name: Any, market: str) -> list[dict[str, Any]] | None:
        model_key = _MARKET_TO_MODEL_KEY.get(str(market or "").strip().lower())
        if not model_key:
            return None
        entry = self.by_player.get(_norm_name(player_name))
        if not entry:
            return None
        ladder = entry.get(model_key)
        return ladder if isinstance(ladder, list) and ladder else None


def _hit_prob_over(ladder: list[dict[str, Any]], line: float) -> float | None:
    """P(actual stat > line), read off the sim's own empirical ladder.

    `hitProb` at a given `total` is P(actual >= total) -- confirmed against
    production 2026-08-19 (Veronica Burton's `pts` ladder: `total=2` carries
    `hitProb=1.0`, monotonically non-increasing to `total=30` at `hitProb=0.01`,
    matching `hitCount`/`n_sims` exactly). "Over LINE" is "actual >= the
    smallest integer strictly greater than LINE" for any line, half-integer or
    whole -- `floor(line) + 1` gets both right (over 12.5 -> >=13; over 12 -> >=13).

    THE LADDER HAS GAPS. With ~100 draws, not every integer total between
    `minTotal` and `maxTotal` was actually hit, so intermediate totals are
    simply absent from the list -- there is zero mass between two present
    totals, so P(actual >= threshold) for a missing `threshold` equals the
    hitProb of the NEXT PRESENT total at or above it. Found by scanning
    ascending, never by a direct dict/key lookup, which would silently return
    nothing for the common case of a threshold that fell in a gap.

    Beyond the highest simulated total, this returns an honest empirical 0.0,
    not None -- nothing in a ~100-draw sample ever reached that high, which is
    a real (if noisy, small-n) measurement, not a missing one.
    """
    try:
        threshold = math.floor(float(line)) + 1
    except (TypeError, ValueError):
        return None
    if not isinstance(ladder, list) or not ladder:
        return None
    entries: list[tuple[float, float]] = []
    for entry in ladder:
        if not isinstance(entry, Mapping):
            continue
        total = entry.get("total")
        prob = entry.get("hitProb")
        try:
            entries.append((float(total), float(prob)))
        except (TypeError, ValueError):
            continue
    if not entries:
        return None
    entries.sort(key=lambda pair: pair[0])
    for total, prob in entries:
        if total >= threshold:
            return max(0.0, min(1.0, prob))
    return 0.0


def load_wnba_prop_distributions(selected_date: str) -> WnbaPropDistributionIndex:
    """Index `cards_sim_detail_<date>.json`'s real per-player empirical ladders.

    Read through `wnba.cards`' own artifact parser (`_artifact_games_index`)
    and path resolver (`processed_path`), not re-derived -- this inherits
    their path-resolution correctness (multi-root fallback, live-fallback
    handling) rather than risking a second, silently-diverging copy of it.
    Both are read-only imports; this lane does not write to `wnba/cards.py`.
    """
    index = WnbaPropDistributionIndex()
    try:
        from syndicate.features.wnba.cards import _artifact_games_index
        from syndicate.features.wnba.sources import processed_path

        path = processed_path(f"cards_sim_detail_{selected_date}.json")
        games = _artifact_games_index(path) if path and path.exists() else {}
    except Exception:
        return index
    index.source_path = f"cards_sim_detail_{selected_date}.json"
    for game in games.values():
        if not isinstance(game, Mapping):
            continue
        sim = game.get("sim") if isinstance(game.get("sim"), Mapping) else {}
        players_by_side = sim.get("players") if isinstance(sim.get("players"), Mapping) else {}
        for side in ("home", "away"):
            rows = players_by_side.get(side)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                name = row.get("player_name")
                if not name:
                    continue
                ladders = row.get("prop_ladders") if isinstance(row.get("prop_ladders"), Mapping) else {}
                by_stat: dict[str, list[dict[str, Any]]] = {}
                for stat_key, stat_block in ladders.items():
                    if isinstance(stat_block, Mapping) and isinstance(stat_block.get("ladder"), list):
                        by_stat[str(stat_key).strip().lower()] = stat_block["ladder"]
                if by_stat:
                    # Same-key overwrite (e.g. a player appearing on both
                    # sides' lists, or two games sharing a date) takes the
                    # LAST one seen -- acceptable here because a real player
                    # plays at most one game per date, so a collision means a
                    # duplicate reference to the same game, not two different
                    # distributions for the same person.
                    index.by_player[_norm_name(name)] = by_stat
    index.players = len(index.by_player)
    return index


def _parse_model_cell(raw: Any) -> dict[str, float]:
    """The `model` column is a Python-literal dict, not JSON (single quotes).

    `literal_eval` rather than `eval`: the file is written by our own pipeline,
    but a parser that can execute code has no business reading a data file.
    """
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        parsed = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return {}
    if not isinstance(parsed, Mapping):
        return {}
    out: dict[str, float] = {}
    for key, value in parsed.items():
        try:
            out[str(key).strip().lower()] = float(value)
        except (TypeError, ValueError):
            continue
    return out


def load_wnba_projections(path: Path) -> WnbaProjectionIndex:
    index = WnbaProjectionIndex(source_path=str(path))
    if not path or not Path(path).is_file():
        return index
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return index
    for row in csv.DictReader(text.splitlines()):
        player = str(row.get("player") or "").strip()
        if not player:
            continue
        model = _parse_model_cell(row.get("model"))
        if not model:
            continue
        index.by_player[_norm_name(player)] = model
    index.players = len(index.by_player)
    return index


def attach_wnba_projections(
    grid: Iterable[Mapping[str, Any]],
    index: WnbaProjectionIndex,
    distribution_index: WnbaPropDistributionIndex | None = None,
) -> dict[str, Any]:
    """Stamp `projection` onto WNBA player-prop rows. Returns coverage.

    `distribution_index` is OPTIONAL and additive (`#263`). Every existing
    caller that does not pass one keeps today's exact behaviour -- means
    only, probability fields null -- which is also what a real row falls back
    to when the distribution index has no ladder for it (an unmatched player,
    or a stat the sim didn't cover). A missing distribution is never an error
    here, only a narrower one.
    """
    rows_considered = 0
    rows_with_projection = 0
    unsupported_market_rows = 0
    unmatched_player_rows = 0
    rows_with_distribution = 0

    for row in grid:
        if str(row.get("kind") or "") != "prop":
            continue
        market = str(row.get("market") or "").strip().lower()
        rows_considered += 1
        if market in _UNSUPPORTED_MARKETS:
            unsupported_market_rows += 1
            continue
        mean = index.mean_for(row.get("player_name"), market)
        if mean is None:
            unmatched_player_rows += 1
            continue

        line = row.get("line")
        try:
            line_value = None if line is None else float(line)
        except (TypeError, ValueError):
            line_value = None

        projection: dict[str, Any] = {
            "projected": round(mean, 3),
            "source": "wnba_props_recommendations",
            "basis": "model_mean",
            # Stated explicitly rather than simply omitted, so a reader knows the
            # blank is a known limit and not a join that failed.
            "model_prob_over": None,
            "edge_vs_market_pct": None,
            "probability_unavailable_reason": "model ships means, not a distribution",
        }
        # `#263`. A real empirical probability, from the sim's own ~100-draw
        # ladder -- tried BEFORE the mean-only edge_vs_line block below, so a
        # successful attach can overwrite `probability_unavailable_reason`
        # before anything reads it. Requires a line: the ladder answers
        # "P(over THIS number)", not a bare existence question.
        if distribution_index is not None and line_value is not None:
            ladder = distribution_index.ladder_for(row.get("player_name"), market)
            if ladder is not None:
                hit_prob = _hit_prob_over(ladder, line_value)
                if hit_prob is not None:
                    projection["basis"] = "empirical_sim_ladder"
                    _attach_sim_probability_edge(projection, row=row, model_prob=hit_prob)
                    rows_with_distribution += 1
        if line_value is not None:
            edge = round(mean - line_value, 3)
            # `#340`. WNBA was the ONLY sport not applying this: measured
            # 2026-08-10, a live game served 128 of 128 projected rows with an
            # `edge_vs_line` while MLB suppressed all 862 of its live rows for
            # the same reason. The model's mean is pregame; once the game
            # starts the line has moved on the score and the difference is the
            # score, not an edge. Worse, it RANKS -- a board that sorts by edge
            # puts those rows on top.
            #
            # `projected` and `side` stay: they are the model's opinion and are
            # legitimate to show against a live line. Only the edge number goes,
            # which mirrors what MLB does with `edge_vs_market_pct`.
            reason = live_edge_unavailable_reason(row)
            if reason:
                projection["edge_vs_line"] = None
                projection["edge_unavailable_reason"] = reason
                projection["side"] = "over" if edge > 0 else "under"
            else:
                projection["edge_vs_line"] = edge
                projection["side"] = "over" if edge > 0 else "under"
        # EVERY BLANK EDGE MUST BE DIAGNOSABLE BY REASON (`#601`).
        #
        # A mean-only row leaves `edge_vs_market_pct` None and states
        # `probability_unavailable_reason`, but never `edge_unavailable_reason`
        # -- and the Layer 1 audit reads the second, because that is the field
        # every other producer sets and the one that answers "why is this row
        # not on the board". Measured on production 2026-08-30, pregame WNBA:
        # 42 prop rows (`player_points_rebounds` 13, `player_points_assists` 19,
        # `player_rebounds_assists` 10) served a blank edge with the reason key
        # ABSENT -- the exact state `prop_projections` was fixed for on
        # 2026-08-16, in the fourth producer that never went through it.
        #
        # ABSENT AND None ARE DIFFERENT ANSWERS. Absent indicts the producer
        # (this path never ran); None indicts the input. A reader could not tell
        # these rows from a join that had crashed.
        #
        # It RESTATES the probability refusal rather than inventing a second
        # vocabulary: there is no edge because there is no probability, and
        # `probability_unavailable_reason` already says precisely why. When the
        # sim ladder DID attach a probability, `_attach_sim_probability_edge`
        # has already written both fields and this leaves them alone.
        if projection.get("edge_vs_market_pct") is None and not projection.get("edge_unavailable_reason"):
            probability_reason = projection.get("probability_unavailable_reason")
            projection["edge_unavailable_reason"] = (
                "no probability to price: %s" % probability_reason
                if probability_reason
                else "this projection carries no probability, so no edge was priced"
            )
        row["projection"] = refuse_published_certainty(projection)  # type: ignore[index]
        rows_with_projection += 1

    return {
        "supported": True,
        "players_in_source": index.players,
        "rows_considered": rows_considered,
        "rows_with_projection": rows_with_projection,
        "unsupported_market_rows": unsupported_market_rows,
        "unmatched_player_rows": unmatched_player_rows,
        "pct_projected": (
            round(100.0 * rows_with_projection / rows_considered, 1) if rows_considered else 0.0
        ),
        # `#263`. Both numbers, not a rewritten claim: `rows_with_distribution`
        # is the real, attributable count, and the STRING is now conditional
        # rather than a blanket "null by design" that would be false on the
        # very rows this shipped to fix.
        "rows_with_distribution": rows_with_distribution,
        "probability_fields": (
            "empirical sim ladder where the player/stat/line matched; "
            "means only elsewhere (unmatched player, unsupported market, or no line)"
            if distribution_index is not None
            else "null by design -- means only, no distribution index supplied"
        ),
        "source_artifact": index.source_path,
        "distribution_source_artifact": (
            distribution_index.source_path if distribution_index is not None else None
        ),
    }
