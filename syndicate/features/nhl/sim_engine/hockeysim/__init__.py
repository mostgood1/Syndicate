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

from .adapters import (
    american_to_decimal,
    american_to_implied,
    build_game_prediction,
    ev_per_unit,
    game_seed,
)
from .calibration_profile import NHL_CALIBRATION_PROFILE, build_nhl_sim_config
from .contracts import (
    HockeyEvaluationRecord,
    HockeyGameFeatures,
    HockeyGamePrediction,
    HockeyMarketLines,
    HockeyPlayerFeatures,
    HockeyPropProjection,
    HockeyTeamFeatures,
)
from .engine import GameSimulator, PeriodSimulator, PossessionSimulator, SimConfig
from .game_market_sim import simulate_from_period_lambdas, simulate_from_totals_diff
from .models import PlayerRates, RateModels, TeamRates
from .player_props import build_prop_projections
from .props_boxscore import aggregate_events_to_boxscores_fast
from .runtime import run_hockeysim_game
from .state import Event, GameState, PlayerState, TeamState

__all__ = [
    # engine + runtime
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
    # game-market sim
    "simulate_from_period_lambdas",
    "simulate_from_totals_diff",
    # contracts
    "HockeyTeamFeatures",
    "HockeyPlayerFeatures",
    "HockeyMarketLines",
    "HockeyGameFeatures",
    "HockeyGamePrediction",
    "HockeyPropProjection",
    "HockeyEvaluationRecord",
    # adapter
    "build_game_prediction",
    "game_seed",
    "american_to_decimal",
    "american_to_implied",
    "ev_per_unit",
    # props
    "build_prop_projections",
    "aggregate_events_to_boxscores_fast",
]
