from __future__ import annotations

from random import Random

from syndicate.features.soccer.sim_engine.soccersim.calibration_profile import CalibrationProfile
from syndicate.features.soccer.sim_engine.soccersim.contracts import SoccerSimSimulationInput
from syndicate.features.soccer.sim_engine.soccersim.contracts import SoccerSimSimulationOutput
from syndicate.features.soccer.sim_engine.soccersim.distribution import MatchDistributionSummary
from syndicate.features.soccer.sim_engine.soccersim.distribution import simulate_match_distribution
from syndicate.features.soccer.sim_engine.soccersim.league_profiles import get_league_profile
from syndicate.features.soccer.sim_engine.soccersim.match_simulator import simulate_match


def resolve_league_profile(league: str | None) -> CalibrationProfile:
    return get_league_profile(league)


def simulate_league_match(
    simulation_input: SoccerSimSimulationInput,
    *,
    league: str | None = None,
    rng: Random | None = None,
) -> SoccerSimSimulationOutput:
    return simulate_match(simulation_input, rng=rng, profile=get_league_profile(league))


def simulate_league_match_distribution(
    simulation_input: SoccerSimSimulationInput,
    *,
    league: str | None = None,
    simulations: int = 500,
) -> MatchDistributionSummary:
    return simulate_match_distribution(
        simulation_input, simulations=simulations, profile=get_league_profile(league)
    )


__all__ = ["resolve_league_profile", "simulate_league_match", "simulate_league_match_distribution"]
