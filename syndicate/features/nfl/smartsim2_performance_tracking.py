"""Real-world performance tracking for NFL's SmartSim 2.0 team-level model.

Added 2026-08-03 (Phase 1 football-season-readiness) to close the gap the
2026-08-02 end-to-end assessment found: NCAAF has an ongoing, real
performance log (smartsim2_performance_log.jsonl, 752 real graded games)
built by syndicate.features.ncaaf.smartsim2_performance_tracking; NFL had
only a manually-invoked CLI backtest (syndicate/features/football/evaluation.py)
whose persisted metrics turned out to be hardcoded placeholders
(brier/roi/clv/win_rate/mae all 0.0 in adapters.py), not real grading.

This mirrors the NCAAF module's design (same record-log-stats shape,
same measurement-only contract -- it does not modify SmartSim 2.0, only
grades numbers the model already produced), but deliberately simplified
for NFL's single-model reality: NCAAF reconciles two real engines
(Enhanced Totals Engine + SmartSim 2.0) into a Consensus blend and tracks
all three plus their disagreement categories; NFL has only the one
SmartSim 2.0 team-level model, so there is no second source to blend
against or disagree with. ``model_picked_winner``/``large_mismatch`` are
this module's single-source analogs of NCAAF's cross-source categories.

Join is by real game_id (schedule_{season}.csv and
smartsim2_projections_{season}_wk{week}.csv already share the identical
"{season}_{week:02d}_{away}_{home}" id) -- no fuzzy team-name
normalization needed, unlike NCAAF's (home, away) string join.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Sequence

from syndicate.features.nfl.sources import default_nfl_source_root

PERFORMANCE_LOG_PATH = default_nfl_source_root() / "data" / "smartsim2_performance_log.jsonl"

# Preseason's own log -- same directory/root convention as
# PERFORMANCE_LOG_PATH, distinct filename, never mixed with real
# regular-season records (added 2026-08-05 for the preseason evaluation/ROI
# task; see scripts/backfill_nfl_performance.py's --season-kind and
# scripts/fetch_nfl_preseason_odds.py's dated snapshot mechanism, the piece
# that makes preseason ATS/totals grading possible at all).
PRESEASON_PERFORMANCE_LOG_PATH = default_nfl_source_root() / "data" / "smartsim2_preseason_performance_log.jsonl"

# A market-margin-based reporting category, same spirit as NCAAF's
# LARGE_MISMATCH_MARGIN_THRESHOLD -- a review flag only, not a model input.
LARGE_MISMATCH_MARGIN_THRESHOLD = 14.0


@dataclass(frozen=True)
class GamePerformanceRecord:
    game_id: str
    season: int
    week: int
    home_team: str
    away_team: str
    market_margin: float | None
    market_total: float | None
    model_margin: float
    model_total: float
    actual_margin: float
    actual_total: float
    model_picked_winner: bool
    large_mismatch: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_game_performance_record(
    *,
    game_id: str,
    season: int,
    week: int,
    home_team: str,
    away_team: str,
    market_margin: float | None,
    market_total: float | None,
    model_margin: float,
    model_total: float,
    actual_home_points: float,
    actual_away_points: float,
) -> GamePerformanceRecord:
    actual_margin = actual_home_points - actual_away_points
    actual_total = actual_home_points + actual_away_points
    situational_margin = market_margin if market_margin is not None else model_margin
    return GamePerformanceRecord(
        game_id=game_id,
        season=season,
        week=week,
        home_team=home_team,
        away_team=away_team,
        market_margin=market_margin,
        market_total=market_total,
        model_margin=model_margin,
        model_total=model_total,
        actual_margin=actual_margin,
        actual_total=actual_total,
        model_picked_winner=(model_margin > 0) == (actual_margin > 0),
        large_mismatch=abs(situational_margin) >= LARGE_MISMATCH_MARGIN_THRESHOLD,
    )


def record_game_performance(
    record: GamePerformanceRecord,
    *,
    log_path: Path = PERFORMANCE_LOG_PATH,
) -> None:
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.to_dict()) + "\n")
    except Exception:  # noqa: BLE001 - monitoring must never break a caller
        pass


def read_performance_log(*, log_path: Path = PERFORMANCE_LOG_PATH) -> list[dict[str, Any]]:
    if not log_path.exists():
        return []
    records: list[dict[str, Any]] = []
    with log_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def _mae(errors: Sequence[float]) -> float:
    return sum(abs(e) for e in errors) / len(errors)


def _rmse(errors: Sequence[float]) -> float:
    return math.sqrt(sum(e * e for e in errors) / len(errors))


def _correlation(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    variance_x = sum((x - mean_x) ** 2 for x in xs)
    variance_y = sum((y - mean_y) ** 2 for y in ys)
    if variance_x == 0 or variance_y == 0:
        return None
    return covariance / math.sqrt(variance_x * variance_y)


def _side_accuracy(predicted_margins: Sequence[float], actual_margins: Sequence[float]) -> float:
    correct = sum(1 for p, a in zip(predicted_margins, actual_margins) if (p > 0) == (a > 0))
    return correct / len(predicted_margins)


def compute_margin_stats(records: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    if not records:
        return None
    predicted = [r["model_margin"] for r in records]
    actual = [r["actual_margin"] for r in records]
    errors = [p - a for p, a in zip(predicted, actual)]
    correlation = _correlation(predicted, actual)
    return {
        "n": len(records),
        "mae": round(_mae(errors), 3),
        "rmse": round(_rmse(errors), 3),
        "correlation": round(correlation, 4) if correlation is not None else None,
        "side_accuracy": round(_side_accuracy(predicted, actual), 4),
    }


def compute_total_stats(records: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    if not records:
        return None
    predicted = [r["model_total"] for r in records]
    actual = [r["actual_total"] for r in records]
    errors = [p - a for p, a in zip(predicted, actual)]
    correlation = _correlation(predicted, actual)
    return {
        "n": len(records),
        "mae": round(_mae(errors), 3),
        "rmse": round(_rmse(errors), 3),
        "correlation": round(correlation, 4) if correlation is not None else None,
    }


def _segment_stats(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return {
        "n": len(records),
        "margin": compute_margin_stats(records),
        "total": compute_total_stats(records),
    }


def summarize_performance(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    large_mismatch = [r for r in records if r["large_mismatch"]]
    return {
        "n_games": len(records),
        "overall": _segment_stats(records),
        "large_mismatch": _segment_stats(large_mismatch),
    }


def summarize_by_week(records: Sequence[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    weeks = sorted({r["week"] for r in records})
    return {week: _segment_stats([r for r in records if r["week"] == week]) for week in weeks}


__all__ = [
    "LARGE_MISMATCH_MARGIN_THRESHOLD",
    "PERFORMANCE_LOG_PATH",
    "PRESEASON_PERFORMANCE_LOG_PATH",
    "GamePerformanceRecord",
    "build_game_performance_record",
    "compute_margin_stats",
    "compute_total_stats",
    "read_performance_log",
    "record_game_performance",
    "summarize_by_week",
    "summarize_performance",
]
