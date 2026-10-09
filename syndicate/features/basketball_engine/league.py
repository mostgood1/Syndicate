"""League parameters for the Syndicate basketball possession engine.

ONE engine (``engine.py``) serves every league. Everything that used to differ
between ``vendor/nba_betting_repo/.../sim/events.py`` and
``vendor/wnba_betting_repo/.../sim/events.py`` is a field here. Those were
module-level switches and the WNBA ``LEAGUE`` constant, and the two copies
disagreed by ~160 of 2,209 lines (lane basketball-native-engine, 2026-10-09).

The NBA and WNBA values reproduce the vendored engines EXACTLY: same RNG draws,
in the same order, and the same output. ``scripts/basketball_engine_parity.py``
gates that over a corpus of real production sim inputs. To change a value,
measure it first, then re-fit (model engine standard §4.4). P1 changed none of
them.

NCAAB values are HOOKS for plan phase P4: 2 x 20-minute halves, 30 s shot clock,
foul-out at 5 and the college bonus. The engine consumes the period geometry and
the foul limit. It does NOT yet consume the shot clock or the bonus, because the
loop has no shot-clock or bonus mechanism to feed. ``scripts/basketball_sim_input_checklist.py``
reports both fields as carried and not consumed, so neither can pass as a working
feature.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class LeagueParams:
    code: str

    # --- Geometry --------------------------------------------------------------------------------------------
    regulation_periods: int  # NBA/WNBA 4 quarters; NCAAB 2 halves
    regulation_period_seconds: int  # NBA 720, WNBA 600, NCAAB 1200
    overtime_period_seconds: int  # 300 in all three
    # 5 x regulation minutes. INERT, in the vendored engines too: _team_rates_from_priors assigns it to `total_min` when
    # no player has _sim_min, then never reads `total_min`. Carried so the port stays the vendored text; pinned inert
    # by tests/test_basketball_engine_parity.py.
    regulation_team_minutes: float
    shot_clock_seconds: int  # HOOK (P4): carried, no shot-clock mechanism in the loop yet
    personal_foul_limit: int  # foul-out; consumed only for players a resumed GameState says are already out
    team_fouls_for_bonus: int  # HOOK (P3/P4): carried, the loop has no bonus mechanism yet

    # --- Pace ------------------------------------------------------------------------------------------------
    default_possessions_per_game: float  # EventSimConfig() default when the caller passes no config
    min_rate_possessions: float  # floor on possessions when deriving per-possession rates from priors

    # --- Engine switches (were module globals in vendored events.py) -----------------------------------------
    shooter_ft_rate: bool
    fouled_miss_not_fga: bool
    exact_target_calibration: bool
    # None = read EventSimConfig.team_prior_stacks_on_target (default True), the NBA behaviour.
    # False = never stack the team prior on a points target, the WNBA module constant (ignores the config).
    team_prior_stacks_on_target: Optional[bool]
    tov_per_attempt: bool
    player_rebound_credit: bool
    oreb_player_credit: float
    dreb_player_credit: float
    block_mode: str  # "legacy" | "team_prior"
    league_blocks_per_missed_2pa: float
    block_rate_assumed_fg3_pct: float
    block_alloc_by_rate: bool
    block_alloc_floor_pm: float
    # NBA wraps the per-shooter FT multipliers in try/except (neutral 1.0 on error); WNBA lets the error propagate.
    ft_mult_errors_neutral: bool

    @property
    def half_start_periods(self) -> tuple[int, ...]:
        """Periods that open a half: (1, 3) for quarters, (1, 2) for halves."""
        n = int(self.regulation_periods)
        return (1, n // 2 + 1) if n >= 2 else (1,)

    @property
    def half_end_periods(self) -> tuple[int, ...]:
        """Periods that close a half: (2, 4) for quarters, (1, 2) for halves."""
        n = int(self.regulation_periods)
        return (n // 2, n) if n >= 2 else (n,)

    @property
    def second_half_first_period(self) -> int:
        return int(self.regulation_periods) // 2 + 1


NBA = LeagueParams(
    code="nba",
    regulation_periods=4,
    regulation_period_seconds=12 * 60,
    overtime_period_seconds=5 * 60,
    regulation_team_minutes=240.0,
    shot_clock_seconds=24,
    personal_foul_limit=6,
    team_fouls_for_bonus=5,
    default_possessions_per_game=98.0,
    min_rate_possessions=60.0,
    shooter_ft_rate=False,
    fouled_miss_not_fga=False,
    exact_target_calibration=False,
    team_prior_stacks_on_target=None,
    tov_per_attempt=False,
    player_rebound_credit=False,
    # NBA FIT window 2025-11-01..2026-02-28 regular season, 1,632 team-games of ESPN team boxes (Phase 2 #1d).
    oreb_player_credit=min(1.0, 0.2418 / 0.24),
    dreb_player_credit=0.6855 / 0.76,
    block_mode="legacy",
    league_blocks_per_missed_2pa=0.2065,
    block_rate_assumed_fg3_pct=0.3588,
    block_alloc_by_rate=False,
    block_alloc_floor_pm=0.002,
    ft_mult_errors_neutral=True,
)

WNBA = LeagueParams(
    code="wnba",
    regulation_periods=4,
    regulation_period_seconds=10 * 60,
    overtime_period_seconds=5 * 60,
    regulation_team_minutes=200.0,
    shot_clock_seconds=24,
    personal_foul_limit=6,
    team_fouls_for_bonus=5,
    default_possessions_per_game=79.5,  # vendored LEAGUE.baseline_pace
    min_rate_possessions=67.5,  # vendored LEAGUE.min_event_possessions
    shooter_ft_rate=True,
    fouled_miss_not_fga=True,
    exact_target_calibration=True,
    team_prior_stacks_on_target=False,
    tov_per_attempt=True,
    player_rebound_credit=True,
    # May-June 2026 WNBA box scores (142 games).
    oreb_player_credit=0.227 / 0.24,
    dreb_player_credit=0.663 / 0.76,
    block_mode="team_prior",
    league_blocks_per_missed_2pa=0.192,
    block_rate_assumed_fg3_pct=0.34,
    block_alloc_by_rate=True,
    block_alloc_floor_pm=0.002,
    ft_mult_errors_neutral=False,
)

# P4 HOOKS. The geometry is real. Every rate switch is the NBA default because no NCAAB fit exists yet. P4 owns
# the rates and the shot-clock and bonus mechanisms. Nothing in production runs NCAAB through this engine.
NCAAB = LeagueParams(
    code="ncaab",
    regulation_periods=2,
    regulation_period_seconds=20 * 60,
    overtime_period_seconds=5 * 60,
    regulation_team_minutes=200.0,
    shot_clock_seconds=30,
    personal_foul_limit=5,
    team_fouls_for_bonus=7,  # one-and-one at 7, double bonus at 10 (men's); carried only
    default_possessions_per_game=68.0,
    min_rate_possessions=55.0,
    shooter_ft_rate=False,
    fouled_miss_not_fga=False,
    exact_target_calibration=False,
    team_prior_stacks_on_target=None,
    tov_per_attempt=False,
    player_rebound_credit=False,
    oreb_player_credit=1.0,
    dreb_player_credit=1.0,
    block_mode="legacy",
    league_blocks_per_missed_2pa=0.2065,
    block_rate_assumed_fg3_pct=0.34,
    block_alloc_by_rate=False,
    block_alloc_floor_pm=0.002,
    ft_mult_errors_neutral=True,
)

_BY_CODE = {"nba": NBA, "wnba": WNBA, "ncaab": NCAAB}


def league_params(code: str | None) -> LeagueParams:
    """Params for a league code. An unknown code RAISES rather than falling back to NBA.

    The vendored path treated any non-"wnba" code as NBA. A silent NBA default is
    how NBA geometry reached WNBA sims (#478).
    """
    key = str(code or "").strip().lower()
    if key not in _BY_CODE:
        raise ValueError(f"unknown basketball league code {code!r}; expected one of {sorted(_BY_CODE)}")
    return _BY_CODE[key]
