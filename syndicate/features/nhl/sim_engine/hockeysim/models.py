"""Team/player rate models for the hockey sim (Syndicate-owned).

Absorbed verbatim from the user's own ``nhl_betting`` engine (``vendor/nhl_betting_repo``)
into Syndicate's local ``hockeysim`` engine. See ``state.py`` for the migration note.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class TeamRates:
    shots_per_60: float = 30.0
    goals_per_60: float = 2.9
    # Pregame team-level faceoff win percentage (0..1). Used as a mild possession/shot-share signal.
    faceoff_win_pct: float = 0.5
    # `blocks_per_60` / `penalties_per_60` REMOVED (`docs/ai_context/hockeysim_engine_reference.md`
    # §2l) -- confirmed dead: nothing in `engine.py` ever read either field. Block volume is fully
    # governed by the truth-calibrated per-shot `block_rate_*` mechanism; penalty rate already
    # drives PP/PK segment generation via `special_teams`'s `committed_per_game`.


@dataclass
class PlayerRates:
    shots_share: float = 0.05  # fraction of team shots
    goals_share: float = 0.05  # fraction of team goals
    blocks_share: float = 0.05  # fraction of team blocks
    saves_share: float = 1.0  # for goalies, fraction of opponent shots saved


@dataclass
class RateModels:
    home: TeamRates
    away: TeamRates
    player_rates: Dict[int, PlayerRates]

    @staticmethod
    def baseline(base_mu: float = 3.0) -> "RateModels":
        # Simple baseline: adjust goals per 60 around base_mu; shots approx 30/60
        home = TeamRates(shots_per_60=31.0, goals_per_60=base_mu)
        away = TeamRates(shots_per_60=30.0, goals_per_60=base_mu)
        return RateModels(home=home, away=away, player_rates={})
