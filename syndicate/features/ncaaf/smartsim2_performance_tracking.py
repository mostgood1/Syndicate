"""Real-world performance tracking: Enhanced Totals Engine vs SmartSim 2.0 vs Consensus.

Production Monitoring Phase 1 (see ``smartsim_live_performance_report.md``):
this module is measurement-only. It does not modify SmartSim 2.0, the
Enhanced Totals Engine, or the blend -- it imports
``smartsim2_blend.compute_blend()`` to compute Consensus values from numbers
those systems already produced, exactly as ``smartsim2_projection.py`` and
``smartsim2_trial_monitoring.py`` do for their own purposes.

Disagreement/mismatch categorization reuses the exact definitions established
in ``smartsim_signal_attribution_report.md`` / ``smartsim_decision_policy_report.md``:
``side_disagreement`` (Engine and SmartSim pick different sides),
``total_disagreement`` (Engine/SmartSim totals differ by >= 10 points), and
``large_mismatch`` (a market-margin-based reporting category,
``LARGE_MISMATCH_MARGIN_THRESHOLD`` imported directly from ``smartsim2_blend``
rather than re-declared). As of the ATS policy implementation (see
``smartsim_ats_policy_implementation_report.md``), ``large_mismatch`` no
longer drives any blend decision -- ``compute_blend()``'s margin is decided
by ``side_disagreement`` alone. This category is retained here purely for
reporting/analysis continuity with every prior phase's breakdowns.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Sequence

from syndicate.features.ncaaf.smartsim2_blend import LARGE_MISMATCH_MARGIN_THRESHOLD
from syndicate.features.ncaaf.smartsim2_blend import compute_blend
from syndicate.features.ncaaf.sources import default_ncaaf_source_root

PERFORMANCE_LOG_PATH = default_ncaaf_source_root() / "data" / "smartsim2_performance_log.jsonl"

# Independent of LARGE_MISMATCH_MARGIN_THRESHOLD -- this is the totals-specific
# disagreement definition from the signal attribution study, not a blend policy input.
TOTAL_DISAGREEMENT_THRESHOLD = 10.0

SOURCES: tuple[str, ...] = ("engine", "smartsim", "consensus")
_MARGIN_FIELDS = {"engine": "engine_margin", "smartsim": "smartsim_margin", "consensus": "consensus_margin"}
_TOTAL_FIELDS = {"engine": "engine_total", "smartsim": "smartsim_total", "consensus": "consensus_total"}


@dataclass(frozen=True)
class GamePerformanceRecord:
    game_id: str
    season: int
    week: int
    home_team: str
    away_team: str
    conference_game: bool
    market_margin: float | None
    market_total: float | None
    engine_margin: float
    engine_total: float
    smartsim_margin: float
    smartsim_total: float
    consensus_margin: float
    consensus_total: float
    consensus_used_smartsim_margin: bool
    actual_margin: float
    actual_total: float
    side_disagreement: bool
    total_disagreement: bool
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
    conference_game: bool,
    market_margin: float | None,
    market_total: float | None,
    engine_margin: float,
    engine_total: float,
    smartsim_margin: float,
    smartsim_total: float,
    actual_home_points: float,
    actual_away_points: float,
) -> GamePerformanceRecord:
    blend = compute_blend(
        engine_margin=engine_margin,
        smartsim_margin=smartsim_margin,
        engine_total=engine_total,
        smartsim_total=smartsim_total,
    )
    # large_mismatch is an independent reporting category (see
    # smartsim_monitoring_phase2_report.md) -- it is no longer a compute_blend()
    # input, but is still measured the same way it always has been.
    situational_margin = market_margin if market_margin is not None else engine_margin
    actual_margin = actual_home_points - actual_away_points
    actual_total = actual_home_points + actual_away_points
    return GamePerformanceRecord(
        game_id=game_id,
        season=season,
        week=week,
        home_team=home_team,
        away_team=away_team,
        conference_game=conference_game,
        market_margin=market_margin,
        market_total=market_total,
        engine_margin=engine_margin,
        engine_total=engine_total,
        smartsim_margin=smartsim_margin,
        smartsim_total=smartsim_total,
        consensus_margin=blend.margin,
        consensus_total=blend.total,
        consensus_used_smartsim_margin=blend.smartsim_margin_used,
        actual_margin=actual_margin,
        actual_total=actual_total,
        side_disagreement=(engine_margin > 0) != (smartsim_margin > 0),
        total_disagreement=abs(engine_total - smartsim_total) >= TOTAL_DISAGREEMENT_THRESHOLD,
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


def compute_margin_stats(records: Sequence[dict[str, Any]], source: str) -> dict[str, Any] | None:
    if not records:
        return None
    field = _MARGIN_FIELDS[source]
    predicted = [r[field] for r in records]
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


def compute_total_stats(records: Sequence[dict[str, Any]], source: str) -> dict[str, Any] | None:
    if not records:
        return None
    field = _TOTAL_FIELDS[source]
    predicted = [r[field] for r in records]
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
        "margin": {source: compute_margin_stats(records, source) for source in SOURCES},
        "total": {source: compute_total_stats(records, source) for source in SOURCES},
    }


def summarize_performance(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    side_disagreement = [r for r in records if r["side_disagreement"]]
    total_disagreement = [r for r in records if r["total_disagreement"]]
    large_mismatch = [r for r in records if r["large_mismatch"]]
    conference_games = [r for r in records if r["conference_game"]]
    non_conference_games = [r for r in records if not r["conference_game"]]
    return {
        "n_games": len(records),
        "overall": _segment_stats(records),
        "side_disagreement": _segment_stats(side_disagreement),
        "total_disagreement": _segment_stats(total_disagreement),
        "large_mismatch": _segment_stats(large_mismatch),
        "conference_games": _segment_stats(conference_games),
        "non_conference_games": _segment_stats(non_conference_games),
    }


def summarize_by_week(records: Sequence[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    weeks = sorted({r["week"] for r in records})
    return {week: _segment_stats([r for r in records if r["week"] == week]) for week in weeks}


# ---------------------------------------------------------------------------
# Phase 2: rolling windows, season-to-date, high/low-total split, drift checks
# ---------------------------------------------------------------------------
#
# Games carry no exact kickoff timestamp in this record (only ``week`` and
# ``game_id``), so chronological order here is (week, game_id) -- CFBD game
# ids are assigned in a stable, roughly time-ordered scheme within a week.
# This is disclosed as an approximation, not exact kickoff order, but is
# adequate at the 50-100 game window granularities this phase analyzes.

# Thresholds below are review triggers for this report, not production
# policy inputs -- they do not feed into smartsim2_blend.py in any way.
PERFORMANCE_DRIFT_ACCURACY_POINTS_THRESHOLD = 8.0
PERFORMANCE_DRIFT_MAE_THRESHOLD = 2.0
CALIBRATION_DRIFT_BIAS_POINTS_THRESHOLD = 2.0
POLICY_DRIFT_ACCURACY_POINTS_THRESHOLD = 15.0


def order_records_chronologically(records: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(records, key=lambda r: (r["week"], int(r["game_id"])))


def rolling_windows(records: Sequence[dict[str, Any]], window_size: int) -> list[dict[str, Any]]:
    """Non-overlapping sequential chunks of ``window_size`` games in chronological order.

    The final, partial chunk (fewer than ``window_size`` games) is included
    so the full sample is always covered, but is labeled ``partial=True`` so
    callers can treat it as lower-confidence.
    """
    ordered = order_records_chronologically(records)
    windows = []
    for start in range(0, len(ordered), window_size):
        chunk = ordered[start : start + window_size]
        windows.append(
            {
                "window_index": start // window_size + 1,
                "start": start + 1,
                "end": start + len(chunk),
                "partial": len(chunk) < window_size,
                **_segment_stats(chunk),
            }
        )
    return windows


def summarize_season_to_date(records: Sequence[dict[str, Any]], *, checkpoint_size: int = 50) -> list[dict[str, Any]]:
    """Cumulative stats from game 1 through each checkpoint boundary, plus a final checkpoint."""
    ordered = order_records_chronologically(records)
    checkpoints = list(range(checkpoint_size, len(ordered), checkpoint_size))
    if not checkpoints or checkpoints[-1] != len(ordered):
        checkpoints.append(len(ordered))
    return [{"through_game": n, **_segment_stats(ordered[:n])} for n in checkpoints if n > 0]


def partition_by_total_level(records: Sequence[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split into (high_total, low_total) by the sample's own median market total.

    Data-driven rather than a fixed point cutoff, so the split is meaningful
    regardless of how total-scoring norms shift week to week.
    """
    with_market_total = [r for r in records if r.get("market_total") is not None]
    if not with_market_total:
        return [], []
    median_total = statistics_median([r["market_total"] for r in with_market_total])
    high = [r for r in with_market_total if r["market_total"] >= median_total]
    low = [r for r in with_market_total if r["market_total"] < median_total]
    return high, low


