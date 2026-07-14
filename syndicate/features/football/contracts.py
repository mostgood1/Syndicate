from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FootballTeamFeatures:
    sport: str
    date: str
    team_id: str
    team_name: str
    team_abbr: str
    offensive_metrics: dict[str, Any] = field(default_factory=dict)
    defensive_metrics: dict[str, Any] = field(default_factory=dict)
    pace_metrics: dict[str, Any] = field(default_factory=dict)
    market_features: dict[str, Any] = field(default_factory=dict)
    adapter_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FootballGameFeatures:
    sport: str
    date: str
    game_id: str
    home_team: str
    away_team: str
    team_metrics: dict[str, Any] = field(default_factory=dict)
    defensive_metrics: dict[str, Any] = field(default_factory=dict)
    advanced_metrics: dict[str, Any] = field(default_factory=dict)
    matchup_metrics: dict[str, Any] = field(default_factory=dict)
    market_features: dict[str, Any] = field(default_factory=dict)
    pace_features: dict[str, Any] = field(default_factory=dict)
    epa_per_play: float | None = None
    success_rate_value: float | None = None
    proe_value: float | None = None
    red_zone_efficiency_value: float | None = None
    explosive_play_rate_value: float | None = None
    home_team_features: FootballTeamFeatures | None = None
    away_team_features: FootballTeamFeatures | None = None
    adapter_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FootballPlayerFeatures:
    sport: str
    date: str
    player_id: str
    player_name: str
    team: str
    position: str
    usage_metrics: dict[str, Any] = field(default_factory=dict)
    market_features: dict[str, Any] = field(default_factory=dict)
    adapter_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FootballSimulationInput:
    sport: str
    date: str
    games: tuple[FootballGameFeatures, ...] = ()
    players: tuple[FootballPlayerFeatures, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    adapter_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FootballSimulationOutput:
    sport: str
    date: str
    win_probability: dict[str, float | None] = field(default_factory=dict)
    expected_spread: dict[str, Any] = field(default_factory=dict)
    expected_total: dict[str, Any] = field(default_factory=dict)
    confidence: float | None = None
    distribution_summary: dict[str, Any] = field(default_factory=dict)
    game_outputs: tuple[dict[str, Any], ...] = ()
    player_outputs: tuple[dict[str, Any], ...] = ()
    artifacts: dict[str, Any] = field(default_factory=dict)
    evaluation: dict[str, Any] = field(default_factory=dict)
    adapter_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FootballEvaluationRecord:
    sport: str
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


@dataclass(frozen=True)
class FootballSeasonEvaluation:
    sport: str
    season: int
    records: tuple[FootballEvaluationRecord, ...] = ()
    sim_vs_actual: dict[str, Any] = field(default_factory=dict)
    calibration: dict[str, Any] = field(default_factory=dict)
    brier: float | None = None
    roi: float | None = None
    clv: float | None = None
    win_rate: float | None = None
    adapter_metadata: dict[str, Any] = field(default_factory=dict)