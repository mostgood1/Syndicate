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
from typing import Any, Mapping

import numpy as np


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


def _advanced_payload(context: Mapping[str, Any]) -> dict[str, Any]:
    advanced = _copy_mapping(context.get("advanced"))
    if advanced:
        return advanced
    modifiers = _copy_mapping(context.get("matchup_modifiers"))
    return _copy_mapping(modifiers.get("advanced"))


def _advanced_std_dev_scale(advanced: Mapping[str, Any]) -> float:
    if not isinstance(advanced, Mapping) or not advanced:
        return 1.0

    page = _copy_mapping(advanced.get("page"))
    game = _copy_mapping(advanced.get("game"))
    scale = 1.0

    lineup_health = _copy_mapping(page.get("lineup_health") or page.get("lineupHealth"))
    if lineup_health:
        if bool(lineup_health.get("healthy")):
            scale *= 0.97
        else:
            scale *= 1.06

    market_availability = _copy_mapping(page.get("marketAvailability"))
    market_warnings = market_availability.get("warnings") if isinstance(market_availability.get("warnings"), list) else []
    if market_warnings:
        scale *= min(1.12, 1.0 + (0.02 * len(market_warnings)))
    else:
        game_lines = _copy_mapping(market_availability.get("gameLines"))
        pitcher_props = _copy_mapping(market_availability.get("pitcherProps"))
        hitter_props = _copy_mapping(market_availability.get("hitterProps"))
        if bool(game_lines.get("available")) and bool(pitcher_props.get("available")) and bool(hitter_props.get("available")):
            scale *= 0.96
        else:
            scale *= 1.03

    hr_targets = _copy_mapping(page.get("hrTargets"))
    if int(hr_targets.get("rows") or 0) > 0 and isinstance(hr_targets.get("topRows"), list) and hr_targets.get("topRows"):
        scale *= 0.98
        top_rows = [row for row in hr_targets.get("topRows") if isinstance(row, Mapping)]
        if top_rows:
            top_row = top_rows[0]
            batter_xwoba = _coerce_float(top_row.get("batter_xwoba"))
            batter_hardhit_rate = _coerce_float(top_row.get("batter_hardhit_rate"))
            batter_barrel_rate = _coerce_float(top_row.get("batter_barrel_rate"))
            batter_launch_angle = _coerce_float(top_row.get("batter_launch_angle_mean") or top_row.get("launch_angle_mean") or top_row.get("la_mean"))
            pitcher_xwoba_allowed = _coerce_float(top_row.get("pitcher_xwoba_allowed"))
            pitch_mix_score = _coerce_float(top_row.get("pitch_mix_score"))

            if batter_xwoba is not None:
                scale *= 0.98 if batter_xwoba >= 0.34 else 1.01
            if batter_hardhit_rate is not None:
                scale *= 0.985 if batter_hardhit_rate >= 0.40 else 1.01
            if batter_barrel_rate is not None:
                scale *= 0.985 if batter_barrel_rate >= 0.07 else 1.01
            if batter_launch_angle is not None:
                scale *= 0.99 if 5.0 <= batter_launch_angle <= 30.0 else 1.01
            if pitcher_xwoba_allowed is not None:
                scale *= 0.985 if pitcher_xwoba_allowed <= 0.32 else 1.01
            if pitch_mix_score is not None:
                scale *= 0.985 if pitch_mix_score >= 1.0 else 1.01

    if isinstance(page.get("workflow"), Mapping):
        scale *= 0.99

    if isinstance(game.get("run_projection_rows"), list) and game.get("run_projection_rows"):
        scale *= 0.97
    if isinstance(game.get("segment_overview_cards"), list) and game.get("segment_overview_cards"):
        scale *= 0.98
    if isinstance(game.get("gameLens"), list) and game.get("gameLens"):
        scale *= 0.99
    if isinstance(game.get("first1BetSignal"), Mapping) and game.get("first1BetSignal"):
        scale *= 0.99
    if isinstance(game.get("props"), list) and game.get("props"):
        scale *= 0.99
    if isinstance(game.get("liveProps"), list) and game.get("liveProps"):
        scale *= 0.99
    if bool(game.get("snapshotAvailable")) and bool(game.get("simContextAvailable")):
        scale *= 0.98

    return _clamp(scale, 0.85, 1.10)


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
    # Vectorization (see run_monte_carlo below) already made 1000 iterations
    # cheap in CPU time; this trim is for the memory side of the same
    # headroom problem -- fewer floats retained per candidate's player-stat
    # distributions before they get summarized and discarded. Standard error
    # only grows by sqrt(1000/400) =~ 1.58x, an acceptable tradeoff for a
    # betting-edge estimate.
    default_iterations: int = 400

    def run_monte_carlo(self, game_context: Mapping[str, Any], iterations: int = 1000) -> SimulationResult:
        context = _copy_mapping(game_context)
        iteration_count = max(1, _safe_int(iterations) or self.default_iterations)
        # numpy's vectorized normal() draws all iterations in one C-level call
        # instead of iteration_count separate Python-level random.normalvariate()
        # calls -- confirmed in production 2026-07-24 as a multi-hundred-second
        # contributor per board-publication cycle once called once per candidate
        # (up to ~270 candidates), since a prop candidate pays this cost twice
        # (once for the game margin, once more per player stat). Output is
        # statistically equivalent (same means/std-devs/floor clamps/thresholds),
        # not bit-identical to the old random.Random sequence -- existing tests
        # only assert distribution shape/keys/comparative relationships, never
        # exact simulated values, so this is safe.
        rng = np.random.default_rng(_safe_int(context.get("seed")))

        team_projections = _copy_mapping(context.get("team_projections"))
        player_projections = _coerce_sequence(context.get("player_projections"))
        matchup_modifiers = _copy_mapping(context.get("matchup_modifiers"))
        advanced_payload = _advanced_payload(context)
        advanced_std_dev_scale = _advanced_std_dev_scale(advanced_payload)

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

        team_std_dev = {
            "home": _baseline_std_dev("team_score", home_projection, context) * advanced_std_dev_scale,
            "away": _baseline_std_dev("team_score", away_projection, context) * advanced_std_dev_scale,
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
            adjusted_std_dev = _baseline_std_dev(stat_name, projection_value, context) * advanced_std_dev_scale
            adjusted_std_dev *= max(0.5, min(2.0, combined_scale))

            stat_bucket = player_stat_values.setdefault(player_name, {})
            player_stat_meta[player_name] = {"player": player_name, "stat": stat_name}
            simulated_values = rng.normal(adjusted_mean, max(0.01, adjusted_std_dev), size=iteration_count)
            np.clip(simulated_values, 0.0, None, out=simulated_values)
            stat_bucket[stat_name] = [round(float(value), 4) for value in simulated_values]

        home_mean = (home_projection if home_projection is not None else _coerce_float(context.get("line")) or 0.0) + margin_bias
        away_mean = away_projection if away_projection is not None else _coerce_float(context.get("line_opp")) or 0.0
        home_scores = rng.normal(home_mean, max(0.01, team_std_dev["home"]), size=iteration_count)
        np.clip(home_scores, 0.0, None, out=home_scores)
        away_scores = rng.normal(away_mean, max(0.01, team_std_dev["away"]), size=iteration_count)
        np.clip(away_scores, 0.0, None, out=away_scores)
        margins = home_scores - away_scores
        push_threshold = _coerce_float(context.get("push_threshold")) or 0.5

        win_mask = margins > push_threshold
        loss_mask = margins < -push_threshold
        push_mask = ~(win_mask | loss_mask)

        outcome_counts = {
            "win": int(np.count_nonzero(win_mask)),
            "loss": int(np.count_nonzero(loss_mask)),
            "push": int(np.count_nonzero(push_mask)),
        }
        win_scores = margins[win_mask].tolist()
        loss_scores = margins[loss_mask].tolist()
        push_scores = margins[push_mask].tolist()

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
            "advanced": advanced_payload,
            "advanced_std_dev_scale": round(advanced_std_dev_scale, 4),
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