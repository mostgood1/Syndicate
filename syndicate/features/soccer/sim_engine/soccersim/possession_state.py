from __future__ import annotations

from dataclasses import replace

from syndicate.features.soccer.sim_engine.soccersim.contracts import PossessionState

PHASE_OPEN_PLAY = "open_play"
PHASE_KICKOFF = "kickoff"
PHASE_SET_PIECE = "set_piece"
PHASE_CORNER = "corner"
PHASE_GOAL_KICK = "goal_kick"

PHASES = (PHASE_OPEN_PLAY, PHASE_KICKOFF, PHASE_SET_PIECE, PHASE_CORNER, PHASE_GOAL_KICK)


def build_initial_possession_state(
    *,
    home_team: str,
    away_team: str,
    owner: str = "home",
    pitch_position: int = 50,
    phase: str = PHASE_KICKOFF,
    half: int = 1,
    clock_remaining: int = 2700,
    score_home: int = 0,
    score_away: int = 0,
    possession_index: int = 0,
) -> PossessionState:
    return PossessionState(
        possession_owner=str(owner or "home").strip().lower() or "home",
        pitch_position=max(1, min(99, int(pitch_position))),
        phase=str(phase or PHASE_OPEN_PLAY).strip().lower() or PHASE_OPEN_PLAY,
        half=max(1, int(half)),
        clock_remaining=max(0, int(clock_remaining)),
        score_home=max(0, int(score_home)),
        score_away=max(0, int(score_away)),
        home_team=str(home_team or "HOME").strip() or "HOME",
        away_team=str(away_team or "AWAY").strip() or "AWAY",
        possession_index=max(0, int(possession_index)),
    )


def advance_possession_clock(state: PossessionState, seconds: int) -> PossessionState:
    return replace(state, clock_remaining=max(0, state.clock_remaining - max(0, int(seconds))))


def move_pitch_position(state: PossessionState, progress: int) -> PossessionState:
    return replace(state, pitch_position=max(1, min(99, state.pitch_position + int(progress))))


def mirror_pitch_position(pitch_position: int) -> int:
    """Translate a pitch position into the opponent's frame of reference."""
    return max(1, min(99, 100 - int(pitch_position)))


def reset_for_next_possession(
    state: PossessionState,
    *,
    owner: str,
    pitch_position: int = 50,
    phase: str = PHASE_OPEN_PLAY,
) -> PossessionState:
    return replace(
        state,
        possession_owner=str(owner or state.possession_owner).strip().lower() or state.possession_owner,
        pitch_position=max(1, min(99, int(pitch_position))),
        phase=str(phase or PHASE_OPEN_PLAY).strip().lower() or PHASE_OPEN_PLAY,
        possession_index=state.possession_index + 1,
    )


def advance_half(state: PossessionState, *, half_seconds: int = 2700) -> PossessionState:
    kickoff_owner = "away" if state.half == 1 else "home"
    return replace(
        state,
        half=state.half + 1,
        clock_remaining=max(0, int(half_seconds)),
        possession_owner=kickoff_owner,
        pitch_position=50,
        phase=PHASE_KICKOFF,
    )


def possession_owner_to_team(state: PossessionState) -> str:
    return state.home_team if state.possession_owner == "home" else state.away_team


__all__ = [
    "PHASES",
    "PHASE_CORNER",
    "PHASE_GOAL_KICK",
    "PHASE_KICKOFF",
    "PHASE_OPEN_PLAY",
    "PHASE_SET_PIECE",
    "advance_half",
    "advance_possession_clock",
    "build_initial_possession_state",
    "mirror_pitch_position",
    "move_pitch_position",
    "possession_owner_to_team",
    "reset_for_next_possession",
]
