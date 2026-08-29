"""One retry policy for every CollegeFootballData.com call this repo makes.

WHY THIS IS A SHARED MODULE AND NOT AN INLINE `except` AT THE ONE CALL SITE
THAT WAS OBSERVED FAILING.

Measured on refresh-worker 2026-08-29: `generate_smartsim2_ncaaf_projections.py`
died on `urllib.error.HTTPError: HTTP Error 429: Too Many Requests` at
`_cfbd_get`, reached through `load_ppa_ratings` <- `load_ppa_ratings_asof` --
the prior-season PPA fallback taken in week 1. Roughly 30 launches in 2h45m,
every one dying the same way, because a failed run leaves the artifact stale
and the autorun's staleness check refires within minutes. The NCAAF season
projection artifact had not rebuilt since 2026-08-26 16:16 CDT.

**It is the SECOND time.** `learnings.md` 2026-08-27 records four runs dying on
the same 429 in the same function. That entry fixed the INSTRUMENT -- an
`age_seconds` stamped by the launcher never vouched for the job succeeding --
and left the 429 itself alone, so the loop was still running two days later.

THERE ARE TWO CFBD ENTRY POINTS AND NEITHER BACKED OFF.
`scripts/generate_smartsim2_ncaaf_projections.py::_cfbd_get` (urllib) is the one
that was observed; `syndicate/features/ncaaf/cfbd.py::CfbdClient._get_json`
(requests) reaches CFBD for ten snapshot builders and called bare
`raise_for_status()`. They share an API key and therefore a quota, so fixing
only the one in the traceback would leave the other free to spend the budget
the first is now politely waiting for.

WHAT THIS MODULE IS, DELIBERATELY.
A PURE POLICY plus a transport-agnostic executor. It does no I/O and imports
no HTTP library, because the two call sites use different ones and raise
different exception types; each maps its own error to `(status, retry_after)`
and this decides what happens next. That keeps the numbers -- which statuses,
how many attempts, how long -- in one place where they can be unit-tested
without a network, rather than duplicated into two `except` blocks that will
drift.

WHAT IT DOES NOT DO. It does not make a failing run succeed. If CFBD is out of
quota for the hour, five bounded retries end in the same exception and the
process still dies -- correctly, and loudly. Its job is to survive the
SHORT-WINDOW throttle that a burst of parallel snapshot builders provokes, and
to stop the caller hammering a limit it has already been told it exceeded. The
relaunch cadence is a separate defect with a separate fix, in
`run_refresh_worker.py::_season_projection_should_launch`.
"""

from __future__ import annotations

import random
import time
from email.utils import parsedate_to_datetime
from typing import Any, Callable

__all__ = [
    "RETRYABLE_STATUSES",
    "MAX_ATTEMPTS",
    "parse_retry_after",
    "retry_delay_seconds",
    "call_with_retry",
]


# 429 is the observed failure. The 5xx family is here because a gateway blip is
# the same decision for the caller -- wait and try again -- and excluding it
# would mean a second `except` branch somewhere else doing this badly.
# 4xx OTHER THAN 429 IS NOT RETRYABLE ON PURPOSE: a 401 from a missing key and
# a 404 from a wrong path do not improve with waiting, and retrying them turns
# a clear error into a slow one.
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})

# Five attempts = the original plus four retries.
MAX_ATTEMPTS = 5

# Exponential from 2s: 2, 4, 8, 16 (before jitter).
BASE_DELAY_SECONDS = 2.0

# A single wait never exceeds this, even if `Retry-After` asks for longer. See
# MAX_TOTAL_SLEEP_SECONDS for why we bound rather than obey.
MAX_DELAY_SECONDS = 60.0

# THE HARD CEILING, AND THE REASON IT IS LOW.
#
# This runs inside a subprocess the refresh worker launches and then does not
# wait on. A run that sleeps for an hour holds the
# `_season_projection_process_still_running` guard for an hour, which suppresses
# every later launch of that sport -- so an over-patient backoff here silently
# becomes an outage there. 180s keeps the worst case shorter than one autorun
# tick while still spanning a typical per-minute throttle window.
MAX_TOTAL_SLEEP_SECONDS = 180.0


