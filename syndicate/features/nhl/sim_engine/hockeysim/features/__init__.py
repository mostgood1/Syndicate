"""hockeysim feature-loaders package.

Assembles the frozen engine contracts (``hockeysim.contracts``) from Syndicate-owned NHL data
(``syndicate.local_nhl_odds`` + the mirrored ``data/nhl_source`` processed artifacts), then runs
the projection layer so downstream engines/adapters receive per-period goal lambdas.
"""
from __future__ import annotations

from .coverage import (
    GameDataCoverage,
    SlateDataCoverage,
    TeamDataCoverage,
    build_game_coverage,
    build_slate_coverage,
)
from .loaders import (
    build_game_features,
    build_player_features,
    build_slate_features,
    build_team_features,
    load_lineups,
    load_starting_goalies,
    load_team_xg_map,
    nhl_source_root,
)

__all__ = [
    "nhl_source_root",
    "load_team_xg_map",
    "load_lineups",
    "load_starting_goalies",
    "build_team_features",
    "build_player_features",
    "build_game_features",
    "build_slate_features",
    # coverage / data-gap audit
    "build_slate_coverage",
    "build_game_coverage",
    "SlateDataCoverage",
    "GameDataCoverage",
    "TeamDataCoverage",
]
