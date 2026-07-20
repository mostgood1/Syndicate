from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from random import Random

from syndicate.features.soccer.sim_engine.soccersim.calibration_profile import CalibrationProfile
from syndicate.features.soccer.sim_engine.soccersim.calibration_profile import SOCCER_CALIBRATION_PROFILE
from syndicate.features.soccer.sim_engine.soccersim.contracts import PossessionOutcome
from syndicate.features.soccer.sim_engine.soccersim.contracts import PossessionState
from syndicate.features.soccer.sim_engine.soccersim.contracts import SoccerSimSimulationInput
from syndicate.features.soccer.sim_engine.soccersim.event_outcomes import EventOutcome
from syndicate.features.soccer.sim_engine.soccersim.event_state import EventState
from syndicate.features.soccer.sim_engine.soccersim.event_state import advance_event_state
from syndicate.features.soccer.sim_engine.soccersim.event_state import apply_situation_context
from syndicate.features.soccer.sim_engine.soccersim.possession_priors import PossessionPriorProfile
from syndicate.features.soccer.sim_engine.soccersim.possession_state import PHASE_CORNER
from syndicate.features.soccer.sim_engine.soccersim.possession_state import PHASE_KICKOFF
from syndicate.features.soccer.sim_engine.soccersim.possession_state import PHASE_OPEN_PLAY
from syndicate.features.soccer.sim_engine.soccersim.possession_state import PHASE_SET_PIECE
from syndicate.features.soccer.sim_engine.soccersim.possession_state import mirror_pitch_position
from syndicate.features.soccer.sim_engine.soccersim.situation_model import classify_situation


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _weighted_choice(rng: Random, weights: dict[EventOutcome, float]) -> EventOutcome:
    roll = rng.random()
    cursor = 0.0
    for outcome, weight in weights.items():
        cursor += weight
        if roll <= cursor:
            return outcome
    return next(reversed(weights))


def _attacking_team_name(state: PossessionState) -> str:
    return state.home_team if state.possession_owner == "home" else state.away_team


def _next_possession_owner(state: PossessionState) -> str:
    return "away" if state.possession_owner == "home" else "home"


def _score_for_team(state: PossessionState, possession_owner: str, goals: int) -> tuple[int, int]:
    if possession_owner == "home":
        return state.score_home + goals, state.score_away
    return state.score_home, state.score_away + goals


def _refresh_situation(event_state: EventState) -> EventState:
    return apply_situation_context(event_state, classify_situation(event_state))


def _event_outcome_weights(
    event_state: EventState,
    priors: PossessionPriorProfile,
    profile: CalibrationProfile = SOCCER_CALIBRATION_PROFILE,
) -> dict[EventOutcome, float]:
    retention = priors.possession_retention_probability
    field_factor = _clamp((event_state.pitch_position - 30) / 70.0, 0.0, 1.0)
    final_third = 1.0 if event_state.final_third else 0.0
    penalty_box = 1.0 if event_state.penalty_box else 0.0
    corner_phase = 1.0 if event_state.corner else 0.0
    dangerous_set_piece = 1.0 if event_state.set_piece and event_state.shooting_range else 0.0

    advance = 0.34 + retention * 0.30
    if event_state.final_third:
        advance *= profile.final_third_stiffening
    if event_state.penalty_box:
        advance *= profile.box_entry_stiffening

    retain = 0.14 + (priors.possession_share_index - 0.5) * 0.20
    turnover = (1.0 - retention) * 0.62 * profile.turnover_multiplier
    if event_state.defensive_third:
        turnover += 0.03

    fast_break = priors.fast_break_probability * profile.fast_break_multiplier
    if event_state.pitch_position > 60:
        fast_break *= 0.30

    foul_won = priors.foul_won_probability
    if event_state.penalty_box:
        # Defenders foul far less readily inside their own box.
        foul_won *= 0.35
    offside = priors.offside_probability * (0.5 + final_third * 1.2)
    corner_won = (
        priors.corner_probability * (0.4 + final_third * 1.3) * profile.corner_frequency_multiplier
        if event_state.pitch_position >= 50
        else 0.0
    )

    shot = 0.0
    if event_state.shooting_range:
        shot = priors.shot_generation_probability * (
            0.65 + penalty_box * 0.95 + corner_phase * 0.82 + dangerous_set_piece * profile.set_piece_shot_bonus
        )
        if event_state.trailing_push:
            shot *= 1.0 + 0.18 * profile.trailing_push_aggression
        if event_state.protect_lead:
            shot *= 0.85
        if event_state.half >= 2:
            # Fatigue, substitutions, and game-state chasing open matches up
            # after the break.
            shot *= profile.second_half_shot_multiplier
        shot *= profile.shot_frequency_multiplier

    if event_state.protect_lead:
        # Lead protection: recycle possession, keep the ball in the corner,
        # slow the match down instead of forcing play forward.
        retain *= 1.55 * profile.protect_lead_defensiveness
        advance *= 0.85
    if event_state.urgency_state == "desperation_push":
        # Everything forward: more direct play, more giveaways.
        advance *= 1.10
        turnover *= 1.15
        retain *= 0.60

    weights = {
        EventOutcome.ADVANCE: max(0.01, advance),
        EventOutcome.FAST_BREAK: max(0.001, fast_break),
        EventOutcome.RETAIN: max(0.01, retain),
        EventOutcome.TURNOVER: max(0.01, turnover),
        EventOutcome.FOUL_WON: max(0.005, foul_won),
        EventOutcome.OFFSIDE: max(0.001, offside),
    }
    if corner_won > 0.0:
        weights[EventOutcome.CORNER_WON] = max(0.001, corner_won)
    if shot > 0.0:
        weights[EventOutcome.SHOT] = max(0.01, shot)
    total = sum(weights.values())
    return {key: value / total for key, value in weights.items()}


