"""Syndicate-owned basketball possession engine (NBA, WNBA; NCAAB hooks).

Plan phase P1 of docs/ai_context/basketball_live_native_plan.md. It replaces
vendor/{nba,wnba}_betting_repo/src/*/sim/events.py at runtime. See engine.py
for what changed against the vendored engines, and resume.py for the live
GameState.
"""

from .engine import (
    EventSimConfig,
    sample_lineup_minutes_weighted,
    simulate_event_level_boxscore,
    simulate_pbp_game_boxscore,
)
from .league import NBA, NCAAB, WNBA, LeagueParams, league_params
from .resume import GameState

__all__ = [
    "EventSimConfig",
    "GameState",
    "LeagueParams",
    "NBA",
    "NCAAB",
    "WNBA",
    "league_params",
    "sample_lineup_minutes_weighted",
    "simulate_event_level_boxscore",
    "simulate_pbp_game_boxscore",
]
