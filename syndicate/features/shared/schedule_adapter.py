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
from dataclasses import dataclass
from datetime import datetime, timezone
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
    return ScheduleEvent(
        sport=sport,
        event_id=event_id,
        home=home,
        away=away,
        start_time_utc=str(start_time_utc).strip() if start_time_utc else None,
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


_FETCHERS = {
    "mlb": _fetch_mlb_schedule,
    "nba": lambda date_str: _fetch_basketball_schedule("nba", date_str),
    "wnba": lambda date_str: _fetch_basketball_schedule("wnba", date_str),
    "nhl": _fetch_nhl_schedule,
}


def fetch_schedule_for_date(sport: str, date_str: str, *, force_refresh: bool = False) -> list[ScheduleEvent]:
    normalized_sport = str(sport or "").strip().lower()
    fetcher = _FETCHERS.get(normalized_sport)
    if fetcher is None:
        return []

    # NBA/WNBA read a local file on every call (cheap; no second-order cache
    # needed) and only hit the network when nothing's on disk yet -- the TTL
    # cache below is for MLB/NHL, which always make a live API call.
    if normalized_sport in ("nba", "wnba") and not force_refresh:
        raw_rows = fetcher(date_str)
    else:
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
