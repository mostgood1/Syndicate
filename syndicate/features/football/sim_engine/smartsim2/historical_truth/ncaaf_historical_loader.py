"""NCAAF historical data loader for the SmartSim 2.0 truth layer.

Acquisition strategy: the CollegeFootballData (CFBD) API.

- ``/games`` and ``/drives`` accept a full season in one call (no ``week``
  required).
- ``/plays`` requires a ``week`` parameter (CFBD rejects a season-wide
  request with HTTP 400), so plays are fetched and cached per week.

All downloads are cached under the Syndicate NCAAF source mirror so repeated
snapshot builds are offline and replayable, mirroring the NFL loader's cache
pattern (``nfl_historical_loader.py``).

Canonicalization: CFBD's drives+plays+games are joined into the same
play-by-play-shaped frame the shared ``historical_snapshot_builder`` already
consumes for NFL data (``posteam``, ``defteam``, ``fixed_drive``,
``fixed_drive_result``, ``yardline_100``, ``drive_time_of_possession``,
``drive_play_count``, ``yards_gained``, ``posteam_score``,
``posteam_score_post``, ``total_home_score``, ``total_away_score``, ``qtr``,
``down``, ``ydstogo``, ``season``, ``week``, ``season_type``, ``game_id``,
``home_team``, ``away_team``, ``play_id``). Only this loader and the CFBD
drive-result vocabulary mapping are NCAAF-specific; the builder and contract
are reused unchanged.
"""

from __future__ import annotations

import gzip
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any
from typing import Iterable
from typing import Sequence

import pandas as pd

DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[6] / "data" / "ncaaf_source" / "historical_truth"

CFBD_API_BASE = "https://api.collegefootballdata.com"
CFBD_ENV_VARS = (
    "CFBD_API_KEY",
    "COLLEGEFOOTBALLDATA_API_KEY",
    "COLLEGE_FOOTBALL_DATA_API_KEY",
)

# CFBD regular-season weeks run 1-15 in most years, with rare rescheduled
# games landing on 16 and occasional week-0 openers; the range is queried
# defensively and empty weeks simply yield an empty list.
DEFAULT_WEEKS: tuple[int, ...] = tuple(range(0, 17))

# CFBD ``driveResult`` -> the exact canonical text vocabulary already
# recognized by the shared builder's ``canonical_drive_result()``
# (historical_snapshot_builder.py's ``_FIXED_DRIVE_RESULT_MAP``). Anything not
# listed here (e.g. CFBD's own "Uncategorized" tag) falls through to that
# function's ``RESULT_OTHER`` default unchanged.
CFBD_DRIVE_RESULT_MAP: dict[str, str] = {
    "td": "touchdown",
    "fumble td": "touchdown",
    "fg": "field goal",
    "fg td": "opp touchdown",
    "missed fg": "missed field goal",
    "missed fg td": "opp touchdown",
    "blocked fg": "missed field goal",
    "punt": "punt",
    "blocked punt": "punt",
    "punt td": "opp touchdown",
    "punt return td": "opp touchdown",
    "downs": "turnover on downs",
    "downs td": "opp touchdown",
    "int": "turnover",
    "int td": "opp touchdown",
    "fumble": "turnover",
    "fumble return td": "opp touchdown",
    "end of game": "end of game",
    "end of half": "end of half",
    "end of 4th quarter": "end of half",
    "sf": "safety",
    "safety": "safety",
}


def canonical_cfbd_drive_result(value: Any) -> str:
    """Translate a raw CFBD ``driveResult`` into the shared builder's text vocabulary."""
    text = str(value or "").strip().lower()
    return CFBD_DRIVE_RESULT_MAP.get(text, text)


def _api_key() -> str:
    for env_var in CFBD_ENV_VARS:
        value = os.environ.get(env_var, "").strip()
        if value:
            return value
    raise RuntimeError("Missing CFBD API key. Set CFBD_API_KEY, COLLEGEFOOTBALLDATA_API_KEY, or COLLEGE_FOOTBALL_DATA_API_KEY.")


