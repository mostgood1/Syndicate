from __future__ import annotations

from random import Random
from typing import Any

from syndicate.features.soccer.sim_engine.soccersim.calibration_profile import CalibrationProfile
from syndicate.features.soccer.sim_engine.soccersim.calibration_profile import SOCCER_CALIBRATION_PROFILE
from syndicate.features.soccer.sim_engine.soccersim.contracts import MatchResult
from syndicate.features.soccer.sim_engine.soccersim.contracts import PossessionState
from syndicate.features.soccer.sim_engine.soccersim.contracts import SoccerSimSimulationInput
from syndicate.features.soccer.sim_engine.soccersim.contracts import SoccerSimSimulationOutput
from syndicate.features.soccer.sim_engine.soccersim.possession_simulator import simulate_possession
from syndicate.features.soccer.sim_engine.soccersim.possession_state import advance_half
from syndicate.features.soccer.sim_engine.soccersim.possession_state import build_initial_possession_state

_EXTRA_TIME_HALF_SECONDS = 900
_SHOOTOUT_CONVERSION = 0.76


def _final_win_probability(home_goals: int, away_goals: int) -> dict[str, float]:
    if home_goals > away_goals:
        return {"home": 1.0, "draw": 0.0, "away": 0.0}
    if home_goals < away_goals:
        return {"home": 0.0, "draw": 0.0, "away": 1.0}
    return {"home": 0.0, "draw": 1.0, "away": 0.0}


def _spread(home_goals: int, away_goals: int) -> dict[str, float]:
    margin = float(home_goals - away_goals)
    return {"home": margin, "away": -margin}


def _total(home_goals: int, away_goals: int) -> dict[str, float]:
    return {"value": float(home_goals + away_goals)}


def _stoppage_seconds(rng: Random, *, base: float, sigma: float) -> int:
    return max(30, min(600, int(round(rng.normalvariate(base, sigma)))))


def _simulate_shootout(rng: Random) -> dict[str, Any]:
    home_converted = 0
    away_converted = 0
    rounds = 0
    # Best-of-five with early termination once one side is uncatchable.
    for round_index in range(1, 6):
        rounds = round_index
        home_converted += 1 if rng.random() < _SHOOTOUT_CONVERSION else 0
        away_converted += 1 if rng.random() < _SHOOTOUT_CONVERSION else 0
        remaining = 5 - round_index
        if home_converted > away_converted + remaining or away_converted > home_converted + remaining:
            break
    # Sudden death.
    while home_converted == away_converted:
        rounds += 1
        home_converted += 1 if rng.random() < _SHOOTOUT_CONVERSION else 0
        away_converted += 1 if rng.random() < _SHOOTOUT_CONVERSION else 0
        if rounds >= 30 and home_converted == away_converted:
            # Safety valve: resolve marathon shootouts with a single decisive kick.
            if rng.random() < 0.5:
                home_converted += 1
            else:
                away_converted += 1
            break
    winner = "home" if home_converted > away_converted else "away"
    return {"home": home_converted, "away": away_converted, "rounds": rounds, "winner": winner}


def _run_half(
    state,
    simulation_input: SoccerSimSimulationInput,
    rng: Random,
    profile: CalibrationProfile,
    possession_log: list[dict[str, Any]],
    event_log: list[dict[str, Any]],
) -> tuple[Any, int, int]:
    half_possession_count = 0
    half_shot_count = 0
    while state.clock_remaining > 0:
        possession_result = simulate_possession(state, simulation_input, rng=rng, profile=profile)
        possession_log.append(possession_result.to_dict())
        event_log.extend(step.to_dict() for step in possession_result.steps)
        half_possession_count += 1
        if possession_result.shot_taken:
            half_shot_count += 1
        state = possession_result.end_state
        if state.clock_remaining <= 0:
            break
    return state, half_possession_count, half_shot_count


