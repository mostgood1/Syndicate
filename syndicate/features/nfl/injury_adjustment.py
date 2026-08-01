"""Real, data-driven injury adjustment for NFL SmartSim 2.0 team ratings.

`scripts/generate_smartsim2_nfl_projections.py`'s `team_rating()` produces a
single aggregate offense/defense rating per team from real play-by-play --
no per-player decomposition. This module adjusts that aggregate rating when
a specific real player is ruled `Out`/`Doubtful`
(`data/nfl_source/tracking/nflverse/injuries/injuries_{season}.csv`),
using only real data already on disk -- no invented severity/impact
constants.

The real data supports two structurally different signals, so offense and
defense are modeled differently, not forced into one shape:

Offense (QB/RB/WR/TE -- clean per-play attribution): every offensive play
in real pbp has a `passer_player_id`/`rusher_player_id`/`receiver_player_id`,
so a specific player's own real EPA contribution, and the team's real rating
with that player's plays excluded, are both directly computable. When the
"excluding this player" sample is too thin (typically the starting-QB case
-- backups rarely have enough real in-season pass attempts to exclude
meaningfully), this falls back to substituting the real depth-chart
backup's own real EPA rate for that player's real share of team plays. If
neither a real exclusion sample nor a real backup rate exists, no
adjustment is applied -- this never guesses.

Defense (credited splash plays -- sparser signal): real pbp has no full
per-snap defensive attribution (most plays credit no specific defender at
all), only discrete credit columns for sacks/half-sacks/interceptions/
tackles-for-loss/forced-fumbles/fumble-recoveries/pass-breakups. This is a
real "credited splash-play value" signal, not a full on/off-field
efficiency signal the way offense's EPA-per-play is. There is no
backup-substitution fallback for defense: `defense_allowed` already
reflects the other ten defenders' aggregate real production, so removing
one player's own credited value is the whole adjustment -- there's no
"who replaces them" question to answer the way there is for a starting QB.

Offensive line and special teams are out of scope -- no per-play
attribution exists for those positions in real pbp. `Questionable` players
are not adjusted -- only `Out`/`Doubtful` (a genuinely uncertain
designation, not a confirmed absence).
"""

from __future__ import annotations

import csv
import statistics
from pathlib import Path
from typing import Any

from syndicate.features.nfl.player_stats import load_player_plays
from syndicate.features.nfl.sources import default_nfl_source_root

MIN_EXCLUSION_SAMPLE = 20
ADJUSTED_STATUSES = frozenset({"out", "doubtful"})

OFFENSE_POSITIONS = frozenset({"QB", "RB", "FB", "WR", "TE"})
DEFENSE_POSITIONS = frozenset({"DE", "DT", "NT", "LB", "ILB", "OLB", "MLB", "CB", "DB", "S", "SS", "FS"})

_DEFENSE_CREDIT_COLUMNS = (
    "sack_player_id",
    "half_sack_1_player_id",
    "half_sack_2_player_id",
    "interception_player_id",
    "tackle_for_loss_1_player_id",
    "tackle_for_loss_2_player_id",
    "forced_fumble_player_1_player_id",
    "forced_fumble_player_2_player_id",
    "fumble_recovery_1_player_id",
    "fumble_recovery_2_player_id",
    "pass_defense_1_player_id",
    "pass_defense_2_player_id",
)


def position_side(position: str) -> str | None:
    code = str(position or "").strip().upper()
    if code in OFFENSE_POSITIONS:
        return "offense"
    if code in DEFENSE_POSITIONS:
        return "defense"
    return None


def _epa(play: dict[str, Any]) -> float | None:
    raw = play.get("epa")
    if raw in (None, ""):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _offense_role_ids(play: dict[str, Any]) -> tuple[str, ...]:
    return tuple(v for v in (play.get("passer_player_id"), play.get("rusher_player_id"), play.get("receiver_player_id")) if v)


def _player_offense_epas(season: int, player_id: str, *, before_week: int | None) -> list[float]:
    values: list[float] = []
    for play in load_player_plays(season):
        if before_week is not None and play["week"] >= before_week:
            continue
        if player_id not in _offense_role_ids(play):
            continue
        epa = _epa(play)
        if epa is None:
            continue
        values.append(epa)
    return values


def _team_offense_epas(season: int, team: str, *, before_week: int | None, exclude_player_id: str | None = None) -> list[float]:
    values: list[float] = []
    for play in load_player_plays(season):
        if before_week is not None and play["week"] >= before_week:
            continue
        if play.get("posteam") != team:
            continue
        if exclude_player_id is not None and exclude_player_id in _offense_role_ids(play):
            continue
        epa = _epa(play)
        if epa is None:
            continue
        values.append(epa)
    return values


def _team_defense_epas(season: int, team: str, *, before_week: int | None) -> list[float]:
    values: list[float] = []
    for play in load_player_plays(season):
        if before_week is not None and play["week"] >= before_week:
            continue
        if play.get("defteam") != team:
            continue
        epa = _epa(play)
        if epa is None:
            continue
        values.append(epa)
    return values


