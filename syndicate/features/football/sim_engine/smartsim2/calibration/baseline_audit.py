from __future__ import annotations

import csv
import zlib
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Sequence

from syndicate.features.football.sim_engine.smartsim2.calibration.benchmark_contracts import BenchmarkDriveRecord
from syndicate.features.football.sim_engine.smartsim2.calibration.benchmark_contracts import BenchmarkGameRecord
from syndicate.features.football.sim_engine.smartsim2.calibration.benchmark_contracts import CalibrationBenchmarkSnapshot
from syndicate.features.football.sim_engine.smartsim2.calibration.benchmark_contracts import CalibrationSplit
from syndicate.features.football.sim_engine.smartsim2.calibration.evaluation_metrics import MetricResult
from syndicate.features.football.sim_engine.smartsim2.calibration.simulator_evaluator import SimulatorEvaluation
from syndicate.features.football.sim_engine.smartsim2.calibration.simulator_evaluator import evaluate_simulator
from syndicate.features.football.sim_engine.smartsim2.contracts import PossessionOutcome
from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationInput
from syndicate.features.football.sim_engine.smartsim2.contracts import SmartSim2SimulationOutput
from syndicate.features.football.sim_engine.smartsim2.game_simulator import simulate_game


TEAM_NAME_TO_ABBR: dict[str, str] = {
    "Arizona Cardinals": "ARI",
    "Atlanta Falcons": "ATL",
    "Baltimore Ravens": "BAL",
    "Buffalo Bills": "BUF",
    "Carolina Panthers": "CAR",
    "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN",
    "Cleveland Browns": "CLE",
    "Dallas Cowboys": "DAL",
    "Denver Broncos": "DEN",
    "Detroit Lions": "DET",
    "Green Bay Packers": "GB",
    "Houston Texans": "HOU",
    "Indianapolis Colts": "IND",
    "Jacksonville Jaguars": "JAX",
    "Kansas City Chiefs": "KC",
    "Las Vegas Raiders": "LV",
    "Los Angeles Chargers": "LAC",
    "Los Angeles Rams": "LA",
    "Miami Dolphins": "MIA",
    "Minnesota Vikings": "MIN",
    "New England Patriots": "NE",
    "New Orleans Saints": "NO",
    "New York Giants": "NYG",
    "New York Jets": "NYJ",
    "Philadelphia Eagles": "PHI",
    "Pittsburgh Steelers": "PIT",
    "San Francisco 49ers": "SF",
    "Seattle Seahawks": "SEA",
    "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN",
    "Washington Commanders": "WAS",
}

TEAM_ABBR_TO_NAME: dict[str, str] = {value: key for key, value in TEAM_NAME_TO_ABBR.items()}


@dataclass(frozen=True)
class BaselineAuditResult:
    benchmark_snapshot: CalibrationBenchmarkSnapshot
    simulation_inputs: tuple[SmartSim2SimulationInput, ...]
    simulation_outputs: tuple[SmartSim2SimulationOutput, ...]
    evaluation: SimulatorEvaluation


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _to_int(value: Any, default: int = 0) -> int:
    if value in {None, ""}:
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float = 0.0) -> float:
    if value in {None, ""}:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_team(value: str | None) -> str:
    if not value:
        return ""
    stripped = value.strip()
    if stripped in TEAM_NAME_TO_ABBR:
        return TEAM_NAME_TO_ABBR[stripped]
    upper = stripped.upper()
    if upper in TEAM_ABBR_TO_NAME:
        return upper
    return upper


def _aggregate_team_rows(rows: Sequence[dict[str, str]], *, team_field: str) -> dict[str, dict[str, float]]:
    grouped: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        team_key = _normalize_team(row.get(team_field))
        if not team_key:
            continue
        for field_name, raw_value in row.items():
            if field_name in {team_field, "season", "week"} or raw_value in {None, ""}:
                continue
            try:
                grouped[team_key][field_name].append(float(raw_value))
            except (TypeError, ValueError):
                continue
    return {
        team_key: {field_name: sum(values) / len(values) for field_name, values in columns.items() if values}
        for team_key, columns in grouped.items()
    }


