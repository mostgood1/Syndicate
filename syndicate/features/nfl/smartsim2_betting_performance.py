"""Betting-performance grading for NFL's SmartSim 2.0 model.

Mirrors syndicate.features.ncaaf.smartsim2_betting_performance, adapted to
NFL's single-model records (see smartsim2_performance_tracking.py's module
docstring for why there is no multi-source comparison here). Measures
betting outcomes (ATS and totals, win %, ROI, units won/lost), not
forecast-accuracy statistics (MAE/RMSE/correlation belong to
smartsim2_performance_tracking.py) -- this answers "would betting on the
model's picks have made money against the real closing line."

Reads the same per-game records smartsim2_performance_tracking.py
produces (model_margin, market_margin, actual_margin and the totals
equivalents) -- does not recompute or duplicate those fields, only grades
bets from them.

Odds assumption, stated plainly: real per-game ATS/totals prices (juice)
are not part of schedule_{season}.csv (only the point spread/total
themselves, plus moneylines). Every graded bet here assumes the standard
flat -110/-110 price on both sides, the same disclosed assumption
NCAAF's equivalent module makes for the identical reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Literal
from typing import Sequence

# Standard flat -110 both sides: risk 1.0 unit to win 100/110 units net.
UNIT_RISK = 1.0
NET_PROFIT_PER_WIN = 100.0 / 110.0
NET_LOSS_PER_LOSS = -1.0

PickGrade = Literal["win", "loss", "push", "no_pick"]


def grade_ats_pick(model_margin: float, market_margin: float, actual_margin: float) -> PickGrade:
    """Grade one ATS bet: the model picks the side it projects to beat the closing market margin."""
    if model_margin == market_margin:
        return "no_pick"
    picked_home = model_margin > market_margin
    if actual_margin == market_margin:
        return "push"
    home_covered = actual_margin > market_margin
    return "win" if picked_home == home_covered else "loss"


def grade_totals_pick(model_total: float, market_total: float, actual_total: float) -> PickGrade:
    """Grade one totals bet: the model picks Over/Under relative to the closing market total."""
    if model_total == market_total:
        return "no_pick"
    picked_over = model_total > market_total
    if actual_total == market_total:
        return "push"
    went_over = actual_total > market_total
    return "win" if picked_over == went_over else "loss"


@dataclass(frozen=True)
class BettingStats:
    n_graded: int
    wins: int
    losses: int
    pushes: int
    no_picks: int
    win_pct: float | None
    roi_pct: float | None
    units_net: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_graded": self.n_graded,
            "wins": self.wins,
            "losses": self.losses,
            "pushes": self.pushes,
            "no_picks": self.no_picks,
            "win_pct": self.win_pct,
            "roi_pct": self.roi_pct,
            "units_net": self.units_net,
        }


def _summarize_grades(grades: Sequence[PickGrade]) -> BettingStats:
    wins = sum(1 for g in grades if g == "win")
    losses = sum(1 for g in grades if g == "loss")
    pushes = sum(1 for g in grades if g == "push")
    no_picks = sum(1 for g in grades if g == "no_pick")
    decided = wins + losses
    units_net = round(wins * NET_PROFIT_PER_WIN + losses * NET_LOSS_PER_LOSS, 4)
    win_pct = round(100.0 * wins / decided, 2) if decided else None
    roi_pct = round(100.0 * units_net / decided, 2) if decided else None
    return BettingStats(
        n_graded=len(grades),
        wins=wins,
        losses=losses,
        pushes=pushes,
        no_picks=no_picks,
        win_pct=win_pct,
        roi_pct=roi_pct,
        units_net=units_net,
    )


def compute_ats_stats(records: Sequence[dict[str, Any]]) -> BettingStats | None:
    if not records:
        return None
    grades = [
        grade_ats_pick(r["model_margin"], r["market_margin"], r["actual_margin"])
        for r in records
        if r.get("market_margin") is not None
    ]
    if not grades:
        return None
    return _summarize_grades(grades)


def compute_totals_stats(records: Sequence[dict[str, Any]]) -> BettingStats | None:
    if not records:
        return None
    grades = [
        grade_totals_pick(r["model_total"], r["market_total"], r["actual_total"])
        for r in records
        if r.get("market_total") is not None
    ]
    if not grades:
        return None
    return _summarize_grades(grades)


def summarize_betting_performance(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """ATS and totals betting stats, overall and for the large-mismatch subset."""

    def _segment(subset: Sequence[dict[str, Any]]) -> dict[str, Any]:
        ats = compute_ats_stats(subset)
        totals = compute_totals_stats(subset)
        return {
            "n": len(subset),
            "ats": ats.to_dict() if ats else None,
            "totals": totals.to_dict() if totals else None,
        }

    large_mismatch = [r for r in records if r["large_mismatch"]]
    return {
        "n_games": len(records),
        "overall": _segment(records),
        "large_mismatch": _segment(large_mismatch),
    }


__all__ = [
    "NET_LOSS_PER_LOSS",
    "NET_PROFIT_PER_WIN",
    "UNIT_RISK",
    "BettingStats",
    "compute_ats_stats",
    "compute_totals_stats",
    "grade_ats_pick",
    "grade_totals_pick",
    "summarize_betting_performance",
]
