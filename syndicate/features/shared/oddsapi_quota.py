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


# Deliberately O(1): the stored payload holds a baseline observation, the
# latest one, and small per-sport counters -- never a list of observations.
#
# It DID keep the last 500 observations. That made this telemetry key by far
# the largest entry in a Redis instance that also holds load-bearing state
# (sim run pointers, refresh manifests, board state), and on 2026-07-25 it
# went from 20 observations to absent across a deploy -- key gone, not stale.
# Eviction under a memory policy is the leading explanation, and even if it
# was not the cause, a diagnostic key has no business being the biggest thing
# in a store that critical operations read. Burn only ever needed two
# observations and a clock, so the list bought nothing.
#
# A smaller key also recovers faster: re-establishing a burn rate after a
# loss now takes two observations instead of five hundred.
_MAX_WINDOW_SECONDS = 7 * 24 * 3600


def _quota_path():
    return reports_root() / "odds_control_plane" / "oddsapi_quota.json"


def _utc_now_iso() -> str:
    # Milliseconds, not seconds: fetchers fire several calls inside one
    # second, and at second resolution those collapse to an identical
    # timestamp, making the elapsed window zero and the rate uncomputable.
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


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

        baseline = payload.get("baseline") if isinstance(payload.get("baseline"), dict) else None
        baseline = _next_baseline(baseline, observation)

        by_sport = payload.get("by_sport") if isinstance(payload.get("by_sport"), dict) else {}
        sport_key = observation.get("sport") or "unknown"
        bucket = by_sport.get(sport_key) if isinstance(by_sport.get(sport_key), dict) else {"calls": 0, "credits": 0}
        bucket["calls"] = int(bucket.get("calls") or 0) + 1
        bucket["credits"] = int(bucket.get("credits") or 0) + int(observation.get("last_cost") or 0)
        by_sport[sport_key] = bucket

        write_json_file(
            _quota_path(),
            {
                "baseline": baseline,
                "latest": observation,
                "by_sport": by_sport,
                "observation_count": int(payload.get("observation_count") or 0) + 1,
                "updatedAt": _utc_now_iso(),
            },
        )
        return observation
    except Exception:
        return None


def _next_baseline(baseline: dict[str, Any] | None, observation: dict[str, Any]) -> dict[str, Any]:
    """Which observation to measure burn FROM.

    Rolls forward in two cases, both of which would otherwise produce a
    nonsense burn rate:

    - `used` went DOWN. That is a billing-period rollover (or a key swap), so
      the delta against the old baseline would be negative.
    - the window got older than _MAX_WINDOW_SECONDS, so a long-dead baseline
      cannot keep flattening a rate that should track recent behaviour.
    """
    if not isinstance(baseline, dict) or baseline.get("used") is None:
        return observation
    try:
        if int(observation.get("used") or 0) < int(baseline.get("used") or 0):
            return observation
    except (TypeError, ValueError):
        return observation
    started = _parse_iso(baseline.get("observedAt"))
    ended = _parse_iso(observation.get("observedAt"))
    if started and ended and (ended - started).total_seconds() > _MAX_WINDOW_SECONDS:
        return observation
    return baseline


def read_oddsapi_quota() -> dict[str, Any]:
    """Latest quota state plus burn derived from the baseline.

    Burn is (latest used - baseline used) over the elapsed time between them.
    Both are absolute server-side counters, so this needs exactly two stored
    observations, never a history.

    With no baseline yet, or with the baseline and latest being the same
    observation, the derived fields come back None rather than 0 -- "not
    measured yet" and "not burning" must not look identical, since that
    confusion is the whole reason this module exists.

    Tolerates the pre-#54 schema (a list under "observations") so a partially
    rolled-out deploy reports a slightly stale window instead of nothing.
    """
    payload = read_json_file(_quota_path())
    if not isinstance(payload, dict):
        payload = {}

    baseline = payload.get("baseline") if isinstance(payload.get("baseline"), dict) else None
    latest = payload.get("latest") if isinstance(payload.get("latest"), dict) else None
    by_sport = payload.get("by_sport") if isinstance(payload.get("by_sport"), dict) else {}
    observation_count = payload.get("observation_count")

    legacy = payload.get("observations")
    if baseline is None and isinstance(legacy, list):
        dated = [item for item in legacy if isinstance(item, dict) and item.get("used") is not None]
        if dated:
            baseline = dated[0]
            latest = latest or dated[-1]
        if observation_count is None:
            observation_count = len(legacy)
        if not by_sport:
            for item in legacy:
                if not isinstance(item, dict):
                    continue
                bucket = by_sport.setdefault(str(item.get("sport") or "unknown"), {"calls": 0, "credits": 0})
                bucket["calls"] += 1
                bucket["credits"] += int(item.get("last_cost") or 0)

    result: dict[str, Any] = {
        "latest": latest,
        "baseline": baseline,
        "observation_count": int(observation_count or 0),
        "credits_burned_in_window": None,
        "window_seconds": None,
        "credits_per_hour": None,
        "projected_30d_credits": None,
        "by_sport": dict(by_sport),
    }

    if not isinstance(baseline, dict) or not isinstance(latest, dict):
        return result
    if baseline.get("used") is None or latest.get("used") is None:
        return result

    # Gate on the COUNT, not on the delta. With a single observation the
    # baseline IS the latest, so the delta is a legitimate-looking 0 -- and
    # reporting 0 would say "not burning" when the truth is "not measured
    # yet". Keeping those distinguishable is the whole point of this module.
    if int(result["observation_count"] or 0) < 2:
        return result

    # How much was burned is known as soon as there are two observations.
    # The RATE needs elapsed time as well, and those are different questions:
    # reporting neither when only the clock is unusable would throw away a
    # fact we actually have.
    result["credits_burned_in_window"] = int(latest["used"]) - int(baseline["used"])

    started = _parse_iso(baseline.get("observedAt"))
    ended = _parse_iso(latest.get("observedAt"))
    if started is None or ended is None:
        return result
    elapsed = (ended - started).total_seconds()
    result["window_seconds"] = int(elapsed)
    if elapsed <= 0:
        # Baseline and latest are the same observation, or arrived inside one
        # clock tick -- a rate off that would be meaningless or infinite.
        return result
    per_hour = result["credits_burned_in_window"] / elapsed * 3600.0
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
