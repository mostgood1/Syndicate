"""One label for a game-status badge, whatever shape the status arrives in.

Most sports hand the shared card templates a plain string ("Final",
"In Progress"), but WNBA's board context carries the source API's status
CONTRACT -- `{"status", "detail", "startTime", "in_progress", "final",
"period", "clock"}` -- and `{{ game.status }}` printed that whole dict into the
badge on /wnba/cards?client=board (2026-10-01). The dict is a real API shape the
source client consumes, so the fix belongs at render time, not in the producer.
Strings pass through unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def status_label(value: Any) -> str:
    if not isinstance(value, Mapping):
        return _text(value)
    if value.get("final"):
        return "Final"
    detail = _text(value.get("detail"))
    if value.get("in_progress"):
        period = _text(value.get("period"))
        clock = _text(value.get("clock"))
        if period and clock:
            return f"Q{period} {clock}"
        return detail or "Live"
    return _text(value.get("status")) or detail
