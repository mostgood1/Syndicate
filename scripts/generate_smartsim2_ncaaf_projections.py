"""Generate the standalone SmartSim 2.0 NCAAF projection artifact for one week.

Writes data/ncaaf_source/data/smartsim2_projections_{season}_wk{week}.csv,
one row per FBS-vs-FBS game on the current engine's own schedule for that
week (read from the predicted-totals snapshot, so SmartSim only ever
projects games the legacy engine already covers).

This script does not modify SmartSim 2.0 or the legacy engine -- it only
calls syndicate.features.football.sim_engine.smartsim2 as a library, using
NCAAF_CALIBRATION_PROFILE exactly as shipped.

Usage:
  python scripts/generate_smartsim2_ncaaf_projections.py --season 2025 --week 8
  # Requires CFBD_API_KEY in environment (team ratings, real game ids).
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from datetime import timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationInput
from syndicate.features.football.sim_engine.smartsim2.game_simulator import simulate_game
from syndicate.features.football.sim_engine.smartsim2.ncaaf_calibration_profile import NCAAF_CALIBRATION_PROFILE
from syndicate.features.football.sim_engine.smartsim2.ncaaf_calibration_profile import NCAAF_CALIBRATION_PROFILE_METADATA
from syndicate.features.ncaaf.cfbd_backoff import call_with_retry
from syndicate.features.ncaaf.cfbd_quota_latch import (
    QuotaExhausted,
    note_quota_exhausted,
    raise_if_latched,
)
from syndicate.features.ncaaf.smartsim2_projection import SmartSimNcaafProjection
from syndicate.features.ncaaf.smartsim2_projection import write_projection_artifact
from syndicate.features.ncaaf.sources import default_ncaaf_source_root

DATA_ROOT = default_ncaaf_source_root() / "data"
ENHANCED_CSV = DATA_ROOT / "college_football_schedule_2025_predicted_totals_enhanced.csv"

CFBD_API_BASE = "https://api.collegefootballdata.com"
CFBD_ENV_VARS = ("CFBD_API_KEY", "COLLEGEFOOTBALLDATA_API_KEY", "COLLEGE_FOOTBALL_DATA_API_KEY")
SEEDS_PER_GAME = 300
PROFILE_NAME = "ncaaf_v2"


def _api_key() -> str:
    for env_var in CFBD_ENV_VARS:
        value = os.environ.get(env_var)
        if value:
            return value
    raise RuntimeError("Missing CFBD API key. Set CFBD_API_KEY, COLLEGEFOOTBALLDATA_API_KEY, or COLLEGE_FOOTBALL_DATA_API_KEY.")


def _classify_cfbd_error(exc: BaseException) -> tuple[int | None, object] | None:
    """`(status, Retry-After)` for an HTTP error, or None to re-raise as-is.

    Only `HTTPError` carries a status. A bare `URLError` (DNS, connection
    refused) deliberately falls through to None: it is not the throttle this
    backoff exists for, and retrying it here would delay a real outage behind
    three minutes of sleeping.
    """
    if isinstance(exc, urllib.error.HTTPError):
        return getattr(exc, "code", None), (exc.headers or {}).get("Retry-After")
    return None


def _cfbd_get(path: str, params: dict[str, object]) -> object:
    """One CFBD GET, retried on 429/5xx per `ncaaf/cfbd_backoff.py`.

    THE 429 THAT MADE THIS NECESSARY was not on the path this script's usage
    line advertises: week 1 has no in-season PPA, so `load_ppa_ratings_asof`
    falls back to the PRIOR season and issues a second `/ppa/teams` call. That
    is the one that was throttled, ~30 times over 2h45m on 2026-08-29, leaving
    the projection artifact three days stale.
    """
    # THE MONTHLY QUOTA IS NOT A THROTTLE AND MUST NOT BE RETRIED LIKE ONE.
    # Measured 2026-08-31: this script relaunched HOURLY for days against a
    # quota CFBD had already said was gone, because a failed run leaves the
    # artifact stale and the staleness trigger refires every tick
    # (`interval_seconds=86400`, firing ~24x that). `raise_if_latched` makes
    # this fail in microseconds with NO request until the month rolls.
    raise_if_latched(f"GET {path}", log=lambda message: print(message, flush=True))

    query = "&".join(f"{key}={value}" for key, value in params.items())
    url = f"{CFBD_API_BASE}{path}?{query}"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {_api_key()}", "User-Agent": "syndicate-smartsim2-shadow/1.0"})

    def _once() -> object:
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # THE BODY IS THE DISCRIMINATOR, NOT THE STATUS. A short-window
            # throttle and an exhausted monthly quota are both 429 and need
            # opposite responses, so an unrecognised 429 falls through to
            # `cfbd_backoff`'s retries exactly as before.
            if getattr(exc, "code", None) == 429:
                try:
                    body = exc.read().decode("utf-8", "replace")
                except Exception:
                    body = ""
                if note_quota_exhausted(body, log=lambda message: print(message, flush=True)):
                    # ABANDON THE LADDER, do not merely record the latch.
                    #
                    # MEASURED in production 2026-08-31 05:16:39-05:16:58: FIVE
                    # `LATCH_SET` lines at 2s/5s/10s gaps -- exactly
                    # `MAX_ATTEMPTS`. The latch was set by the first 429 and the
                    # four retries behind it still went out, because
                    # `raise_if_latched` is checked once BEFORE
                    # `call_with_retry` and never again inside it. On the run
                    # that DISCOVERS the exhaustion the latch was saving zero
                    # calls.
                    #
                    # `QuotaExhausted` is not an `HTTPError`, so
                    # `_classify_cfbd_error` returns None and `call_with_retry`
                    # re-raises immediately instead of sleeping and retrying a
                    # limit it has just been told about. It is also the type
                    # `load_ppa_ratings` already catches to fall back to cache,
                    # so the discovering run now gets the stale-cache path too.
                    raise QuotaExhausted(
                        "CFBD monthly quota exhausted (first 429 of this run); "
                        "abandoning the retry ladder."
                    ) from exc
            raise

    return call_with_retry(
        _once,
        classify=_classify_cfbd_error,
        describe=f"GET {path}",
        # `print`, not `logging`: `logger.info` never reaches Render's log
        # collector, and a backoff nobody can see is indistinguishable from a
        # hang. See CLAUDE.md.
        log=lambda message: print(message, flush=True),
    )


def norm(name: str) -> str:
    text = (name or "").strip().lower()
    text = text.replace("state", "st").replace("&", "and")
    text = re.sub(r"[^a-z0-9 ]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def load_engine_schedule(season: int, week: int) -> list[dict[str, str]]:
    """Rows for this season/week from the legacy engine's predicted-totals CSV.

    RETURNS EMPTY WHEN THE FILE IS ABSENT, DELIBERATELY. `#445`.

    `games_from_cfbd_when_engine_schedule_empty` below is the intended handling
    for a season this file does not cover, and its own docstring says so: "a
    single, non-season-partitioned file that is only ever refreshed for the
    engine's own season". `main` already calls it on an empty result. But this
    function OPENED the path unguarded, so an absent file raised
    FileNotFoundError and killed the run before that fallback could engage --
    the fallback has been unreachable for exactly the case it was written for.

    Measured 2026-08-16 on refresh-worker: every launch for season=2026 week=1
    died here on
    `.../ncaaf_source/data/college_football_schedule_2025_predicted_totals_enhanced.csv`,
    and the staleness gate relaunched it indefinitely
    (`SEASON_PROJECTION_ARTIFACT_MISSING sport=ncaaf ... since_launch_seconds=2866`).
    All 278 of these files in the checkout are season 2025; there is no 2026 one
    and nothing writes one.

    NOTE THE FILENAME IS PINNED TO 2025 WHILE THE FILTER BELOW IS SEASON-AWARE.
    That is left alone on purpose: pointing it at a 2026 file would be worse, not
    better, because no such file exists and inventing one would rate the 2026
    season from 2025 predicted totals. CFBD is the correct source for a season
    the legacy engine never covered.
    """
    if not ENHANCED_CSV.is_file():
        # Attributable, not silent: "no rows for this week" and "the file is not
        # there at all" are different facts, and the caller's fallback log line
        # cannot tell them apart on its own.
        print(
            f"ENGINE_SCHEDULE_ABSENT path={ENHANCED_CSV} season={season} week={week} "
            "-- falling back to CFBD games",
            flush=True,
        )
        return []
    with ENHANCED_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row.get("week") == str(week) and row.get("season") == str(season)]
    return rows


def _cached_games(season: int, week: int) -> list[dict] | None:
    """`/games` from the historical-truth cache the loader already maintains.

    THE SECOND OF TWO CFBD CALLS THIS SCRIPT CANNOT AVOID -- and unlike SP+,
    this one HAS a local equivalent. `historical_truth/games_<season>.json.gz`
    is CREATED by `ncaaf_historical_loader.ensure_games_cached` and REFRESHED by
    `ncaaf_historical_loader.refresh_games_cache`, which `main()` calls; for 2026
    it holds 888 rows covering weeks 1-13 and 15.

    THE PREVIOUS VERSION OF THIS PARAGRAPH SAID `ensure_games_cached` REFRESHED
    IT. It does not and never did -- it returns early on `path.exists()`. That
    one word is why nobody went looking: the file was written 2026-07-21 and
    still read `completed: False` on 888 of 888 games six weeks later, which
    pinned `ncaaf_target_week` to 1 and the whole board to week 1. The week span
    was wrong too (1-6, measured as 1-13 and 15), from reading the row count and
    guessing the range.

    Measured 2026-08-27: with the CFBD quota exhausted, BOTH `/games` and
    `/ratings/sp` returned HTTP 429 and projections could not regenerate at all.
    Serving the schedule from disk reduces the hard dependency to exactly ONE
    endpoint, so a single successful SP+ fetch is all a regeneration needs.

    Returns None (not an empty list) when the cache is absent or unusable, so
    the caller falls through to the API rather than treating "no cache" as
    "no games" -- an empty schedule would silently produce zero projections.
    """
    path = Path(__file__).resolve().parents[1] / "data" / "ncaaf_source" / "historical_truth" / f"games_{season}.json.gz"
    if not path.exists():
        return None
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return None
    rows = payload if isinstance(payload, list) else (payload.get("data") if isinstance(payload, dict) else None)
    if not isinstance(rows, list):
        return None
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            if int(row.get("week") or 0) != int(week):
                continue
        except (TypeError, ValueError):
            continue
        # Regular season only, matching the API call's own params.
        if str(row.get("seasonType") or "regular").lower() != "regular":
            continue
        out.append(row)
    return out or None


def load_cfbd_games(season: int, week: int) -> dict[tuple[str, str], dict]:
    cached = _cached_games(season, week)
    if cached is not None:
        print(f"[games] season={season} week={week} source=cache rows={len(cached)}", flush=True)
        payload: object = cached
    else:
        payload = _cfbd_get("/games", {"year": season, "week": week, "seasonType": "regular", "classification": "fbs"})
        print(f"[games] season={season} week={week} source=api", flush=True)
    index: dict[tuple[str, str], dict] = {}
    if isinstance(payload, list):
        for game in payload:
            index[(norm(game.get("homeTeam", "")), norm(game.get("awayTeam", "")))] = game
    return index


def _ppa_cache_path(season: int) -> Path:
    root = str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip()
    base = Path(root) if root else Path(__file__).resolve().parents[1] / "data"
    return base / "ncaaf_source" / "historical_truth" / f"ppa_teams_{season}.json.gz"


def _read_ppa_cache(season: int) -> tuple[list, float] | None:
    """`(rows, age_seconds)` from the local PPA cache, or None."""
    path = _ppa_cache_path(season)
    if not path.exists():
        return None
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
        rows = payload.get("rows") if isinstance(payload, dict) else payload
        if not isinstance(rows, list) or not rows:
            return None
        written = float((payload or {}).get("written_epoch") or 0.0) if isinstance(payload, dict) else 0.0
        age = max(0.0, time.time() - written) if written else float("inf")
        return rows, age
    except Exception:
        return None


def _write_ppa_cache(season: int, rows: list) -> None:
    """Best effort. A cache that cannot be written must not fail the run."""
    if not rows:
        return
    try:
        path = _ppa_cache_path(season)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with gzip.open(tmp, "wt", encoding="utf-8") as handle:
            json.dump({"written_epoch": time.time(), "season": season, "rows": rows}, handle)
        tmp.replace(path)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[ppa] CACHE_WRITE_FAILED season={season} {type(exc).__name__}", flush=True)


# How old a cached PPA may be before we prefer a fresh fetch. PPA is a
# season-aggregate that moves as games are played, so a day is the natural
# grain -- the artifact this feeds regenerates daily by design
# (`interval_seconds=86400`).
_PPA_CACHE_FRESH_SECONDS = 86400.0

# The last PPA age actually used, in hours, or None when the fetch was fresh.
# Read by `main` to stamp provenance into the output CSV: a cached rating that
# cannot be told apart from a fresh one is the failure this whole file's
# `rating_source` column exists to prevent.
PPA_CACHE_AGE_HOURS: float | None = None


def load_ppa_ratings(season: int) -> dict[str, dict]:
    """Season-aggregate PPA, from cache when fresh and from cache when the
    quota is gone.

    `/ppa/teams` WAS THE LAST HARD CFBD DEPENDENCY IN A REGENERATION. `/games`
    has been served from `historical_truth` since `514d5ed4` and `/ratings/sp`
    is cached, so this one endpoint was the difference between "regenerates"
    and "dies" for the whole NCAAF projection artifact. Measured 2026-08-31:
    the artifact had been stale 4.25 days and every hourly attempt died here.

    THE STALE FALLBACK IS THE POINT, AND IT MUST ANNOUNCE ITSELF. When the
    quota is exhausted the choice is not "fresh PPA vs cached PPA", it is
    "cached PPA vs NO PROJECTIONS AT ALL" -- and a week-old season aggregate is
    a far better input than nothing. But a silent stale read is how a cached
    number gets mistaken for a measured one, so the age is logged AND stamped
    into `rating_source` on every row it produces.
    """
    global PPA_CACHE_AGE_HOURS
    PPA_CACHE_AGE_HOURS = None

    cached = _read_ppa_cache(season)
    if cached is not None and cached[1] <= _PPA_CACHE_FRESH_SECONDS:
        rows, age = cached
        PPA_CACHE_AGE_HOURS = round(age / 3600.0, 1)
        print(f"[ppa] season={season} source=cache age_hours={PPA_CACHE_AGE_HOURS} rows={len(rows)}", flush=True)
        payload: object = rows
    else:
        try:
            payload = _cfbd_get("/ppa/teams", {"year": season, "excludeGarbageTime": "true"})
            print(f"[ppa] season={season} source=api", flush=True)
            if isinstance(payload, list):
                _write_ppa_cache(season, payload)
        except QuotaExhausted:
            # The quota is KNOWN gone -- distinct from a network failure, which
            # is why the latch raises its own type. Serve the stale cache and
            # say how stale, or re-raise if there is nothing to serve.
            if cached is None:
                print(f"[ppa] season={season} source=none reason=quota_exhausted_and_cache_empty", flush=True)
                raise
            rows, age = cached
            PPA_CACHE_AGE_HOURS = round(age / 3600.0, 1)
            print(
                f"[ppa] season={season} source=cache_stale age_hours={PPA_CACHE_AGE_HOURS} "
                f"rows={len(rows)} reason=quota_exhausted -- STALE, and stamped into rating_source",
                flush=True,
            )
            payload = rows

    index: dict[str, dict] = {}
    if isinstance(payload, list):
        for row in payload:
            index[norm(row.get("team", ""))] = row
    return index


# Minimum prior games before a team's as-of PPA is trusted. Below this the
# team falls back to the prior season rather than being rated on two games --
# and it is reported as fallback, never silently averaged.
_MIN_ASOF_GAMES = 3


def load_ppa_games_week(season: int, week: int) -> list[dict]:
    """Per-GAME PPA for one REGULAR-SEASON week.

    `seasonType=regular` IS LOAD-BEARING AND ITS ABSENCE IS A WORSE LEAK THAN
    THE ONE THIS FILE EXISTS TO FIX. Without it, `/ppa/games?week=1` returns
    regular week 1 AND the postseason's "week 1" -- the College Football Playoff.
    Measured 2026-08-19: Ohio State came back with FIVE rows for 2024 week 1,
    one against Akron (the real week-1 game) and four against Texas, Notre Dame,
    Oregon and Tennessee, all played the following JANUARY. Aggregating
    "weeks < 8" was therefore importing games from months AFTER the target week,
    which is strictly worse than the season-aggregate leak it replaced.

    The tell was an impossible count, not a failing test: 10 prior games through
    week 7 for a team that plays once a week, and 231 rows in week 1 against
    ~100-127 in every other week. A postseason row is otherwise indistinguishable
    from a regular one -- same shape, same fields, plausible values.
    """
    payload = _cfbd_get("/ppa/games", {
        "year": season, "week": week,
        "seasonType": "regular", "excludeGarbageTime": "true",
    })
    return [row for row in (payload if isinstance(payload, list) else [])
            if str(row.get("seasonType") or "regular") == "regular"]


def load_ppa_ratings_asof(season: int, week: int) -> tuple[dict[str, dict], str]:
    """Team PPA aggregated over weeks STRICTLY BEFORE `week`.

    WHY THIS REPLACES `/ppa/teams`. That endpoint returns season-aggregate PPA --
    its own docstring below says so -- which for a completed season includes the
    game being predicted. Measured 2026-08-19 over 558 games of 2024:

        r(full-season PPA differential, margin) = 0.663   <- leaked
        r(as-of      PPA differential, margin) = 0.487   <- this function

    a 0.176 gap, inflating apparent skill by 36%. The as-of value sits in the
    0.3-0.5 band expected of honest prior form, which is the same frame that
    caught the NFL in-game leak at r = 0.988.

    AND THE OBVIOUS FIX IS A SILENT NO-OP, which is why this takes the longer
    route. `/ppa/teams` ACCEPTS `week=N` AND IGNORES IT -- measured, identical
    134 rows and identical 0.42 for Ohio State with and without `week=5`. Adding
    a week parameter there yields the same leaked number, a clean diff and a
    false all-clear. `/ppa/games` is the only week-scoped source.

    Returns the SAME SHAPE as `/ppa/teams` ({"offense": {"overall": x}, ...})
    so `offense_defense_rating` is unchanged.

    Cost: week-1 CFBD calls instead of 1. CFBD is not the OddsAPI budget and a
    full season is ~15 calls.
    """
    offs: dict[str, list[float]] = {}
    defs: dict[str, list[float]] = {}
    for wk in range(1, max(1, int(week))):
        for row in load_ppa_games_week(season, wk):
            team = row.get("team")
            o = (row.get("offense") or {}).get("overall")
            d = (row.get("defense") or {}).get("overall")
            if team is None or o is None or d is None:
                continue
            offs.setdefault(norm(team), []).append(float(o))
            defs.setdefault(norm(team), []).append(float(d))

    index: dict[str, dict] = {}
    for key, values in offs.items():
        if len(values) < _MIN_ASOF_GAMES:
            continue
        index[key] = {
            "offense": {"overall": sum(values) / len(values)},
            "defense": {"overall": sum(defs[key]) / len(defs[key])},
            "_asof_games": len(values),
        }
    if index:
        return index, f"cfbd_ppa_asof_{season}_through_wk{int(week) - 1}"

    # No usable in-season history (week 1, or a season that has not started).
    # The prior season's FULL aggregate is a legitimate preseason proxy and is
    # not a leak: it contains no information about the season being predicted.
    prior = load_ppa_ratings(season - 1)
    if prior:
        return prior, f"cfbd_ppa_season_{season - 1}_fallback_for_{season}"
    return {}, f"cfbd_ppa_asof_{season}_unavailable"


def load_ppa_ratings_with_fallback(season: int) -> tuple[dict[str, dict], str]:
    """PPA ratings are season-aggregate stats computed from games actually
    played that season -- for the first week(s) of a brand-new season, CFBD
    has nothing yet (confirmed empty for a pre-season 2026 request). Fall
    back to the prior season's final ratings as a preseason proxy for team
    strength, same idea real prediction systems use for week 1 of a new
    season. The fallback is whole-index (not per-team): PPA data for a
    season is either fully populated (games have been played) or entirely
    empty (none have), not partially populated.
    """
    index = load_ppa_ratings(season)
    if index:
        return index, f"cfbd_ppa_season_{season}"
    fallback_index = load_ppa_ratings(season - 1)
    if fallback_index:
        return fallback_index, f"cfbd_ppa_season_{season - 1}_fallback_for_{season}"
    return index, f"cfbd_ppa_season_{season}"


# SP+ -> engine-rating scale. CALIBRATED EMPIRICALLY, not derived.
#
# `build_drive_priors` does `clamp(0.5 + rating, 0.05, 0.95)`, so a rating
# outside about +/-0.45 CLAMPS. SP+ component ratings are points-per-game in the
# 10-40 band, so passing them raw would clamp every team to 0.95 and destroy
# exactly the discrimination they are here to provide.
#
# The divisor converts a centred SP+ component into that band. It is set so the
# projected margin SD across a real slate lands near the market's, which is the
# only defensible target: the model should be LESS dispersed than realised
# margins (SD ~20.4, that gap is game-day variance) and about as dispersed as
# the market (SD ~14.5).
SP_RATING_SCALE = 10.0

# Set from --refresh-sp-cache. Module-level because `load_sp_ratings` is called
# from other scripts (the re-fit harnesses import it directly) that have no
# argparse of their own and should get the cached path by default.
_SP_CACHE_REFRESH = False


def sp_ratings_cache_path(season: int) -> Path:
    """Beside the other CFBD caches this repo already keeps."""
    override = str(os.environ.get("SYNDICATE_SP_RATINGS_CACHE_DIR") or "").strip()
    base = Path(override) if override else (Path(__file__).resolve().parents[1] / "data" / "ncaaf_source" / "historical_truth")
    return base / f"sp_ratings_{season}.json"


def _read_sp_cache(path: Path) -> dict[str, tuple[float, float]]:
    """Never raises: a corrupt cache behaves exactly as if it were absent."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    teams = raw.get("teams") if isinstance(raw, dict) else None
    if not isinstance(teams, dict):
        return {}
    out: dict[str, tuple[float, float]] = {}
    for team, pair in teams.items():
        try:
            out[str(team)] = (float(pair[0]), float(pair[1]))
        except Exception:
            continue
    return out


