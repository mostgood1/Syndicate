from __future__ import annotations

from dataclasses import replace
from random import Random
from typing import Any

from syndicate.features.football.sim_engine.smartsim2.calibration_profile import CalibrationProfile
from syndicate.features.football.sim_engine.smartsim2.calibration_profile import NFL_CALIBRATION_PROFILE
from syndicate.features.football.sim_engine.smartsim2.contracts import DriveResult
from syndicate.features.football.sim_engine.smartsim2.contracts import PossessionOutcome
from syndicate.features.football.sim_engine.smartsim2.contracts import PossessionState
from syndicate.features.football.sim_engine.smartsim2.contracts import PossessionStepResult
from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationInput
from syndicate.features.football.sim_engine.smartsim2.drive_priors import build_drive_priors
from syndicate.features.football.sim_engine.smartsim2.play_simulator import PlayResult
from syndicate.features.football.sim_engine.smartsim2.play_simulator import simulate_play
from syndicate.features.football.sim_engine.smartsim2.play_state import build_play_state_from_possession_state
from syndicate.features.football.sim_engine.smartsim2.possession_state import advance_possession_clock
from syndicate.features.football.sim_engine.smartsim2.situation_model import TRUE_FIELD_GOAL_RANGE_YARDLINE
from syndicate.features.football.sim_engine.smartsim2.situation_model import URGENCY_TRAILING
from syndicate.features.football.sim_engine.smartsim2.situation_model import URGENCY_TWO_MINUTE
from syndicate.features.football.sim_engine.smartsim2.situation_model import classify_urgency


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _play_terminal_outcome(result: PlayResult) -> PossessionOutcome:
    if result.terminal_drive_outcome is not None:
        return result.terminal_drive_outcome
    return PossessionOutcome(result.outcome.value)


def _change_of_possession_spot(state: PossessionState, spot: int) -> int:
    return max(1, min(99, int(spot)))


def _punt_decision(
    state: PossessionState,
    priors: Any,
    rng: Random,
    profile: CalibrationProfile = NFL_CALIBRATION_PROFILE,
) -> bool:
    if state.down < 4:
        return False
    distance_factor = max(0.0, min(1.0, (state.distance - 3) / 10.0))
    # Neutral 4th-and-short aggression: real offenses go for it on short
    # distance around midfield instead of always punting.
    if state.distance <= 3 and state.field_position >= 42:
        return rng.random() < profile.fourth_down_short_distance_punt_probability
    if state.distance <= 6 and state.field_position >= 55:
        return rng.random() < profile.fourth_down_mid_distance_punt_probability
    if state.field_position < 40:
        return True
    if state.field_position < 55:
        return rng.random() < profile.fourth_down_midfield_punt_probability
    if state.field_position < TRUE_FIELD_GOAL_RANGE_YARDLINE:
        return rng.random() < profile.fourth_down_range_approach_punt_base + distance_factor * profile.fourth_down_range_approach_punt_scale
    # In true field-goal range and the field-goal attempt was already declined:
    # long distance still pins with a short punt, short distance goes for it.
    return rng.random() < profile.fourth_down_in_range_punt_base + distance_factor * profile.fourth_down_in_range_punt_scale


def _punt_result(state: PossessionState, priors: Any, rng: Random) -> tuple[PossessionState, int, int, bool]:
    gross_distance = max(24, min(67, int(round(rng.normalvariate(42.0 + priors.punt_probability * 10.0, 7.0)))))
    return_yards = max(0, min(28, int(round(rng.normalvariate(4.0 + priors.explosive_play_probability * 8.0, 5.0)))))
    gross_landing_spot = max(1, min(99, state.field_position + gross_distance))
    touchback = gross_landing_spot >= 100 or (gross_landing_spot >= 96 and rng.random() < 0.7)

    if touchback:
        next_spot = 25
    else:
        net_spot = gross_landing_spot - return_yards
        next_spot = max(1, min(99, 100 - net_spot))

    end_state = replace(
        state,
        field_position=next_spot,
        down=1,
        distance=10,
        possession_owner="away" if state.possession_owner == "home" else "home",
        drive_index=state.drive_index + 1,
        possession_index=state.possession_index + 1,
    )
    net_yards = max(0, gross_distance - return_yards)
    return end_state, gross_distance, net_yards, touchback