def _index_rows(rows: Sequence[dict[str, str]], *, team_field: str) -> dict[tuple[int, int, str], dict[str, str]]:
    indexed: dict[tuple[int, int, str], dict[str, str]] = {}
    for row in rows:
        season = _to_int(row.get("season"), default=-1)
        week = _to_int(row.get("week"), default=-1)
        team_key = _normalize_team(row.get(team_field))
        if team_key:
            indexed[(season, week, team_key)] = row
    return indexed


def _lookup_row(
    season: int,
    week: int,
    team_key: str,
    indexed_rows: dict[tuple[int, int, str], dict[str, str]],
    aggregate_rows: dict[str, dict[str, float]],
) -> dict[str, Any]:
    row = indexed_rows.get((season, week, team_key))
    if row is not None:
        return row
    return aggregate_rows.get(team_key, {})


def _game_id_from_row(game_row: dict[str, str]) -> str:
    season = _to_int(game_row.get("season"), default=0)
    week = _to_int(game_row.get("week"), default=0)
    home_team = str(game_row.get("home_team") or "HOME")
    away_team = str(game_row.get("away_team") or "AWAY")
    return str(game_row.get("game_id") or f"{season}_{week}_{home_team}_{away_team}")


def _build_drive_records(
    *,
    game_row: dict[str, str],
    team_summary_row: dict[str, Any],
    game_id: str,
    team_key: str,
    team_name: str,
    opponent_name: str,
    pace_field: str,
    drive_offset: int,
) -> list[BenchmarkDriveRecord]:
    drives = max(0, _to_int(team_summary_row.get("drives"), default=0))
    if drives == 0:
        return []

    pace_secs_play = max(1.0, _to_float(game_row.get(pace_field), default=24.0))
    plays_per_drive = max(1, round(_to_float(team_summary_row.get("seconds_per_drive"), default=0.0) / pace_secs_play))
    seconds_per_drive = max(0, round(_to_float(team_summary_row.get("seconds_per_drive"), default=0.0)))
    yards_per_drive = max(0, round(_to_float(team_summary_row.get("yards_per_drive"), default=0.0)))
    start_fp = max(1, min(99, round(_to_float(team_summary_row.get("avg_start_fp"), default=25.0))))

    touchdown_count = min(drives, max(0, round(_to_float(team_summary_row.get("td_per_drive"), default=0.0) * drives)))
    field_goal_count = min(drives - touchdown_count, max(0, round(_to_float(team_summary_row.get("fg_per_drive"), default=0.0) * drives)))
    turnover_rate = _to_float(team_summary_row.get("turnover_adj_rate"), default=0.0)
    turnover_count = min(drives - touchdown_count - field_goal_count, max(0, round(turnover_rate * drives)))
    punt_count = max(0, drives - touchdown_count - field_goal_count - turnover_count)

    drive_records: list[BenchmarkDriveRecord] = []
    for drive_index in range(drives):
        if drive_index < touchdown_count:
            outcome = PossessionOutcome.TOUCHDOWN
            points = 7
            touchdown = True
            field_goal_attempt = False
            punt = False
            turnover = False
        elif drive_index < touchdown_count + field_goal_count:
            outcome = PossessionOutcome.FIELD_GOAL
            points = 3
            touchdown = False
            field_goal_attempt = True
            punt = False
            turnover = False
        elif drive_index < touchdown_count + field_goal_count + turnover_count:
            outcome = PossessionOutcome.TURNOVER
            points = 0
            touchdown = False
            field_goal_attempt = False
            punt = False
            turnover = True
        else:
            outcome = PossessionOutcome.PUNT
            points = 0
            touchdown = False
            field_goal_attempt = False
            punt = True
            turnover = False

        field_position_end = max(1, min(99, start_fp + yards_per_drive))
        red_zone_entry = start_fp >= 75 or field_position_end >= 75
        goal_to_go = start_fp >= 90 or field_position_end >= 90
        drive_records.append(
            BenchmarkDriveRecord(
                drive_id=f"{game_id}-{team_key}-{drive_offset + drive_index + 1}",
                game_id=game_id,
                offense_team=team_name,
                defense_team=opponent_name,
                season=_to_int(game_row.get("season"), default=0),
                week=_to_int(game_row.get("week"), default=0),
                quarter=1 + (drive_index % 4),
                down_start=1,
                distance_start=10,
                field_position_start=start_fp,
                field_position_end=field_position_end,
                plays=plays_per_drive,
                seconds=seconds_per_drive,
                yards=yards_per_drive,
                points=points,
                outcome=outcome,
                red_zone_entry=red_zone_entry,
                goal_to_go=goal_to_go,
                turnover=turnover,
                field_goal_attempt=field_goal_attempt,
                punt=punt,
                touchdown=touchdown,
                metadata={
                    "source": "proxy_team_summary",
                    "drive_number": drive_index + 1,
                    "drives_in_game": drives,
                    "punt_residual_count": punt_count,
                },
            )
        )
    return drive_records


