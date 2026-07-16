from __future__ import annotations

from dataclasses import replace

from syndicate.features.football.sim_engine.smartsim2.contracts import PossessionState


def build_initial_possession_state(
    *,
    home_team: str,
    away_team: str,
    owner: str = "home",
    field_position: int = 25,
    down: int = 1,
    distance: int = 10,
    quarter: int = 1,
    clock_remaining: int = 900,
    score_home: int = 0,
    score_away: int = 0,
    drive_index: int = 0,
    possession_index: int = 0,
) -> PossessionState:
    return PossessionState(
        possession_owner=str(owner or "home").strip().lower() or "home",
        field_position=max(1, min(99, int(field_position))),
        down=max(1, min(4, int(down))),
        distance=max(1, int(distance)),
        quarter=max(1, int(quarter)),
        clock_remaining=max(0, int(clock_remaining)),
        score_home=max(0, int(score_home)),
        score_away=max(0, int(score_away)),
        home_team=str(home_team or "HOME").strip() or "HOME",
        away_team=str(away_team or "AWAY").strip() or "AWAY",
        drive_index=max(0, int(drive_index)),
        possession_index=max(0, int(possession_index)),
    )


def advance_possession_clock(state: PossessionState, seconds: int) -> PossessionState:
    return replace(state, clock_remaining=max(0, state.clock_remaining - max(0, int(seconds))))


def move_field_position(state: PossessionState, yards: int) -> PossessionState:
    return replace(state, field_position=max(1, min(99, state.field_position + int(yards))))


def reset_for_next_possession(state: PossessionState, *, owner: str, field_position: int = 25) -> PossessionState:
    return replace(
        state,
        possession_owner=str(owner or state.possession_owner).strip().lower() or state.possession_owner,
        field_position=max(1, min(99, int(field_position))),
        down=1,
        distance=10,
        drive_index=state.drive_index + 1,
        possession_index=state.possession_index + 1,
    )


def advance_quarter(state: PossessionState, *, quarter_seconds: int = 900) -> PossessionState:
    return replace(state, quarter=state.quarter + 1, clock_remaining=max(0, int(quarter_seconds)))


def possession_owner_to_team(state: PossessionState) -> str:
    return state.home_team if state.possession_owner == "home" else state.away_team