def _field_goal_decision(
    state: PossessionState,
    priors: Any,
    rng: Random,
    profile: CalibrationProfile = NFL_CALIBRATION_PROFILE,
) -> bool:
    if state.down < 4:
        return False
    if state.field_position >= TRUE_FIELD_GOAL_RANGE_YARDLINE - 3:
        if state.field_position < TRUE_FIELD_GOAL_RANGE_YARDLINE:
            # Long-range fringe (53-55 yard kicks): attempted, but not routine.
            return rng.random() < profile.field_goal_attempt_fringe_probability
        attempt_probability = _clamp(
            profile.field_goal_attempt_base_probability + (state.field_position - TRUE_FIELD_GOAL_RANGE_YARDLINE) * profile.field_goal_attempt_distance_scale,
            profile.field_goal_attempt_base_probability,
            0.97,
        )
        return rng.random() < attempt_probability
    return False


def _field_goal_make_probability(state: PossessionState, profile: CalibrationProfile = NFL_CALIBRATION_PROFILE) -> float:
    kick_distance = 17 + max(0, 100 - state.field_position)
    return _clamp(
        profile.field_goal_make_base - max(0.0, kick_distance - 25.0) * profile.field_goal_make_distance_penalty,
        profile.field_goal_make_floor,
        profile.field_goal_make_ceiling,
    )


def _missed_field_goal_result(state: PossessionState, clock_consumed: int) -> PossessionState:
    next_spot = _change_of_possession_spot(state, 100 - state.field_position)
    return replace(
        state,
        field_position=next_spot,
        down=1,
        distance=10,
        clock_remaining=max(0, state.clock_remaining - clock_consumed),
        possession_owner="away" if state.possession_owner == "home" else "home",
        drive_index=state.drive_index + 1,
        possession_index=state.possession_index + 1,
    )


def _owner_score_differential(state: PossessionState) -> int:
    if state.possession_owner == "home":
        return state.score_home - state.score_away
    return state.score_away - state.score_home


def _execute_field_goal(
    state: PossessionState,
    priors: Any,
    rng: Random,
    step_index: int,
    *,
    urgency_kick: bool = False,
    profile: CalibrationProfile = NFL_CALIBRATION_PROFILE,
) -> tuple[PossessionStepResult, PossessionState, PossessionOutcome, int]:
    if urgency_kick:
        clock_consumed = min(state.clock_remaining, 5)
    else:
        clock_consumed = min(state.clock_remaining, max(4, int(round(rng.normalvariate(priors.expected_clock_seconds * 0.09, 3.0)))))
    end_state = advance_possession_clock(state, clock_consumed)
    if rng.random() < _field_goal_make_probability(state, profile):
        score_home = end_state.score_home + 3 if end_state.possession_owner == "home" else end_state.score_home
        score_away = end_state.score_away + 3 if end_state.possession_owner == "away" else end_state.score_away
        end_state = replace(
            end_state,
            score_home=score_home,
            score_away=score_away,
            field_position=25,
            down=1,
            distance=10,
            possession_owner="away" if state.possession_owner == "home" else "home",
            drive_index=state.drive_index + 1,
            possession_index=state.possession_index + 1,
        )
        summary = f"{state.possession_owner} kicked a field goal" + (" as time expired" if urgency_kick else "")
        play_step = PossessionStepResult(
            step_index=step_index,
            start_state=state,
            end_state=end_state,
            outcome=PossessionOutcome.FIELD_GOAL,
            yards_gained=0,
            clock_consumed=clock_consumed,
            points_scored=3,
            summary=summary,
        )
        return play_step, end_state, PossessionOutcome.FIELD_GOAL, 3

    end_state = _missed_field_goal_result(state, clock_consumed)
    play_step = PossessionStepResult(
        step_index=step_index,
        start_state=state,
        end_state=end_state,
        outcome=PossessionOutcome.MISSED_FIELD_GOAL,
        yards_gained=0,
        clock_consumed=clock_consumed,
        points_scored=0,
        summary=f"{state.possession_owner} missed a field goal" + (" as time expired" if urgency_kick else ""),
    )
    return play_step, end_state, PossessionOutcome.MISSED_FIELD_GOAL, 0


