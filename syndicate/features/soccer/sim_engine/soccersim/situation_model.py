from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syndicate.features.soccer.sim_engine.soccersim.event_state import EventState


# Pitch position runs 1-99 from the possession owner's own goal toward the
# opponent's goal. The final third starts at 67; the penalty box occupies
# roughly the last 16% of the pitch (16.5m of a 105m pitch), so >= 84.
FINAL_THIRD_PITCH_POSITION = 67
PENALTY_BOX_PITCH_POSITION = 84
# Realistic shooting range: long-range attempts start around 62 (roughly
# 25-30 meters out); attempts from deeper than this are not modeled.
SHOOTING_RANGE_PITCH_POSITION = 62

# Explicit urgency states for late-half and late-match soccer behavior.
URGENCY_NEUTRAL = "neutral_possession"
URGENCY_TRAILING_PUSH = "trailing_push"
URGENCY_DESPERATION = "desperation_push"
URGENCY_PROTECT_LEAD = "protect_lead"
URGENCY_CLOSING_HALF = "closing_half"

URGENCY_STATES = (
    URGENCY_NEUTRAL,
    URGENCY_TRAILING_PUSH,
    URGENCY_DESPERATION,
    URGENCY_PROTECT_LEAD,
    URGENCY_CLOSING_HALF,
)


def classify_urgency(*, half: int, seconds_remaining: int, score_differential: int) -> str:
    """Classify the possession owner's urgency state from match context.

    Desperation (keeper up, everything forward) takes precedence, then the
    trailing push, then lead protection (low block, time management), then
    the neutral close of the first half.
    """
    if half >= 2 and seconds_remaining <= 480 and -2 <= score_differential < 0:
        return URGENCY_DESPERATION
    if half >= 2 and seconds_remaining <= 1500 and score_differential < 0:
        return URGENCY_TRAILING_PUSH
    if half >= 2 and seconds_remaining <= 900 and score_differential > 0:
        return URGENCY_PROTECT_LEAD
    if half == 1 and seconds_remaining <= 120:
        return URGENCY_CLOSING_HALF
    return URGENCY_NEUTRAL


@dataclass(frozen=True)
class SituationContext:
    label: str
    defensive_third: bool
    final_third: bool
    penalty_box: bool
    shooting_range: bool
    set_piece: bool
    corner: bool
    trailing_push: bool
    protect_lead: bool
    urgency_state: str = URGENCY_NEUTRAL

    def to_dict(self) -> dict[str, bool | str]:
        return {
            "label": self.label,
            "defensive_third": self.defensive_third,
            "final_third": self.final_third,
            "penalty_box": self.penalty_box,
            "shooting_range": self.shooting_range,
            "set_piece": self.set_piece,
            "corner": self.corner,
            "trailing_push": self.trailing_push,
            "protect_lead": self.protect_lead,
            "urgency_state": self.urgency_state,
        }


def classify_situation(event_state: EventState) -> SituationContext:
    defensive_third = event_state.pitch_position <= 33
    final_third = event_state.pitch_position >= FINAL_THIRD_PITCH_POSITION
    penalty_box = event_state.pitch_position >= PENALTY_BOX_PITCH_POSITION
    shooting_range = event_state.pitch_position >= SHOOTING_RANGE_PITCH_POSITION
    set_piece = event_state.phase == "set_piece"
    corner = event_state.phase == "corner"
    urgency_state = classify_urgency(
        half=event_state.half,
        seconds_remaining=event_state.seconds_remaining,
        score_differential=event_state.score_differential,
    )
    trailing_push = urgency_state in {URGENCY_TRAILING_PUSH, URGENCY_DESPERATION}
    protect_lead = urgency_state == URGENCY_PROTECT_LEAD

    if corner:
        label = "Corner"
    elif set_piece and shooting_range:
        label = "Dangerous Set Piece"
    elif penalty_box:
        label = "Penalty Box"
    elif urgency_state == URGENCY_DESPERATION:
        label = "Desperation Push"
    elif protect_lead:
        label = "Protect Lead"
    elif final_third:
        label = "Final Third"
    elif defensive_third:
        label = "Build Out"
    else:
        label = "Neutral"

    return SituationContext(
        label=label,
        defensive_third=defensive_third,
        final_third=final_third,
        penalty_box=penalty_box,
        shooting_range=shooting_range,
        set_piece=set_piece,
        corner=corner,
        trailing_push=trailing_push,
        protect_lead=protect_lead,
        urgency_state=urgency_state,
    )


__all__ = [
    "FINAL_THIRD_PITCH_POSITION",
    "PENALTY_BOX_PITCH_POSITION",
    "SHOOTING_RANGE_PITCH_POSITION",
    "SituationContext",
    "URGENCY_CLOSING_HALF",
    "URGENCY_DESPERATION",
    "URGENCY_NEUTRAL",
    "URGENCY_PROTECT_LEAD",
    "URGENCY_STATES",
    "URGENCY_TRAILING_PUSH",
    "classify_situation",
    "classify_urgency",
]
