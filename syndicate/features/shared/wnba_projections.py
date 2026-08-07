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
"""

from __future__ import annotations

import ast
import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from syndicate.features.shared.prop_projections import _norm_name

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


def attach_wnba_projections(grid: Iterable[Mapping[str, Any]], index: WnbaProjectionIndex) -> dict[str, Any]:
    """Stamp `projection` onto WNBA player-prop rows. Returns coverage."""
    rows_considered = 0
    rows_with_projection = 0
    unsupported_market_rows = 0
    unmatched_player_rows = 0

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
        if line_value is not None:
            edge = round(mean - line_value, 3)
            projection["edge_vs_line"] = edge
            projection["side"] = "over" if edge > 0 else "under"
        row["projection"] = projection  # type: ignore[index]
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
        "probability_fields": "null by design -- means only, no distribution",
        "source_artifact": index.source_path,
    }
