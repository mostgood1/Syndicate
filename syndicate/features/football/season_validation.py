from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict
from dataclasses import is_dataclass
from pathlib import Path
from typing import Any

from syndicate.features.football.adapters import FootballSimulationAdapter
from syndicate.features.football.evaluation import football_eval_backtest_manifest_path
from syndicate.features.football.evaluation import football_eval_calibration_report_path
from syndicate.features.football.evaluation import football_eval_calibration_summary_path
from syndicate.features.football.evaluation import football_eval_daily_path
from syndicate.features.football.evaluation import football_eval_manifest_path
from syndicate.features.football.evaluation import persist_football_backtest_manifest


def _json_safe(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _json_safe(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value


def _load_json_file(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def run_football_season_validation(*, sport: str, season: int, dates: list[str], selection: int | None = None) -> dict[str, Any]:
    adapter = FootballSimulationAdapter(sport=sport)
    records: list[dict[str, Any]] = []
    date_outputs: list[dict[str, Any]] = []

    for date in dates:
        simulation_input = adapter.load_features(date=date, selection=selection, season=season)
        simulation_output = adapter.simulate_games(simulation_input)
        persisted = adapter.persist_evaluation(simulation_output, season=season)
        evaluation = adapter.evaluate(simulation_output)
        record = _json_safe(evaluation.get("evaluation_record"))
        if isinstance(record, dict):
            records.append(record)
        date_outputs.append(
            {
                "date": date,
                "persisted": persisted,
                "paths": {
                    "season_eval_manifest": str(football_eval_manifest_path(sport=sport, season=season)),
                    "backtest_manifest": str(football_eval_backtest_manifest_path(sport=sport, season=season)),
                    "calibration_summary": str(football_eval_calibration_summary_path(sport=sport, season=season, date=date)),
                    "calibration_report": str(football_eval_calibration_report_path(sport=sport, season=season, date=date)),
                    "sim_vs_actual": str(football_eval_daily_path(sport=sport, season=season, date=date, name="sim_vs_actual")),
                },
            }
        )

    season_manifest_path = persist_football_backtest_manifest(sport=sport, season=season, evaluation_records=records)
    latest_output = date_outputs[-1] if date_outputs else {}
    latest_paths = latest_output.get("paths") if isinstance(latest_output.get("paths"), dict) else {}
    calibration_summary = _load_json_file(latest_paths.get("calibration_summary", ""))
    calibration_report = _load_json_file(latest_paths.get("calibration_report", ""))
    sim_vs_actual = _load_json_file(latest_paths.get("sim_vs_actual", ""))
    calibration_values = [record.get("calibration", {}) for record in records if isinstance(record, dict)]
    brier_values = [float((record.get("brier") or 0.0)) for record in records if isinstance(record, dict) and record.get("brier") is not None]
    spread_errors = [float((calibration.get("spread") or {}).get("mae") or 0.0) for calibration in calibration_values if isinstance(calibration, dict)]
    total_errors = [float((calibration.get("total") or {}).get("mae") or 0.0) for calibration in calibration_values if isinstance(calibration, dict)]
    prop_errors = [float((calibration.get("props") or {}).get("mae") or 0.0) for calibration in calibration_values if isinstance(calibration, dict)]
    largest_misses = Counter({"game_calibration": len(spread_errors), "prop_calibration": len(prop_errors)})
    review = {
        "sport": sport,
        "season": season,
        "calibration": {
            "win_probability": {
                "sample_size": len(brier_values),
                "mean_brier": (sum(brier_values) / len(brier_values)) if brier_values else None,
            },
            "spread": {
                "sample_size": len(spread_errors),
                "mean_mae": (sum(spread_errors) / len(spread_errors)) if spread_errors else None,
            },
            "total": {
                "sample_size": len(total_errors),
                "mean_mae": (sum(total_errors) / len(total_errors)) if total_errors else None,
            },
        },
        "error_analysis": {
            "largest_misses": dict(largest_misses),
            "systematic_bias": "unknown_until_historical_backtest",
            "missing_feature_impacts": ["EPA/play", "Success Rate", "Snap Share", "Target Share", "Route Participation", "Goal Line Share", "Red Zone Share"],
        },
        "data_quality": {
            "placeholder_inputs": ["advanced football usage metrics", "historical play-by-play depth", "injury depth-chart signals"],
            "highest_value_feeds": ["EPA/play", "Success Rate", "Pass Rate Over Expectation", "Red Zone Efficiency", "Explosive Play Rate"],
        },
        "recommendation": {
            "ready_for_advanced_data_phase": False,
        },
        "artifact_inputs": {
            "calibration_summary": calibration_summary,
            "calibration_report": calibration_report,
            "sim_vs_actual": sim_vs_actual,
        },
    }
    return {
        "sport": sport,
        "season": season,
        "dates": list(dates),
        "run_count": len(records),
        "backtest_manifest": season_manifest_path,
        "review": review,
        "date_outputs": date_outputs,
    }


def build_football_season_review_markdown(review: dict[str, Any], *, calibration_summary: dict[str, Any] | None = None, calibration_report: dict[str, Any] | None = None, sim_vs_actual: dict[str, Any] | None = None) -> str:
    calibration = review.get("calibration") if isinstance(review.get("calibration"), dict) else {}
    error_analysis = review.get("error_analysis") if isinstance(review.get("error_analysis"), dict) else {}
    data_quality = review.get("data_quality") if isinstance(review.get("data_quality"), dict) else {}
    recommendation = review.get("recommendation") if isinstance(review.get("recommendation"), dict) else {}
    calibration_summary = calibration_summary if isinstance(calibration_summary, dict) else {}
    calibration_report = calibration_report if isinstance(calibration_report, dict) else {}
    sim_vs_actual = sim_vs_actual if isinstance(sim_vs_actual, dict) else {}
    game_calibration = calibration_summary.get("game_calibration") if isinstance(calibration_summary.get("game_calibration"), dict) else {}
    prop_calibration = calibration_summary.get("prop_calibration") if isinstance(calibration_summary.get("prop_calibration"), dict) else {}
    summary = calibration_summary.get("summary") if isinstance(calibration_summary.get("summary"), dict) else {}
    win_probability = game_calibration.get("win_probability") if isinstance(game_calibration.get("win_probability"), dict) else {}
    spread = game_calibration.get("spread") if isinstance(game_calibration.get("spread"), dict) else {}
    total = game_calibration.get("total") if isinstance(game_calibration.get("total"), dict) else {}
    report_calibration = calibration_report.get("calibration") if isinstance(calibration_report.get("calibration"), dict) else {}
    report_sim_vs_actual = calibration_report.get("sim_vs_actual") if isinstance(calibration_report.get("sim_vs_actual"), dict) else {}
    report_prop_accuracy = calibration_report.get("prop_accuracy") if isinstance(calibration_report.get("prop_accuracy"), dict) else {}
    games_value = summary.get("game_count") if summary else report_sim_vs_actual.get("game_count") if report_sim_vs_actual else sim_vs_actual.get("game_count")
    players_value = summary.get("player_count") if summary else report_sim_vs_actual.get("player_count") if report_sim_vs_actual else sim_vs_actual.get("player_count")
    prop_samples_value = prop_calibration.get("sample_size") if prop_calibration else report_prop_accuracy.get("player_count") if report_prop_accuracy else sim_vs_actual.get("prop_samples")
    win_brier_value = win_probability.get("brier") if win_probability else (report_calibration.get("win_probability") or {}).get("brier")
    win_mae_value = win_probability.get("mae") if win_probability else None
    spread_mae_value = spread.get("mae") if spread else (report_calibration.get("spread") or {}).get("mae")
    total_mae_value = total.get("mae") if total else (report_calibration.get("total") or {}).get("mae")
    prop_mae_value = prop_calibration.get("mae") if prop_calibration else (report_calibration.get("props") or {}).get("mae")

    lines = [
        "# Football Season Review",
        "",
        "## Calibration",
        "",
        f"- Win probability Brier: {win_brier_value if win_brier_value is not None else 'n/a'}",
        f"- Win probability MAE: {win_mae_value if win_mae_value is not None else 'n/a'}",
        f"- Spread MAE: {spread_mae_value if spread_mae_value is not None else 'n/a'}",
        f"- Total MAE: {total_mae_value if total_mae_value is not None else 'n/a'}",
        f"- Prop MAE: {prop_mae_value if prop_mae_value is not None else 'n/a'}",
        f"- Sample size: games={games_value if games_value is not None else 'n/a'}, players={players_value if players_value is not None else 'n/a'}, prop_samples={prop_samples_value if prop_samples_value is not None else 'n/a'}",
        "",
        "## Error Analysis",
        "",
        f"- Largest misses: {json.dumps(error_analysis.get('largest_misses', {}), ensure_ascii=False, sort_keys=True)}",
        f"- Systematic bias: {error_analysis.get('systematic_bias') or 'unknown_until_historical_backtest'}",
        f"- Missing feature impacts: {', '.join(error_analysis.get('missing_feature_impacts') or []) or 'pending advanced-data review'}",
        "",
        "## Data Quality Assessment",
        "",
        f"- Placeholder inputs: {', '.join(data_quality.get('placeholder_inputs') or []) or 'pending historical season run'}",
        f"- Highest-value advanced feeds: {', '.join(data_quality.get('highest_value_feeds') or []) or 'see football_data_acquisition_plan.md'}",
        "",
        "## Recommendation",
        "",
        f"- Ready for advanced-data phase: {'YES' if recommendation.get('ready_for_advanced_data_phase') else 'NO'}",
        "",
    ]
    return "\n".join(lines)


def write_football_season_review(review: dict[str, Any], out_path: str | Path) -> str:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        build_football_season_review_markdown(
            review,
            calibration_summary=review.get("artifact_inputs", {}).get("calibration_summary") if isinstance(review.get("artifact_inputs"), dict) else None,
            calibration_report=review.get("artifact_inputs", {}).get("calibration_report") if isinstance(review.get("artifact_inputs"), dict) else None,
            sim_vs_actual=review.get("artifact_inputs", {}).get("sim_vs_actual") if isinstance(review.get("artifact_inputs"), dict) else None,
        ),
        encoding="utf-8",
    )
    return str(path)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a football historical season validation loop")
    parser.add_argument("--sport", required=True, choices=("nfl", "ncaaf"))
    parser.add_argument("--season", required=True, type=int)
    parser.add_argument("--dates", required=True, help="Comma-separated list of ISO dates to evaluate")
    parser.add_argument("--selection", type=int, default=1)
    parser.add_argument("--out", default="", help="Optional JSON output path")
    parser.add_argument("--review-out", default="", help="Optional markdown review output path")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    dates = [part.strip() for part in str(args.dates or "").split(",") if part.strip()]
    payload = run_football_season_validation(sport=args.sport, season=int(args.season), dates=dates, selection=args.selection)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
    else:
        print(text)
    if args.review_out:
        write_football_season_review(payload.get("review") or {}, args.review_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())