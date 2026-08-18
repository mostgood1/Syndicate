"""Truth-layer contracts for the ``hockeysim`` calibration lane.

Mirrors football ``historical_truth`` (``HistoricalGameRecord`` / ``Metrics`` / ``Snapshot`` +
``to_calibration_snapshot``) and soccer's truth baseline. These frozen records are the boundary
between the raw NHL StatsWeb feed (``nhl_statsweb_loader``) and the aggregation
(``snapshot_builder``) that produces the numbers the Phase-3 evaluator scores the engine against.

The truth baseline answers "what does real NHL actually look like?" for the handful of quantities
the engine + projection profile are calibrated to: goals/game, the home-ice goal split, shots and
shooting %, the per-period scoring shape, power-play and empty-net goal share, and the
regulation/OT/shootout mix.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class HistoricalGameRecord:
    """One finished game's settled truth, parsed from a StatsWeb ``landing`` feed."""

    game_id: str
    date: str
    season: str
    game_type: int  # 2 = regular season, 3 = playoffs
    home_abbr: str
    away_abbr: str
    home_goals: int
    away_goals: int
    home_sog: int
    away_sog: int
    # Regulation+OT goals per period as (home, away); index 0 = P1 .. 2 = P3, 3+ = OT frames.
    period_goals: Tuple[Tuple[int, int], ...] = ()
    pp_goals_home: int = 0
    pp_goals_away: int = 0
    en_goals_home: int = 0
    en_goals_away: int = 0
    # Minor penalties (2-min, incl. double-minors) COMMITTED by each team -- i.e. the OPPONENT's
    # resulting power-play opportunities. Majors/misconducts are deliberately excluded: a fighting
    # major is typically offset by a simultaneous major on the other team and creates no power
    # play, and distinguishing an offsetting major from a standalone one needs same-timestamp
    # matching this parser does not attempt. This undercounts the rarer standalone-major PP case;
    # documented here rather than silently absorbed.
    penalties_committed_home: int = 0
    penalties_committed_away: int = 0
    went_ot: bool = False
    went_shootout: bool = False

    @property
    def total_goals(self) -> int:
        return int(self.home_goals) + int(self.away_goals)

    @property
    def home_win(self) -> bool:
        return int(self.home_goals) > int(self.away_goals)

    @property
    def regulation_period_goals(self) -> Tuple[Tuple[int, int], ...]:
        """Just the first three (regulation) period tuples, padded to 3 with zeros."""
        reg = list(self.period_goals[:3])
        while len(reg) < 3:
            reg.append((0, 0))
        return tuple(reg)


@dataclass(frozen=True)
class TruthMetrics:
    """Aggregate truth quantities the calibration profile is measured against."""

    goals_per_game: float
    home_goals_per_game: float
    away_goals_per_game: float
    shots_per_game: float
    shooting_pct: float
    period_goal_share: Tuple[float, float, float]  # P1, P2, P3 fraction of regulation goals
    pp_goal_share: float        # fraction of goals scored on the power play
    empty_net_share: float      # fraction of goals that were empty-net
    home_win_pct: float
    ot_rate: float              # fraction of games reaching overtime
    shootout_rate: float        # fraction of games decided in a shootout

    def to_dict(self) -> Dict[str, object]:
        d = asdict(self)
        d["period_goal_share"] = list(self.period_goal_share)
        return d


@dataclass(frozen=True)
class TruthSnapshot:
    """A truth baseline plus provenance for auditability."""

    metrics: TruthMetrics
    n_games: int
    season: str
    date_from: str
    date_to: str
    game_type: int = 2
    source: str = "nhl_statsweb_landing"
    excluded_games: int = 0

    def to_dict(self) -> Dict[str, object]:
        return {
            "provenance": {
                "n_games": self.n_games,
                "season": self.season,
                "date_from": self.date_from,
                "date_to": self.date_to,
                "game_type": self.game_type,
                "source": self.source,
                "excluded_games": self.excluded_games,
            },
            "metrics": self.metrics.to_dict(),
        }

    def to_calibration_snapshot(self) -> Dict[str, float]:
        """Flat metric->value mapping the Phase-3 evaluator/benchmark consumes.

        These keys are the calibration *targets*; the evaluator extracts the same-named metrics
        from a batch of engine sim outputs and scores the normalized error against them.
        """
        m = self.metrics
        return {
            "goals_per_game": m.goals_per_game,
            "home_goals_per_game": m.home_goals_per_game,
            "away_goals_per_game": m.away_goals_per_game,
            "shots_per_game": m.shots_per_game,
            "shooting_pct": m.shooting_pct,
            "period1_share": m.period_goal_share[0],
            "period2_share": m.period_goal_share[1],
            "period3_share": m.period_goal_share[2],
            "pp_goal_share": m.pp_goal_share,
            "empty_net_share": m.empty_net_share,
            "home_win_pct": m.home_win_pct,
            "ot_rate": m.ot_rate,
            "shootout_rate": m.shootout_rate,
        }