def _player_defense_epas(season: int, player_id: str, *, before_week: int | None) -> list[float]:
    values: list[float] = []
    for play in load_player_plays(season):
        if before_week is not None and play["week"] >= before_week:
            continue
        if not any(play.get(column) == player_id for column in _DEFENSE_CREDIT_COLUMNS):
            continue
        epa = _epa(play)
        if epa is None:
            continue
        values.append(-epa)
    return values


def player_offense_epa_rate(season: int, week: int, player_id: str) -> tuple[float, int] | None:
    """Rolling pre-week (mean EPA, real play count) over plays where
    player_id is the passer, rusher, or receiver -- no-lookahead, falling
    back to the entire prior season if this player has no qualifying plays
    yet this season. None if neither source has any real plays."""
    values = _player_offense_epas(season, player_id, before_week=week)
    if values:
        return statistics.fmean(values), len(values)
    prior_values = _player_offense_epas(season - 1, player_id, before_week=None)
    if prior_values:
        return statistics.fmean(prior_values), len(prior_values)
    return None


def team_offense_rating_excluding_player(season: int, week: int, team: str, player_id: str) -> tuple[float, int] | None:
    """Real team offense rating recomputed over only the plays where this
    specific player was NOT the passer/rusher/receiver -- a real conditional
    average, not an invented replacement-level constant. None if fewer than
    MIN_EXCLUSION_SAMPLE real plays remain (typically the starting-QB case,
    where within-season backup snaps are too thin to be a real signal)."""
    values = _team_offense_epas(season, team, before_week=week, exclude_player_id=player_id)
    if len(values) < MIN_EXCLUSION_SAMPLE:
        return None
    return statistics.fmean(values), len(values)


def player_defense_value_rate(season: int, week: int, player_id: str) -> tuple[float, int] | None:
    """Rolling pre-week (mean credited defensive value, real credited-play
    count) -- see module docstring for why this is a sparser, structurally
    different signal from the offense side."""
    values = _player_defense_epas(season, player_id, before_week=week)
    if values:
        return statistics.fmean(values), len(values)
    prior_values = _player_defense_epas(season - 1, player_id, before_week=None)
    if prior_values:
        return statistics.fmean(prior_values), len(prior_values)
    return None


def _depth_chart_path(season: int) -> Path:
    return default_nfl_source_root() / "source_artifacts" / "data" / "processed" / "depth" / f"depth_{season}_snapshot.csv"


def _depth_chart_rows(season: int, team: str) -> list[dict[str, Any]]:
    path = _depth_chart_path(season)
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return [row for row in csv.DictReader(handle) if str(row.get("team") or "").strip().upper() == team]
    except Exception:
        return []


def real_depth_chart_backup(season: int, team: str, starter_player_id: str) -> str | None:
    """The real depth-chart player one rank below `starter_player_id` at the
    same team/position group -- None if the starter isn't found on the real
    depth chart, has no real backup listed, or the backup's own id is a
    synthetic fallback (not a real gsis id, so it can't be joined to pbp)."""
    rows = _depth_chart_rows(season, team)
    starter_row = next((row for row in rows if str(row.get("player_id") or "").strip() == starter_player_id), None)
    if starter_row is None:
        return None
    position_group = str(starter_row.get("positional_group") or starter_row.get("position") or "").strip()
    try:
        starter_rank = int(starter_row.get("depth_rank") or 0)
    except (TypeError, ValueError):
        return None
    candidates = [
        row for row in rows
        if str(row.get("positional_group") or row.get("position") or "").strip() == position_group
        and _to_rank(row.get("depth_rank")) is not None
        and _to_rank(row.get("depth_rank")) > starter_rank
    ]
    if not candidates:
        return None
    backup_row = min(candidates, key=lambda row: _to_rank(row.get("depth_rank")))
    backup_id = str(backup_row.get("player_id") or "").strip()
    if not _looks_like_real_gsis_id(backup_id):
        return None
    return backup_id


