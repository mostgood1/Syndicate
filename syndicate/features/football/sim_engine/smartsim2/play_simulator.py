from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from random import Random

from syndicate.features.football.sim_engine.smartsim2.calibration_profile import CalibrationProfile
from syndicate.features.football.sim_engine.smartsim2.calibration_profile import NFL_CALIBRATION_PROFILE
from syndicate.features.football.sim_engine.smartsim2.contracts import PossessionOutcome
from syndicate.features.football.sim_engine.smartsim2.contracts import PossessionState
from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationInput
from syndicate.features.football.sim_engine.smartsim2.drive_priors import DrivePriorProfile
from syndicate.features.football.sim_engine.smartsim2.play_outcomes import PlayOutcome
from syndicate.features.football.sim_engine.smartsim2.play_state import PlayState
from syndicate.features.football.sim_engine.smartsim2.play_state import advance_play_state
from syndicate.features.football.sim_engine.smartsim2.play_state import apply_situation_context
from syndicate.features.football.sim_engine.smartsim2.situation_model import URGENCY_END_GAME_PRESERVATION
from syndicate.features.football.sim_engine.smartsim2.situation_model import URGENCY_HALFTIME_PRESERVATION
from syndicate.features.football.sim_engine.smartsim2.situation_model import URGENCY_TRAILING
from syndicate.features.football.sim_engine.smartsim2.situation_model import URGENCY_TWO_MINUTE
from syndicate.features.football.sim_engine.smartsim2.situation_model import classify_situation


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _weighted_choice(rng: Random, weights: dict[PlayOutcome, float]) -> PlayOutcome:
    roll = rng.random()
    cursor = 0.0
    for outcome, weight in weights.items():
        cursor += weight
        if roll <= cursor:
            return outcome
    return next(reversed(weights))


def _offense_team_name(state: PossessionState) -> str:
    return state.home_team if state.possession_owner == "home" else state.away_team


def _next_possession_team(state: PossessionState) -> str:
    return "away" if state.possession_owner == "home" else "home"


def _score_for_team(state: PossessionState, possession_owner: str, points: int) -> tuple[int, int]:
    if possession_owner == "home":
        return state.score_home + points, state.score_away
    return state.score_home, state.score_away + points


def _refresh_situation(play_state: PlayState) -> PlayState:
    return apply_situation_context(play_state, classify_situation(play_state))


def _field_goal_success_probability(
    play_state: PlayState,
    priors: DrivePriorProfile,
    profile: CalibrationProfile = NFL_CALIBRATION_PROFILE,
) -> float:
    distance_from_goal = max(0, 100 - play_state.yardline)
    kick_distance = 17 + distance_from_goal
    return _clamp(
        profile.field_goal_make_base - max(0.0, kick_distance - 25.0) * profile.field_goal_make_distance_penalty,
        profile.field_goal_make_floor,
        profile.field_goal_make_ceiling,
    )


