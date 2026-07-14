from __future__ import annotations

from syndicate.features.football.adapters import FootballSimulationAdapter


def build_football_simulation_adapter(sport: str) -> FootballSimulationAdapter:
    return FootballSimulationAdapter(sport=sport)