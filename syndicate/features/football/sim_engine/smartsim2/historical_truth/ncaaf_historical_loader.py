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
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from datetime import timezone
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


def _classify_urllib_error(exc: BaseException) -> tuple[int | None, Any] | None:
    """`(status, Retry-After)` for a urllib HTTP error, or None to re-raise.

    NOT `cfbd.py::_classify_requests_error`. That one reads `exc.response`,
    which only a `requests` exception has; this module calls urllib, whose
    `HTTPError` carries `.code` and `.headers` instead. Handing the requests
    classifier a urllib error returns None for everything -- every 429 would
    re-raise immediately and the retry ladder would be inert while looking
    wired.

    `URLError`/timeouts return None deliberately, matching the sibling: a
    backoff aimed at a throttle must not also delay a real outage.
    """
    if not isinstance(exc, urllib.error.HTTPError):
        return None
    headers = getattr(exc, "headers", None) or {}
    try:
        retry_after = headers.get("Retry-After")
    except Exception:  # noqa: BLE001 - a header mapping that will not index
        retry_after = None
    return getattr(exc, "code", None), retry_after


def _cfbd_get_latched(path: str, params: dict[str, Any], *, api_key: str | None = None, timeout: float = 60.0) -> Any:
    """`_cfbd_get` behind the monthly-quota latch and the retry ladder.

    THIS MODULE HAD NEITHER. `_cfbd_get` is raw urllib, and the only mention of
    429 in the file is a comment recording that a few full-season pulls
    exhausted the quota and it was still 429 thirteen hours later. Everything
    periodic must come through here.

    `raise_if_latched` runs INSIDE the retried operation, not once before it.
    That placement is the `ncaaf-cfbd-quota-latch` lane's own measured defect,
    reproduced here rather than rediscovered: with the check outside, "the first
    429 set the latch and the four retries behind it still went out" -- 5 calls
    spent against an exhausted monthly quota instead of 1.
    """
    from syndicate.features.ncaaf.cfbd_backoff import call_with_retry
    from syndicate.features.ncaaf.cfbd_quota_latch import (
        is_monthly_quota_body,
        note_quota_exhausted,
        raise_if_latched,
    )

    describe = f"GET {path}"

    def _operation() -> Any:
        raise_if_latched(describe)
        try:
            return _cfbd_get(path, params, api_key=api_key, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if getattr(exc, "code", None) == 429:
                # The BODY is the discriminator, not the status: a per-minute
                # throttle and an exhausted monthly quota both arrive as 429 and
                # need opposite responses. Reading it consumes the stream, so
                # this happens once and is guarded.
                try:
                    body = exc.read().decode("utf-8", "replace")
                except Exception:  # noqa: BLE001 - an unreadable body is just not a quota answer
                    body = ""
                if is_monthly_quota_body(body):
                    note_quota_exhausted(body)
                    # Latched now -- convert to QuotaExhausted immediately so the
                    # retry ladder does not spend four more calls on an answer
                    # that cannot change for days.
                    raise_if_latched(describe)
            raise

    return call_with_retry(_operation, classify=_classify_urllib_error, describe=describe)


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


def _ratings_cache_path(season: int, cache_dir: Path) -> Path:
    return cache_dir / f"ratings_sp_{season}.json.gz"


def ensure_games_cached(season: int, *, cache_dir: Path = DEFAULT_CACHE_DIR, api_key: str | None = None) -> Path:
    """The games cache path, fetching only when the file is ABSENT.

    DELIBERATELY STILL WRITE-ONCE FOR READERS, and that is not the bug below.
    `ncaaf_target_week` -> `load_games_season` -> here runs inside Flask request
    handlers (`ncaaf/cards.py`), and CLAUDE.md's load-bearing rule is that the
    web service does no on-request backfill. A lazy refresh here would put a
    blocking CFBD call on the cards page.

    `refresh_games_cache` is the producer half: explicit, worker-side, and the
    thing that actually keeps `completed` current. See its docstring.
    """
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


# A game is over well inside this many hours of kickoff. CFBD flips `completed`
# when it ingests the final; the window only has to exceed game length plus that
# ingest lag, and being generous costs one extra day of staleness at most.
_GAME_COMPLETION_GRACE_SECONDS = 12 * 3600

# A failed refresh must not re-attempt on every call. The generator runs hourly
# when its artifact is stale, and an unthrottled retry here would restore the
# exact per-tick CFBD hammering `cfbd_quota_latch` exists to stop -- on a path
# the latch cannot see, because a non-quota failure (500, DNS) never latches.
_GAMES_REFRESH_RETRY_SECONDS = 6 * 3600


def _games_refresh_marker_path(season: int, cache_dir: Path) -> Path:
    return cache_dir / f"games_{season}.refresh_attempt"


def _kickoff_epoch(game: Any) -> float | None:
    """Kickoff as a UTC epoch, or None when the row carries no usable date."""
    if not isinstance(game, dict):
        return None
    text = str(game.get("startDate") or "").strip()
    if not text:
        return None
    # CFBD emits `2026-08-29T23:00:00.000Z`; `fromisoformat` rejects the `Z`
    # on Python < 3.11 and accepts it on 3.11+. Normalise rather than depend
    # on the interpreter version.
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()


def games_payload_is_stale(payload: Any, *, now: float) -> bool:
    """Does this snapshot predate results that already exist?

    THE STALENESS SIGNAL IS THE CONTENT, NOT THE FILE'S MTIME, and that choice
    is load-bearing. This file is git-tracked and `bootstrap_data_root` copies
    it onto the mounted disk, so its mtime is the time of the last deploy or
    bootstrap -- a freshly deployed snapshot from July reads as seconds old. An
    mtime rule would report "fresh" on exactly the file this function exists to
    catch.

    A regular-season game that kicked off more than `_GAME_COMPLETION_GRACE_SECONDS`
    ago and is still `completed: False` is proof the snapshot is behind reality.
    That is precisely the field `ncaaf_target_week` reads, so this tests the
    thing that is wrong rather than a proxy for it.
    """
    if not isinstance(payload, list):
        # Unreadable or unexpected shape: not stale, because a refresh cannot
        # be justified by a payload we could not interpret. `load_games_season`
        # already raises on a corrupt file.
        return False
    cutoff = now - _GAME_COMPLETION_GRACE_SECONDS
    for game in payload:
        if not isinstance(game, dict):
            continue
        if game.get("completed"):
            continue
        kickoff = _kickoff_epoch(game)
        if kickoff is not None and kickoff < cutoff:
            return True
    return False


def refresh_games_cache(
    season: int,
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    api_key: str | None = None,
    now: float | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Re-fetch `games_{season}.json.gz` when its `completed` flags are behind.

    WHY THIS EXISTS. `ensure_games_cached` returns early on `path.exists()`, so
    the file was written once and never again. Measured 2026-09-01:
    `games_2026.json.gz` (written 2026-07-21, six weeks before kickoff) held 888
    games with `completed: False` on **888 of 888**. `ncaaf_target_week` is
    `min(week with an unplayed game)`, so it returned 1 -- and would have
    returned 1 for the whole season. `_week_is_within_pregame_window` then
    filters the week list to `week <= 1`, so the board served "2026 Week 1" for
    every requested week (`?week=2` and `?week=3` both did, on production) while
    projection artifacts existed for weeks 1-13 and 15.

    Never raises for a caller: returns a status dict. A generator must not die
    because a refresh did, and neither must a board.

    THE FOUR RULES THIS FOLLOWS, each one a failure mode that is worse than the
    staleness it replaces:

      * ROUTED THROUGH THE QUOTA LATCH. This module's `_cfbd_get` is raw urllib
        with no `cfbd_backoff` and no `cfbd_quota_latch` -- the only 429 handling
        in the file is a comment. Adding an unlatched periodic caller here would
        rebuild the hourly hammer the latch shipped to stop, on a path the latch
        cannot see.
      * NEVER CLOBBERS A GOOD FILE. A short or empty payload is refused, not
        written. `ensure_ratings_cached` already states the rule for its own
        sibling: "An absent file is honest; an empty one is not." A truncated
        schedule would silently shrink the board.
      * FALLS BACK TO THE STALE FILE. Any failure leaves the existing cache in
        place. A stale board is a real defect; a blank one is a worse one, and
        CFBD is on a MONTHLY quota, so an outage can last days.
      * THROTTLED ON FAILURE. See `_GAMES_REFRESH_RETRY_SECONDS`.
    """
    now = time.time() if now is None else now
    path = _games_cache_path(season, cache_dir)
    marker = _games_refresh_marker_path(season, cache_dir)

    if not path.exists():
        return {"status": "absent", "refreshed": False, "path": str(path)}

    try:
        existing = _read_json_gz(path)
    except Exception as exc:  # noqa: BLE001 - a corrupt cache is not this function's job
        return {"status": "unreadable", "refreshed": False, "error": f"{type(exc).__name__}: {exc}"}

    existing_rows = len(existing) if isinstance(existing, list) else 0

    if not force and not games_payload_is_stale(existing, now=now):
        return {"status": "fresh", "refreshed": False, "rows": existing_rows}

    if not force:
        try:
            last_attempt = float(marker.read_text(encoding="utf-8").strip())
        except Exception:  # noqa: BLE001 - absent or unparseable means "never attempted"
            last_attempt = None
        if last_attempt is not None and (now - last_attempt) < _GAMES_REFRESH_RETRY_SECONDS:
            return {
                "status": "throttled",
                "refreshed": False,
                "rows": existing_rows,
                "retry_in_seconds": int(_GAMES_REFRESH_RETRY_SECONDS - (now - last_attempt)),
            }

    # Stamped BEFORE the call, not after. A process killed mid-fetch (the
    # season-projection generator is launched with a timeout and has been seen
    # to hit it) must still count as an attempt, or the throttle is not one.
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(now), encoding="utf-8")
    except Exception:  # noqa: BLE001 - an unwritable marker must not block the refresh
        pass

    try:
        payload = _cfbd_get_latched(
            "/games",
            {"year": season, "seasonType": "regular", "classification": "fbs"},
            api_key=api_key,
        )
    except Exception as exc:  # noqa: BLE001 - includes QuotaExhausted; stale beats blank
        return {
            "status": "fetch_failed",
            "refreshed": False,
            "rows": existing_rows,
            "error": f"{type(exc).__name__}: {exc}",
        }

    if not isinstance(payload, list) or not payload:
        return {"status": "empty_payload_refused", "refreshed": False, "rows": existing_rows}

    if len(payload) < existing_rows:
        # A schedule does not shrink. Fewer rows than we already hold means a
        # partial or filtered response, and writing it would drop games off the
        # board with no error anywhere.
        return {
            "status": "short_payload_refused",
            "refreshed": False,
            "rows": existing_rows,
            "incoming_rows": len(payload),
        }

    _write_json_gz(payload, path)
    completed_before = sum(1 for g in existing if isinstance(g, dict) and g.get("completed")) if isinstance(existing, list) else 0
    completed_after = sum(1 for g in payload if isinstance(g, dict) and g.get("completed"))
    return {
        "status": "refreshed",
        "refreshed": True,
        "rows": len(payload),
        "completed_before": completed_before,
        "completed_after": completed_after,
        "path": str(path),
    }


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


def ensure_ratings_cached(season: int, *, cache_dir: Path = DEFAULT_CACHE_DIR, api_key: str | None = None) -> Path:
    """SP+ team ratings for one season, cached like games/drives/plays.

    WHY THIS BELONGS HERE AND DID NOT EXIST. This loader cached three datasets --
    games, drives, plays -- all of them EVENT data, a record of what happened.
    Ratings were the one input it never cached, and they are the one input that:

      * CANNOT be derived from the events. SP+ is CFBD's own model output, not a
        statistic computable from drives or plays.
      * DOES NOT CHANGE for a completed season, so re-fetching buys nothing.
      * IS THE PRIMARY MODEL INPUT. `generate_smartsim2_ncaaf_projections`
        backtested SP+ against PPA over ~740 games per season and SP+ won on
        both pairs (r 0.506 vs 0.372 for 2024->2025); PPA is only the fallback.

    So the bulky, derivable datasets were retained and the small, irreplaceable
    one was thrown away after every run.

    WHAT THAT COST, measured 2026-08-27: a few full-season pulls exhausted the
    CFBD quota, and it was still HTTP 429 THIRTEEN HOURS later -- a hard cap, not
    a rolling window. Projection regeneration was blocked outright, which in turn
    blocked the production confirmation that a promoted calibration artifact had
    loaded. A run on 19 August HAD fetched SP+ 2026 successfully; the numbers went
    into the simulation and were discarded. Nothing on disk held them, and they
    cannot be recovered from the projections (51 games against ~204 unknowns,
    through a 300-seed Monte Carlo).

    Same contract as its three siblings: returns the path, fetches only when the
    file is absent, and writes gzipped JSON verbatim.
    """
    path = _ratings_cache_path(season, cache_dir)
    if path.exists():
        return path
    payload = _cfbd_get("/ratings/sp", {"year": season}, api_key=api_key)
    # NEVER cache an empty payload. A rate-limited or malformed response written
    # once would be served forever as though it were real, and the generator
    # would silently produce projections with no ratings at all -- which looks
    # like a completed run. An absent file is honest; an empty one is not.
    if not payload:
        raise RuntimeError(f"/ratings/sp returned no rows for {season}; refusing to cache an empty payload")
    _write_json_gz(payload, path)
    return path


def load_cached_ratings(season: int, *, cache_dir: Path = DEFAULT_CACHE_DIR) -> list | None:
    """The cached payload, or None when absent/unusable -- never a partial read.

    None rather than [] on purpose: an empty list would read as "this season has
    no ratings", which is indistinguishable from a failed fetch and would send a
    caller down the no-ratings path instead of to the API.
    """
    path = _ratings_cache_path(season, cache_dir)
    if not path.exists():
        return None
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return None
    if isinstance(payload, dict):
        payload = payload.get("data")
    return payload if isinstance(payload, list) and payload else None


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
    "games_payload_is_stale",
    "load_drives_season",
    "load_games_season",
    "load_ncaaf_canonical_frame",
    "load_plays_season",
    "refresh_games_cache",
]
