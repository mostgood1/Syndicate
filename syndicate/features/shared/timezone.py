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