"""Soccer projections for the Layer 1 board (S3, third sport after MLB/WNBA).

Audited 2026-08-07: soccer rendered **0.0% projections on all 7 markets** while
identity/line/odds were 100%.

WHAT THE SOURCE ACTUALLY CARRIES, checked field by field rather than assumed --
`recommendations_<date>.json`, per league:

    win_probability      {home, draw, away}   REAL probability
    anytime_scorer_probability                REAL probability (per player)
    total_distribution   {mean, over_2_5_probability, both_teams_scored_...}
    spread_distribution  {home: margin, away: -margin}
    expected_shots / expected_shots_on_target REAL means (per player)

The two `*_distribution` keys are **summary statistics, not distributions**, and
the naming invites exactly the wrong assumption. `total_distribution` can answer
P(over) at **2.5 and nowhere else**; at any other line it has a mean and nothing
more. `spread_distribution` is a single margin number.

So this emits a probability ONLY where one genuinely exists, and a mean
otherwise -- never a probability derived from a mean. Where a real probability
is present the row gets `model_prob_over` and can carry a true
`edge_vs_market_pct`; where only a mean is present it gets `projected` +
`edge_vs_line`, the same contract WNBA uses. Every row states its `basis` so a
reader can tell the two apart, because "0.65" from a simulation and "0.65"
inferred from a mean are not the same claim.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from syndicate.features.shared.prop_projections import _norm_name

# Player-prop market -> field on the player_props entry, and whether that field
# is a PROBABILITY or a MEAN. Getting this wrong in either direction is the
# whole risk: a mean presented as a probability is a fabricated edge.
_PLAYER_FIELDS: dict[str, tuple[str, str]] = {
    "player_goal_scorer_anytime": ("anytime_scorer_probability", "probability"),
    "player_shots": ("expected_shots", "mean"),
    "player_shots_on_target": ("expected_shots_on_target", "mean"),
}

# `player_first_goal_scorer` is deliberately absent: "anytime" is not "first",
# and there is no first-scorer field. Reusing the anytime probability would
# overstate every one of those rows.

_TOTALS_EXACT_PROB_LINE = 2.5


def _norm_team(value: Any) -> str:
    return _norm_name(value)


@dataclass
class SoccerProjectionIndex:
    by_event: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_teams: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    players_by_match: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    leagues: list[str] = field(default_factory=list)
    matches: int = 0
    source_paths: list[str] = field(default_factory=list)

    def match_for(self, row: Mapping[str, Any]) -> dict[str, Any] | None:
        event_id = str(row.get("event_id") or "").strip()
        if event_id and event_id in self.by_event:
            return self.by_event[event_id]
        home = _norm_team(row.get("home_team"))
        away = _norm_team(row.get("away_team"))
        if home and away:
            return self.by_teams.get((home, away))
        return None


def _load_one(path: Path, index: SoccerProjectionIndex) -> None:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(payload, Mapping):
        return
    league = str(payload.get("league") or "")
    if league:
        index.leagues.append(league)
    index.source_paths.append(str(path))

    for match in payload.get("matches") or []:
        if not isinstance(match, Mapping):
            continue
        matchup = match.get("matchup") or {}
        home = _norm_team(matchup.get("home_team"))
        away = _norm_team(matchup.get("away_team"))
        event_id = str(match.get("event_id") or "").strip()
        if event_id:
            index.by_event[event_id] = dict(match)
        if home and away:
            index.by_teams[(home, away)] = dict(match)
        index.matches += 1

    # Player props are keyed by match_id, so a name collision across two matches
    # on the same slate cannot cross-contaminate.
    for entry in payload.get("player_props") or []:
        if not isinstance(entry, Mapping):
            continue
        match_id = str(entry.get("match_id") or "").strip()
        name = _norm_name(entry.get("player_name"))
        if not name:
            continue
        index.players_by_match.setdefault(match_id, {})[name] = dict(entry)


def load_soccer_projections(roots: Iterable[Path], selected_date: str) -> SoccerProjectionIndex:
    """Merge every league's recommendations file for this date."""
    index = SoccerProjectionIndex()
    file_name = f"recommendations_{selected_date}.json"
    seen: set[str] = set()
    for root in roots:
        try:
            candidates = sorted(Path(root).glob(f"*/api/recommendations/{file_name}"))
        except OSError:
            continue
        for candidate in candidates:
            key = str(candidate.resolve()) if candidate.exists() else str(candidate)
            if key in seen:
                continue
            seen.add(key)
            _load_one(candidate, index)
    return index


