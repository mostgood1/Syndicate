from __future__ import annotations

from enum import Enum


class EventOutcome(str, Enum):
    ADVANCE = "advance"
    FAST_BREAK = "fast_break"
    RETAIN = "retain"
    TURNOVER = "turnover"
    FOUL_WON = "foul_won"
    OFFSIDE = "offside"
    SHOT = "shot"
    CORNER_WON = "corner_won"


__all__ = ["EventOutcome"]
