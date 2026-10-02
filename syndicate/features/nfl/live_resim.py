"""NFL live re-simulation. DEFAULT OFF, and it refuses on a degenerate rating.

`[2026-09-07, user decision: "build it default-off behind a flag"]`, taken after
the case against shipping it was put and reaffirmed. That case is not softened
here, because whoever flips the flag needs to read it:

  * NFL regular season LOSES to the closing line -- test MAE 10.495 vs market
    9.722, t=+3.34 over 272 held-out games -- and `nfl_preseason_calibration
    .skill_note()` returns None for anything that is not the preseason profile,
    so **no skill gate exists on the branch this feeds**.
  * `NFL_CALIBRATION_PROFILE` is the in-source DEFAULT. Its own docstring says
    it "reproduces today's hardcoded constants exactly" -- NFL has never had a
    real calibration.
  * Lane `nfl-rating-units` is OPEN and mid-diagnosis on a measurement that this
    engine CANNOT TELL TEAMS APART: across-game `margin_mean` stdev 2.16 for an
    NFL week against NCAAF's 15.37, with 93.8% of games landing in P(home)
    0.35-0.65.

So this module exists, is wired for the day those are answered, and does not
publish until someone deliberately turns it on.

--------------------------------------------------------------------------
THE FLAG IS NOT THE ONLY GUARD, AND THAT IS DELIBERATE
--------------------------------------------------------------------------
A flag protects against being ON by accident. It does nothing about being ON
when the model is broken, which is the actual risk here and is a live, measured
condition rather than a hypothetical. So `resim_live_game` REFUSES with
`degenerate_ratings` when the four ratings handed to it cannot separate the two
teams -- see `RATING_SEPARATION_FLOOR`.

That check is deliberately on the INPUT rather than the output. A degenerate
rating produces a confident-looking 0.5, and a probability near 0.5 is
indistinguishable from a genuinely even game. Refusing on the input keeps the
two apart; refusing on the output could not.

**If `nfl-rating-units` fixes the rating, this check stops firing on its own.**
It is not a workaround for that lane's bug and does not need removing when they
land -- it is a floor that a working rating clears.

--------------------------------------------------------------------------
WHAT IS DELIBERATELY NOT HERE
--------------------------------------------------------------------------
No worker tick, no join registration, no `_LIVE_GAMELINE_SPORTS` entry. Those
live in `scripts/run_refresh_worker.py`, `live_gameline_join.py` and
`board_enrichment.py`, all CLAIMED by other lanes (`ncaaf-live-resim-wire`,
`ncaaf-live-resim`). Registering there is what would make this reachable, and it
is theirs to do. **Until then this module is inert by construction, not merely
by flag** -- nothing calls it.

The lens contract below mirrors `ncaaf/live_resim.py` exactly so that
registration is a two-entry change rather than a translation layer.
"""

from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from syndicate.features.football.sim_engine.smartsim2.calibration_profile import (
    NFL_CALIBRATION_PROFILE,
)
from syndicate.features.football.sim_engine.smartsim2.contracts import (
    SmartSim2SimulationInput,
)
from syndicate.features.football.sim_engine.smartsim2.game_simulator import simulate_game
from syndicate.features.shared.team_aliases import canonical_team

LIVE_RESIM_LENS_SOURCE = "live_resim"
PREGAME_LENS_SOURCE = "pregame"
DEFAULT_SIMS = 120
MAX_RESUMABLE_PERIOD = 4

# A LITERAL-DEGENERACY FLOOR ON THE INPUT. Kept, but it is NOT the real guard --
# see `UNINFORMATIVE_BAND` below, and read this comment before trusting it.
#
# THIS FLOOR WAS THE WHOLE GUARD AND IT DID NOT COVER THE FAILURE MODE.
# `[corrected 2026-09-07 by lane soccer-unfed-inputs; arithmetic re-derived here
# before accepting]`. Using `nfl-rating-units`' own number -- NFL rating sd 2.16,
# so a difference of two ratings has sd 2.16*sqrt(2) = 3.05:
#
#     P(|rating gap| < 0.5)          13.0%   <- what this floor catches
#     P(output inside 0.35-0.65)     93.8%   <- the measured defect
#
# So AT LEAST 80.8% of games clear this floor AND are uninformative. The floor
# stops LITERAL degeneracy; the defect is COMPRESSION. A gap of 0.6 clears a 0.5
# floor comfortably and still yields a coin flip.
#
# The same arithmetic on NCAAF (sd 15.37) refuses 1.8% -- this floor was
# calibrated as if NFL's ratings behaved like NCAAF's, which is precisely what
# `nfl-rating-units` measured they do not.
#
# **A guard that makes wiring LOOK safe without making it safe is worse than no
# guard**, because a named refusal in the lane reads to a later auditor as "the
# brake held". Kept only because literal-identical ratings are still worth
# refusing early and cheaply.
#
# ---------------------------------------------------------------------------
# RE-CALIBRATED 2026-09-27, AND THE ARITHMETIC ABOVE WAS FITTED TO A RATING
# SCALE PRODUCTION DOES NOT USE.
# ---------------------------------------------------------------------------
#
# The block above reasons from "NFL rating sd 2.16" and predicts this floor
# refuses 13% of games. MEASURED on the artifacts production's own tick reads
# (`nfl_source/smartsim2_ratings_2026_wk<N>.json`, fetched live), the net
# rating (offense + defense) is nowhere near that scale:
#
#     wk1  net sd 0.381   P(|separation| < 0.5) over all 496 pairings = 63.1%
#     wk2  net sd 0.866                                                28.4%
#     wk3  net sd 0.329                                                68.3%
#
# which is why a cutoff-replay grade of this function refused 15 of 33 games
# (45%) with `degenerate_ratings`. The 13% was never the live rate.
#
# AND THE FLOOR IS NOT SMALL IN THE ENGINE'S UNITS. Measured by driving
# `resim_live_game` with a controlled separation, tied at kickoff, 400-600 sims:
#
#     separation 0.50 -> margin +5.7 to +6.1, p(home) 0.666-0.671
#     separation 1.00 -> margin +11.3,        p(home) 0.774
#
# i.e. roughly 11-12 margin points per 1.0 of separation. So a 0.5 floor
# refuses every game this model thinks is closer than about a SIX-POINT spread
# -- which is most of the NFL. It was never a degeneracy test; it was an
# accidental "only price blowouts" rule.
#
# WHY LOWERING IT IS NOT MERELY MOVING THE REFUSAL. At tied kickoff the two
# guards look coincident: sub-floor separations land inside `UNINFORMATIVE_BAND`
# anyway, so nothing would change. That reading is an artifact of a state with
# NO score information. At the states this function is actually called on --
# quarter boundaries of a game in progress -- the scoreline carries the signal
# and the output is informative even when the ratings barely separate:
#
#     Q1 end  7-0   separation 0.05 -> p 0.7314   priceable
#     Q3 end 21-14  separation 0.05 -> p 0.8304   priceable
#     Q3 end 14-21  separation 0.05 -> p 0.1931   priceable
#     Q2 end 10-7   separation 0.05 -> band-refused (genuinely close)
#
# Three of four representative states are priceable at a separation this floor
# currently refuses, and the one that is not is caught by the band on its own
# merits. So the floor was costing real coverage.
#
# THE NEW VALUE IS DERIVED, NOT PICKED: 0.02 of separation is ~0.25 margin
# points at the measured sensitivity, which is the scale at which ratings
# genuinely stop distinguishing two teams. Everything above that is left to
# `UNINFORMATIVE_BAND`, which guards the OUTPUT -- the quantity that decides
# whether a price is a coin flip -- and which the comment above correctly
# identifies as the real guard.
RATING_SEPARATION_FLOOR = 0.02

