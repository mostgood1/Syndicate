"""Aggregate finished-game truth records into a calibration :class:`TruthSnapshot`."""
from __future__ import annotations

from typing import List, Optional, Sequence

from .contracts import HistoricalGameRecord, TruthMetrics, TruthSnapshot


def _safe_div(num: float, den: float) -> float:
    return float(num) / float(den) if den else 0.0


def build_truth_snapshot(
    records: Sequence[HistoricalGameRecord],
    *,
    regular_only: bool = True,
    season: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> TruthSnapshot:
    """Aggregate settled game records into a truth baseline.

    ``regular_only`` (default) keeps only ``game_type == 2`` so the baseline reflects regular-season
    pace (playoff hockey is systematically lower-scoring/tighter). Excluded games are counted in the
    snapshot provenance for auditability. Raises ``ValueError`` on an empty eligible set — a truth
    baseline over zero games would be a silent lie, exactly the failure mode this layer prevents.
    """
    excluded = 0
    eligible: List[HistoricalGameRecord] = []
    for r in records:
        if regular_only and int(r.game_type) != 2:
            excluded += 1
            continue
        eligible.append(r)

    n = len(eligible)
    if n == 0:
        raise ValueError("build_truth_snapshot: no eligible games (need >=1 to form a baseline)")

    total_goals = sum(r.total_goals for r in eligible)
    home_goals = sum(r.home_goals for r in eligible)
    away_goals = sum(r.away_goals for r in eligible)
    total_sog = sum(r.home_sog + r.away_sog for r in eligible)
    pp_goals = sum(r.pp_goals_home + r.pp_goals_away for r in eligible)
    en_goals = sum(r.en_goals_home + r.en_goals_away for r in eligible)
    home_wins = sum(1 for r in eligible if r.home_win)
    ot_games = sum(1 for r in eligible if r.went_ot)
    so_games = sum(1 for r in eligible if r.went_shootout)

    # Per-period regulation scoring shape.
    per_period = [0, 0, 0]
    for r in eligible:
        for i, (h, a) in enumerate(r.regulation_period_goals):
            per_period[i] += h + a
    reg_period_total = sum(per_period) or 1
    period_share = tuple(_safe_div(p, reg_period_total) for p in per_period)  # type: ignore[assignment]

    metrics = TruthMetrics(
        goals_per_game=round(_safe_div(total_goals, n), 4),
        home_goals_per_game=round(_safe_div(home_goals, n), 4),
        away_goals_per_game=round(_safe_div(away_goals, n), 4),
        shots_per_game=round(_safe_div(total_sog, n), 4),
        shooting_pct=round(_safe_div(total_goals, total_sog), 4),
        period_goal_share=(round(period_share[0], 4), round(period_share[1], 4), round(period_share[2], 4)),
        pp_goal_share=round(_safe_div(pp_goals, total_goals), 4),
        empty_net_share=round(_safe_div(en_goals, total_goals), 4),
        home_win_pct=round(_safe_div(home_wins, n), 4),
        ot_rate=round(_safe_div(ot_games, n), 4),
        shootout_rate=round(_safe_div(so_games, n), 4),
    )

    seasons = sorted({r.season for r in eligible if r.season})
    dates = sorted({r.date[:10] for r in eligible if r.date})
    return TruthSnapshot(
        metrics=metrics,
        n_games=n,
        season=season or (seasons[0] if seasons else ""),
        date_from=date_from or (dates[0] if dates else ""),
        date_to=date_to or (dates[-1] if dates else ""),
        game_type=2 if regular_only else 0,
        excluded_games=excluded,
    )