def _goal_probability(
    event_state: EventState,
    priors: PossessionPriorProfile,
    profile: CalibrationProfile = SOCCER_CALIBRATION_PROFILE,
) -> float:
    if event_state.corner:
        base = profile.corner_shot_conversion_base * profile.corner_goal_multiplier
    elif event_state.penalty_box:
        base = profile.box_shot_conversion_base
    else:
        base = profile.outside_box_conversion_base
    team_factor = 1.0 + (priors.attack_index - 0.5) * 0.50 - (priors.defense_index - 0.5) * 0.35
    return _clamp(base * team_factor * profile.goal_conversion_multiplier, 0.01, 0.50)


def _clock_consumed(
    event_state: EventState,
    priors: PossessionPriorProfile,
    rng: Random,
    *,
    profile: CalibrationProfile,
    extra_seconds: float = 0.0,
) -> int:
    base = priors.pace_seconds_per_event * profile.possession_tempo_multiplier
    if event_state.protect_lead:
        base *= 1.30 * profile.protect_lead_defensiveness
    elif event_state.trailing_push:
        base *= 0.85
    seconds = rng.normalvariate(base + extra_seconds, 4.0)
    return max(3, int(round(seconds)))


@dataclass(frozen=True)
class EventResult:
    step_index: int
    start_state: EventState
    end_state: EventState
    end_possession_state: PossessionState
    outcome: EventOutcome
    pitch_progress: int
    clock_consumed: int
    goals_scored: int = 0
    terminal_possession_outcome: PossessionOutcome | None = None
    summary: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "step_index": self.step_index,
            "start_state": self.start_state.to_dict(),
            "end_state": self.end_state.to_dict(),
            "end_possession_state": self.end_possession_state.to_dict(),
            "outcome": self.outcome.value,
            "pitch_progress": self.pitch_progress,
            "clock_consumed": self.clock_consumed,
            "goals_scored": self.goals_scored,
            "terminal_possession_outcome": self.terminal_possession_outcome.value if self.terminal_possession_outcome is not None else None,
            "summary": self.summary,
        }


def _goal_result(state: PossessionState, clock_consumed: int, *, goals: int = 1) -> PossessionState:
    score_home, score_away = _score_for_team(state, state.possession_owner, goals)
    return replace(
        state,
        score_home=score_home,
        score_away=score_away,
        pitch_position=50,
        phase=PHASE_KICKOFF,
        clock_remaining=max(0, state.clock_remaining - clock_consumed),
        possession_owner=_next_possession_owner(state),
        possession_index=state.possession_index + 1,
    )