# THE REAL GUARD, and it is on the OUTPUT because that is where the defect is.
#
# Refuse when the produced probability lands in the band this engine has never
# been shown to beat the closing line inside. Measured: 93.8% of NFL games land
# in P(home) 0.35-0.65, and NFL regular season loses to the close at t=+3.34
# over 272 held-out games with NO skill gate on the h2h branch.
#
# I ARGUED AGAINST AN OUTPUT CHECK AND WAS WRONG. My objection was that a
# confident-looking 0.5 from a broken rating is indistinguishable from a
# genuinely even game, so refusing on the output cannot tell them apart. True --
# and it does not matter: on an engine with no demonstrated skill, a GENUINE
# 0.5 has no more value than a spurious one. Refusing both costs nothing real,
# and refusing neither is what publishes noise.
#
# It fires on ~93.8% of games today and on progressively fewer as the rating
# starts separating teams, which is what a floor is supposed to do. Its exit
# condition is explicit: **remove it when a skill gate exists on the h2h branch**
# -- the thing NCAAF gets for free from `no_two_sided_market_price` and NFL does
# not have. Until then it is doing that gate's job.
UNINFORMATIVE_BAND = (0.35, 0.65)


def nfl_live_resim_enabled(env: Mapping[str, str] | None = None) -> bool:
    """DEFAULT OFF. Absent reads as off, and that is checked not assumed.

    CLAUDE.md's rule: *absent is not off* -- `_evaluation_settlement_auto_refresh
    _enabled` treats absent as False while `_mlb_refresh_tick_owner_here`
    defaults True, so the same edit is a no-op in one and a behaviour change in
    the other. Here absent is OFF, explicitly, because the module publishes live
    money edges on an engine that currently loses to the close.
    """
    source = os.environ if env is None else env
    raw = str(source.get("SYNDICATE_NFL_LIVE_RESIM") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class NflResimRefusal:
    """Why this game carries no live probability. Never a probability."""

    reason: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"reason": self.reason, "detail": self.detail}


@dataclass(frozen=True)
class NflLiveGameState:
    """What smartsim2 needs to resume an NFL game, and nothing more.

    `home_team`/`away_team` are the BOARD's names, not ESPN's. `nfl/live_game_state
    .py` already carries the ESPN side and the two disagree; joining on ESPN
    names here would import that disagreement into the probability.
    """

    away_team: str
    home_team: str
    period: int
    clock_seconds: int
    home_score: int
    away_score: int
    down: int = 1
    distance: int = 10
    # SMARTSIM2's frame: yards from the POSSESSING team's own goal line, 1..99.
    # ESPN's `yardLine` is in the home team's frame.
    field_position: int = 25
    # None means ESPN did not say. NOT defaulted to a side -- `resim_live_game`
    # marginalises over both, because picking one is worth roughly a possession
    # of field position on a close game.
    possession_owner: str | None = None


def default_sims() -> int:
    raw = str(os.environ.get("SYNDICATE_NFL_LIVE_RESIM_SIMS") or "").strip()
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_SIMS
    return n if 1 <= n <= 2000 else DEFAULT_SIMS


def ratings_are_unfed(
    *, home_offense: float, home_defense: float,
    away_offense: float, away_defense: float,
) -> bool:
    """True when all four ratings are exactly zero, i.e. nothing fed them.

    THIS IS A DIFFERENT FAILURE FROM TWO EVENLY-MATCHED TEAMS and it now gets
    its own refusal reason. `sp_offense_defense_rating` returns `(0.0, 0.0)` for
    a team it cannot find, and there is NO week-4 ratings artifact as of
    2026-09-27 -- so a live tick on a week-4 game rates both sides zero and the
    old code spelled that "degenerate_ratings", identical to a close game. One
    is missing data that someone must publish; the other is the model working.
    A shared reason string made them indistinguishable in the refusal counts,
    which is how 45% of a grade's sample got attributed to a closed lane's
    rating compression instead of to an absent file.
    """
    return all(abs(float(v)) == 0.0 for v in
               (home_offense, home_defense, away_offense, away_defense))


def ratings_are_degenerate(
    *, home_offense: float, home_defense: float,
    away_offense: float, away_defense: float,
) -> bool:
    """True when the two teams' ratings cannot separate them.

    Compares the two SIDES, not the four numbers: what the simulation acts on is
    home-offense against away-defense and vice versa, so two teams with
    identical net strength are indistinguishable even if their individual
    numbers differ.
    """
    home_net = float(home_offense) - float(away_defense)
    away_net = float(away_offense) - float(home_defense)
    return abs(home_net - away_net) < RATING_SEPARATION_FLOOR


