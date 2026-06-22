"""
Context: Syndicate Simulation System
See: docs/ai_context/architecture.md

Role:
- Runs Monte Carlo simulation and produces projections, variance, and distributions.

Constraints:
- State-driven execution
- Avoid redundant computation
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from math import sqrt
import random
from typing import Any, Mapping


def _copy_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _coerce_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except Exception:
        return None


def _safe_int(value: Any) -> int | None:
    numeric = _coerce_float(value)
    if numeric is None:
        return None
    try:
        return int(round(numeric))
    except Exception:
        return None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / float(len(values))


def _variance(values: list[float], mean_value: float | None = None) -> float | None:
    if not values:
        return None
    if mean_value is None:
        mean_value = _mean(values)
    if mean_value is None:
        return None
    return sum((value - mean_value) ** 2 for value in values) / float(len(values))


def _distribution_summary(values: list[float]) -> dict[str, float | None]:
    mean_value = _mean(values)
    variance_value = _variance(values, mean_value)
    std_dev_value = sqrt(variance_value) if variance_value is not None else None
    return {
        "mean": round(mean_value, 4) if mean_value is not None else None,
        "variance": round(variance_value, 4) if variance_value is not None else None,
        "std_dev": round(std_dev_value, 4) if std_dev_value is not None else None,
    }


def _coerce_sequence(value: Any) -> list[Any]:
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def _extract_projection_name(projection: Mapping[str, Any], fallback: str) -> str:
    for key in ("player", "player_name", "name", "selection", "label", "id"):
        text = str(projection.get(key) or "").strip()
        if text:
            return text
    return fallback


def _extract_projection_stat_name(projection: Mapping[str, Any]) -> str:
    for key in ("stat", "market", "metric", "prop", "type"):
        text = str(projection.get(key) or "").strip()
        if text:
            return text
    return "stat"


def _projection_value(projection: Mapping[str, Any]) -> float | None:
    for key in ("projection", "projected", "mean", "value", "line", "average", "avg"):
        numeric = _coerce_float(projection.get(key))
        if numeric is not None:
            return numeric
    return None


def _modifiers_for_key(modifiers: Mapping[str, Any], key: str) -> dict[str, Any]:
    if not isinstance(modifiers, Mapping):
        return {}
    if key in modifiers and isinstance(modifiers.get(key), Mapping):
        return dict(modifiers.get(key) or {})
    return {}


def _modifier_scale(modifiers: Mapping[str, Any], key: str, *, default: float = 1.0) -> float:
    specific = _modifiers_for_key(modifiers, key)
    for candidate_key in ("scale", "multiplier", "factor"):
        numeric = _coerce_float(specific.get(candidate_key))
        if numeric is not None and numeric > 0:
            return numeric
    numeric = _coerce_float(modifiers.get(key))
    if numeric is not None and numeric > 0:
        return numeric
    return default


def _modifier_shift(modifiers: Mapping[str, Any], key: str, *, default: float = 0.0) -> float:
    specific = _modifiers_for_key(modifiers, key)
    for candidate_key in ("shift", "bias", "delta", "adjustment"):
        numeric = _coerce_float(specific.get(candidate_key))
        if numeric is not None:
            return numeric
    numeric = _coerce_float(modifiers.get(key))
    if numeric is not None:
        return numeric
    return default


def _baseline_std_dev(stat_name: str, projection_value: float | None, context: Mapping[str, Any]) -> float:
    stat = str(stat_name or "").strip().lower()
    sport = str(context.get("sport") or "").strip().lower()
    base_value = projection_value if projection_value is not None else _coerce_float(context.get("average")) or 0.0

    if any(token in stat for token in ("points", "runs", "yards", "rebounds", "assists", "shots", "saves", "goals", "hits", "rbi", "total_bases")):
        return max(0.75, abs(base_value) * 0.15)
    if any(token in stat for token in ("win", "loss", "moneyline", "spread", "total", "team_score", "score")):
        return max(1.5, abs(base_value) * 0.10)
    if sport in {"nba", "wnba", "ncaab"}:
        return max(1.25, abs(base_value) * 0.12)
    if sport in {"nfl", "ncaaf"}:
        return max(1.75, abs(base_value) * 0.14)
    if sport in {"mlb", "nhl"}:
        return max(1.0, abs(base_value) * 0.18)
    return max(1.0, abs(base_value) * 0.15)


def _simulate_normal(rng: random.Random, mean_value: float, std_dev: float, *, floor: float | None = None, ceiling: float | None = None) -> float:
    value = rng.normalvariate(mean_value, max(0.01, std_dev))
    if floor is not None:
        value = max(floor, value)
    if ceiling is not None:
        value = min(ceiling, value)
    return value


@dataclass(frozen=True)
class SimulationResult:
    outcome_distribution: dict[str, float]
    player_stat_distributions: dict[str, dict[str, dict[str, float | None]]]
    expected_values: dict[str, Any]
    variance: dict[str, Any]
    std_dev: dict[str, Any]
    inputs: dict[str, Any] = field(default_factory=dict)
    iterations: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome_distribution": dict(self.outcome_distribution),
            "player_stat_distributions": dict(self.player_stat_distributions),
            "expected_values": dict(self.expected_values),
            "variance": dict(self.variance),
            "std_dev": dict(self.std_dev),
            "iterations": self.iterations,
            "distribution": dict(self.outcome_distribution),
            "probability_distributions": dict(self.outcome_distribution),
            "inputs": dict(self.inputs),
        }


@dataclass(frozen=True)
class SimulationEngine:
    default_iterations: int = 1000

    def run_monte_carlo(self, game_context: Mapping[str, Any], iterations: int = 1000) -> SimulationResult:
        context = _copy_mapping(game_context)
        iteration_count = max(1, _safe_int(iterations) or self.default_iterations)
        rng = random.Random(_safe_int(context.get("seed")) or None)

        team_projections = _copy_mapping(context.get("team_projections"))
        player_projections = _coerce_sequence(context.get("player_projections"))
        matchup_modifiers = _copy_mapping(context.get("matchup_modifiers"))

        home_projection = _coerce_float(team_projections.get("home"))
        away_projection = _coerce_float(team_projections.get("away"))
        if home_projection is None:
            home_projection = _coerce_float(context.get("home_projection")) or _coerce_float(context.get("projection"))
        if away_projection is None:
            away_projection = _coerce_float(context.get("away_projection")) or _coerce_float(context.get("projection_opp"))

        base_probability = _coerce_float(context.get("model_probability"))
        if base_probability is None:
            base_probability = _coerce_float(context.get("confidence"))
        if base_probability is None:
            base_probability = 0.5
        base_probability = _clamp(base_probability, 0.01, 0.99)

        edge = _coerce_float(context.get("edge")) or 0.0
        win_probability = _clamp(base_probability + _clamp(edge, -0.12, 0.12), 0.01, 0.99)

        win_scores: list[float] = []
        loss_scores: list[float] = []
        push_scores: list[float] = []
        outcome_counts = {"win": 0, "loss": 0, "push": 0}

        team_std_dev = {
            "home": _baseline_std_dev("team_score", home_projection, context),
            "away": _baseline_std_dev("team_score", away_projection, context),
        }
        margin_bias = (win_probability - 0.5) * ((team_std_dev["home"] + team_std_dev["away"]) / 2.0)
        confidence = _clamp(_coerce_float(context.get("confidence")) or 0.5, 0.0, 1.0)
        margin_bias += (confidence - 0.5) * 0.5

        player_stat_values: dict[str, dict[str, list[float]]] = {}
        player_stat_meta: dict[str, dict[str, str]] = {}
        for projection in player_projections:
            if not isinstance(projection, Mapping):
                continue
            player_name = _extract_projection_name(projection, "player")
            stat_name = _extract_projection_stat_name(projection)
            projection_value = _projection_value(projection)
            if projection_value is None:
                continue

            player_modifiers = _modifiers_for_key(matchup_modifiers, player_name)
            stat_modifiers = _modifiers_for_key(player_modifiers, stat_name)
            combined_scale = _modifier_scale(stat_modifiers, stat_name, default=_modifier_scale(player_modifiers, stat_name, default=1.0))
            combined_shift = _modifier_shift(stat_modifiers, stat_name, default=_modifier_shift(player_modifiers, stat_name, default=0.0))
            adjusted_mean = (projection_value * combined_scale) + combined_shift
            adjusted_std_dev = _baseline_std_dev(stat_name, projection_value, context)
            adjusted_std_dev *= max(0.5, min(2.0, combined_scale))

            stat_bucket = player_stat_values.setdefault(player_name, {})
            stat_bucket.setdefault(stat_name, [])
            player_stat_meta[player_name] = {"player": player_name, "stat": stat_name}
            for _ in range(iteration_count):
                simulated_value = _simulate_normal(rng, adjusted_mean, adjusted_std_dev, floor=0.0)
                stat_bucket[stat_name].append(round(simulated_value, 4))

        for _ in range(iteration_count):
            home_score = _simulate_normal(
                rng,
                (home_projection if home_projection is not None else _coerce_float(context.get("line")) or 0.0) + margin_bias,
                team_std_dev["home"],
                floor=0.0,
            )
            away_score = _simulate_normal(
                rng,
                away_projection if away_projection is not None else _coerce_float(context.get("line_opp")) or 0.0,
                team_std_dev["away"],
                floor=0.0,
            )
            margin = home_score - away_score
            push_threshold = _coerce_float(context.get("push_threshold")) or 0.5

            if margin > push_threshold:
                outcome_counts["win"] += 1
                win_scores.append(margin)
            elif margin < -push_threshold:
                outcome_counts["loss"] += 1
                loss_scores.append(margin)
            else:
                outcome_counts["push"] += 1
                push_scores.append(margin)

        outcome_distribution = {
            key: round(count / float(iteration_count), 4)
            for key, count in outcome_counts.items()
        }

        player_distributions: dict[str, dict[str, dict[str, float | None]]] = {}
        for player_name, stat_map in player_stat_values.items():
            player_distributions[player_name] = {
                stat_name: _distribution_summary(values)
                for stat_name, values in stat_map.items()
            }

        expected_values = {
            "team_score": {
                "home": round(home_projection, 4) if home_projection is not None else None,
                "away": round(away_projection, 4) if away_projection is not None else None,
            },
            "margin": _distribution_summary(win_scores + loss_scores + push_scores),
            "players": {
                player_name: {
                    stat_name: summary.get("mean")
                    for stat_name, summary in stat_map.items()
                }
                for player_name, stat_map in player_distributions.items()
            },
        }

        variance = {
            "team_score": {
                "home": round(team_std_dev["home"] ** 2, 4),
                "away": round(team_std_dev["away"] ** 2, 4),
            },
            "outcome_margin": _distribution_summary(win_scores + loss_scores + push_scores).get("variance"),
            "players": {
                player_name: {
                    stat_name: summary.get("variance")
                    for stat_name, summary in stat_map.items()
                }
                for player_name, stat_map in player_distributions.items()
            },
        }

        std_dev = {
            "team_score": {
                "home": round(team_std_dev["home"], 4),
                "away": round(team_std_dev["away"], 4),
            },
            "outcome_margin": _distribution_summary(win_scores + loss_scores + push_scores).get("std_dev"),
            "players": {
                player_name: {
                    stat_name: summary.get("std_dev")
                    for stat_name, summary in stat_map.items()
                }
                for player_name, stat_map in player_distributions.items()
            },
        }

        inputs = {
            "sport": context.get("sport"),
            "market": context.get("market"),
            "selection": context.get("selection"),
            "line": context.get("current_line") or context.get("line"),
            "odds": context.get("odds"),
            "iterations": iteration_count,
        }

        return SimulationResult(
            outcome_distribution=outcome_distribution,
            player_stat_distributions=player_distributions,
            expected_values=expected_values,
            variance=variance,
            std_dev=std_dev,
            inputs=inputs,
            iterations=iteration_count,
        )

    def run_simulation(self, game_context: Mapping[str, Any]) -> dict[str, Any]:
        return self.run_monte_carlo(game_context, iterations=self.default_iterations).to_dict()


def run_monte_carlo(game_context: Mapping[str, Any], iterations: int = 1000) -> dict[str, Any]:
    return SimulationEngine(default_iterations=iterations).run_monte_carlo(game_context, iterations=iterations).to_dict()


__all__ = ["SimulationEngine", "SimulationResult", "run_monte_carlo"]