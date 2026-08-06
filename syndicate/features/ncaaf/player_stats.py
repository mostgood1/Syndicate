"""Real per-player game-log aggregation from CFBD's ``/games/players``
player-game-stats snapshot.

NCAAF's equivalent of ``syndicate.features.nfl.player_stats`` -- same
no-lookahead rolling-rate discipline (``player_rate`` only ever looks at
games strictly before the requested week), applied over CFBD's already
per-player-per-game aggregated stat lines
(``data/ncaaf_source/source_artifacts/data/processed/player_game_stats/
ncaaf_player_game_stats_snapshot.csv``, written by
``scripts/build_ncaaf_player_game_stats_snapshot.py`` via
``syndicate.features.ncaaf.cfbd.write_ncaaf_player_game_stats_snapshot_csv``)
instead of raw play-by-play. Unlike NFL's nflverse feed, there is no NCAAF
play-by-play source to sum plays from here -- CFBD's ``/games/players``
endpoint already returns one aggregated stat line per player per game per
category, which the snapshot writer merges (dual-threat players appear in
both ``passing`` and ``rushing`` categories for the same game) into one row
per (game_id, player_id) before it ever reaches this module.

Because CFBD's athlete names in ``/games/players`` are already the real
full display name (unlike nflverse pbp's first-initial.last-name), there is
no NFL-style short-name bridging needed here -- ``resolve_player_id``
matches on the full name directly.

Stat keys match the columns CfbdClient.fetch_player_game_stats's real
response shape supports: passing_yards, passing_attempts, passing_tds,
interceptions, rushing_yards, rushing_attempts, receptions,
receiving_yards, anytime_td. This module is deliberately NOT wired to any
props page yet -- see scripts/fetch_ncaaf_oddsapi_props_local.py's
docstring for why.
"""

from __future__ import annotations

import csv
import statistics
from functools import lru_cache
from pathlib import Path
from typing import Any

from syndicate.features.ncaaf.sources import player_game_stats_snapshot_path

STAT_KEYS: tuple[str, ...] = (
    "passing_yards",
    "passing_attempts",
    "passing_tds",
    "interceptions",
    "rushing_yards",
    "rushing_attempts",
    "receptions",
    "receiving_yards",
    "anytime_td",
)

# Extra numeric columns present in the snapshot CSV but not part of
# STAT_KEYS (no real player-prop market maps to raw completions or the
# rushing/receiving TD components separately from anytime_td) -- still
# coerced to float on load so a caller reaching for them directly gets a
# real number rather than a CSV string.
_EXTRA_NUMERIC_COLUMNS: tuple[str, ...] = ("passing_completions", "rushing_tds", "receiving_tds")

_NUMERIC_COLUMNS: tuple[str, ...] = STAT_KEYS + _EXTRA_NUMERIC_COLUMNS


def _snapshot_path() -> Path:
    return player_game_stats_snapshot_path()


@lru_cache(maxsize=8)
def load_player_game_rows(season: int) -> tuple[dict[str, Any], ...]:
    """Every real per-player-per-game stat row for `season`, numeric stat
    fields coerced to float -- one row per (game_id, player_id), already
    merged across passing/rushing/receiving categories by the CFBD
    snapshot writer. Cached per season -- callers may ask for many
    different players' rates against the same season within one request."""
    path = _snapshot_path()
    if not path.exists():
        return ()
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if str(row.get("season") or "").strip() != str(season):
                continue
            try:
                week = int(row.get("week") or 0)
            except (TypeError, ValueError):
                continue
            parsed: dict[str, Any] = {
                "game_id": row.get("game_id") or "",
                "week": week,
                "player_id": row.get("player_id") or "",
                "player_name": row.get("player_name") or "",
                "team": row.get("team") or "",
            }
            for stat in _NUMERIC_COLUMNS:
                try:
                    parsed[stat] = float(row.get(stat) or 0)
                except (TypeError, ValueError):
                    parsed[stat] = 0.0
            rows.append(parsed)
    return tuple(rows)


@lru_cache(maxsize=8)
def player_name_index(season: int) -> dict[str, str]:
    """Real CFBD player display name (e.g. "Drake Maye") -> player id.
    Case/whitespace-normalized key. CFBD's /games/players athletes already
    carry the full display name, so (unlike NFL's pbp short-name bridge)
    a direct name match is enough."""
    index: dict[str, str] = {}
    for row in load_player_game_rows(season):
        player_id = row.get("player_id")
        name = row.get("player_name")
        if player_id and name:
            index.setdefault(str(name).strip().lower(), str(player_id))
    return index


def resolve_player_id(season: int, full_name: str) -> str | None:
    return player_name_index(season).get(str(full_name or "").strip().lower())


def player_game_log(season: int, player_id: str) -> list[dict[str, Any]]:
    """One row per game this player has a real stat line in: {game_id,
    week, <stat>: total, ...} for every stat in STAT_KEYS -- the real
    "box score" line a player's card would show for that game."""
    log = [
        {
            "game_id": row["game_id"],
            "week": row["week"],
            **{stat: row.get(stat, 0.0) for stat in STAT_KEYS},
        }
        for row in load_player_game_rows(season)
        if row.get("player_id") == player_id
    ]
    return sorted(log, key=lambda row: row["week"])


def player_rate(season: int, week: int, player_id: str, stat: str) -> tuple[float | None, float | None, int]:
    """Rolling pre-week (mean, stdev, sample_size) for one stat -- only
    games strictly before `week`, same no-lookahead discipline as
    syndicate.features.nfl.player_stats.player_rate. Returns
    (None, None, sample_size) with fewer than 2 qualifying games -- a rate
    off a single game is not a real distribution, never fabricated."""
    values = [row[stat] for row in player_game_log(season, player_id) if row["week"] < week]
    if len(values) < 2:
        return None, None, len(values)
    return statistics.fmean(values), statistics.pstdev(values), len(values)


def final_stat_value(season: int, game_id: str, player_id: str, stat: str) -> float | None:
    """The real settled value for one game -- this module's actual-result
    grading primitive, the NCAAF analog of
    syndicate.features.nfl.player_stats.final_stat_value."""
    for row in player_game_log(season, player_id):
        if row["game_id"] == game_id:
            return row.get(stat)
    return None
