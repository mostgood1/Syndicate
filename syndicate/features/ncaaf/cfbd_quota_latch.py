"""Stop calling CFBD once it has said the MONTHLY quota is gone.

WHY A LATCH AND NOT MORE BACKOFF. `cfbd_backoff.py` survives a short-window
throttle: five bounded retries, then the caller dies loudly. That is the right
policy for a per-minute limit and the wrong one for a per-MONTH limit, because
there is nothing to back off *to* -- the answer will be identical for days. Its
own docstring says so: "If CFBD is out of quota for the hour, five bounded
retries end in the same exception and the process still dies -- correctly."

MEASURED 2026-08-31 on refresh-worker, which is what makes this worth a module:

    SEASON_PROJECTION_LAUNCHING sport=ncaaf reason=artifact_stale
      age_seconds=366893  interval_seconds=86400

**The configured interval is once per DAY and it was firing about 24x that.**
A failing run never refreshes the artifact, so `age_seconds` keeps climbing past
the staleness threshold and every worker tick re-triggers it -- 14 generator
attempts that day, hourly, each dying in `load_ppa_ratings_asof` -> `_cfbd_get`,
with the artifact 4.25 days stale. Ten snapshot builders share the API key and
therefore the quota.

That is a feedback loop with the wrong sign: **it hammers hardest exactly when
the quota is scarcest.** The latch breaks it. Once CFBD answers "Monthly call
quota exceeded", every caller on this key fails fast WITHOUT issuing a request
until the month rolls.

THE LATCH IS PERSISTENT BECAUSE THE CALLERS ARE NOT. The generator runs as a
fresh process on every launch, so an in-memory flag would be forgotten between
attempts -- which is precisely the interval this exists to cover.

IT EXPIRES ON THE MONTH ROLL, NOT ON A DURATION. The quota is monthly, so the
honest expiry is 00:00 UTC on the 1st. A fixed TTL would either keep calling
after the quota returned or keep refusing after it did.

WHAT IT DELIBERATELY DOES NOT DO. It does not latch on a bare 429. A
short-window throttle and an exhausted monthly quota arrive with the same
status code and need opposite responses, so the discriminator is the BODY --
CFBD says `{"message": "Monthly call quota exceeded."}`. An unrecognised 429
falls through to `cfbd_backoff`'s retries exactly as before. Guessing here would
convert a 30-second throttle into a multi-day outage.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__all__ = [
    "MONTHLY_QUOTA_MARKERS",
    "QuotaExhausted",
    "is_monthly_quota_body",
    "latch_path",
    "note_quota_exhausted",
    "quota_latched_until",
    "raise_if_latched",
    "clear_latch",
]

# Matched case-insensitively against the response body. A LIST, not one string:
# the wording is the vendor's and can change, and a latch that silently stops
# recognising its own trigger degrades to today's behaviour rather than to
# something worse -- but it degrades SILENTLY, which is why `note_quota_exhausted`
# logs the body it did not recognise.
MONTHLY_QUOTA_MARKERS = (
    "monthly call quota exceeded",
    "monthly quota exceeded",
    "call quota exceeded",
)


class QuotaExhausted(RuntimeError):
    """Raised INSTEAD of making a request, while the latch is set.

    A distinct type on purpose: a caller that wants to fall back to cache needs
    to tell "the quota is gone" from "the network failed", and those have
    different right answers -- the first should use stale data and say so, the
    second should retry.
    """


def _state_dir() -> Path:
    """Where the latch lives.

    `SYNDICATE_DATA_ROOT` when set, because on Render that is the MOUNTED DISK
    and the repo checkout is ephemeral -- a latch written into the checkout
    would not survive the next deploy, which is exactly when a storm restarts.
    """
    root = str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip()
    base = Path(root) if root else Path(__file__).resolve().parents[3] / "data"
    return base / "ncaaf_source" / "state"


def latch_path() -> Path:
    return _state_dir() / "cfbd_quota_latch.json"


def is_monthly_quota_body(body: Any) -> bool:
    text = str(body or "").strip().lower()
    if not text:
        return False
    return any(marker in text for marker in MONTHLY_QUOTA_MARKERS)


def _next_month_roll(now: datetime) -> datetime:
    """00:00 UTC on the 1st of the next month."""
    year, month = now.year, now.month
    return datetime(year + (month // 12), (month % 12) + 1, 1, tzinfo=timezone.utc)


def note_quota_exhausted(body: Any, *, log=None) -> float | None:
    """Set the latch if `body` says the MONTHLY quota is gone. Returns the epoch
    it expires at, or None if this was not a monthly-quota answer.

    Never raises: a latch that cannot be written must not take down the call it
    was trying to protect. It degrades to today's behaviour.
    """
    if not is_monthly_quota_body(body):
        return None
    now = datetime.now(timezone.utc)
    expires = _next_month_roll(now).timestamp()
    payload = {
        "expires_epoch": expires,
        "expires_iso": _next_month_roll(now).isoformat(),
        "noted_iso": now.isoformat(),
        "body": str(body)[:400],
    }
    try:
        path = latch_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
        tmp.replace(path)
    except Exception as exc:  # pragma: no cover - defensive
        if log:
            log(f"[cfbd_quota] LATCH_WRITE_FAILED {type(exc).__name__} -- calls continue unthrottled")
        return expires
    if log:
        log(
            f"[cfbd_quota] LATCH_SET until={payload['expires_iso']} "
            f"-- CFBD calls on this key will fail fast without a request until then"
        )
    return expires


def quota_latched_until(*, now: float | None = None) -> float | None:
    """The epoch the latch expires at, or None if not latched.

    An unreadable or malformed latch reads as NOT latched. Failing open is
    deliberate here and is the opposite of the usual rule: the cost of a wrong
    "not latched" is one wasted call, while the cost of a wrong "latched" is a
    multi-day outage on a service that is actually healthy.
    """
    try:
        payload = json.loads(latch_path().read_text(encoding="utf-8"))
        expires = float(payload.get("expires_epoch") or 0.0)
    except Exception:
        return None
    current = time.time() if now is None else now
    return expires if expires > current else None


def raise_if_latched(describe: str, *, log=None, now: float | None = None) -> None:
    """`QuotaExhausted` if the monthly quota is known-gone, else return."""
    expires = quota_latched_until(now=now)
    if expires is None:
        return
    current = time.time() if now is None else now
    hours = max(0.0, (expires - current) / 3600.0)
    message = (
        f"CFBD monthly quota exhausted; not issuing {describe}. "
        f"Latch clears in {hours:.1f}h at the month roll."
    )
    if log:
        log(f"[cfbd_quota] LATCHED_SKIP {describe} clears_in_hours={hours:.1f}")
    raise QuotaExhausted(message)


def clear_latch() -> None:
    """Drop the latch. For tests and for a deliberate manual override."""
    try:
        latch_path().unlink()
    except Exception:
        pass
