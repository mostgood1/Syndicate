from __future__ import annotations

from datetime import date
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


CENTRAL_TIMEZONE = ZoneInfo("America/Chicago")


def central_now() -> datetime:
    return datetime.now(CENTRAL_TIMEZONE)


def central_today() -> date:
    return central_now().date()


def central_today_iso() -> str:
    return central_today().isoformat()


def central_year() -> int:
    return central_now().year


def central_datetime_from_epoch(epoch: float) -> datetime:
    return datetime.fromtimestamp(float(epoch), tz=CENTRAL_TIMEZONE)


def central_date_from_iso(value: Any) -> date | None:
    """Central-calendar-day a UTC/ISO timestamp actually falls on.

    Bug found 2026-07-21: WNBA game-card filtering compared a raw UTC
    commence_time string's date PREFIX against the requested slate date,
    e.g. treating "2026-07-21T00:00:00Z" as belonging to 2026-07-21. A
    7pm Central tip-off is 00:00 UTC the *next* calendar day (19:00 + 5h),
    so essentially every evening game's UTC-date prefix is slate_date + 1,
    not slate_date -- naive prefix matching against slate_date was actually
    selecting the PRIOR day's evening games. Use this for any "which slate
    day does this game belong to" comparison instead of string prefixes.
    """
    text = str(value or "").strip()
    if not text:
        return None
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=CENTRAL_TIMEZONE)
        return stamp.astimezone(CENTRAL_TIMEZONE).date()
    except Exception:
        return None


def _centralize_iso_timestamp(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=CENTRAL_TIMEZONE)
        return stamp.astimezone(CENTRAL_TIMEZONE).isoformat(timespec="seconds")
    except Exception:
        return text


def normalize_timestamped_payload(value: Any) -> Any:
    timestamp_keys = {
        "completedAt",
        "completed_at",
        "finishedAt",
        "finished_at",
        "generatedAt",
        "generated_at",
        "lastSeenAt",
        "last_seen_at",
        "lastUpdated",
        "last_updated",
        "oddsRefreshedAt",
        "odds_refreshed_at",
        "publishedAt",
        "published_at",
        "recordedAt",
        "recorded_at",
        "refreshedAt",
        "refreshed_at",
        "timestamp",
        "updatedAt",
        "updated_at",
    }
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if key in timestamp_keys:
                normalized[key] = _centralize_iso_timestamp(item)
            else:
                normalized[key] = normalize_timestamped_payload(item)
        return normalized
    if isinstance(value, list):
        return [normalize_timestamped_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(normalize_timestamped_payload(item) for item in value)
    return value

def central_clock(value: Any, *, with_date: bool = False) -> str:
    """A UTC/ISO timestamp -> what the clock said in CENTRAL. Display only.

    EVERY TIME A PERSON READS IS CENTRAL [USER DECISION 2026-08-25]. The live
    portfolio rendered `submitted_at[11:19]` -- a raw slice of the stored UTC
    string -- so an order placed at 6:15 PM Central appeared as `23:15:05`. Not
    labelled, not converted, five hours wrong, and sitting in the column a
    person uses to reconcile against the venue's own screen.

    STORAGE STAYS UTC, AND THAT IS NOT A COMPROMISE. Venue payloads are UTC,
    `fetched_at` ages are computed against `time.time()`, and ISO strings are
    compared lexically all over this repo -- rewriting stored stamps to a
    zone with a DST discontinuity would break every one of those, and twice a
    year would break them silently. The rule is: UTC on the wire and on disk,
    Central everywhere a human looks, converted at the edge.

    Returns "" for anything unreadable rather than a guess -- a blank cell is
    honest, and `str(None)[11:19]` was how the old slice failed.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return ""
    if moment.tzinfo is None:
        # A naive stamp in this repo is UTC by convention -- everything that
        # writes one uses `datetime.now(timezone.utc)` or `time.time()`.
        from datetime import timezone as _tz

        moment = moment.replace(tzinfo=_tz.utc)
    local = moment.astimezone(CENTRAL_TIMEZONE)
    return local.strftime("%Y-%m-%d %H:%M:%S") if with_date else local.strftime("%H:%M:%S")


def central_clock_from_epoch(epoch: Any, *, with_date: bool = False) -> str:
    """Same, for a float epoch (`fetched_at` is stored that way)."""
    try:
        moment = central_datetime_from_epoch(float(epoch))
    except (TypeError, ValueError, OSError):
        return ""
    return moment.strftime("%Y-%m-%d %H:%M:%S") if with_date else moment.strftime("%H:%M:%S")
