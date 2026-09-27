"""NCAAF LIVE RE-SIM: smartsim2 restarted from the current game state.

    live_state_from_espn_event(event)   -> NcaafLiveGameState | NcaafResimRefusal
    resim_live_game(state, ratings)     -> dict (the lens lane) | NcaafResimRefusal
    build_live_lens_snapshot(date_str)  -> the shared `gameLens` snapshot

--------------------------------------------------------------------------
WHY THIS EXISTS
--------------------------------------------------------------------------

Measured on production 2026-09-05, mid-slate: `/ncaaf/api/live-lens` served
**51 games, 7 live, 26 final, 18 pregame**, and every live card's win
probability, predicted final, spread and total was the PREGAME number. Boise
State led Oregon 7-0 in Q2 while the board read "Oregon 97.7%".

The board is right to suppress an edge on those rows (`#340`): a pregame model
priced against a re-priced market yields the score, not an edge -- measured
2026-07-12 as a +23-point "edge" on a coin-flip. **So the fix is never to stop
suppressing. It is to produce a probability that knows the score**, and to let
`live_edge_policy` release the edge on the strength of THAT.

--------------------------------------------------------------------------
THE ENGINE COULD ALWAYS DO THIS. ITS ENTRYPOINT COULD NOT.
--------------------------------------------------------------------------

`possession_state.build_initial_possession_state` has always taken `quarter`,
`clock_remaining`, `score_home` and `score_away`, and `drive_simulator` already
branches on `state.quarter` and `state.clock_remaining` for the two-minute
drill, end-of-half and end-of-game behaviour. `game_simulator.simulate_game`
simply never passed them: it hard-coded `quarter=1`,
`clock_remaining=quarter_seconds` and no score, and looped
`for quarter in range(1, quarters + 1)`.

MEASURED BEFORE ANY CODE WAS WRITTEN, running the drive loop directly from a
mid-game state (n=200 shared seeds, ratings held fixed):

    resumed at Q1 15:00, 0-0      p(home) 0.6000   == the pregame entrypoint
    resumed at Q2 15:00, away +7  p(home) 0.4250
    resumed at Q4 00:15, home +21 p(home) 1.0000
    resumed at Q4 00:15, home -21 p(home) 0.0000

The first line is the one that matters: resuming at kickoff is not an
approximation of the pregame sim, it IS the pregame sim. And the cost falls as
the game runs -- 154 ms/sim pregame, 85 ms at Q2, 7.9 ms at Q4 2:00, 0.7 ms at
Q4 0:15 -- so a live re-sim is always cheaper than the pregame sim it updates.

--------------------------------------------------------------------------
WHAT IS PUBLISHED, AND WHAT IS DELIBERATELY NOT
--------------------------------------------------------------------------

TWO MARKET FAMILIES: the moneyline and TOTALS. The lane carries
`modelHomeWinProb` and `simsRun`, which is exactly what
`live_gameline_join.price_moneyline` prices, and `prob_std_err` derives the
interval from `simsRun` the same way it does for MLB. Nothing here relaxes
`PRICEABLE_SIGMA`.

TOTALS BECAME PRICEABLE ON 2026-09-26 BY MEASUREMENT.
`scripts/backtest_ncaaf_live_totals.py` replays this module's own
`resim_live_game` from quarter boundaries in completed games -- the score is
exact and the clock is 0:00 there, so no play-by-play is needed -- and scores
its histogram against the real final total. Publishing was and remains right:
the distribution reaching the pricer took the board's withheld reason
`live_resim_published_no_distribution_for_this_market` from 112 to 7 and
priceable rows from 4 to 16, measured on production.

**THE CORRECTION THAT SHIPPED WITH IT WAS WRONG AND WAS WITHDRAWN THE SAME
NIGHT, and the reason is worth more than the fix.** The grade that produced
`shift +2.165` ran against SP+ ratings stamped `fetched_at 2026-09-05`,
`verified=False` -- 22 days stale. The harness printed that provenance on every
run; nobody read it. Re-run over the SAME dates with the ratings production
actually uses, on 546 Saturday rows / 182 games:

    uncorrected totals bias   +0.171   95% CI over games [-1.176, +1.538]
    worst bucket uncorrected  0.0556
    worst bucket AT +2.165    0.1558   <- the shipped correction made it WORSE

The -2.165 was a property of stale ratings, not of the simulator. So
`calibrate_total_distribution` is now IDENTITY, and `#499`'s 0.150 bar is
cleared by the UNCORRECTED estimator at 0.0556. A stale-input artifact is
indistinguishable from a model defect at every level except the input's own
provenance field -- which is why that field is now the first thing a grade
reports.

SPREADS FOLLOWED ON 2026-09-27, on their own grade, and their correction was
REFIT the same night for the same stale-ratings reason. `marginDist` was
deliberately withheld for one commit because the totals grade licensed totals
and nothing else. Publishing it opened live spreads. The constant, refit on the
SATURDAY population with fresh ratings (546 rows / 182 games):

    uncorrected       worst 0.0411   bias -0.387  CI over games [-1.644, +0.896]
    first shipped     worst 0.0869   bias +0.673  <- +1.06/1.30, too large
    refit +0.387/1.10 worst 0.0397   bias -0.000  <- then ZEROED as well

Saturday is the right population because NCAAF live games are overwhelmingly a
Saturday event, and day of week is EXOGENOUS -- a "dates with >= 20 games"
filter selects nearly the same rows by looking at the data, and silently drops
opening Saturday 2026-08-29. `calibrate_margin_distribution` holds it and,
unlike the totals one, does NOT clamp: a margin is signed and clamping would
delete every away-win draw.

THE MARGIN CORRECTION IS NOW IDENTITY TOO `[2026-09-27, user decision]`. Its
whole improvement was 0.0014 on the worst bucket over a bias whose CI spans
zero, and a constant fitted to a quantity that cannot be shown non-zero is the
same mistake as the stale-ratings one, just smaller. BOTH markets now price the
draws the simulator produced, and both clear `#499`'s 0.150 bar uncorrected
(totals 0.0556, margin 0.0411). The transform, the env overrides and the
signed/no-clamp frame are KEPT so a later honest refit has somewhere to land.

A CLAIM MADE EARLIER AND
RETRACTED: that the margin bias "drifts hard across the season" (-0.485 early
vs -1.631 late). It does not. That split was confounded by WHICH DATES fell in
each half -- 31 midweek games sat mostly in the early one -- and on well-powered
Saturdays the halves read -1.496 and -1.927. Restricted properly the difference
is mild and its interval spans zero.

COHERENCE: `home_win_prob` is counted from the RAW margins while `marginDist`
is corrected, a measured 0.12-1.87pp disagreement at the pivot. Far inside the
~9.13pp publish bar at 120 sims, so the two cannot print contradictory edges,
and a test fails if it ever widens.

**NO FALLBACK TO THE PREGAME PROBABILITY, EVER** (`#414`). The re-sim used to
ship a live mean beside a `modelProbOver` that was bit-identical to the pregame
value on 24 of 28 live rows, and pricing that produced `#340` wearing a live
label. Every path here that cannot produce a live probability returns an
`NcaafResimRefusal` with a named `reason`, and a refusal publishes a lane
stamped `pregame_only` -- which `LIVE_LENS_SOURCES_BY_SPORT["ncaaf"]` does not
accept, so the join withholds and says why. A refused game is never a game
priced off its pregame number.

--------------------------------------------------------------------------
RUNS ON A WORKER. NEVER IN A REQUEST HANDLER.
--------------------------------------------------------------------------

`build_live_lens_snapshot` is a simulation. It is called by
`live_lens_loop._run_live_lens_tick`, on the worker that owns the live-lens
loop, and it writes an artifact the web service reads. It carries
`refuse_if_compute_in_request_path` for the same reason MLB's live-lens
enhancement does. The join
(`board_enrichment.attach_live_gamelines_for_sport`) reads the PUBLISHED
snapshot and never calls anything in this module.
"""

