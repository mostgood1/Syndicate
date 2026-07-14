from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from statistics import mean
from typing import Any

from syndicate.features.football.adapters import FootballSimulationAdapter
from syndicate.features.football.feature_lift_analysis import _historical_simulation_input
from syndicate.features.football.feature_lift_analysis import _mask_simulation_input
from syndicate.features.football.ingestion.nflverse_ingestion import load_nflverse_player_stats


@dataclass(frozen=True)
class PlayerPropFamily:
    name: str
    keys: tuple[str, ...]
    cost: int


PLAYER_PROP_FAMILIES: tuple[PlayerPropFamily, ...] = (
    PlayerPropFamily("Snap Share", ("snap_share", "snap_pct", "snap_rate", "snaps_share"), 1),
    PlayerPropFamily("Target Share", ("target_share", "targets_share", "target_pct"), 1),
    PlayerPropFamily("Route Participation", ("route_participation", "route_pct", "routes_share", "wopr"), 2),
    PlayerPropFamily("Air Yards Share", ("air_yard_share", "air_yards_share", "air_yards_pct"), 2),
)


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except Exception:
        return None


def _player_metric_value(player: Any, keys: tuple[str, ...]) -> float | None:
    usage_metrics = dict(getattr(player, "usage_metrics", {}) or {})
    for key in keys:
        value = _safe_float(usage_metrics.get(key))
        if value is not None:
            return value
    return None


def _player_projection_value(player_output: dict[str, Any]) -> float | None:
    projection = dict(player_output.get("projection") or {})
    for key in ("receiving_yards_mean", "targets_mean", "receptions_mean", "rushing_yards_mean", "passing_yards_mean", "projection_mean"):
        value = _safe_float(projection.get(key))
        if value is not None:
            return value
    return None


def _best_prop_value(player_output: dict[str, Any], actual_row: dict[str, Any] | None) -> tuple[float | None, float | None]:
    if not actual_row:
        return None, None
    projection = dict(player_output.get("projection") or {})
    candidates: list[tuple[float, float]] = []
    metric_map = (
        ("passing_yards_mean", "passing_yards"),
        ("rushing_yards_mean", "rushing_yards"),
        ("receiving_yards_mean", "receiving_yards"),
        ("targets_mean", "targets"),
        ("receptions_mean", "receptions"),
    )
    for projection_key, actual_key in metric_map:
        projected = _safe_float(projection.get(projection_key))
        actual = _safe_float(actual_row.get(actual_key))
        if projected is None or actual is None:
            continue
        candidates.append((projected, actual))
    if not candidates:
        projected = _player_projection_value(player_output)
        actual = _safe_float(actual_row.get("fantasy_points"))
        return projected, actual
    return max(candidates, key=lambda item: item[0])


@lru_cache(maxsize=16)
def _player_stats_index(season: int) -> dict[tuple[str, str, str], dict[str, Any]]:
    rows = load_nflverse_player_stats(season)
    index: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        player_id = str(row.get("player_id") or "").strip().upper()
        team = str(row.get("team") or "").strip().upper()
        week = str(row.get("week") or "").strip()
        if not player_id or not team or not week:
            continue
        index[(player_id, team, week)] = row
    return index


def _actual_player_row(season: int, player_output: dict[str, Any], week: str) -> dict[str, Any] | None:
    player_id = str(player_output.get("player_id") or "").strip().upper()
    team = str(player_output.get("team") or "").strip().upper()
    return _player_stats_index(season).get((player_id, team, week))


@lru_cache(maxsize=64)
def _analysis_input(sport: str, season: int, date: str):
    return _historical_simulation_input(sport, season, date)