def _build_game_record(game_row: dict[str, str], *, home_drive_count: int, away_drive_count: int) -> BenchmarkGameRecord:
    game_id = _game_id_from_row(game_row)
    season = _to_int(game_row.get("season"), default=0)
    week = _to_int(game_row.get("week"), default=0)
    quarter_home_points = tuple(_to_int(game_row.get(f"home_q{quarter}"), default=0) for quarter in range(1, 5))
    quarter_away_points = tuple(_to_int(game_row.get(f"away_q{quarter}"), default=0) for quarter in range(1, 5))
    home_points = _to_int(game_row.get("home_score"), default=sum(quarter_home_points))
    away_points = _to_int(game_row.get("away_score"), default=sum(quarter_away_points))
    return BenchmarkGameRecord(
        game_id=game_id,
        home_team=str(game_row.get("home_team") or "HOME"),
        away_team=str(game_row.get("away_team") or "AWAY"),
        season=season,
        week=week,
        home_points=home_points,
        away_points=away_points,
        quarter_home_points=quarter_home_points,
        quarter_away_points=quarter_away_points,
        possessions=home_drive_count + away_drive_count,
        drives=home_drive_count + away_drive_count,
        metadata={
            "margin_actual": _to_float(game_row.get("margin_actual"), default=0.0),
            "total_actual": _to_float(game_row.get("total_actual"), default=0.0),
            "source": "historical_game_summary",
        },
    )


def _build_simulation_input(game_row: dict[str, str]) -> SmartSim2SimulationInput:
    game_id = _game_id_from_row(game_row)
    seed = zlib.crc32(game_id.encode("utf-8"))
    pace_value = (
        _to_float(game_row.get("home_pace_secs_play"), default=24.0)
        + _to_float(game_row.get("away_pace_secs_play"), default=24.0)
    ) / 2.0
    return SmartSim2SimulationInput(
        home_team=str(game_row.get("home_team") or "HOME"),
        away_team=str(game_row.get("away_team") or "AWAY"),
        seed=seed,
        home_offense_rating=_to_float(game_row.get("home_off_epa"), default=0.0),
        home_defense_rating=_to_float(game_row.get("home_def_epa"), default=0.0),
        away_offense_rating=_to_float(game_row.get("away_off_epa"), default=0.0),
        away_defense_rating=_to_float(game_row.get("away_def_epa"), default=0.0),
        pace_seconds_per_play=max(1.0, pace_value),
        feature_generation_payload={
            "game_id": game_id,
            "season": _to_int(game_row.get("season"), default=0),
            "week": _to_int(game_row.get("week"), default=0),
            "market_total": _to_float(game_row.get("market_total"), default=0.0),
            "market_spread_home": _to_float(game_row.get("market_spread_home"), default=0.0),
        },
    )


