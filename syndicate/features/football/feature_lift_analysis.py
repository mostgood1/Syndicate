from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from statistics import mean
from typing import Any

from syndicate.features.football.adapters import FootballSimulationAdapter
from syndicate.features.football.ingestion.nflverse_ingestion import load_nflverse_rows


@dataclass(frozen=True)
class FeatureFamilySpec:
    name: str
    scope: str
    keys: tuple[str, ...]
    cost: int


FEATURE_FAMILIES: tuple[FeatureFamilySpec, ...] = (
    FeatureFamilySpec("EPA", "game", ("offensive_epa", "defensive_epa", "epa_play", "epa_allowed", "home_offensive_epa", "away_offensive_epa", "home_defensive_epa", "away_defensive_epa"), 1),
    FeatureFamilySpec("Success Rate", "game", ("success_rate", "success_rate_allowed", "home_success_rate", "away_success_rate", "home_success_rate_allowed", "away_success_rate_allowed"), 1),
    FeatureFamilySpec("PROE", "game", ("pass_rate_over_expectation", "proe", "home_pass_rate", "away_pass_rate"), 1),
    FeatureFamilySpec("Red Zone Efficiency", "game", ("red_zone_efficiency", "home_red_zone_efficiency", "away_red_zone_efficiency"), 2),
    FeatureFamilySpec("Explosive Play Metrics", "game", ("explosive_play_rate", "home_explosive_pass_rate", "away_explosive_pass_rate"), 2),
    FeatureFamilySpec("Snap Share", "game", ("snap_share", "snap_pct", "snap_rate", "snaps_share"), 2),
    FeatureFamilySpec("Target Share", "game", ("target_share", "targets_share", "target_pct"), 2),
    FeatureFamilySpec("Route Participation", "game", ("route_participation", "route_pct", "routes_share", "wopr"), 3),
    FeatureFamilySpec("Air Yards Share", "game", ("air_yard_share", "air_yards_share", "air_yards_pct"), 3),
)

DEFAULT_DATE_SPECS: tuple[tuple[int, str], ...] = (
    (2024, "2024-09-01"),
    (2024, "2024-09-02"),
    (2024, "2024-09-03"),
    (2025, "2025-09-01"),
    (2025, "2025-09-02"),
    (2025, "2025-09-03"),
)


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except Exception:
        return None


def _clone_payload(payload: dict[str, Any]) -> dict[str, Any]:
    cloned: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, dict):
            cloned[key] = dict(value)
        elif isinstance(value, list):
            cloned[key] = list(value)
        elif isinstance(value, tuple):
            cloned[key] = list(value)
        else:
            cloned[key] = value
    return cloned


def _team_player_usage(simulation_input, team_abbr: str) -> dict[str, float]:
    team = str(team_abbr or "").upper().strip()
    values = {"snap_share": [], "target_share": [], "route_participation": [], "air_yard_share": []}
    for player in getattr(simulation_input, "players", ()):
        if str(getattr(player, "team", "") or "").upper().strip() != team:
            continue
        usage_metrics = dict(getattr(player, "usage_metrics", {}) or {})
        for key in values:
            value = _safe_float(usage_metrics.get(key))
            if value is not None:
                values[key].append(value)
    return {key: round(mean(value_list), 4) if value_list else 0.0 for key, value_list in values.items()}


def _mask_game_features(game: Any, enabled_keys: set[str]) -> Any:
    if not enabled_keys:
        enabled_keys = set()
    payload = _clone_payload(game.__dict__)
    if "EPA" not in enabled_keys:
        for key in ("offensive_epa", "defensive_epa", "epa_play", "epa_allowed", "home_offensive_epa", "away_offensive_epa", "home_defensive_epa", "away_defensive_epa"):
            payload.pop(key, None)
            payload.get("team_metrics", {}).pop(key, None)
            payload.get("advanced_metrics", {}).pop(key, None)
    if "Success Rate" not in enabled_keys:
        for key in ("success_rate", "success_rate_allowed", "home_success_rate", "away_success_rate", "home_success_rate_allowed", "away_success_rate_allowed"):
            payload.pop(key, None)
            payload.get("team_metrics", {}).pop(key, None)
            payload.get("advanced_metrics", {}).pop(key, None)
    if "PROE" not in enabled_keys:
        for key in ("pass_rate_over_expectation", "proe", "home_pass_rate", "away_pass_rate"):
            payload.pop(key, None)
            payload.get("team_metrics", {}).pop(key, None)
            payload.get("advanced_metrics", {}).pop(key, None)
    if "Red Zone Efficiency" not in enabled_keys:
        for key in ("red_zone_efficiency", "home_red_zone_efficiency", "away_red_zone_efficiency"):
            payload.pop(key, None)
            payload.get("team_metrics", {}).pop(key, None)
            payload.get("advanced_metrics", {}).pop(key, None)
    if "Explosive Play Metrics" not in enabled_keys:
        for key in ("explosive_play_rate", "home_explosive_pass_rate", "away_explosive_pass_rate"):
            payload.pop(key, None)
            payload.get("team_metrics", {}).pop(key, None)
            payload.get("advanced_metrics", {}).pop(key, None)
    if payload.get("home_team_features") is not None:
        home_features = payload.get("home_team_features")
        payload["home_team_features"] = type(home_features)(**_clone_payload(home_features.__dict__))
    if payload.get("away_team_features") is not None:
        away_features = payload.get("away_team_features")
        payload["away_team_features"] = type(away_features)(**_clone_payload(away_features.__dict__))
    return type(game)(**payload)


