"""A faithful Syndicate copy of the slice of the vendored MLB StatsAPI client that the live loop's MLB helper scripts use.

Lane mlb-schedule-fetch-native (2026-10-15, user request). `scripts/fetch_mlb_schedule_for_date.py` imported
`StatsApiClient` and `fetch_schedule_for_date` from vendor/mlb_bettingv2/sim_engine/data/statsapi.py, putting that tree
on sys.path. It used a bare `StatsApiClient()` -- no disk cache -- so this module copies exactly that behaviour:

  * GET `https://statsapi.mlb.com/api/v1<path>` through a `requests.Session` that ignores HTTP(S)_PROXY unless
    STATSAPI_TRUST_ENV is truthy;
  * an (8 s, 8 s) connect/read timeout;
  * up to 2 retries with jittered exponential backoff (0.6 s base) on timeouts, connection errors and 5xx -- nothing
    else is retried;
  * the thin `/schedule` and `/teams/{id}/roster` wrappers, returning the raw lists.

Nothing here caches, logs or imports anything vendored.
"""
from __future__ import annotations

import os
import random
import time
from typing import Any

STATSAPI_BASE_URL = "https://statsapi.mlb.com/api/v1"
TIMEOUT_SEC = 8.0
MAX_RETRIES = 2
RETRY_BACKOFF_SEC = 0.6


def _trust_env() -> bool:
    env = os.environ.get("STATSAPI_TRUST_ENV")
    if env is None:
        return False
    return str(env).strip().lower() in ("1", "true", "yes", "y", "on")


def statsapi_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    import requests

    url = path if str(path).lower().startswith("http") else f"{STATSAPI_BASE_URL}{path}"
    session = requests.Session()
    session.trust_env = _trust_env()
    attempts = 1 + MAX_RETRIES
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            response = session.get(url, params=params or {}, timeout=(TIMEOUT_SEC, TIMEOUT_SEC))
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            status = getattr(getattr(exc, "response", None), "status_code", None)
            retryable_status = isinstance(status, int) and 500 <= int(status) < 600
            retryable = isinstance(exc, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)) or retryable_status
            if (attempt + 1) >= attempts or not retryable:
                break
            time.sleep(RETRY_BACKOFF_SEC * (2.0**attempt) * (1.0 + 0.25 * random.random()))
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("StatsAPI GET failed without exception")


def fetch_schedule_for_date(date_str: str) -> list[dict[str, Any]]:
    data = statsapi_get("/schedule", {"sportId": 1, "date": date_str, "hydrate": "probablePitcher,team"})
    return [game for day in data.get("dates", []) or [] for game in day.get("games", []) or []]


def fetch_team_roster(team_id: int, roster_type: str = "active", date_str: str | None = None) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"rosterType": str(roster_type)}
    if date_str:
        params["date"] = str(date_str)
    return statsapi_get(f"/teams/{int(team_id)}/roster", params).get("roster", []) or []