def simulate_match(
    simulation_input: SoccerSimSimulationInput,
    *,
    rng: Random | None = None,
    profile: CalibrationProfile = SOCCER_CALIBRATION_PROFILE,
    initial_state: PossessionState | None = None,
) -> SoccerSimSimulationOutput:
    """Simulate a match, optionally resuming from ``initial_state`` instead
    of kickoff -- the live-lens hook. ``initial_state`` must already carry
    the correct half/clock_remaining/score (``live_lens.py`` builds this
    from a live or in-progress match's real current state); halves *after*
    the resumed one are still simulated fresh, including their own sampled
    stoppage time.
    """
    rng = rng or Random(simulation_input.seed)
    if initial_state is not None:
        state = initial_state
        starting_half = state.half
        first_half_stoppage = None
    else:
        first_half_stoppage = _stoppage_seconds(
            rng, base=profile.first_half_stoppage_base_seconds, sigma=profile.stoppage_seconds_sigma
        )
        state = build_initial_possession_state(
            home_team=simulation_input.home_team,
            away_team=simulation_input.away_team,
            owner=simulation_input.initial_possession_owner,
            pitch_position=simulation_input.initial_pitch_position,
            half=1,
            clock_remaining=simulation_input.half_seconds + first_half_stoppage,
        )
        starting_half = 1

    possession_log: list[dict[str, Any]] = []
    event_log: list[dict[str, Any]] = []
    half_log: list[dict[str, Any]] = []
    shootout: dict[str, Any] | None = None

    for half in range(starting_half, simulation_input.halves + 1):
        resuming_this_half = initial_state is not None and half == starting_half
        if resuming_this_half:
            # State is already correctly positioned by the caller for the
            # half being resumed -- no advance_half, no fresh stoppage roll.
            stoppage = None
        elif half == 1:
            stoppage = first_half_stoppage
        else:
            stoppage = _stoppage_seconds(
                rng, base=profile.second_half_stoppage_base_seconds, sigma=profile.stoppage_seconds_sigma
            )
            state = advance_half(state, half_seconds=simulation_input.half_seconds + stoppage)
        start_clock = state.clock_remaining
        half_home_goals_start = state.score_home
        half_away_goals_start = state.score_away

        state, half_possession_count, half_shot_count = _run_half(
            state, simulation_input, rng, profile, possession_log, event_log
        )

        half_log.append(
            {
                "half": half,
                "start_clock": start_clock,
                "end_clock": state.clock_remaining,
                "stoppage_seconds": stoppage,
                "home_goals": state.score_home - half_home_goals_start,
                "away_goals": state.score_away - half_away_goals_start,
                "possession_count": half_possession_count,
                "shot_count": half_shot_count,
            }
        )

    if simulation_input.knockout and state.score_home == state.score_away:
        for extra_half_offset in range(2):
            extra_half = simulation_input.halves + 1 + extra_half_offset
            stoppage = _stoppage_seconds(rng, base=60.0, sigma=30.0)
            state = advance_half(state, half_seconds=_EXTRA_TIME_HALF_SECONDS + stoppage)
            start_clock = state.clock_remaining
            half_home_goals_start = state.score_home
            half_away_goals_start = state.score_away
            state, half_possession_count, half_shot_count = _run_half(
                state, simulation_input, rng, profile, possession_log, event_log
            )
            half_log.append(
                {
                    "half": extra_half,
                    "start_clock": start_clock,
                    "end_clock": state.clock_remaining,
                    "stoppage_seconds": stoppage,
                    "home_goals": state.score_home - half_home_goals_start,
                    "away_goals": state.score_away - half_away_goals_start,
                    "possession_count": half_possession_count,
                    "shot_count": half_shot_count,
                    "extra_time": True,
                }
            )
        if state.score_home == state.score_away:
            shootout = _simulate_shootout(rng)

    final_score = {"home": state.score_home, "away": state.score_away}
    win_probability = _final_win_probability(state.score_home, state.score_away)
    if shootout is not None:
        win_probability = {
            "home": 1.0 if shootout["winner"] == "home" else 0.0,
            "draw": 0.0,
            "away": 1.0 if shootout["winner"] == "away" else 0.0,
        }
    spread = _spread(state.score_home, state.score_away)
    total = _total(state.score_home, state.score_away)
    distribution_summary = {
        "half_totals": [half_entry["home_goals"] + half_entry["away_goals"] for half_entry in half_log],
        "possession_count": len(possession_log),
        "event_count": len(event_log),
        "shot_count": sum(half_entry["shot_count"] for half_entry in half_log),
        "both_teams_scored": state.score_home > 0 and state.score_away > 0,
    }
    compatibility_summary = {
        "projected_final_score": final_score,
        "projected_spread": spread,
        "projected_total": total,
        "shootout": shootout,
        "feature_generation_payload_present": bool(simulation_input.feature_generation_payload),
    }

    output = SoccerSimSimulationOutput(
        simulation_kind="soccersim_possession",
        seed=simulation_input.seed,
        input_state=simulation_input.to_dict(),
        event_log=tuple(event_log),
        possession_log=tuple(possession_log),
        half_log=tuple(half_log),
        final_score=final_score,
        win_probability=win_probability,
        spread=spread,
        total=total,
        distribution_summary=distribution_summary,
        compatibility_summary=compatibility_summary,
        final_state=state.to_dict(),
    )
    return output


__all__ = ["MatchResult", "simulate_match"]