def _mask_player_features(player: Any, enabled_keys: set[str]) -> Any:
    payload = _clone_payload(player.__dict__)
    usage_metrics = payload.get("usage_metrics", {}) if isinstance(payload.get("usage_metrics"), dict) else {}
    if "Snap Share" not in enabled_keys:
        for key in ("snap_share", "snap_pct", "snap_rate", "snaps_share"):
            usage_metrics.pop(key, None)
            payload.pop(key, None)
    if "Target Share" not in enabled_keys:
        for key in ("target_share", "targets_share", "target_pct"):
            usage_metrics.pop(key, None)
            payload.pop(key, None)
    if "Route Participation" not in enabled_keys:
        for key in ("route_participation", "route_pct", "routes_share", "wopr"):
            usage_metrics.pop(key, None)
            payload.pop(key, None)
    if "Air Yards Share" not in enabled_keys:
        for key in ("air_yard_share", "air_yards_share", "air_yards_pct"):
            usage_metrics.pop(key, None)
            payload.pop(key, None)
    payload["usage_metrics"] = usage_metrics
    if payload.get("adapter_metadata") is not None and not isinstance(payload.get("adapter_metadata"), dict):
        payload["adapter_metadata"] = dict(payload.get("adapter_metadata") or {})
    return type(player)(**payload)


def _mask_simulation_input(simulation_input, enabled_families: set[str]):
    masked_games = tuple(_mask_game_features(game, enabled_families) for game in getattr(simulation_input, "games", ()))
    masked_players = tuple(_mask_player_features(player, enabled_families) for player in getattr(simulation_input, "players", ()))
    return type(simulation_input)(
        sport=simulation_input.sport,
        date=simulation_input.date,
        games=masked_games,
        players=masked_players,
        metadata=dict(getattr(simulation_input, "metadata", {}) or {}),
        adapter_metadata=dict(getattr(simulation_input, "adapter_metadata", {}) or {}),
    )


def _actual_game_results(season: int, date: str) -> dict[tuple[str, str, str], dict[str, float]]:
    rows = [row for row in load_nflverse_rows(season=season) if str(row.get("game_date") or "").strip() == str(date).strip()]
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        home_team = str(row.get("home_team") or "").strip().upper()
        away_team = str(row.get("away_team") or "").strip().upper()
        if not home_team or not away_team:
            continue
        grouped.setdefault((str(date), home_team, away_team), []).append(row)
    actuals: dict[tuple[str, str, str], dict[str, float]] = {}
    for key, game_rows in grouped.items():
        home_scores = [_safe_float(row.get("home_score")) for row in game_rows]
        away_scores = [_safe_float(row.get("away_score")) for row in game_rows]
        home_score = max([score for score in home_scores if score is not None], default=None)
        away_score = max([score for score in away_scores if score is not None], default=None)
        if home_score is None or away_score is None:
            continue
        actuals[key] = {
            "home_score": float(home_score),
            "away_score": float(away_score),
            "margin": float(home_score) - float(away_score),
            "total": float(home_score) + float(away_score),
            "home_win": 1.0 if home_score > away_score else 0.0,
        }
    return actuals


@lru_cache(maxsize=64)
def _historical_simulation_input(sport: str, season: int, date: str):
    adapter = FootballSimulationAdapter(sport=sport)
    return adapter.load_features(date=date, selection=1, season=season)