from __future__ import annotations

import math
import os
import re
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from random import Random
from typing import Any, Mapping

from syndicate.features.football.sim_engine.smartsim2.contracts import (
    SmartSim2SimulationInput,
)
from syndicate.features.football.sim_engine.smartsim2.game_simulator import simulate_game
from syndicate.features.football.sim_engine.smartsim2.ncaaf_calibration_profile import (
    NCAAF_CALIBRATION_PROFILE,
)

__all__ = [
    "LIVE_RESIM_LENS_SOURCE",
    "NcaafLiveGameState",
    "NcaafResimRefusal",
    "build_live_lens_snapshot",
    "clock_to_seconds",
    "default_sims",
    "field_position_for_possessor",
    "live_state_from_espn_event",
    "live_lens_snapshot_path",
    "resim_live_game",
    "validate_live_lens_snapshot",
]

# THE STAMP THE JOIN ACCEPTS. It must be distinct from the `pregame` stamp this
# module also emits, and from every other sport's, because
# `live_gameline_from_lens` keys on `source` and NOT on the probability's
# presence -- the whole point of that rule is that a lane the re-sim never
# touched must not be mistaken for one it did.
LIVE_RESIM_LENS_SOURCE = "live_resim"
PREGAME_LENS_SOURCE = "pregame"

# 120 IS MLB'S NUMBER AND IT IS CHOSEN FOR THE SAME REASON. `prob_std_err` reads
# `sqrt(p(1-p)/n)`; at n=120, p=0.5 that is 4.56 pp, so `PRICEABLE_SIGMA = 2.0`
# sets a ~9.13 pp bar on a coin-flip game and a narrower one toward the tails.
# The honest lever on that bar is this number, not the threshold.
#
# It is also the cost lever, and the two pull the same way here: at ~85 ms/sim
# in the second quarter, 120 sims is ~10 s per live game. A 30-game Saturday
# window is ~5 minutes of worker CPU, which is why `LIVE_RESIM_BUDGET_SECONDS`
# exists below rather than being discovered as a tick overrun.
DEFAULT_SIMS = 120
DEFAULT_BUDGET_SECONDS = 90.0

# Regulation only. `simulate_game` resumes at `initial_quarter` and the OT block
# runs after the quarter loop, so an OT resume simulates the OT period rather
# than returning the tied score as final -- but NOTHING has graded NCAAF overtime
# against outcomes, and college OT (alternating possessions from the 25, no
# clock) is not what that block models. Refused by name rather than answered
# badly.
MAX_RESUMABLE_PERIOD = 4

_CLOCK_RE = re.compile(r"^\s*(\d{1,3}):(\d{2})\s*$")


@dataclass(frozen=True)
class NcaafResimRefusal:
    """Why this game carries no live probability. Never a probability."""

    reason: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"reason": self.reason, "detail": self.detail}


@dataclass(frozen=True)
class NcaafLiveGameState:
    """Everything smartsim2 needs to resume, and nothing it does not.

    `home_team`/`away_team` are the BOARD's team names, carried through from the
    same source `ncaaf/game_projections.py` joins on (`_norm` is a plain
    lowercase there and the pregame join matches 327 of 692 rows on it, its
    FBS-vs-FBS boundary explaining the rest). They are NOT ESPN's names: the
    NCAAF board's abbreviations and ESPN's disagree on 10 of 10 comparable games
    (`ncaaf/live_game_state.py`), and a name-based join here would import that.
    """

    away_team: str
    home_team: str
    period: int
    clock_seconds: int
    home_score: int
    away_score: int
    down: int = 1
    distance: int = 10
    # `field_position` is in SMARTSIM2's frame: yards from the POSSESSING team's
    # own goal line, 1..99. ESPN's `yardLine` is in the HOME team's frame; see
    # `field_position_for_possessor`.
    field_position: int = 25
    # None means ESPN did not say. It is NOT defaulted to a side -- see
    # `resim_live_game`, which marginalises over both rather than picking one.
    possession_owner: str | None = None
    as_of: str = ""

    @property
    def home_margin(self) -> int:
        return self.home_score - self.away_score


def default_sims() -> int:
    raw = str(os.environ.get("NCAAF_LIVE_RESIM_SIMS") or "").strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_SIMS
    return value if value > 0 else DEFAULT_SIMS


def default_budget_seconds() -> float:
    raw = str(os.environ.get("NCAAF_LIVE_RESIM_BUDGET_SECONDS") or "").strip()
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_BUDGET_SECONDS
    return value if value > 0 else DEFAULT_BUDGET_SECONDS


def clock_to_seconds(value: Any) -> int | None:
    """`"13:20"` -> 800. None when it is not a clock.

    ESPN blanks or zeroes the clock between quarters and shows `0:00` at a
    quarter's end. `0` is a legitimate value and must NOT be conflated with
    "unparseable": resuming at `Q1 0:00` means the quarter loop advances
    immediately to Q2 with a full clock, which is exactly right. Returning None
    for it would refuse every game at every quarter break.
    """
    match = _CLOCK_RE.match(str(value or ""))
    if not match:
        return None
    minutes, seconds = int(match.group(1)), int(match.group(2))
    if seconds >= 60:
        return None
    return minutes * 60 + seconds


