"""A soccer refresh background loop, mirroring the shared
``live_refresh_loop.py``'s dark-launch posture (default off, gated behind
one env var) but deliberately much simpler: soccer has none of the
OOM/memory-headroom history that motivated that file's elaborate
mutex/fingerprint machinery, and adding that complexity preemptively for a
sport that hasn't shipped yet would be over-engineering, not safety.

Every tick, for each league: makes sure the current default week's
recommendations are populated (``build_soccer_artifacts.py``, cheap no-op
if already there since it just overwrites with the same simulation), and
polls live state (``poll_soccer_live_state.py``) if ESPN reports any match
currently in progress. Both run as short-lived subprocesses, matching how
the rest of this app launches its own background jobs (e.g.
``_launch_mlb_daily_sim`` in live_refresh_loop.py) rather than running
inside the web process's own thread.
"""

from __future__ import annotations

import atexit
import os
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from syndicate.features.shared.refresh_state_store import reports_root
from syndicate.features.shared.refresh_state_store import read_json_file
from syndicate.features.shared.refresh_state_store import write_json_file
from syndicate.features.shared.source_roots import repo_root_from
from syndicate.features.soccer.ingestion.espn_lineups import LEAGUE_ESPN_SLUGS
from syndicate.features.soccer.ingestion.espn_lineups import fetch_events
from syndicate.features.soccer.sources import default_season
from syndicate.features.soccer.sources import default_week
from syndicate.features.soccer.sources import week_date_list

REPO_ROOT = repo_root_from(__file__)
_LOOP_THREAD: threading.Thread | None = None
_LOOP_LOCK = threading.Lock()
_LOOP_STOP = threading.Event()


def _env_bool(name: str, *, default: bool = False) -> bool:
    raw = str(os.environ.get(name) or "").strip().lower()
    if not raw:
        return bool(default)
    return raw in {"1", "true", "yes", "on"}


def _enabled() -> bool:
    return _env_bool("SYNDICATE_ENABLE_SOCCER_REFRESH_LOOP", default=False)


def _interval_seconds() -> int:
    raw = str(os.environ.get("SYNDICATE_SOCCER_REFRESH_INTERVAL_SECONDS") or "").strip()
    try:
        value = int(raw or 3600)
    except Exception:
        value = 3600
    return max(300, value)


def _live_poll_interval_seconds() -> int:
    raw = str(os.environ.get("SYNDICATE_SOCCER_LIVE_POLL_INTERVAL_SECONDS") or "").strip()
    try:
        value = int(raw or 90)
    except Exception:
        value = 90
    return max(30, value)


def _python_exe() -> str:
    return sys.executable if (sys.executable and Path(sys.executable).exists()) else "python"


def _meta_dir() -> Path:
    path = reports_root() / "soccer_refresh_loop"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _status_path() -> Path:
    return _meta_dir() / "status.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _run_script(args: list[str], *, timeout_s: float = 600.0) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            [_python_exe(), *args],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        return result.returncode == 0, (result.stdout or "") + (result.stderr or "")
    except Exception as error:
        return False, f"{type(error).__name__}: {error}"


def _any_live_matches(league: str) -> bool:
    try:
        from datetime import date

        today = date.today().strftime("%Y%m%d")
        events = fetch_events(league, date_windows=[f"{today}-{today}"], statuses={"in"})
        return bool(events)
    except Exception:
        return False


def _refresh_league(league: str) -> dict[str, Any]:
    result: dict[str, Any] = {"league": league}
    try:
        season = default_season(league)
        week = default_week(league, season)
        dates = week_date_list(league, season, week)
    except Exception as error:
        result["error"] = f"week resolution failed: {error}"
        return result
    result["season"] = season
    result["week"] = week
    result["dates_refreshed"] = []
    for date_str in dates:
        ok, output = _run_script(
            [str(REPO_ROOT / "scripts" / "build_soccer_artifacts.py"), "--league", league, "--date", date_str]
        )
        result["dates_refreshed"].append({"date": date_str, "ok": ok})
        if not ok:
            result.setdefault("errors", []).append({"date": date_str, "output": output[-2000:]})
    if _any_live_matches(league):
        ok, output = _run_script([str(REPO_ROOT / "scripts" / "poll_soccer_live_state.py"), "--league", league])
        result["live_poll"] = {"ok": ok}
        if not ok:
            result.setdefault("errors", []).append({"live_poll": output[-2000:]})
    return result


def _tick() -> dict[str, Any]:
    leagues_result = [_refresh_league(league) for league in LEAGUE_ESPN_SLUGS]
    status = {"tickAt": _utc_now(), "leagues": leagues_result}
    write_json_file(_status_path(), status)
    return status


def _background_loop() -> None:
    try:
        while not _LOOP_STOP.is_set():
            try:
                _tick()
            except Exception:
                pass
            _LOOP_STOP.wait(_interval_seconds())
    finally:
        pass


def start_soccer_refresh_background_loop() -> bool:
    global _LOOP_THREAD
    if not _enabled():
        return False
    with _LOOP_LOCK:
        if _LOOP_THREAD is not None and _LOOP_THREAD.is_alive():
            return False
        _LOOP_STOP.clear()
        _LOOP_THREAD = threading.Thread(
            target=_background_loop,
            name="syndicate-soccer-refresh-loop",
            daemon=True,
        )
        _LOOP_THREAD.start()
        return True


def stop_soccer_refresh_background_loop() -> None:
    _LOOP_STOP.set()


def soccer_refresh_loop_status_payload() -> dict[str, Any]:
    status = read_json_file(_status_path())
    return {
        "enabled": _enabled(),
        "intervalSeconds": _interval_seconds(),
        "threadAlive": bool(_LOOP_THREAD is not None and _LOOP_THREAD.is_alive()),
        "latestTick": status if isinstance(status, dict) else {},
    }


atexit.register(stop_soccer_refresh_background_loop)
