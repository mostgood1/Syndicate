"""Syndicate's smart-sim ORCHESTRATOR (plan P6): one league-parametric orchestrator (nba, wnba; ncaab hook).

It replaces ``vendor/{nba,wnba}_betting_repo/src/*/sim/smart_sim.py:simulate_smart_game`` and every
vendored function that call executed (quarters, connected_game, boxscores, prob_calibration,
prop_ladders, roster_files, player names). The generated modules are produced by
``scripts/port_basketball_orchestrator.py``; ``runtime.py``, ``hooks.py`` and ``view.py`` are hand-written.

    orch = OrchestratorEnv.for_processed_root(processed_root, league_code)
    out = simulate_smart_game(date_str=..., home_tri=..., away_tri=..., props_df=..., cfg=..., orch=orch)
"""

from .runtime import NBA, WNBA, OrchestratorEnv, OrchestratorLeague, SmartSimPaths, orchestrator_league
from .smart_sim import SmartSimConfig, simulate_smart_game
from .view import module_view

__all__ = [
    "NBA",
    "WNBA",
    "OrchestratorEnv",
    "OrchestratorLeague",
    "SmartSimConfig",
    "SmartSimPaths",
    "module_view",
    "orchestrator_league",
    "simulate_smart_game",
]
