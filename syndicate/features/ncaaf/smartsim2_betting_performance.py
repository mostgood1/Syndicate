"""Betting-performance grading for Enhanced Totals Engine / SmartSim 2.0 / Consensus.

Measures betting outcomes (ATS and totals, win %, ROI, units won/lost),
not forecast-accuracy statistics -- MAE/RMSE/correlation belong to
``smartsim2_performance_tracking.py``; this module answers "would betting on
this source's picks have made money against the real closing line," a
different (and, for a betting product, more decision-relevant) question.

Reads the same per-game records ``smartsim2_performance_tracking.py``
produces (``engine_margin``, ``smartsim_margin``, ``consensus_margin``,
``market_margin``, ``actual_margin`` and the totals equivalents, plus the
existing ``side_disagreement``/``total_disagreement``/``large_mismatch``/
``conference_game`` category flags) -- it does not recompute or duplicate
those fields, only grades bets from them. This module does not modify
SmartSim 2.0, the Enhanced Totals Engine, calibration profiles, blend
formulas, or the decision policy; it only grades bets against numbers those
systems already produced.

Odds assumption, stated plainly: real per-game ATS/totals prices (juice)
are not part of the market-lines data this project has collected (only the
point spread and total themselves, plus moneylines for the moneyline
market). Every graded bet here assumes the standard flat -110/-110 price on
both sides, which is the industry-standard assumption for this kind of
backtest when real bet-slip prices aren't available -- disclosed here
rather than presented as more precise than it is.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Literal
from typing import Sequence

from syndicate.features.ncaaf.smartsim2_performance_tracking import SOURCES

# Standard flat -110 both sides: risk 1.0 unit to win 100/110 units net.
UNIT_RISK = 1.0
NET_PROFIT_PER_WIN = 100.0 / 110.0
NET_LOSS_PER_LOSS = -1.0

PickGrade = Literal["win", "loss", "push", "no_pick"]

_MARGIN_FIELDS = {"engine": "engine_margin", "smartsim": "smartsim_margin", "consensus": "consensus_margin"}
_TOTAL_FIELDS = {"engine": "engine_total", "smartsim": "smartsim_total", "consensus": "consensus_total"}


def grade_ats_pick(source_margin: float, market_margin: float, actual_margin: float) -> PickGrade:
    """Grade one ATS bet: source picks the side it projects to beat the closing market margin."""
    if source_margin == market_margin:
        return "no_pick"
    picked_home = source_margin > market_margin
    if actual_margin == market_margin:
        return "push"
    home_covered = actual_margin > market_margin
    return "win" if picked_home == home_covered else "loss"


def grade_totals_pick(source_total: float, market_total: float, actual_total: float) -> PickGrade:
    """Grade one totals bet: source picks Over/Under relative to the closing market total."""
    if source_total == market_total:
        return "no_pick"
    picked_over = source_total > market_total
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


def compute_ats_stats(records: Sequence[dict[str, Any]], source: str) -> BettingStats | None:
    if not records:
        return None
    field = _MARGIN_FIELDS[source]
    grades = [
        grade_ats_pick(r[field], r["market_margin"], r["actual_margin"])
        for r in records
        if r.get("market_margin") is not None
    ]
    if not grades:
        return None
    return _summarize_grades(grades)


def compute_totals_stats(records: Sequence[dict[str, Any]], source: str) -> BettingStats | None:
    if not records:
        return None
    field = _TOTAL_FIELDS[source]
    grades = [
        grade_totals_pick(r[field], r["market_total"], r["actual_total"])
        for r in records
        if r.get("market_total") is not None
    ]
    if not grades:
        return None
    return _summarize_grades(grades)


def summarize_betting_performance(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """ATS and totals betting stats for all three sources, overall and by category."""

    def _segment(subset: Sequence[dict[str, Any]]) -> dict[str, Any]:
        return {
            "n": len(subset),
            "ats": {source: (s.to_dict() if (s := compute_ats_stats(subset, source)) else None) for source in SOURCES},
            "totals": {
                source: (s.to_dict() if (s := compute_totals_stats(subset, source)) else None) for source in SOURCES
            },
        }

    side_disagreement = [r for r in records if r["side_disagreement"]]
    total_disagreement = [r for r in records if r["total_disagreement"]]
    large_mismatch = [r for r in records if r["large_mismatch"]]
    conference_games = [r for r in records if r["conference_game"]]
    non_conference_games = [r for r in records if not r["conference_game"]]

    return {
        "n_games": len(records),
        "overall": _segment(records),
        "side_disagreement": _segment(side_disagreement),
        "total_disagreement": _segment(total_disagreement),
        "large_mismatch": _segment(large_mismatch),
        "conference_games": _segment(conference_games),
        "non_conference_games": _segment(non_conference_games),
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