def _stage_metrics(adapter: FootballSimulationAdapter, simulation_input, actuals: dict[tuple[str, str, str], dict[str, float]]) -> dict[str, Any]:
    simulation_output = adapter.simulate_games(simulation_input)
    brier_values: list[float] = []
    spread_errors: list[float] = []
    total_errors: list[float] = []
    calibration_errors: list[float] = []
    matched_games = 0
    for game_output in simulation_output.game_outputs:
        matchup = game_output.get("matchup") if isinstance(game_output.get("matchup"), dict) else {}
        key = (str(simulation_output.date), str(matchup.get("home_team") or "").upper().strip(), str(matchup.get("away_team") or "").upper().strip())
        actual = actuals.get(key)
        if not actual:
            continue
        predicted_home = _safe_float((game_output.get("win_probability") or {}).get("home"))
        predicted_spread = _safe_float((game_output.get("spread_distribution") or {}).get("home"))
        predicted_total = _safe_float((game_output.get("total_distribution") or {}).get("line"))
        if predicted_home is None or predicted_spread is None or predicted_total is None:
            continue
        matched_games += 1
        brier_values.append((predicted_home - actual["home_win"]) ** 2)
        spread_errors.append(abs(predicted_spread - actual["margin"]))
        total_errors.append(abs(predicted_total - actual["total"]))
        calibration_errors.append(abs(predicted_home - actual["home_win"]))
    return {
        "sample_count": matched_games,
        "brier": round(mean(brier_values), 4) if brier_values else None,
        "spread_mae": round(mean(spread_errors), 4) if spread_errors else None,
        "total_mae": round(mean(total_errors), 4) if total_errors else None,
        "calibration_error": round(mean(calibration_errors), 4) if calibration_errors else None,
    }


def _metric_string(metrics: dict[str, Any]) -> str:
    return (
        f"Brier={metrics.get('brier')}, Spread MAE={metrics.get('spread_mae')}, Total MAE={metrics.get('total_mae')}, "
        f"Calibration Error={metrics.get('calibration_error')}, n={metrics.get('sample_count')}"
    )


def _delta(previous: dict[str, Any], current: dict[str, Any], key: str) -> tuple[float | None, float | None]:
    prev = _safe_float(previous.get(key))
    curr = _safe_float(current.get(key))
    if prev is None or curr is None:
        return None, None
    absolute = prev - curr
    relative = (absolute / prev) if prev else None
    return round(absolute, 4), round(relative, 4) if relative is not None else None


def run_feature_lift_analysis(*, sport: str = "nfl", date_specs: tuple[tuple[int, str], ...] = DEFAULT_DATE_SPECS) -> dict[str, Any]:
    adapter = FootballSimulationAdapter(sport=sport)
    actual_cache = { (season, date): _actual_game_results(season, date) for season, date in date_specs }
    simulation_cache = { (season, date): _historical_simulation_input(sport, season, date) for season, date in date_specs }
    stages: list[dict[str, Any]] = []
    enabled: set[str] = set()
    for family in (None, *FEATURE_FAMILIES):
        if family is not None:
            enabled.add(family.name)
        stage_label = "Baseline model" if family is None else f"+ {family.name}"
        stage_metrics: list[dict[str, Any]] = []
        for season, date in date_specs:
            simulation_input = simulation_cache[(season, date)]
            masked_input = _mask_simulation_input(simulation_input, enabled)
            actuals = actual_cache[(season, date)]
            metrics = _stage_metrics(adapter, masked_input, actuals)
            metrics.update({"season": season, "date": date})
            stage_metrics.append(metrics)
        combined = {
            "sample_count": sum(int(item.get("sample_count") or 0) for item in stage_metrics),
            "brier": round(mean([item["brier"] for item in stage_metrics if item.get("brier") is not None]), 4) if any(item.get("brier") is not None for item in stage_metrics) else None,
            "spread_mae": round(mean([item["spread_mae"] for item in stage_metrics if item.get("spread_mae") is not None]), 4) if any(item.get("spread_mae") is not None for item in stage_metrics) else None,
            "total_mae": round(mean([item["total_mae"] for item in stage_metrics if item.get("total_mae") is not None]), 4) if any(item.get("total_mae") is not None for item in stage_metrics) else None,
            "calibration_error": round(mean([item["calibration_error"] for item in stage_metrics if item.get("calibration_error") is not None]), 4) if any(item.get("calibration_error") is not None for item in stage_metrics) else None,
        }
        stages.append({
            "label": stage_label,
            "enabled_families": sorted(enabled),
            "metrics": combined,
            "per_date": stage_metrics,
        })

    rows: list[dict[str, Any]] = []
    previous_metrics: dict[str, Any] | None = None
    for index, stage in enumerate(stages):
        metrics = dict(stage["metrics"])
        if previous_metrics is None:
            previous_metrics = metrics
            rows.append({
                "family": "Baseline model",
                "baseline": _metric_string(metrics),
                "new": _metric_string(metrics),
                "absolute_improvement": "n/a",
                "relative_improvement": "n/a",
                "recommendation": "baseline reference",
                "metrics": metrics,
                "cost": 0,
            })
            continue
        family_name = FEATURE_FAMILIES[index - 1].name
        abs_cal, rel_cal = _delta(previous_metrics, metrics, "calibration_error")
        abs_brier, rel_brier = _delta(previous_metrics, metrics, "brier")
        abs_spread, rel_spread = _delta(previous_metrics, metrics, "spread_mae")
        abs_total, rel_total = _delta(previous_metrics, metrics, "total_mae")
        positive_signals = [value for value in (abs_brier, abs_spread, abs_total, abs_cal) if value is not None]
        lift_score = round(mean(positive_signals), 4) if positive_signals else 0.0
        recommendation = "promote" if (abs_cal or 0.0) > 0 and lift_score > 0 else "keep as optional" if (abs_cal or 0.0) >= 0 else "drop"
        rows.append({
            "family": family_name,
            "baseline": _metric_string(previous_metrics),
            "new": _metric_string(metrics),
            "absolute_improvement": f"Brier={abs_brier}, Spread MAE={abs_spread}, Total MAE={abs_total}, Calibration Error={abs_cal}",
            "relative_improvement": f"Brier={rel_brier}, Spread MAE={rel_spread}, Total MAE={rel_total}, Calibration Error={rel_cal}",
            "recommendation": recommendation,
            "metrics": metrics,
            "cost": FEATURE_FAMILIES[index - 1].cost,
            "lift_score": lift_score,
        })
        previous_metrics = metrics

    return {
        "sport": sport,
        "date_specs": list(date_specs),
        "rows": rows,
    }