def _write_sp_cache(path: Path, season: int, index: dict[str, tuple[float, float]]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "season": season,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "source": "cfbd /ratings/sp",
            "teams": {k: [v[0], v[1]] for k, v in sorted(index.items())},
        }, indent=1, sort_keys=True), encoding="utf-8")
    except Exception as exc:
        print(f"[sp_ratings] cache write failed ({type(exc).__name__}) -- continuing without it", flush=True)


def load_sp_ratings(season: int) -> dict[str, tuple[float, float]]:
    """`{norm(team): (offense_rating, defense_rating)}` from SP+, in POINTS.

    WHY SP+ REPLACES PPA AS THE RATING SOURCE. Backtested 2026-08-19 on ~740
    games per season, prior-season rating against the NEXT season's realised
    margins, so no leakage:

        prior->target   rating      r       residual SD
        2023 -> 2024    SP+         0.442   18.25   <- better
                        PPA diff    0.348   19.08
        2024 -> 2025    SP+         0.506   17.63   <- better
                        PPA diff    0.372   18.97

    SP+ wins on correlation and residual SD in BOTH independent pairs.

    It also fixes a units problem PPA could not. PPA `overall` is a PER-PLAY
    rate with SD 0.089; across the 51-game 2026 wk1 slate the resulting
    differential had SD 0.136, which the engine rendered as margin SD **1.74
    against a market SD of 14.46**. SP+ is already denominated in points per
    game (SD ~13), which is the quantity a margin model needs.

    `defense.rating` is POINTS ALLOWED -- lower is better -- so it is negated
    for the engine, whose `defense_rating` means "how good this defense is".
    """
    # CACHED ON DISK, because this is the only CFBD call a projections run
    # cannot get from an artifact we already hold — and it is the one that
    # blocks everything when the quota goes.
    #
    # Of the four endpoints this script hits, `/games` is already covered by
    # `historical_truth/games_<season>.json.gz` (888 rows, weeks 1-6 for 2026),
    # and `/ppa/*` is only the FALLBACK rating source. SP+ is the primary.
    #
    # A COMPLETED SEASON'S SP+ NEVER CHANGES, so re-fetching it every run buys
    # nothing and costs the quota. Measured 2026-08-27: a few full-season pulls
    # put EVERY CFBD endpoint behind HTTP 429 for over two hours — 20 retries,
    # all refused — which blocked the totals re-fit and the confirmation that a
    # promoted calibration artifact had loaded. Both were gated on this one call.
    #
    # In-season a rating still moves week to week, so the cache is keyed by
    # season and `--refresh-sp-cache` forces a re-fetch; the file is only ever
    # written after a successful, NON-EMPTY fetch, so a rate-limited run can
    # never poison it with an empty index.
    # THE LOADER'S CACHE FIRST. `ncaaf_historical_loader` now caches SP+ beside
    # games/drives/plays (`ensure_ratings_cached`), which is where a CFBD payload
    # belongs -- one owner, one refresh path. This script's own JSON cache stays
    # as the second lookup so an existing one keeps working, but the loader's is
    # authoritative and is what a scheduled refresh will populate.
    if not _SP_CACHE_REFRESH:
        try:
            from syndicate.features.football.sim_engine.smartsim2.historical_truth.ncaaf_historical_loader import (
                load_cached_ratings,
            )
            raw = load_cached_ratings(season)
        except Exception:
            raw = None
        if raw:
            index: dict[str, tuple[float, float]] = {}
            for row in raw:
                team = row.get("team") if isinstance(row, dict) else None
                if not team or team == "nationalAverages":
                    continue
                off = (row.get("offense") or {}).get("rating")
                dfn = (row.get("defense") or {}).get("rating")
                if off is None or dfn is None:
                    continue
                index[norm(team)] = (float(off), float(dfn))
            if index:
                print(f"[sp_ratings] season={season} source=loader_cache teams={len(index)}", flush=True)
                return index

    cache_path = sp_ratings_cache_path(season)
    cached = {} if _SP_CACHE_REFRESH else _read_sp_cache(cache_path)
    if cached:
        # `log` is defined INSIDE main(); this runs at module scope, so print.
        # `flush=True` because todo.md records logger.info never reaching
        # Render's log collector.
        print(f"[sp_ratings] season={season} source=cache teams={len(cached)} path={cache_path}", flush=True)
        return cached

    payload = _cfbd_get("/ratings/sp", {"year": season})
    index: dict[str, tuple[float, float]] = {}
    if isinstance(payload, list):
        for row in payload:
            team = row.get("team")
            if not team or team == "nationalAverages":
                continue
            off = (row.get("offense") or {}).get("rating")
            dfn = (row.get("defense") or {}).get("rating")
            if off is None or dfn is None:
                continue
            index[norm(team)] = (float(off), float(dfn))
    if index:
        _write_sp_cache(cache_path, season, index)
        print(f"[sp_ratings] season={season} source=api teams={len(index)} cached={cache_path}", flush=True)
    else:
        # NEVER cache an empty index. A rate-limited or malformed response would
        # otherwise be written once and served forever as though it were real.
        print(f"[sp_ratings] season={season} source=api teams=0 NOT CACHED (empty)", flush=True)
    return index


