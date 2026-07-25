"""Ground truth for OddsAPI credit burn.

Every OddsAPI response carries the account's quota state:

    x-requests-remaining   credits left in the billing period
    x-requests-used        credits consumed in the billing period
    x-requests-last        what THIS call cost

Until now only vendor code read those headers, so Syndicate had no
measurement of its own burn rate -- every cadence decision was an estimate
(e.g. "MLB alone is ~585 credits/sweep at 60s ticks, so ~6.3M/month against
a 5M budget"). That number may well be right, but it has never been checked
against the counter the vendor actually bills from. This module exists so
the next cadence change is made against a measurement.

Design note -- why observations, not accumulation:

`used` and `remaining` are ABSOLUTE, server-side, monotonic counters. So we
never add anything up locally. We record what the API reported and when, and
derive burn as the delta between two observations. That matters because
three services (web, refresh-worker, live-odds-worker) and their detached
subprocesses all call OddsAPI concurrently through a shared, non-atomic
state store: a local accumulator would lose increments to last-write-wins
races, while a lost *observation* costs nothing -- the next one still
carries the true absolute total. Recording is therefore safe from anywhere,
with no lock.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from syndicate.features.shared.refresh_state_store import read_json_file
from syndicate.features.shared.refresh_state_store import reports_root
from syndicate.features.shared.refresh_state_store import write_json_file


# Bounded so the shared store entry stays small; the derived burn only needs
# the oldest and newest observation in the window, not every call.
_MAX_OBSERVATIONS = 500


def _quota_path():
    return reports_root() / "odds_control_plane" / "oddsapi_quota.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _coerce_int(value: Any) -> int | None:
    text = str(value if value is not None else "").strip()
    if not text:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def parse_quota_headers(headers: Any) -> dict[str, int] | None:
    """Pull the three quota values out of a response's headers.

    Returns None when the headers carry no quota information at all, so a
    caller can tell "not an OddsAPI response / quota not reported" apart
    from "reported zero remaining", which is a real and alarming state.
    """
    if not headers:
        return None
    try:
        lowered = {str(key).lower(): value for key, value in dict(headers).items()}
    except Exception:
        return None
    parsed = {
        "remaining": _coerce_int(lowered.get("x-requests-remaining")),
        "used": _coerce_int(lowered.get("x-requests-used")),
        "last_cost": _coerce_int(lowered.get("x-requests-last")),
    }
    if all(value is None for value in parsed.values()):
        return None
    return {key: value for key, value in parsed.items() if value is not None}


def record_oddsapi_quota(headers: Any, *, sport: str | None = None, endpoint: str | None = None) -> dict[str, Any] | None:
    """Record one quota observation. Never raises.

    Called from fetchers' HTTP seams, including inside detached subprocesses,
    so a failure here must never be able to fail a refresh -- instrumentation
    that can break the thing it measures is worse than no instrumentation.
    """
    try:
        parsed = parse_quota_headers(headers)
        if parsed is None:
            return None
        observation = {
            **parsed,
            "sport": str(sport or "").strip().lower() or None,
            "endpoint": str(endpoint or "").strip() or None,
            "observedAt": _utc_now_iso(),
        }
        payload = read_json_file(_quota_path())
        if not isinstance(payload, dict):
            payload = {}
        observations = payload.get("observations")
        if not isinstance(observations, list):
            observations = []
        observations.append(observation)
        if len(observations) > _MAX_OBSERVATIONS:
            observations = observations[-_MAX_OBSERVATIONS:]
        write_json_file(
            _quota_path(),
            {"latest": observation, "observations": observations, "updatedAt": _utc_now_iso()},
        )
        return observation
    except Exception:
        return None


def read_oddsapi_quota() -> dict[str, Any]:
    """Latest quota state plus burn derived from the observation window.

    Burn is (newest used - oldest used) over the window's elapsed time. With
    no second observation there is nothing to derive, and the fields come
    back None rather than 0 -- "not measured yet" and "not burning" must not
    look identical, since that confusion is the whole reason this module
    exists.
    """
    payload = read_json_file(_quota_path())
    if not isinstance(payload, dict):
        payload = {}
    observations = payload.get("observations")
    if not isinstance(observations, list):
        observations = []
    dated = [item for item in observations if isinstance(item, dict) and item.get("used") is not None]

    result: dict[str, Any] = {
        "latest": payload.get("latest"),
        "observation_count": len(observations),
        "credits_burned_in_window": None,
        "window_seconds": None,
        "credits_per_hour": None,
        "projected_30d_credits": None,
        "by_sport": {},
    }
    for item in observations:
        if not isinstance(item, dict):
            continue
        sport = str(item.get("sport") or "unknown")
        bucket = result["by_sport"].setdefault(sport, {"calls": 0, "credits": 0})
        bucket["calls"] += 1
        bucket["credits"] += int(item.get("last_cost") or 0)

    if len(dated) >= 2:
        oldest, newest = dated[0], dated[-1]
        burned = int(newest["used"]) - int(oldest["used"])
        started = _parse_iso(oldest.get("observedAt"))
        ended = _parse_iso(newest.get("observedAt"))
        result["credits_burned_in_window"] = burned
        if started and ended:
            elapsed = (ended - started).total_seconds()
            result["window_seconds"] = int(elapsed)
            if elapsed > 0:
                per_hour = burned / elapsed * 3600.0
                result["credits_per_hour"] = round(per_hour, 1)
                result["projected_30d_credits"] = int(per_hour * 24 * 30)
    return result


def _parse_iso(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