def _possession_change_result(
    state: PossessionState,
    clock_consumed: int,
    *,
    next_position: int,
    phase: str = PHASE_OPEN_PLAY,
) -> PossessionState:
    return replace(
        state,
        pitch_position=max(1, min(99, int(next_position))),
        phase=phase,
        clock_remaining=max(0, state.clock_remaining - clock_consumed),
        possession_owner=_next_possession_owner(state),
        possession_index=state.possession_index + 1,
    )


def _continue_result(
    state: PossessionState,
    clock_consumed: int,
    *,
    pitch_position: int,
    phase: str = PHASE_OPEN_PLAY,
) -> PossessionState:
    return replace(
        state,
        pitch_position=max(1, min(99, int(pitch_position))),
        phase=phase,
        clock_remaining=max(0, state.clock_remaining - clock_consumed),
    )


def _build_event_result(
    *,
    event_state: EventState,
    possession_state: PossessionState,
    outcome: EventOutcome,
    end_possession_state: PossessionState,
    pitch_progress: int,
    clock_consumed: int,
    phase: str | None,
    goals_scored: int = 0,
    terminal_possession_outcome: PossessionOutcome | None = None,
    summary: str = "",
) -> EventResult:
    end_event_state = _refresh_situation(
        advance_event_state(event_state, pitch_progress=pitch_progress, clock_consumed=clock_consumed, phase=phase)
    )
    if goals_scored:
        end_event_state = replace(end_event_state, score_differential=event_state.score_differential + goals_scored)
        end_event_state = _refresh_situation(end_event_state)
    return EventResult(
        step_index=event_state.event_index + 1,
        start_state=event_state,
        end_state=end_event_state,
        end_possession_state=end_possession_state,
        outcome=outcome,
        pitch_progress=pitch_progress,
        clock_consumed=clock_consumed,
        goals_scored=goals_scored,
        terminal_possession_outcome=terminal_possession_outcome,
        summary=summary,
    )


def _resolve_shot(
    event_state: EventState,
    possession_state: PossessionState,
    priors: PossessionPriorProfile,
    rng: Random,
    profile: CalibrationProfile,
    clock_consumed: int,
) -> EventResult:
    team = _attacking_team_name(possession_state)
    goal_probability = _goal_probability(event_state, priors, profile)
    on_target_probability = _clamp(
        priors.shot_on_target_probability * profile.shot_on_target_multiplier,
        goal_probability,
        0.60,
    )
    roll = rng.random()
    if roll < goal_probability:
        end_possession_state = _goal_result(possession_state, clock_consumed + 30)
        return _build_event_result(
            event_state=event_state,
            possession_state=possession_state,
            outcome=EventOutcome.SHOT,
            end_possession_state=end_possession_state,
            pitch_progress=0,
            clock_consumed=clock_consumed + 30,
            phase=PHASE_KICKOFF,
            goals_scored=1,
            terminal_possession_outcome=PossessionOutcome.GOAL,
            summary=f"{team} scored",
        )
    if roll < on_target_probability:
        next_position = max(2, min(35, int(round(rng.normalvariate(12.0, 6.0)))))
        end_possession_state = _possession_change_result(possession_state, clock_consumed, next_position=next_position)
        return _build_event_result(
            event_state=event_state,
            possession_state=possession_state,
            outcome=EventOutcome.SHOT,
            end_possession_state=end_possession_state,
            pitch_progress=0,
            clock_consumed=clock_consumed,
            phase=PHASE_OPEN_PLAY,
            terminal_possession_outcome=PossessionOutcome.SHOT_SAVED,
            summary=f"{team} shot was saved",
        )
    if rng.random() < 0.27:
        if rng.random() < 0.35:
            end_possession_state = _continue_result(possession_state, clock_consumed + 15, pitch_position=96, phase=PHASE_CORNER)
            return _build_event_result(
                event_state=event_state,
                possession_state=possession_state,
                outcome=EventOutcome.SHOT,
                end_possession_state=end_possession_state,
                pitch_progress=max(0, 96 - event_state.pitch_position),
                clock_consumed=clock_consumed + 15,
                phase=PHASE_CORNER,
                terminal_possession_outcome=None,
                summary=f"{team} shot was blocked out for a corner",
            )
        next_position = mirror_pitch_position(possession_state.pitch_position + int(round(rng.normalvariate(0.0, 5.0))))
        end_possession_state = _possession_change_result(possession_state, clock_consumed, next_position=next_position)
        return _build_event_result(
            event_state=event_state,
            possession_state=possession_state,
            outcome=EventOutcome.SHOT,
            end_possession_state=end_possession_state,
            pitch_progress=0,
            clock_consumed=clock_consumed,
            phase=PHASE_OPEN_PLAY,
            terminal_possession_outcome=PossessionOutcome.SHOT_BLOCKED,
            summary=f"{team} shot was blocked",
        )
    next_position = max(3, min(20, int(round(rng.normalvariate(9.0, 3.0)))))
    end_possession_state = _possession_change_result(possession_state, clock_consumed + 10, next_position=next_position)
    return _build_event_result(
        event_state=event_state,
        possession_state=possession_state,
        outcome=EventOutcome.SHOT,
        end_possession_state=end_possession_state,
        pitch_progress=0,
        clock_consumed=clock_consumed + 10,
        phase=PHASE_OPEN_PLAY,
        terminal_possession_outcome=PossessionOutcome.SHOT_OFF_TARGET,
        summary=f"{team} shot missed the target",
    )