def sp_offense_defense_rating(team: str, sp_index: dict[str, tuple[float, float]],
                              means: tuple[float, float]) -> tuple[float, float] | None:
    """SP+ components -> engine ratings, centred on the league mean.

    CENTRING IS NOT COSMETIC. The engine treats 0.0 as an average team
    (`0.5 + rating`), and SP+ components are absolute points-per-game around a
    non-zero league mean. Feeding them uncentred would shift EVERY team the same
    way, which is the same bias that put the NFL payload's league-mean
    offense_index at 0.405 against a neutral 0.500.

    Returns None for an unmatched team rather than (0.0, 0.0). A neutral default
    is indistinguishable from a genuinely average team, and the caller needs to
    know to fall back rather than silently rate an unknown team as league-average.
    """
    row = sp_index.get(norm(team))
    if row is None:
        return None
    off_mean, def_mean = means
    offense = (row[0] - off_mean) / SP_RATING_SCALE
    # negate: SP+ defense is points ALLOWED, engine wants defensive STRENGTH
    defense = -(row[1] - def_mean) / SP_RATING_SCALE
    return offense, defense


def sp_league_means(sp_index: dict[str, tuple[float, float]]) -> tuple[float, float]:
    if not sp_index:
        return (0.0, 0.0)
    offs = [v[0] for v in sp_index.values()]
    defs = [v[1] for v in sp_index.values()]
    return (sum(offs) / len(offs), sum(defs) / len(defs))


