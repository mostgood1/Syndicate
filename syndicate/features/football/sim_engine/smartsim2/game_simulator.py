from __future__ import annotations

from dataclasses import replace
from random import Random
from typing import Any

from syndicate.features.football.sim_engine.smartsim2.calibration_profile import CalibrationProfile
from syndicate.features.football.sim_engine.smartsim2.calibration_profile import NFL_CALIBRATION_PROFILE
from syndicate.features.football.sim_engine.smartsim2.contracts import GameResult
from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationInput
from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationOutput
from syndicate.features.football.sim_engine.smartsim2.drive_simulator import simulate_drive
from syndicate.features.football.sim_engine.smartsim2.possession_state import advance_quarter
from syndicate.features.football.sim_engine.smartsim2.possession_state import build_initial_possession_state


def _final_win_probability(home_points: int, away_points: int) -> dict[str, float]:
    if home_points == away_points:
        return {"home": 0.5, "away": 0.5}
    if home_points > away_points:
        return {"home": 1.0, "away": 0.0}
    return {"home": 0.0, "away": 1.0}


def _spread(home_points: int, away_points: int) -> dict[str, float]:
    margin = float(home_points - away_points)
    return {"home": margin, "away": -margin}


def _total(home_points: int, away_points: int) -> dict[str, float]:
    return {"value": float(home_points + away_points)}


def _merge_quarter_carryover_drives(drive_log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge drives split by Q1->Q2 and Q3->Q4 boundaries into single logical drives.

    The possession carries over the quarter boundary (owner, field position, and
    down are preserved by advance_quarter), so the fragment that "stopped" at the
    boundary and its continuation are one real football drive.
    """
    merged: list[dict[str, Any]] = []
    for entry in drive_log:
        previous = merged[-1] if merged else None
        if previous is not None and str(previous.get("outcome")) == "end_of_quarter_stop":
            previous_end = previous.get("end_state") or {}
            entry_start = entry.get("start_state") or {}
            if (
                int(previous_end.get("quarter") or 0) in {1, 3}
                and int(entry_start.get("quarter") or 0) == int(previous_end.get("quarter") or 0) + 1
                and str(entry_start.get("possession_owner")) == str(previous_end.get("possession_owner"))
                and int(entry_start.get("field_position") or -1) == int(previous_end.get("field_position") or -2)
            ):
                previous["outcome"] = entry.get("outcome")
                previous["points_scored"] = int(previous.get("points_scored") or 0) + int(entry.get("points_scored") or 0)
                previous["yards_gained"] = int(previous.get("yards_gained") or 0) + int(entry.get("yards_gained") or 0)
                previous["clock_consumed"] = int(previous.get("clock_consumed") or 0) + int(entry.get("clock_consumed") or 0)
                previous["play_count"] = int(previous.get("play_count") or 0) + int(entry.get("play_count") or 0)
                previous["possession_change"] = entry.get("possession_change")
                previous["next_possession_owner"] = entry.get("next_possession_owner")
                previous["end_state"] = entry.get("end_state")
                previous["steps"] = list(previous.get("steps") or []) + list(entry.get("steps") or [])
                continue
        merged.append(dict(entry))
    return merged


def simulate_game(
    simulation_input: SmartSim2SimulationInput,
    *,
    rng: Random | None = None,
    profile: CalibrationProfile = NFL_CALIBRATION_PROFILE,
) -> SmartSim2SimulationOutput:
    rng = rng or Random(simulation_input.seed)
    state = build_initial_possession_state(
        home_team=simulation_input.home_team,
        away_team=simulation_input.away_team,
        owner=simulation_input.initial_possession_owner,
        field_position=simulation_input.initial_field_position,
        down=simulation_input.initial_down,
        distance=simulation_input.initial_distance,
        quarter=1,
        clock_remaining=simulation_input.quarter_seconds,
    )

    possession_log: list[dict[str, Any]] = []
    drive_log: list[dict[str, Any]] = []
    quarter_log: list[dict[str, Any]] = []
    quarter_start_clock = simulation_input.quarter_seconds

    for quarter in range(1, simulation_input.quarters + 1):
        quarter_drive_count = 0
        quarter_possession_count = 0
        quarter_home_points_start = state.score_home
        quarter_away_points_start = state.score_away
        current_quarter_clock = simulation_input.quarter_seconds

        while state.clock_remaining > 0:
            drive_result = simulate_drive(state, simulation_input, rng=rng, profile=profile)
            drive_log.append(drive_result.to_dict())
            possession_log.extend(step.to_dict() for step in drive_result.steps)
            quarter_possession_count += 1
            quarter_drive_count += 1
            state = drive_result.end_state

            if state.clock_remaining <= 0:
                break

        quarter_log.append(
            {
                "quarter": quarter,
                "start_clock": quarter_start_clock,
                "end_clock": state.clock_remaining,
                "home_points": state.score_home - quarter_home_points_start,
                "away_points": state.score_away - quarter_away_points_start,
                "drive_count": quarter_drive_count,
                "possession_count": quarter_possession_count,
            }
        )

        if quarter < simulation_input.quarters:
            state = advance_quarter(state, quarter_seconds=simulation_input.quarter_seconds)
            quarter_start_clock = simulation_input.quarter_seconds
            continue

        if state.score_home == state.score_away:
            ot_owner = "away" if state.possession_owner == "home" else "home"
            state = replace(state, possession_owner=ot_owner, field_position=25, down=1, distance=10)
            overtime_cap = 2
            overtime_rounds = 0
            while state.score_home == state.score_away and overtime_rounds < overtime_cap:
                overtime_rounds += 1
                state = replace(state, quarter=state.quarter + 1, clock_remaining=simulation_input.quarter_seconds)
                drive_result = simulate_drive(state, simulation_input, rng=rng, profile=profile)
                drive_log.append(drive_result.to_dict())
                possession_log.extend(step.to_dict() for step in drive_result.steps)
                state = drive_result.end_state
                if state.score_home != state.score_away:
                    break

    final_score = {"home": state.score_home, "away": state.score_away}
    drive_log = _merge_quarter_carryover_drives(drive_log)
    win_probability = _final_win_probability(state.score_home, state.score_away)
    spread = _spread(state.score_home, state.score_away)
    total = _total(state.score_home, state.score_away)
    distribution_summary = {
        "quarter_totals": [quarter_entry["home_points"] + quarter_entry["away_points"] for quarter_entry in quarter_log],
        "drive_count": len(drive_log),
        "possession_count": len(possession_log),
    }
    compatibility_summary = {
        "projected_final_score": final_score,
        "projected_spread": spread,
        "projected_total": total,
        "feature_generation_payload_present": bool(simulation_input.feature_generation_payload),
    }

    output = SmartSim2SimulationOutput(
        simulation_kind="smartsim2_possession",
        seed=simulation_input.seed,
        input_state=simulation_input.to_dict(),
        possession_log=tuple(possession_log),
        drive_log=tuple(drive_log),
        quarter_log=tuple(quarter_log),
        final_score=final_score,
        win_probability=win_probability,
        spread=spread,
        total=total,
        distribution_summary=distribution_summary,
        compatibility_summary=compatibility_summary,
        final_state=state.to_dict(),
    )
    return output


GameResult = SmartSim2SimulationOutput
