"""
Context: Syndicate Simulation System
See: docs/ai_context/architecture.md

Role:
- Normalizes each sport's own, heterogeneous "here are today's games and their
  start times" source into one shared shape, independent of whether that
  sport's predictions/props have been generated yet for the date.
- Built to let the always-on refresh loop (live_refresh_loop.py) reason about
  schedule timing (e.g. "force a resim within N minutes of tip-off") without
  depending on the once-daily GitHub Actions pipeline that used to be the only
  place doing this.

Constraints:
- Read-only with respect to prediction/props state. Never triggers sim/props
  generation itself -- callers decide what to do with the schedule.
- Must degrade gracefully: a source being unreachable or a game missing a
  resolvable start time returns a partial/empty result, never raises, so a
  scheduling decision elsewhere in the refresh loop can't be taken down by a
  flaky upstream API.
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from syndicate.features.shared.refresh_state_store import read_json_file
from syndicate.features.shared.refresh_state_store import reports_root
from syndicate.features.shared.refresh_state_store import write_json_file
from syndicate.features.shared.source_roots import preferred_artifact_roots
from syndicate.features.shared.source_roots import repo_root_from

REPO_ROOT = repo_root_from(__file__)


@dataclass(frozen=True)
class ScheduleEvent:
    sport: str
    event_id: str
    home: str
    away: str
    start_time_utc: str | None  # ISO8601 "...Z"; None if the source couldn't resolve a time
    # MLB-only (other sports leave these None): StatsAPI numeric team ids, needed
    # to slice lineups_last_known_by_team.json (keyed by team_id) down to a single
    # game for per-game sim-input fingerprinting. See live_refresh_loop.py's
    # _mlb_sim_input_fingerprint_by_game().
    home_team_id: int | None = None
    away_team_id: int | None = None

    def start_time_epoch(self) -> float | None:
        if not self.start_time_utc:
            return None
        try:
            text = str(self.start_time_utc).strip()
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            return datetime.fromisoformat(text).astimezone(timezone.utc).timestamp()
        except Exception:
            return None


def _default_ttl_seconds() -> int:
    raw = str(os.environ.get("SYNDICATE_SCHEDULE_ADAPTER_TTL_SECONDS") or "").strip()
    try:
        value = int(raw or 900)
    except Exception:
        value = 900
    return max(60, value)


def _cache_path(sport: str, date_str: str) -> Path:
    return reports_root() / "schedule_adapter" / f"{sport}_{date_str}.json"


def _read_cache(sport: str, date_str: str) -> list[dict[str, Any]] | None:
    payload = read_json_file(_cache_path(sport, date_str))
    if not isinstance(payload, dict):
        return None
    fetched_at = payload.get("fetchedAt")
    try:
        age_seconds = float(datetime.now(timezone.utc).timestamp()) - float(fetched_at)
    except Exception:
        return None
    if age_seconds > _default_ttl_seconds():
        return None
    events = payload.get("events")
    return events if isinstance(events, list) else None


def _write_cache(sport: str, date_str: str, rows: list[dict[str, Any]]) -> None:
    try:
        write_json_file(
            _cache_path(sport, date_str),
            {"fetchedAt": datetime.now(timezone.utc).timestamp(), "date": date_str, "sport": sport, "events": rows},
        )
    except Exception:
        pass


def _event_from_row(sport: str, row: dict[str, Any]) -> ScheduleEvent | None:
    event_id = str(row.get("event_id") or "").strip()
    home = str(row.get("home") or "").strip()
    away = str(row.get("away") or "").strip()
    if not event_id or not home or not away:
        return None
    start_time_utc = row.get("start_time_utc")

    def _team_id(value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except Exception:
            return None

    return ScheduleEvent(
        sport=sport,
        event_id=event_id,
        home=home,
        away=away,
        start_time_utc=str(start_time_utc).strip() if start_time_utc else None,
        home_team_id=_team_id(row.get("home_team_id")),
        away_team_id=_team_id(row.get("away_team_id")),
    )


# ---------------------------------------------------------------------------
# MLB: no persisted season schedule file exists (unlike NBA/WNBA), so this
# always goes out to the MLB Stats API. Run via subprocess (a tiny helper
# script under scripts/) rather than importing vendor/mlb_bettingv2 in-process,
# so a bug in the vendored client can't take down this shared module that
# every sport's gating logic depends on.
# ---------------------------------------------------------------------------

def _fetch_mlb_schedule(date_str: str, *, timeout_s: float = 20.0) -> list[dict[str, Any]]:
    helper = REPO_ROOT / "scripts" / "fetch_mlb_schedule_for_date.py"
    if not helper.exists():
        return []
    python_exe = sys.executable if (sys.executable and Path(sys.executable).exists()) else "python"
    try:
        result = subprocess.run(
            [python_exe, str(helper), "--date", date_str],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        if result.returncode != 0:
            return []
        payload = json.loads(result.stdout or "[]")
        return payload if isinstance(payload, list) else []
    except Exception:
        return []


# ---------------------------------------------------------------------------
# NBA / WNBA: a whole-season schedule file already gets written by the
# vendored `fetch-schedule` CLI as a pre-step of the normal props refresh.
# Read whatever's on disk; only invoke the CLI ourselves if nothing usable is
# there yet (first run on a fresh disk, or the season file is missing).
# ---------------------------------------------------------------------------

_BASKETBALL_ENV_VAR = {"nba": "SYNDICATE_NBA_SOURCE_ROOT", "wnba": "SYNDICATE_WNBA_SOURCE_ROOT"}
_BASKETBALL_LOCAL_DIR = {"nba": "nba_source", "wnba": "wnba_source"}
_BASKETBALL_VENDOR_DIR = {"nba": "nba_betting_repo", "wnba": "wnba_betting_repo"}
_BASKETBALL_PACKAGE = {"nba": "nba_betting", "wnba": "wnba_betting"}


def _basketball_processed_roots(sport: str) -> list[Path]:
    roots = preferred_artifact_roots(__file__, env_var=_BASKETBALL_ENV_VAR[sport], local_dir_name=_BASKETBALL_LOCAL_DIR[sport])
    out: list[Path] = []
    for root in roots:
        out.append(root / "data" / "processed")
        out.append(root / "source_artifacts" / "data" / "processed")
    return out


def _read_basketball_schedule_rows(sport: str, date_str: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for processed_root in _basketball_processed_roots(sport):
        if not processed_root.exists():
            continue
        for path in glob.glob(str(processed_root / "schedule_*.json")):
            try:
                payload = json.loads(Path(path).read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(payload, list):
                continue
            for row in payload:
                if not isinstance(row, dict):
                    continue
                row_date = str(row.get("date_utc") or "").strip()[:10]
                if row_date != date_str:
                    continue
                # A postponed/cancelled game's date_utc can still match the
                # query date -- without this it reads back as a real
                # scheduled event (wrong tip-off-window triggers, wrong
                # "does this date have games" answers). Same underlying gap
                # as vendor/wnba_betting_repo/.../cli.py's _load_schedule_day,
                # fixed there for the same reason.
                status_text = str(row.get("game_status_text") or "").strip().lower()
                if status_text in {"postponed", "cancelled", "canceled", "suspended"}:
                    continue
                rows.append(
                    {
                        "event_id": row.get("game_id"),
                        "home": row.get("home_tricode") or row.get("home_name"),
                        "away": row.get("away_tricode") or row.get("away_name"),
                        "start_time_utc": row.get("datetime_utc"),
                    }
                )
    return rows


def _fetch_basketball_schedule_via_cli(sport: str, *, timeout_s: float = 60.0) -> bool:
    source_root = REPO_ROOT / "vendor" / _BASKETBALL_VENDOR_DIR[sport]
    if not source_root.exists():
        return False
    python_exe = sys.executable if (sys.executable and Path(sys.executable).exists()) else "python"
    env = dict(os.environ)
    src_dir = str(source_root / "src")
    existing = str(env.get("PYTHONPATH") or "").strip()
    env["PYTHONPATH"] = src_dir if not existing else f"{src_dir}{os.pathsep}{existing}"
    env.setdefault("PYTHONUNBUFFERED", "1")
    try:
        result = subprocess.run(
            [python_exe, "-m", f"{_BASKETBALL_PACKAGE[sport]}.cli", "fetch-schedule"],
            cwd=str(source_root),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        return result.returncode == 0
    except Exception:
        return False


def _fetch_basketball_schedule(sport: str, date_str: str) -> list[dict[str, Any]]:
    rows = _read_basketball_schedule_rows(sport, date_str)
    if rows:
        return rows
    if _fetch_basketball_schedule_via_cli(sport):
        rows = _read_basketball_schedule_rows(sport, date_str)
    return rows


# ---------------------------------------------------------------------------
# NHL: pure Syndicate code (syndicate/local_nhl_odds.py), safe to import
# in-process -- it's not a vendored subprocess boundary like MLB/NBA/WNBA.
# ---------------------------------------------------------------------------

def _fetch_nhl_schedule(date_str: str) -> list[dict[str, Any]]:
    try:
        from syndicate.local_nhl_odds import NhlWebClient
    except Exception:
        return []
    try:
        client = NhlWebClient()
        raw_rows = client.scoreboard_day(date_str)
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        game_pk = row.get("gamePk")
        rows.append(
            {
                "event_id": str(game_pk) if game_pk is not None else None,
                "home": row.get("home"),
                "away": row.get("away"),
                "start_time_utc": row.get("gameDate"),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Soccer: pure Syndicate code (espn_lineups.fetch_events), same in-process
# posture as NHL above. Unlike every other sport here, soccer is 10
# independently-scheduled leagues rather than one competition, so this loops
# over whichever leagues are currently in season (see
# syndicate/features/soccer/sources.py's active_leagues_for_date -- MLS runs
# Feb-Dec, the rest follow the Aug-May European calendar) and merges their
# events into one list under the single "soccer" sport key every other
# _FETCHERS/consumer (look-ahead, _LIVE_STATUS_CHECKERS) already expects.
# Event ids are prefixed with the league slug: ESPN ids are only unique
# within one competition, and ScheduleEvent.event_id is read as a bare string
# by callers like _mlb_sim_input_fingerprint_by_game for other sports, so an
# unprefixed id could collide across two leagues' fixtures on the same date.
# ---------------------------------------------------------------------------

def _fetch_soccer_schedule(date_str: str) -> list[dict[str, Any]]:
    try:
        from syndicate.features.soccer.ingestion.espn_lineups import fetch_events
        from syndicate.features.soccer.sources import active_leagues_for_date
    except Exception:
        return []
    compact = str(date_str).replace("-", "")
    window = f"{compact}-{compact}"
    rows: list[dict[str, Any]] = []
    for league in active_leagues_for_date(date_str):
        try:
            events = fetch_events(league, date_windows=[window])
        except Exception:
            continue
        for event in events:
            event_id = str(event.get("event_id") or "").strip()
            if not event_id:
                continue
            rows.append(
                {
                    "event_id": f"{league}:{event_id}",
                    "home": event.get("home_team"),
                    "away": event.get("away_team"),
                    "start_time_utc": event.get("date"),
                }
            )
    return rows


# ---------------------------------------------------------------------------
# NFL / NCAAF: neither has a schedule source anywhere else in this codebase
# (their refresh steps auto-infer season/week from existing recommendation
# snapshots rather than fetching a real per-game kickoff-time schedule) --
# unlike every fetcher above, this isn't reading an existing pipeline, it's
# the first schedule source these two sports have. Uses ESPN's public
# unauthenticated scoreboard API directly (same one
# fetch_espn_live_status_for_date.py hits via subprocess for the live-status
# check; this one runs in-process like NHL/soccer above since it's a single
# GET with no vendored-repo import risk).
# ---------------------------------------------------------------------------

_ESPN_FOOTBALL_LEAGUE = {
    "nfl": "nfl",
    "ncaaf": "college-football",
}


def _fetch_espn_football_schedule(
    sport: str,
    date_str: str,
    *,
    timeout: int = 12,
    strict: bool = False,
) -> list[dict[str, Any]]:
    """`strict=True` re-raises transport failures instead of returning [].

    Default stays False so every existing caller is unchanged. The strict path
    exists for callers that GATE on emptiness: a swallowed timeout and a genuine
    "no games today" are the same empty list, and a gate that cannot tell them
    apart silently turns itself off whenever ESPN is slow. That failure mode has
    already burned this repo twice -- see audit_slate_coverage.py, which exits 2
    on fetch failure for exactly this reason.
    """
    league_slug = _ESPN_FOOTBALL_LEAGUE.get(sport)
    if not league_slug:
        return []
    try:
        compact_date = datetime.strptime(str(date_str).strip(), "%Y-%m-%d").strftime("%Y%m%d")
    except ValueError:
        return []
    url = (
        f"https://site.api.espn.com/apis/site/v2/sports/football/{league_slug}/scoreboard"
        f"?dates={urllib.parse.quote(compact_date)}"
    )
    # Confirmed live 2026-08-05: ESPN's scoreboard API returns HTTP 403 for
    # this exact bare "User-Agent: Mozilla/5.0" header when called from
    # Render's outbound IP (found via the identical pattern in wnba/cards.py
    # and fetch_espn_live_status_for_date.py -- see either's matching
    # comment for the full probe results). Sending no custom User-Agent at
    # all -- urllib's own honest default -- was the confirmed-working
    # variant; this site shares the exact byte-identical header dict that
    # was proven blocked, so fixing it proactively rather than waiting to
    # rediscover the same bug for NFL/NCAAF schedules.
    request_obj = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(request_obj, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        if strict:
            raise
        return []

    rows: list[dict[str, Any]] = []
    events = payload.get("events") if isinstance(payload, dict) else None
    for event in events or []:
        if not isinstance(event, dict):
            continue
        competitions = event.get("competitions") or []
        competition = competitions[0] if competitions else {}
        competitors = competition.get("competitors") or []
        home = next((c for c in competitors if c.get("homeAway") == "home"), {})
        away = next((c for c in competitors if c.get("homeAway") == "away"), {})
        event_id = str(event.get("id") or "").strip()
        if not event_id:
            continue
        rows.append(
            {
                "event_id": event_id,
                "home": (home.get("team") or {}).get("displayName"),
                "away": (away.get("team") or {}).get("displayName"),
                "start_time_utc": event.get("date"),
            }
        )
    return rows


def _fetch_espn_football_live_state(sport: str, date_str: str, *, timeout: int = 12) -> list[dict[str, Any]]:
    """Sibling to _fetch_espn_football_schedule: hits the exact same ESPN
    scoreboard endpoint but extracts real live status/score/clock instead of
    discarding everything except event_id/home/away/start_time_utc.

    Deliberately NOT folded into _fetch_espn_football_schedule itself: that
    function's rows feed ScheduleEvent via _event_from_row (extra dict keys
    are silently ignored there, so folding would be harmless) and are cached
    through fetch_schedule_for_date's TTL cache -- fine for "when does this
    game start" but wrong for "what's the score right now", which callers
    need fresh on every live-lens tick. Kept as an uncached, standalone call
    so a caller can decide its own polling cadence instead of inheriting the
    schedule cache's 900s default.
    """
    league_slug = _ESPN_FOOTBALL_LEAGUE.get(sport)
    if not league_slug:
        return []
    try:
        compact_date = datetime.strptime(str(date_str).strip(), "%Y-%m-%d").strftime("%Y%m%d")
    except ValueError:
        return []
    url = (
        f"https://site.api.espn.com/apis/site/v2/sports/football/{league_slug}/scoreboard"
        f"?dates={urllib.parse.quote(compact_date)}"
    )
    # Same bare-Request, no-custom-header pattern as _fetch_espn_football_schedule
    # above -- confirmed live 2026-08-05 that ESPN 403s this exact endpoint
    # for Render's outbound IP when any custom User-Agent is sent (see that
    # function's comment for the full probe results). Do not add headers here.
    request_obj = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(request_obj, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return []

    rows: list[dict[str, Any]] = []
    events = payload.get("events") if isinstance(payload, dict) else None
    for event in events or []:
        if not isinstance(event, dict):
            continue
        competitions = event.get("competitions") or []
        competition = competitions[0] if competitions else {}
        competitors = competition.get("competitors") or []
        home = next((c for c in competitors if c.get("homeAway") == "home"), {})
        away = next((c for c in competitors if c.get("homeAway") == "away"), {})
        event_id = str(event.get("id") or "").strip()
        if not event_id:
            continue

        status = event.get("status") if isinstance(event.get("status"), dict) else {}
        status_type = status.get("type") if isinstance(status.get("type"), dict) else {}

        def _score(value: Any) -> float | None:
            try:
                if value is None or str(value).strip() == "":
                    return None
                return float(value)
            except (TypeError, ValueError):
                return None

        # ESPN's standard scoreboard shape puts period/displayClock directly
        # on `status` (not nested under `status.type`, which only carries
        # id/name/state/completed/description/detail/shortDetail) -- fall
        # back to status.type's copy if present, since some ESPN sports feeds
        # (e.g. wnba/cards.py's own basketball scoreboard reader) have been
        # observed nesting it there instead.
        period_raw = status.get("period")
        if period_raw in (None, ""):
            period_raw = status_type.get("period")
        try:
            period = int(period_raw) if period_raw not in (None, "") else None
        except (TypeError, ValueError):
            period = None

        display_clock = str(status.get("displayClock") or status_type.get("displayClock") or "").strip()

        rows.append(
            {
                "event_id": event_id,
                "home": (home.get("team") or {}).get("displayName"),
                "away": (away.get("team") or {}).get("displayName"),
                "home_abbr": (home.get("team") or {}).get("abbreviation"),
                "away_abbr": (away.get("team") or {}).get("abbreviation"),
                "home_score": _score(home.get("score")),
                "away_score": _score(away.get("score")),
                # "pre" | "in" | "post" -- ESPN's own three-value game-state enum.
                "state": str(status_type.get("state") or "").strip().lower(),
                "completed": bool(status_type.get("completed")),
                "period": period,
                "display_clock": display_clock,
                "status_detail": str(
                    status_type.get("shortDetail") or status_type.get("detail") or status_type.get("description") or ""
                ).strip(),
                "start_time_utc": event.get("date"),
            }
        )
    return rows


_FETCHERS = {
    "mlb": _fetch_mlb_schedule,
    "nba": lambda date_str: _fetch_basketball_schedule("nba", date_str),
    "wnba": lambda date_str: _fetch_basketball_schedule("wnba", date_str),
    "nhl": _fetch_nhl_schedule,
    "soccer": _fetch_soccer_schedule,
    "nfl": lambda date_str: _fetch_espn_football_schedule("nfl", date_str),
    "ncaaf": lambda date_str: _fetch_espn_football_schedule("ncaaf", date_str),
}


def fetch_schedule_for_date(sport: str, date_str: str, *, force_refresh: bool = False) -> list[ScheduleEvent]:
    normalized_sport = str(sport or "").strip().lower()
    fetcher = _FETCHERS.get(normalized_sport)
    if fetcher is None:
        return []

    # Every sport goes through the same TTL cache, no exceptions. NBA/WNBA's
    # fetcher falls back to a subprocess CLI network call whenever the local
    # schedule file has no rows for the date -- without this cache, a caller
    # invoked every tick (e.g. the tip-off force-window check in
    # live_refresh_loop.py, which runs on every loop iteration regardless of
    # the surrounding interval throttle) would spawn that subprocess call
    # every single tick forever. Confirmed cause of a production OOM.
    cached = None if force_refresh else _read_cache(normalized_sport, date_str)
    if cached is not None:
        raw_rows = cached
    else:
        raw_rows = fetcher(date_str)
        _write_cache(normalized_sport, date_str, raw_rows)

    events: list[ScheduleEvent] = []
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        event = _event_from_row(normalized_sport, row)
        if event is not None:
            events.append(event)
    return events


_GAME_WINDOW_CACHE: dict[tuple[str, str, int], tuple[float, bool]] = {}
_GAME_WINDOW_TTL_SECONDS = 900.0


def sport_has_games_within(
    sport: str,
    date_str: str,
    *,
    horizon_days: int = 1,
    unknown_means_yes: bool = True,
) -> bool:
    """Does *sport* have any scheduled game from `date_str` through +horizon_days?

    THE OWNERSHIP PREDICATE. NFL/NCAAF/NCAAB are "weekly sports": excluded from
    the fast odds tick and handed to refresh-worker's 6-hourly weekly autorun.
    That split exists to prevent a real write race -- both would otherwise target
    the same non-date-partitioned football artifacts -- but it also meant NFL's
    board went 24 hours between captures while MLB got one every ~26 minutes.

    Both services call THIS function to decide ownership, so they partition on
    one deterministic answer rather than coordinating through shared state:

        games in the horizon  -> the fast tick owns it (prices move; capture often)
        no games              -> the weekly autorun owns it (schedule/artifact work)

    If the two ever disagreed the write race would come back, so neither side may
    grow its own copy of this rule.

    `unknown_means_yes` is the load-bearing default. `fetch_schedule_for_date`
    returns [] for a swallowed timeout exactly as it does for "no games", so a
    gate that treated empty as authoritative would silently hand NFL back to the
    6-hourly path every time ESPN was slow -- the failure would look like normal
    operation. On an unresolvable schedule we over-capture instead, which costs
    OddsAPI credits rather than a dark board.
    """
    normalized_sport = str(sport or "").strip().lower()
    try:
        start = datetime.strptime(str(date_str).strip(), "%Y-%m-%d").date()
    except ValueError:
        return bool(unknown_means_yes)
    span = max(0, int(horizon_days))

    cache_key = (normalized_sport, start.isoformat(), span)
    now = datetime.now(timezone.utc).timestamp()
    cached = _GAME_WINDOW_CACHE.get(cache_key)
    if cached is not None and (now - cached[0]) < _GAME_WINDOW_TTL_SECONDS:
        return cached[1]

    fetcher = _FETCHERS.get(normalized_sport)
    if fetcher is None:
        return bool(unknown_means_yes)

    resolved: bool | None = None
    any_failed = False
    for offset in range(span + 1):
        day = (start + timedelta(days=offset)).isoformat()
        try:
            # strict, so a transport failure is distinguishable from an empty
            # slate. Football goes through the ESPN fetcher directly to get it;
            # anything else falls back to the cached path and is treated as
            # unknown-on-empty only when every day came back empty.
            if normalized_sport in _ESPN_FOOTBALL_LEAGUE:
                rows = _fetch_espn_football_schedule(normalized_sport, day, strict=True)
            else:
                rows = fetcher(day)
        except Exception:
            any_failed = True
            continue
        if rows:
            resolved = True
            break

    if resolved is None:
        # Every day answered, none had games -> a real, trustworthy "no".
        # Any day failed and none of the rest had games -> we do not know.
        resolved = bool(unknown_means_yes) if any_failed else False

    _GAME_WINDOW_CACHE[cache_key] = (now, resolved)
    return resolved


def events_starting_within(events: list[ScheduleEvent], *, now_epoch: float, window_minutes: int) -> list[ScheduleEvent]:
    window_seconds = max(0, int(window_minutes)) * 60
    out: list[ScheduleEvent] = []
    for event in events:
        start_epoch = event.start_time_epoch()
        if start_epoch is None:
            continue
        delta = start_epoch - float(now_epoch)
        if -window_seconds <= delta <= window_seconds:
            out.append(event)
    return out