def _as_float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _probability_projection(prob: float, *, basis: str, side: str = "over") -> dict[str, Any]:
    return {
        "model_prob_over": round(prob, 4),
        "side": side,
        "basis": basis,
        "source": "soccer_recommendations",
    }


def _mean_projection(mean: float, line: Any, *, basis: str) -> dict[str, Any]:
    projection: dict[str, Any] = {
        "projected": round(mean, 3),
        "basis": basis,
        "source": "soccer_recommendations",
        "model_prob_over": None,
        "edge_vs_market_pct": None,
        "probability_unavailable_reason": "source carries a mean, not a distribution",
    }
    line_value = _as_float(line)
    if line_value is not None:
        edge = round(mean - line_value, 3)
        projection["edge_vs_line"] = edge
        projection["side"] = "over" if edge > 0 else "under"
    return projection


def attach_soccer_projections(
    grid: Iterable[Mapping[str, Any]], index: SoccerProjectionIndex
) -> dict[str, Any]:
    considered = 0
    projected = 0
    with_probability = 0
    unmatched_match = 0
    unmatched_player = 0
    unsupported_market = 0

    for row in grid:
        market = str(row.get("market") or "").strip().lower()
        considered += 1
        match = index.match_for(row)
        if match is None:
            unmatched_match += 1
            continue

        projection: dict[str, Any] | None = None

        if market in {"h2h", "h2h_3_way"}:
            win = match.get("win_probability") or {}
            prob = _as_float(win.get("home"))
            if prob is not None:
                # Expressed from the HOME side, matching how the board's other
                # sports state a game-line projection.
                projection = _probability_projection(prob, basis="win_probability", side="home")
                projection["draw_probability"] = _as_float(win.get("draw"))
                projection["away_probability"] = _as_float(win.get("away"))
        elif market in {"totals", "totals_alt"}:
            totals = match.get("total_distribution") or {}
            line_value = _as_float(row.get("line"))
            over_25 = _as_float(totals.get("over_2_5_probability"))
            if line_value is not None and over_25 is not None and abs(line_value - _TOTALS_EXACT_PROB_LINE) < 1e-9:
                # The ONE line this source can answer as a probability.
                projection = _probability_projection(over_25, basis="over_2_5_probability")
            else:
                mean = _as_float(totals.get("mean")) or _as_float(
                    (match.get("team_projection") or {}).get("total_mean")
                )
                if mean is not None:
                    projection = _mean_projection(mean, row.get("line"), basis="total_mean")
        elif market in {"spreads", "spreads_alt"}:
            margin = _as_float((match.get("spread_distribution") or {}).get("home"))
            if margin is None:
                margin = _as_float((match.get("team_projection") or {}).get("margin_mean"))
            if margin is not None:
                projection = _mean_projection(margin, row.get("line"), basis="margin_mean")
        elif market in _PLAYER_FIELDS:
            field_name, kind = _PLAYER_FIELDS[market]
            players = index.players_by_match.get(str(match.get("match_id") or "").strip()) or {}
            entry = players.get(_norm_name(row.get("player_name")))
            if entry is None:
                unmatched_player += 1
                continue
            value = _as_float(entry.get(field_name))
            if value is not None:
                projection = (
                    _probability_projection(value, basis=field_name)
                    if kind == "probability"
                    else _mean_projection(value, row.get("line"), basis=field_name)
                )
        else:
            unsupported_market += 1
            continue

        if projection is None:
            continue
        row["projection"] = projection  # type: ignore[index]
        projected += 1
        if projection.get("model_prob_over") is not None:
            with_probability += 1

    return {
        "supported": True,
        "leagues": sorted(set(index.leagues)),
        "matches_in_source": index.matches,
        "rows_considered": considered,
        "rows_with_projection": projected,
        "rows_with_true_probability": with_probability,
        "unmatched_match_rows": unmatched_match,
        "unmatched_player_rows": unmatched_player,
        "unsupported_market_rows": unsupported_market,
        "pct_projected": round(100.0 * projected / considered, 1) if considered else 0.0,
        "note": "probability only where the source has one; totals answer P(over) at 2.5 only",
        "source_artifacts": index.source_paths,
    }
