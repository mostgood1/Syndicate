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
receiving_yards, anytime_td. It feeds the game card's box score, Ask's
player log and typed-question answers (`question_player_section`); the prop
PROJECTION is built separately, on the worker, by `ncaaf/prop_projections.py`.
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
    _light_name_index_cached.cache_clear()
    _one_player_history_cached.cache_clear()
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


# ---------------------------------------------------------------------------
# TYPED QUESTIONS: "how has Arch Manning played this season"
#
# Ask's NCAAF player fetcher answered only from a BOARD ROW, so a typed
# question about a college player got no player evidence at all. This is the
# data half of that fetcher (the Ask blueprint wraps it): find a player NAMED in
# free text, then build his last-N table and a season-to-date row, plus the
# published prop projection when one exists. It READS the snapshot and the
# projection artifact; nothing is modelled here.
#
# NAME MATCHING IS BY FULL NAME ONLY. MLB's matcher accepts a bare surname; with
# ~9,000 college players a surname is not an identity ("Manning", "Smith"), so a
# player is found only when his whole normalised name appears as consecutive
# words in the question. A name carried by two players, or two names that
# overlap in the question, is REFUSED by name -- the answer lists who matched
# and asks for the school -- rather than guessed.
#
# COST, measured on the 35,829-row 2025 checkout snapshot. A NON-MATCH (every
# unrouted typed question): one light pass per file stamp (name, id, team, week
# -- no stat columns), 0.36 s and 2.8 MB retained, then dictionary lookups. A
# MATCH: one more pass keeping only that player's lines (a few KB). The full
# season cache (`load_player_game_rows`, ~1 KB per row = 35.7 MB for 2025, 1.3 s)
# is never loaded by this path.
# ---------------------------------------------------------------------------

QUESTION_LAST_N = 10

_POSSESSIVE_RE = re.compile(r"['’]s\b", re.IGNORECASE)


@lru_cache(maxsize=4)
def _light_name_index_cached(stamp: tuple) -> dict[int, dict[str, dict[str, tuple[str, int, int]]]]:
    """season -> normalised name -> {player_id: (latest team, games, latest week)}."""
    path = Path(stamp[0])
    out: dict[int, dict[str, dict[str, list]]] = {}
    if stamp[1] is None or not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                season = int(row.get("season") or 0)
                week = int(row.get("week") or 0)
            except (TypeError, ValueError):
                continue
            player_id = str(row.get("player_id") or "").strip()
            key = normalize_name(row.get("player_name"))
            if not season or not player_id or player_id.startswith("-") or not key:
                continue
            cell = out.setdefault(season, {}).setdefault(key, {}).setdefault(player_id, [str(row.get("team") or ""), 0, 0])
            cell[1] += 1
            if week >= cell[2]:
                cell[0], cell[2] = str(row.get("team") or cell[0]), week
    return {season: {key: {pid: tuple(v) for pid, v in ids.items()} for key, ids in names.items()}
            for season, names in out.items()}


