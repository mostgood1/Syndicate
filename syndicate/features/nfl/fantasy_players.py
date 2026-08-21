"""Who is on which 2026 roster, at what position, at what depth.

This is the layer that makes a projection about NEXT season rather than a
recap of last one. Historical usage (``fantasy_usage``) is keyed by
``gsis_id`` on the team a player played for THEN; this module says what team
and role he holds NOW, and the projection re-bases his usage onto that.

Three real inputs, each with a different failure mode, all named in the
payload so a row can never claim more certainty than it has:

* ``roster_2026.csv``     -- team, position, age, draft capital. Authoritative
  for WHO is on a team. Measured 2026-08-21: 2,930 players, 32 teams, 958 at
  QB/RB/WR/TE/K.
* ``depth_charts_2026.csv`` -- ``pos_rank`` within a position group. The only
  signal for role among players with no NFL history. **Snapshot-dated**: the
  latest local snapshot is 2026-08-01, which is stale against an August draft
  and is exactly the gap the news layer is meant to close. ``depth_chart_as_of``
  is surfaced so a reader can see the staleness rather than infer it.
* ``pbp_20xx.csv``        -- the usage history, joined on ``gsis_id``.

A player with no ``gsis_id`` cannot be joined to history at all; he is kept
with ``has_history=False`` and projected from role priors, not dropped. Dropping
him would silently shrink his team's opportunity pool and inflate everyone
else's share -- the normalisation downstream is a closed system.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

from syndicate.features.nfl.sources import _resolve_nfl_tracking_path


#: Positions this engine projects. IDP is deliberately out of scope -- ESPN
#: IDP scoring varies too much between leagues for one default to be useful.
FANTASY_POSITIONS: tuple[str, ...] = ("QB", "RB", "WR", "TE", "K")

#: Depth-chart position abbreviations that map onto a fantasy position.
_DEPTH_POSITION_MAP: dict[str, str] = {
    "QB": "QB",
    "RB": "RB",
    "FB": "RB",
    "WR": "WR",
    "LWR": "WR",
    "RWR": "WR",
    "SWR": "WR",
    "TE": "TE",
    "K": "K",
    "PK": "K",
    "H": "K",
    # The older week-indexed schema spells positions out in its `position`
    # column rather than using alignment abbreviations.
    "QUARTERBACK": "QB",
    "RUNNING BACK": "RB",
    "FULLBACK": "RB",
    "WIDE RECEIVER": "WR",
    "TIGHT END": "TE",
    "PLACE KICKER": "K",
    "KICKER": "K",
}

#: Team-code aliases seen across nflverse feeds, mapped to the code the
#: play-by-play and the schedule use. THIS IS NOT COSMETIC.
#:
#: Measured 2026-08-21: refetching `roster_2026.csv` changed Arizona's code
#: from `ARI` to `AZ` while `schedules_games.csv` and the play-by-play kept
#: `ARI`. Nothing raised. Every Arizona player simply stopped joining to a team
#: volume or a schedule and fell through to the no-market fallback branch --
#: and still produced a plausible number, which is why it survived a read of
#: the board (Trey McBride still held TE1 and his projection went UP).
#:
#: The relocations are included because the same feeds still emit the old codes
#: for historical seasons, and a season that silently loses a team is the same
#: failure with a different year on it.
_TEAM_CODE_ALIASES: dict[str, str] = {
    "AZ": "ARI",
    "ARZ": "ARI",
    "BLT": "BAL",
    "CLV": "CLE",
    "HST": "HOU",
    "JAC": "JAX",
    "LAR": "LA",
    "STL": "LA",
    "SL": "LA",
    "SD": "LAC",
    "OAK": "LV",
    "WSH": "WAS",
}


def canonical_team(code: str | None) -> str:
    """The team code the play-by-play and schedule use."""
    text = (code or "").strip().upper()
    return _TEAM_CODE_ALIASES.get(text, text)


#: Roster statuses that mean a player will not accrue usage. ``RES`` is
#: injured reserve, ``CUT`` is released, ``RET`` retired, ``E14`` an exempt
#: list. Kept as an explicit set rather than an ``== "ACT"`` test so a new
#: status code shows up as "unknown, treated as active" and can be reviewed,
#: instead of silently zeroing a real player.
_INACTIVE_STATUSES: frozenset[str] = frozenset({"RES", "CUT", "RET", "E14"})

#: A depth-chart snapshot at or after this instant is IN-SEASON for that
#: season and must not feed a preseason projection. NFL week 1 has never
#: started before September.
PRESEASON_CUTOFF = "{season}-09-01"


@dataclass(frozen=True)
class FantasyPlayer:
    """One rostered player, as the projection engine needs him."""

    player_id: str
    #: ESPN's own athlete id. Carried so news articles can be joined by the
    #: tag ESPN attaches to them rather than by matching a name, which has to
    #: drop every ambiguous case to stay safe.
    espn_id: str
    name: str
    team: str
    position: str
    season: int
    age: float | None
    years_exp: int
    draft_number: int | None
    rookie_year: int | None
    status: str
    depth_rank: int | None
    depth_chart_as_of: str | None
    has_history: bool

    @property
    def is_rookie(self) -> bool:
        return self.rookie_year == self.season or self.years_exp == 0

    @property
    def is_active(self) -> bool:
        return self.status not in _INACTIVE_STATUSES


def roster_path(season: int) -> Path:
    return _resolve_nfl_tracking_path(Path("tracking") / "nflverse" / "roster" / f"roster_{season}.csv")


def depth_chart_path(season: int) -> Path:
    return _resolve_nfl_tracking_path(
        Path("tracking") / "nflverse" / "depth_charts" / f"depth_charts_{season}.csv"
    )


def _int_or_none(raw: Any) -> int | None:
    text = str(raw or "").strip()
    if not text or text == "NA":
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _age_on(birth_date: str, reference: date) -> float | None:
    text = (birth_date or "").strip()
    if not text or text == "NA":
        return None
    try:
        born = date.fromisoformat(text[:10])
    except ValueError:
        return None
    return (reference - born).days / 365.25


@lru_cache(maxsize=16)
def latest_depth_chart(
    season: int, as_of: str | None = None
) -> tuple[dict[str, int], str | None]:
    """``gsis_id -> depth rank`` for *season*, and a label for when it is from.

    NFLVERSE PUBLISHES TWO DIFFERENT SCHEMAS and both are in play here:

    * the CURRENT one (2026 locally) is a stream of dated snapshots --
      ``dt``/``team``/``pos_abb``/``pos_rank``, 134 snapshots in one file;
    * the OLDER one (2022-2025) is week-indexed --
      ``club_code``/``week``/``depth_team``/``position``, no timestamp.

    Reading only the first would have left every past season with no depth
    chart at all, which is not a loud failure: ranks come back empty, every
    player falls into the catch-all bucket, and the engine quietly grades in a
    weaker configuration than the one it ships. Detect the schema, do not
    assume it.

    **Which snapshot: the last PRESEASON one.** A depth chart is used here to
    project a season before it starts, so the honest analogue of August 2026's
    chart is a preseason chart from the target season -- never one taken after
    the games it is supposed to be blind to.

    That cut has to be made explicitly and it is easy to get wrong by assuming
    a file is what it looks like. This code originally took the LATEST dated
    snapshot on the reasoning that "the 2026 season has not started, so its
    newest snapshot is preseason". True for 2026, false for 2025: that file
    runs from 2025-08 to 2026-03, so the latest snapshot is dated 2026-03-14 --
    a chart from after the season finished, handed to a backtest whose whole
    job is to not know how the season went. The leak ran in the flattering
    direction, which is the kind that survives review.

    So the rule is now stated in terms of the CALENDAR rather than the file:
    take the newest snapshot before ``PRESEASON_CUTOFF`` (1 September of the
    season), and fall back to the earliest available snapshot when a season
    has none. The week-indexed schema takes week 1 for the same reason.

    ``as_of`` overrides the cutoff with an explicit ISO date, so a caller can
    ask what the depth chart looked like on a given day. That is what makes
    "how much did training camp move the board" answerable rather than a
    feeling -- see ``scripts/compare_nfl_fantasy_depth_charts.py``.

    Taking the minimum rank across a player's rows handles someone listed at
    more than one alignment (a slot receiver at both ``WR`` and ``SWR``): his
    role is the best one he holds, not the average.
    """
    path = depth_chart_path(season)
    if not path.is_file():
        return {}, None

    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or ())
        rows = list(reader)
    if not rows:
        return {}, None

    dated_schema = "pos_rank" in columns and "dt" in columns
    if dated_schema:
        key_column, rank_column, position_column = "dt", "pos_rank", "pos_abb"
        stamps = sorted({(row.get("dt") or "").strip() for row in rows} - {""})
        if not stamps:
            return {}, None
        cutoff = as_of or PRESEASON_CUTOFF.format(season=season)
        preseason = [stamp for stamp in stamps if stamp < cutoff]
        selected = preseason[-1] if preseason else stamps[0]
        label = selected
    elif "depth_team" in columns:
        key_column, rank_column, position_column = "week", "depth_team", "position"
        weeks = [_int_or_none(row.get("week")) for row in rows]
        present = [week for week in weeks if week is not None]
        if not present:
            return {}, None
        selected = str(min(present))
        label = f"{season} week {selected}"
    else:
        return {}, None

    ranks: dict[str, int] = {}
    for row in rows:
        raw_key = (row.get(key_column) or "").strip()
        if dated_schema:
            if raw_key != selected:
                continue
        elif str(_int_or_none(raw_key)) != selected:
            continue
        position = _DEPTH_POSITION_MAP.get((row.get(position_column) or "").strip().upper())
        if position is None:
            continue
        player_id = (row.get("gsis_id") or "").strip()
        rank = _int_or_none(row.get(rank_column))
        if not player_id or rank is None:
            continue
        current = ranks.get(player_id)
        if current is None or rank < current:
            ranks[player_id] = rank
    return ranks, label


@lru_cache(maxsize=16)
def load_fantasy_players(
    season: int,
    *,
    as_of: str | None = None,
    depth_chart_as_of: str | None = None,
) -> tuple[FantasyPlayer, ...]:
    """Every fantasy-relevant player on a *season* roster.

    ``as_of`` is an ISO date used only for age; it defaults to 1 September of
    the season, so ages are comparable across runs instead of drifting with
    the clock. (``feedback_report_local_time_not_utc`` is about reporting; this
    is about making the MODEL deterministic -- an aging curve that reads a
    different age on Tuesday than on Monday is not reproducible.)
    """
    path = roster_path(season)
    if not path.is_file():
        return ()
    reference = date.fromisoformat(as_of) if as_of else date(season, 9, 1)
    depth_ranks, depth_as_of = latest_depth_chart(season, depth_chart_as_of)

    players: list[FantasyPlayer] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            position = (row.get("position") or "").strip().upper()
            if position not in FANTASY_POSITIONS:
                continue
            player_id = (row.get("gsis_id") or "").strip()
            key = player_id or f"noid::{row.get('full_name')}::{row.get('team')}"
            if key in seen:
                continue
            seen.add(key)
            players.append(
                FantasyPlayer(
                    player_id=player_id,
                    espn_id=(row.get("espn_id") or "").strip(),
                    name=(row.get("full_name") or "").strip(),
                    team=canonical_team(row.get("team")),
                    position=position,
                    season=season,
                    age=_age_on(row.get("birth_date") or "", reference),
                    years_exp=_int_or_none(row.get("years_exp")) or 0,
                    draft_number=_int_or_none(row.get("draft_number")),
                    rookie_year=_int_or_none(row.get("rookie_year")),
                    status=(row.get("status") or "").strip().upper(),
                    depth_rank=depth_ranks.get(player_id) if player_id else None,
                    depth_chart_as_of=depth_as_of,
                    has_history=False,  # filled by the projection engine, which owns the usage join
                )
            )
    return tuple(players)


def players_by_team(season: int) -> dict[str, list[FantasyPlayer]]:
    grouped: dict[str, list[FantasyPlayer]] = {}
    for player in load_fantasy_players(season):
        if not player.team:
            continue
        grouped.setdefault(player.team, []).append(player)
    for roster in grouped.values():
        roster.sort(key=lambda entry: (entry.position, entry.depth_rank or 99, entry.name))
    return grouped


def roster_substrate(season: int) -> dict[str, Any]:
    roster = roster_path(season)
    depth = depth_chart_path(season)
    players = load_fantasy_players(season)
    _, depth_as_of = latest_depth_chart(season)
    by_position: dict[str, int] = {}
    for player in players:
        by_position[player.position] = by_position.get(player.position, 0) + 1
    return {
        "season": season,
        "roster_path": str(roster),
        "roster_exists": roster.is_file(),
        "depth_chart_path": str(depth),
        "depth_chart_exists": depth.is_file(),
        "depth_chart_as_of": depth_as_of,
        "fantasy_players": len(players),
        "by_position": by_position,
        "teams": len({player.team for player in players if player.team}),
        "with_depth_rank": sum(1 for player in players if player.depth_rank is not None),
        "with_gsis_id": sum(1 for player in players if player.player_id),
    }