def _cfbd_get(path: str, params: dict[str, Any], *, api_key: str | None = None, timeout: float = 60.0) -> Any:
    key = api_key or _api_key()
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    url = f"{CFBD_API_BASE}{path}?{query}"
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
            "User-Agent": "syndicate-smartsim2-truth-layer",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _write_json_gz(payload: Any, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    with gzip.open(temporary, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle)
    temporary.replace(destination)


def _read_json_gz(path: Path) -> Any:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def _games_cache_path(season: int, cache_dir: Path) -> Path:
    return cache_dir / f"games_{season}.json.gz"


def _drives_cache_path(season: int, cache_dir: Path) -> Path:
    return cache_dir / f"drives_{season}.json.gz"


def _plays_cache_path(season: int, week: int, cache_dir: Path) -> Path:
    return cache_dir / f"plays_{season}_wk{week:02d}.json.gz"


def ensure_games_cached(season: int, *, cache_dir: Path = DEFAULT_CACHE_DIR, api_key: str | None = None) -> Path:
    path = _games_cache_path(season, cache_dir)
    if path.exists():
        return path
    payload = _cfbd_get(
        "/games",
        {"year": season, "seasonType": "regular", "classification": "fbs"},
        api_key=api_key,
    )
    _write_json_gz(payload, path)
    return path


def ensure_drives_cached(season: int, *, cache_dir: Path = DEFAULT_CACHE_DIR, api_key: str | None = None) -> Path:
    path = _drives_cache_path(season, cache_dir)
    if path.exists():
        return path
    payload = _cfbd_get(
        "/drives",
        {"year": season, "seasonType": "regular", "classification": "fbs"},
        api_key=api_key,
    )
    _write_json_gz(payload, path)
    return path


def ensure_plays_cached(
    season: int,
    *,
    weeks: Sequence[int] = DEFAULT_WEEKS,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    api_key: str | None = None,
) -> list[Path]:
    """Ensure per-week plays are cached; CFBD requires ``week`` on this endpoint."""
    paths: list[Path] = []
    for week in weeks:
        path = _plays_cache_path(season, week, cache_dir)
        if not path.exists():
            try:
                payload = _cfbd_get(
                    "/plays",
                    {"year": season, "week": week, "seasonType": "regular", "classification": "fbs"},
                    api_key=api_key,
                )
            except urllib.error.HTTPError as exc:
                if exc.code == 400:
                    payload = []
                else:
                    raise
            # CFBD's /plays payload carries neither `season` nor `week`; tag
            # both from the request itself since the builder's drive/game
            # records require them.
            for row in payload:
                if isinstance(row, dict):
                    row["season"] = season
                    row["week"] = week
            _write_json_gz(payload, path)
        paths.append(path)
    return paths


def load_games_season(season: int, *, cache_dir: Path = DEFAULT_CACHE_DIR, api_key: str | None = None) -> list[dict[str, Any]]:
    path = ensure_games_cached(season, cache_dir=cache_dir, api_key=api_key)
    return _read_json_gz(path)


def load_drives_season(season: int, *, cache_dir: Path = DEFAULT_CACHE_DIR, api_key: str | None = None) -> list[dict[str, Any]]:
    path = ensure_drives_cached(season, cache_dir=cache_dir, api_key=api_key)
    return _read_json_gz(path)


def load_plays_season(
    season: int,
    *,
    weeks: Sequence[int] = DEFAULT_WEEKS,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    api_key: str | None = None,
) -> list[dict[str, Any]]:
    paths = ensure_plays_cached(season, weeks=weeks, cache_dir=cache_dir, api_key=api_key)
    rows: list[dict[str, Any]] = []
    for path in paths:
        rows.extend(_read_json_gz(path))
    return rows


def _clock_seconds(value: Any) -> int:
    if not isinstance(value, dict):
        return 0
    minutes = int(value.get("minutes") or 0)
    seconds = int(value.get("seconds") or 0)
    return minutes * 60 + seconds


def _drive_key(game_id: Any, drive_number: Any) -> tuple[Any, Any]:
    return (game_id, drive_number)


def canonicalize_ncaaf_frame(
    *,
    games: Iterable[dict[str, Any]],
    drives: Iterable[dict[str, Any]],
    plays: Iterable[dict[str, Any]],
    fbs_only: bool = True,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Join CFBD games/drives/plays into the NFL-pbp-shaped canonical frame.

    Returns the canonical frame plus a small metadata dict (counts of
    FBS-vs-FCS games excluded) so callers can report acquisition scope
    honestly instead of silently dropping rows.
    """
    games_list = [dict(row) for row in games if isinstance(row, dict)]
    drives_list = [dict(row) for row in drives if isinstance(row, dict)]
    plays_list = [dict(row) for row in plays if isinstance(row, dict)]

    game_final_scores: dict[str, tuple[int, int]] = {}
    fbs_game_ids: set[int] = set()
    excluded_non_fbs = 0
    for game in games_list:
        game_id = game.get("id")
        home_points = int(game.get("homePoints") or 0)
        away_points = int(game.get("awayPoints") or 0)
        game_final_scores[str(game_id)] = (home_points, away_points)
        is_fbs = str(game.get("homeClassification") or "").lower() == "fbs" and str(game.get("awayClassification") or "").lower() == "fbs"
        if fbs_only and not is_fbs:
            excluded_non_fbs += 1
            continue
        fbs_game_ids.add(game_id)

    # Per-drive lookup: canonical result text, play count, elapsed seconds.
    drive_meta: dict[tuple[Any, Any], dict[str, Any]] = {}
    for drive in drives_list:
        game_id = drive.get("gameId")
        drive_number = drive.get("driveNumber")
        drive_meta[_drive_key(game_id, drive_number)] = {
            "result_text": canonical_cfbd_drive_result(drive.get("driveResult")),
            "plays": int(drive.get("plays") or 0),
            "seconds": _clock_seconds(drive.get("elapsed")),
            "end_offense_score": drive.get("endOffenseScore"),
        }

    rows: list[dict[str, Any]] = []
    for play in plays_list:
        game_id = play.get("gameId")
        if fbs_only and game_id not in fbs_game_ids:
            continue
        drive_number = play.get("driveNumber")
        meta = drive_meta.get(_drive_key(game_id, drive_number))
        if meta is None:
            continue

        offense = str(play.get("offense") or "")
        defense = str(play.get("defense") or "")
        home_team = str(play.get("home") or "")
        away_team = str(play.get("away") or "")
        if not offense or not home_team:
            continue

        offense_is_home = offense == home_team
        offense_score = int(play.get("offenseScore") or 0)
        defense_score = int(play.get("defenseScore") or 0)
        home_score_pre = offense_score if offense_is_home else defense_score
        away_score_pre = defense_score if offense_is_home else offense_score

        end_offense_score = meta["end_offense_score"]
        posteam_score_post = int(end_offense_score) if end_offense_score is not None else offense_score

        play_number = play.get("playNumber") or 0
        play_id = (int(game_id or 0) * 1_000_000) + (int(drive_number or 0) * 1_000) + int(play_number)

        rows.append(
            {
                "play_id": play_id,
                "game_id": str(game_id),
                "season": play.get("season"),
                "week": play.get("week"),
                "season_type": "REG",
                "home_team": home_team,
                "away_team": away_team,
                "posteam": offense,
                "defteam": defense,
                "qtr": play.get("period"),
                "down": play.get("down"),
                "ydstogo": play.get("distance"),
                "yardline_100": play.get("yardsToGoal"),
                "yards_gained": play.get("yardsGained"),
                "play": 1,
                "fixed_drive": drive_number,
                "fixed_drive_result": meta["result_text"],
                "drive_play_count": meta["plays"],
                "drive_time_of_possession": f"{meta['seconds'] // 60}:{meta['seconds'] % 60:02d}",
                "posteam_score": offense_score,
                "posteam_score_post": posteam_score_post,
                "_home_score_pre": home_score_pre,
                "_away_score_pre": away_score_pre,
                "_offense_is_home": offense_is_home,
            }
        )

    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame, {"excluded_non_fbs_games": excluded_non_fbs, "fbs_games": len(fbs_game_ids)}

    frame = frame.sort_values(["game_id", "play_id"]).reset_index(drop=True)

    # total_home_score/total_away_score need the POST-play cumulative score;
    # CFBD's per-play offenseScore/defenseScore are pre-play, so shift each
    # game's sequence forward by one row and backfill the final row with the
    # game's actual final score (from /games, since there is no play after
    # the last one to shift in from).
    frame["total_home_score"] = frame.groupby("game_id")["_home_score_pre"].shift(-1)
    frame["total_away_score"] = frame.groupby("game_id")["_away_score_pre"].shift(-1)

    # The last play of each game has no following row to shift a post-play
    # score in from; backfill it with the game's actual final score.
    home_final_by_game = {game_id: scores[0] for game_id, scores in game_final_scores.items()}
    away_final_by_game = {game_id: scores[1] for game_id, scores in game_final_scores.items()}
    missing_home = frame["total_home_score"].isna()
    frame.loc[missing_home, "total_home_score"] = frame.loc[missing_home, "game_id"].map(home_final_by_game)
    missing_away = frame["total_away_score"].isna()
    frame.loc[missing_away, "total_away_score"] = frame.loc[missing_away, "game_id"].map(away_final_by_game)
    frame = frame.drop(columns=["_home_score_pre", "_away_score_pre", "_offense_is_home"])
    return frame, {"excluded_non_fbs_games": excluded_non_fbs, "fbs_games": len(fbs_game_ids)}


def load_ncaaf_canonical_frame(
    seasons: Iterable[int],
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    weeks: Sequence[int] = DEFAULT_WEEKS,
    fbs_only: bool = True,
    api_key: str | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Fetch (or reuse cached) CFBD games/drives/plays and return the canonical frame."""
    frames: list[pd.DataFrame] = []
    metadata: dict[str, Any] = {"seasons": {}}
    for season in seasons:
        games = load_games_season(season, cache_dir=cache_dir, api_key=api_key)
        drives = load_drives_season(season, cache_dir=cache_dir, api_key=api_key)
        plays = load_plays_season(season, weeks=weeks, cache_dir=cache_dir, api_key=api_key)
        season_frame, season_meta = canonicalize_ncaaf_frame(games=games, drives=drives, plays=plays, fbs_only=fbs_only)
        if not season_frame.empty:
            season_frame["season"] = season
        metadata["seasons"][season] = {
            "games_fetched": len(games),
            "drives_fetched": len(drives),
            "plays_fetched": len(plays),
            **season_meta,
        }
        frames.append(season_frame)
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return combined, metadata


__all__ = [
    "CFBD_DRIVE_RESULT_MAP",
    "DEFAULT_CACHE_DIR",
    "DEFAULT_WEEKS",
    "canonical_cfbd_drive_result",
    "canonicalize_ncaaf_frame",
    "ensure_drives_cached",
    "ensure_games_cached",
    "ensure_plays_cached",
    "load_drives_season",
    "load_games_season",
    "load_ncaaf_canonical_frame",
    "load_plays_season",
]