@lru_cache(maxsize=32)
def _one_player_history_cached(stamp: tuple, player_id: str) -> dict[int, tuple[dict[str, Any], ...]]:
    """season -> ONE player's rows (oldest first), each carrying `opponent`.

    A single pass that keeps only this player's lines, rather than the full
    season cache: the full rows are ~1 KB each (35.7 MB for 2025, measured) and
    a typed question needs one player's twenty lines of them. Retained cost is
    a few KB per asked-about player; time is one CSV pass (~0.4 s on 2025).
    """
    path = Path(stamp[0])
    if stamp[1] is None or not path.exists():
        return {}
    mine: dict[int, list[dict[str, Any]]] = {}
    teams_by_game: dict[str, set[str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            game_id, team = str(row.get("game_id") or ""), str(row.get("team") or "")
            if game_id and team:
                teams_by_game.setdefault(game_id, set()).add(team)
            if str(row.get("player_id") or "").strip() != player_id:
                continue
            try:
                season, week = int(row.get("season") or 0), int(row.get("week") or 0)
            except (TypeError, ValueError):
                continue
            parsed: dict[str, Any] = {"game_id": game_id, "week": week, "team": team,
                                      "player_name": row.get("player_name") or ""}
            for stat in _NUMERIC_COLUMNS:
                try:
                    parsed[stat] = float(row.get(stat) or 0)
                except (TypeError, ValueError):
                    parsed[stat] = 0.0
            mine.setdefault(season, []).append(parsed)
    for rows in mine.values():
        for parsed in rows:
            others = sorted(teams_by_game.get(parsed["game_id"], set()) - {parsed["team"]})
            parsed["opponent"] = others[0] if others else ""
    return {season: tuple(sorted(rows, key=lambda r: (r["week"], r["game_id"]))) for season, rows in mine.items()}


def _question_grams(question: str) -> list[tuple[int, int, str]]:
    """(start, end, phrase) for every 2-4 word run of the normalised question."""
    tokens = normalize_name(_POSSESSIVE_RE.sub("", str(question or ""))).split()
    grams: list[tuple[int, int, str]] = []
    for size in (4, 3, 2):
        for start in range(0, len(tokens) - size + 1):
            grams.append((start, start + size, " ".join(tokens[start:start + size])))
    return grams


def question_season(selected_date: str | None = None) -> int:
    """A football season is named for the year it starts; Jan/Feb belong to the previous one."""
    from datetime import date

    text = str(selected_date or "").strip() or date.today().isoformat()
    try:
        year, month = int(text[:4]), int(text[5:7])
    except (ValueError, IndexError):
        today = date.today()
        year, month = today.year, today.month
    return year - 1 if month <= 2 else year


def match_players_in_question(question: str, *, season: int) -> list[dict[str, Any]]:
    """Every player whose FULL name is in the question, for `season` and the one
    before it. Each match: {name_key, span, candidates: [{player_id, team,
    season, games, last_week}]}; a match with >1 candidate is a namesake set."""
    index = _light_name_index_cached(_current_stamp())
    seasons = [int(season), int(season) - 1]
    found: list[dict[str, Any]] = []
    for start, end, phrase in _question_grams(question):
        candidates: dict[str, dict[str, Any]] = {}
        for year in seasons:
            for player_id, (team, games, last_week) in (index.get(year, {}).get(phrase) or {}).items():
                # The NEWEST season's view of each id wins (his current team).
                candidates.setdefault(player_id, {"player_id": player_id, "team": team, "season": year,
                                                  "games": games, "last_week": last_week})
        if candidates:
            found.append({"name_key": phrase, "span": (start, end), "candidates": list(candidates.values())})
    # A shorter phrase inside a longer matched one is the same mention.
    kept: list[dict[str, Any]] = []
    for match in sorted(found, key=lambda m: m["span"][0] - m["span"][1]):
        s, e = match["span"]
        if any(k["span"][0] <= s and e <= k["span"][1] for k in kept):
            continue
        kept.append(match)
    return sorted(kept, key=lambda m: m["span"][0])


def _fold(value: Any) -> str:
    return normalize_name(value)


def _role_columns(games: list[dict[str, Any]]) -> tuple[str, tuple[tuple[str, str], ...]]:
    n = max(1, len(games))
    passing = sum(g.get("passing_attempts", 0.0) for g in games) / n
    rushing = sum(g.get("rushing_attempts", 0.0) for g in games) / n
    receiving = sum(g.get("receptions", 0.0) for g in games) / n
    if passing >= 5.0:
        return "passing_yards", (("passing_attempts", "Att"), ("passing_yards", "Pass yds"), ("passing_tds", "Pass TD"),
                                 ("interceptions", "INT"), ("rushing_yards", "Rush yds"))
    if rushing >= receiving:
        return "rushing_yards", (("rushing_attempts", "Car"), ("rushing_yards", "Rush yds"), ("receptions", "Rec"),
                                 ("receiving_yards", "Rec yds"), ("anytime_td", "TD"))
    return "receiving_yards", (("receptions", "Rec"), ("receiving_yards", "Rec yds"), ("rushing_yards", "Rush yds"),
                               ("anytime_td", "TD"))


def _num(value: Any, digits: int) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


_STAT_LABELS = {"passing_yards": "Passing yards", "rushing_yards": "Rushing yards", "receiving_yards": "Receiving yards"}


def _projection_table(player_id: str, name: str, season: int) -> dict[str, Any] | None:
    """The player's published projection for the week in progress (published
    week_state; never the games-cache fallback -- see
    `prop_projections.week_for_kickoff`), else the newest week on disk."""
    try:
        from syndicate.features.ncaaf import prop_projections as pp

        weeks = pp.artifact_weeks_on_disk(int(season))
        if not weeks:
            return None
        week = pp.current_week_from_state(int(season))
        index = pp.newest_index_at_or_before(int(season), week) if week else pp.load_index(int(season), weeks[-1])
    except Exception:  # noqa: BLE001 - the projection is optional evidence
        return None
    player = index.by_id.get(str(player_id)) if index is not None else None
    if not player:
        return None
    rows = []
    for stat, entry in (player.get("markets") or {}).items():
        interval = pp.central_range(entry)
        rows.append([
            pp.MARKETS.get(stat, {}).get("label", stat),
            _num(entry.get("mean"), 2),
            f"{_num(entry.get('season_mean'), 2)} ({entry.get('season_games')} g)",
            f"{_num(entry.get('prior_mean'), 2)} ({entry.get('prior_source')})",
            f"{_num(interval[0], 1)} – {_num(interval[1], 1)}" if interval else "—",
        ])
    if not rows:
        return None
    return {
        "title": f"Prop model projections — {name} ({season} week {index.week}, from games before week {index.week}; unmeasured against prices)",
        "columns": ["Market", "Projected", "Season avg", "Shrunk toward", "Approx. 80% range"],
        "rows": rows,
    }


def question_player_section(
    question: str,
    *,
    selected_date: str | None = None,
    question_teams: Any = (),
) -> dict[str, Any] | None:
    """The Ask section for an NCAAF player NAMED in a typed question, or None.

    `question_teams` -- CFBD school names the question mentions, or a callable
    returning them (evaluated only when a name is ambiguous) -- is the one way a
    namesake set is narrowed. Otherwise an ambiguous name is refused by name.
    """
    season = question_season(selected_date)
    matches = match_players_in_question(question, season=season)
    if not matches:
        return None
    overlapping = any(a["span"][1] > b["span"][0] for a, b in zip(matches, matches[1:]))
    teams_cache: list[set[str]] = []

    def _teams() -> set[str]:
        if not teams_cache:
            raw = question_teams() if callable(question_teams) else question_teams
            teams_cache.append({_fold(t) for t in (raw or ()) if t})
        return teams_cache[0]

    resolved: list[tuple[str, dict[str, Any]]] = []
    refused: list[tuple[str, list[dict[str, Any]]]] = []
    for match in matches:
        candidates = match["candidates"]
        current = [c for c in candidates if c["season"] == season] or candidates
        if len(current) > 1 and _teams():
            narrowed = [c for c in current if _fold(c["team"]) in _teams()]
            current = narrowed or current
        if overlapping or len(current) != 1:
            refused.append((match["name_key"], candidates))
        else:
            resolved.append((match["name_key"], current[0]))

    tables: list[dict[str, Any]] = []
    charts: list[dict[str, Any]] = []
    evidence: dict[str, Any] = {"source": "ncaaf_player_game_stats", "season": season, "players": []}
    for key, candidates in refused:
        tables.append({
            "title": f"Last games — '{key}' matches {len(candidates)} NCAAF players; refused rather than guessed (name the school)",
            "columns": ["Player", "Team", "Season", "Games", "Last week"],
            "rows": [[key.title(), c["team"], str(c["season"]), str(c["games"]), str(c["last_week"])]
                     for c in sorted(candidates, key=lambda c: (-c["season"], c["team"]))],
        })
        evidence.setdefault("ambiguous", []).append({"name": key, "candidates": len(candidates)})

    for key, candidate in resolved[:2]:
        player_id = candidate["player_id"]
        history_by_season = _one_player_history_cached(_current_stamp(), player_id)
        logs_now = list(history_by_season.get(season, ()))
        logs_before = list(history_by_season.get(season - 1, ()))
        history = [(season, g) for g in reversed(logs_now)] + [(season - 1, g) for g in reversed(logs_before)]
        last = history[:QUESTION_LAST_N]
        if not last:
            continue
        name = (logs_now or logs_before)[-1].get("player_name") or key.title()
        team = (logs_now or logs_before)[-1].get("team") or candidate["team"]
        primary, columns = _role_columns([g for _, g in last])
        rows = [[str(year), str(g["week"]), g["team"], g.get("opponent") or "—",
                 *(_num(g.get(col), 0) for col, _ in columns)] for year, g in last]
        rows.append([f"Avg (last {len(last)})", "", "", "",
                     *(_num(sum(g.get(col, 0.0) for _, g in last) / len(last), 1) for col, _ in columns)])
        n = len(logs_now)
        if n:
            rows.append([f"{season} season to date — total ({n} game{'s' if n != 1 else ''})", "", "", "",
                         *(_num(sum(g.get(col, 0.0) for g in logs_now), 0) for col, _ in columns)])
            rows.append([f"{season} season to date — per game", "", "", "",
                         *(_num(sum(g.get(col, 0.0) for g in logs_now) / n, 1) for col, _ in columns)])
        else:
            rows.append([f"{season} season to date: no {season} games in the CFBD snapshot", "", "", "",
                         *("" for _ in columns)])
        tables.append({
            "title": f"Last {len(last)} games — {name} ({team}, CFBD box scores)",
            "columns": ["Season", "Week", "Team", "Opp", *(label for _, label in columns)],
            "rows": rows,
        })
        charts.append({
            "type": "bar",
            "title": f"{_STAT_LABELS[primary]} by game — {name}",
            "x_label": "Game",
            "y_label": _STAT_LABELS[primary],
            "points": [{"x": f"{year} W{g['week']}", "y": float(g.get(primary) or 0.0)} for year, g in reversed(last)],
        })
        projection = _projection_table(player_id, name, season)
        if projection:
            tables.append(projection)
        evidence["players"].append({
            "name": name, "player_id": player_id, "team": team, "games_shown": len(last), "season_games": n,
            "season_totals": {col: sum(g.get(col, 0.0) for g in logs_now) for col, _ in columns} if n else {},
            "projection": bool(projection),
        })

    if not tables:
        return None
    stamp = snapshot_stamp()
    as_of = ""
    if stamp[1] is not None:
        from datetime import datetime, timezone

        as_of = datetime.fromtimestamp(stamp[1] / 1e9, tz=timezone.utc).strftime("%Y-%m-%d")
    return {"evidence": evidence, "tables": tables, "charts": charts, "as_of": as_of, "sport": "ncaaf"}