def simulate_drive(
    possession_state: PossessionState,
    simulation_input: SmartSim2SimulationInput,
    *,
    rng: Random | None = None,
    profile: CalibrationProfile = NFL_CALIBRATION_PROFILE,
) -> DriveResult:
    rng = rng or Random(simulation_input.seed)
    state = possession_state
    priors = build_drive_priors(simulation_input, possession_state=state)
    play_state = build_play_state_from_possession_state(state)
    steps: list[PossessionStepResult] = []
    total_yards = 0
    total_clock = 0
    points_scored = 0
    possession_change = False
    next_owner = state.possession_owner
    terminal_outcome: PossessionOutcome | None = None
    max_plays = max(4, int(round(priors.expected_play_count * 2.2)) + 4)

    for _ in range(max_plays):
        if state.clock_remaining <= 0:
            terminal_outcome = PossessionOutcome.END_OF_HALF_STOP if state.quarter in {2, 4} else PossessionOutcome.END_OF_QUARTER_STOP
            break

        score_differential = _owner_score_differential(state)
        urgency = classify_urgency(
            quarter=state.quarter,
            seconds_remaining=state.clock_remaining,
            score_differential=score_differential,
            yardline=state.field_position,
        )

        # Urgency field goal: take the points before the half or game expires.
        if (
            state.quarter != 1
            and state.quarter != 3
            and state.clock_remaining <= 90
            and state.field_position >= TRUE_FIELD_GOAL_RANGE_YARDLINE
            and -9 <= score_differential <= 2
        ):
            play_step, end_state, terminal_outcome, points = _execute_field_goal(state, priors, rng, len(steps) + 1, urgency_kick=True, profile=profile)
            steps.append(play_step)
            total_clock += play_step.clock_consumed
            points_scored += points
            possession_change = True
            state = end_state
            break

        if state.down == 4:
            go_for_it = (
                state.quarter >= 4
                and state.clock_remaining <= 300
                and score_differential < 0
                and urgency in {URGENCY_TRAILING, URGENCY_TWO_MINUTE}
                and state.field_position < TRUE_FIELD_GOAL_RANGE_YARDLINE
            )
            if go_for_it:
                clock_consumed = min(state.clock_remaining, max(4, int(round(rng.normalvariate(priors.expected_clock_seconds * 0.09, 3.0)))))
                end_state = advance_possession_clock(state, clock_consumed)
                conversion_probability = _clamp((0.62 - max(0, state.distance - 2) * 0.05) * profile.fourth_down_conversion_multiplier, 0.25, 0.62)
                if rng.random() < conversion_probability:
                    gained = max(state.distance, int(round(rng.normalvariate(state.distance + 2.0, 2.0))))
                    end_state = replace(
                        end_state,
                        field_position=max(1, min(99, end_state.field_position + gained)),
                        down=1,
                        distance=10,
                    )
                    play_step = PossessionStepResult(
                        step_index=len(steps) + 1,
                        start_state=state,
                        end_state=end_state,
                        outcome=PossessionOutcome.GAIN,
                        yards_gained=gained,
                        clock_consumed=clock_consumed,
                        points_scored=0,
                        summary=f"{state.possession_owner} converted on fourth down",
                    )
                    steps.append(play_step)
                    total_yards += gained
                    total_clock += clock_consumed
                    state = end_state
                    play_state = build_play_state_from_possession_state(state)
                    continue
                next_spot = _change_of_possession_spot(end_state, 100 - end_state.field_position)
                end_state = replace(
                    end_state,
                    field_position=next_spot,
                    down=1,
                    distance=10,
                    possession_owner="away" if state.possession_owner == "home" else "home",
                    drive_index=state.drive_index + 1,
                    possession_index=state.possession_index + 1,
                )
                play_step = PossessionStepResult(
                    step_index=len(steps) + 1,
                    start_state=state,
                    end_state=end_state,
                    outcome=PossessionOutcome.TURNOVER_ON_DOWNS,
                    yards_gained=0,
                    clock_consumed=clock_consumed,
                    points_scored=0,
                    summary=f"{state.possession_owner} failed on fourth down",
                )
                steps.append(play_step)
                total_clock += clock_consumed
                possession_change = True
                terminal_outcome = PossessionOutcome.TURNOVER_ON_DOWNS
                state = end_state
                break

            if _field_goal_decision(state, priors, rng, profile):
                play_step, end_state, terminal_outcome, points = _execute_field_goal(state, priors, rng, len(steps) + 1, profile=profile)
                steps.append(play_step)
                total_clock += play_step.clock_consumed
                points_scored += points
                possession_change = True
                state = end_state
                break

            if _punt_decision(state, priors, rng, profile):
                clock_consumed = min(state.clock_remaining, max(4, int(round(rng.normalvariate(priors.expected_clock_seconds * 0.20, 4.0)))))
                end_state = advance_possession_clock(state, clock_consumed)
                end_state, gross_distance, net_distance, touchback = _punt_result(end_state, priors, rng)
                play_step = PossessionStepResult(
                    step_index=len(steps) + 1,
                    start_state=state,
                    end_state=end_state,
                    outcome=PossessionOutcome.PUNT,
                    yards_gained=net_distance,
                    clock_consumed=clock_consumed,
                    points_scored=0,
                    summary=(
                        f"{state.possession_owner} punted {gross_distance} yards"
                        + (" for a touchback" if touchback else f" and netted {net_distance} yards")
                    ),
                )
                steps.append(play_step)
                # Punt distance is special-teams yardage, not offensive drive yardage.
                total_clock += clock_consumed
                possession_change = True
                terminal_outcome = PossessionOutcome.PUNT
                state = end_state
                break

            clock_consumed = min(state.clock_remaining, max(4, int(round(rng.normalvariate(priors.expected_clock_seconds * 0.12, 3.0)))))
            end_state = advance_possession_clock(state, clock_consumed)
            # Neutral go-for-it attempt: short distance converts realistically
            # instead of every declined kick/punt becoming a failed 4th down.
            conversion_probability = _clamp((0.52 - max(0, state.distance - 2) * 0.06) * profile.fourth_down_conversion_multiplier, 0.15, 0.52)
            if rng.random() < conversion_probability:
                gained = max(state.distance, int(round(rng.normalvariate(state.distance + 2.0, 2.0))))
                end_state = replace(
                    end_state,
                    field_position=max(1, min(99, end_state.field_position + gained)),
                    down=1,
                    distance=10,
                )
                play_step = PossessionStepResult(
                    step_index=len(steps) + 1,
                    start_state=state,
                    end_state=end_state,
                    outcome=PossessionOutcome.GAIN,
                    yards_gained=gained,
                    clock_consumed=clock_consumed,
                    points_scored=0,
                    summary=f"{state.possession_owner} converted on fourth down",
                )
                steps.append(play_step)
                total_yards += gained
                total_clock += clock_consumed
                state = end_state
                play_state = build_play_state_from_possession_state(state)
                continue
            next_spot = _change_of_possession_spot(end_state, 100 - end_state.field_position)
            end_state = replace(
                end_state,
                field_position=next_spot,
                down=1,
                distance=10,
                possession_owner="away" if state.possession_owner == "home" else "home",
                drive_index=state.drive_index + 1,
                possession_index=state.possession_index + 1,
            )
            play_step = PossessionStepResult(
                step_index=len(steps) + 1,
                start_state=state,
                end_state=end_state,
                outcome=PossessionOutcome.TURNOVER_ON_DOWNS,
                yards_gained=0,
                clock_consumed=clock_consumed,
                points_scored=0,
                summary=f"{state.possession_owner} turned the ball over on downs",
            )
            steps.append(play_step)
            total_clock += clock_consumed
            possession_change = True
            terminal_outcome = PossessionOutcome.TURNOVER_ON_DOWNS
            state = end_state
            break

        if _punt_decision(state, priors, rng, profile):
            clock_consumed = min(state.clock_remaining, max(4, int(round(rng.normalvariate(priors.expected_clock_seconds * 0.24, 4.0)))))
            end_state = advance_possession_clock(state, clock_consumed)
            end_state, gross_distance, net_distance, touchback = _punt_result(end_state, priors, rng)
            play_step = PossessionStepResult(
                step_index=len(steps) + 1,
                start_state=state,
                end_state=end_state,
                outcome=PossessionOutcome.PUNT,
                yards_gained=net_distance,
                clock_consumed=clock_consumed,
                points_scored=0,
                summary=(
                    f"{state.possession_owner} punted {gross_distance} yards"
                    + (" for a touchback" if touchback else f" and netted {net_distance} yards")
                ),
            )
            steps.append(play_step)
            # Punt distance is special-teams yardage, not offensive drive yardage.
            total_clock += clock_consumed
            possession_change = True
            terminal_outcome = PossessionOutcome.PUNT
            state = end_state
            break

        play_result = simulate_play(play_state, state, simulation_input, priors=priors, rng=rng, profile=profile)
        terminal_outcome = play_result.terminal_drive_outcome
        outcome = PossessionOutcome(play_result.outcome.value)
        play_step = PossessionStepResult(
            step_index=len(steps) + 1,
            start_state=state,
            end_state=play_result.end_possession_state,
            outcome=outcome,
            yards_gained=play_result.yards_gained,
            clock_consumed=play_result.clock_consumed,
            points_scored=play_result.points_scored,
            summary=play_result.summary,
        )
        steps.append(play_step)
        total_yards += play_result.yards_gained
        total_clock += play_result.clock_consumed
        points_scored += play_result.points_scored
        state = play_result.end_possession_state
        play_state = play_result.end_state

        if terminal_outcome is not None:
            possession_change = terminal_outcome in {
                PossessionOutcome.TOUCHDOWN,
                PossessionOutcome.FIELD_GOAL,
                PossessionOutcome.MISSED_FIELD_GOAL,
                PossessionOutcome.PUNT,
                PossessionOutcome.TURNOVER,
                PossessionOutcome.TURNOVER_ON_DOWNS,
            }
            next_owner = state.possession_owner
            break

    if terminal_outcome is None:
        terminal_outcome = PossessionOutcome.END_OF_HALF_STOP if state.clock_remaining <= 0 and state.quarter in {2, 4} else PossessionOutcome.END_OF_QUARTER_STOP
        if state.clock_remaining <= 0:
            state = replace(state, clock_remaining=0)
    next_owner = state.possession_owner

    return DriveResult(
        drive_index=possession_state.drive_index,
        possession_index=possession_state.possession_index,
        start_state=possession_state,
        end_state=state,
        outcome=terminal_outcome,
        points_scored=points_scored,
        yards_gained=total_yards,
        clock_consumed=total_clock,
        play_count=len(steps),
        possession_change=possession_change,
        next_possession_owner=next_owner,
        steps=tuple(steps),
    )
