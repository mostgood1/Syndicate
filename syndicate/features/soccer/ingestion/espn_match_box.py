"""A card-readable per-match box score from an ESPN match summary.

The data for a real soccer box score was never missing. ``boxscore.teams``
carries 28 team statistics per side -- possession, shots, shots on target,
corners, fouls, cards, passes and pass accuracy, tackles, saves -- and
``keyEvents`` carries every goal with its scorer and minute. Both arrive in
the SAME ``fetch_match_summary`` payload ``poll_soccer_live_state`` already
fetches per live match, so building this costs no extra HTTP call.

What was missing was a consumer-shaped artifact. ``espn_match_stats`` and
``espn_match_events`` already read this payload, but they feed model-feature
CSVs and season aggregates -- per-90 rates, rolling form -- none of which a
game card can render. Soccer's box tab therefore showed only sim squad
projections, while MLB's showed both a real "Live / final box" and a "Sim
box".

Team stats plus goals were the FIRST cut, and the per-player grid is the
second (2026-09-09). The rows were already parsed and then dropped on the
floor: ``espn_lineups.extract_match_player_rows`` yields real goals,
assists, shots, shots on target and the starter flag off the SAME payload,
and ``espn_match_events.compute_minutes_played`` turns the same payload's
``keyEvents`` into exact minutes -- both were feeding model CSVs only, and
``build_match_box`` did not carry either through. So soccer's box tab
rendered the sim's per-player projection with no per-player counterpart for
what actually happened. Adding it costs no extra HTTP call: same
``fetch_match_summary`` response ``poll_soccer_live_state`` already holds.

All of it stays inside the existing ``live_state_{date}.json`` artifact
(already allowlisted in ``HOT_ARTIFACT_PATTERNS``) rather than needing a new
published file.
"""

from __future__ import annotations

from typing import Any

from syndicate.features.soccer.ingestion.espn_lineups import extract_match_player_rows
from syndicate.features.soccer.ingestion.espn_match_events import (
    compute_minutes_played,
    extract_key_events,
)

# (ESPN `name`, display label, scale). Ordered as the card renders them:
# what a bettor reads first, not ESPN's own emission order.
#
# `scale` exists because ESPN MIXES TWO PERCENTAGE CONVENTIONS in the same
# statistics list and gives no field that distinguishes them. Measured on
# fixture 401882908, 2026-08-20: `possessionPct` has `displayValue: "50.3"`
# (already a percentage) while `passPct` has `displayValue: "0.8"` (a
# fraction -- 80%). `value` is `None` on every percentage stat, so there is
# no second field to fall back on and no way to infer the convention from
# the payload. It has to be declared per stat.
#
# The fraction-valued stats are also rounded to ONE decimal at source, so
# `passPct` carries a single significant digit: 0.8 can only ever render as
# 80%, never 82%. Rendered as a whole number for that reason -- "80%" is
# honest about the precision, "80.0%" would not be.
_PCT_0_100 = "pct_0_100"
_PCT_FRACTION = "pct_fraction"
_COUNT = "count"

_TEAM_STATS: tuple[tuple[str, str, str], ...] = (
    ("possessionPct", "Possession", _PCT_0_100),
    ("totalShots", "Shots", _COUNT),
    ("shotsOnTarget", "On target", _COUNT),
    ("wonCorners", "Corners", _COUNT),
    ("saves", "Saves", _COUNT),
    ("foulsCommitted", "Fouls", _COUNT),
    ("yellowCards", "Yellow", _COUNT),
    ("redCards", "Red", _COUNT),
    ("offsides", "Offsides", _COUNT),
    ("totalPasses", "Passes", _COUNT),
    ("passPct", "Pass %", _PCT_FRACTION),
    ("totalTackles", "Tackles", _COUNT),
)


def _stat_display(stats: list[dict[str, Any]], name: str, scale: str) -> str | None:
    """One stat, rendered for display, or None if ESPN did not report it.

    Reads `displayValue` rather than `value` because `value` is `None` on
    every percentage stat in this payload (see `_TEAM_STATS`).
    """
    for stat in stats:
        if stat.get("name") != name:
            continue
        text = str(stat.get("displayValue") or "").strip()
        if not text:
            return None
        if scale == _COUNT:
            return text
        if text.endswith("%"):
            return text
        try:
            number = float(text)
        except ValueError:
            # Not numeric after all -- pass it through untouched rather than
            # dropping a stat ESPN did report.
            return text
        if scale == _PCT_FRACTION:
            return f"{round(number * 100.0):g}%"
        return f"{number:g}%"
    return None


