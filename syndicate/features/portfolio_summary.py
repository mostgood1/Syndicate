from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from syndicate.features.prediction_ledger import get_performance_summary
from syndicate.features.prediction_ledger import load_all_predictions
from syndicate.features.shared.timezone import central_today_iso


def _outcome(prediction: Mapping[str, Any]) -> str:
    result = prediction.get("result") if isinstance(prediction.get("result"), Mapping) else None
    if result is None:
        return "pending"
    outcome = str(result.get("outcome") or "").strip().lower()
    return outcome or "pending"


def _placed_bet_text(prediction: Mapping[str, Any], legs: list[dict[str, Any]] | None) -> str:
    if legs:
        return f"Parlay ({len(legs)} legs)"
    market = str(prediction.get("market") or "").strip()
    selection = str(prediction.get("selection") or "").strip()
    if market and selection:
        return f"{selection} ({market})"
    return selection or market or "-"


def _position_row(prediction: Mapping[str, Any]) -> dict[str, Any]:
    result = prediction.get("result") if isinstance(prediction.get("result"), Mapping) else {}
    features = prediction.get("features_snapshot") if isinstance(prediction.get("features_snapshot"), Mapping) else {}
    matchup = str(features.get("event_id") or "").strip() or None
    legs = prediction.get("legs") if isinstance(prediction.get("legs"), list) else None
    bet_type = str(prediction.get("bet_type") or "straight").strip().lower() or "straight"
    return {
        "id": prediction.get("id"),
        "timestamp": prediction.get("timestamp"),
        "sport": prediction.get("sport"),
        "market": prediction.get("market"),
        "selection": prediction.get("selection"),
        "matchup": matchup,
        "odds": prediction.get("odds"),
        "edge": prediction.get("edge"),
        "confidence": prediction.get("confidence"),
        "status": _outcome(prediction),
        "pnl": result.get("pnl"),
        "clv": result.get("clv"),
        "stake": prediction.get("stake"),
        "bet_type": bet_type,
        "legs": legs,
        "placed_bet": _placed_bet_text(prediction, legs),
    }


def _exposure_by_sport(predictions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Open/pending stake only -- settled positions are no longer exposure,
    # they're realized pnl (already reflected in performance's by_sport).
    exposure: dict[str, float] = {}
    for prediction in predictions:
        if _outcome(prediction) != "pending":
            continue
        stake = prediction.get("stake")
        try:
            stake_value = float(stake) if stake is not None else 1.0
        except (TypeError, ValueError):
            stake_value = 1.0
        sport = str(prediction.get("sport") or "unknown").strip().lower() or "unknown"
        exposure[sport] = exposure.get(sport, 0.0) + stake_value
    total = sum(exposure.values())
    rows = [
        {
            "sport": sport,
            "stake": round(value, 2),
            "pct": round((value / total) * 100.0, 1) if total > 0 else 0.0,
        }
        for sport, value in exposure.items()
    ]
    return sorted(rows, key=lambda row: row["stake"], reverse=True)


def build_portfolio_summary(*, limit: int = 60) -> dict[str, Any]:
    """Real, ledger-backed portfolio state -- not a fabricated bankroll.

    prediction_ledger.py tracks recommendation quality (edge, confidence,
    settlement outcome), not dollar stakes, so this reports open/settled
    counts, win rate, ROI, and CLV in the ledger's own terms rather than
    inventing a bankroll figure the data model doesn't actually carry.
    """
    predictions = load_all_predictions()
    performance = get_performance_summary()

    today = central_today_iso()
    today_count = sum(1 for item in predictions if str(item.get("timestamp") or "").startswith(today))
    pending_count = sum(1 for item in predictions if _outcome(item) == "pending")

    ordered = sorted(predictions, key=lambda item: str(item.get("timestamp") or ""), reverse=True)
    positions = [_position_row(item) for item in ordered[:limit]]

    by_sport_raw = performance.get("by_sport") if isinstance(performance.get("by_sport"), dict) else {}
    by_sport = sorted(
        (
            {"sport": sport, **{key: value for key, value in stats.items() if key != "edges"}}
            for sport, stats in by_sport_raw.items()
            if isinstance(stats, dict)
        ),
        key=lambda row: row.get("predictions", 0),
        reverse=True,
    )

    return {
        "schema": "portfolio_summary_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "total_tracked": performance.get("total_bets", 0),
        "pending_count": pending_count,
        "today_count": today_count,
        "settled_count": performance.get("settled_count", 0),
        "decisive_count": performance.get("decisive_count", 0),
        "win_rate": performance.get("win_rate"),
        "roi": performance.get("roi"),
        "total_pnl": performance.get("total_pnl"),
        "avg_edge": performance.get("avg_edge"),
        "avg_clv": performance.get("average_clv"),
        "by_sport": by_sport,
        "exposure_by_sport": _exposure_by_sport(predictions),
        "positions": positions,
    }


__all__ = ["build_portfolio_summary"]