def _play_outcome_weights(
    play_state: PlayState,
    priors: DrivePriorProfile,
    profile: CalibrationProfile = NFL_CALIBRATION_PROFILE,
) -> dict[PlayOutcome, float]:
    field_position_factor = _clamp((play_state.yardline - 20) / 80.0, 0.0, 1.0)
    red_zone = 1.0 if play_state.red_zone else 0.0
    short_yardage = 1.0 if play_state.distance <= 3 else 0.0
    long_yardage = _clamp((play_state.distance - 5) / 12.0, 0.0, 1.0)
    late_down = 1.0 if play_state.down >= 3 else 0.0
    trailing = _clamp(-play_state.score_differential / 17.0, 0.0, 1.0)
    leading = _clamp(play_state.score_differential / 17.0, 0.0, 1.0)

    gain = 0.60 + priors.drive_success_probability * 0.30 + short_yardage * 0.08 - long_yardage * 0.08
    explosive_gain = (
        0.035 + priors.explosive_play_probability * (0.62 + field_position_factor * 0.20 + trailing * 0.04)
    ) * profile.explosive_play_multiplier
    sack = 0.05 + long_yardage * 0.06 + late_down * 0.04 + (1.0 - priors.drive_success_probability) * 0.04
    penalty = 0.035 + (1.0 - priors.coach_continuity_index) * 0.03 + late_down * 0.01
    turnover = priors.turnover_probability * (0.095 + long_yardage * 0.045 + trailing * 0.015)
    incomplete_pass = 0.165 + long_yardage * 0.06 + late_down * 0.03 + trailing * 0.02
    touchdown = priors.touchdown_probability * (
        0.04 + field_position_factor * 0.22 + red_zone * profile.red_zone_touchdown_weight_bonus + trailing * 0.03
    ) * profile.touchdown_weight_multiplier
    field_goal_attempt = priors.field_goal_probability * (
        0.01 + red_zone * 0.18 + (1.0 if play_state.field_goal_range else 0.0) * 0.30 + late_down * 0.12 - leading * 0.04
    ) * profile.field_goal_weight_multiplier

    if play_state.down >= 4:
        field_goal_attempt += 0.08 + red_zone * 0.06
        turnover += 0.01 + long_yardage * 0.02
        gain += 0.03

    if play_state.red_zone:
        touchdown += 0.06
        field_goal_attempt += 0.04
        punt = 0.01
    else:
        punt = 0.38 + (1.0 - field_position_factor) * 0.36 + long_yardage * 0.08

    if play_state.goal_to_go:
        touchdown += 0.08
        field_goal_attempt += 0.04
        gain += 0.02

    if play_state.backed_up_territory:
        punt += 0.32
        turnover += 0.04
        field_goal_attempt *= 0.65

    if play_state.field_goal_range:
        field_goal_attempt += 0.12

    if play_state.two_minute_drill:
        incomplete_pass += 0.06
        field_goal_attempt += 0.04
        explosive_gain *= 1.60
        touchdown += 0.04

    if play_state.urgency_state == URGENCY_TRAILING:
        incomplete_pass += 0.05
        explosive_gain *= 1.15
        sack += 0.02

    if play_state.urgency_state in {URGENCY_HALFTIME_PRESERVATION, URGENCY_END_GAME_PRESERVATION}:
        # Kneel/run-out offense: keep the ball on the ground, avoid clock stoppage.
        gain += 0.30
        incomplete_pass *= 0.25
        explosive_gain *= 0.40
        turnover *= 0.40

    if play_state.four_minute_offense:
        gain += 0.08
        sack *= 0.90
        incomplete_pass *= 0.90

    if play_state.long_yardage:
        sack += 0.04
        turnover += 0.01
        punt += 0.04

    if play_state.field_goal_range:
        # Scoring-zone defensive stiffening: compressed field shortens gains and
        # forces more stalled series that settle for field-goal attempts.
        gain *= profile.red_zone_gain_stiffening
        incomplete_pass += 0.07

    weights = {
        PlayOutcome.GAIN: max(0.01, gain),
        PlayOutcome.EXPLOSIVE_GAIN: max(0.01, explosive_gain),
        PlayOutcome.SACK: max(0.01, sack),
        PlayOutcome.PENALTY: max(0.01, penalty),
        PlayOutcome.TURNOVER: max(0.01, turnover),
        PlayOutcome.INCOMPLETE_PASS: max(0.01, incomplete_pass),
        PlayOutcome.TOUCHDOWN: max(0.01, touchdown),
    }
    if play_state.down >= 4 and play_state.field_goal_range:
        weights[PlayOutcome.FIELD_GOAL_ATTEMPT] = max(0.01, field_goal_attempt)
    total = sum(weights.values())
    return {key: value / total for key, value in weights.items()}


def _touchdown_result(state: PossessionState, clock_consumed: int) -> PossessionState:
    score_home, score_away = _score_for_team(state, state.possession_owner, 7)
    return replace(
        state,
        score_home=score_home,
        score_away=score_away,
        field_position=25,
        down=1,
        distance=10,
        clock_remaining=max(0, state.clock_remaining - clock_consumed),
        possession_owner=_next_possession_team(state),
        drive_index=state.drive_index + 1,
        possession_index=state.possession_index + 1,
    )