def build_baseline_audit_snapshot_and_inputs(
    *,
    data_root: Path,
    game_detail_paths: Sequence[Path],
    split: CalibrationSplit = CalibrationSplit.CALIBRATION,
    source_name: str | None = None,
) -> tuple[CalibrationBenchmarkSnapshot, tuple[SmartSim2SimulationInput, ...]]:
    pfr_rows = _read_csv_rows(data_root / "pfr_drive_stats.csv")
    special_rows = _read_csv_rows(data_root / "special_teams.csv")
    redzone_rows = _read_csv_rows(data_root / "redzone_splits.csv")
    penalty_rows = _read_csv_rows(data_root / "penalties_stats.csv")
    team_rows = _read_csv_rows(data_root / "team_stats.csv")

    pfr_index = _index_rows(pfr_rows, team_field="team")
    special_index = _index_rows(special_rows, team_field="team")
    redzone_index = _index_rows(redzone_rows, team_field="team")
    penalty_index = _index_rows(penalty_rows, team_field="team")
    team_index = _index_rows(team_rows, team_field="team")

    pfr_aggregates = _aggregate_team_rows(pfr_rows, team_field="team")
    special_aggregates = _aggregate_team_rows(special_rows, team_field="team")
    redzone_aggregates = _aggregate_team_rows(redzone_rows, team_field="team")
    penalty_aggregates = _aggregate_team_rows(penalty_rows, team_field="team")
    team_aggregates = _aggregate_team_rows(team_rows, team_field="team")

    drive_records: list[BenchmarkDriveRecord] = []
    game_records: list[BenchmarkGameRecord] = []
    simulation_inputs: list[SmartSim2SimulationInput] = []

    for game_path in game_detail_paths:
        game_rows = _read_csv_rows(game_path)
        for game_row in game_rows:
            season = _to_int(game_row.get("season"), default=0)
            week = _to_int(game_row.get("week"), default=0)
            home_key = _normalize_team(game_row.get("home_team"))
            away_key = _normalize_team(game_row.get("away_team"))
            if not home_key or not away_key:
                continue

            home_name = str(game_row.get("home_team") or TEAM_ABBR_TO_NAME.get(home_key, home_key))
            away_name = str(game_row.get("away_team") or TEAM_ABBR_TO_NAME.get(away_key, away_key))

            home_team_summary = {
                **_lookup_row(season, week, home_key, pfr_index, pfr_aggregates),
                **_lookup_row(season, week, home_key, special_index, special_aggregates),
                **_lookup_row(season, week, home_key, redzone_index, redzone_aggregates),
                **_lookup_row(season, week, home_key, penalty_index, penalty_aggregates),
                **_lookup_row(season, week, home_key, team_index, team_aggregates),
            }
            away_team_summary = {
                **_lookup_row(season, week, away_key, pfr_index, pfr_aggregates),
                **_lookup_row(season, week, away_key, special_index, special_aggregates),
                **_lookup_row(season, week, away_key, redzone_index, redzone_aggregates),
                **_lookup_row(season, week, away_key, penalty_index, penalty_aggregates),
                **_lookup_row(season, week, away_key, team_index, team_aggregates),
            }

            game_id = _game_id_from_row(game_row)
            home_drives = _build_drive_records(
                game_row=game_row,
                team_summary_row=home_team_summary,
                game_id=game_id,
                team_key=home_key,
                team_name=home_name,
                opponent_name=away_name,
                pace_field="home_pace_secs_play",
                drive_offset=0,
            )
            away_drives = _build_drive_records(
                game_row=game_row,
                team_summary_row=away_team_summary,
                game_id=game_id,
                team_key=away_key,
                team_name=away_name,
                opponent_name=home_name,
                pace_field="away_pace_secs_play",
                drive_offset=len(home_drives),
            )
            drive_records.extend(home_drives)
            drive_records.extend(away_drives)
            game_records.append(
                _build_game_record(
                    game_row,
                    home_drive_count=len(home_drives),
                    away_drive_count=len(away_drives),
                )
            )
            simulation_inputs.append(_build_simulation_input(game_row))

    benchmark_snapshot = CalibrationBenchmarkSnapshot(
        split=split,
        source_name=source_name or "; ".join(str(path) for path in game_detail_paths),
        drive_records=tuple(drive_records),
        game_records=tuple(game_records),
        metadata={
            "data_root": str(data_root),
            "game_detail_paths": [str(path) for path in game_detail_paths],
            "special_team_rows": len(special_rows),
            "redzone_rows": len(redzone_rows),
            "penalty_rows": len(penalty_rows),
            "team_rows": len(team_rows),
        },
    )
    return benchmark_snapshot, tuple(simulation_inputs)


