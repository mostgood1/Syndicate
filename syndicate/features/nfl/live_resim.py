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
RATING_SEPARATION_FLOOR = 0.5

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

    return Path(data_root) / "live" / "nfl_live_lens.json"


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

    prepared: list[tuple[float, dict[str, str], Any]] = []
    for game in games or ():
        if not isinstance(game, Mapping):
            continue
        away_team = str(game.get("away_team") or "").strip()
        home_team = str(game.get("home_team") or "").strip()
        if not away_team or not home_team:
            continue
        resolved = live_state_from_row(
            live_index.get(str(game.get("live_key") or "")),
            away_team=away_team, home_team=home_team,
        )
        remaining = (
            (4 - resolved.period) * 900 + resolved.clock_seconds
            if isinstance(resolved, NflLiveGameState) else -1.0
        )
        prepared.append((float(remaining),
                         {"away_team": away_team, "home_team": home_team}, resolved))
    prepared.sort(key=lambda item: item[0])

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
        out_games.append({
            "away_name": names["away_team"],
            "home_name": names["home_team"],
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
