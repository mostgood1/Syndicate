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

Deliberately team-level plus goals, not a full per-player grid. The card's
box tab already renders the sim's per-player squad projection; what it had
no counterpart for was *what actually happened*. Team stats plus the goals
are that, and they stay small enough to sit inside the existing
``live_state_{date}.json`` artifact (which is already allowlisted in
``HOT_ARTIFACT_PATTERNS``) rather than needing a new published file.
"""

from __future__ import annotations

from typing import Any

from syndicate.features.soccer.ingestion.espn_match_events import extract_key_events

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


def build_match_box(summary: dict[str, Any], *, event_id: str) -> dict[str, Any]:
    """The per-match box record written into ``live_state_{date}.json``."""
    return {
        "event_id": event_id,
        "teams": extract_team_box(summary),
        "goals": extract_goals(summary),
    }


__all__ = ["build_match_box", "extract_goals", "extract_team_box"]