def offense_defense_rating(team: str, ppa_index: dict[str, dict]) -> tuple[float, float]:
    row = ppa_index.get(norm(team))
    if row is None:
        return 0.0, 0.0
    offense = float((row.get("offense") or {}).get("overall") or 0.0)
    defense_allowed = float((row.get("defense") or {}).get("overall") or 0.0)
    return offense, -defense_allowed


def games_from_cfbd_when_engine_schedule_empty(cfbd_games: dict[tuple[str, str], dict]) -> list[dict[str, str]]:
    """Fallback game list for a season the legacy engine has no schedule for
    (its predicted-totals CSV is a single, non-season-partitioned file that
    is only ever refreshed for the engine's own season). Reuses the same
    real CFBD game data already fetched for cross-referencing -- filtered to
    strict FBS-vs-FBS, matching the same check the normal engine-schedule
    path applies downstream."""
    rows = []
    for game in cfbd_games.values():
        if game.get("homeClassification") != "fbs" or game.get("awayClassification") != "fbs":
            continue
        home_team = str(game.get("homeTeam") or "").strip()
        away_team = str(game.get("awayTeam") or "").strip()
        if not home_team or not away_team:
            continue
        rows.append({"home_team": home_team, "away_team": away_team})
    return rows


def build_projection(
    *,
    season: int,
    week: int,
    home_team: str,
    away_team: str,
    game_id: str,
    ppa_index: dict[str, dict],
    rating_source: str,
    seeds: int = SEEDS_PER_GAME,
    sp_index: dict[str, tuple[float, float]] | None = None,
    sp_means: tuple[float, float] = (0.0, 0.0),
) -> SmartSimNcaafProjection:
    # SP+ FIRST, PPA AS FALLBACK. SP+ is points-per-game and backtests better on
    # margin (r 0.506 vs 0.372, residual SD 17.63 vs 18.97 over 740 games); PPA
    # is a per-play rate whose differential SD of 0.136 produced margin SD 1.74
    # against a market 14.46. Per team, so one unrated team does not discard the
    # whole slate's SP+ ratings.
    home_sp = sp_offense_defense_rating(home_team, sp_index or {}, sp_means)
    away_sp = sp_offense_defense_rating(away_team, sp_index or {}, sp_means)
    if home_sp is not None and away_sp is not None:
        (home_off, home_def), (away_off, away_def) = home_sp, away_sp
    else:
        home_off, home_def = offense_defense_rating(home_team, ppa_index)
        away_off, away_def = offense_defense_rating(away_team, ppa_index)

    home_scores: list[int] = []
    away_scores: list[int] = []
    for seed in range(1, seeds + 1):
        sim_input = SmartSim2SimulationInput(
            home_team=home_team,
            away_team=away_team,
            seed=seed,
            home_offense_rating=home_off,
            home_defense_rating=home_def,
            away_offense_rating=away_off,
            away_defense_rating=away_def,
        )
        output = simulate_game(sim_input, profile=NCAAF_CALIBRATION_PROFILE)
        home_scores.append(output.final_score["home"])
        away_scores.append(output.final_score["away"])

    margins = [h - a for h, a in zip(home_scores, away_scores)]
    totals = [h + a for h, a in zip(home_scores, away_scores)]
    home_win_rate = sum(1 for m in margins if m > 0) / seeds

    return SmartSimNcaafProjection(
        game_id=game_id,
        season=season,
        week=week,
        home_team=home_team,
        away_team=away_team,
        home_score_mean=round(statistics.fmean(home_scores), 3),
        away_score_mean=round(statistics.fmean(away_scores), 3),
        margin_mean=round(statistics.fmean(margins), 3),
        total_mean=round(statistics.fmean(totals), 3),
        margin_stdev=round(statistics.pstdev(margins), 3),
        total_stdev=round(statistics.pstdev(totals), 3),
        home_win_rate=round(home_win_rate, 4),
        seeds_used=seeds,
        profile_name=PROFILE_NAME,
        rating_source=rating_source,
        generated_at=datetime.now(timezone.utc).isoformat(),
        # Read from the LOADED profile's metadata, not from a constant -- the
        # point is to record which calibration actually produced this row.
        profile_source=str(NCAAF_CALIBRATION_PROFILE_METADATA.get("source") or "unknown"),
        profile_version=str(NCAAF_CALIBRATION_PROFILE_METADATA.get("version") or ""),
    )