def _field_goal_result(state: PossessionState, clock_consumed: int) -> PossessionState:
    score_home, score_away = _score_for_team(state, state.possession_owner, 3)
    return replace(
        state,
        score_home=score_home,
        score_away=score_away,
        field_position=25,
        down=1,
        distance=10,
        clock_remaining=max(0, state.clock_remaining - clock_consumed),
        possession_owner=_next_possession_team(state),
        drive_index=state.drive_index + 1,
        possession_index=state.possession_index + 1,
    )


def _turnover_result(state: PossessionState, *, clock_consumed: int, return_yards: int = 0) -> PossessionState:
    next_spot = max(1, min(99, 100 - min(99, state.field_position + max(0, return_yards))))
    return replace(
        state,
        field_position=next_spot,
        down=1,
        distance=10,
        clock_remaining=max(0, state.clock_remaining - clock_consumed),
        possession_owner=_next_possession_team(state),
        drive_index=state.drive_index + 1,
        possession_index=state.possession_index + 1,
    )


@dataclass(frozen=True)
class PlayResult:
    step_index: int
    start_state: PlayState
    end_state: PlayState
    end_possession_state: PossessionState
    outcome: PlayOutcome
    yards_gained: int
    clock_consumed: int
    points_scored: int = 0
    terminal_drive_outcome: PossessionOutcome | None = None
    summary: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "step_index": self.step_index,
            "start_state": self.start_state.to_dict(),
            "end_state": self.end_state.to_dict(),
            "end_possession_state": self.end_possession_state.to_dict(),
            "outcome": self.outcome.value,
            "yards_gained": self.yards_gained,
            "clock_consumed": self.clock_consumed,
            "points_scored": self.points_scored,
            "terminal_drive_outcome": self.terminal_drive_outcome.value if self.terminal_drive_outcome is not None else None,
            "summary": self.summary,
        }