def _resolve_penalty(
    event_state: EventState,
    possession_state: PossessionState,
    rng: Random,
    profile: CalibrationProfile,
    clock_consumed: int,
) -> EventResult:
    team = _attacking_team_name(possession_state)
    if rng.random() < profile.penalty_conversion:
        end_possession_state = _goal_result(possession_state, clock_consumed + 60)
        return _build_event_result(
            event_state=event_state,
            possession_state=possession_state,
            outcome=EventOutcome.FOUL_WON,
            end_possession_state=end_possession_state,
            pitch_progress=0,
            clock_consumed=clock_consumed + 60,
            phase=PHASE_KICKOFF,
            goals_scored=1,
            terminal_possession_outcome=PossessionOutcome.PENALTY_GOAL,
            summary=f"{team} converted a penalty",
        )
    next_position = max(2, min(20, int(round(rng.normalvariate(8.0, 3.0)))))
    end_possession_state = _possession_change_result(possession_state, clock_consumed + 50, next_position=next_position)
    return _build_event_result(
        event_state=event_state,
        possession_state=possession_state,
        outcome=EventOutcome.FOUL_WON,
        end_possession_state=end_possession_state,
        pitch_progress=0,
        clock_consumed=clock_consumed + 50,
        phase=PHASE_OPEN_PLAY,
        terminal_possession_outcome=PossessionOutcome.PENALTY_MISSED,
        summary=f"{team} missed a penalty",
    )