def run_player_prop_lift_analysis(*, sport: str = "nfl", date_specs: tuple[tuple[int, str], ...] = ((2024, "2024-09-05"), (2024, "2024-09-06"), (2025, "2025-09-04"), (2025, "2025-09-05"))) -> dict[str, Any]:
    adapter = FootballSimulationAdapter(sport=sport)
    rows: list[dict[str, Any]] = []
    for family in (None, *PLAYER_PROP_FAMILIES):
        enabled = set()
        if family is not None:
            enabled.add(family.name)
        family_name = "Baseline model" if family is None else family.name
        family_metrics: list[float] = []
        family_sample_count = 0
        for season, date in date_specs:
            simulation_input = _analysis_input(sport, season, date)
            masked_input = _mask_simulation_input(simulation_input, enabled)
            output = adapter.simulate_games(masked_input)
            for player_in, player_out in zip(masked_input.players, output.player_outputs):
                actual_row = _actual_player_row(season, player_out, str(date).split("-")[-1].lstrip("0") or str(int(str(date).split("-")[-1])))
                projected_value, actual_value = _best_prop_value(player_out, actual_row)
                if actual_value is None or projected_value is None:
                    continue
                family_metrics.append(abs(projected_value - actual_value))
                family_sample_count += 1
        rows.append(
            {
                "family": family_name,
                "sample_count": family_sample_count,
                "mae": round(mean(family_metrics), 4) if family_metrics else None,
                "cost": 0 if family is None else family.cost,
            }
        )

    baseline = rows[0]
    for row in rows[1:]:
        if baseline["mae"] is None or row["mae"] is None:
            row["absolute_lift"] = None
            row["relative_lift"] = None
            row["recommendation"] = "insufficient data"
            continue
        row["absolute_lift"] = round(baseline["mae"] - row["mae"], 4)
        row["relative_lift"] = round((baseline["mae"] - row["mae"]) / baseline["mae"], 4) if baseline["mae"] else None
        row["recommendation"] = "promote" if row["absolute_lift"] > 0 else "drop"

    ranked = sorted(rows[1:], key=lambda row: (-(row.get("absolute_lift") or 0.0), row.get("cost", 0), row["family"]))
    return {
        "sport": sport,
        "date_specs": list(date_specs),
        "rows": rows,
        "ranked": ranked,
        "baseline": baseline,
    }


def build_player_prop_lift_report_markdown(analysis: dict[str, Any]) -> str:
    rows = list(analysis.get("rows") or [])
    ranked = list(analysis.get("ranked") or [])
    baseline = dict(analysis.get("baseline") or {})
    lines = [
        "# Football Player Prop Lift Report",
        "",
        "## Executive Summary",
        "",
        "This report measures player-prop lift on the four completed NFL dates using actual nflverse player-week outcomes and the existing usage-driven player projections.",
        "",
        f"Baseline MAE: {baseline.get('mae')} across {baseline.get('sample_count', 0)} samples.",
        "",
        "## Family Results",
        "",
        "| Feature Family | Baseline MAE | New MAE | Absolute Lift | Relative Lift | Sample Count | Recommendation |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        if row["family"] == "Baseline model":
            lines.append(f"| Baseline model | {row.get('mae')} | {row.get('mae')} | n/a | n/a | {row.get('sample_count')} | baseline reference |")
            continue
        lines.append(
            f"| {row['family']} | {baseline.get('mae')} | {row.get('mae')} | {row.get('absolute_lift')} | {row.get('relative_lift')} | {row.get('sample_count')} | {row.get('recommendation')} |"
        )
    lines.extend([
        "",
        "## Ranking",
        "",
        "| Rank | Feature Family | Measured Lift | Operational Cost |",
        "| --- | --- | --- | --- |",
    ])
    for index, row in enumerate(ranked, start=1):
        lines.append(f"| {index} | {row['family']} | {row.get('absolute_lift')} | {row.get('cost')} |")
    lines.extend([
        "",
        "## No Measurable Lift",
        "",
    ])
    no_lift = [row["family"] for row in ranked if not row.get("absolute_lift") or row.get("absolute_lift", 0) <= 0]
    lines.extend([f"- {family}" for family in no_lift] or ["- None detected."])
    return "\n".join(lines)


def write_player_prop_lift_report(out_path: str | Path, *, sport: str = "nfl") -> str:
    analysis = run_player_prop_lift_analysis(sport=sport)
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_player_prop_lift_report_markdown(analysis), encoding="utf-8")
    return str(path)