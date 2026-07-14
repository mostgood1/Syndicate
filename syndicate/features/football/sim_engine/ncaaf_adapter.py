from __future__ import annotations

from dataclasses import dataclass

from syndicate.features.football.sim_engine.football_core import build_football_simulation_adapter


@dataclass(frozen=True)
class NcaafAdapter:
    def build(self):
        return build_football_simulation_adapter("ncaaf")