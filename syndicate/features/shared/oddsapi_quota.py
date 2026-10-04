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

import time
from datetime import datetime, timezone
from typing import Any

from syndicate.features.shared.refresh_state_store import WriteConflict
from syndicate.features.shared.refresh_state_store import compare_and_swap_json_file
from syndicate.features.shared.refresh_state_store import read_json_file
from syndicate.features.shared.refresh_state_store import read_json_file_result
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
    # `_1st_*` is MLB's spelling and it was the ONLY spelling this recognised.
    # Football and hockey segments are suffixed `_q1..._q4`, `_h1`/`_h2`,
    # `_p1..._p3` (`market_segments._SUFFIX`), so every one of them fell past
    # this test, past `_FULL_GAME_MARKETS` -- which holds bare `h2h`/`totals`
    # and not `totals_h1` -- and landed in `other`. The `segment` family is 35%
    # of all platform burn; a football segment tier billed into `other` would
    # make the one bucket the cadence decisions are read from silently wrong.
    if market.endswith(("_q1", "_q2", "_q3", "_q4", "_h1", "_h2", "_p1", "_p2", "_p3")):
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

    WRITTEN BY COMPARE-AND-SWAP `[2026-10-02, lane layer2-freshness-1h]`. This
    was read -> add -> blind write, and with many writers (the hourly
    seven-sport look-ahead, the live sweep, the NCAAF lines autorun every
    150s, NHL's threaded client) the last write won and every other writer's
    increment vanished. Measured on the fleet 16:15-17:30Z: +2,382 credits on
    the account's own `used` counter against +643 attributed to sports -- 73%
    of the window's spend lost from `by_sport`, including two minutes in which
    +666 credits moved no sport at all. `used` itself was always right (it is
    the server's absolute counter); only the per-sport/hour/family sums lost
    increments. Now each attempt re-reads the document inside the swap
    (`refresh_state_store.compare_and_swap_json_file`: WATCH/MULTI on keyvalue),
    so a concurrent writer causes a retry, never a lost increment.
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
        last_cost = int(observation.get("last_cost") or 0)
        sport_key = observation.get("sport") or "unknown"
        # Computed once, outside the swap: it depends only on this call.
        family_error = None
        try:
            families = _attribute_request_families(observation.get("endpoint") or "", last_cost)
        except Exception as exc:
            families = {}
            family_error = {
                "error": f"{type(exc).__name__}: {exc}",
                "endpoint": observation.get("endpoint"),
                "sport": observation.get("sport"),
                "observedAt": observation.get("observedAt"),
            }
        hour_key = str(observation.get("observedAt") or "")[11:13] or "??"

        def _build(attempt: int) -> dict[str, Any]:
            # A FAILED READ MUST NEVER BECOME AN EMPTY DOCUMENT. `read_json_file`
            # returns None both for "no document yet" and for "the read failed"
            # (a store hiccup, or a file read mid-replace), and building from {}
            # on the second would commit a fresh document and ZERO every
            # counter -- which the pre-CAS code did as well. Retry the read
            # briefly; if it still cannot be trusted, abort this attempt and
            # drop only this one observation.
            payload, ok = read_json_file_result(_quota_path())
            for _ in range(4):
                if ok:
                    break
                time.sleep(0.01)
                payload, ok = read_json_file_result(_quota_path())
            if not ok:
                raise _UntrustedRead()
            if not isinstance(payload, dict):
                # AND AN ABSENT DOCUMENT MUST NEVER BE *CREATED* FROM OFF-FLEET.
                # The guard above distinguishes "read failed" from "no document
                # yet", but there is a THIRD state it cannot see: absent in THIS
                # process's `reports_root()` while the real ledger lives
                # somewhere else. `read_json_file_result` returns (None, ok=True)
                # for both, so an off-fleet run built from {} and committed a
                # fresh document -- which ZEROES every other sport's counters in
                # whatever file its path happens to resolve to.
                #
                # MEASURED 2026-10-03: a backfill run from a git worktree whose
                # sparse checkout excludes `reports/` wrote
                # `by_sport={"nfl": {...}}` over a tracked document holding
                # `nfl` AND `ncaaf`, and `by_market_family={"historical": ...}`
                # over `full_game`/`event_list`/`props`. Reproduced both ways:
                # with the document PRESENT every prior sport survives (the
                # merge in `_apply_observation` is correct), with it ABSENT they
                # are all lost. Absence is the whole cause.
                #
                # Off-fleet spend is already accounted on the fleet by
                # `_forward_to_fleet` below, which still runs. So the bounded
                # cost of this refusal is ONE telemetry observation when the
                # forward is also unreachable -- far cheaper than a document
                # that can be committed over the authoritative ledger. Both
                # lines print, so the pair says which happened.
                if _fleet_forward_enabled() and not _local_create_allowed():
                    raise _OffFleetAbsentDocument()
                payload = {}
            return _apply_observation(
                payload, observation, attempt,
                sport_key=sport_key, last_cost=last_cost, families=families,
                family_error=family_error, hour_key=hour_key,
            )

        try:
            compare_and_swap_json_file(_quota_path(), _build, max_attempts=_CAS_MAX_ATTEMPTS, backoff_seconds=0.02)
        except (WriteConflict, _UntrustedRead):
            # Every attempt collided. Dropping ONE observation is the bounded
            # cost; `used` stays exact on the next recorded call regardless.
            print(f"[oddsapi_quota] CAS_GAVE_UP sport={sport_key} attempts={_CAS_MAX_ATTEMPTS}", flush=True)
            return None
        except _OffFleetAbsentDocument:
            # NOT a failure, and NOT a `return`: the forward below is the whole
            # point of this branch. Printed every time rather than once, because
            # the count is how you notice a dev box whose spend is reaching
            # nobody (this line with no `FLEET_FORWARD status=ok` beside it).
            print(
                f"[oddsapi_quota] LOCAL_DOC_ABSENT_OFFFLEET sport={sport_key} "
                f"path={_quota_path()} -- not creating a local document; "
                f"forwarding only (set SYNDICATE_ODDSAPI_QUOTA_ALLOW_LOCAL_CREATE=1 "
                f"to create one anyway)",
                flush=True,
            )
        _forward_to_fleet(
            observation, sport_key=sport_key, last_cost=last_cost, families=families,
            family_error=family_error, hour_key=hour_key,
        )
        return observation
    except Exception:
        return None


# ---------------------------------------------------------------------------
# OFF-FLEET SPEND REACHES THE FLEET'S COUNTERS (lane `layer2-freshness-1h`,
# 2026-10-03, user: "wire backtests into the quota recorder").
#
# MEASURED: overnight 10-02/03 the account's `used` rose 126,764 credits more
# than the fleet's per-sport counters. 94,458 were a WNBA backtest's historical
# pull and 26,220 an NHL backtest's (`scripts/backtest_nhl_game_lines.py`) --
# and that NHL script ALREADY called `record_oddsapi_quota`. On a dev machine
# the state backend is the local filesystem, so its 874 observations went into
# a file in its working tree that nothing reads. Calling the recorder was
# necessary and not sufficient: off the fleet it has to reach the fleet's store.
#
# So an off-fleet process (state backend NOT keyvalue) ALSO applies each
# observation to the fleet's quota document, under `<sport>:offfleet` so
# backtest spend is its own line and never inflates a production sport. The
# fleet's key embeds the fleet's absolute data path, which a Windows process
# cannot reproduce from env, so the key is DISCOVERED (exactly one match, or
# nothing is written). Same compare-and-swap as the fleet's own writer; the
# key's TTL is kept. Fleet processes are untouched (their backend IS keyvalue).
#
#   SYNDICATE_ODDSAPI_QUOTA_FORWARD=0       off  (also off under pytest unless =force)
#   SYNDICATE_ODDSAPI_QUOTA_FORWARD_URL     default redis://127.0.0.1:6379/0
#
# One status line per process (`FLEET_FORWARD status=...`), so a backtest that
# could NOT reach the fleet says so instead of recording into a file nobody reads.
# ---------------------------------------------------------------------------
_FLEET_FORWARD_STATE: dict[str, Any] = {"announced": False, "key": None, "client": None, "failed": None}
_FLEET_QUOTA_KEY_PATTERN = "*:refresh-state:*odds_control_plane/oddsapi_quota.json"


def _fleet_forward_enabled() -> bool:
    import os

    raw = str(os.environ.get("SYNDICATE_ODDSAPI_QUOTA_FORWARD") or "").strip().lower()
    if raw in {"0", "off", "false", "no"}:
        return False
    # NEVER FROM A TEST RUN unless forced. Tests feed FAKE headers, and a test
    # process is off-fleet by definition: on 2026-10-03 15:52-15:54Z the quota
    # suite forwarded 556 fake observations into the fleet's document (fake
    # `<sport>:offfleet` buckets, and a `used=0` observation reset its burn
    # baseline). Real headers come only from real calls, which never run
    # under pytest.
    import sys

    if raw != "force" and ("PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules):
        return False
    try:
        from syndicate.features.shared.refresh_state_store import _keyvalue_backed

        return not _keyvalue_backed(_quota_path())
    except Exception:
        return False


def _fleet_forward_target() -> tuple[Any, str] | None:
    """(client, key) for the fleet's quota document, discovered once per process."""
    import os

    state = _FLEET_FORWARD_STATE
    if state["failed"] is not None:
        return None
    if state["client"] is not None and state["key"]:
        return state["client"], state["key"]
    try:
        import redis

        url = str(os.environ.get("SYNDICATE_ODDSAPI_QUOTA_FORWARD_URL") or "redis://127.0.0.1:6379/0").strip()
        client = redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=2)
        keys = sorted({k.decode() if isinstance(k, bytes) else str(k) for k in client.scan_iter(match=_FLEET_QUOTA_KEY_PATTERN, count=1000)})
    except Exception as exc:
        state["failed"] = f"unreachable:{type(exc).__name__}"
        return None
    if len(keys) != 1:
        state["failed"] = "no_quota_key" if not keys else f"ambiguous:{len(keys)}_keys"
        return None
    state["client"], state["key"] = client, keys[0]
    return client, keys[0]


def _forward_to_fleet(
    observation: dict[str, Any],
    *,
    sport_key: str,
    last_cost: int,
    families: dict[str, float],
    family_error: dict[str, Any] | None,
    hour_key: str,
) -> str:
    """Apply this observation to the fleet's quota document. Never raises."""
    status = "not_off_fleet"
    try:
        if not _fleet_forward_enabled():
            return status
        target = _fleet_forward_target()
        if target is None:
            status = f"skipped:{_FLEET_FORWARD_STATE['failed']}"
            return status
        client, key = target
        import json as _json

        import redis

        from syndicate.features.shared.refresh_state_store import normalize_timestamped_payload

        offfleet_key = f"{sport_key}:offfleet"
        for attempt in range(1, _CAS_MAX_ATTEMPTS + 1):
            with client.pipeline(transaction=True) as pipe:
                pipe.watch(key)
                raw_doc = client.get(key)
                payload = _json.loads(raw_doc) if raw_doc else {}
                if not isinstance(payload, dict) or not payload:
                    # Never rebuild the fleet's document from empty -- the same
                    # rule `_build` enforces for a failed local read.
                    status = "skipped:fleet_document_unreadable"
                    return status
                new = _apply_observation(
                    payload, observation, attempt,
                    sport_key=offfleet_key, last_cost=last_cost, families=families,
                    family_error=family_error, hour_key=hour_key,
                )
                pipe.multi()
                pipe.set(key, _json.dumps(normalize_timestamped_payload(new), separators=(",", ":")), keepttl=True)
                try:
                    pipe.execute()
                except redis.exceptions.WatchError:
                    time.sleep(0.02 * attempt)
                    continue
            status = f"ok:{offfleet_key}"
            return status
        status = "gave_up:cas"
        return status
    except Exception as exc:  # noqa: BLE001 -- instrumentation never fails a fetch
        status = f"error:{type(exc).__name__}"
        return status
    finally:
        if status != "not_off_fleet" and not _FLEET_FORWARD_STATE["announced"]:
            _FLEET_FORWARD_STATE["announced"] = True
            print(f"[oddsapi_quota] FLEET_FORWARD status={status} key={_FLEET_FORWARD_STATE.get('key')}", flush=True)


def _apply_observation(
    payload: dict[str, Any],
    observation: dict[str, Any],
    attempt: int,
    *,
    sport_key: str,
    last_cost: int,
    families: dict[str, float],
    family_error: dict[str, Any] | None,
    hour_key: str,
) -> dict[str, Any]:
    """The quota document after one observation. Pure: no IO.

    Shared by the local compare-and-swap and the off-fleet forward
    (`_forward_to_fleet`), so the two can never count an observation differently.
    """
    baseline = payload.get("baseline") if isinstance(payload.get("baseline"), dict) else None
    baseline = _next_baseline(baseline, observation)
    # LATEST IS THE HIGHEST `used`, not the last writer. Under
    # concurrency a slower writer can commit an older observation
    # after a newer one; `used` is monotonic within a billing period,
    # so the larger one is the newer reading. A drop (period rollover)
    # resets the baseline to this observation and takes it as latest.
    prior_latest = payload.get("latest") if isinstance(payload.get("latest"), dict) else None
    latest = observation
    if prior_latest is not None and baseline is not observation:
        try:
            if int(prior_latest.get("used") or 0) > int(observation.get("used") or 0):
                latest = prior_latest
        except (TypeError, ValueError):
            pass
    by_sport = dict(payload.get("by_sport") or {}) if isinstance(payload.get("by_sport"), dict) else {}
    bucket = dict(by_sport.get(sport_key) or {"calls": 0, "credits": 0})
    bucket["calls"] = int(bucket.get("calls") or 0) + 1
    bucket["credits"] = int(bucket.get("credits") or 0) + last_cost
    by_sport[sport_key] = bucket
    by_family = dict(payload.get("by_market_family") or {}) if isinstance(payload.get("by_market_family"), dict) else {}
    for family, credits in families.items():
        family_bucket = dict(by_family.get(family) or {"calls": 0, "credits": 0.0})
        family_bucket["calls"] = int(family_bucket.get("calls") or 0) + 1
        family_bucket["credits"] = round(float(family_bucket.get("credits") or 0.0) + credits, 2)
        by_family[family] = family_bucket
    by_hour = dict(payload.get("by_hour_utc") or {}) if isinstance(payload.get("by_hour_utc"), dict) else {}
    hour_bucket = dict(by_hour.get(hour_key) or {"calls": 0, "credits": 0})
    hour_bucket["calls"] = int(hour_bucket.get("calls") or 0) + 1
    hour_bucket["credits"] = int(hour_bucket.get("credits") or 0) + last_cost
    by_hour[hour_key] = hour_bucket
    return {
        "baseline": baseline,
        "latest": latest,
        "by_sport": by_sport,
        "by_market_family": by_family,
        "by_hour_utc": by_hour,
        "attribution_error_count": int(payload.get("attribution_error_count") or 0) + (1 if family_error else 0),
        "last_attribution_error": family_error or payload.get("last_attribution_error"),
        # Kept for continuity with the pre-CAS probe's history; no longer
        # incremented -- a conflict now retries instead of racing.
        "race_detected_count": int(payload.get("race_detected_count") or 0),
        "last_race_detail": payload.get("last_race_detail"),
        # Conflicts absorbed by a retry: the collisions that used to
        # lose an increment, now counted instead of lost.
        "cas_conflicts_count": int(payload.get("cas_conflicts_count") or 0) + (attempt - 1),
        "aggregates_started_at": str(payload.get("aggregates_started_at") or _utc_now_iso()),
        "observation_count": int(payload.get("observation_count") or 0) + 1,
        "updatedAt": _utc_now_iso(),
    }


# Retries before one observation is dropped. Contention is bursty and short (a
# few writers per second at peak), and each attempt is one small read + SET.
_CAS_MAX_ATTEMPTS = 20


class _UntrustedRead(RuntimeError):
    """The quota document could not be read reliably; never build from empty."""


class _OffFleetAbsentDocument(RuntimeError):
    """No local quota document, and this process is off-fleet.

    Distinct from `_UntrustedRead` because the handling differs: an untrusted
    read drops the observation entirely, while this one still FORWARDS it to
    the fleet and only declines the local write.
    """


def _local_create_allowed() -> bool:
    """Opt-in escape hatch for a dev box that genuinely wants its own document.

    Off by default: the common case is a run whose `reports_root()` simply is
    not where the ledger lives, and in that case creating a document is the bug.
    A developer measuring their own spend in isolation can set this and get the
    old behaviour.
    """
    import os

    return str(os.environ.get("SYNDICATE_ODDSAPI_QUOTA_ALLOW_LOCAL_CREATE") or "").strip().lower() in {
        "1", "on", "true", "yes",
    }


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
        # Collisions absorbed by a compare-and-swap retry (2026-10-02): each one
        # is an increment the pre-CAS recorder would have lost.
        "cas_conflicts_count": int(payload.get("cas_conflicts_count") or 0),
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