def parse_retry_after(value: Any) -> float | None:
    """`Retry-After` in seconds, from either of its two legal spellings.

    RFC 9110 allows a delay in seconds OR an HTTP-date, and CFBD has been seen
    sending neither -- so this returns None rather than raising, and None means
    "the server did not tell us", never "wait zero".
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return max(0.0, float(text))
    except (TypeError, ValueError):
        pass
    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    try:
        delta = when.timestamp() - time.time()
    except (OverflowError, OSError, ValueError):
        return None
    return max(0.0, delta)


def retry_delay_seconds(
    *,
    status: int | None,
    attempt: int,
    retry_after: Any = None,
    slept_so_far: float = 0.0,
    rng: Callable[[], float] = random.random,
) -> float | None:
    """Seconds to wait before attempt `attempt + 1`, or None to give up.

    `attempt` is 1-based: the call that just failed. Returning None is the ONLY
    way this says stop, so a caller that treats None as zero would loop forever
    -- hence the name says delay and the contract says None means give up.

    FULL JITTER, not a fixed schedule. Ten snapshot builders that all hit 429 at
    once and all back off to exactly 2s would come back as a synchronised burst
    and re-trigger the same limit. `rng` is injectable so the policy can be
    tested as a pure function.
    """
    if status is None or int(status) not in RETRYABLE_STATUSES:
        return None
    if attempt >= MAX_ATTEMPTS:
        return None

    remaining = MAX_TOTAL_SLEEP_SECONDS - max(0.0, float(slept_so_far))
    if remaining <= 0.0:
        return None

    server_ask = parse_retry_after(retry_after)
    if server_ask is not None:
        # The server's own number wins over our guess, bounded by our ceiling.
        # Not obeyed unconditionally: a 3600s `Retry-After` would park this
        # subprocess for an hour and block the sport (see MAX_TOTAL_SLEEP).
        delay = min(server_ask, MAX_DELAY_SECONDS)
    else:
        backoff = BASE_DELAY_SECONDS * (2 ** (attempt - 1))
        delay = min(backoff, MAX_DELAY_SECONDS) * rng()

    if delay > remaining:
        # Waiting the full amount would exceed the budget. Take what is left
        # rather than giving up: a shortened last wait is still a wait, and the
        # ceiling is about bounding the process, not about precision.
        delay = remaining
    return max(0.0, delay)


def call_with_retry(
    operation: Callable[[], Any],
    *,
    classify: Callable[[BaseException], tuple[int | None, Any] | None],
    describe: str = "cfbd",
    sleep: Callable[[float], None] = time.sleep,
    rng: Callable[[], float] = random.random,
    log: Callable[[str], None] | None = None,
) -> Any:
    """Run `operation()`, retrying per the policy above.

    `classify(exc)` returns `(status, retry_after_header)` for an HTTP error it
    recognises, or None for anything it does not -- and None RE-RAISES
    IMMEDIATELY. That is the important direction: an exception this module does
    not understand must not be swallowed into a retry loop and reported as a
    rate limit.

    The final failure re-raises the ORIGINAL exception, so the traceback still
    names the real call site and status. A wrapper exception here would have
    hidden exactly the `HTTP Error 429 ... in _cfbd_get` line that made this
    diagnosable at all.
    """
    slept = 0.0
    attempt = 0
    while True:
        attempt += 1
        try:
            return operation()
        except BaseException as exc:  # noqa: BLE001 -- re-raised below unless retryable
            classified = classify(exc)
            if classified is None:
                raise
            status, retry_after = classified
            delay = retry_delay_seconds(
                status=status,
                attempt=attempt,
                retry_after=retry_after,
                slept_so_far=slept,
                rng=rng,
            )
            if delay is None:
                raise
            if log is not None:
                log(
                    f"[cfbd_backoff] {describe} status={status} attempt={attempt}/{MAX_ATTEMPTS} "
                    f"sleeping={delay:.1f}s slept_total={slept:.1f}s"
                )
            sleep(delay)
            slept += delay