# ---------------------------------------------------------------------------
# RATING UNCERTAINTY PROPAGATION. The distribution is too narrow because the
# simulator treats a noisy rating as a certain one.
# ---------------------------------------------------------------------------
#
# MEASURED 2026-09-27 over 80 cutoff rows / 32 games, margins, split by the
# rating source the artifact itself declares:
#
#     wk1  prior_season_fallback   sim_sd 8.414   residual_sd 10.219
#     wk2+3 rolling / blend        sim_sd 8.504   residual_sd 14.153
#
# `sim_sd` IS FLAT while `residual_sd` swings four points with the SOURCE. The
# simulator's spread cannot be the explanation for a difference the simulator
# does not know about: what changes between those rows is how well-determined
# the ratings are. wk1's come from a full prior season; wk2's come from one week
# of games. The missing variance is RATING uncertainty, not game variance.
#
# THIS IS ALSO WHY A GLOBAL SPREAD CONSTANT CANNOT WORK, and one was refused on
# exactly this evidence: the widening required is x1.214 on wk1 and x1.664 on
# wk2+3, so any single scale is wrong for whichever half it was not fitted on.
# Fitted anyway on a 221-point grid it reached a worst bucket of 0.1177 -- under
# `#499`'s bar -- and INVERTED out of sample (test 0.254 -> 0.3495), partly by
# evacuating the failing bucket below the power floor (0.9-1.0: n=83 -> n=9).
#
# THE CONSTANTS BELOW ARE PROVISIONAL, and the first derivation of them was
# WRONG in a way worth recording. Required extra variance is
# `residual_sd^2 - sim_sd^2` (5.80 pts for wk1, 11.31 for wk2+3). Converting
# that to rating units by the engine's sensitivity of ~11.4 margin points per
# 1.0 of net separation, then halving because net separation is
# `(ho+hd) - (ao+ad)` whose variance is 4*sd^2, gives per-rating sd 0.254 and
# 0.496 -- and PREDICTS a widening of roughly 1.6x at 0.496.
#
# MEASURED, it is 1.17x:
#
#     rating_sd 0.000 -> margin sd 11.379   1.000x
#     rating_sd 0.254 -> margin sd 11.853   1.042x
#     rating_sd 0.496 -> margin sd 13.327   1.171x
#     rating_sd 0.750 -> margin sd 14.478   1.272x
#
# The 11.4 slope was taken across LARGE separations and the engine's response
# SATURATES (separation 2.0 -> +16.4 margin, 4.0 -> +23.9, 8.0 -> +29.1), so the
# local slope around an operating point is far smaller than the global one, and
# perturbing symmetrically across a concave response yields less spread than the
# linear approximation. **A sensitivity measured over the wrong range is the same
# class of error as a threshold measured in the wrong units** -- which is what
# `RATING_SEPARATION_FLOOR` above turned out to be.
#
# So the mapping source -> sd was fitted EMPIRICALLY against the observed
# widening rather than computed from a slope. That fit has now RUN; see the
# table below for what it returned and why it collapsed to a single value.
#
# WHAT THE FIT DOES NOT BUY, stated here so the number above is not misread as a
# green light: with dispersion matched at rating_sd 1.0 the worst powered bucket
# is 0.2410 against `#499`'s 0.150 bar, all ten buckets still powered, and MAE
# 9.596 still LOSES to a frozen baseline's 7.522. Fixing the spread did not make
# this model publishable -- the remaining error is RESOLUTION, not calibration.
# It also costs coverage: refused cutoffs rise 19 -> 30 as honest uncertainty
# pulls more games into the uninformative band. That is the correct trade and it
# is still a trade.
#
# READ THE SANITY CHECK BEFORE TRUSTING ANY OUTPUT OF THIS: those uncertainties
# are the SAME ORDER as the ratings' own dispersion (net sd 0.381 / 0.866 /
# 0.329 for wk1/2/3). The ratings carry about as much noise as signal, which is
# precisely what a model losing to a frozen baseline looks like. Propagating
# this honestly will pull probabilities TOWARD the score-implied baseline. That
# is the correct direction, not a bug.
#
# DEFAULT OFF. NFL live re-sim is ENABLED in production (measured today:
# `NFL_LIVE_RESIM {"enabled": true, "games": 16}`) and prices the MONEYLINE, so
# switching this on changes live published probabilities. It ships inert and
# turns on after its own grade, which is the sequence NCAAF's totals correction
# skipped.
# FITTED EMPIRICALLY 2026-09-27, replacing the slope-derived 0.254 / 0.496.
# Swept `--rating-sd` over the full replay and compared on the 51 rows COMMON to
# every run, because raising the sd pulls probabilities toward 0.5 and pushes
# rows into `UNINFORMATIVE_BAND` -- the scored sample shrank 80 -> 69 -> 56, so a
# naive cross-sweep comparison is partly selection, not calibration:
#
#     rating_sd 0.0   sim_sd  7.761   residual_sd 12.244   ratio 0.634
#     rating_sd 1.0   sim_sd  9.818   residual_sd 11.659   ratio 0.842
#     rating_sd 2.0   sim_sd 12.965   residual_sd 10.832   ratio 1.197
#
# The mismatch closes monotonically on a FIXED sample, so the mechanism does what
# it was built to do. ~1.0 is the defensible setting; 2.0 over-widens.
#
# AND A SINGLE VALUE FITS BOTH SOURCES, so the per-source split this table was
# invented for is NOT warranted by the evidence. At rating_sd 1.0:
#
#     wk1 prior_season_fallback   sim_sd 10.439  residual_sd  9.591  ratio 1.088
#     wk2+3 rolling / blend       sim_sd 11.029  residual_sd 12.172  ratio 0.906
#
# Those straddle 1.0 within ~10%. The x1.214-vs-x1.664 gap that motivated a
# per-source map was an artifact of measuring the required widening on the POINT
# estimate, where rating noise is entirely absent from the spread; once it is
# propagated, the two sources need nearly the same sd. The table is kept as the
# hook for a later refit ON EVIDENCE, with both entries at the fitted value
# rather than at numbers that would imply a distinction nothing has measured.
_RATING_UNCERTAINTY_BY_SOURCE = {
    "prior_season_fallback": 1.0,
    "current_season_rolling": 1.0,
    "current_season_blend": 1.0,
}
_RATING_UNCERTAINTY_DEFAULT = 1.0


