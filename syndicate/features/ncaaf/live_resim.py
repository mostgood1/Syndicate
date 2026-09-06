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

ONE MARKET FAMILY: the moneyline. The lane carries `modelHomeWinProb` and
`simsRun`, which is exactly what `live_gameline_join.price_moneyline` prices,
and `prob_std_err` derives the interval from `simsRun` the same way it does for
MLB. Nothing here relaxes `PRICEABLE_SIGMA`.

THE REST-OF-GAME MARGIN AND TOTAL DISTRIBUTIONS ARE **NOT** PUBLISHED, though
this re-sim has them in hand. `live_gameline_join` would price totals and
spreads off `marginDist`/`totalRunsDist` the moment they appeared, and no NCAAF
live totals estimator has ever been graded. `#499` is the precedent in the other
direction: WNBA totals only became priceable after a 249-game / 23,712-sample
backtest produced a measured 0.150 interval. Publishing a distribution here
would open pricing on the strength of a sim count alone. The projection block
carries the live MEANS for display and nothing a pricer reads.

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

    return {
        "home_win_prob": round(home_win_prob, 6),
        "sims_run": ran,
        "home_margin_mean": round(sum(margins) / ran, 3),
        "total_mean": round(sum(totals) / ran, 3),
        "possession_unknown": possession_unknown,
        "ties": ties,
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
        # DISPLAY ONLY. `live_gameline_join` reads `projection.total` and
        # `projection.homeMargin` for the row's display fields and prices
        # NEITHER: totals and spreads are priced from `totalRunsDist` /
        # `marginDist`, which this lane deliberately does not carry (see the
        # module docstring).
        "projection": {
            "homeMargin": result["home_margin_mean"],
            "total": result["total_mean"],
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
        # Remaining regulation seconds: the cost proxy, and it is a good one --
        # 154 ms/sim with a full game left, 0.7 ms with 15 seconds left.
        if isinstance(resolved, NcaafLiveGameState):
            remaining = (4 - resolved.period) * 900 + resolved.clock_seconds
        else:
            remaining = -1.0
        prepared.append((float(remaining), {"away_team": away_team, "home_team": home_team}, resolved))

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
        out_games.append({
            "away_name": names["away_team"],
            "home_name": names["home_team"],
            "gameLens": build_game_lens(
                state, result, live_state_as_of=state.as_of if state is not None else generated_at
            ),
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
