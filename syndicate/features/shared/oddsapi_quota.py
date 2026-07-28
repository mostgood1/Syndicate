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


# #15 attribution (2026-07-27). The first full-day burn reading measured
# 371,563 credits/day -- 11.1M/30d projected against a 5M target -- with MLB
# at 96.3%. But "MLB burned 358k" is one number; every cut decision on the
# table (#16's drop-alternates and drop-first7, cadence tiering, event
# scoping) needs to know WHICH MARKETS the credits went to. The fetchers
# already pass endpoint=url into record_oddsapi_quota; these buckets finally
# aggregate what was already flowing past.
#
# Families are DECISION-MAPPED, not taxonomy for its own sake: each one is a
# lever someone can actually pull.
#   first7     -> #16 cut (b): any *_1st_7_innings market
#   alternate  -> #16 cut (a): alternate_* (excluding first7, mirroring the
#                 audit's disjoint counts of 8 alternates / 6 first7)
#   segment    -> other *_1st_* period/inning markets (cadence-tier candidate)
#   props      -> batter_/pitcher_/player_ (event-scoping candidate)
#   full_game  -> h2h/spreads/totals and their 3-way forms (the board's core;
#                 not a cut candidate)
#   event_list -> requests with no markets= param (usually cost 0)
#   historical -> anything under /historical/ (#21: 10x-billed, should never
#                 appear in production at all -- a non-zero bucket here IS the
#                 #21 alarm)
#
# A single request carries several markets (cost = markets x regions), so a
# request's cost is split across families proportionally to market count --
# exact, because OddsAPI bills per market uniformly within a request.
_FULL_GAME_MARKETS = {"h2h", "spreads", "totals", "h2h_3_way", "outrights", "spreads_3_way", "totals_3_way"}


def _market_family(market: str) -> str:
    market = str(market or "").strip().lower()
    if not market:
        return "other"
    if "_1st_7_innings" in market:
        return "first7"
    if market.startswith("alternate_"):
        return "alternate"
    if "_1st_" in market:
        return "segment"
    if market.startswith(("batter_", "pitcher_", "player_")):
        return "props"
    if market in _FULL_GAME_MARKETS:
        return "full_game"
    return "other"


def _attribute_request_families(endpoint: str, last_cost: int) -> dict[str, float]:
    """{family: credits} for one request, splitting cost across families."""
    endpoint = str(endpoint or "")
    if "/historical/" in endpoint:
        return {"historical": float(last_cost)}
    try:
        from urllib.parse import parse_qs, urlsplit

        query = parse_qs(urlsplit(endpoint).query)
        markets = [m for chunk in query.get("markets", []) for m in chunk.split(",") if m.strip()]
    except Exception:
        markets = []
    if not markets:
        return {"event_list": float(last_cost)}
    per_market = float(last_cost) / len(markets)
    out: dict[str, float] = {}
    for market in markets:
        family = _market_family(market)
        out[family] = out.get(family, 0.0) + per_market
    return out


