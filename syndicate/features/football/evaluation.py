from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from syndicate.features.football.artifacts import football_source_artifacts_root
from syndicate.features.shared.source_roots import preferred_artifact_roots


def football_eval_root(*, sport: str) -> Path:
    root = football_source_artifacts_root(sport=sport)
    return root / "data" / "eval"


def football_eval_season_root(*, sport: str, season: int) -> Path:
    return football_eval_root(sport=sport) / "seasons" / str(int(season))


def football_eval_manifest_path(*, sport: str, season: int) -> Path:
    return football_eval_season_root(sport=sport, season=season) / "season_eval_manifest.json"


def football_eval_daily_path(*, sport: str, season: int, date: str, name: str) -> Path:
    return football_eval_season_root(sport=sport, season=season) / "daily" / str(date).replace("-", "_") / f"{name}.json"


def football_eval_calibration_path(*, sport: str, season: int, date: str) -> Path:
    return football_eval_daily_path(sport=sport, season=season, date=date, name="calibration")


def football_eval_calibration_report_path(*, sport: str, season: int, date: str) -> Path:
    return football_eval_daily_path(sport=sport, season=season, date=date, name="calibration_report")


def football_eval_calibration_summary_path(*, sport: str, season: int, date: str) -> Path:
    return football_eval_daily_path(sport=sport, season=season, date=date, name="calibration_summary")