def field_position_for_possessor(yard_line: Any, *, possessor_is_home: bool) -> int | None:
    """ESPN's `yardLine` -> smartsim2's `field_position`.

    MEASURED against the 2026-09-05 live slate, 11 games carrying both
    `yardLine` and `downDistanceText`:

        home possessing  "1st & 10 at TEX 39" yardLine 39   -> own 39
        away possessing  "1st & 10 at BAY 25" yardLine 75   -> own 25
        away possessing  "4th & 5  at BOIS 3" yardLine 97   -> own 3

    So ESPN measures from the HOME team's goal line, in a fixed frame, and
    smartsim2 measures from the POSSESSING team's own goal line. The transform
    is an inversion for the away side and identity for the home side. Getting
    this backwards would place a team at its opponent's 3 instead of its own --
    a swing of nearly the whole field, on a state the sim then treats as
    authoritative.
    """
    try:
        value = int(yard_line)
    except (TypeError, ValueError):
        return None
    if not 0 <= value <= 100:
        return None
    own = value if possessor_is_home else 100 - value
    return max(1, min(99, own))


def live_state_from_espn_event(
    state: Mapping[str, Any],
    *,
    away_team: str,
    home_team: str,
) -> NcaafLiveGameState | NcaafResimRefusal:
    """A resumable state from one row of `ncaaf/live_game_state`'s index.

    Takes the ALREADY-PARSED row (`in_progress`, `final`, `period`, `clock`,
    `home_score`, `away_score`, plus the raw `situation` when present) rather
    than the ESPN event, so this module cannot drift from
    `scripts/poll_ncaaf_live_state._game_from_event` on what "in progress"
    means. That module's docstring warns against a third parser and this is not
    one.
    """
    if bool(state.get("final")):
        return NcaafResimRefusal("game_final", "the market is settled; there is no price to beat")
    if not bool(state.get("in_progress")):
        return NcaafResimRefusal("game_not_in_progress", "kickoff has not happened")

    period = state.get("period")
    try:
        period_int = int(period)
    except (TypeError, ValueError):
        period_int = 0
    if period_int <= 0:
        # SEEN IN PRODUCTION, and it is not a parse bug. On 2026-09-05 three
        # ESPN events read `state=in` with `period: 0` and no `situation` at
        # all -- the window between "the broadcast has started" and the opening
        # kickoff. There is no game state to resume from, and the pregame
        # projection is still the correct answer for those minutes.
        return NcaafResimRefusal("no_period", "ESPN reports the game in progress with no period")
    if period_int > MAX_RESUMABLE_PERIOD:
        return NcaafResimRefusal(
            "overtime_not_modelled",
            f"period {period_int}: college overtime has never been graded by this engine",
        )

    clock_seconds = clock_to_seconds(state.get("clock"))
    if clock_seconds is None:
        return NcaafResimRefusal("no_clock", f"unparseable clock {state.get('clock')!r}")

    home_score = state.get("home_score")
    away_score = state.get("away_score")
    if home_score is None or away_score is None:
        return NcaafResimRefusal("no_score", "ESPN carries no score for a game it says is live")

    situation = state.get("situation") if isinstance(state.get("situation"), Mapping) else {}
    possession_owner = state.get("possession_owner")
    possession_owner = str(possession_owner).strip().lower() if possession_owner else None
    if possession_owner not in ("home", "away"):
        possession_owner = None

    down = _positive_int(situation.get("down"), default=1, hi=4)
    distance = _positive_int(situation.get("distance"), default=10, hi=99)
    field_position = 25
    if possession_owner is not None:
        derived = field_position_for_possessor(
            situation.get("yardLine"), possessor_is_home=possession_owner == "home"
        )
        if derived is not None:
            field_position = derived

    return NcaafLiveGameState(
        away_team=str(away_team or "").strip(),
        home_team=str(home_team or "").strip(),
        period=period_int,
        clock_seconds=clock_seconds,
        home_score=int(home_score),
        away_score=int(away_score),
        down=down,
        distance=distance,
        field_position=field_position,
        possession_owner=possession_owner,
        as_of=str(state.get("as_of") or datetime.now(timezone.utc).isoformat()),
    )


def _positive_int(value: Any, *, default: int, hi: int) -> int:
    """ESPN sends `-1` for down and distance during a kickoff or a change.

    Two of the fourteen games carrying a `situation` on 2026-09-05 read
    `down: -1, distance: -1`, which `build_initial_possession_state` would clamp
    to `down=1, distance=1` -- a 1st-and-1, which is not a football state. The
    default is the correct reading for "between plays": a fresh set of downs.
    """
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    if parsed < 1 or parsed > hi:
        return default
    return parsed