def run_feature_lift_analysis_cached() -> dict[str, Any]:
    return run_feature_lift_analysis(date_specs=((2024, "2024-09-05"), (2024, "2024-09-06"), (2025, "2025-09-04"), (2025, "2025-09-05")))


def build_feature_lift_report_markdown(analysis: dict[str, Any]) -> str:
    rows = list(analysis.get("rows") or [])
    ranked = [row for row in rows if row.get("family") != "Baseline model"]
    ranked.sort(key=lambda row: (-(row.get("lift_score") or 0.0), row.get("cost", 0), row.get("family", "")))
    top_five = ranked[:5]
    no_lift = [row["family"] for row in ranked if row.get("lift_score") in (None, 0) or (row.get("metrics") or {}).get("calibration_error") == (rows[0].get("metrics") or {}).get("calibration_error")]
    production_set = [row["family"] for row in ranked if (row.get("recommendation") == "promote" and row.get("cost", 0) <= 2)]
    lines = [
        "# Football Feature Lift Report",
        "",
        "## Executive Summary",
        "",
        "This report measures calibration lift by incrementally enabling football feature families on top of a baseline built from implied spread, implied total, and basic team identifiers.",
        "",
        "## Feature Family Results",
        "",
        "| Feature Family | Baseline Result | New Result | Absolute Improvement | Relative Improvement | Recommendation |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['family']} | {row['baseline']} | {row['new']} | {row['absolute_improvement']} | {row['relative_improvement']} | {row['recommendation']} |"
        )
    lines.extend([
        "",
        "## Ranking",
        "",
        "| Rank | Feature Family | Calibration Contribution | Predictive Lift | Operational Cost |",
        "| --- | --- | --- | --- | --- |",
    ])
    for index, row in enumerate(top_five, start=1):
        lines.append(
            f"| {index} | {row['family']} | {row.get('lift_score')} | {row.get('lift_score')} | {row.get('cost')} |"
        )
    lines.extend([
        "",
        "## Top 5 Features",
        "",
    ])
    for row in top_five:
        lines.append(f"- {row['family']}")
    lines.extend([
        "",
        "## Features With No Measurable Lift",
        "",
    ])
    if no_lift:
        for family in no_lift:
            lines.append(f"- {family}")
    else:
        lines.append("- None detected in this sample set.")
    lines.extend([
        "",
        "## Recommended Production Feature Set",
        "",
    ])
    if production_set:
        for family in production_set:
            lines.append(f"- {family}")
    else:
        lines.append("- Baseline only until additional evidence is gathered.")
    return "\n".join(lines)


def write_feature_lift_report(out_path: str | Path, *, sport: str = "nfl") -> str:
    analysis = run_feature_lift_analysis(sport=sport)
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_feature_lift_report_markdown(analysis), encoding="utf-8")
    return str(path)