def _sanitize_endpoint(endpoint: str) -> str:
    """Strip credentials from a request URL, keeping the rest of the query.

    The recorded endpoint is persisted to the shared state store, so it must
    never carry apiKey -- which is why several fetchers used to record only
    the path. But attribution needs the QUERY (markets= is what
    _attribute_request_families reads), and a path-only endpoint files every
    cost-carrying call under event_list: the first attributed day read 100%
    event_list precisely because callers were stripping (or never had) the
    query. Central redaction lets callers pass the real requested URL.

    On any parse failure the whole query is dropped -- losing attribution for
    one observation is acceptable; persisting a key never is.
    """
    endpoint = str(endpoint or "").strip()
    if "?" not in endpoint:
        return endpoint
    try:
        from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

        parts = urlsplit(endpoint)
        query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key.lower() not in {"apikey", "api_key"}]
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    except Exception:
        return endpoint.split("?", 1)[0]


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
            "endpoint": _sanitize_endpoint(endpoint) or None,
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

        # #15 attribution. Both aggregates stay O(1) like by_sport (#54's
        # hard-won constraint): families are a fixed vocabulary of ~7 and
        # hours are 24, so this key cannot grow back into the biggest thing
        # in the store no matter how long it runs.
        last_cost = int(observation.get("last_cost") or 0)
        by_family = payload.get("by_market_family") if isinstance(payload.get("by_market_family"), dict) else {}
        by_hour = payload.get("by_hour_utc") if isinstance(payload.get("by_hour_utc"), dict) else {}
        attribution_error_count = int(payload.get("attribution_error_count") or 0)
        last_attribution_error = payload.get("last_attribution_error")
        try:
            for family, credits in _attribute_request_families(observation.get("endpoint") or "", last_cost).items():
                family_bucket = by_family.get(family) if isinstance(by_family.get(family), dict) else {"calls": 0, "credits": 0.0}
                family_bucket["calls"] = int(family_bucket.get("calls") or 0) + 1
                family_bucket["credits"] = round(float(family_bucket.get("credits") or 0.0) + credits, 2)
                by_family[family] = family_bucket

            # Hour-of-day histogram (UTC), for the off-hours question: how
            # much of the burn happens when nothing is live? 24 fixed buckets.
            hour_key = str(observation.get("observedAt") or "")[11:13] or "??"
            hour_bucket = by_hour.get(hour_key) if isinstance(by_hour.get(hour_key), dict) else {"calls": 0, "credits": 0}
            hour_bucket["calls"] = int(hour_bucket.get("calls") or 0) + 1
            hour_bucket["credits"] = int(hour_bucket.get("credits") or 0) + last_cost
            by_hour[hour_key] = hour_bucket
        except Exception as exc:
            # Attribution is a bonus on top of the load-bearing burn counter.
            # If it breaks, the observation must still be recorded --
            # un-attributed beats un-recorded, and the outer never-raises
            # handler would otherwise throw away the whole reading. But a
            # bare `except: pass` here previously made that failure
            # completely invisible: by_market_family/by_hour_utc measured
            # ~54% of by_sport's total for the entire tracked window with
            # zero signal as to why (confirmed 2026-07-28, both stuck at the
            # identical reduced figure, proving they fail together in this
            # one block). Recording the exception (bounded: one message, one
            # counter, not one entry per failure) turns the next occurrence
            # into a one-read diagnosis instead of another blind
            # investigation.
            attribution_error_count += 1
            last_attribution_error = {
                "error": f"{type(exc).__name__}: {exc}",
                "endpoint": observation.get("endpoint"),
                "sport": observation.get("sport"),
                "observedAt": observation.get("observedAt"),
            }

        # Concurrent-write race probe. #106/#107 flagged that by_sport (~96%
        # complete vs the ground-truth burn counter) and
        # by_market_family/by_hour_utc (~54%, identical to each other since
        # they update in the same block above) are written together, in one
        # function call, to one shared key -- yet diverge in completeness.
        # That contradicts a plain lost-update race (which should lose all
        # three equally per collision) if this write and the collision are
        # simultaneous, so: re-read the store immediately before writing and
        # compare observation_count against what this call read at the top.
        # A mismatch proves another writer completed in between -- this call
        # is about to overwrite it with a payload computed from the stale
        # read, the exact mechanism under suspicion. Read-only probe: it
        # does not change what gets written, only records how often this
        # happens so the rate is measurable instead of inferred.
        observation_count_at_read = int(payload.get("observation_count") or 0)
        race_detected_count = int(payload.get("race_detected_count") or 0)
        last_race_detail = payload.get("last_race_detail")
        try:
            fresh_payload = read_json_file(_quota_path())
            fresh_count = int((fresh_payload or {}).get("observation_count") or 0) if isinstance(fresh_payload, dict) else observation_count_at_read
            if fresh_count != observation_count_at_read:
                race_detected_count += 1
                last_race_detail = {
                    "observation_count_at_read": observation_count_at_read,
                    "observation_count_at_write": fresh_count,
                    "sport": observation.get("sport"),
                    "observedAt": observation.get("observedAt"),
                }
        except Exception:
            pass

        write_json_file(
            _quota_path(),
            {
                "baseline": baseline,
                "latest": observation,
                "by_sport": by_sport,
                "by_market_family": by_family,
                "by_hour_utc": by_hour,
                "attribution_error_count": attribution_error_count,
                "last_attribution_error": last_attribution_error,
                "race_detected_count": race_detected_count,
                "last_race_detail": last_race_detail,
                # Stamped once, because none of the aggregates above ever
                # reset -- a rate is only computable as total/(now - this).
                "aggregates_started_at": str(payload.get("aggregates_started_at") or _utc_now_iso()),
                "observation_count": observation_count_at_read + 1,
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
    by_family = payload.get("by_market_family") if isinstance(payload.get("by_market_family"), dict) else {}
    by_hour = payload.get("by_hour_utc") if isinstance(payload.get("by_hour_utc"), dict) else {}
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
        # The attribution aggregates never reset, so a rate over them is only
        # computable against aggregates_started_at, not the burn baseline --
        # the baseline rolls forward (rollover, 7-day cap) while these do not.
        "by_market_family": dict(by_family),
        "by_hour_utc": dict(by_hour),
        "aggregates_started_at": payload.get("aggregates_started_at"),
        "attribution_error_count": int(payload.get("attribution_error_count") or 0),
        "last_attribution_error": payload.get("last_attribution_error"),
        "race_detected_count": int(payload.get("race_detected_count") or 0),
        "last_race_detail": payload.get("last_race_detail"),
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
