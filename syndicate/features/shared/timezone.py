from __future__ import annotations

from datetime import date
from datetime import datetime
from zoneinfo import ZoneInfo


CENTRAL_TIMEZONE = ZoneInfo("America/Chicago")


def central_now() -> datetime:
    return datetime.now(CENTRAL_TIMEZONE)


def central_today() -> date:
    return central_now().date()


def central_today_iso() -> str:
    return central_today().isoformat()


def central_year() -> int:
    return central_today().year


def central_datetime_from_epoch(epoch: float) -> datetime:
    return datetime.fromtimestamp(float(epoch), tz=CENTRAL_TIMEZONE)