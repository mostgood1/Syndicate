from __future__ import annotations

from syndicate.features.soccer.sim_engine.soccersim.contracts import SoccerSimSimulationInput
from syndicate.features.soccer.sim_engine.soccersim.match_simulator import simulate_match


def run_soccersim_simulation(simulation_input: SoccerSimSimulationInput):
    return simulate_match(simulation_input)
