from __future__ import annotations

from enum import Enum


class PlayOutcome(str, Enum):
    GAIN = "gain"
    EXPLOSIVE_GAIN = "explosive_gain"
    SACK = "sack"
    PENALTY = "penalty"
    TURNOVER = "turnover"
    INCOMPLETE_PASS = "incomplete_pass"
    TOUCHDOWN = "touchdown"
    FIELD_GOAL_ATTEMPT = "field_goal_attempt"
    MISSED_FIELD_GOAL = "missed_field_goal"


__all__ = ["PlayOutcome"]