from __future__ import annotations

import datetime as dt
import logging
import os
import threading

from flask import has_request_context


logger = logging.getLogger(__name__)


class ComputeInRequestPathError(RuntimeError):
    """Raised when heavy intelligence compute is about to run inside a live
    web request on a hosted (Render) deployment. See
    refuse_if_compute_in_request_path.
    """


_TRUTHY = {"1", "true", "yes", "on"}

# Opt-in flags. Either one being TRUE means hosted.
_HOSTED_FLAGS = ("RENDER", "SYNDICATE_REQUIRE_HOSTED_STORAGE")

# Injected by the Render RUNTIME, not by the service's env-var config, and so
# not deletable from the dashboard. Verified 2026-09-04 against the live web
# dyno's own `/api/ops/version`, which reports its own environment:
# RENDER_SERVICE_NAME='syndicate-an21',
# RENDER_INSTANCE_ID='srv-d88ahvrbc2fs73eodu30-7cff65c8c4-68pvq',
# RENDER_EXTERNAL_URL='https://syndicate-an21.onrender.com' -- while NONE of
# them appear among that service's 76 user-defined env vars. Presence alone is
# the signal; these carry identifiers, not booleans.
_HOSTED_MARKERS = ("RENDER_SERVICE_ID", "RENDER_INSTANCE_ID", "RENDER_SERVICE_NAME", "RENDER_EXTERNAL_URL")


# --------------------------------------------------------------------------
# Counters. On 2026-08-27 this guard refused 348 times in seven hours and
# nothing counted them -- every one a silently degraded response, discoverable
# only by going and reading the logs afterwards. `[user decision 2026-09-04]`
#
# SCOPE, and it is stated in the payload rather than left to the reader: web
# runs WEB_CONCURRENCY=2 gunicorn workers x GUNICORN_THREADS=4. These counters
# live in ONE process, so a read covers one worker of two -- and four threads
# share them, hence the lock. Making them service-wide would mean a keyvalue
# write per refusal, i.e. network I/O added to the request path the guard exists
# to keep work off. The counter is the always-on signal; the log line (which
# names the operation as of `08d3fae5`) is the ledger.
# --------------------------------------------------------------------------

# Bounded so an unexpected caller passing a dynamic name cannot grow this
# without limit. Overflow is VISIBLE under a single key, never dropped.
_MAX_TRACKED_OPERATIONS = 32
_OVERFLOW_KEY = "__other__"

_counter_lock = threading.Lock()
_counts = {"refused": 0, "warned": 0}
_by_operation: dict[str, dict[str, int]] = {}
_first_refusal_at: str | None = None
_last_refusal_at: str | None = None
_last_refused_operation: str | None = None


def _utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _record(kind: str, operation: str) -> None:
    """Never raises. A counter that can break the thing it measures is worse
    than no counter."""
    global _first_refusal_at, _last_refusal_at, _last_refused_operation
    try:
        with _counter_lock:
            _counts[kind] = _counts.get(kind, 0) + 1
            key = operation if (operation in _by_operation or len(_by_operation) < _MAX_TRACKED_OPERATIONS) else _OVERFLOW_KEY
            bucket = _by_operation.setdefault(key, {"refused": 0, "warned": 0})
            bucket[kind] = bucket.get(kind, 0) + 1
            if kind == "refused":
                stamp = _utc_now_iso()
                if _first_refusal_at is None:
                    _first_refusal_at = stamp
                _last_refusal_at = stamp
                _last_refused_operation = operation
    except Exception:  # noqa: BLE001 -- see the docstring
        pass


def guard_counters() -> dict:
    """A snapshot, carrying the scope that makes it readable.

    `pid` and `covers` are not decoration: without them a caller reads a
    one-worker number as a service total and halves the truth.
    """
    with _counter_lock:
        by_operation = {k: dict(v) for k, v in _by_operation.items()}
        counts = dict(_counts)
        first, last, last_op = _first_refusal_at, _last_refusal_at, _last_refused_operation
    concurrency = str(os.environ.get("WEB_CONCURRENCY") or "").strip() or None
    return {
        "refused": counts.get("refused", 0),
        "warned": counts.get("warned", 0),
        "by_operation": by_operation,
        "first_refusal_at": first,
        "last_refusal_at": last,
        "last_refused_operation": last_op,
        "hosted_signal": hosted_signal(),
        "pid": os.getpid(),
        "web_concurrency": concurrency,
        "covers": (
            f"THIS gunicorn worker only (pid {os.getpid()}); the service runs "
            f"{concurrency or 'an unknown number of'} workers, so a service-wide total is "
            "this times the worker count only if load is even -- read the logs for the real ledger"
        ),
        "tracked_operations_cap": _MAX_TRACKED_OPERATIONS,
    }


