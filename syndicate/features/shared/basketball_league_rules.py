"""League rules for the native basketball engine, as data (NBA, WNBA, NCAAB men's).

Phase P4 of `docs/ai_context/basketball_live_native_plan.md`. P1 ports the
possession engine as ONE league-parametric engine; this module is the parameter
set it takes, written before the engine exists so that the NCAAB half of the
port has a contract to meet rather than a guess to make.

WHAT THE VENDORED ENGINE HARDCODES, and what each becomes here
(`vendor/nba_betting_repo/src/nba_betting/sim/events.py`, read 2026-10-09):

  * `for q in range(1, 5)` (:2059) and `base_poss = 2*poss / 4.0` (:1610)
    -> `LeagueRules.periods`, and `period_share()` for the possession split.
  * `quarter_seconds` / `ot_seconds` arguments -> `period_seconds`,
    `overtime_seconds`.
  * `_rotation_windows` (:179): quarter numbers (1, 3) / (2, 4) / 4 and
    absolute second thresholds -> `RotationWindow` rows per league. The NBA and
    WNBA rows reproduce the vendored function EXACTLY (both vendored copies are
    identical); `tests/test_basketball_league_rules.py` proves it on a full grid.
  * blowout checks `q >= 3` / `q >= 4` (:2104) -> `regulation_elapsed_fraction()`:
    in a two-half game "start of Q3" is 0.50 and "start of Q4" is 0.75, which is
    10:00 left in the second half and is NOT a period boundary. An engine that
    keeps testing period numbers would never enter its Q4 blowout state in NCAAB.
  * The vendored engine models NO team-foul bonus and NO foul-out at all (no
    team-foul counter exists in events.py). `bonus_free_throws()` and
    `foul_out` are the rulebook those mechanisms must use when P3 adds them; the
    college 1-and-1 is a different expected-points function, not a constant.

Rules (rulebook facts) and rotation windows (behavioural priors) are kept apart
on purpose: a rule is never re-fit; a window is an estimator and carries
`fitted` so nobody mistakes a prior for a measurement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Literal, Optional, Tuple

BonusAward = Literal["none", "one_and_one", "two_shots"]


@dataclass(frozen=True)
class RotationWindow:
    """One named game-situation window, as the engine's lineup sampler reads it.

    True when the period is in `periods` and every bound that is set holds.
    `elapsed_*` are seconds since the period started, `remaining_max` seconds
    left in it, `margin_max` the absolute score margin.
    """

    name: str
    periods: Tuple[int, ...]
    elapsed_min: Optional[int] = None
    elapsed_max: Optional[int] = None  # exclusive
    remaining_max: Optional[int] = None  # inclusive
    margin_max: Optional[int] = None  # inclusive

    def holds(self, period: int, elapsed: int, remaining: int, abs_margin: int) -> bool:
        if period not in self.periods:
            return False
        if self.elapsed_min is not None and elapsed < self.elapsed_min:
            return False
        if self.elapsed_max is not None and elapsed >= self.elapsed_max:
            return False
        if self.remaining_max is not None and remaining > self.remaining_max:
            return False
        if self.margin_max is not None and abs_margin > self.margin_max:
            return False
        return True


@dataclass(frozen=True)
class LeagueRules:
    league: str
    periods: int
    period_seconds: int
    overtime_seconds: int
    shot_clock_seconds: int
    shot_clock_after_offensive_rebound: int
    foul_out: int
    # Team-foul bonus. `bonus_scope` is what the team-foul count resets on:
    # "period" (NBA/WNBA quarters) or "half" (NCAAB; overtime CONTINUES the
    # second half's count). Thresholds are the opponent's team-foul number at
    # which the award starts (the 5th foul in an NBA quarter is two shots).
    bonus_scope: Literal["period", "half"]
    one_and_one_from: Optional[int]
    two_shots_from: int
    overtime_two_shots_from: Optional[int]
    # NBA/WNBA: in the last `late_period_seconds` of a period, the second team
    # foul in that window is two shots even below `two_shots_from`.
    late_period_seconds: Optional[int]
    late_period_two_shots_from: Optional[int]
    rotation_windows: Tuple[RotationWindow, ...] = field(default_factory=tuple)
    rotation_windows_fitted: bool = False
    source: str = ""

    # ------------------------------------------------------------ clock

    @property
    def regulation_seconds(self) -> int:
        return self.periods * self.period_seconds

    def is_overtime(self, period: int) -> bool:
        return int(period) > self.periods

    def seconds_in_period(self, period: int) -> int:
        return self.overtime_seconds if self.is_overtime(period) else self.period_seconds

    def period_share(self, period: int) -> float:
        """This period's share of a regulation game's possessions (the vendored `/4.0`)."""
        return float(self.seconds_in_period(period)) / float(self.regulation_seconds)

    def elapsed_seconds(self, period: int, remaining_in_period: float) -> float:
        """Game seconds elapsed at (period, clock). Overtime counts past regulation."""
        p = int(period)
        rem = max(0.0, float(remaining_in_period))
        if p <= self.periods:
            return (p - 1) * self.period_seconds + (self.period_seconds - rem)
        return self.regulation_seconds + (p - self.periods - 1) * self.overtime_seconds + (self.overtime_seconds - rem)

    def regulation_elapsed_fraction(self, period: int, remaining_in_period: float) -> float:
        """0.0 at the tip, 1.0 at the end of regulation, capped at 1.0 in overtime.

        Use this, never a period number, for any "second half / fourth quarter"
        game-state test: it is what makes one threshold mean the same game
        moment in a four-quarter and a two-half league.
        """
        return min(1.0, self.elapsed_seconds(period, remaining_in_period) / float(self.regulation_seconds))

    def remaining_regulation_seconds(self, period: int, remaining_in_period: float) -> float:
        return max(0.0, self.regulation_seconds - self.elapsed_seconds(period, remaining_in_period))

    # ------------------------------------------------------------ fouls

    def foul_count_resets(self, period: int) -> bool:
        """Does the team-foul count start at zero when `period` starts?"""
        p = int(period)
        if self.bonus_scope == "period":
            return True
        # half scope: only the second half resets; overtime continues it.
        return p <= self.periods

    def bonus_free_throws(
        self,
        team_fouls_in_scope: int,
        *,
        period: int,
        remaining_in_period: float,
        fouls_in_late_window: int = 0,
    ) -> BonusAward:
        """Award for a NON-shooting team foul, given the fouling team's count INCLUDING it.

        `fouls_in_late_window` is that team's fouls (including this one) in the
        last `late_period_seconds` of the period; NBA/WNBA only.
        """
        n = int(team_fouls_in_scope)
        two_from = self.two_shots_from
        if self.is_overtime(period) and self.overtime_two_shots_from is not None:
            two_from = self.overtime_two_shots_from
        if n >= two_from:
            return "two_shots"
        if (
            self.late_period_seconds is not None
            and self.late_period_two_shots_from is not None
            and float(remaining_in_period) <= self.late_period_seconds
            and int(fouls_in_late_window) >= self.late_period_two_shots_from
        ):
            return "two_shots"
        if self.one_and_one_from is not None and n >= self.one_and_one_from:
            return "one_and_one"
        return "none"

    def fouled_out(self, personal_fouls: int) -> bool:
        return int(personal_fouls) >= self.foul_out

    # ------------------------------------------------------------ rotation

    def rotation_window_flags(self, period: int, remaining_in_period: int, margin: int) -> Dict[str, bool]:
        """League-parametric `_rotation_windows`. Overtime sets no flag, as vendored."""
        p = int(period)
        rem = max(0, int(remaining_in_period))
        elapsed = max(0, int(self.seconds_in_period(p)) - rem)
        abs_margin = abs(int(margin))
        flags = {w.name: False for w in self.rotation_windows}
        if self.is_overtime(p) or p < 1:
            return flags
        for w in self.rotation_windows:
            if w.holds(p, elapsed, rem, abs_margin):
                flags[w.name] = True
        return flags


def expected_free_throw_points(award: BonusAward, ft_pct: float) -> float:
    """Expected points from a bonus award. A 1-and-1 is p + p^2, not 2p."""
    p = min(1.0, max(0.0, float(ft_pct)))
    if award == "two_shots":
        return 2.0 * p
    if award == "one_and_one":
        return p + p * p
    return 0.0


# The vendored windows, verbatim (events.py:179). Shared by NBA and WNBA
# because both vendored copies are identical -- including WNBA's use of the
# NBA's absolute-second thresholds inside a 600 s quarter. Reproducing that is
# the P1 parity requirement; whether it is RIGHT for WNBA is a P5 re-fit.
_PRO_WINDOWS: Tuple[RotationWindow, ...] = (
    RotationWindow("opening_stint", (1, 3), elapsed_max=180),
    RotationWindow("bench_stint", (2, 4), elapsed_max=180),
    RotationWindow("mid_wave", (1, 3), elapsed_min=180, elapsed_max=420),
    RotationWindow("closing_window", (2, 4), remaining_max=210, margin_max=10),
    RotationWindow("crunch_time", (4,), remaining_max=180, margin_max=8),
    RotationWindow("late_half_push", (2,), remaining_max=90, margin_max=12),
    RotationWindow("late_game_push", (4,), remaining_max=180, margin_max=14),
)

# NCAAB: two 20-minute halves with media timeouts at the first dead ball under
# 16:00 / 12:00 / 8:00 / 4:00. PRIORS, NOT FITS (`rotation_windows_fitted=False`):
# each half opens with the starters until the under-16 timeout (elapsed < 240),
# the bench wave runs between the under-16 and under-12 timeouts (240..480),
# then a mixed middle (480..840). Closing / crunch / push windows keep the
# vendored margins and remaining-time bounds, mapped onto the half that ends
# the game (2) and the half that ends the first half (1). The fit is owed from
# P2's `rotation_stints_history` (starter on-floor share by clock bucket).
_NCAAB_WINDOWS: Tuple[RotationWindow, ...] = (
    RotationWindow("opening_stint", (1, 2), elapsed_max=240),
    RotationWindow("bench_stint", (1, 2), elapsed_min=240, elapsed_max=480),
    RotationWindow("mid_wave", (1, 2), elapsed_min=480, elapsed_max=840),
    RotationWindow("closing_window", (1, 2), remaining_max=210, margin_max=10),
    RotationWindow("crunch_time", (2,), remaining_max=180, margin_max=8),
    RotationWindow("late_half_push", (1,), remaining_max=90, margin_max=12),
    RotationWindow("late_game_push", (2,), remaining_max=180, margin_max=14),
)

NBA = LeagueRules(
    league="nba",
    periods=4,
    period_seconds=720,
    overtime_seconds=300,
    shot_clock_seconds=24,
    shot_clock_after_offensive_rebound=14,
    foul_out=6,
    bonus_scope="period",
    one_and_one_from=None,
    two_shots_from=5,
    overtime_two_shots_from=4,
    late_period_seconds=120,
    late_period_two_shots_from=2,
    rotation_windows=_PRO_WINDOWS,
    rotation_windows_fitted=False,
    source="NBA rulebook (Rule 12B: 5th team foul per quarter, 4th in OT, 2nd in the last 2:00)",
)

WNBA = LeagueRules(
    league="wnba",
    periods=4,
    period_seconds=600,
    overtime_seconds=300,
    shot_clock_seconds=24,
    shot_clock_after_offensive_rebound=14,
    foul_out=6,
    bonus_scope="period",
    one_and_one_from=None,
    two_shots_from=5,
    overtime_two_shots_from=4,
    late_period_seconds=120,
    late_period_two_shots_from=2,
    rotation_windows=_PRO_WINDOWS,
    rotation_windows_fitted=False,
    source="WNBA rulebook (10-minute quarters; team-foul penalty as NBA)",
)

NCAAB = LeagueRules(
    league="ncaab",
    periods=2,
    period_seconds=1200,
    overtime_seconds=300,
    shot_clock_seconds=30,
    shot_clock_after_offensive_rebound=20,
    foul_out=5,
    bonus_scope="half",
    one_and_one_from=7,
    two_shots_from=10,
    overtime_two_shots_from=None,  # overtime continues the second half's count
    late_period_seconds=None,
    late_period_two_shots_from=None,
    rotation_windows=_NCAAB_WINDOWS,
    rotation_windows_fitted=False,
    source="NCAA men's rules 2025-26 (two 20:00 halves, 30 s / 20 s reset, 1-and-1 on the 7th team foul per half, double bonus on the 10th, foul out at 5)",
)

LEAGUES: Dict[str, LeagueRules] = {r.league: r for r in (NBA, WNBA, NCAAB)}


def rules_for(league: str) -> LeagueRules:
    """Rules by league slug. Unknown leagues raise: an engine must not run on a guessed rulebook."""
    key = str(league or "").strip().lower()
    if key not in LEAGUES:
        raise KeyError(f"no basketball league rules for {league!r}; known: {sorted(LEAGUES)}")
    return LEAGUES[key]