# LIVE TOTALS CALIBRATION, measured 2026-09-26 and applied to TOTALS ONLY.
#
# The cutoff-replay grade (`scripts/backtest_ncaaf_live_totals.py`) run on
# production ratings over 187 completed games / 561 cutoff rows found the live
# totals estimator wrong in TWO independent ways:
#
#     location    projected - actual = -2.165 points   (the sim runs LOW)
#     dispersion  sim SD 8.45 vs residual SD 10.73     (too NARROW, ratio 0.79)
#
# Either alone leaves most of the miss: on identical draws the worst
# predicted-probability bucket went 0.1463 -> 0.0790 (shift only) -> 0.0837
# (spread only) -> 0.0492 (both). CLAUDE.md warns that two mechanisms added
# together can interact NEGATIVELY (measured: 4 of 4 markets); here they are
# COMPLEMENTARY, and that was checked rather than assumed.
#
# VALIDATED OUT OF SAMPLE, because the constants were fitted on the same games
# they were then scored against, which flatters by construction. Refitting on
# the EARLIER 101 games only and scoring the LATER 86 it had never seen:
# worst bucket 0.1797 -> 0.0646, i.e. better out of sample than in. The shipped
# constants are then refitted on the FULL sample, which is the standard order:
# validate the method out of sample, estimate the parameter on everything.
#
# RESIDUAL, NOT CLAIMED AS FIXED: the out-of-sample bias only fell from -2.96 to
# -1.32, because the true bias DRIFTS between windows and this is a constant.
# It should be refitted as the season accumulates.
#
# THE MARGIN IS CORRECTED TOO, ON ITS OWN GRADE (2026-09-27), and the paragraph
# that used to sit here saying it was not is kept in spirit: the correction only
# became legitimate once `--market margin` produced a number. See
# `calibrate_margin_distribution` below for that grade and for how much weaker
# its evidence is than this one's.
# ---------------------------------------------------------------------------
# THE TOTALS CORRECTION IS WITHDRAWN (2026-09-27, hours after it shipped). It
# was fitted on STALE SP+ RATINGS and it made production WORSE.
# ---------------------------------------------------------------------------
#
# The grade that produced `shift +2.165` ran against a `sp_ratings_2026.json`
# whose `fetched_at` was 2026-09-05 -- 22 days old, `verified=False`. The
# harness printed that provenance on every run and it was not read. Re-run over
# the SAME dates with the ratings production actually uses (fetched
# 2026-09-27T01:10Z, `verified=True`), on 546 Saturday rows / 182 games:
#
#     uncorrected totals bias   +0.171   95% CI over games [-1.176, +1.538]
#     worst bucket uncorrected  0.0556
#     worst bucket AT +2.165    0.1558   <- the shipped correction, nearly the
#                                          `#499` bar, bias pushed to +2.336
#
# So the -2.165 that justified the correction was an artifact of stale ratings,
# not a property of the simulator. With fresh ratings the bias cannot be
# distinguished from zero, and the Saturday-weighted fit is -0.171 -- which in
# an INTEGER histogram rounds away entirely, so shipping it would be false
# precision dressed as a correction. Identity it is.
#
# WHAT THIS DOES NOT UNDO: publishing `totalRunsDist` was still right. The
# distribution reaching the pricer is what took the withheld reason from 112 to
# 7; only the transform applied to it was wrong.
def _live_total_bias_points() -> float:
    raw = str(os.environ.get("NCAAF_LIVE_TOTAL_BIAS_POINTS") or "").strip()
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _live_total_spread_scale() -> float:
    raw = str(os.environ.get("NCAAF_LIVE_TOTAL_SPREAD_SCALE") or "").strip()
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 1.0
    return value if value > 0 else 1.0


def calibrate_total_distribution(totals: list[int]) -> tuple[float, dict[str, int]]:
    """`(corrected_mean, corrected_histogram)` for rest-of-game totals.

    `corrected = mu + shift + (draw - mu) * spread`. The histogram keys are
    rounded back to whole points because a total IS a whole number of points;
    rounding after the transform keeps the support on the real lattice rather
    than inventing fractional totals the game cannot produce.
    """
    if not totals:
        return 0.0, {}
    shift = _live_total_bias_points()
    spread = _live_total_spread_scale()
    mu = sum(totals) / len(totals)
    out: dict[str, int] = {}
    moved_sum = 0.0
    for value in totals:
        moved = mu + shift + (value - mu) * spread
        moved = max(0.0, moved)  # a total cannot be negative
        key = str(int(round(moved)))
        out[key] = out.get(key, 0) + 1
        moved_sum += moved
    return moved_sum / len(totals), out


# --------------------------------------------------------------------------
# THE MARGIN CORRECTION. Weaker evidence than the totals one above, stated here
# rather than in a commit message, because the next reader decides whether to
# trust a spread price on it.
# --------------------------------------------------------------------------
#
# GRADED 2026-09-27 by the same cutoff-replay harness, `--market margin`, over
# 570 rows / 190 completed games at production's 120 sims and production's SP+
# ratings. Uncorrected: worst predicted-probability bucket 0.0954, signed bias
# -1.058 points, and realised exceeding predicted in 9 of 10 buckets -- the
# same one-way signature that got the FIRST totals grade refused at 0.1499.
# Corrected (shift +1.06, spread 1.30): worst bucket 0.0448, bias +0.002,
# direction balanced at 5 of 10. All ten buckets powered, n 252-957.
#
# TWO HARNESS DEFECTS WERE FOUND AND FIXED BEFORE THIS NUMBER MEANT ANYTHING,
# and both produced a healthy-looking reading first:
#   1. A FIXED line ladder (-10.5..+10.5) put 3,988 of 3,990 cells in the
#      0.9-1.0 bucket and reported a worst gap of 0.0004. Totals cluster and
#      margins do not -- each game has its own centre.
#   2. Anchoring the ladder on the DISTRIBUTION'S OWN MEDIAN fixed the spread of
#      predictions and was structurally blind to location: a shift moves the
#      distribution and the anchor together, so the calibration was invariant to
#      the very bias it was added to measure (0.1036 -> 0.1036, identical to
#      four decimals). The anchor is now the FROZEN MARGIN -- the score already
#      on the board -- which is observed, not modelled.
#
# HOW THIS IS WEAKER THAN THE TOTALS CORRECTION, and it is not a footnote.
# Out of sample on a game-balanced split (95 games fitted, 95 unseen), the test
# half improved 0.1320 -> 0.1105. It generalises, and 0.1105 still clears
# `#499`'s 0.150 bar -- but totals reached 0.0646 on the same test, and the
# margin's residual out-of-sample bias is -1.381 points against the totals'
# -1.32 on a much larger correction. The reason is that THE MARGIN BIAS DRIFTS
# HARD ACROSS THE SEASON: -0.485 over the earlier half, -1.631 over the later.
# A single constant cannot track that, so it UNDERCORRECTS recent games. Refit
# as the season accumulates; do not read 0.0448 as the live number.
# REFIT 2026-09-27 ON THE SATURDAY POPULATION WITH FRESH RATINGS. The first
# constants (+1.06 / 1.30) came from the same stale-ratings sample as the totals
# ones and were likewise too large: on 546 Saturday rows / 182 games they took
# the worst bucket from 0.0411 UP to 0.0869 and pushed the bias from -0.387 to
# +0.673. Saturday-weighted is the right population because NCAAF live games are
# overwhelmingly a Saturday event, and the day of week is exogenous -- a
# "dates with >= 20 games" filter picks nearly the same rows but is chosen by
# looking at the data, and it silently drops opening Saturday 2026-08-29.
#
#     uncorrected       worst 0.0411   bias -0.387  CI over games [-1.644, +0.896]
#     refit +0.387/1.10 worst 0.0397   bias -0.000
#
# AND THEN IT WAS ZEROED TOO `[2026-09-27, user decision]`, which the numbers
# above already argued for: the entire improvement is **0.0014** on the worst
# bucket, and the bias it corrects has a CI that SPANS ZERO. Fitting a constant
# to a quantity you cannot show is non-zero is how the stale-ratings mistake
# happened one commit earlier -- it dresses sampling noise as a mechanism, and
# then every later reading has to be interpreted through it.
#
# SO BOTH CALIBRATORS ARE NOW IDENTITY and the board prices the draws the
# simulator produced. `#499`'s 0.150 bar is cleared UNCORRECTED in both markets
# (totals 0.0556, margin 0.0411).
#
# THE MECHANISM IS KEPT ON PURPOSE. These two functions, their env overrides and
# the transform in `calibrate_margin_distribution` stay exactly where they are,
# because the next honest refit -- on a larger sample, with provenance read --
# needs somewhere to land, and re-deriving the signed/no-clamp frame from scratch
# is how that gets done wrongly. Identity is a VALUE here, not a missing feature.
def _live_margin_bias_points() -> float:
    raw = str(os.environ.get("NCAAF_LIVE_MARGIN_BIAS_POINTS") or "").strip()
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _live_margin_spread_scale() -> float:
    raw = str(os.environ.get("NCAAF_LIVE_MARGIN_SPREAD_SCALE") or "").strip()
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 1.0
    return value if value > 0 else 1.0


