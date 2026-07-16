from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syndicate.features.football.sim_engine.smartsim2.play_state import PlayState


# True field-goal range: kick distance = 17 + (100 - yardline). Yardline >= 65 keeps the
# attempt at 52 yards or shorter, which is the realistic NFL attempt envelope.
TRUE_FIELD_GOAL_RANGE_YARDLINE = 65

# Explicit urgency states for late-half and late-game football behavior.
URGENCY_NEUTRAL = "neutral_offense"
URGENCY_TWO_MINUTE = "two_minute_drill"
URGENCY_FOUR_MINUTE = "four_minute_offense"
URGENCY_TRAILING = "trailing_urgency"
URGENCY_HALFTIME_PRESERVATION = "halftime_preservation"
URGENCY_END_GAME_PRESERVATION = "end_game_preservation"

URGENCY_STATES = (
    URGENCY_NEUTRAL,
    URGENCY_TWO_MINUTE,
    URGENCY_FOUR_MINUTE,
    URGENCY_TRAILING,
    URGENCY_HALFTIME_PRESERVATION,
    URGENCY_END_GAME_PRESERVATION,
)


def classify_urgency(*, quarter: int, seconds_remaining: int, score_differential: int, yardline: int) -> str:
    """Classify the offense's urgency state from game context.

    Preservation states (kneel/run-out) take precedence, then hurry-up states,
    then the leading four-minute grind, then neutral offense.
    """
    if quarter >= 4 and seconds_remaining <= 150 and score_differential > 0:
        return URGENCY_END_GAME_PRESERVATION
    if quarter == 2 and seconds_remaining <= 60 and score_differential >= 0 and yardline < 50:
        return URGENCY_HALFTIME_PRESERVATION
    if quarter in {2, 4} or quarter >= 5:
        if seconds_remaining <= 120 and score_differential <= 7:
            return URGENCY_TWO_MINUTE
    if quarter >= 4 and seconds_remaining <= 360 and score_differential < 0:
        return URGENCY_TRAILING
    if quarter >= 4 and 120 < seconds_remaining <= 240 and score_differential > 0:
        return URGENCY_FOUR_MINUTE
    return URGENCY_NEUTRAL


@dataclass(frozen=True)
class SituationContext:
    label: str
    red_zone: bool
    goal_to_go: bool
    backed_up_territory: bool
    field_goal_range: bool
    four_minute_offense: bool
    two_minute_drill: bool
    long_yardage: bool
    urgency_state: str = URGENCY_NEUTRAL

    def to_dict(self) -> dict[str, bool | str]:
        return {
            "label": self.label,
            "red_zone": self.red_zone,
            "goal_to_go": self.goal_to_go,
            "backed_up_territory": self.backed_up_territory,
            "field_goal_range": self.field_goal_range,
            "four_minute_offense": self.four_minute_offense,
            "two_minute_drill": self.two_minute_drill,
            "long_yardage": self.long_yardage,
            "urgency_state": self.urgency_state,
        }


def classify_situation(play_state: PlayState) -> SituationContext:
    red_zone = play_state.yardline >= 80
    goal_to_go = play_state.yardline >= 90 and play_state.yards_to_goal <= play_state.distance
    backed_up_territory = play_state.yardline <= 20
    field_goal_range = play_state.yardline >= TRUE_FIELD_GOAL_RANGE_YARDLINE
    urgency_state = classify_urgency(
        quarter=play_state.quarter,
        seconds_remaining=play_state.seconds_remaining,
        score_differential=play_state.score_differential,
        yardline=play_state.yardline,
    )
    four_minute_offense = urgency_state == URGENCY_FOUR_MINUTE
    two_minute_drill = urgency_state == URGENCY_TWO_MINUTE
    long_yardage = play_state.distance >= 8

    if goal_to_go and play_state.yards_to_goal <= 5:
        label = "Goal Line"
    elif two_minute_drill:
        label = "Two Minute Drill"
    elif four_minute_offense:
        label = "Four Minute Offense"
    elif red_zone:
        label = "Red Zone"
    elif long_yardage:
        label = "Long Yardage"
    else:
        label = "Neutral"

    return SituationContext(
        label=label,
        red_zone=red_zone,
        goal_to_go=goal_to_go,
        backed_up_territory=backed_up_territory,
        field_goal_range=field_goal_range,
        four_minute_offense=four_minute_offense,
        two_minute_drill=two_minute_drill,
        long_yardage=long_yardage,
        urgency_state=urgency_state,
    )


__all__ = [
    "SituationContext",
    "TRUE_FIELD_GOAL_RANGE_YARDLINE",
    "URGENCY_NEUTRAL",
    "URGENCY_TWO_MINUTE",
    "URGENCY_FOUR_MINUTE",
    "URGENCY_TRAILING",
    "URGENCY_HALFTIME_PRESERVATION",
    "URGENCY_END_GAME_PRESERVATION",
    "URGENCY_STATES",
    "classify_situation",
    "classify_urgency",
]