def rating_uncertainty_for_source(source: Any) -> float:
    """Per-rating sd for a declared `rating_source`. UNKNOWN IS THE WIDE ONE.

    An unrecognised source is treated as the NOISIEST case, not the cleanest:
    `learnings.md` forbids mapping unknown onto the permissive branch, and here
    the permissive branch is "this rating is well determined", which would
    publish a confident probability off a source nobody has measured.
    """
    key = str(source or "").strip().lower()
    return _RATING_UNCERTAINTY_BY_SOURCE.get(key, _RATING_UNCERTAINTY_DEFAULT)


def _perturbed_ratings(
    seed: int, sd: float,
    home_offense: float, home_defense: float,
    away_offense: float, away_defense: float,
) -> tuple[float, float, float, float]:
    """The four ratings resampled for ONE simulation, deterministically.

    Seeded from the sim's own seed so a replay of the same seed reproduces the
    same draw -- a harness that could not reproduce its own rows could not
    compare two variants on the SAME draws, which is how a calibration sweep
    turns into a comparison of random seeds.
    """
    # Seeded from a STRING, not from a tuple's `__hash__()`: a tuple hashes its str
    # member through Python's per-process randomised string hash (PYTHONHASHSEED),
    # so every new interpreter drew different ratings -- deterministic within one
    # process, irreproducible across them (2026-10-02: p 0.657..0.760 over hash
    # seeds 0..9 at rating_sd 0.75; the widening test failed ~1 run in 5).
    # `random.Random(str)` seeds from the string's SHA-512, identical everywhere.
    rng = random.Random(f"nfl-rating-uncertainty|{int(seed)}|{float(sd)!r}")
    return (
        home_offense + rng.gauss(0.0, sd),
        home_defense + rng.gauss(0.0, sd),
        away_offense + rng.gauss(0.0, sd),
        away_defense + rng.gauss(0.0, sd),
    )


def _histogram(values: list[int]) -> dict[str, int]:
    """`{value: count}` over integer draws, keyed by str so it survives JSON.

    Same shape as the pregame sidecar's `margin_dist` / `total_points_dist` and
    as NCAAF's, so a reader who understands one understands the others.
    """
    out: dict[str, int] = {}
    for value in values:
        key = str(value)
        out[key] = out.get(key, 0) + 1
    return out


