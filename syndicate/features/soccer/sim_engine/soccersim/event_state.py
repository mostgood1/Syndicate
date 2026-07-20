from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace

from syndicate.features.soccer.sim_engine.soccersim.contracts import PossessionState
from syndicate.features.soccer.sim_engine.soccersim.situation_model import SituationContext
from syndicate.features.soccer.sim_engine.soccersim.situation_model import classify_situation


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


def _score_differential(state: PossessionState, possession_team: str) -> int:
    if possession_team == state.home_team:
        return state.score_home - state.score_away
    return state.score_away - state.score_home


@dataclass(frozen=True)
class EventState:
    possession_team: str
    pitch_position: int
    phase: str
    half: int
    seconds_remaining: int
    score_differential: int
    defensive_third: bool = False
    final_third: bool = False
    penalty_box: bool = False
    shooting_range: bool = False
    set_piece: bool = False
    corner: bool = False
    trailing_push: bool = False
    protect_lead: bool = False
    situation_label: str = "Neutral"
    urgency_state: str = "neutral_possession"
    event_index: int = 0
    possession_index: int = 0

    def to_dict(self) -> dict[str, int | str | bool]:
        return {
            "possession_team": self.possession_team,
            "pitch_position": self.pitch_position,
            "phase": self.phase,
            "half": self.half,
            "seconds_remaining": self.seconds_remaining,
            "score_differential": self.score_differential,
            "defensive_third": self.defensive_third,
            "final_third": self.final_third,
            "penalty_box": self.penalty_box,
            "shooting_range": self.shooting_range,
            "set_piece": self.set_piece,
            "corner": self.corner,
            "trailing_push": self.trailing_push,
            "protect_lead": self.protect_lead,
            "situation_label": self.situation_label,
            "urgency_state": self.urgency_state,
            "event_index": self.event_index,
            "possession_index": self.possession_index,
        }

    @property
    def distance_to_goal(self) -> int:
        return max(0, 100 - self.pitch_position)


def build_event_state_from_possession_state(state: PossessionState) -> EventState:
    possession_team = state.home_team if state.possession_owner == "home" else state.away_team
    event_state = EventState(
        possession_team=possession_team,
        pitch_position=_clamp(state.pitch_position, 1, 99),
        phase=state.phase,
        half=max(1, int(state.half)),
        seconds_remaining=max(0, int(state.clock_remaining)),
        score_differential=_score_differential(state, possession_team),
        possession_index=max(0, int(state.possession_index)),
    )
    return apply_situation_context(event_state, classify_situation(event_state))


def advance_pitch_position(state: EventState, progress: int) -> EventState:
    return replace(state, pitch_position=_clamp(state.pitch_position + int(progress), 1, 99))


def advance_event_clock(state: EventState, seconds: int) -> EventState:
    return replace(state, seconds_remaining=max(0, state.seconds_remaining - max(0, int(seconds))))


def apply_situation_context(state: EventState, context: SituationContext) -> EventState:
    return replace(
        state,
        defensive_third=context.defensive_third,
        final_third=context.final_third,
        penalty_box=context.penalty_box,
        shooting_range=context.shooting_range,
        set_piece=context.set_piece,
        corner=context.corner,
        trailing_push=context.trailing_push,
        protect_lead=context.protect_lead,
        situation_label=context.label,
        urgency_state=context.urgency_state,
    )


def advance_event_state(
    state: EventState,
    *,
    pitch_progress: int,
    clock_consumed: int,
    phase: str | None = None,
) -> EventState:
    updated = advance_pitch_position(state, pitch_progress)
    updated = advance_event_clock(updated, clock_consumed)
    if phase is not None:
        updated = replace(updated, phase=phase)
    updated = replace(updated, event_index=state.event_index + 1)
    return apply_situation_context(updated, classify_situation(updated))


def reset_for_next_possession(state: EventState, *, possession_team: str, pitch_position: int) -> EventState:
    return replace(
        state,
        possession_team=possession_team,
        pitch_position=_clamp(pitch_position, 1, 99),
        phase="open_play",
        event_index=0,
    )


__all__ = [
    "EventState",
    "advance_event_clock",
    "advance_event_state",
    "advance_pitch_position",
    "apply_situation_context",
    "build_event_state_from_possession_state",
    "reset_for_next_possession",
]