def football_eval_backtest_manifest_path(*, sport: str, season: int) -> Path:
    return football_eval_season_root(sport=sport, season=season) / "backtest_manifest.json"


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _json_safe(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {key: _json_safe(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / float(len(values))


def _calibration_metrics(evaluation: dict[str, Any]) -> dict[str, Any]:
    calibration = evaluation.get("calibration") if isinstance(evaluation.get("calibration"), dict) else {}
    sim_vs_actual = evaluation.get("sim_vs_actual") if isinstance(evaluation.get("sim_vs_actual"), dict) else {}
    prop_accuracy = evaluation.get("prop_accuracy") if isinstance(evaluation.get("prop_accuracy"), dict) else {}

    win_probability_brier = _coerce_float((calibration.get("win_probability") or {}).get("brier") if isinstance(calibration.get("win_probability"), dict) else None)
    spread_mae = _coerce_float((calibration.get("spread") or {}).get("mae") if isinstance(calibration.get("spread"), dict) else None)
    total_mae = _coerce_float((calibration.get("total") or {}).get("mae") if isinstance(calibration.get("total"), dict) else None)
    prop_mae = _coerce_float((calibration.get("props") or {}).get("mae") if isinstance(calibration.get("props"), dict) else None)

    return {
        "game_calibration": {
            "win_probability": {
                "brier": win_probability_brier,
                "mae": _mean([abs(win_probability_brier)] if win_probability_brier is not None else []),
            },
            "spread": {"mae": spread_mae},
            "total": {"mae": total_mae},
        },
        "prop_calibration": {
            "mae": prop_mae,
            "sample_size": _coerce_float(prop_accuracy.get("player_count")) or 0,
        },
        "summary": {
            "game_count": _coerce_float(sim_vs_actual.get("game_count")) or 0,
            "player_count": _coerce_float(sim_vs_actual.get("player_count")) or 0,
            "overall_calibration_error": _mean([value for value in [win_probability_brier, spread_mae, total_mae, prop_mae] if value is not None]),
        },
    }


def persist_football_evaluation(*, sport: str, season: int, date: str, evaluation: dict[str, Any]) -> dict[str, str]:
    persisted: dict[str, str] = {}
    calibration = evaluation.get("calibration") if isinstance(evaluation.get("calibration"), dict) else {}
    sim_vs_actual = evaluation.get("sim_vs_actual") if isinstance(evaluation.get("sim_vs_actual"), dict) else {}
    prop_accuracy = evaluation.get("prop_accuracy") if isinstance(evaluation.get("prop_accuracy"), dict) else {}
    record = evaluation.get("evaluation_record")
    season_evaluation = evaluation.get("season_evaluation")
    calibration_summary = _calibration_metrics(evaluation)
    calibration_report = {
        "sport": sport,
        "season": season,
        "date": date,
        "calibration": calibration,
        "sim_vs_actual": sim_vs_actual,
        "prop_accuracy": prop_accuracy,
        "brier": evaluation.get("brier"),
        "roi": evaluation.get("roi"),
        "clv": evaluation.get("clv"),
        "win_rate": evaluation.get("win_rate"),
        "evaluation_record": str(record) if record is not None else None,
    }

    if calibration:
        persisted["calibration"] = str(_write_json(football_eval_calibration_path(sport=sport, season=season, date=date), calibration))
    persisted["calibration_summary"] = str(_write_json(football_eval_calibration_summary_path(sport=sport, season=season, date=date), calibration_summary))
    if sim_vs_actual:
        persisted["sim_vs_actual"] = str(_write_json(football_eval_daily_path(sport=sport, season=season, date=date, name="sim_vs_actual"), sim_vs_actual))
    if prop_accuracy:
        persisted["prop_accuracy"] = str(_write_json(football_eval_daily_path(sport=sport, season=season, date=date, name="prop_accuracy"), prop_accuracy))
    persisted["calibration_report"] = str(_write_json(football_eval_calibration_report_path(sport=sport, season=season, date=date), calibration_report))
    if isinstance(record, dict):
        persisted["evaluation_record"] = str(_write_json(football_eval_daily_path(sport=sport, season=season, date=date, name="evaluation_record"), record))
    elif record is not None:
        persisted["evaluation_record"] = str(_write_json(football_eval_daily_path(sport=sport, season=season, date=date, name="evaluation_record"), {"value": str(record)}))
    if season_evaluation is not None:
        if hasattr(season_evaluation, "__dict__") or isinstance(season_evaluation, dict):
            payload = _json_safe(season_evaluation)
        else:
            payload = {"value": str(season_evaluation)}
        persisted["season_evaluation"] = str(_write_json(football_eval_manifest_path(sport=sport, season=season), payload))
    return persisted


def build_football_season_backtest_manifest(*, sport: str, season: int, evaluation_records: list[dict[str, Any]]) -> dict[str, Any]:
    calibration_records = [record for record in evaluation_records if isinstance(record, dict)]
    calibration_summaries = [record.get("calibration") for record in calibration_records if isinstance(record.get("calibration"), dict)]
    calibration = {
        "sample_size": len(calibration_records),
        "sports": sorted({str(record.get("sport") or sport).strip().lower() for record in calibration_records if str(record.get("sport") or sport).strip()}),
    }
    brier_values = [float(record.get("brier")) for record in calibration_records if record.get("brier") is not None]
    roi_values = [float(record.get("roi")) for record in calibration_records if record.get("roi") is not None]
    clv_values = [float(record.get("clv")) for record in calibration_records if record.get("clv") is not None]
    win_rate_values = [float(record.get("win_rate")) for record in calibration_records if record.get("win_rate") is not None]
    return {
        "sport": sport,
        "season": season,
        "sample_size": len(calibration_records),
        "calibration": calibration,
        "sim_vs_actual": {
            "sample_size": len(calibration_records),
            "game_outputs": sum(int(record.get("sim_vs_actual", {}).get("game_count") or 0) for record in calibration_records if isinstance(record.get("sim_vs_actual"), dict)),
            "player_outputs": sum(int(record.get("sim_vs_actual", {}).get("player_count") or 0) for record in calibration_records if isinstance(record.get("sim_vs_actual"), dict)),
        },
        "brier": (sum(brier_values) / len(brier_values)) if brier_values else None,
        "roi": (sum(roi_values) / len(roi_values)) if roi_values else None,
        "clv": (sum(clv_values) / len(clv_values)) if clv_values else None,
        "win_rate": (sum(win_rate_values) / len(win_rate_values)) if win_rate_values else None,
        "calibration_summary": {
            "sample_size": len(calibration_summaries),
            "overall_calibration_error": _mean([
                _coerce_float((summary.get("win_probability") or {}).get("brier") if isinstance(summary, dict) else None)
                for summary in calibration_summaries
                if summary is not None
            ]),
        },
        "records": calibration_records,
    }


def persist_football_backtest_manifest(*, sport: str, season: int, evaluation_records: list[dict[str, Any]]) -> str:
    payload = build_football_season_backtest_manifest(sport=sport, season=season, evaluation_records=evaluation_records)
    return str(_write_json(football_eval_backtest_manifest_path(sport=sport, season=season), _json_safe(payload)))