def resim_live_game(
    state: NflLiveGameState,
    *,
    home_offense: float,
    home_defense: float,
    away_offense: float,
    away_defense: float,
    sims: int | None = None,
    profile: Any = NFL_CALIBRATION_PROFILE,
    env: Mapping[str, str] | None = None,
    rating_sd: float = 0.0,
) -> dict[str, Any] | NflResimRefusal:
    """Rest-of-game Monte Carlo from `state`, or a refusal. Never raises.

    The probability is the empirical share of simulated rest-of-games the home
    team finishes ahead in, given the scoreboard -- not a transform of the
    pregame number. An already-decided game falls out as exactly 1.0 or 0.0
    because that is what the simulations say.
    """
    if not nfl_live_resim_enabled(env):
        return NflResimRefusal(
            "nfl_live_resim_disabled",
            "SYNDICATE_NFL_LIVE_RESIM is not set; NFL regular season has no skill "
            "gate and loses to the close at t=+3.34",
        )
    if ratings_are_unfed(home_offense=home_offense, home_defense=home_defense,
                         away_offense=away_offense, away_defense=away_defense):
        return NflResimRefusal(
            "unfed_ratings",
            "all four ratings are exactly 0.0; nothing fed them. Most likely no "
            "ratings artifact exists for this week (there was none for week 4 on "
            "2026-09-27) or the team name did not join. This is missing DATA, not "
            "two evenly-matched teams",
        )
    if ratings_are_degenerate(home_offense=home_offense, home_defense=home_defense,
                              away_offense=away_offense, away_defense=away_defense):
        return NflResimRefusal(
            "degenerate_ratings",
            f"net rating separation < {RATING_SEPARATION_FLOOR}; the engine would "
            f"report its prior, not its opinion (see lane nfl-rating-units)",
        )
    if int(state.period) > MAX_RESUMABLE_PERIOD:
        return NflResimRefusal("overtime_not_resumable",
                               f"period {state.period} > {MAX_RESUMABLE_PERIOD}")
    if int(state.clock_seconds) < 0:
        return NflResimRefusal("bad_clock", f"clock_seconds={state.clock_seconds}")

    n = int(sims) if sims else default_sims()
    if n <= 0:
        return NflResimRefusal("no_sims_requested", f"sims={n}")

    base = dict(
        home_team=state.home_team or "HOME",
        away_team=state.away_team or "AWAY",
        home_offense_rating=float(home_offense),
        home_defense_rating=float(home_defense),
        away_offense_rating=float(away_offense),
        away_defense_rating=float(away_defense),
        initial_quarter=int(state.period),
        initial_clock_seconds=int(state.clock_seconds),
        initial_score_home=int(state.home_score),
        initial_score_away=int(state.away_score),
        initial_down=int(state.down),
        initial_distance=int(state.distance),
    )

    # Possession unknown is MARGINALISED, not assumed -- half the seeds with each
    # side at its own 25. Picking a side silently is worth about a possession of
    # field position on a close game.
    plans = ([("home", 25), ("away", 25)] if state.possession_owner is None
             else [(state.possession_owner, int(state.field_position))])

    # ZERO IS OFF AND IS BIT-IDENTICAL TO THE PREVIOUS BEHAVIOUR: the branch
    # below is not entered, `base` is used unchanged, and the same seeds produce
    # the same games. That is asserted by a test rather than assumed.
    sd = max(0.0, float(rating_sd or 0.0))

    started = time.time()
    home_wins = 0
    ties = 0
    margins: list[int] = []
    totals: list[int] = []
    ran = 0
    per_plan = max(1, n // len(plans))
    for owner, field_position in plans:
        for seed in range(1, per_plan + 1):
            call = base
            if sd > 0.0:
                # RESAMPLED PER SIMULATION, so each draw is a game played by a
                # plausible version of these teams rather than by the point
                # estimate. Perturbing the INPUT and letting the engine respond
                # is what makes the widening game-specific: a well-determined
                # rating barely moves, a one-week rating moves a lot.
                ho, hd, ao, ad = _perturbed_ratings(
                    seed, sd, home_offense, home_defense, away_offense, away_defense)
                call = dict(base,
                            home_offense_rating=ho, home_defense_rating=hd,
                            away_offense_rating=ao, away_defense_rating=ad)
            try:
                out = simulate_game(
                    SmartSim2SimulationInput(
                        seed=seed,
                        initial_possession_owner=owner,
                        initial_field_position=field_position,
                        **call,
                    ),
                    profile=profile,
                )
            except Exception as exc:  # never raise into the tick
                return NflResimRefusal("sim_failed", f"{type(exc).__name__}: {exc}"[:200])
            home_points = int(out.final_score["home"])
            away_points = int(out.final_score["away"])
            margins.append(home_points - away_points)
            totals.append(home_points + away_points)
            ran += 1
            if home_points > away_points:
                home_wins += 1
            elif home_points == away_points:
                ties += 1

    if ran <= 0:
        return NflResimRefusal("no_sims_run", "the simulation loop produced no results")

    # A tie is half a win, matching the pregame convention. And the POINT
    # estimate is Agresti-Coull, not raw Wald -- `#C2` in the output checklist
    # exists because `prob_std_err` smoothed the INTERVAL while the caller
    # published the raw `k/n` as the CENTRE for months, and 83 MLB rows reached
    # exactly 0.0/1.0 as a result. Same trap, avoided at the source.
    k = home_wins + 0.5 * ties
    raw = k / ran
    smoothed = (k + 2.0) / (ran + 4.0)

    # THE OUTPUT GUARD. Runs AFTER the sim, on the number that would be
    # published, because that is where the measured defect lives -- the input
    # floor above catches 13% of a 93.8% problem. Refusing here costs a genuine
    # coin-flip game its lane, and that is the right trade while the engine has
    # no demonstrated skill: an edge on a true 0.5 is worth nothing either.
    lo, hi = UNINFORMATIVE_BAND
    if lo <= smoothed <= hi:
        return NflResimRefusal(
            "uninformative_probability",
            f"p={smoothed:.4f} is inside {lo}-{hi}, the band this engine has not "
            f"been shown to beat the close in (t=+3.34, no h2h skill gate). "
            f"Remove this guard when that gate exists.",
        )
    return {
        "model_home_win_prob": round(smoothed, 6),
        "model_home_win_prob_raw": round(raw, 6),
        "point_estimator": "agresti_coull",
        "sims_run": ran,
        "margin_mean": round(sum(margins) / ran, 4),
        "total_mean": round(sum(totals) / ran, 4),
        # THE DRAWS, not just their means. This loop already built them per sim
        # and threw them away at the return -- the same defect NCAAF carried
        # until 2026-09-26 and MLB until `0315f548`.
        #
        # WHAT THIS DOES NOT DO: publish. `build_game_lens` below still
        # constructs its lane field by field and carries NEITHER
        # `totalRunsDist` NOR `marginDist`, so `live_gameline_join` cannot price
        # a live NFL total or spread and keeps refusing them BY NAME. That gate
        # opens on the strength of a cutoff-replay grade and nothing else --
        # NCAAF's shipped on a grade that turned out to be fitted on 22-day-stale
        # SP+ ratings and had to be withdrawn hours later, which is the whole
        # argument for measuring before publishing rather than after.
        #
        # `margin_dist` is HOME-POSITIVE (`home - away`), matching
        # `run_margin_dist` and what `price_distribution_market` expects.
        "margin_dist": _histogram(margins),
        "total_dist": _histogram(totals),
        # AUDITABLE: a reader can always tell whether a published probability
        # came from the point estimate or from resampled ratings.
        "rating_sd": round(sd, 6),
        "possession_marginalised": state.possession_owner is None,
        "elapsed_seconds": round(time.time() - started, 3),
    }


def build_game_lens(
    state: NflLiveGameState | None,
    result: dict[str, Any] | NflResimRefusal,
    *,
    live_state_as_of: str = "",
) -> list[dict[str, Any]]:
    """The `gameLens` lane list, shaped exactly like NCAAF's.

    A refusal still produces a lane. A lane that vanishes on refusal is
    indistinguishable from a game the producer never saw, and that ambiguity is
    what made the original NCAAF zero unreadable.
    """
    as_of = live_state_as_of or datetime.now(timezone.utc).isoformat()
    if isinstance(result, NflResimRefusal):
        # STAMPED `pregame`, NOT `live_resim`. This module said it was "shaped
        # exactly like NCAAF's" while stamping refusals with the LIVE source and
        # leaving `PREGAME_LENS_SOURCE` defined-but-unused -- ncaaf/live_resim.py
        # uses it (line 472) and the join rejects it by stamp.
        #
        # It mattered the moment nfl was wired: `live_gameline_from_lens` keys on
        # `source` first and only then requires `modelHomeWinProb`. With the live
        # stamp, a refused game was excluded solely because it carries no
        # probability -- and that function's own docstring warns that keying on
        # the probability's presence "would silently accept a lens the re-sim
        # never touched". The stamp is the intended discriminator; this restores
        # it, so a refusal is rejected for WHAT IT IS rather than for what it
        # happens to lack.
        return [{
            "source": PREGAME_LENS_SOURCE,
            "ok": False,
            "as_of": as_of,
            "refusal": result.to_dict(),
        }]
    lane = {
        "source": LIVE_RESIM_LENS_SOURCE,
        "ok": True,
        "as_of": as_of,
        **result,
        # THE JOIN'S OWN FIELD NAMES, beside the snake-case ones above. Until
        # 2026-09-28 this lane carried ONLY `model_home_win_prob` / `sims_run`,
        # and `live_gameline_join.live_gameline_from_lens` reads only
        # `modelHomeWinProb` / `simsRun` / `projection` (NCAAF writes them at
        # `ncaaf/live_resim.py:772`, NHL at `nhl/live_resim.py:421`). So every
        # PRICED NFL lane was skipped as `skipped_no_accepted_lane` -- measured on
        # refresh-worker 2026-09-27 22:53Z: `sources_seen {live_resim: 4,
        # pregame: 12}`, `indexed 0`, and 82-92 full-game rows per build withheld
        # `no_live_gameline_projection`, none of them written to the ledger.
        "modelHomeWinProb": result.get("model_home_win_prob"),
        "simsRun": result.get("sims_run"),
        "liveStateAsOf": as_of,
        # THE MEANS, which is what `live_gameline_score` grades spreads/totals
        # on (`model_margin_mean` / `model_total_mean`), and FINAL-GAME values
        # because the sim resumes from the live score.
        #
        # NO `totalRunsDist` / `marginDist`, DELIBERATELY. Those open spread and
        # total PRICING, and `nfl-live-distribution-grade` graded NFL live
        # margins a measured FAIL (worst powered bucket 0.4290 vs `#499`'s 0.150)
        # with totals unmeasurable. Without a distribution the join withholds
        # those rows by name and still records the means, so they are SCORED
        # without being priced.
        "projection": {
            "total": result.get("total_mean"),
            "homeMargin": result.get("margin_mean"),
        },
    }
    if state is not None:
        lane["live_state"] = {
            "period": state.period,
            "clock_seconds": state.clock_seconds,
            "home_score": state.home_score,
            "away_score": state.away_score,
        }
    return [lane]


def summarise(games: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Counts AND the refusal breakdown. A zero without one is not a result."""
    reasons: dict[str, int] = {}
    resimmed = 0
    for game in games or []:
        for lane in game.get("gameLens") or []:
            # BOTH STAMPS, because this module's own lanes now carry two.
            # Refusals moved to `pregame` on 2026-09-24 so the board's join can
            # reject them BY STAMP; this filter still read the live stamp only,
            # which silently took `refused` and `refusals_by_reason` to zero.
            # That is the precise failure the docstring above forbids -- "a zero
            # without one is not a result" -- and it would have reported a
            # healthy, fully-refusing slate as a slate with nothing to refuse.
            if lane.get("source") not in (LIVE_RESIM_LENS_SOURCE, PREGAME_LENS_SOURCE):
                continue
            if lane.get("ok"):
                resimmed += 1
            else:
                reason = str((lane.get("refusal") or {}).get("reason") or "unknown")
                reasons[reason] = reasons.get(reason, 0) + 1
    return {
        "games": len(games or []),
        "live_resimmed": resimmed,
        "refused": sum(reasons.values()),
        "refusals_by_reason": reasons,
        "enabled": nfl_live_resim_enabled(),
    }


# ---------------------------------------------------------------------------
# THE SNAPSHOT HALF. Added 2026-09-07 after lane `soccer-unfed-inputs` went to
# write the worker tick and found this producer had only two of the five things
# `_run_ncaaf_live_resim_tick` calls. These three are the missing ones.
#
# THEY LIVE HERE AND NOT IN THE TICK, deliberately. The snapshot SHAPE and its
# validator are the contract `live_lens_loop` reads, so putting them in the
# worker would leave that contract in two places and let a lane-shape change
# silently disagree with the validator meant to catch exactly that. Same reason
# the season pull moved into the sweep rather than into a caller: one owner per
# invariant.
# ---------------------------------------------------------------------------

DEFAULT_BUDGET_SECONDS = 90.0


def default_budget_seconds() -> float:
    raw = str(os.environ.get("SYNDICATE_NFL_LIVE_RESIM_BUDGET_SECONDS") or "").strip()
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_BUDGET_SECONDS
    return value if 1.0 <= value <= 600.0 else DEFAULT_BUDGET_SECONDS


def live_lens_snapshot_path(data_root: Any) -> Any:
    """Where the join reads. The same route every other sport's live lens takes.

    `data/live/nfl_live_lens.json` is NOT date-scoped and does not need to be:
    `refresh_state_store.write_json_file` routes `data/live/` to the KEYVALUE
    backend on Render, so it reaches the web service through Redis rather than
    through `pull_hot_artifacts`, whose `*<date>*` glob would never match an
    undated filename. `mlb_live_lens.json`, `wnba_live_lens.json` and
    `ncaaf_live_lens.json` all take this route.

    Putting NFL anywhere else would make it the one sport the join cannot see,
    and the symptom would be indistinguishable from "the producer never ran" --
    which is the ambiguity this whole lane exists to remove.
    """
    from pathlib import Path

    # `nfl_live_resim.json`, NOT `nfl_live_lens.json`. Those were the same file
    # until 2026-09-24, which made this module and `nfl/live_lens.py` two
    # producers writing ONE Redis key from two services on a ~60s cadence --
    # last write wins, and the pregame writer overwriting this one is `#340`
    # arriving by race. It was latent only because the flag defaulted OFF.
    #
    # NOT resolved the `ncaaf` way (drop nfl from the lens loop and let the
    # re-sim own the file): `nfl/live_lens.py:_load_live_lens_snapshot` READS
    # that path for the live-lens PAGE and validates `cards`/`rank_cards`/
    # `season`/`week`, which this snapshot does not carry. The page would fall
    # through to rebuilding from cards ON THE WEB REQUEST PATH -- the one thing
    # the runtime split forbids. So the two producers get two paths, and
    # `board_enrichment._LIVE_GAMELINE_SNAPSHOT_PATHS` points the board here.
    return Path(data_root) / "live" / "nfl_live_resim.json"


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


def live_state_from_row(
    row: Any, *, away_team: str, home_team: str
) -> "NflLiveGameState | NflResimRefusal":
    """Build a resumable state from an already-normalised live-state mapping.

    DELIBERATELY NOT AN ESPN PARSER. `nfl/live_game_state.py` already owns the
    ESPN shape, and the survey that scoped this work flagged that NFL's
    `situation` payload has never been checked against the shape NCAAF's
    transform assumes. Rather than guess at it, this takes explicit fields and
    REFUSES BY NAME when they are absent -- so a payload mismatch surfaces as
    `incomplete_live_state` naming the missing key, instead of a confident state
    assembled out of defaults.
    """
    if not isinstance(row, Mapping):
        return NflResimRefusal("no_live_state", "no live row matched this game")
    status = str(row.get("state") or row.get("status") or "").strip().lower()
    if status in {"final", "post", "postgame"}:
        return NflResimRefusal("game_final", f"state={status!r}")
    if status not in {"live", "in", "in_progress", "inprogress"}:
        return NflResimRefusal("game_not_in_progress", f"state={status!r}")

    missing = [k for k in ("period", "clock_seconds", "home_score", "away_score")
               if row.get(k) is None]
    if missing:
        return NflResimRefusal("incomplete_live_state", f"missing {','.join(missing)}")
    try:
        period = int(row["period"])
        clock_seconds = int(row["clock_seconds"])
        home_score = int(row["home_score"])
        away_score = int(row["away_score"])
    except (TypeError, ValueError) as exc:
        return NflResimRefusal("incomplete_live_state", type(exc).__name__)
    if period < 1:
        return NflResimRefusal("no_period", f"period={period}")

    owner = row.get("possession_owner")
    owner = str(owner).strip().lower() if owner is not None else None
    if owner not in {"home", "away"}:
        owner = None
    return NflLiveGameState(
        away_team=away_team,
        home_team=home_team,
        period=period,
        clock_seconds=clock_seconds,
        home_score=home_score,
        away_score=away_score,
        down=int(row.get("down") or 1),
        distance=int(row.get("distance") or 10),
        field_position=int(row.get("field_position") or 25),
        possession_owner=owner,
    )


# How close to the end of a quarter a tick must land for its box to count as a
# BOUNDARY observation. A tick can miss 0:00 entirely, so this is a window
# rather than an instant, and the actual clock is recorded with the row so the
# fit can filter rather than assume. First capture per (event, boundary) wins --
# `record_quarter_snapshot` is idempotent, which is what makes a liberal window
# safe.
PROP_CAPTURE_CLOCK_SECONDS = 120


def _maybe_capture_prop_snapshot(row: Any, resolved: Any, *, date_str: str) -> str:
    """Persist one per-quarter player box, if this game is at a boundary.

    READS THE RAW ROW, NOT THE PARSED SIM STATE, and that distinction cost a
    live slate on 2026-09-27. The first version gated on
    `isinstance(resolved, NflLiveGameState)` -- i.e. on the game being
    SIMULATABLE. But `live_state_from_row` refuses a game that is not "in
    progress", and **a game at a quarter boundary is in a BREAK**: measured at
    22:07Z, LV@NO sat at `Q2 0:00` while the tick reported `live_resimmed 3`
    against 4 live games on the board. So the capture returned silently at
    exactly the moments it exists for, and halftime -- the longest and most
    reliably observable boundary of the three -- was missed every time.

    A game at halftime has already produced the Q2 production this is
    collecting. Whether the re-sim can resume from it is a different question
    and not this one's business.

    WHY THIS HOOK AND NOT THE BOX FETCHER. `nfl_player_box_index` is called only
    from the WEB blueprint, in a request path: it would write to a disk the
    worker cannot read, and only when somebody loaded the cards page. A
    collector that depends on browsing is not a collector.

    COST IS BOUNDED (`#241`): one ESPN summary per game per BOUNDARY, about
    three across a whole game, and the idempotence marker makes the repeats a
    120-second window produces cost a single `exists()`.

    Never raises: a capture must not cost the tick its snapshot.
    """
    try:
        # BEFORE EVERY EARLY RETURN BELOW, and that placement is the whole
        # point. The sweep recovers captures written before the push existed,
        # and gating it on a SUCCESSFUL capture would make the recovery depend
        # on the very thing it exists to recover from. MEASURED 2026-09-28: this
        # tick runs every ~5 min returning `no_period_or_clock=16`, while the
        # next capturable boundary was ~9.5 h away (one game, kickoff 00:15Z) --
        # so from `record_quarter_snapshot` the sweep would have waited 9.5 h to
        # publish a file that was already sitting on disk.
        #
        # It is once-per-process and self-guarding, so this costs one directory
        # listing per boot, not one per tick (`#241`).
        from syndicate.features.nfl.live_prop_capture import publish_pending_captures

        publish_pending_captures()

        if not isinstance(row, Mapping):
            return "no_row"
        period_raw = row.get("period")
        clock_raw = row.get("clock_seconds")
        if period_raw is None or clock_raw is None:
            return "no_period_or_clock"
        period, clock = int(period_raw), int(clock_raw)
        if period not in (1, 2, 3):
            return "period_not_capturable"
        if clock > PROP_CAPTURE_CLOCK_SECONDS:
            return "outside_window"
        # A FINAL game is not at a boundary worth capturing: Q4's end is the
        # final box, which is not lossy and is already fetched elsewhere.
        if str(row.get("state") or "").strip().lower() == "final":
            return "final"

        event_id = str(row.get("event_id") or "").strip()
        if not event_id:
            print("[nfl_live_resim] PROP_CAPTURE_SKIPPED reason=no_event_id "
                  f"period={period} clock={clock}", flush=True)
            return "no_event_id"

        from syndicate.features.nfl.live_prop_capture import (
            capture_enabled,
            default_capture_dir,
            record_quarter_snapshot,
        )

        if not capture_enabled():
            return "disabled"
        from syndicate.features.nfl.live_player_box import fetch_player_stat_rows

        rows = fetch_player_stat_rows(event_id)
        if not rows:
            print("[nfl_live_resim] PROP_CAPTURE_SKIPPED reason=no_player_rows "
                  f"event={event_id} period={period}", flush=True)
            return "no_player_rows"
        # THE RETURN VALUE IS CHECKED. Reporting "captured" because the writer
        # was CALLED is a success signal that is not one -- measured 01:44:39Z,
        # the tick logged `captured=1` while every row had been dropped on a
        # field-name mismatch and nothing reached disk.
        written = record_quarter_snapshot(
            default_capture_dir().parent,
            event_id=event_id,
            period=period,
            date_str=date_str,
            player_rows=rows,
            home_score=row.get("home_score"),
            away_score=row.get("away_score"),
            clock_seconds=clock,
        )
        if not written:
            print("[nfl_live_resim] PROP_CAPTURE_SKIPPED reason=wrote_nothing "
                  f"event={event_id} period={period} box_rows={len(rows)}", flush=True)
            return "wrote_nothing"
        return "captured"
    except Exception as exc:  # noqa: BLE001
        print(f"[nfl_live_resim] PROP_CAPTURE_FAILED {type(exc).__name__}: {exc}", flush=True)
        return "failed"


def build_live_lens_snapshot(
    date_str: str,
    *,
    games: Any,
    live_index: Mapping[str, Mapping[str, Any]],
    ratings: Mapping[str, Any],
    sims: int | None = None,
    budget_seconds: float | None = None,
    now: Any = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """One entry per game, one lens lane per entry. Never raises.

    INPUTS ARE INJECTED, and that is deliberate rather than lazy. The week's
    games, the live index and the ratings each have a different owner and a
    different failure mode, and a function that fetched all three itself could
    not be tested without all three -- which is how a producer ships inert.

    THE BUDGET IS A REFUSAL, NOT A TIMEOUT. Worker periodic work is never free
    (`#241` restarted production in a loop). Games are simulated CHEAPEST-FIRST,
    because cost falls sharply with time remaining, so the budget buys the most
    games it can -- and every game it could not reach carries
    `tick_budget_exhausted` BY NAME rather than vanishing into a silently short
    slate. A short slate and a refused slate look identical from the board.

    WHAT THIS DOES NOT DO: it does not bypass `resim_live_game`, so the flag and
    the `UNINFORMATIVE_BAND` refusal apply to every game here. A snapshot built
    with the flag off is all refusals, by design, and `coverage` says so.
    """
    try:
        from syndicate.features.shared.request_path_guard import (
            refuse_if_compute_in_request_path,
        )

        refuse_if_compute_in_request_path("nfl_live_resim_snapshot")
    except ImportError:  # pragma: no cover - the guard is optional under pytest
        pass

    n_sims = int(sims or default_sims())
    budget = float(budget_seconds if budget_seconds is not None else default_budget_seconds())
    generated_at = str(now or datetime.now(timezone.utc).isoformat())

    # ONE LINE PER TICK, NOT ONE PER GAME. Every early return in the capture was
    # silent, so "no game was at a boundary" and "the capture is broken" were the
    # SAME observation. Measured 2026-09-27: the tick ran 8 times through a Q3
    # window with zero lines of any kind, and nothing could distinguish a missed
    # 120 s window from a third bug. A tally names every branch, once per tick.
    _capture_tally: dict[str, int] = {}

    prepared: list[tuple[float, dict[str, str], Any]] = []
    for game in games or ():
        if not isinstance(game, Mapping):
            continue
        away_team = str(game.get("away_team") or "").strip()
        home_team = str(game.get("home_team") or "").strip()
        if not away_team or not home_team:
            continue
        live_row = live_index.get(str(game.get("live_key") or ""))
        resolved = live_state_from_row(
            live_row, away_team=away_team, home_team=home_team,
        )
        # CAPTURE BEFORE ANY REFUSAL SHORT-CIRCUITS. A game whose re-sim is
        # refused (degenerate ratings, budget exhausted) still produced real
        # player production, and that observation is worth exactly as much to a
        # prop fit as one from a game that simulated cleanly.
        _cap = _maybe_capture_prop_snapshot(live_row, resolved, date_str=str(date_str))
        _capture_tally[_cap] = _capture_tally.get(_cap, 0) + 1
        remaining = (
            (4 - resolved.period) * 900 + resolved.clock_seconds
            if isinstance(resolved, NflLiveGameState) else -1.0
        )
        prepared.append((float(remaining),
                         {"away_team": away_team, "home_team": home_team}, resolved))
    prepared.sort(key=lambda item: item[0])

    if _capture_tally:
        print("[nfl_live_resim] PROP_CAPTURE_TICK "
              + " ".join(f"{k}={v}" for k, v in sorted(_capture_tally.items())), flush=True)

    started = time.monotonic()
    out_games: list[dict[str, Any]] = []
    for _remaining, names, resolved in prepared:
        state: Any = None
        if isinstance(resolved, NflResimRefusal):
            result: Any = resolved
        elif time.monotonic() - started >= budget:
            state = resolved
            result = NflResimRefusal(
                "tick_budget_exhausted",
                f"the {budget:.0f}s budget was spent before this game; NOT a sim "
                f"failure and NOT an absent game",
            )
        else:
            state = resolved
            home_off, home_def = ratings.get(names["home_team"], (0.0, 0.0))
            away_off, away_def = ratings.get(names["away_team"], (0.0, 0.0))
            result = resim_live_game(
                state,
                home_offense=float(home_off), home_defense=float(home_def),
                away_offense=float(away_off), away_defense=float(away_def),
                sims=n_sims, env=env,
            )
        # FULL CLUB NAMES, because that is what the board's join keys on. The
        # games come from the smartsim2 projection CSV, which carries TRI-CODES
        # ("phi" / "chi"), while every grid row carries "Philadelphia Eagles" /
        # "Chicago Bears" and `live_gameline_join._norm_team` compares them
        # EXACTLY -- measured 2026-09-28 against the week-3 artifact and the
        # 09-27 grid: 0 of 16 pairs matched. The codes stay beside the names
        # (and stay the key into `ratings` / `live_index` above, which are
        # themselves code-keyed). An unresolvable code keeps the code, so it
        # misses by name in the join's own counters rather than vanishing here.
        out_games.append({
            "away_name": canonical_team("nfl", names["away_team"]) or names["away_team"],
            "home_name": canonical_team("nfl", names["home_team"]) or names["home_team"],
            "away_code": names["away_team"],
            "home_code": names["home_team"],
            "gameLens": build_game_lens(state, result, live_state_as_of=generated_at),
        })

    coverage = summarise(out_games)
    coverage["budget_seconds"] = budget
    coverage["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return {
        "sport": "nfl",
        "date": str(date_str or ""),
        "generated_at": generated_at,
        "games": out_games,
        "coverage": coverage,
    }