def extract_team_box(summary: dict[str, Any]) -> dict[str, Any]:
    """``{"home": {...}, "away": {...}}`` of display-ready team stats.

    Sides are keyed off ESPN's own ``homeAway``, never off list order --
    ``displayOrder`` is present and is not the same thing.
    """
    box: dict[str, Any] = {}
    for team_block in ((summary.get("boxscore") or {}).get("teams") or []):
        side = str(team_block.get("homeAway") or "").strip().lower()
        if side not in {"home", "away"}:
            continue
        stats = team_block.get("statistics") or []
        values = {}
        for name, label, scale in _TEAM_STATS:
            display = _stat_display(stats, name, scale)
            if display is not None:
                values[label] = display
        box[side] = {
            "team": ((team_block.get("team") or {}).get("displayName")),
            "stats": values,
        }
    return box


def extract_goals(summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Goals in chronological order, with scorer and minute.

    Matches ``build_live_state``'s own goal rule -- ESPN uses distinct type
    keys per goal variant (``goal``, ``goal---header``, ``goal---volley``),
    so this matches the PREFIX. ``own-goal`` does not share that prefix and
    is picked up separately, because a card that silently drops an own goal
    disagrees with its own scoreline.
    """
    goals: list[dict[str, Any]] = []
    for event in extract_key_events(summary):
        event_type = str(event.get("type") or "")
        is_own_goal = event_type.startswith("own-goal")
        if not event_type.startswith("goal") and not is_own_goal:
            continue
        participants = event.get("participants") or []
        scorer = next(
            (str(p.get("athlete_name")) for p in participants if p.get("athlete_name")),
            None,
        )
        goals.append(
            {
                "team": event.get("team"),
                "scorer": scorer,
                # ESPN's own display ("45'+2'"), so stoppage-time goals read
                # the way every scoreboard renders them.
                "clock": event.get("clock_display"),
                "clock_seconds": event.get("clock_seconds"),
                "own_goal": is_own_goal,
            }
        )
    goals.sort(key=lambda goal: goal.get("clock_seconds") or 0.0)
    return goals


def extract_linescores(summary: dict[str, Any]) -> dict[str, list[int | None]]:
    """``{"home": [1st-half goals, 2nd-half goals], "away": [...]}`` from the
    summary HEADER, or ``{}`` when the summary does not carry them.

    THE SCOREBOARD DOES NOT HAVE THIS. Soccer's scoreboard event carries
    ``linescores: null`` (verified 2026-09-08, EPL 401879317), so a half-time
    score is only reachable from the match summary this module already
    parses: ``header.competitions[0].competitors[].linescores`` is
    ``[{"displayValue": "3"}, {"displayValue": "1"}]`` -- one entry per half,
    ordered, no ``period`` key. It is what lets a first-half order settle
    (``segment_actuals``); nothing on the card reads it.

    Sides keyed off ``homeAway``, never list order, same as ``extract_team_box``.
    """
    from syndicate.features.shared.segment_actuals import linescores_from_competitor

    header = summary.get("header") if isinstance(summary.get("header"), dict) else {}
    competitions = header.get("competitions") if isinstance(header.get("competitions"), list) else []
    competition = competitions[0] if competitions and isinstance(competitions[0], dict) else {}
    out: dict[str, list[int | None]] = {}
    for row in competition.get("competitors") or []:
        if not isinstance(row, dict):
            continue
        side = str(row.get("homeAway") or "").strip().lower()
        if side not in {"home", "away"}:
            continue
        values = linescores_from_competitor(row)
        if values is not None:
            out[side] = values
    return out


def summary_clock_seconds(summary: dict[str, Any]) -> float | None:
    """The match clock carried by the summary HEADER, in seconds, or None.

    Same shape ``fetch_events`` reads off the scoreboard: the clock lives on
    ``competition.status``, NOT on its nested ``.type`` (which has no ``clock``
    key at all -- measured on live fixture 401882908).

    Exists so minutes played on an IN-PROGRESS match are cut at the current
    clock rather than at ``compute_minutes_played``'s nominal 5400s full-time
    default. Without it a starter 20 minutes into a match reads "90" -- a
    projected-looking number sitting in a column that claims to be actuals,
    which is the exact class of failure this repo has paid for before.
    """
    header = summary.get("header") if isinstance(summary.get("header"), dict) else {}
    competitions = header.get("competitions") if isinstance(header.get("competitions"), list) else []
    competition = competitions[0] if competitions and isinstance(competitions[0], dict) else {}
    status = competition.get("status") if isinstance(competition.get("status"), dict) else {}
    try:
        value = float(status.get("clock"))
    except (TypeError, ValueError):
        return None
    return value if value > 0.0 else None


def extract_player_box(summary: dict[str, Any], *, event_id: str) -> dict[str, Any]:
    """``{"home": {"team": ..., "players": [...]}, "away": {...}}`` of REAL
    per-player match lines -- minutes, goals, assists, shots, shots on target.

    Every value here is a RECORDED value from the match feed. Nothing in this
    dict is ever a model output, and nothing merges a model output into it;
    the sim's per-player numbers live on a separate artifact key
    (``player_props``) and are rendered in a separate, separately labelled
    card section. See ``cards._player_box_sections``.

    ``appeared`` is the load-bearing flag. ``compute_minutes_played`` OMITS a
    player who never entered the match (an unused substitute) rather than
    giving them 0.0, because "played zero minutes" is impossible and "did not
    play" is the real state. That distinction is carried through here rather
    than collapsed: ``minutes`` is ``None``, not ``0``, for an unused sub.

    Returns ``{}`` when the summary carries no ``rosters`` block at all --
    which is what a PRE-MATCH summary looks like, and is a different state
    from "played but recorded nothing". Callers must say which.
    """
    rows = extract_match_player_rows(summary, event_id=event_id)
    if not rows:
        return {}
    clock = summary_clock_seconds(summary)
    key_events = extract_key_events(summary)
    if clock is None:
        minutes = compute_minutes_played(key_events, rows)
    else:
        minutes = compute_minutes_played(key_events, rows, match_end_seconds=clock)

    box: dict[str, Any] = {}
    for row in rows:
        side = str(row.get("side") or "").strip().lower()
        if side not in {"home", "away"}:
            continue
        bucket = box.setdefault(side, {"team": row.get("team") or "", "players": []})
        player_id = str(row.get("player_id") or "")
        played = minutes.get(player_id)
        bucket["players"].append(
            {
                "player_id": player_id,
                "player_name": row.get("player_name") or "",
                "position": row.get("position") or "",
                "starter": bool(row.get("starter")),
                "appeared": played is not None,
                "minutes": played,
                "goals": row.get("total_goals"),
                "assists": row.get("goal_assists"),
                "shots": row.get("total_shots"),
                "shots_on_target": row.get("shots_on_target"),
            }
        )
    return box


def build_match_box(summary: dict[str, Any], *, event_id: str) -> dict[str, Any]:
    """The per-match box record written into ``live_state_{date}.json``."""
    linescores = extract_linescores(summary)
    return {
        "event_id": event_id,
        "teams": extract_team_box(summary),
        "goals": extract_goals(summary),
        # REAL per-player lines. Keyed `players`, distinct from the sim's
        # `player_props`, so no reader can confuse a recorded number for a
        # projected one by key alone.
        "players": extract_player_box(summary, event_id=event_id),
        # The clock those minutes were cut at (None on a finished match, where
        # the nominal full-time default is correct).
        "clock_seconds": summary_clock_seconds(summary),
        # Per-half goals for segment settlement. ``None`` (not ``[]``) when the
        # summary carries none, so the resolver refuses BY NAME rather than
        # reading an empty half as 0-0.
        "home_linescores": linescores.get("home"),
        "away_linescores": linescores.get("away"),
    }


__all__ = [
    "build_match_box",
    "extract_goals",
    "extract_linescores",
    "extract_player_box",
    "extract_team_box",
    "summary_clock_seconds",
]
