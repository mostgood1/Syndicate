from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SoccerTeamFeatures:
    league: str
    date: str
    team_id: str
    team_name: str
    team_abbr: str
    attacking_metrics: dict[str, Any] = field(default_factory=dict)
    defensive_metrics: dict[str, Any] = field(default_factory=dict)
    possession_metrics: dict[str, Any] = field(default_factory=dict)
    set_piece_metrics: dict[str, Any] = field(default_factory=dict)
    market_features: dict[str, Any] = field(default_factory=dict)
    adapter_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SoccerMatchFeatures:
    league: str
    date: str
    match_id: str
    home_team: str
    away_team: str
    team_metrics: dict[str, Any] = field(default_factory=dict)
    defensive_metrics: dict[str, Any] = field(default_factory=dict)
    possession_metrics: dict[str, Any] = field(default_factory=dict)
    set_piece_metrics: dict[str, Any] = field(default_factory=dict)
    market_features: dict[str, Any] = field(default_factory=dict)
    tempo_features: dict[str, Any] = field(default_factory=dict)
    knockout: bool = False
    home_team_features: SoccerTeamFeatures | None = None
    away_team_features: SoccerTeamFeatures | None = None
    # Confirmed/projected lineup for props allocation: player_id values (or
    # "name:<lowercased player_name>" for id-less rows). Empty means no
    # lineup is known -- allocation falls back to per-player `is_starter`
    # tags if present, else season-long usage rates. See
    # soccersim.player_props.build_usage_profiles.
    home_starter_ids: tuple[str, ...] = ()
    away_starter_ids: tuple[str, ...] = ()
    adapter_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SoccerPlayerFeatures:
    league: str
    date: str
    player_id: str
    player_name: str
    team: str
    position: str
    usage_metrics: dict[str, Any] = field(default_factory=dict)
    market_features: dict[str, Any] = field(default_factory=dict)
    adapter_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SoccerSimulationInput:
    league: str
    date: str
    matches: tuple[SoccerMatchFeatures, ...] = ()
    players: tuple[SoccerPlayerFeatures, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    adapter_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SoccerSimulationOutput:
    league: str
    date: str
    win_probability: dict[str, float | None] = field(default_factory=dict)
    expected_spread: dict[str, Any] = field(default_factory=dict)
    expected_total: dict[str, Any] = field(default_factory=dict)
    confidence: float | None = None
    distribution_summary: dict[str, Any] = field(default_factory=dict)
    match_outputs: tuple[dict[str, Any], ...] = ()
    player_outputs: tuple[dict[str, Any], ...] = ()
    artifacts: dict[str, Any] = field(default_factory=dict)
    evaluation: dict[str, Any] = field(default_factory=dict)
    adapter_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SoccerEvaluationRecord:
    league: str
    season: int | None
    date: str
    simulation_kind: str
    calibration: dict[str, Any] = field(default_factory=dict)
    sim_vs_actual: dict[str, Any] = field(default_factory=dict)
    prop_accuracy: dict[str, Any] = field(default_factory=dict)
    brier: float | None = None
    roi: float | None = None
    clv: float | None = None
    win_rate: float | None = None
    adapter_metadata: dict[str, Any] = field(default_factory=dict)
