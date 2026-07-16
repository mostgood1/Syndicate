from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace

from syndicate.features.football.sim_engine.smartsim2.contracts import PossessionState
from syndicate.features.football.sim_engine.smartsim2.situation_model import SituationContext
from syndicate.features.football.sim_engine.smartsim2.situation_model import classify_situation


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


def _score_differential(state: PossessionState, possession_team: str) -> int:
    if possession_team == state.home_team:
        return state.score_home - state.score_away
    return state.score_away - state.score_home


@dataclass(frozen=True)
class PlayState:
    possession_team: str
    down: int
    distance: int
    yardline: int
    quarter: int
    seconds_remaining: int
    score_differential: int
    red_zone: bool = False
    goal_to_go: bool = False
    backed_up_territory: bool = False
    field_goal_range: bool = False
    four_minute_offense: bool = False
    two_minute_drill: bool = False
    long_yardage: bool = False
    situation_label: str = "Neutral"
    urgency_state: str = "neutral_offense"
    play_index: int = 0
    drive_index: int = 0
    possession_index: int = 0

    def to_dict(self) -> dict[str, int | str]:
        return {
            "possession_team": self.possession_team,
            "down": self.down,
            "distance": self.distance,
            "yardline": self.yardline,
            "quarter": self.quarter,
            "seconds_remaining": self.seconds_remaining,
            "score_differential": self.score_differential,
            "red_zone": self.red_zone,
            "goal_to_go": self.goal_to_go,
            "backed_up_territory": self.backed_up_territory,
            "field_goal_range": self.field_goal_range,
            "four_minute_offense": self.four_minute_offense,
            "two_minute_drill": self.two_minute_drill,
            "long_yardage": self.long_yardage,
            "situation_label": self.situation_label,
            "urgency_state": self.urgency_state,
            "play_index": self.play_index,
            "drive_index": self.drive_index,
            "possession_index": self.possession_index,
        }

    @property
    def yards_to_goal(self) -> int:
        return max(0, 100 - self.yardline)


def build_play_state_from_possession_state(state: PossessionState) -> PlayState:
    possession_team = state.home_team if state.possession_owner == "home" else state.away_team
    distance = max(1, int(state.distance))
    if state.field_position >= 95:
        distance += 100 - _clamp(state.field_position, 1, 100)
    play_state = PlayState(
        possession_team=possession_team,
        down=_clamp(state.down, 1, 4),
        distance=distance,
        yardline=_clamp(state.field_position, 1, 100),
        quarter=max(1, int(state.quarter)),
        seconds_remaining=max(0, int(state.clock_remaining)),
        score_differential=_score_differential(state, possession_team),
        drive_index=max(0, int(state.drive_index)),
        possession_index=max(0, int(state.possession_index)),
    )
    return apply_situation_context(play_state, classify_situation(play_state))


def advance_field_position(state: PlayState, yards_gained: int) -> PlayState:
    return replace(state, yardline=_clamp(state.yardline + int(yards_gained), 1, 100))


def advance_down_and_distance(state: PlayState, *, yards_gained: int, repeat_down: bool = False) -> PlayState:
    gained = int(yards_gained)
    if gained >= state.distance or state.yardline >= 100:
        return replace(state, down=1, distance=10)
    if repeat_down:
        remaining = max(1, state.distance - gained)
        return replace(state, distance=remaining)
    if state.down >= 4:
        return replace(state, down=4, distance=max(1, state.distance - gained))
    remaining = max(1, state.distance - gained)
    return replace(state, down=min(4, state.down + 1), distance=remaining)


def advance_play_clock(state: PlayState, seconds: int) -> PlayState:
    return replace(state, seconds_remaining=max(0, state.seconds_remaining - max(0, int(seconds))))


def apply_situation_context(state: PlayState, context: SituationContext) -> PlayState:
    return replace(
        state,
        red_zone=context.red_zone,
        goal_to_go=context.goal_to_go,
        backed_up_territory=context.backed_up_territory,
        field_goal_range=context.field_goal_range,
        four_minute_offense=context.four_minute_offense,
        two_minute_drill=context.two_minute_drill,
        long_yardage=context.long_yardage,
        situation_label=context.label,
        urgency_state=context.urgency_state,
    )


def advance_play_state(
    state: PlayState,
    *,
    yards_gained: int,
    clock_consumed: int,
    repeat_down: bool = False,
) -> PlayState:
    updated = advance_field_position(state, yards_gained)
    updated = advance_down_and_distance(updated, yards_gained=yards_gained, repeat_down=repeat_down)
    updated = advance_play_clock(updated, clock_consumed)
    updated = replace(updated, play_index=state.play_index + 1)
    return apply_situation_context(updated, classify_situation(updated))


def reset_for_next_possession(state: PlayState, *, possession_team: str, yardline: int) -> PlayState:
    return replace(
        state,
        possession_team=possession_team,
        down=1,
        distance=10,
        yardline=_clamp(yardline, 1, 99),
        play_index=0,
    )


__all__ = [
    "PlayState",
    "advance_down_and_distance",
    "advance_field_position",
    "advance_play_clock",
    "advance_play_state",
    "apply_situation_context",
    "build_play_state_from_possession_state",
    "reset_for_next_possession",
]