def simulate_play(
    play_state: PlayState,
    possession_state: PossessionState,
    simulation_input: SmartSim2SimulationInput,
    *,
    priors: DrivePriorProfile,
    rng: Random,
    profile: CalibrationProfile = NFL_CALIBRATION_PROFILE,
) -> PlayResult:
    play_state = _refresh_situation(play_state)
    weights = _play_outcome_weights(play_state, priors, profile)
    outcome = _weighted_choice(rng, weights)
    offense_rating = simulation_input.home_offense_rating if possession_state.possession_owner == "home" else simulation_input.away_offense_rating
    defense_rating = simulation_input.away_defense_rating if possession_state.possession_owner == "home" else simulation_input.home_defense_rating

    if outcome == PlayOutcome.TOUCHDOWN:
        yards_gained = max(1, 100 - play_state.yardline)
        clock_multiplier = 0.14 if play_state.two_minute_drill else 0.18
        clock_consumed = max(4, int(round(rng.normalvariate(priors.expected_clock_seconds * clock_multiplier, 4.0))))
        end_possession_state = _touchdown_result(possession_state, clock_consumed)
        end_play_state = _refresh_situation(advance_play_state(play_state, yards_gained=yards_gained, clock_consumed=clock_consumed))
        end_play_state = replace(end_play_state, score_differential=play_state.score_differential + 7)
        end_play_state = _refresh_situation(end_play_state)
        return PlayResult(
            step_index=play_state.play_index + 1,
            start_state=play_state,
            end_state=end_play_state,
            end_possession_state=end_possession_state,
            outcome=outcome,
            yards_gained=yards_gained,
            clock_consumed=clock_consumed,
            points_scored=7,
            terminal_drive_outcome=PossessionOutcome.TOUCHDOWN,
            summary=f"{_offense_team_name(possession_state)} scored a touchdown",
        )

    if outcome == PlayOutcome.FIELD_GOAL_ATTEMPT:
        clock_multiplier = 0.07 if play_state.two_minute_drill else 0.09
        clock_consumed = max(4, int(round(rng.normalvariate(priors.expected_clock_seconds * clock_multiplier, 3.0))))
        yards_gained = max(0, int(round(rng.normalvariate(0.0, 1.0))))
        success_probability = _field_goal_success_probability(play_state, priors, profile)
        made = rng.random() <= success_probability
        if made:
            end_possession_state = _field_goal_result(possession_state, clock_consumed)
            terminal_outcome = PossessionOutcome.FIELD_GOAL
            points_scored = 3
            summary = f"{_offense_team_name(possession_state)} made a field goal"
        else:
            next_spot = max(1, min(99, 100 - possession_state.field_position))
            end_possession_state = replace(
                possession_state,
                field_position=next_spot,
                down=1,
                distance=10,
                clock_remaining=max(0, possession_state.clock_remaining - clock_consumed),
                possession_owner=_next_possession_team(possession_state),
                drive_index=possession_state.drive_index + 1,
                possession_index=possession_state.possession_index + 1,
            )
            terminal_outcome = PossessionOutcome.MISSED_FIELD_GOAL
            points_scored = 0
            summary = f"{_offense_team_name(possession_state)} missed a field goal"
        end_play_state = _refresh_situation(advance_play_state(play_state, yards_gained=yards_gained, clock_consumed=clock_consumed, repeat_down=True))
        return PlayResult(
            step_index=play_state.play_index + 1,
            start_state=play_state,
            end_state=end_play_state,
            end_possession_state=end_possession_state,
            outcome=outcome,
            yards_gained=yards_gained,
            clock_consumed=clock_consumed,
            points_scored=points_scored,
            terminal_drive_outcome=terminal_outcome,
            summary=summary,
        )

    if outcome == PlayOutcome.TURNOVER:
        clock_multiplier = 0.12 if play_state.two_minute_drill else 0.16
        clock_consumed = max(3, int(round(rng.normalvariate(priors.expected_clock_seconds * clock_multiplier, 4.0))))
        yards_gained = -max(0, int(round(rng.normalvariate(3.0 + priors.turnover_probability * 5.0, 3.0))))
        return_yards = max(0, int(round(rng.normalvariate(4.0 + priors.explosive_play_probability * 4.0, 3.0))))
        end_possession_state = _turnover_result(possession_state, clock_consumed=clock_consumed, return_yards=return_yards)
        end_play_state = _refresh_situation(advance_play_state(play_state, yards_gained=yards_gained, clock_consumed=clock_consumed))
        return PlayResult(
            step_index=play_state.play_index + 1,
            start_state=play_state,
            end_state=end_play_state,
            end_possession_state=end_possession_state,
            outcome=outcome,
            yards_gained=yards_gained,
            clock_consumed=clock_consumed,
            terminal_drive_outcome=PossessionOutcome.TURNOVER,
            summary=f"{_offense_team_name(possession_state)} turned the ball over",
        )

    if play_state.four_minute_offense:
        clock_base = 0.26
    elif play_state.urgency_state in {URGENCY_HALFTIME_PRESERVATION, URGENCY_END_GAME_PRESERVATION}:
        # Preservation offense drains the full play clock on every snap.
        clock_base = 0.30
    elif play_state.two_minute_drill or play_state.urgency_state == URGENCY_TRAILING:
        # Hurry-up: timeouts, spikes, sideline throws, and incompletions preserve clock.
        clock_base = 0.05 if outcome == PlayOutcome.INCOMPLETE_PASS else 0.09
    else:
        clock_base = 0.14 if outcome in {PlayOutcome.EXPLOSIVE_GAIN, PlayOutcome.INCOMPLETE_PASS} else 0.19
    clock_consumed = max(3, int(round(rng.normalvariate(priors.expected_clock_seconds * clock_base, 4.0))))

    if outcome == PlayOutcome.GAIN:
        base_gain = (5.6 + priors.drive_success_probability * 4.5 + offense_rating * 3.0 - defense_rating * 2.2) * profile.drive_yardage_multiplier
        yard_multiplier = 0.6 if play_state.down >= 3 else 0.0
        yards_gained = max(0, int(round(rng.normalvariate(base_gain + yard_multiplier, 3.2))))
        end_play_state = _refresh_situation(advance_play_state(play_state, yards_gained=yards_gained, clock_consumed=clock_consumed))
        summary = (
            f"{_offense_team_name(possession_state)} converted a first down"
            if yards_gained >= play_state.distance
            else f"{_offense_team_name(possession_state)} gained {yards_gained} yards"
        )
        end_possession_state = replace(
            possession_state,
            field_position=end_play_state.yardline,
            down=end_play_state.down,
            distance=end_play_state.distance,
            clock_remaining=end_play_state.seconds_remaining,
        )
        return PlayResult(
            step_index=play_state.play_index + 1,
            start_state=play_state,
            end_state=end_play_state,
            end_possession_state=end_possession_state,
            outcome=outcome,
            yards_gained=yards_gained,
            clock_consumed=clock_consumed,
            summary=summary,
        )

    if outcome == PlayOutcome.EXPLOSIVE_GAIN:
        base_gain = (9.0 + priors.explosive_play_probability * 18.0 + offense_rating * 4.0 - defense_rating * 2.5) * profile.explosive_yardage_multiplier
        yards_gained = max(6, min(55, int(round(rng.normalvariate(base_gain, 7.0)))))
        end_play_state = _refresh_situation(advance_play_state(play_state, yards_gained=yards_gained, clock_consumed=clock_consumed))
        end_possession_state = replace(
            possession_state,
            field_position=end_play_state.yardline,
            down=end_play_state.down,
            distance=end_play_state.distance,
            clock_remaining=end_play_state.seconds_remaining,
        )
        return PlayResult(
            step_index=play_state.play_index + 1,
            start_state=play_state,
            end_state=end_play_state,
            end_possession_state=end_possession_state,
            outcome=outcome,
            yards_gained=yards_gained,
            clock_consumed=clock_consumed,
            summary=f"{_offense_team_name(possession_state)} broke an explosive gain",
        )

    if outcome == PlayOutcome.SACK:
        yards_gained = -max(1, min(12, int(round(rng.normalvariate(3.0 + priors.turnover_probability * 5.0, 2.0)))))
        end_play_state = _refresh_situation(advance_play_state(play_state, yards_gained=yards_gained, clock_consumed=clock_consumed))
        end_possession_state = replace(
            possession_state,
            field_position=end_play_state.yardline,
            down=end_play_state.down,
            distance=end_play_state.distance,
            clock_remaining=end_play_state.seconds_remaining,
        )
        return PlayResult(
            step_index=play_state.play_index + 1,
            start_state=play_state,
            end_state=end_play_state,
            end_possession_state=end_possession_state,
            outcome=outcome,
            yards_gained=yards_gained,
            clock_consumed=clock_consumed,
            summary=f"{_offense_team_name(possession_state)} took a sack",
        )

    if outcome == PlayOutcome.PENALTY:
        defensive_penalty = rng.random() < 0.35 + priors.drive_success_probability * 0.1
        yards_gained = 5 if defensive_penalty else -5
        if not defensive_penalty and rng.random() < 0.35:
            yards_gained = -10
        end_play_state = _refresh_situation(
            advance_play_state(play_state, yards_gained=yards_gained, clock_consumed=clock_consumed, repeat_down=defensive_penalty)
        )
        end_possession_state = replace(
            possession_state,
            field_position=end_play_state.yardline,
            down=end_play_state.down,
            distance=end_play_state.distance,
            clock_remaining=end_play_state.seconds_remaining,
        )
        return PlayResult(
            step_index=play_state.play_index + 1,
            start_state=play_state,
            end_state=end_play_state,
            end_possession_state=end_possession_state,
            outcome=outcome,
            yards_gained=yards_gained,
            clock_consumed=clock_consumed,
            summary=f"{_offense_team_name(possession_state)} penalty changed field position",
        )

    yards_gained = 0
    end_play_state = _refresh_situation(advance_play_state(play_state, yards_gained=yards_gained, clock_consumed=clock_consumed))
    end_possession_state = replace(
        possession_state,
        field_position=end_play_state.yardline,
        down=end_play_state.down,
        distance=end_play_state.distance,
        clock_remaining=end_play_state.seconds_remaining,
    )
    return PlayResult(
        step_index=play_state.play_index + 1,
        start_state=play_state,
        end_state=end_play_state,
        end_possession_state=end_possession_state,
        outcome=outcome,
        yards_gained=yards_gained,
        clock_consumed=clock_consumed,
        summary=f"{_offense_team_name(possession_state)} fell incomplete",
    )


__all__ = ["PlayResult", "simulate_play"]
