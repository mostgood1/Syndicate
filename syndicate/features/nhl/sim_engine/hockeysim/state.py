"""Hockey simulation state primitives (Syndicate-owned).

Absorbed from the user's own ``nhl_betting`` engine (``vendor/nhl_betting_repo``) as part
of the NHL end-to-end revamp that gives Syndicate a fully-local hockey sim engine
(``hockeysim``), mirroring the football ``smartsim2`` and ``soccersim`` packages. Logic is
preserved verbatim from the source; only the module home changed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


# League A/(onGF-G) by position, 2024-25 regular season, NHL stats `skater/goalsForAgainst` pooled
# over every skater (F 0.5029, D 0.3191) `[2026-10-05, lane nhl-elite-assists]`. The shrinkage prior
# for `PlayerState.assist_share`, and the engine's value for a player whose share is unknown.
ASSIST_SHARE_PRIOR = {"F": 0.503, "D": 0.319}


@dataclass
class PlayerState:
    player_id: int
    full_name: str
    position: str  # F/D/G
    team: str
    toi_proj: float = 0.0
    # projected EVEN-STRENGTH minutes; None = unknown (EV rotation then uses toi_proj)
    ev_toi_proj: Optional[float] = None
    # as-of ASSISTS PER TEAMMATE GOAL while on ice, A/(onGF-G), shrunk to ASSIST_SHARE_PRIOR; None = unknown
    assist_share: Optional[float] = None
    # Weights to bias event attribution while on ice
    shot_weight: float = 0.0
    goal_weight: float = 0.0
    block_weight: float = 0.0
    stats: Dict[str, float] = field(default_factory=dict)  # shots, goals, assists, blocks, saves


@dataclass
class TeamState:
    name: str
    abbrev: Optional[str] = None
    score: int = 0
    shots: int = 0
    penalties: int = 0
    players: Dict[int, PlayerState] = field(default_factory=dict)


@dataclass
class GameState:
    home: TeamState
    away: TeamState
    period: int = 0
    clock: int = 20 * 60  # seconds remaining in current period
    events: List["Event"] = field(default_factory=list)


@dataclass
class Event:
    t: float  # absolute seconds since start
    period: int
    team: str  # team name
    kind: str  # faceoff|shot|goal|block|penalty|save|turnover|shift
    player_id: Optional[int] = None
    meta: Dict[str, float] = field(default_factory=dict)
