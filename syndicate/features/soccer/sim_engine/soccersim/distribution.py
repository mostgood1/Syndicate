from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from statistics import mean
from typing import Any

from syndicate.features.soccer.sim_engine.soccersim.calibration_profile import CalibrationProfile
from syndicate.features.soccer.sim_engine.soccersim.calibration_profile import SOCCER_CALIBRATION_PROFILE
from syndicate.features.soccer.sim_engine.soccersim.contracts import PossessionState
from syndicate.features.soccer.sim_engine.soccersim.contracts import SoccerSimSimulationInput
from syndicate.features.soccer.sim_engine.soccersim.match_simulator import simulate_match


@dataclass(frozen=True)
class MatchDistributionSummary:
    simulations: int
    home_win_probability: float
    draw_probability: float
    away_win_probability: float
    mean_home_goals: float
    mean_away_goals: float
    mean_total: float
    mean_margin: float
    over_2_5_probability: float
    both_teams_scored_probability: float
    scoreline_probabilities: dict[str, float]
    # Per-team volume aggregates: the allocation base for player props.
    mean_home_shots: float = 0.0
    mean_away_shots: float = 0.0
    mean_home_shots_on_target: float = 0.0
    mean_away_shots_on_target: float = 0.0
    mean_home_corners: float = 0.0
    mean_away_corners: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "simulations": self.simulations,
            "home_win_probability": self.home_win_probability,
            "draw_probability": self.draw_probability,
            "away_win_probability": self.away_win_probability,
            "mean_home_goals": self.mean_home_goals,
            "mean_away_goals": self.mean_away_goals,
            "mean_total": self.mean_total,
            "mean_margin": self.mean_margin,
            "over_2_5_probability": self.over_2_5_probability,
            "both_teams_scored_probability": self.both_teams_scored_probability,
            "scoreline_probabilities": dict(self.scoreline_probabilities),
            "mean_home_shots": self.mean_home_shots,
            "mean_away_shots": self.mean_away_shots,
            "mean_home_shots_on_target": self.mean_home_shots_on_target,
            "mean_away_shots_on_target": self.mean_away_shots_on_target,
            "mean_home_corners": self.mean_home_corners,
            "mean_away_corners": self.mean_away_corners,
        }


def simulate_match_distribution(
    simulation_input: SoccerSimSimulationInput,
    *,
    simulations: int = 500,
    profile: CalibrationProfile = SOCCER_CALIBRATION_PROFILE,
) -> MatchDistributionSummary:
    """Aggregate many seeded single-match simulations into market-facing
    probabilities: three-way result, totals, and scoreline distribution.

    Seeds are derived deterministically from the input seed, so the whole
    distribution is reproducible the same way single runs are.
    """
    simulations = max(1, int(simulations))
    base_seed = simulation_input.seed if simulation_input.seed is not None else 1
    home_wins = 0
    draws = 0
    away_wins = 0
    over_2_5 = 0
    both_scored = 0
    home_goals: list[float] = []
    away_goals: list[float] = []
    scoreline_counts: dict[str, int] = {}
    home_shots = 0
    away_shots = 0
    home_shots_on_target = 0
    away_shots_on_target = 0
    home_corners = 0
    away_corners = 0

    for offset in range(simulations):
        seeded_input = replace(simulation_input, seed=base_seed + offset)
        output = simulate_match(seeded_input, profile=profile)
        home = int(output.final_score["home"])
        away = int(output.final_score["away"])
        home_goals.append(float(home))
        away_goals.append(float(away))
        for possession in output.possession_log:
            start_state = possession.get("start_state") or {}
            owner = str(start_state.get("possession_owner") or "")
            if owner == "home":
                home_shots += 1 if possession.get("shot_taken") else 0
                home_shots_on_target += 1 if possession.get("shot_on_target") else 0
                home_corners += int(possession.get("corner_count") or 0)
            elif owner == "away":
                away_shots += 1 if possession.get("shot_taken") else 0
                away_shots_on_target += 1 if possession.get("shot_on_target") else 0
                away_corners += int(possession.get("corner_count") or 0)
        if home > away:
            home_wins += 1
        elif away > home:
            away_wins += 1
        else:
            draws += 1
        if home + away >= 3:
            over_2_5 += 1
        if home > 0 and away > 0:
            both_scored += 1
        scoreline = f"{home}-{away}"
        scoreline_counts[scoreline] = scoreline_counts.get(scoreline, 0) + 1

    scoreline_probabilities = {
        scoreline: round(count / simulations, 4)
        for scoreline, count in sorted(scoreline_counts.items(), key=lambda item: item[1], reverse=True)
    }
    mean_home = mean(home_goals)
    mean_away = mean(away_goals)
    return MatchDistributionSummary(
        simulations=simulations,
        home_win_probability=round(home_wins / simulations, 4),
        draw_probability=round(draws / simulations, 4),
        away_win_probability=round(away_wins / simulations, 4),
        mean_home_goals=round(mean_home, 4),
        mean_away_goals=round(mean_away, 4),
        mean_total=round(mean_home + mean_away, 4),
        mean_margin=round(mean_home - mean_away, 4),
        over_2_5_probability=round(over_2_5 / simulations, 4),
        both_teams_scored_probability=round(both_scored / simulations, 4),
        scoreline_probabilities=scoreline_probabilities,
        mean_home_shots=round(home_shots / simulations, 4),
        mean_away_shots=round(away_shots / simulations, 4),
        mean_home_shots_on_target=round(home_shots_on_target / simulations, 4),
        mean_away_shots_on_target=round(away_shots_on_target / simulations, 4),
        mean_home_corners=round(home_corners / simulations, 4),
        mean_away_corners=round(away_corners / simulations, 4),
    )


__all__ = ["MatchDistributionSummary", "simulate_match_distribution"]
