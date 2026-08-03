"""Real per-player game-log aggregation from nflverse play-by-play.

This is NFL's equivalent of two MLB pieces at once: the rolling rate
computation `scripts/generate_smartsim2_nfl_projections.py` uses for
TEAM ratings, applied at the PLAYER level instead, and
`syndicate/features/mlb/box_score_stats.py`'s actual-result lookup for
grading a settled prop. Both read the same real play-by-play data
(`data/nfl_source/tracking/nflverse/pbp/pbp_{season}.csv`) -- there is no
separate player-stats feed to pull from.

Stat keys match the real markets seen in oddsapi_player_props_*.csv:
passing_yards, passing_attempts, passing_tds, rushing_yards,
rushing_attempts, receptions, anytime_td, receiving_yards, interceptions.
"""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
from typing import Any

from syndicate.features.nfl.sources import default_nfl_source_root

_PLAY_COLUMNS = (
    "game_id",
    "week",
    "passer_player_id",
    "passer_player_name",
    "passing_yards",
    "pass_attempt",
    "pass_touchdown",
    "rusher_player_id",
    "rusher_player_name",
    "rushing_yards",
    "rush_attempt",
    "rush_touchdown",
    "receiver_player_id",
    "receiver_player_name",
    "receiving_yards",
    "complete_pass",
    "touchdown",
    "interception",
    # Added for syndicate.features.nfl.injury_adjustment -- real per-play
    # team/value attribution, not used by any stat extractor above.
    "posteam",
    "defteam",
    "epa",
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


def _pbp_path(season: int) -> Path:
    return default_nfl_source_root() / "tracking" / "nflverse" / "pbp" / f"pbp_{season}.csv"


@lru_cache(maxsize=8)
def load_player_plays(season: int) -> tuple[dict[str, Any], ...]:
    """Every real regular-season play, trimmed to the columns player-stat
    aggregation needs. Cached per season -- callers may ask for many
    different players' rates against the same season within one request."""
    path = _pbp_path(season)
    if not path.exists():
        return ()
    plays: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("season_type") != "REG":
                continue
            try:
                week = int(row.get("week") or 0)
            except (TypeError, ValueError):
                continue
            plays.append({column: row.get(column) or "" for column in _PLAY_COLUMNS} | {"week": week})
    return tuple(plays)


@lru_cache(maxsize=8)
def player_name_index(season: int) -> dict[str, str]:
    """Real nflverse display name (e.g. "K.Murray") -> player id, built
    directly off whichever passer/rusher/receiver columns carried that id.
    Case/whitespace-normalized key."""
    index: dict[str, str] = {}
    for play in load_player_plays(season):
        for id_key, name_key in (
            ("passer_player_id", "passer_player_name"),
            ("rusher_player_id", "rusher_player_name"),
            ("receiver_player_id", "receiver_player_name"),
        ):
            player_id = play.get(id_key)
            name = play.get(name_key)
            if player_id and name:
                index.setdefault(name.strip().lower(), player_id)
    return index


def short_name_from_full(full_name: str) -> str:
    """"Drake Maye" -> "D.Maye" -- real player-prop odds carry full names
    while nflverse pbp uses first-initial.last-name; this bridges the two
    real data sources. Known limitation: two players sharing a first
    initial + last name on the same roster would collide -- acceptable for
    a v1, same class of simplification as this session's other rate-based
    approximations."""
    parts = [part for part in str(full_name or "").strip().split() if part]
    if len(parts) < 2:
        return str(full_name or "").strip()
    return f"{parts[0][0]}.{parts[-1]}"


def resolve_player_id(season: int, full_name: str) -> str | None:
    return player_name_index(season).get(short_name_from_full(full_name).strip().lower())


_STAT_EXTRACTORS = {
    "passing_yards": lambda play, pid: float(play["passing_yards"] or 0) if play.get("passer_player_id") == pid and play.get("passing_yards") else 0.0,
    "passing_attempts": lambda play, pid: 1.0 if play.get("passer_player_id") == pid and play.get("pass_attempt") == "1" else 0.0,
    "passing_tds": lambda play, pid: 1.0 if play.get("passer_player_id") == pid and play.get("pass_touchdown") == "1" else 0.0,
    "rushing_yards": lambda play, pid: float(play["rushing_yards"] or 0) if play.get("rusher_player_id") == pid and play.get("rushing_yards") else 0.0,
    "rushing_attempts": lambda play, pid: 1.0 if play.get("rusher_player_id") == pid and play.get("rush_attempt") == "1" else 0.0,
    "receptions": lambda play, pid: 1.0 if play.get("receiver_player_id") == pid and play.get("complete_pass") == "1" else 0.0,
    "receiving_yards": lambda play, pid: float(play["receiving_yards"] or 0) if play.get("receiver_player_id") == pid and play.get("receiving_yards") else 0.0,
    "interceptions": lambda play, pid: 1.0 if play.get("passer_player_id") == pid and play.get("interception") == "1" else 0.0,
    # Anytime TD attributed only to the ball-carrier/receiver of the
    # scoring play -- deliberately checked against rusher/receiver id
    # only, so a passer's OWN touchdown pass never counts as their own
    # anytime-TD (that's a passing_tds event, a different market), and a
    # passing touchdown never inflates the receiver's own rushing/other
    # attribution.
    "anytime_td": lambda play, pid: 1.0 if play.get("touchdown") == "1" and pid in (play.get("rusher_player_id"), play.get("receiver_player_id")) else 0.0,
}

STAT_KEYS: tuple[str, ...] = tuple(_STAT_EXTRACTORS.keys())


def player_game_log(season: int, player_id: str) -> list[dict[str, Any]]:
    """One row per game this player has a qualifying play in: {game_id,
    week, <stat>: total, ...} for every stat in STAT_KEYS -- the real
    "box score" line a player's card would show for that game."""
    totals: dict[str, dict[str, Any]] = {}
    for play in load_player_plays(season):
        if player_id not in (play.get("passer_player_id"), play.get("rusher_player_id"), play.get("receiver_player_id")):
            continue
        game_id = play["game_id"]
        row = totals.setdefault(game_id, {"game_id": game_id, "week": play["week"], **{stat: 0.0 for stat in STAT_KEYS}})
        for stat, extractor in _STAT_EXTRACTORS.items():
            row[stat] += extractor(play, player_id)
    return sorted(totals.values(), key=lambda row: row["week"])


def player_rate(season: int, week: int, player_id: str, stat: str) -> tuple[float | None, float | None, int]:
    """Rolling pre-week (mean, stdev, sample_size) for one stat -- only
    games strictly before `week`, same no-lookahead discipline as the
    team-rating aggregator in generate_smartsim2_nfl_projections.py.
    Returns (None, None, 0) with fewer than 2 qualifying games -- a rate
    off a single game is not a real distribution, never fabricated."""
    import statistics

    values = [row[stat] for row in player_game_log(season, player_id) if row["week"] < week]
    if len(values) < 2:
        return None, None, len(values)
    return statistics.fmean(values), statistics.pstdev(values), len(values)


def final_stat_value(season: int, game_id: str, player_id: str, stat: str) -> float | None:
    """The real settled value for one game -- this module's actual-result
    grading primitive, the NFL analog of
    syndicate.features.mlb.box_score_stats.final_stat_value."""
    for row in player_game_log(season, player_id):
        if row["game_id"] == game_id:
            return row.get(stat)
    return None
