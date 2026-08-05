"""Real, depth-chart-informed preseason context: who's likely to see the
most snaps in a given real preseason week, and which real starters are
likely resting.

Deliberately NOT a repurposing of
syndicate.features.nfl.injury_adjustment's per-starter substitution logic
(team_offense_rating_excluding_player, real_depth_chart_backup,
player_offense_epa_rate) -- those are all gated on real per-play EPA
history, and the population that actually plays in preseason (depth_rank
3+, many with non-GSIS synthetic ids) mostly has no real EPA history to
substitute in. Reusing that logic here would silently produce "no
adjustment" for almost every real preseason game, which would look like
modeling while doing nothing. This module only ever surfaces real,
observable depth-chart facts (name/position/depth_rank/role) -- it never
attempts to rate a player it has no real data for.

Reuses injury_adjustment.py's real depth-chart row-loading
(`_depth_chart_rows`) and rank-parsing (`_to_rank`) helpers directly,
since the underlying real data source (depth_{season}_snapshot.csv) and
its column shape are identical -- only the *use* of the data differs.
"""

from __future__ import annotations

from typing import Any

from syndicate.features.nfl.injury_adjustment import _depth_chart_rows
from syndicate.features.nfl.injury_adjustment import _to_rank

PRESEASON_WEEK_LABELS: dict[int, str] = {
    1: "Hall of Fame Weekend",
    2: "Preseason Week 1",
    3: "Preseason Week 2 (dress rehearsal)",
    4: "Preseason Week 3 (final cuts)",
}

# Real, documented NFL convention -- there is no real preseason
# snap-count data to derive these from (nflverse has zero preseason pbp,
# confirmed), so these are judgment constants with a real justification,
# not fabricated precision: the Hall of Fame game and the final preseason
# week are backup/roster-bubble heavy (starters often don't play at all,
# especially in the HOF game); the middle preseason week is the real
# "dress rehearsal" where starters typically see their most preseason
# snaps (commonly up to a half).
NONSTARTER_PARTICIPATION_SHARE: dict[int, float] = {1: 0.92, 2: 0.80, 3: 0.55, 4: 0.92}

_SITTING_STATUS_NOTE: dict[int, str] = {
    1: "Likely resting",
    2: "May see limited first-half reps",
    3: "May see limited first-half reps",
    4: "Likely resting",
}


def depth_chart_rows_for_team(season: int, team: str) -> list[dict[str, Any]]:
    return _depth_chart_rows(season, team)


def likely_snap_leaders(season: int, team: str, *, week: int, top_n: int = 8) -> list[dict[str, Any]]:
    """Real depth-chart players most likely to see the majority of snaps
    this real preseason week, ordered by real depth_rank. Weeks with a
    high NONSTARTER_PARTICIPATION_SHARE (1, 4) start from depth_rank 2 --
    the real starter is presumed inactive; the dress-rehearsal week (3)
    includes depth_rank 1 too, since starters do play meaningful snaps
    that week. No EPA/quality rating is attached -- documented in the
    module docstring why that would be dishonest for this population."""
    min_rank = 1 if week == 3 else 2
    rows = depth_chart_rows_for_team(season, team)
    candidates = [row for row in rows if (_to_rank(row.get("depth_rank")) or 0) >= min_rank]
    candidates.sort(key=lambda row: _to_rank(row.get("depth_rank")) or 999)
    return [
        {
            "player_name": row.get("player_name"),
            "position": row.get("position"),
            "depth_rank": _to_rank(row.get("depth_rank")),
            "role": row.get("role"),
            "roster_status": row.get("roster_status"),
        }
        for row in candidates[:top_n]
    ]


def likely_starters_sitting(season: int, team: str, *, week: int) -> list[dict[str, Any]]:
    """Real depth_rank == 1 players for this team, tagged with a real,
    conservative status note per week -- informational only, never fed
    into the numeric projection."""
    rows = depth_chart_rows_for_team(season, team)
    starters = [row for row in rows if _to_rank(row.get("depth_rank")) == 1]
    status_note = _SITTING_STATUS_NOTE.get(week, "Status uncertain")
    return [
        {
            "player_name": row.get("player_name"),
            "position": row.get("position"),
            "role": row.get("role"),
            "status_note": status_note,
        }
        for row in starters
    ]