def _to_rank(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _looks_like_real_gsis_id(player_id: str) -> bool:
    parts = player_id.split("-")
    return len(parts) == 2 and len(parts[0]) == 2 and parts[0].isdigit() and len(parts[1]) == 7 and parts[1].isdigit()


def _injured_players_for_team(season: int, week: int, team: str) -> list[dict[str, Any]]:
    path = default_nfl_source_root() / "tracking" / "nflverse" / "injuries" / f"injuries_{season}.csv"
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except Exception:
        return []
    result = []
    for row in rows:
        if str(row.get("team") or "").strip().upper() != team:
            continue
        try:
            row_week = int(row.get("week") or 0)
        except (TypeError, ValueError):
            continue
        if row_week != week:
            continue
        status = str(row.get("report_status") or "").strip().lower()
        if status not in ADJUSTED_STATUSES:
            continue
        gsis_id = str(row.get("gsis_id") or "").strip()
        if not gsis_id:
            continue
        result.append({"player_id": gsis_id, "position": row.get("position"), "full_name": row.get("full_name"), "report_status": status})
    return result


def _adjust_offense_for_player(season: int, week: int, team: str, unadjusted_rating: float, player_id: str, full_name: str) -> tuple[float, dict[str, Any]]:
    """Returns a DELTA (not a new absolute rating) computed independently
    against the real, all-players-included `unadjusted_rating` -- so that
    multiple injured players on the same side compose by simple addition
    (adjust_team_rating_for_injuries sums these), rather than one player's
    real-data recompute silently discarding another's."""
    excluded = team_offense_rating_excluding_player(season, week, team, player_id)
    if excluded is not None:
        excl_rating, sample_size = excluded
        delta = excl_rating - unadjusted_rating
        return delta, {"player": full_name, "player_id": player_id, "side": "offense", "method": "real_team_rate_excluding_player", "sample_size": sample_size}

    team_plays = _team_offense_epas(season, team, before_week=week)
    n_team = len(team_plays)
    starter_plays = _player_offense_epas(season, player_id, before_week=week)
    if n_team == 0 or not starter_plays:
        return 0.0, {"player": full_name, "player_id": player_id, "side": "offense", "method": "no_real_substitution_data", "reason": "insufficient_current_season_plays"}
    share = len(starter_plays) / n_team

    starter_rate_info = player_offense_epa_rate(season, week, player_id)
    backup_id = real_depth_chart_backup(season, team, player_id)
    backup_rate_info = player_offense_epa_rate(season, week, backup_id) if backup_id else None
    if starter_rate_info is None or backup_id is None or backup_rate_info is None:
        return 0.0, {"player": full_name, "player_id": player_id, "side": "offense", "method": "no_real_substitution_data", "reason": "no_real_backup_signal"}

    starter_rate, _starter_n = starter_rate_info
    backup_rate, backup_n = backup_rate_info
    delta = share * (backup_rate - starter_rate)
    return delta, {"player": full_name, "player_id": player_id, "side": "offense", "method": "real_backup_epa_substitution", "backup_player_id": backup_id, "backup_sample_size": backup_n, "share_of_team_plays": round(share, 4)}


def _adjust_defense_for_player(season: int, week: int, team: str, unadjusted_rating: float, player_id: str, full_name: str) -> tuple[float, dict[str, Any]]:
    """Returns a DELTA, same composability reasoning as _adjust_offense_for_player."""
    credited_values = _player_defense_epas(season, player_id, before_week=week)
    lookup_season = season
    if not credited_values:
        credited_values = _player_defense_epas(season - 1, player_id, before_week=None)
        lookup_season = season - 1
    if not credited_values:
        return 0.0, {"player": full_name, "player_id": player_id, "side": "defense", "method": "no_real_substitution_data", "reason": "no_real_credited_plays"}

    team_defense_plays = _team_defense_epas(lookup_season, team, before_week=(week if lookup_season == season else None))
    if not team_defense_plays:
        return 0.0, {"player": full_name, "player_id": player_id, "side": "defense", "method": "no_real_substitution_data", "reason": "no_real_team_defense_plays"}

    delta_per_play = sum(credited_values) / len(team_defense_plays)
    return -delta_per_play, {"player": full_name, "player_id": player_id, "side": "defense", "method": "real_credited_value_removed", "sample_size": len(credited_values)}


def adjust_team_rating_for_injuries(*, season: int, week: int, team: str, side: str, base_rating: float) -> tuple[float, list[dict[str, Any]]]:
    """Entry point called once per (team, side) right after
    scripts/generate_smartsim2_nfl_projections.py's team_rating(). Returns
    the (possibly unchanged) rating plus a diagnostics list -- one entry per
    real `Out`/`Doubtful` player on that side, naming the real player, the
    real method used, and the real delta applied (or the real reason none
    was applied). Never silent: every injured player on this side produces
    a diagnostic entry even when no adjustment was possible. Multiple
    injured players' deltas are computed independently against the real,
    unadjusted `base_rating` and summed -- not chained -- so the result
    doesn't depend on iteration order."""
    injured = [p for p in _injured_players_for_team(season, week, team) if position_side(p["position"]) == side]
    if not injured:
        return base_rating, []

    total_delta = 0.0
    diagnostics: list[dict[str, Any]] = []
    for player in injured:
        if side == "offense":
            delta, note = _adjust_offense_for_player(season, week, team, base_rating, player["player_id"], player["full_name"])
        else:
            delta, note = _adjust_defense_for_player(season, week, team, base_rating, player["player_id"], player["full_name"])
        note["report_status"] = player["report_status"]
        note["delta"] = round(delta, 4)
        diagnostics.append(note)
        total_delta += delta
    return base_rating + total_delta, diagnostics