def calibrate_margin_distribution(margins: list[int]) -> tuple[float, dict[str, int]]:
    """`(corrected_mean, corrected_histogram)` for rest-of-game home margins.

    Same transform as the totals calibrator -- `mu + shift + (draw - mu) * spread`
    -- with one deliberate difference: THERE IS NO CLAMP. A total cannot be
    negative and is clamped at zero; a home margin is signed, and clamping it
    would silently delete every away-win draw and turn a close game into a
    guaranteed home cover. The frame stays HOME-POSITIVE, matching
    `run_margin_dist` and what `price_distribution_market` expects.
    """
    if not margins:
        return 0.0, {}
    shift = _live_margin_bias_points()
    spread = _live_margin_spread_scale()
    mu = sum(margins) / len(margins)
    out: dict[str, int] = {}
    moved_sum = 0.0
    for value in margins:
        moved = mu + shift + (value - mu) * spread
        key = str(int(round(moved)))
        out[key] = out.get(key, 0) + 1
        moved_sum += moved
    return moved_sum / len(margins), out


def resim_live_game(
    state: NcaafLiveGameState,
    *,
    home_offense: float,
    home_defense: float,
    away_offense: float,
    away_defense: float,
    sims: int | None = None,
    profile: Any = NCAAF_CALIBRATION_PROFILE,
) -> dict[str, Any] | NcaafResimRefusal:
    """Rest-of-game Monte Carlo from `state`. Returns the lens lane's payload.

    THE PROBABILITY IS THE EMPIRICAL SHARE OF SIMULATED REST-OF-GAMES the home
    team finishes ahead in, given what is already on the scoreboard -- not a
    transform of the pregame number, and not a logistic on the margin. An
    already-decided game falls out as exactly 1.0 or 0.0 the way `#414`'s prop
    re-sim does, because that is what the simulations say.

    POSSESSION, WHEN ESPN DOES NOT SAY, IS MARGINALISED AND NOT ASSUMED. Three
    of the seventeen in-progress games on 2026-09-05 carried no `possession`,
    and picking a side would be a silent substitution worth roughly a
    possession of field position on a close game. Half the seeds are run with
    each side in possession at its own 25, 1st and 10, and the lane is stamped
    `possessionUnknown` so a consumer can see that the estimate is an average
    over the two.
    """
    n = int(sims or default_sims())
    if n <= 0:
        return NcaafResimRefusal("no_sims_requested", f"sims={n}")

    base = dict(
        home_team=state.home_team or "HOME",
        away_team=state.away_team or "AWAY",
        home_offense_rating=float(home_offense),
        home_defense_rating=float(home_defense),
        away_offense_rating=float(away_offense),
        away_defense_rating=float(away_defense),
        initial_quarter=state.period,
        initial_clock_seconds=state.clock_seconds,
        initial_score_home=state.home_score,
        initial_score_away=state.away_score,
        initial_down=state.down,
        initial_distance=state.distance,
    )

    possession_unknown = state.possession_owner is None
    if possession_unknown:
        plans = [("home", 25), ("away", 25)]
    else:
        plans = [(state.possession_owner, state.field_position)]

    home_wins = 0
    ties = 0
    margins: list[int] = []
    totals: list[int] = []
    per_plan = max(1, n // len(plans))
    ran = 0
    for owner, field_position in plans:
        for seed in range(1, per_plan + 1):
            sim_input = SmartSim2SimulationInput(
                seed=seed,
                initial_possession_owner=owner,
                initial_field_position=field_position,
                **base,
            )
            out = simulate_game(sim_input, profile=profile)
            home_points = int(out.final_score["home"])
            away_points = int(out.final_score["away"])
            margins.append(home_points - away_points)
            totals.append(home_points + away_points)
            ran += 1
            if home_points > away_points:
                home_wins += 1
            elif home_points == away_points:
                ties += 1

    if ran <= 0:  # pragma: no cover - guarded by the n<=0 check above
        return NcaafResimRefusal("no_sims_run", "the simulation loop produced no results")

    # A TIE COUNTS AS HALF A WIN, not as a loss. `_final_win_probability` already
    # says 0.5/0.5 on a tie, and the engine's overtime cap of two rounds means a
    # small share of simulated games end level. Treating those as losses would
    # bias every probability downward by that share.
    home_win_prob = (home_wins + 0.5 * ties) / ran

    # THE DRAWS, KEPT RATHER THAN DISCARDED -- AND STILL NOT PUBLISHED.
    #
    # These histograms are what a pricer would need for totals and spreads, and
    # the module docstring is explicit that NCAAF must not price them until a
    # live estimator has been GRADED (`#499`: WNBA totals waited for a 249-game
    # / 23,712-sample backtest). Nothing here changes that: `build_game_lens`
    # constructs its lane field by field and does NOT forward this dict, so a
    # key added here reaches no lens and no pricer. Turning pricing on is a
    # deliberate edit to that literal, made on the strength of a grade.
    #
    # What they unblock is the GRADE ITSELF. A cutoff-replay harness has to
    # score the SHIPPED function; re-implementing the loop would measure
    # something production does not run, which is the same error as scoring
    # against ratings production never used.
    # BOTH FAMILIES ARE CALIBRATED, each on its own grade. `total_mean` and
    # `home_margin_mean` below are the CORRECTED means, so the board's displayed
    # live total stops running ~2.2 points low and its displayed live margin
    # stops running ~1.06 points against the home side. The uncalibrated means
    # ride alongside so a reader can always recover what the sim actually drew.
    calibrated_total_mean, total_dist = calibrate_total_distribution(totals)
    calibrated_margin_mean, margin_dist = calibrate_margin_distribution(margins)

    return {
        "home_win_prob": round(home_win_prob, 6),
        "sims_run": ran,
        "home_margin_mean": round(calibrated_margin_mean, 3),
        "home_margin_mean_uncalibrated": round(sum(margins) / ran, 3),
        "total_mean": round(calibrated_total_mean, 3),
        "total_mean_uncalibrated": round(sum(totals) / ran, 3),
        "possession_unknown": possession_unknown,
        "ties": ties,
        # Same shape as the pregame sidecar's `margin_dist` / `total_points_dist`
        # (home-positive margin), so a reader that already understands one
        # understands the other.
        "margin_dist": margin_dist,
        "total_dist": total_dist,
    }


def build_game_lens(
    state: NcaafLiveGameState | None,
    result: dict[str, Any] | NcaafResimRefusal,
    *,
    live_state_as_of: str = "",
) -> list[dict[str, Any]]:
    """The `gameLens` list for one game: exactly one lane, honestly stamped.

    A REFUSAL PUBLISHES A LANE. It would be simpler to publish nothing, and it
    would be worse: an absent lane is indistinguishable from a producer that
    never ran, which is the reading that cost WNBA a week
    (`build_live_gameline_index`'s `sources_seen` exists for exactly this). The
    refused lane is stamped `pregame`, which `LIVE_LENS_SOURCES_BY_SPORT` does
    not accept for ncaaf, so the join withholds the edge AND the diagnostic can
    see the reason.

    THE REFUSED LANE CARRIES NO `modelHomeWinProb`. Not the pregame one, not a
    zero, not a null that a downstream `or` could turn into a number. `#414`.
    """
    if isinstance(result, NcaafResimRefusal):
        return [{
            "key": "live",
            "label": "Live",
            "source": PREGAME_LENS_SOURCE,
            "closed": result.reason == "game_final",
            "liveResimRefusal": result.reason,
            "liveResimRefusalDetail": result.detail,
            "liveStateAsOf": live_state_as_of,
        }]

    assert state is not None  # a result implies a state
    return [{
        "key": "live",
        "label": "Live",
        "source": LIVE_RESIM_LENS_SOURCE,
        "closed": False,
        "modelHomeWinProb": result["home_win_prob"],
        "simsRun": result["sims_run"],
        "liveStateAsOf": live_state_as_of or state.as_of,
        "possessionUnknown": bool(result.get("possession_unknown")),
        # `totalRunsDist` OPENS TOTALS PRICING, and it is published because the
        # estimator behind it has now been GRADED -- not because the gate was
        # inconvenient. 561 cutoff-replay rows over 187 completed games at
        # production's own 120 sims and production's own SP+ ratings:
        # worst predicted-probability bucket 0.0492 after the location
        # correction, every bucket gap <= 0.049, MAE 8.282 against a frozen
        # baseline's 27.046, and the correction re-validated out of sample
        # (fit on the earlier 101 games, scored on the later 86: 0.1797 ->
        # 0.0646). That is `#499`'s WNBA precedent met and beaten -- its
        # measured worst bucket was 0.150.
        #
        # THE HISTOGRAM PUBLISHED HERE IS THE CALIBRATED ONE. `resim_live_game`
        # returns `total_dist` already shifted and scaled by
        # `calibrate_total_distribution`, so the board prices the same numbers
        # the grade scored. Publishing the raw draws beside a corrected
        # `total` would have the display and the price disagree.
        #
        # `marginDist` IS STILL WITHHELD, and the asymmetry is the point: the
        # grade measured TOTALS. Carrying `marginDist` would open SPREAD
        # pricing on an estimator that has never been scored and that
        # `calibrate_total_distribution` deliberately does not correct. Its own
        # grade is the precondition, exactly as this one was.
        #
        # `projection.total` / `projection.homeMargin` remain display fields;
        # the join prices neither.
        "projection": {
            "homeMargin": result["home_margin_mean"],
            "total": result["total_mean"],
            "totalRunsDist": result.get("total_dist") or {},
            "marginDist": result.get("margin_dist") or {},
            "homeScore": state.home_score,
            "awayScore": state.away_score,
            "period": state.period,
            "clockSeconds": state.clock_seconds,
        },
    }]


def possession_side_from_espn(competition: Any, *, home_id: Any, away_id: Any) -> tuple[str | None, dict[str, Any]]:
    """The possessing SIDE and the raw situation fields, from an ESPN competition.

    NOT A THIRD STATE PARSER. `scripts/poll_ncaaf_live_state._game_from_event`
    owns what "in progress" and "final" mean and this does not touch either;
    `ncaaf/live_game_state.py` adds the team ids and the clock the board needs.
    This adds only the down/distance/field-position block, which neither of
    those has any use for, read off the same `competitions[0]` mapping so it
    cannot disagree with the state beside it.

    ESPN names the possessing TEAM by id (`situation.possession = "68"`), not by
    side, so the side is resolved against the competitors already parsed. On
    2026-09-05, 11 of 17 in-progress games carried `possession`; the rest are
    reported as unknown and marginalised rather than guessed.
    """
    if not isinstance(competition, Mapping):
        return None, {}
    situation = competition.get("situation")
    if not isinstance(situation, Mapping):
        return None, {}
    holder = str(situation.get("possession") or "").strip()
    side: str | None = None
    if holder:
        if holder == str(home_id or "").strip():
            side = "home"
        elif holder == str(away_id or "").strip():
            side = "away"
    return side, dict(situation)


def build_live_lens_snapshot(
    date_str: str,
    *,
    games: Any,
    live_index: Mapping[str, Mapping[str, Any]],
    ratings: Mapping[str, tuple[float, float]],
    sims: int | None = None,
    budget_seconds: float | None = None,
    now: Any = None,
) -> dict[str, Any]:
    """The published snapshot: one entry per game, one lens lane per entry.

    INPUTS ARE INJECTED, and that is deliberate rather than lazy. Each of the
    three has a different owner and a different failure mode -- the week's games
    come from the smartsim2 projections artifact, the live state from ESPN, the
    ratings from the SP+ cache -- and a function that reached out for all three
    itself could not be tested without all three, which is how a producer ships
    inert. The caller that assembles them is named in the module's ledger entry.

    `games` is an iterable of mappings carrying `away_team`, `home_team` (BOARD
    names -- the join downstream is on these and nothing else) and the key into
    `live_index`.

    THE BUDGET IS A REFUSAL, NOT A TIMEOUT. Worker periodic work is never free
    (`#241` restarted production in a loop), and a 30-game Saturday window at
    120 sims is minutes of CPU. Games are simulated cheapest-first -- cost falls
    with time remaining, measured -- so the budget buys the most games it can,
    and every game it could not reach carries `tick_budget_exhausted` by name
    instead of a silently short slate.
    """
    from syndicate.features.shared.request_path_guard import refuse_if_compute_in_request_path

    refuse_if_compute_in_request_path("ncaaf_live_resim_snapshot")

    sims = int(sims or default_sims())
    budget = float(budget_seconds if budget_seconds is not None else default_budget_seconds())
    generated_at = str(now or datetime.now(timezone.utc).isoformat())

    prepared: list[tuple[float, dict[str, Any], NcaafLiveGameState | NcaafResimRefusal]] = []
    for game in games or ():
        if not isinstance(game, Mapping):
            continue
        away_team = str(game.get("away_team") or "").strip()
        home_team = str(game.get("home_team") or "").strip()
        if not away_team or not home_team:
            continue
        state_row = live_index.get(str(game.get("live_key") or ""))
        if not isinstance(state_row, Mapping):
            resolved: NcaafLiveGameState | NcaafResimRefusal = NcaafResimRefusal(
                "no_live_state", "no ESPN row matched this game"
            )
        else:
            resolved = live_state_from_espn_event(
                state_row, away_team=away_team, home_team=home_team
            )
        # A CALLER-NAMED REFUSAL, applied only to a game that is actually live.
        # The FBS-vs-FCS path uses it for `no_pregame_line`: a game still in its
        # pregame state keeps the more informative not-started reason above.
        preset = game.get("refusal")
        if isinstance(resolved, NcaafLiveGameState) and isinstance(preset, (tuple, list)) and preset:
            resolved = NcaafResimRefusal(str(preset[0]), str(preset[1]) if len(preset) > 1 else "")
        # Remaining regulation seconds: the cost proxy, and it is a good one --
        # 154 ms/sim with a full game left, 0.7 ms with 15 seconds left.
        if isinstance(resolved, NcaafLiveGameState):
            remaining = (4 - resolved.period) * 900 + resolved.clock_seconds
        else:
            remaining = -1.0
        names = {"away_team": away_team, "home_team": home_team}
        provenance = game.get("rating_provenance")
        if isinstance(provenance, Mapping):
            names["provenance"] = dict(provenance)
        prepared.append((float(remaining), names, resolved))

    prepared.sort(key=lambda item: item[0])

    started = time.monotonic()
    out_games: list[dict[str, Any]] = []
    for _remaining, names, resolved in prepared:
        if isinstance(resolved, NcaafResimRefusal):
            result: dict[str, Any] | NcaafResimRefusal = resolved
            state = None
        else:
            state = resolved
            pair = _ratings_for(ratings, state.home_team, state.away_team)
            if pair is None:
                result = NcaafResimRefusal(
                    "no_pregame_ratings",
                    "no SP+ rating for one or both teams; a neutral default would rate "
                    "an unknown team as league-average",
                )
            elif time.monotonic() - started >= budget:
                result = NcaafResimRefusal(
                    "tick_budget_exhausted",
                    f"the {budget:.0f}s re-sim budget was spent before this game",
                )
            else:
                (home_off, home_def), (away_off, away_def) = pair
                result = resim_live_game(
                    state,
                    home_offense=home_off,
                    home_defense=home_def,
                    away_offense=away_off,
                    away_defense=away_def,
                    sims=sims,
                )
        lanes = build_game_lens(
            state, result, live_state_as_of=state.as_of if state is not None else generated_at
        )
        # PROVENANCE ON THE LANE, never only in a log. A probability resting on a
        # market-implied rating must be distinguishable from one resting on SP+
        # by anyone holding the snapshot. FBS lanes get no key at all, so their
        # payload is unchanged.
        provenance = names.get("provenance")
        if isinstance(provenance, Mapping):
            for lane in lanes:
                lane["ratingSource"] = provenance.get("source")
                lane["marketImplied"] = {k: v for k, v in provenance.items() if k != "source"}
        out_games.append({
            "away_name": names["away_team"],
            "home_name": names["home_team"],
            "gameLens": lanes,
        })

    snapshot = {
        "sport": "ncaaf",
        "date": str(date_str or "")[:10],
        "generatedAt": generated_at,
        "simsPerGame": sims,
        "budgetSeconds": budget,
        "elapsedSeconds": round(time.monotonic() - started, 3),
        "games": out_games,
    }
    snapshot["coverage"] = summarise(out_games)
    return snapshot


# ---------------------------------------------------------------------------
# FBS-vs-FCS: A MARKET-IMPLIED RATING FOR THE UNRATED SIDE
# `[2026-09-10, user decision: "Market-implied rating", for FAMU @ MIA]`
# ---------------------------------------------------------------------------
# SP+ covers FBS only, so an FBS-vs-FCS game has no rating for one side and
# `_ratings_for` refuses it rather than rate the unknown team league-average.
# This does NOT relax that rule. It supplies a MEASURED number for the missing
# side -- the market's own pregame view -- and stamps it, so a probability that
# rests on it can never pass as one resting on SP+.
#
# AN ESTIMATOR, NOT A MECHANISM (`model_engine_standard.md` §4.4): it changes how
# one input is measured, not what the engine does, so there is no re-fit
# obligation. It IS unvalidated on FCS games -- nothing has graded one -- which
# is why the stamp exists.
MARKET_IMPLIED_RATING_SOURCE = "market_implied"


def fcs_market_implied_enabled() -> bool:
    """ABSENT MEANS ON, like `SYNDICATE_NCAAF_LIVE_RESIM`: turning it off needs
    only the env var (`off`/`0`/`false`/`no`) and a deploy, never a code change."""
    raw = str(os.environ.get("SYNDICATE_NCAAF_FCS_MARKET_IMPLIED") or "").strip().lower()
    return raw not in {"off", "0", "false", "no"}


def pregame_line_from_espn_event(event: Any) -> dict[str, Any] | None:
    """The book's PREGAME spread and total off an ESPN scoreboard event, or None.

    `pre` EVENTS ONLY. An in-progress event's odds object is not guaranteed to be
    the pregame line, and reading a live quote as a pregame one would make the
    FCS team's rating move with the score -- the one thing a pregame prior must
    not do. The caller captures the line while the game is `pre` and persists it.

    THE SIGN COMES FROM THE FAVOURITE FLAGS, not from `spread`'s sign, which is
    not documented as home-relative. A line with no single favourite and a
    non-zero spread is refused rather than guessed.
    """
    if not isinstance(event, Mapping):
        return None
    status = event.get("status") if isinstance(event.get("status"), Mapping) else {}
    status_type = status.get("type") if isinstance(status.get("type"), Mapping) else {}
    if str(status_type.get("state") or "").strip().lower() != "pre":
        return None
    competitions = event.get("competitions")
    competition = (
        competitions[0]
        if isinstance(competitions, list) and competitions and isinstance(competitions[0], Mapping)
        else {}
    )
    for odds in competition.get("odds") or ():
        if not isinstance(odds, Mapping):
            continue
        try:
            magnitude = abs(float(odds.get("spread")))
            total = float(odds.get("overUnder"))
        except (TypeError, ValueError):
            continue
        if not (total > 0.0):
            continue
        home_odds = odds.get("homeTeamOdds") if isinstance(odds.get("homeTeamOdds"), Mapping) else {}
        away_odds = odds.get("awayTeamOdds") if isinstance(odds.get("awayTeamOdds"), Mapping) else {}
        home_fav, away_fav = bool(home_odds.get("favorite")), bool(away_odds.get("favorite"))
        if magnitude == 0.0:
            home_margin = 0.0
        elif home_fav and not away_fav:
            home_margin = magnitude
        elif away_fav and not home_fav:
            home_margin = -magnitude
        else:
            continue
        provider = odds.get("provider") if isinstance(odds.get("provider"), Mapping) else {}
        return {
            "home_margin": home_margin,
            "total": total,
            "provider": str(provider.get("name") or ""),
            "details": str(odds.get("details") or ""),
        }
    return None


def market_implied_sp_components(
    *,
    rated_offense: float,
    rated_defense: float,
    rated_is_home: bool,
    home_margin: float,
    total: float,
    league_means: tuple[float, float],
) -> tuple[float, float] | None:
    """Raw SP+ (offense, defense) POINTS for the unrated side, or None.

    SP+'s own additive form: a team's expected points = its offense rating + the
    opponent's defense rating (points ALLOWED) - the league baseline, taken as
    the mean of the two component means so an average team scores the baseline
    against an average team. The market's pregame line gives both expected
    scores, `(total +/- home_margin) / 2`, and the rated side's components are
    known, which leaves exactly two unknowns and two equations.

    The result is in SP+'s RAW scale, so the caller runs it through
    `sp_offense_defense_rating` -- the same centring and scaling every FBS team
    gets. Home field is NOT separated out: the market's margin includes it and so
    does this rating, a bias of at most a few points against spreads this path
    exists for (MIA -59.5).

    None when the line implies a negative score -- it cannot be a real line.
    """
    off_mean, def_mean = league_means
    baseline = (float(off_mean) + float(def_mean)) / 2.0
    home_points = (float(total) + float(home_margin)) / 2.0
    away_points = (float(total) - float(home_margin)) / 2.0
    if home_points < 0.0 or away_points < 0.0:
        return None
    rated_points_allowed = home_points if not rated_is_home else away_points
    rated_points_scored = home_points if rated_is_home else away_points
    unrated_defense = rated_points_scored - float(rated_offense) + baseline
    unrated_offense = rated_points_allowed - float(rated_defense) + baseline
    return float(unrated_offense), float(unrated_defense)


def _ratings_for(
    ratings: Mapping[str, tuple[float, float]], home_team: str, away_team: str
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """Both sides' (offense, defense), or None. NEVER a neutral default.

    `sp_offense_defense_rating` returns None for an unmatched team for exactly
    this reason: 0.0 is the engine's AVERAGE team, so substituting it would rate
    an unknown as league-average and the resulting probability would be
    indistinguishable from a real one. The FBS-only boundary is real -- 48 of 99
    week-1 fixtures had an unrated side -- so this refusal will fire often and
    must stay legible.
    """
    home = ratings.get(_norm_name(home_team))
    away = ratings.get(_norm_name(away_team))
    if home is None or away is None:
        return None
    return (float(home[0]), float(home[1])), (float(away[0]), float(away[1]))


def _norm_name(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def live_lens_snapshot_path(data_root: Any) -> Any:
    """Where the join reads. Mirrors every other sport's live-lens path.

    `data/live/ncaaf_live_lens.json` is NOT date-scoped and does not need to be:
    `refresh_state_store.write_json_file` routes it to the KEYVALUE backend on
    Render (`data/live/` matches none of `_KEYVALUE_EXCLUDED_PATH_MARKERS`), so
    it reaches the web service through Redis rather than through
    `pull_hot_artifacts`, whose `*<date>*` glob would never carry it. That is
    the same route `mlb_live_lens.json` and `wnba_live_lens.json` already take.
    """
    from pathlib import Path

    return Path(data_root) / "live" / "ncaaf_live_lens.json"


def validate_live_lens_snapshot(snapshot: Any) -> tuple[bool, str]:
    """Shape gate for `live_lens_loop`. Cheap, and it must not pass an empty."""
    if not isinstance(snapshot, Mapping):
        return False, "snapshot_is_not_a_mapping"
    games = snapshot.get("games")
    if not isinstance(games, list):
        return False, "snapshot_carries_no_games_list"
    for game in games:
        if not isinstance(game, Mapping):
            return False, "game_is_not_a_mapping"
        if not str(game.get("home_name") or "").strip():
            return False, "game_carries_no_home_name"
        if not isinstance(game.get("gameLens"), list):
            return False, "game_carries_no_gameLens"
    return True, "ok"


def summarise(games: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Coverage counters with their denominators, by refusal reason.

    `A RATE, NOT A COUNT`: `live_resimmed` alone cannot say whether a small
    number means a quiet slate or a dead producer, so the denominators and every
    refusal reason travel with it.
    """
    counts: dict[str, int] = {}
    resimmed = 0
    for game in games:
        lanes = game.get("gameLens") if isinstance(game.get("gameLens"), list) else []
        for lane in lanes:
            if not isinstance(lane, Mapping):
                continue
            if str(lane.get("source") or "") == LIVE_RESIM_LENS_SOURCE:
                resimmed += 1
            else:
                reason = str(lane.get("liveResimRefusal") or "unstamped")
                counts[reason] = counts.get(reason, 0) + 1
    return {
        "games": len(games),
        "live_resimmed": resimmed,
        "refused": sum(counts.values()),
        "refusals_by_reason": counts,
    }