def reset_guard_counters() -> None:
    """Tests only."""
    global _first_refusal_at, _last_refusal_at, _last_refused_operation
    with _counter_lock:
        _counts.clear()
        _counts.update({"refused": 0, "warned": 0})
        _by_operation.clear()
        _first_refusal_at = _last_refusal_at = _last_refused_operation = None


def hosted_signal() -> str | None:
    """The NAME of the env var saying this is a hosted deployment, or None.

    A name rather than a bool so the answer can be logged. "Is the guard armed?"
    was an open question on 2026-09-04 precisely because nothing recorded WHICH
    key armed it, and the two candidates have very different durability.
    """
    for key in _HOSTED_FLAGS:
        if str(os.environ.get(key) or "").strip().lower() in _TRUTHY:
            return key
    for key in _HOSTED_MARKERS:
        if str(os.environ.get(key) or "").strip():
            return key
    return None


def warn_if_compute_in_request_path(operation: str) -> None:
    if not has_request_context():
        return
    name = str(operation or "").strip() or "unknown"
    _record("warned", name)
    logger.warning("WARNING: compute in request path (operation=%s)", name, extra={"operation": name})


def _is_render_hosted() -> bool:
    """Hosted if ANY flag is true or ANY injected marker is present.

    Two changes from the original `RENDER or SYNDICATE_REQUIRE_HOSTED_STORAGE`:

    1. **Each key is tested independently.** The `or` chained the LOOKUPS, not
       the results, so any non-empty `RENDER` short-circuited the fallback --
       `RENDER=false` disarmed the guard outright even with
       `SYNDICATE_REQUIRE_HOSTED_STORAGE=true`. A value that says "not hosted"
       must not also suppress the key that says "hosted".
    2. **The injected markers are consulted.** Arming used to be able to rest on
       `SYNDICATE_REQUIRE_HOSTED_STORAGE` alone -- a key whose NAME is about
       storage, so a plausible thing for someone to tidy away, and deleting it
       would have silently downgraded this HARD gate to warn-only and restored
       `#98`. The markers cannot be deleted from the dashboard.

    This is hardening with no production behaviour change: the guard was already
    refusing on web (348 events on 2026-08-27, a branch unreachable unless this
    already returned True), so nothing is newly armed -- only made undeletable.
    """
    return hosted_signal() is not None


def refuse_if_compute_in_request_path(operation: str) -> None:
    """Hard-enforce this repo's load-bearing rule: the web service does no
    heavy computation, intelligence compute belongs on refresh-worker only,
    web just reads what has already been computed there.

    #56/#98/#109. Two separate incidents this session were both the same
    root cause wearing different clothes: #98's OOM (the ops.py candidate-
    trace debug endpoint calling _build_candidate_pool directly on the 2GB
    web container under load) and #109's memory spike (the query API's
    force_refresh cache-miss fallback calling _compute_response directly).
    Both were fixed individually after the fact. Rather than relying on
    every future caller remembering not to reintroduce this, this is now a
    structural gate at the actual compute entry points
    (IntelligenceStateService._compute_response/_build_candidate_pool) --
    including the admin-gated debug endpoint, which is not exempted; #98's
    incident is exactly why not.

    refresh-worker is a plain script with no Flask app, so
    has_request_context() is always False there -- this can only ever fire
    for a real HTTP request being served by a web dyno, regardless of which
    Render service happens to be running the code. Local dev (not
    render-hosted) keeps the previous warn-only behavior so a developer
    running the app directly, with no separate worker process, is
    unaffected.
    """
    if not has_request_context():
        return
    if not _is_render_hosted():
        warn_if_compute_in_request_path(operation)
        return
    name = str(operation or "").strip() or "unknown"
    _record("refused", name)
    signal = hosted_signal()
    # The operation goes in the MESSAGE, not only in `extra`. The default
    # formatter drops `extra`, so all 348 refusals logged on 2026-08-27 were
    # byte-identical text and `_compute_response` could not be told from
    # `_build_candidate_pool` -- including the ops debug endpoint that caused
    # `#98`. The arming signal rides along for the same reason.
    logger.error(
        "REFUSED: compute in request path on hosted web (operation=%s, hosted_signal=%s)",
        name,
        signal,
        extra={"operation": name, "hosted_signal": signal},
    )
    raise ComputeInRequestPathError(
        f"Refusing to run {operation!r} inside a web request on a hosted deployment -- "
        "intelligence compute belongs on refresh-worker only; web reads precomputed state."
    )
