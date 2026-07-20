from __future__ import annotations

from dataclasses import replace
from random import Random

from syndicate.features.soccer.sim_engine.soccersim.calibration_profile import CalibrationProfile
from syndicate.features.soccer.sim_engine.soccersim.calibration_profile import SOCCER_CALIBRATION_PROFILE
from syndicate.features.soccer.sim_engine.soccersim.contracts import PossessionOutcome
from syndicate.features.soccer.sim_engine.soccersim.contracts import PossessionResult
from syndicate.features.soccer.sim_engine.soccersim.contracts import PossessionState
from syndicate.features.soccer.sim_engine.soccersim.contracts import PossessionStepResult
from syndicate.features.soccer.sim_engine.soccersim.contracts import SoccerSimSimulationInput
from syndicate.features.soccer.sim_engine.soccersim.event_outcomes import EventOutcome
from syndicate.features.soccer.sim_engine.soccersim.event_simulator import simulate_event
from syndicate.features.soccer.sim_engine.soccersim.event_state import build_event_state_from_possession_state
from syndicate.features.soccer.sim_engine.soccersim.possession_priors import build_possession_priors
from syndicate.features.soccer.sim_engine.soccersim.situation_model import FINAL_THIRD_PITCH_POSITION
from syndicate.features.soccer.sim_engine.soccersim.situation_model import PENALTY_BOX_PITCH_POSITION

_TERMINAL_POSSESSION_CHANGE_OUTCOMES = {
    PossessionOutcome.GOAL,
    PossessionOutcome.PENALTY_GOAL,
    PossessionOutcome.PENALTY_MISSED,
    PossessionOutcome.SHOT_SAVED,
    PossessionOutcome.SHOT_OFF_TARGET,
    PossessionOutcome.SHOT_BLOCKED,
    PossessionOutcome.TURNOVER,
    PossessionOutcome.OFFSIDE,
}

_SHOT_OUTCOMES = {
    PossessionOutcome.GOAL,
    PossessionOutcome.PENALTY_GOAL,
    PossessionOutcome.PENALTY_MISSED,
    PossessionOutcome.SHOT_SAVED,
    PossessionOutcome.SHOT_OFF_TARGET,
    PossessionOutcome.SHOT_BLOCKED,
}

_ON_TARGET_OUTCOMES = {
    PossessionOutcome.GOAL,
    PossessionOutcome.PENALTY_GOAL,
    PossessionOutcome.SHOT_SAVED,
}


def _end_of_clock_outcome(state: PossessionState) -> PossessionOutcome:
    # Odd halves (1, and 3 in extra time) end a period; even halves end the match
    # (or send it to extra time / penalties at the match-simulator layer).
    if state.half % 2 == 1:
        return PossessionOutcome.END_OF_HALF_STOP
    return PossessionOutcome.END_OF_MATCH_STOP


def simulate_possession(
    possession_state: PossessionState,
    simulation_input: SoccerSimSimulationInput,
    *,
    rng: Random | None = None,
    profile: CalibrationProfile = SOCCER_CALIBRATION_PROFILE,
) -> PossessionResult:
    rng = rng or Random(simulation_input.seed)
    state = possession_state
    priors = build_possession_priors(simulation_input, possession_state=state, profile=profile)
    event_state = build_event_state_from_possession_state(state)
    steps: list[PossessionStepResult] = []
    total_progress = 0
    total_clock = 0
    goals_scored = 0
    corner_count = 0
    shot_taken = False
    shot_on_target = False
    reached_final_third = state.pitch_position >= FINAL_THIRD_PITCH_POSITION
    reached_penalty_box = state.pitch_position >= PENALTY_BOX_PITCH_POSITION
    possession_change = False
    terminal_outcome: PossessionOutcome | None = None
    max_events = max(3, int(round(priors.expected_event_count * 2.2)) + 3)

    for _ in range(max_events):
        if state.clock_remaining <= 0:
            terminal_outcome = _end_of_clock_outcome(state)
            break

        event_result = simulate_event(event_state, state, simulation_input, priors=priors, rng=rng, profile=profile)
        terminal_outcome = event_result.terminal_possession_outcome
        if terminal_outcome is not None:
            step_outcome = terminal_outcome
        elif event_result.outcome == EventOutcome.SHOT:
            # Non-terminal shot: blocked behind for a corner, possession retained.
            step_outcome = PossessionOutcome.CORNER_WON
        else:
            step_outcome = PossessionOutcome(event_result.outcome.value)
        play_step = PossessionStepResult(
            step_index=len(steps) + 1,
            start_state=state,
            end_state=event_result.end_possession_state,
            outcome=step_outcome,
            pitch_progress=event_result.pitch_progress,
            clock_consumed=event_result.clock_consumed,
            goals_scored=event_result.goals_scored,
            summary=event_result.summary,
        )
        steps.append(play_step)
        total_progress += event_result.pitch_progress
        total_clock += event_result.clock_consumed
        goals_scored += event_result.goals_scored
        state = event_result.end_possession_state
        event_state = event_result.end_state
        if step_outcome == PossessionOutcome.CORNER_WON or state.phase == "corner":
            corner_count = corner_count + 1 if step_outcome == PossessionOutcome.CORNER_WON else corner_count
        if state.pitch_position >= FINAL_THIRD_PITCH_POSITION and state.possession_owner == possession_state.possession_owner:
            reached_final_third = True
        if state.pitch_position >= PENALTY_BOX_PITCH_POSITION and state.possession_owner == possession_state.possession_owner:
            reached_penalty_box = True

        if terminal_outcome is not None:
            if terminal_outcome in _SHOT_OUTCOMES:
                shot_taken = True
                shot_on_target = terminal_outcome in _ON_TARGET_OUTCOMES
            possession_change = terminal_outcome in _TERMINAL_POSSESSION_CHANGE_OUTCOMES
            break

    if terminal_outcome is None:
        if state.clock_remaining <= 0:
            terminal_outcome = _end_of_clock_outcome(state)
            state = replace(state, clock_remaining=0)
        else:
            # Event cap reached without a terminal event: the move breaks down.
            terminal_outcome = PossessionOutcome.TURNOVER
            possession_change = True
            state = replace(
                state,
                possession_owner="away" if state.possession_owner == "home" else "home",
                pitch_position=max(1, min(99, 100 - state.pitch_position)),
                phase="open_play",
                possession_index=state.possession_index + 1,
            )

    return PossessionResult(
        possession_index=possession_state.possession_index,
        start_state=possession_state,
        end_state=state,
        outcome=terminal_outcome,
        goals_scored=goals_scored,
        pitch_progress=total_progress,
        clock_consumed=total_clock,
        event_count=len(steps),
        shot_taken=shot_taken,
        shot_on_target=shot_on_target,
        corner_count=corner_count,
        reached_final_third=reached_final_third,
        reached_penalty_box=reached_penalty_box,
        possession_change=possession_change,
        next_possession_owner=state.possession_owner,
        steps=tuple(steps),
    )


__all__ = ["simulate_possession"]