def simulate_event(
    event_state: EventState,
    possession_state: PossessionState,
    simulation_input: SoccerSimSimulationInput,
    *,
    priors: PossessionPriorProfile,
    rng: Random,
    profile: CalibrationProfile = SOCCER_CALIBRATION_PROFILE,
) -> EventResult:
    event_state = _refresh_situation(event_state)
    weights = _event_outcome_weights(event_state, priors, profile)
    outcome = _weighted_choice(rng, weights)
    team = _attacking_team_name(possession_state)

    if outcome == EventOutcome.SHOT:
        clock_consumed = _clock_consumed(event_state, priors, rng, profile=profile)
        return _resolve_shot(event_state, possession_state, priors, rng, profile, clock_consumed)

    if outcome == EventOutcome.FOUL_WON:
        clock_consumed = _clock_consumed(event_state, priors, rng, profile=profile, extra_seconds=18.0)
        if event_state.penalty_box and rng.random() < profile.penalty_award_probability:
            return _resolve_penalty(event_state, possession_state, rng, profile, clock_consumed)
        pitch_progress = max(0, int(round(rng.normalvariate(5.0, 3.0))))
        end_possession_state = _continue_result(
            possession_state,
            clock_consumed,
            pitch_position=possession_state.pitch_position + pitch_progress,
            phase=PHASE_SET_PIECE,
        )
        return _build_event_result(
            event_state=event_state,
            possession_state=possession_state,
            outcome=outcome,
            end_possession_state=end_possession_state,
            pitch_progress=pitch_progress,
            clock_consumed=clock_consumed,
            phase=PHASE_SET_PIECE,
            summary=f"{team} won a free kick",
        )

    if outcome == EventOutcome.CORNER_WON:
        clock_consumed = _clock_consumed(event_state, priors, rng, profile=profile, extra_seconds=15.0)
        end_possession_state = _continue_result(possession_state, clock_consumed, pitch_position=96, phase=PHASE_CORNER)
        return _build_event_result(
            event_state=event_state,
            possession_state=possession_state,
            outcome=outcome,
            end_possession_state=end_possession_state,
            pitch_progress=max(0, 96 - event_state.pitch_position),
            clock_consumed=clock_consumed,
            phase=PHASE_CORNER,
            summary=f"{team} won a corner",
        )

    if outcome == EventOutcome.TURNOVER:
        clock_consumed = _clock_consumed(event_state, priors, rng, profile=profile)
        next_position = mirror_pitch_position(possession_state.pitch_position + int(round(rng.normalvariate(0.0, 6.0))))
        end_possession_state = _possession_change_result(possession_state, clock_consumed, next_position=next_position)
        return _build_event_result(
            event_state=event_state,
            possession_state=possession_state,
            outcome=outcome,
            end_possession_state=end_possession_state,
            pitch_progress=0,
            clock_consumed=clock_consumed,
            phase=PHASE_OPEN_PLAY,
            terminal_possession_outcome=PossessionOutcome.TURNOVER,
            summary=f"{team} lost possession",
        )

    if outcome == EventOutcome.OFFSIDE:
        clock_consumed = _clock_consumed(event_state, priors, rng, profile=profile, extra_seconds=8.0)
        next_position = mirror_pitch_position(possession_state.pitch_position)
        end_possession_state = _possession_change_result(
            possession_state, clock_consumed, next_position=next_position, phase=PHASE_SET_PIECE
        )
        return _build_event_result(
            event_state=event_state,
            possession_state=possession_state,
            outcome=outcome,
            end_possession_state=end_possession_state,
            pitch_progress=0,
            clock_consumed=clock_consumed,
            phase=PHASE_SET_PIECE,
            terminal_possession_outcome=PossessionOutcome.OFFSIDE,
            summary=f"{team} was caught offside",
        )

    if outcome == EventOutcome.FAST_BREAK:
        clock_consumed = _clock_consumed(event_state, priors, rng, profile=profile)
        pitch_progress = max(10, min(45, int(round(rng.normalvariate(24.0, 8.0)))))
        end_possession_state = _continue_result(
            possession_state, clock_consumed, pitch_position=possession_state.pitch_position + pitch_progress
        )
        return _build_event_result(
            event_state=event_state,
            possession_state=possession_state,
            outcome=outcome,
            end_possession_state=end_possession_state,
            pitch_progress=pitch_progress,
            clock_consumed=clock_consumed,
            phase=PHASE_OPEN_PLAY,
            summary=f"{team} broke forward on the counter",
        )

    if outcome == EventOutcome.RETAIN:
        clock_consumed = _clock_consumed(event_state, priors, rng, profile=profile)
        pitch_progress = int(round(rng.normalvariate(0.0, 3.0)))
        end_possession_state = _continue_result(
            possession_state, clock_consumed, pitch_position=possession_state.pitch_position + pitch_progress
        )
        return _build_event_result(
            event_state=event_state,
            possession_state=possession_state,
            outcome=outcome,
            end_possession_state=end_possession_state,
            pitch_progress=pitch_progress,
            clock_consumed=clock_consumed,
            phase=PHASE_OPEN_PLAY,
            summary=f"{team} recycled possession",
        )

    clock_consumed = _clock_consumed(event_state, priors, rng, profile=profile)
    pitch_progress = max(0, int(round(rng.normalvariate(priors.expected_pitch_progress * 0.55, 5.0))))
    end_possession_state = _continue_result(
        possession_state, clock_consumed, pitch_position=possession_state.pitch_position + pitch_progress
    )
    return _build_event_result(
        event_state=event_state,
        possession_state=possession_state,
        outcome=EventOutcome.ADVANCE,
        end_possession_state=end_possession_state,
        pitch_progress=pitch_progress,
        clock_consumed=clock_consumed,
        phase=PHASE_OPEN_PLAY,
        summary=f"{team} advanced up the pitch",
    )


__all__ = ["EventResult", "simulate_event"]
