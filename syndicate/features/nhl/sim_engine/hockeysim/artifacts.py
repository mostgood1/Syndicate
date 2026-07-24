"""Artifact writers — hockeysim predictions -> the exact CSV contracts the NHL UI reads.

The Syndicate NHL surfaces (``syndicate/features/nhl/cards.py`` etc.) read
``data/processed/predictions_{date}.csv`` with a fixed column set (mapped 1:1 to card fields). The
local producer must emit byte-compatible rows so the UI is untouched when the vendor subprocess is
retired (Phase 5). This module owns that column contract.

Mirrors soccer/football ``artifacts.py``: pure row-shaping + CSV writing, no simulation.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .contracts import HockeyGamePrediction, HockeyMarketLines

# Exact predictions_{date}.csv column order the UI consumes (the vendor game-predictions contract).
PREDICTIONS_COLUMNS: List[str] = [
    "home", "away", "proj_home_goals", "proj_away_goals", "model_total", "model_spread",
    "p_home_ml", "p_away_ml", "date",
    "period1_home_proj", "period1_away_proj", "period2_home_proj", "period2_away_proj",
    "period3_home_proj", "period3_away_proj",
    "p_f10_yes", "p_f10_no", "totals_line_used",
    "home_ml_odds", "away_ml_odds", "over_odds", "under_odds",
    "home_pl_-1.5_odds", "away_pl_+1.5_odds",
    "p_over", "p_under", "p_push_total", "p_home_pl_-1.5", "p_away_pl_+1.5",
    "ev_home_ml", "ev_away_ml", "ev_over", "ev_under", "ev_home_pl_-1.5", "ev_away_pl_+1.5",
]


def _fmt(value: object) -> object:
    """Round floats to 4dp for stable output; pass through None/str/int."""
    if isinstance(value, float):
        return round(value, 6)
    return value


def prediction_to_row(pred: HockeyGamePrediction, market: Optional[HockeyMarketLines] = None) -> Dict[str, object]:
    """Map a :class:`HockeyGamePrediction` (+ its market) to a predictions_{date}.csv row dict."""
    m = market or HockeyMarketLines()
    ev = pred.ev or {}
    row: Dict[str, object] = {
        "home": pred.home,
        "away": pred.away,
        "proj_home_goals": _fmt(pred.proj_home_goals),
        "proj_away_goals": _fmt(pred.proj_away_goals),
        "model_total": _fmt(pred.model_total),
        "model_spread": _fmt(pred.model_spread),
        "p_home_ml": _fmt(pred.p_home_ml),
        "p_away_ml": _fmt(pred.p_away_ml),
        "date": pred.date,
        "period1_home_proj": _fmt(pred.period_home_proj[0]),
        "period1_away_proj": _fmt(pred.period_away_proj[0]),
        "period2_home_proj": _fmt(pred.period_home_proj[1]),
        "period2_away_proj": _fmt(pred.period_away_proj[1]),
        "period3_home_proj": _fmt(pred.period_home_proj[2]),
        "period3_away_proj": _fmt(pred.period_away_proj[2]),
        "p_f10_yes": _fmt(pred.p_f10_yes),
        "p_f10_no": _fmt(pred.p_f10_no),
        "totals_line_used": _fmt(pred.totals_line_used if pred.totals_line_used is not None else m.total_line),
        "home_ml_odds": m.home_ml_odds,
        "away_ml_odds": m.away_ml_odds,
        "over_odds": m.over_odds,
        "under_odds": m.under_odds,
        "home_pl_-1.5_odds": m.home_pl_odds,
        "away_pl_+1.5_odds": m.away_pl_odds,
        "p_over": _fmt(pred.p_over),
        "p_under": _fmt(pred.p_under),
        "p_push_total": _fmt(pred.p_push_total),
        "p_home_pl_-1.5": _fmt(pred.p_home_pl_minus_1_5),
        "p_away_pl_+1.5": _fmt(pred.p_away_pl_plus_1_5),
        "ev_home_ml": _fmt(ev.get("home_ml")),
        "ev_away_ml": _fmt(ev.get("away_ml")),
        "ev_over": _fmt(ev.get("over")),
        "ev_under": _fmt(ev.get("under")),
        "ev_home_pl_-1.5": _fmt(ev.get("home_pl_-1.5")),
        "ev_away_pl_+1.5": _fmt(ev.get("away_pl_+1.5")),
    }
    return row


def write_predictions_csv(
    path: Path,
    predictions: Iterable[HockeyGamePrediction],
    markets: Optional[Dict[str, HockeyMarketLines]] = None,
) -> int:
    """Write predictions_{date}.csv. ``markets`` maps game_pk -> lines. Returns the row count."""
    markets = markets or {}
    rows = [prediction_to_row(p, markets.get(p.game_pk)) for p in predictions]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=PREDICTIONS_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return len(rows)
