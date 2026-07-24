"""hockeysim — Syndicate's local NHL simulation engine.

Absorbed from the user's own ``nhl_betting`` engine (``vendor/nhl_betting_repo``) and
restructured to the ``smartsim2`` / ``soccersim`` package conventions as part of the NHL
end-to-end revamp. One simulator; calibration differences live in ``calibration_profile``;
``runtime.run_hockeysim_game`` is the public entry point.

Public API:
    run_hockeysim_game        -> single deterministic game (GameState, events)
    NHL_CALIBRATION_PROFILE   -> canonical baseline SimConfig
    build_nhl_sim_config      -> per-run config (seed + calibration overrides)
    GameSimulator, SimConfig  -> engine internals (advanced callers/tests)
    RateModels, TeamRates, PlayerRates
    GameState, TeamState, PlayerState, Event
"""
from __future__ import annotations

from .calibration_profile import NHL_CALIBRATION_PROFILE, build_nhl_sim_config
from .engine import GameSimulator, PeriodSimulator, PossessionSimulator, SimConfig
from .models import PlayerRates, RateModels, TeamRates
from .runtime import run_hockeysim_game
from .state import Event, GameState, PlayerState, TeamState

__all__ = [
    "run_hockeysim_game",
    "NHL_CALIBRATION_PROFILE",
    "build_nhl_sim_config",
    "GameSimulator",
    "PeriodSimulator",
    "PossessionSimulator",
    "SimConfig",
    "RateModels",
    "TeamRates",
    "PlayerRates",
    "GameState",
    "TeamState",
    "PlayerState",
    "Event",
]