def _load_env() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        return
    load_dotenv()


def main() -> None:
    _load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-sp-cache", action="store_true",
                        help="Ignore any cached SP+ ratings and re-fetch. In-season a rating still moves week to week; a completed season's never does.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--seeds", type=int, default=SEEDS_PER_GAME)
    parser.add_argument("--leaked-season-ppa", action="store_true",
                        help="use season-aggregate PPA (LEAKED for a completed season). "
                             "Reproduces pre-2026-08-19 behaviour for comparison only.")
    parser.add_argument("--ratings-season", type=int, default=None,
                        help="Season whose SP+ ratings to use. Defaults to --season. "
                             "SET IT TO THE PRIOR SEASON TO BACKTEST A COMPLETED ONE: "
                             "/ratings/sp?year=<completed season> returns FINAL ratings, "
                             "which contain the outcome of the games being predicted. "
                             "The rating_source records whichever season is actually "
                             "used, so a leaked run is identifiable downstream rather "
                             "than merely disclaimed here.")
    parser.add_argument("--progress-log", type=Path, default=None)
    args = parser.parse_args()
    global _SP_CACHE_REFRESH
    _SP_CACHE_REFRESH = bool(getattr(args, 'refresh_sp_cache', False))

    def log(message: str) -> None:
        if args.progress_log:
            with args.progress_log.open("a", encoding="utf-8") as handle:
                handle.write(f"{time.strftime('%H:%M:%S')} {message}\n")

    start = time.time()
    log(f"START season={args.season} week={args.week} seeds={args.seeds}")

    # KEEP THE SCHEDULE'S `completed` FLAGS HONEST. This is the producer half of
    # the games cache, and it runs HERE because this script is the NCAAF process
    # that already runs on refresh-worker on a daily interval, already holds the
    # CFBD key, and already has the quota latch wired.
    #
    # It cannot live in `ensure_games_cached`: that is reached from Flask request
    # handlers via `ncaaf_target_week`, and the web service does no on-request
    # backfill.
    #
    # Measured 2026-09-01, which is why this exists: `games_2026.json.gz` was
    # written 2026-07-21 and never re-fetched, so 888 of 888 games still read
    # `completed: False`. `ncaaf_target_week` is `min(week with an unplayed
    # game)` -> 1, permanently, and `_week_is_within_pregame_window` then trimmed
    # the board's week list to `[1]` while artifacts existed for weeks 1-13, 15.
    #
    # Best-effort, like the publish below: `refresh_games_cache` never raises,
    # and a generator must not die because a refresh did.
    try:
        from syndicate.features.football.sim_engine.smartsim2.historical_truth.ncaaf_historical_loader import (
            refresh_games_cache,
        )

        games_refresh = refresh_games_cache(args.season)
    except Exception as exc:  # noqa: BLE001 - a refresh must never fail generation
        games_refresh = {"status": "raised", "error": f"{type(exc).__name__}: {exc}"}
    # Printed every run, including the no-op ones. `status=fresh` and
    # `status=throttled` are the healthy quiet states; `status=stale` never
    # appears because a stale cache is acted on rather than reported.
    log(f"GAMES_CACHE_REFRESH {' '.join(f'{k}={v}' for k, v in games_refresh.items())}")

    schedule_rows = load_engine_schedule(args.season, args.week)
    log(f"ENGINE_SCHEDULE rows={len(schedule_rows)}")

    cfbd_games = load_cfbd_games(args.season, args.week)
    log(f"CFBD_GAMES fbs_vs_any={len(cfbd_games)}")

    used_cfbd_schedule_fallback = False
    if not schedule_rows:
        schedule_rows = games_from_cfbd_when_engine_schedule_empty(cfbd_games)
        used_cfbd_schedule_fallback = True
        log(f"ENGINE_SCHEDULE_EMPTY falling back to CFBD games directly rows={len(schedule_rows)}")

    # AS-OF, not season-aggregate. `load_ppa_ratings_with_fallback` is retained
    # below for reference and for the `--leaked-season-ppa` escape hatch, but the
    # default is now leak-free. See `load_ppa_ratings_asof`.
    if args.leaked_season_ppa:
        ppa_index, rating_source = load_ppa_ratings_with_fallback(args.season)
        print("WARNING: --leaked-season-ppa in use. Ratings contain the games "
              "being predicted; any accuracy number from this run is an UPPER "
              "BOUND, not a measurement.", flush=True)
    else:
        ppa_index, rating_source = load_ppa_ratings_asof(args.season, args.week)
    # PROVENANCE TRAVELS WITH THE NUMBER. When PPA came from a stale cache --
    # which is what happens while the CFBD monthly quota is exhausted -- every
    # row this run writes carries that fact in `rating_source`, the same column
    # that already distinguishes which SEASON's ratings were used. A cached
    # rating that reads identically to a fresh one is precisely the confusion
    # this column exists to prevent, and the whole reason the stale fallback is
    # safe to have at all.
    if PPA_CACHE_AGE_HOURS is not None:
        rating_source = f"{rating_source}[ppa_cache_age_hours={PPA_CACHE_AGE_HOURS:g}]"
        log(f"PPA_FROM_CACHE age_hours={PPA_CACHE_AGE_HOURS:g} -- stamped into rating_source")
    log(f"PPA_RATINGS teams={len(ppa_index)} rating_source={rating_source}")

    # SP+ is the primary rating source; PPA above stays as the per-team fallback.
    ratings_season = args.ratings_season if args.ratings_season is not None else args.season
    sp_index = load_sp_ratings(ratings_season)
    sp_means = sp_league_means(sp_index)
    if sp_index:
        rating_source = f"cfbd_sp_plus_{ratings_season}[scale={SP_RATING_SCALE:g}]+{rating_source}"
    if ratings_season != args.season:
        log(f"RATINGS_SEASON_OVERRIDE ratings={ratings_season} games={args.season} "
            f"(prior-season ratings -> leak-free backtest)" )
    log(f"SP_RATINGS teams={len(sp_index)} off_mean={sp_means[0]:.2f} def_mean={sp_means[1]:.2f}")

    projections: list[SmartSimNcaafProjection] = []
    skipped_no_cfbd_match: list[str] = []
    skipped_not_fbs_vs_fbs: list[str] = []

    for row in schedule_rows:
        home_team = str(row.get("home_team") or "").strip()
        away_team = str(row.get("away_team") or "").strip()
        if not home_team or not away_team:
            continue
        cfbd_game = cfbd_games.get((norm(home_team), norm(away_team)))
        if cfbd_game is None:
            skipped_no_cfbd_match.append(f"{away_team} @ {home_team}")
            continue
        if cfbd_game.get("homeClassification") != "fbs" or cfbd_game.get("awayClassification") != "fbs":
            skipped_not_fbs_vs_fbs.append(f"{away_team} @ {home_team}")
            continue
        game_id = str(cfbd_game.get("id") or f"{args.season}_{args.week}_{home_team}_{away_team}".replace(" ", "_"))
        projection = build_projection(
            season=args.season,
            week=args.week,
            home_team=home_team,
            away_team=away_team,
            game_id=game_id,
            ppa_index=ppa_index,
            sp_index=sp_index,
            sp_means=sp_means,
            rating_source=rating_source,
            seeds=args.seeds,
        )
        projections.append(projection)
        log(f"PROJECTED {away_team} @ {home_team} -> {projection.home_score_mean:.1f}-{projection.away_score_mean:.1f}")

    path = write_projection_artifact(projections, season=args.season, week=args.week, data_root=DATA_ROOT)
    elapsed = time.time() - start

    log(f"WRITE_DONE path={path} projections={len(projections)} elapsed={elapsed:.1f}s")
    log(f"SKIPPED_NO_CFBD_MATCH count={len(skipped_no_cfbd_match)} {skipped_no_cfbd_match}")
    log(f"SKIPPED_NOT_FBS_VS_FBS count={len(skipped_not_fbs_vs_fbs)} {skipped_not_fbs_vs_fbs}")
    print(f"engine_schedule_rows={len(schedule_rows)}")
    print(f"used_cfbd_schedule_fallback={used_cfbd_schedule_fallback}")
    print(f"rating_source={rating_source}")
    print(f"projections_written={len(projections)}")
    print(f"skipped_no_cfbd_match={len(skipped_no_cfbd_match)}: {skipped_no_cfbd_match}")
    print(f"skipped_not_fbs_vs_fbs={len(skipped_not_fbs_vs_fbs)}: {skipped_not_fbs_vs_fbs}")
    print(f"elapsed_seconds={elapsed:.1f}")
    print(f"artifact_path={path}")

    # PUBLISH TO WEB. Without this the whole run is inert for the board.
    #
    # Measured 2026-08-19: refresh-worker regenerated this artifact on its own
    # disk and the served board did not move for HOURS, because the worker and
    # web do not share a disk and nothing pushed the file across. Web reads
    # SYNDICATE_NCAAF_SOURCE_ROOT (its MOUNTED DISK); the only other way in is
    # committing the CSV to git and riding a web deploy, which is a deploy per
    # model change and leaves the worker's own autorun pointless.
    #
    # The relative path lands where web already reads: the worker publishes
    # `ncaaf_source/data/smartsim2_projections_<season>_wk<week>.csv` relative
    # to SYNDICATE_DATA_ROOT, and web writes it under its own data root --
    # `/opt/render/project/data/ncaaf_source/data/...`, which is exactly
    # SYNDICATE_NCAAF_SOURCE_ROOT. So no read-path change is needed on web.
    #
    # Best-effort by design: publish_hot_artifact never raises and returns
    # False when unconfigured (every local run), when the path is not
    # allowlisted, or on a network error. A generator must not fail because a
    # transfer did -- the artifact on disk is still correct and still the
    # output of this script.
    try:
        from syndicate.features.shared.artifact_publisher import publish_hot_artifact

        published = publish_hot_artifact(Path(path))
    except Exception as exc:  # noqa: BLE001 - transfer must never fail generation
        published = False
        print(f"artifact_publish_error={type(exc).__name__}: {exc}", flush=True)
    # Printed either way. `published=False` on the worker means the board is
    # still serving whatever it had -- the condition that was invisible for the
    # entire life of this gap, and the first thing to check when a model change
    # does not show up.
    print(f"artifact_published={published}", flush=True)


if __name__ == "__main__":
    main()