def statistics_median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _half_split(records: Sequence[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ordered = order_records_chronologically(records)
    mid = len(ordered) // 2
    return ordered[:mid], ordered[mid:]


def detect_drift(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Compare the chronological first half vs. second half of the sample.

    Returns a dict with three independent checks -- ``performance_drift``
    (has any source's accuracy or MAE moved by more than the review
    threshold), ``calibration_drift`` (has SmartSim's raw, uncorrected total
    bias moved away from the ``SMARTSIM_TOTAL_BIAS`` constant the blend
    assumes), and ``policy_drift`` (does the large-mismatch/side-disagreement
    subset -- the one the Phase 4 policy revision targeted -- still favor
    SmartSim by a similar margin in both halves). All three are review
    flags for this report only; none of them feed back into the blend.
    """
    first_half, second_half = _half_split(records)
    if not first_half or not second_half:
        return {
            "n_first_half": len(first_half),
            "n_second_half": len(second_half),
            "performance_drift": {"flagged": False, "reason": "insufficient data for both halves"},
            "calibration_drift": {"flagged": False, "reason": "insufficient data for both halves"},
            "policy_drift": {"flagged": False, "reason": "insufficient data for both halves"},
        }

    first_stats = _segment_stats(first_half)
    second_stats = _segment_stats(second_half)

    performance_flags = []
    for source in SOURCES:
        first_margin = first_stats["margin"][source]
        second_margin = second_stats["margin"][source]
        if first_margin and second_margin:
            accuracy_delta = (second_margin["side_accuracy"] - first_margin["side_accuracy"]) * 100
            mae_delta = second_margin["mae"] - first_margin["mae"]
            if abs(accuracy_delta) >= PERFORMANCE_DRIFT_ACCURACY_POINTS_THRESHOLD:
                performance_flags.append(f"{source} side_accuracy moved {accuracy_delta:+.1f} pts (first->second half)")
            if abs(mae_delta) >= PERFORMANCE_DRIFT_MAE_THRESHOLD:
                performance_flags.append(f"{source} margin MAE moved {mae_delta:+.2f} (first->second half)")

    smartsim_raw_bias_first = _mean_signed_error(first_half, "smartsim_total", "actual_total")
    smartsim_raw_bias_second = _mean_signed_error(second_half, "smartsim_total", "actual_total")
    calibration_delta = (
        None
        if smartsim_raw_bias_first is None or smartsim_raw_bias_second is None
        else smartsim_raw_bias_second - smartsim_raw_bias_first
    )
    calibration_flagged = calibration_delta is not None and abs(calibration_delta) >= CALIBRATION_DRIFT_BIAS_POINTS_THRESHOLD

    first_lm_side = [r for r in first_half if r["large_mismatch"] and r["side_disagreement"]]
    second_lm_side = [r for r in second_half if r["large_mismatch"] and r["side_disagreement"]]
    first_gap = _accuracy_gap(first_lm_side)
    second_gap = _accuracy_gap(second_lm_side)
    policy_delta = None if first_gap is None or second_gap is None else second_gap - first_gap
    policy_flagged = policy_delta is not None and abs(policy_delta) >= POLICY_DRIFT_ACCURACY_POINTS_THRESHOLD

    return {
        "n_first_half": len(first_half),
        "n_second_half": len(second_half),
        "performance_drift": {"flagged": bool(performance_flags), "details": performance_flags},
        "calibration_drift": {
            "flagged": calibration_flagged,
            "smartsim_raw_total_bias_first_half": smartsim_raw_bias_first,
            "smartsim_raw_total_bias_second_half": smartsim_raw_bias_second,
            "delta": calibration_delta,
        },
        "policy_drift": {
            "flagged": policy_flagged,
            "n_first_half_subset": len(first_lm_side),
            "n_second_half_subset": len(second_lm_side),
            "smartsim_minus_engine_accuracy_gap_pts_first_half": first_gap,
            "smartsim_minus_engine_accuracy_gap_pts_second_half": second_gap,
            "delta": policy_delta,
        },
    }


def _mean_signed_error(records: Sequence[dict[str, Any]], field: str, actual_field: str) -> float | None:
    if not records:
        return None
    errors = [r[field] - r[actual_field] for r in records]
    return round(sum(errors) / len(errors), 3)


def _accuracy_gap(records: Sequence[dict[str, Any]]) -> float | None:
    """SmartSim side accuracy minus Engine side accuracy, in percentage points."""
    if not records:
        return None
    engine_stats = compute_margin_stats(records, "engine")
    smartsim_stats = compute_margin_stats(records, "smartsim")
    if not engine_stats or not smartsim_stats:
        return None
    return round((smartsim_stats["side_accuracy"] - engine_stats["side_accuracy"]) * 100, 2)


__all__ = [
    "CALIBRATION_DRIFT_BIAS_POINTS_THRESHOLD",
    "PERFORMANCE_DRIFT_ACCURACY_POINTS_THRESHOLD",
    "PERFORMANCE_DRIFT_MAE_THRESHOLD",
    "PERFORMANCE_LOG_PATH",
    "POLICY_DRIFT_ACCURACY_POINTS_THRESHOLD",
    "SOURCES",
    "TOTAL_DISAGREEMENT_THRESHOLD",
    "GamePerformanceRecord",
    "build_game_performance_record",
    "compute_margin_stats",
    "compute_total_stats",
    "detect_drift",
    "order_records_chronologically",
    "partition_by_total_level",
    "read_performance_log",
    "record_game_performance",
    "rolling_windows",
    "summarize_by_week",
    "summarize_performance",
    "summarize_season_to_date",
]
