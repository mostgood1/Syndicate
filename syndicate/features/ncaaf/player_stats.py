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
import re
import statistics
import unicodedata
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


# ---------------------------------------------------------------------------
# CACHING: keyed by the FILE, not by the season.
#
# These readers used to be `@lru_cache(maxsize=8)` keyed by season alone, so a
# process that read the snapshot once kept that reading until it restarted --
# on web, until the next DEPLOY. The worker refreshes the CSV and publishes it
# across, web's disk gets the new file, and every reader here kept serving the
# weeks it saw at boot: the game card's Box Score tab and Ask's player log both
# froze with no signal, the worst shape a cache can have.
#
# The key is now `(path, mtime_ns, size)` -- the stamp
# `ncaaf/player_projections.py` (`_stamp`) already uses for the roster -- so a
# new publish is read on the next call. When the stamp moves every derived
# cache is CLEARED rather than left to age out of the LRU, so a daily refresh
# never holds two parsed copies of a ~13 MB file in a web worker. The cost is
# one `stat()` per public call.
# ---------------------------------------------------------------------------

#: One-element list so the rebind is unambiguous under a threaded web worker.
#: The worst race is a redundant `cache_clear()`; `lru_cache` is thread-safe.
_LAST_STAMP: list[tuple] = []


def _snapshot_stamp() -> tuple:
    path = _snapshot_path()
    try:
        info = path.stat()
    except OSError:
        return (str(path), None, None)
    return (str(path), int(info.st_mtime_ns), int(info.st_size))


def _clear_caches() -> None:
    _load_rows_cached.cache_clear()
    _name_index_cached.cache_clear()
    _ids_by_name_cached.cache_clear()
    _player_logs_cached.cache_clear()
    _game_teams_cached.cache_clear()
    _LAST_STAMP[:] = []


def _current_stamp() -> tuple:
    stamp = _snapshot_stamp()
    if _LAST_STAMP and _LAST_STAMP[0] != stamp:
        _clear_caches()
    if not _LAST_STAMP:
        _LAST_STAMP.append(stamp)
    return stamp


def snapshot_stamp() -> tuple:
    """(path, mtime_ns, size) of the snapshot being read; None fields = absent.
    Public so a caller can say WHICH file answered."""
    return _current_stamp()


@lru_cache(maxsize=4)
def _load_rows_cached(season: int, stamp: tuple) -> tuple[dict[str, Any], ...]:
    path = Path(stamp[0])
    if stamp[1] is None or not path.exists():
        return ()
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
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


def load_player_game_rows(season: int) -> tuple[dict[str, Any], ...]:
    """Every real per-player-per-game stat row for `season`, numeric stat
    fields coerced to float -- one row per (game_id, player_id), already
    merged across passing/rushing/receiving categories by the CFBD
    snapshot writer. Cached per (season, file stamp) -- see CACHING above."""
    return _load_rows_cached(int(season), _current_stamp())


load_player_game_rows.cache_clear = _clear_caches  # type: ignore[attr-defined]


@lru_cache(maxsize=4)
def _name_index_cached(season: int, stamp: tuple) -> dict[str, str]:
    index: dict[str, str] = {}
    for row in _load_rows_cached(season, stamp):
        player_id = row.get("player_id")
        name = row.get("player_name")
        if player_id and name:
            index.setdefault(str(name).strip().lower(), str(player_id))
    return index


def player_name_index(season: int) -> dict[str, str]:
    """Real CFBD player display name (e.g. "Drake Maye") -> player id.
    Case/whitespace-normalized key. CFBD's /games/players athletes already
    carry the full display name, so (unlike NFL's pbp short-name bridge)
    a direct name match is enough.

    COLLAPSES NAMESAKES to the first id seen. A caller that must not guess
    between two players of one name uses `player_ids_by_name` instead."""
    return _name_index_cached(int(season), _current_stamp())


player_name_index.cache_clear = _clear_caches  # type: ignore[attr-defined]


_NON_ALNUM_RE = re.compile(r"[^a-z0-9 ]+")
_SPACE_RE = re.compile(r"\s+")
_NAME_SUFFIXES = frozenset({"jr", "sr", "ii", "iii", "iv", "v"})


def normalize_name(value: Any) -> str:
    """Accent-folded, punctuation-free, lowercase, generational suffix dropped.

    "Kenneth Walker III" -> "kenneth walker"; "Ja'Kobi Lane" -> "jakobi lane".
    Apostrophes are DELETED rather than split on, so a possessive in a typed
    question ("Manning's") folds to the same token as the name.
    """
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    text = text.replace("'", "").replace("’", "").replace("`", "")
    text = _NON_ALNUM_RE.sub(" ", text)
    tokens = [t for t in _SPACE_RE.split(text.strip()) if t and t not in _NAME_SUFFIXES]
    return " ".join(tokens)


@lru_cache(maxsize=4)
def _ids_by_name_cached(season: int, stamp: tuple) -> dict[str, tuple[str, ...]]:
    seen: dict[str, dict[str, None]] = {}
    for row in _load_rows_cached(season, stamp):
        player_id = str(row.get("player_id") or "")
        key = normalize_name(row.get("player_name"))
        if player_id and key:
            seen.setdefault(key, {})[player_id] = None
    return {key: tuple(ids) for key, ids in seen.items()}


def player_ids_by_name(season: int) -> dict[str, tuple[str, ...]]:
    """`normalize_name(name)` -> EVERY player id carrying it in `season`.

    The set, not one winner: the fixture slice alone has a Joseph Williams at
    Colorado and another at Holy Cross, and a caller that took the first id
    would answer about the wrong person with nothing on the page saying so."""
    return _ids_by_name_cached(int(season), _current_stamp())


@lru_cache(maxsize=4)
def _player_logs_cached(season: int, stamp: tuple) -> dict[str, tuple[dict[str, Any], ...]]:
    logs: dict[str, list[dict[str, Any]]] = {}
    for row in _load_rows_cached(season, stamp):
        player_id = str(row.get("player_id") or "")
        if player_id:
            logs.setdefault(player_id, []).append(row)
    return {pid: tuple(sorted(rows, key=lambda r: (r["week"], r["game_id"]))) for pid, rows in logs.items()}


def player_logs(season: int) -> dict[str, tuple[dict[str, Any], ...]]:
    """player_id -> that player's rows for `season`, oldest week first. One
    pass over the season rather than one per player."""
    return _player_logs_cached(int(season), _current_stamp())


@lru_cache(maxsize=4)
def _game_teams_cached(season: int, stamp: tuple) -> dict[str, tuple[str, ...]]:
    teams: dict[str, dict[str, None]] = {}
    for row in _load_rows_cached(season, stamp):
        game_id, team = str(row.get("game_id") or ""), str(row.get("team") or "")
        if game_id and team:
            teams.setdefault(game_id, {})[team] = None
    return {gid: tuple(names) for gid, names in teams.items()}


def opponent_for(season: int, game_id: str, team: str) -> str:
    """The other school in `game_id`, from the snapshot's own rows ('' when the
    other side logged no player line)."""
    others = [t for t in _game_teams_cached(int(season), _current_stamp()).get(str(game_id), ()) if t != team]
    return others[0] if others else ""


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
        for row in player_logs(season).get(str(player_id or ""), ())
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