def load_baseline_audit_result(
    *,
    data_root: Path,
    game_detail_paths: Sequence[Path],
    split: CalibrationSplit = CalibrationSplit.CALIBRATION,
    source_name: str | None = None,
) -> BaselineAuditResult:
    benchmark_snapshot, simulation_inputs = build_baseline_audit_snapshot_and_inputs(
        data_root=data_root,
        game_detail_paths=game_detail_paths,
        split=split,
        source_name=source_name,
    )
    simulation_outputs = tuple(simulate_game(simulation_input) for simulation_input in simulation_inputs)
    evaluation = evaluate_simulator(benchmark_snapshot, simulation_outputs)
    return BaselineAuditResult(
        benchmark_snapshot=benchmark_snapshot,
        simulation_inputs=simulation_inputs,
        simulation_outputs=simulation_outputs,
        evaluation=evaluation,
    )


def _normalized_error(metric: MetricResult) -> float:
    benchmark_scale = abs(float(metric.benchmark_value)) if metric.benchmark_value else 1.0
    return float(metric.absolute_error) / benchmark_scale


def classify_metric_severity(metric: MetricResult) -> str:
    normalized_error = _normalized_error(metric)
    if normalized_error >= 0.25:
        return "Critical"
    if normalized_error >= 0.10:
        return "Moderate"
    return "Minor"


def _format_metric_value(value: float, unit: str) -> str:
    if unit == "rate":
        return f"{value * 100:.1f}%"
    if unit == "seconds":
        return f"{value:.1f}"
    return f"{value:.2f}"


def _metric_line(metric: MetricResult) -> str:
    return (
        f"| {metric.name} | {classify_metric_severity(metric)} | "
        f"{_format_metric_value(metric.benchmark_value, metric.unit)} | "
        f"{_format_metric_value(metric.simulated_value, metric.unit)} | "
        f"{metric.absolute_error:.3f} | {_normalized_error(metric):.3f} |"
    )


def generate_baseline_audit_report(
    result: BaselineAuditResult,
    *,
    title: str = "SmartSim 2.0 Baseline Calibration Audit",
    top_n: int = 8,
) -> str:
    evaluation = result.evaluation
    metric_rows = sorted(evaluation.metric_results, key=_normalized_error, reverse=True)
    severity_counts = {"Critical": 0, "Moderate": 0, "Minor": 0}
    for metric in metric_rows:
        severity_counts[classify_metric_severity(metric)] += 1

    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"- Source: {evaluation.benchmark_snapshot.source_name}")
    lines.append(f"- Split: {evaluation.benchmark_snapshot.split.value}")
    lines.append(f"- Calibration score: {evaluation.score:.3f}")
    lines.append(f"- Games evaluated: {len(result.simulation_outputs)}")
    lines.append(f"- Drives synthesized: {len(evaluation.benchmark_snapshot.drive_records)}")
    lines.append("- Benchmark shape: proxy benchmark built from historical game summaries plus team-week summary tables")
    lines.append("- Current hypothesis: drive length and drive finishing behavior are the first-zero realism gaps")
    lines.append("")
    lines.append("## Severity Summary")
    lines.append("")
    lines.append(f"- Critical: {severity_counts['Critical']}")
    lines.append(f"- Moderate: {severity_counts['Moderate']}")
    lines.append(f"- Minor: {severity_counts['Minor']}")
    lines.append("")
    lines.append("## Largest Gaps")
    lines.append("")
    lines.append("| Metric | Severity | Benchmark | Simulated | Abs Error | Normalized Error |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for metric in metric_rows[:top_n]:
        lines.append(_metric_line(metric))
    lines.append("")
    lines.append("## Full Metric Table")
    lines.append("")
    lines.append("| Metric | Severity | Benchmark | Simulated | Abs Error | Normalized Error |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for metric in metric_rows:
        lines.append(_metric_line(metric))
    lines.append("")
    lines.append("## Interpretation")
    lines.append("")
    lines.append("- Read the drive-length rows first; if they are off, the scoring and totals rows are downstream noise.")
    lines.append("- Punt and field-goal mix should be reconciled before treating game totals as trustworthy.")
    lines.append("- This audit is intentionally a proxy baseline until true drive-level historical play-by-play is mirrored locally.")
    return "\n".join(lines)


__all__ = [
    "BaselineAuditResult",
    "TEAM_ABBR_TO_NAME",
    "TEAM_NAME_TO_ABBR",
    "build_baseline_audit_snapshot_and_inputs",
    "classify_metric_severity",
    "generate_baseline_audit_report",
    "load_baseline_audit_result",
]