"""Feature / IO contracts for the ``hockeysim`` engine (the ingestion <-> engine boundary).

Mirrors ``soccersim.contracts`` / football ``contracts.py``: frozen dataclasses that decouple the
data-loaders (Phase 2 ``features/loaders.py``, fed by ``syndicate.local_nhl_odds``) from the
engine internals, and that carry exactly the fields the existing NHL artifact CSVs need so the
adapter can emit a byte-compatible ``predictions_{date}.csv`` / ``props_recommendations_{date}.csv``
and the UI (``syndicate/features/nhl/cards.py``) needs no change.

These are pure data holders — no simulation logic lives here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class HockeyTeamFeatures:
    """Pregame team-strength inputs for one side."""
    name: str
    abbrev: Optional[str] = None
    # Per-60 rates consumed by the boxscore engine (models.TeamRates).
    shots_per_60: float = 30.0
    goals_per_60: float = 2.9
    blocks_per_60: float = 12.0
    penalties_per_60: float = 3.0
    faceoff_win_pct: float = 0.5
    # Expected-goals rates (5v5+all-situations blend) consumed by the projection layer
    # (``projection.project_game``). Optional: when absent the projection falls back to
    # ``goals_per_60`` for offense and the league baseline for defense.
    xgf_per_60: Optional[float] = None
    xga_per_60: Optional[float] = None
    # Optional Elo rating (used to blend a rating-based win prob into the projection seed).
    elo_rating: Optional[float] = None
    # Per-period expected goals [P1, P2, P3] consumed by the fast game-market sim.
    period_goal_lambdas: Tuple[float, float, float] = (0.9, 0.95, 1.05)
    # Special-teams context (pp/pk pct + committed/drawn per game).
    special_teams: Dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class HockeyPlayerFeatures:
    """One skater/goalie's usage + propensity inputs for the boxscore engine."""
    player_id: int
    full_name: str
    position: str  # F / D / G
    proj_toi: float = 0.0
    shot_weight: Optional[float] = None
    goal_weight: Optional[float] = None
    block_weight: Optional[float] = None
    line_slot: Optional[str] = None  # L1..L4 / D1..D3
    pp_unit: Optional[int] = None
    pk_unit: Optional[int] = None
    is_starting_goalie: bool = False

    def roster_row(self) -> Dict:
        """Convert to the list[dict] roster row shape the engine consumes."""
        return {
            "player_id": int(self.player_id),
            "full_name": self.full_name,
            "position": self.position,
            "proj_toi": float(self.proj_toi or 0.0),
            "shot_weight": self.shot_weight,
            "goal_weight": self.goal_weight,
            "block_weight": self.block_weight,
        }

    def lineup_row(self) -> Dict:
        """Convert to the list[dict] lineup row shape (line/PP/PK slots)."""
        return {
            "player_id": int(self.player_id),
            "line_slot": self.line_slot,
            "pp_unit": self.pp_unit,
            "pk_unit": self.pk_unit,
        }


@dataclass(frozen=True)
class HockeyMarketLines:
    """Captured book lines/odds for a game (American odds), used for EV + line-anchored sims."""
    total_line: Optional[float] = None
    puck_line: float = -1.5
    home_ml_odds: Optional[int] = None
    away_ml_odds: Optional[int] = None
    over_odds: Optional[int] = None
    under_odds: Optional[int] = None
    home_pl_odds: Optional[int] = None
    away_pl_odds: Optional[int] = None
    # Optional market-implied home win probability (devigged) for Phase-4 anchoring.
    home_win_probability: Optional[float] = None


@dataclass(frozen=True)
class HockeyGameFeatures:
    """Full pregame feature bundle for a single game."""
    game_pk: str
    date: str
    home: HockeyTeamFeatures
    away: HockeyTeamFeatures
    home_players: Tuple[HockeyPlayerFeatures, ...] = ()
    away_players: Tuple[HockeyPlayerFeatures, ...] = ()
    market: HockeyMarketLines = field(default_factory=HockeyMarketLines)


@dataclass(frozen=True)
class HockeyGamePrediction:
    """Aggregated game-market output — maps 1:1 onto ``predictions_{date}.csv`` columns."""
    home: str
    away: str
    date: str
    game_pk: str
    proj_home_goals: float
    proj_away_goals: float
    model_total: float
    model_spread: float
    period_home_proj: Tuple[float, float, float]
    period_away_proj: Tuple[float, float, float]
    p_home_ml: float
    p_away_ml: float
    p_over: float
    p_under: float
    p_push_total: float
    p_home_pl_minus_1_5: float
    p_away_pl_plus_1_5: float
    p_f10_yes: float
    p_f10_no: float
    totals_line_used: Optional[float] = None
    # EV fields (filled when market odds are present).
    ev: Dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class HockeyPropProjection:
    """One player-market projection — maps onto ``props_recommendations_{date}.csv`` rows."""
    date: str
    player_id: int
    player: str
    team: str
    opp: str
    market: str  # SOG / GOALS / ASSISTS / POINTS / SAVES / BLOCKS
    proj_lambda: float
    proj: float
    line: Optional[float] = None
    p_over: Optional[float] = None
    p_under: Optional[float] = None


@dataclass(frozen=True)
class HockeyEvaluationRecord:
    """Settled-outcome record for the evaluation/calibration lanes (Phase 3/9)."""
    date: str
    game_pk: str
    market: str
    selection: str
    model_probability: float
    result: Optional[str] = None  # win / loss / push
    closing_line: Optional[float] = None
    pnl: Optional[float] = None
