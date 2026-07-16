from __future__ import annotations

from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationInput
from syndicate.features.football.sim_engine.smartsim2.game_simulator import simulate_game


def run_smartsim2_simulation(simulation_input: SmartSim2SimulationInput):
    return simulate_game(simulation_input)
