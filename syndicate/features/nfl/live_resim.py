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

LIVE_RESIM_LENS_SOURCE = "live_resim"
PREGAME_LENS_SOURCE = "pregame"
DEFAULT_SIMS = 120
MAX_RESUMABLE_PERIOD = 4

# THE NUMBER THIS MODULE REFUSES BELOW, and where it comes from.
#
# `nfl-rating-units` measured NFL's across-game `margin_mean` stdev at 2.16
# points against NCAAF's 15.37 on a comparable slate, with a market spread range
# of ~14. A rating spread that cannot move the simulated margin cannot move the
# win probability either, so every game converges on ~0.5 and the engine is
# reporting its prior rather than its opinion.
#
# 0.5 rating points is deliberately a LOW bar -- it is not "the ratings are
# good", it is "the ratings are not literally identical". A working rating
# clears it by an order of magnitude; the degenerate case does not clear it at
# all. Set low on purpose: this is a floor against publishing noise, not a
# quality gate, and a quality gate is `nfl-rating-units`' to write.
RATING_SEPARATION_FLOOR = 0.5


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

    started = time.time()
    home_wins = 0
    ties = 0
    margins: list[int] = []
    totals: list[int] = []
    ran = 0
    per_plan = max(1, n // len(plans))
    for owner, field_position in plans:
        for seed in range(1, per_plan + 1):
            try:
                out = simulate_game(
                    SmartSim2SimulationInput(
                        seed=seed,
                        initial_possession_owner=owner,
                        initial_field_position=field_position,
                        **base,
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
    return {
        "model_home_win_prob": round(smoothed, 6),
        "model_home_win_prob_raw": round(raw, 6),
        "point_estimator": "agresti_coull",
        "sims_run": ran,
        "margin_mean": round(sum(margins) / ran, 4),
        "total_mean": round(sum(totals) / ran, 4),
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
        return [{
            "source": LIVE_RESIM_LENS_SOURCE,
            "ok": False,
            "as_of": as_of,
            "refusal": result.to_dict(),
        }]
    lane = {
        "source": LIVE_RESIM_LENS_SOURCE,
        "ok": True,
        "as_of": as_of,
        **result,
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
            if lane.get("source") != LIVE_RESIM_LENS_SOURCE:
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
