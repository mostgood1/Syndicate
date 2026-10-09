"""The resumable game state for the basketball possession engine.

``simulate_pbp_game_boxscore(..., state=GameState(...))`` starts the possession
loop from a live game situation instead of 0-0 at the opening tip.

THE GUARANTEE THIS RESTS ON. ``GameState()`` (the default, the opening tip)
takes EXACTLY the pregame code path: the same RNG draws in the same order and
the same output, seed for seed. ``tests/test_basketball_engine_resume.py``
proves it. It is the same guarantee as the NHL precedent
(``syndicate/features/nhl/live_resim.py`` docstring :34-49): a resume at 0:00
must reproduce the pregame run, or a live re-sim cannot tell its own drift
from the game's.

WHAT A RESUMED RUN RETURNS. The player box lines and the per-quarter player
arrays are the REMAINDER only, the stats produced from the resume point on.
The caller adds the actuals. The team period points are FULL GAME: completed
periods come from the state, the current period is points-so-far plus the
simulated rest, and later periods are simulated. ``sum(home_q_pts) + sum(ot)``
is therefore a final score.

WHAT IS CONSUMED AND WHAT IS ONLY CARRIED (P1 is no behaviour change, so the
engine gains no new mechanism here):

  consumed  period, seconds_remaining, home/away_period_pts (score and margin
            feed the blowout, rotation-window and late-clock rules), possession
            (the first possession only; the loop alternates after that),
            home/away_on_floor (the first possession's lineup), and
            home/away_player_fouls at or above the league foul limit (a
            fouled-out player gets no further lineup weight).
  carried   home/away_team_fouls, home/away_in_bonus, and player fouls BELOW
            the limit. The loop has no bonus or foul-trouble mechanism to feed
            them into. Adding one is a MECHANISM and needs a re-fit (P3).
            ``scripts/basketball_sim_input_checklist.py`` reports these as
            carried and not consumed, so none of them can pass as a working
            feature.

A fouled-out player stays out only for fouls they already had at the resume
point. A player who reaches the limit inside the simulated remainder keeps
playing, which is today's pregame behaviour. Enforcing it in-sim is a P3
mechanism.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional, Tuple

from .league import LeagueParams


@dataclass(frozen=True)
class GameState:
    # 1-based. 1..regulation_periods is regulation; above that is overtime (5 = OT1 for quarters).
    period: int = 1
    # Seconds left in `period`. None = the whole period (the start of it).
    seconds_remaining: Optional[int] = None
    # Points per period so far, INCLUDING the current (partial) one. Length must be <= period.
    home_period_pts: Tuple[int, ...] = ()
    away_period_pts: Tuple[int, ...] = ()
    # "home" | "away" | None. None = unknown, so a coin flip, exactly as at the opening tip.
    possession: Optional[str] = None
    # Player names exactly as in the player frames' `player_name`. Empty = sample the lineup as usual.
    home_on_floor: Tuple[str, ...] = ()
    away_on_floor: Tuple[str, ...] = ()
    # Personal fouls by player name. Only counts >= the league foul limit are consumed (foul-out).
    home_player_fouls: Mapping[str, int] = field(default_factory=dict)
    away_player_fouls: Mapping[str, int] = field(default_factory=dict)
    # Current-period team fouls and bonus. CARRIED, not consumed (no bonus mechanism yet; P3).
    home_team_fouls: int = 0
    away_team_fouls: int = 0
    home_in_bonus: Optional[bool] = None
    away_in_bonus: Optional[bool] = None

    @property
    def home_score(self) -> int:
        return int(sum(int(x) for x in self.home_period_pts))

    @property
    def away_score(self) -> int:
        return int(sum(int(x) for x in self.away_period_pts))

    def is_opening_tip(self, league: LeagueParams) -> bool:
        """True when this state is indistinguishable from a pregame run."""
        return (
            int(self.period) == 1
            and (self.seconds_remaining is None or int(self.seconds_remaining) == int(league.regulation_period_seconds))
            and self.home_score == 0
            and self.away_score == 0
            and self.possession is None
            and not self.home_on_floor
            and not self.away_on_floor
            and not _fouled_out_names(self.home_player_fouls, league)
            and not _fouled_out_names(self.away_player_fouls, league)
        )

    def period_seconds(self, league: LeagueParams) -> int:
        return int(league.regulation_period_seconds if int(self.period) <= int(league.regulation_periods) else league.overtime_period_seconds)

    def validate(self, league: LeagueParams) -> None:
        """Refuse an impossible state instead of simulating from it. Raises ValueError, naming the field."""
        p = int(self.period)
        if p < 1:
            raise ValueError(f"GameState.period must be >= 1, got {p}")
        full = self.period_seconds(league)
        if self.seconds_remaining is not None and not (0 <= int(self.seconds_remaining) <= full):
            raise ValueError(f"GameState.seconds_remaining {self.seconds_remaining} outside [0, {full}] for period {p}")
        for side, pts in (("home", self.home_period_pts), ("away", self.away_period_pts)):
            if len(pts) > p:
                raise ValueError(f"GameState.{side}_period_pts has {len(pts)} periods but period is {p}")
            if any(int(x) < 0 for x in pts):
                raise ValueError(f"GameState.{side}_period_pts has a negative entry: {tuple(pts)}")
        if p > int(league.regulation_periods):
            # Overtime is only reached from a tie at the end of the previous period.
            n_prev = p - 1
            hp = list(self.home_period_pts) + [0] * (p - len(self.home_period_pts))
            ap = list(self.away_period_pts) + [0] * (p - len(self.away_period_pts))
            if sum(hp[:n_prev]) != sum(ap[:n_prev]):
                raise ValueError(f"GameState.period {p} is overtime but the score after period {n_prev} is not tied")
        if self.possession not in (None, "home", "away"):
            raise ValueError(f"GameState.possession must be 'home', 'away' or None, got {self.possession!r}")
        for side, names in (("home", self.home_on_floor), ("away", self.away_on_floor)):
            if names and len(set(names)) != 5:
                raise ValueError(f"GameState.{side}_on_floor must name 5 distinct players, got {tuple(names)}")


def _fouled_out_names(fouls: Mapping[str, int], league: LeagueParams) -> set[str]:
    limit = int(league.personal_foul_limit)
    return {str(name).strip() for name, n in (fouls or {}).items() if int(n or 0) >= limit}
