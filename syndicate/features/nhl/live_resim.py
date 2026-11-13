"""NHL LIVE RE-SIM: hockeysim restarted from the current game state.

    live_state_from_score_row(row)        -> NhlLiveGameState | NhlResimRefusal
    resim_live_game(features, state)      -> dict (the lens lane) | NhlResimRefusal
    build_live_lens_snapshot(date_str)    -> the shared `gameLens` snapshot

--------------------------------------------------------------------------
WHY THIS EXISTS
--------------------------------------------------------------------------

NHL has a calibrated, Syndicate-owned engine (`sim_engine/hockeysim`) and no
live tier at all. `nhl/live_lens.py` overlays a scoreboard on the PREGAME
`sim` payload and recomputes nothing -- so a team down 1-3 in the third carries
the win probability it had at puck drop. NHL is also absent from
`_LIVE_LENS_SPORTS`, so no loop even builds it.

The board is right to suppress an edge on those rows (`#340`): a pregame model
priced against a re-priced market yields the score, not an edge. **So the fix
is never to stop suppressing. It is to produce a probability that knows the
score.**

--------------------------------------------------------------------------
THE ENGINE COULD ALWAYS DO THIS. ITS ENTRYPOINT COULD NOT.
--------------------------------------------------------------------------

`GameState` has always carried `period`, `clock` and per-team `score`
(`state.py`), and `simulate_period_with_lines` has always taken
`period_seconds` -- already exercised with a non-default value by the overtime
call. `simulate_with_lineups` simply never passed them: it hard-coded a 0-0
state and looped `for pd in range(self.cfg.periods)` with a full period every
time.

MEASURED BEFORE ANY OF THIS MODULE WAS WRITTEN, running the production path
directly from a mid-game state (n=300 shared seeds, rates held fixed):

    pregame entrypoint                   p(home) 0.4867   14.94 ms/sim
    resumed P1 20:00, 0-0  (identity)    p(home) 0.4867   14.53 ms/sim
    resumed P2 10:00, level 1-1          p(home) 0.4700    8.52 ms/sim
    resumed P3 10:00, home -1 (1-2)      p(home) 0.1867    3.44 ms/sim
    resumed P3 05:00, home -2 (1-3)      p(home) 0.0233    2.05 ms/sim
    resumed P3 05:00, home +2 (3-1)      p(home) 0.9867    1.89 ms/sim
    resumed P3 00:30, home +3 (4-1)      p(home) 1.0000    1.07 ms/sim
    resumed P3 00:30, home -3 (1-4)      p(home) 0.0000    1.18 ms/sim

The second line is the one that matters: resuming at the opening faceoff is not
an approximation of the pregame sim, it IS the pregame sim, bit-identical seed
for seed. And the cost FALLS as the game runs -- 14.94 ms at puck drop, 1.07 ms
late in the third -- so a live re-sim is always cheaper than the pregame sim it
updates. That is what makes a per-tick budget affordable on the 2 GB
live-odds-worker.

--------------------------------------------------------------------------
WHAT IS PUBLISHED, AND WHAT IS DELIBERATELY NOT
--------------------------------------------------------------------------

ONE MARKET FAMILY: the moneyline. The lane carries `modelHomeWinProb` and
`simsRun`, which is exactly what `live_gameline_join.price_moneyline` prices,
and `prob_std_err` derives the interval from `simsRun`. Nothing here relaxes
`PRICEABLE_SIGMA`.

THE REST-OF-GAME MARGIN AND TOTAL DISTRIBUTIONS ARE **NOT** PUBLISHED FOR
PRICING, though this re-sim has them in hand. `live_gameline_join` would price
totals and puck lines off `totalRunsDist` / `marginDist` the moment they
appeared, and **no NHL live totals or puck-line estimator has ever been
graded**. `#499` is the precedent in the other direction: WNBA totals became
priceable only after a 249-game backtest produced a measured interval. The
projection block carries live MEANS for display and nothing a pricer reads.

THE MARGIN HISTOGRAM RIDES AS `displayMarginDist`, FOR THE LIVE COLUMN ONLY
(`#773`, lane nhl-live-puckline-display, 2026-11-10). Served 2026-11-09 NYR@EDM:
moneyline 1 of 1 and totals 2 of 2 showed a live number, the puck line 0 of 1,
refused `live_resim_published_no_distribution_for_this_market`. The join reads
this key ONLY into `live_display_block`, which shows P(home covers) beside the
row and prices nothing: the row is refused `live_margin_published_for_display_only`,
with no edge. The same 200 sims as the moneyline; the sim is unchanged. Pricing
a puck line needs this histogram GRADED first (the pregame puck line already
ran ~4 pts under the fair on home -1.5 in 9 of 10, 2026-10-15, a possibly too
narrow margin), and then publishing it as `marginDist`. The total histogram is
not published at all: the totals row's live number is the mean, and nothing
would read a display-only total.

**NO FALLBACK TO THE PREGAME PROBABILITY, EVER** (`#414`). Every path that
cannot produce a live probability returns an `NhlResimRefusal` with a named
reason, and a refusal publishes a lane stamped `pregame_only` -- a stamp
`LIVE_LENS_SOURCES_BY_SPORT` must not accept for nhl -- so the join withholds
and says why. A refused game is never a game priced off its pregame number.

**PER-PLAYER STATS FROM THIS PATH ARE REST-OF-GAME ONLY** and no prop is
published from them. `simulate_with_lineups`' resume docstring says why: the
banked boxscore is not replayed.

--------------------------------------------------------------------------
RUNS ON A WORKER. NEVER IN A REQUEST HANDLER.
--------------------------------------------------------------------------

`build_live_lens_snapshot` is a simulation. It carries
`refuse_if_compute_in_request_path` for the same reason MLB's live-lens
enhancement and NCAAF's re-sim do. The join reads the PUBLISHED snapshot and
never calls anything in this module.

--------------------------------------------------------------------------
THE CLOCK IS THE KNOWN GAP, AND IT IS A REFUSAL RATHER THAN A GUESS
--------------------------------------------------------------------------

`/v1/schedule/<date>` returns `clock: null` on live games -- measured 7 of 7 on
2026-09-22 (`lanes.md`, lane `nhl-compact-card-start-time`). `/v1/score/<date>`
carries a running clock and is what this module reads. When the clock is
missing anyway, this REFUSES (`no_clock`) rather than assuming a period
boundary: assuming full time remaining on a game that is 19 minutes into the
third would publish a confident number about a game that is nearly over.
"""

from __future__ import annotations

import json
import os
import random
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence

# Lane stamps. `live_resim` mirrors NCAAF's, and `pregame_only` is the refusal
# stamp the join must NOT accept -- the pair is what keeps `#414` shut.
LIVE_RESIM_LENS_SOURCE = "live_resim"
PREGAME_LENS_SOURCE = "pregame_only"

# Regulation only; OT/shootout are resolved by the engine from a tied state.
_REGULATION_PERIODS = 3
_PERIOD_SECONDS = 20 * 60

_DEFAULT_SIMS = 200
_DEFAULT_BUDGET_SECONDS = 25.0

# THE LIVE END-GAME (lane nhl-live-endgame-calibration, todo #773, 2026-11-11). A cutoff replay of
# this producer over 284 regular-season games (findings_2026-11-11_nhl_live_puckline_grade.md) found
# the live histogram's one decisive miss: with a ONE-GOAL LEAD LATE IN THE THIRD the leader went on to
# win by 2+ in 0.43 of games (P3 05:00, n=90) and 0.50 (P3 10:00, n=93) against the model's 0.18 /
# 0.26, and 98 of the 229 goals in the last 5 minutes were into an empty net. The event engine's only
# end-game logic is `engine.py`'s last-3-minute heuristic. The PREGAME game-market path closes the same
# gap post-sim with `NHL_GAME_MARKET_CALIBRATION['empty_net_p']` 0.3006, but that number was fit on a
# plain per-period Poisson sim with NO end-game logic at all, so it is not this engine's number (and
# that path's `tie_weight` would make this one worse: the live engine already gives the trailer slightly
# too many ties). This applies the SAME MECHANISM -- a sim that finishes REGULATION with a one-goal lead
# gets one more goal for the leader with probability p -- with p FIT ON THIS ENGINE by walk-forward
# replay. `ramp_seconds` is the regulation time a one-goal margin needs to carry its FULL empty-net
# chance: a sim whose margin last changed with less regulation left than that (the trailer cut it to
# one, or the leader went ahead, with 30 s to go -- there is barely time to pull the goalie) gets p
# scaled linearly by the time it had. That time is read off the sim's OWN goal events
# (`seconds_left_at_last_goal`); a sim with no goal after the cutoff carries the cutoff's regulation
# time. Applied post-sim with its own RNG, so the engine's draws are untouched and `off` reproduces the
# old histogram seed for seed. OT/shootout sims are never touched (their margin is the one-goal OT/SO
# result).
# THE MARGIN ONLY, NOT THE TOTAL. The same replay measured the live total mean already HIGH early
# (+0.81 goals at puck drop, +0.34 at P2 10:00; the event engine's scoring rate, the issue the pregame
# path's `regulation_scale` corrects), and adding these goals would push it +0.11 higher. A mechanism
# goes in with a re-fit of what absorbs it (model_engine_standard 4.4); the total's level is set by that
# separately-biased rate, so the total waits for its own fit.
# FIT (findings_2026-11-11_nhl_live_endgame_calibration.md): 284 games / 41 dates, 8 cutoffs, the
# board's +-1.5 Brier; walk-forward fits p 0.35-0.55, ramp 90-120 s; out of sample (185 games) the late
# one-goal states went from +0.20..+0.28 under to within +-0.035. Full-sample fit below.
# Off switch: SYNDICATE_NHL_LIVE_ENDGAME_CALIBRATION=off.
NHL_LIVE_ENDGAME_CALIBRATION: dict[str, float] = {
    "empty_net_p": 0.38,
    "ramp_seconds": 90.0,
}
LEGACY_LIVE_ENDGAME: dict[str, float] = {"empty_net_p": 0.0, "ramp_seconds": 0.0}
LIVE_ENDGAME_ENV = "SYNDICATE_NHL_LIVE_ENDGAME_CALIBRATION"
# `regulation_one_goal_seconds` bins: fine enough for any ramp, capped well past one.
_ONE_GOAL_SECONDS_BIN = 5
_ONE_GOAL_SECONDS_CAP = 600

# THE LIVE SCORING LEVEL (lane nhl-live-total-calibration, todo #773, 2026-11-13). The same cutoff replay
# measured the live TOTAL running high early: model mean minus the actual final total +0.81 goals at puck
# drop, +0.34 at P2 10:00, -0.20 at P3 05:00 (185 games out of sample). The engine's per-shot goal chance
# is `goals_per_60 / shots_per_60` (`engine.py`), and `goals_per_60` is the projection's FULL-GAME rate --
# OT goals and shootout credits included -- used as a REGULATION rate: exactly the issue the pregame
# game-market path corrects with `adapters.NHL_GAME_MARKET_CALIBRATION['regulation_scale']` (0.9398, fit
# on that path's Poisson sim; this engine's level is its own, so it is fit on THIS engine).
# TWO WAYS TO LOWER IT WERE MEASURED, on the same replayed states (the findings file):
#   `goal_scale` multiplies both teams' `goals_per_60` before the sims run: the ENGINE scores less, so the
#     total, the margin and the moneyline all move. It fixed the early total, and made the +-1.5 and the
#     moneyline Brier slightly WORSE (within noise, but the moneyline is a number the join can price): the
#     margin was already too NARROW, and fewer goals narrow it further.
#   `total_keep` thins the TOTAL only: each sim's REGULAR-PLAY goals (regulation goals after the live state
#     with more than `total_keep_late_seconds` of regulation left) are kept with probability q, post-sim, on
#     their own RNG. The engine's draws are untouched, so the margin, the puck line and the moneyline are
#     today's EXACTLY, and the total's fix is the same (out-of-sample CRPS -0.0142 vs -0.0140). The late
#     window is spared because the engine's LATE play is not high: the keep that zeroes the bias was ~0.87
#     with 20+ minutes left and ~1.0 inside the last five. THIS is what production runs; `goal_scale` stays
#     1.0 and is the replay's knob.
# THE END-GAME'S GOALS COUNT IN THE TOTAL WHEN THIS IS ON (`count_endgame_in_total`), added after the
# thinning (they are not the engine's goals). Real empty-net goals are in every real final; the end-game
# was kept out of the total only because the total's level was wrong (the 2026-11-11 note above), and
# this is the re-fit that note was waiting for. Off, the total is today's: the raw engine total, no
# thinning, the end-game out of it.
# Off switch: SYNDICATE_NHL_LIVE_SCORING_CALIBRATION=off (legacy: scale 1.0, keep 1.0, end-game out).
# FIT (findings_2026-11-13_nhl_live_total_calibration.md): 301 games / 43 dates (2026-10-01..11-12), 8 cutoffs,
# mean CRPS of the total over (window 0..600 s) x (keep 0.70..1.00). Walk-forward: keep 0.82-0.85, window
# 120-240 s on every out-of-sample date; out of sample (202 games) the late window beats one keep for the whole
# game by CRPS -0.0025 [-0.0045, -0.0007]. Full-sample fit below: every cutoff's bias within +-0.08 goals
# (today +0.87 at puck drop), pooled CRPS 0.6950 -> 0.6692.
NHL_LIVE_SCORING_CALIBRATION: dict[str, Any] = {
    "goal_scale": 1.0,
    "total_keep": 0.85,
    "total_keep_late_seconds": 240.0,
    "count_endgame_in_total": True,
}
LEGACY_LIVE_SCORING: dict[str, Any] = {"goal_scale": 1.0, "total_keep": 1.0, "total_keep_late_seconds": 0.0,
                                       "count_endgame_in_total": False}
LIVE_SCORING_ENV = "SYNDICATE_NHL_LIVE_SCORING_CALIBRATION"
# A value outside these ranges is a typo, not a fit: refuse it (read as 1.0) rather than run it.
_GOAL_SCALE_BOUNDS = (0.5, 1.5)
_TOTAL_KEEP_BOUNDS = (0.5, 1.0)


# OVERTIME AS IT IS PLAYED (lane nhl-live-overtime, todo #773, 2026-11-13). The engine used to play OT as one
# whole 5:00 segment and sum its goals, and a state resumed IN OT got a fresh 5:00 whatever the clock showed:
# ~10% of sims that reached OT ended 2-3 goals past the tie (a stub P4 2-2 state: 31 of 300), which no
# regular-season game can. On, OT is sudden death on the clock shown (`engine.simulate_with_lineups(
# ot_sudden_death=True)`): every sim that reaches OT ends exactly one past the tie, by an OT goal or the
# shootout credit. A rule, not a fit: nothing here has a parameter. Sims that end in regulation are untouched
# seed for seed (OT comes last, and the cut draws nothing).
# Off switch: SYNDICATE_NHL_LIVE_OVERTIME=off (the old OT).
LIVE_OVERTIME_ENV = "SYNDICATE_NHL_LIVE_OVERTIME"


def live_overtime_sudden_death() -> bool:
    """Whether production plays OT as sudden death: on unless the env switch says off."""
    raw = str(os.environ.get(LIVE_OVERTIME_ENV) or "").strip().lower()
    return raw not in {"off", "0", "false", "legacy"}


def live_endgame_calibration() -> dict[str, float]:
    """The end-game production uses: the fitted one unless the env switch says off."""
    raw = str(os.environ.get(LIVE_ENDGAME_ENV) or "").strip().lower()
    return dict(LEGACY_LIVE_ENDGAME if raw in {"off", "0", "false", "legacy"} else NHL_LIVE_ENDGAME_CALIBRATION)


def live_scoring_calibration() -> dict[str, Any]:
    """The scoring level production uses: the fitted one unless the env switch says off."""
    raw = str(os.environ.get(LIVE_SCORING_ENV) or "").strip().lower()
    return dict(LEGACY_LIVE_SCORING if raw in {"off", "0", "false", "legacy"} else NHL_LIVE_SCORING_CALIBRATION)


def scoring_goal_scale(calibration: Mapping[str, Any]) -> float:
    """The `goal_scale` to run: 1.0 when absent, unreadable, or outside `_GOAL_SCALE_BOUNDS`."""
    try:
        scale = float(calibration.get("goal_scale", 1.0))
    except (TypeError, ValueError, AttributeError):
        return 1.0
    lo, hi = _GOAL_SCALE_BOUNDS
    return scale if (scale == scale and lo <= scale <= hi) else 1.0


def scoring_total_keep(calibration: Mapping[str, Any]) -> float:
    """The `total_keep` to run: 1.0 when absent, unreadable, or outside `_TOTAL_KEEP_BOUNDS`."""
    try:
        keep = float(calibration.get("total_keep", 1.0))
    except (TypeError, ValueError, AttributeError):
        return 1.0
    lo, hi = _TOTAL_KEEP_BOUNDS
    return keep if (keep == keep and lo <= keep <= hi) else 1.0


def scoring_late_seconds(calibration: Mapping[str, Any]) -> float:
    """`total_keep_late_seconds`: 0 when absent or unreadable, clipped to one period."""
    try:
        late = float(calibration.get("total_keep_late_seconds", 0.0) or 0.0)
    except (TypeError, ValueError, AttributeError):
        return 0.0
    return min(float(_PERIOD_SECONDS), max(0.0, late)) if late == late else 0.0


def thin_total(raw_total: int, goal_seconds_left: Sequence[float], keep: float, late_seconds: float,
               rng: random.Random) -> int:
    """The raw total less the REGULAR-PLAY goals not kept: each regulation goal after the live state scored with
    more than `late_seconds` of regulation left is kept with probability `keep` (one draw per such goal, none
    at all when keep is 1, so the stream is untouched). Goals in the last `late_seconds`, OT goals and the
    shootout credit are always kept: the engine's late play is measured about right, its regular play high."""
    if keep >= 1.0:
        return int(raw_total)
    early = sum(1 for s in goal_seconds_left if s > late_seconds)
    return int(raw_total) - sum(1 for _ in range(early) if rng.random() >= keep)


def regulation_seconds_left(period: int, clock_seconds: int) -> int:
    """Regulation seconds left at a 1-based scoreboard state; 0 in overtime."""
    if int(period) > _REGULATION_PERIODS:
        return 0
    return (_REGULATION_PERIODS - int(period)) * _PERIOD_SECONDS + max(0, int(clock_seconds))


def endgame_empty_net_prob(calibration: Mapping[str, Any], *, seconds_left: float) -> float:
    """p for ONE sim whose regulation ended with a one-goal margin that had `seconds_left` of regulation to
    run when it last changed: the full p from `ramp_seconds` up, linear below. 0 when the calibration is off."""
    try:
        p = float(calibration.get("empty_net_p") or 0.0)
        ramp = float(calibration.get("ramp_seconds") or 0.0)
        left = float(seconds_left)
    except (TypeError, ValueError):
        return 0.0
    if not (p > 0.0):
        return 0.0
    p = min(p, 1.0)
    if ramp <= 0.0:
        return p
    return p * max(0.0, min(1.0, left / ramp))


def seconds_left_at_last_goal(events: Any, *, start_period_idx: int, start_seconds: int, default: float) -> float:
    """Regulation seconds left when this sim's LAST regulation goal went in -- the moment its final margin
    was set. `default` (the cutoff's regulation time) when no regulation goal was scored after the cutoff.

    The engine times a goal `t = within + period_idx * T`, where T is THAT period's length: the resumed
    period runs only `start_seconds` (`simulate_with_lineups` passes `period_seconds = resume_seconds_remaining`),
    every later one 1200. So `within = t - period_idx * T`, and the time left is `(T - within)` plus the
    full periods still to come."""
    lefts = regulation_goal_seconds_left(events, start_period_idx=start_period_idx, start_seconds=start_seconds)
    return float(default) if not lefts else min(lefts)


def regulation_goal_seconds_left(events: Any, *, start_period_idx: int, start_seconds: int) -> list[float]:
    """Regulation seconds left at EVERY regulation goal this sim scored after the live state, in event order
    (the clock arithmetic is `seconds_left_at_last_goal`'s). OT goals and the shootout credit are not here."""
    out: list[float] = []
    for event in events or ():
        if getattr(event, "kind", None) != "goal":
            continue
        try:
            pd = int(getattr(event, "period", 0) or 0) - 1
            t = float(getattr(event, "t", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if pd < int(start_period_idx) or pd >= _REGULATION_PERIODS:
            continue
        length = float(start_seconds) if pd == int(start_period_idx) else float(_PERIOD_SECONDS)
        within = t - pd * length
        out.append(max(0.0, length - within) + (_REGULATION_PERIODS - 1 - pd) * _PERIOD_SECONDS)
    return out


def _went_past_regulation(events: Any) -> bool:
    """Did this sim need OT or a shootout? The engine stamps goal events `period = period_idx + 1`
    (so OT is 4) and the shootout credit `period = periods + 1`."""
    for event in events or ():
        if getattr(event, "kind", None) in ("goal", "shootout"):
            try:
                if int(getattr(event, "period", 0) or 0) > _REGULATION_PERIODS:
                    return True
            except (TypeError, ValueError):
                continue
    return False

_SCORE_URL = "https://api-web.nhle.com/v1/score/{date}"
# See `fetch_score_rows`: the endpoint 403s Python's default UA.
_SCORE_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


@dataclass(frozen=True)
class NhlResimRefusal:
    """Why one game could not be re-simulated. `reason` is a stable token."""

    reason: str
    detail: str = ""


@dataclass(frozen=True)
class NhlLiveGameState:
    """A live NHL game, in the terms the engine's resume takes.

    `period` is 1-BASED, as a scoreboard shows it. `runtime`'s resume is
    0-based and this module does the conversion in exactly one place
    (`resim_live_game`), because doing it at the call site is how a resume ends
    up a whole period early with a plausible-looking answer.
    """

    game_pk: str
    home_name: str
    away_name: str
    home_score: int
    away_score: int
    period: int
    clock_seconds: int
    as_of: str


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_clock_seconds(value: Any) -> Optional[int]:
    """`"12:34"` -> 754. Returns None for anything it cannot read.

    NEVER defaults to a full period. See the module docstring: a missing clock
    is a refusal, and turning it into 20:00 would publish a confident number
    about a game that may be seconds from over.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        secs = int(value)
        return secs if secs >= 0 else None
    text = str(value or "").strip()
    if not text or ":" not in text:
        return None
    mm, _, ss = text.partition(":")
    try:
        minutes, seconds = int(mm), int(ss)
    except ValueError:
        return None
    if minutes < 0 or seconds < 0 or seconds >= 60:
        return None
    return minutes * 60 + seconds


def _as_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def team_names_from_score_row(row: Mapping[str, Any]) -> tuple[str, str]:
    """`(away_name, home_name)` from a raw `/v1/score` row, or `("", "")`.

    SHARED BY THE SUCCESS PATH AND THE REFUSAL PATH ON PURPOSE. The join keys on
    team names, so a refusal whose names are formatted even slightly differently
    from a success's is a refusal the board cannot match -- which is the same
    invisibility this module exists to remove, arriving one level lower down.
    One extractor means the two cannot drift.
    """
    if not isinstance(row, Mapping):
        return "", ""

    def _one(side: Any) -> str:
        block = side if isinstance(side, Mapping) else {}
        name = block.get("name")
        value = name.get("default") if isinstance(name, Mapping) else name
        return str(value or "").strip()

    return _one(row.get("awayTeam")), _one(row.get("homeTeam"))


def _published_team_names(row: Mapping[str, Any], by_pk: Mapping[str, Any]) -> tuple[str, str]:
    """`(away_name, home_name)` the snapshot PUBLISHES for one game: the slate features' full names.

    WHY `[2026-11-09, lane nhl-live-resim-slate-root]`. The board joins on full team names compared
    lowercased (`live_gameline_join._norm_team`, "JOINED ON FULL TEAM NAMES, WHICH MATCH EXACTLY"),
    and its NHL rows carry the scoreboard's names -- 'New York Rangers' @ 'Edmonton Oilers'.
    `/v1/score`'s `name.default` is the SHORT name, 'Rangers' @ 'Oilers', so no live NHL game could
    ever be indexed. Measured on the fleet 11-09 ~17:0xZ: served NHL rows ('New York Rangers',
    'Edmonton Oilers') x107, ('Philadelphia Flyers', 'Vancouver Canucks') x99, ('New York Islanders',
    'San Jose Sharks') x96, while the snapshot said ('Rangers', 'Oilers') etc. (first reported by
    lane nhl-nfl-live-prop-actuals).

    The slate features carry the SCOREBOARD's spelling -- the board's own source -- so they match
    where an alias table would not: `canonical_team('nhl', 'Canadiens')` is 'montreal canadiens', but
    the scoreboard and the board say 'Montréal Canadiens'. Keyed by gamePk, so orientation comes from
    the scoreboard row. A game the features do not cover keeps the raw row's names, exactly as before
    (it is refused `no_slate_features` anyway). Both the refusal and the success path call this, so
    the two cannot drift -- the reason `team_names_from_score_row` is shared.
    """
    raw_away, raw_home = team_names_from_score_row(row)
    pk = str(row.get("id") or row.get("gamePk") or "").strip() if isinstance(row, Mapping) else ""
    feats = by_pk.get(pk) if pk else None
    if feats is not None:
        away = str(getattr(getattr(feats, "away", None), "name", "") or "").strip()
        home = str(getattr(getattr(feats, "home", None), "name", "") or "").strip()
        if away and home:
            return away, home
    return raw_away, raw_home


def live_state_from_score_row(row: Mapping[str, Any]) -> NhlLiveGameState | NhlResimRefusal:
    """Read one `/v1/score/<date>` game into a resume state, or refuse by name.

    EVERY REFUSAL IS A NAMED TOKEN, never a None the caller can misread as "no
    games". `build_live_lens_snapshot` publishes the reason on the lane, so a
    zero is diagnosable from the snapshot alone.
    """
    if not isinstance(row, Mapping):
        return NhlResimRefusal("row_not_a_mapping")

    state = str(row.get("gameState") or row.get("gameStatus") or "").strip().upper()
    if state in {"FUT", "PRE", "SCHEDULED"}:
        return NhlResimRefusal("game_not_started", state)
    if state in {"FINAL", "OFF", "OVER"}:
        return NhlResimRefusal("game_final", state)
    if state not in {"LIVE", "CRIT", "IN_PROGRESS"}:
        # UNKNOWN IS NOT LIVE. An unrecognised status must not take the
        # permissive branch -- that is this repo's standing rule, and the cost
        # of being wrong here is a live-stamped number on a finished game.
        return NhlResimRefusal("game_state_unrecognised", state or "<empty>")

    pk = str(row.get("id") or row.get("gamePk") or "").strip()
    if not pk:
        return NhlResimRefusal("no_game_id")

    home = row.get("homeTeam") if isinstance(row.get("homeTeam"), Mapping) else {}
    away = row.get("awayTeam") if isinstance(row.get("awayTeam"), Mapping) else {}
    home_score, away_score = _as_int(home.get("score")), _as_int(away.get("score"))
    if home_score is None or away_score is None:
        return NhlResimRefusal("no_score")

    period_desc = row.get("periodDescriptor")
    period = _as_int(period_desc.get("number")) if isinstance(period_desc, Mapping) else None
    if period is None:
        period = _as_int(row.get("period"))
    if period is None or period < 1:
        return NhlResimRefusal("no_period")

    clock_block = row.get("clock") if isinstance(row.get("clock"), Mapping) else None
    raw_clock = clock_block.get("timeRemaining") if clock_block else row.get("timeRemaining")
    clock_seconds = _parse_clock_seconds(raw_clock)
    if clock_seconds is None:
        # THE KNOWN GAP, refused rather than guessed. `/v1/schedule` returns
        # `clock: null` on live games; `/v1/score` is what this reads, and if
        # even that is absent the game is not resumable this tick.
        return NhlResimRefusal("no_clock", str(raw_clock))

    if clock_block is not None and bool(clock_block.get("inIntermission")):
        # An intermission clock counts DOWN TO THE NEXT PERIOD, not within the
        # current one. Reading it as time-remaining-in-period would shorten the
        # game by up to 20 minutes.
        return NhlResimRefusal("in_intermission")

    away_name, home_name = team_names_from_score_row(row)
    if not home_name or not away_name:
        return NhlResimRefusal("no_team_names")

    return NhlLiveGameState(
        game_pk=pk,
        home_name=home_name,
        away_name=away_name,
        home_score=home_score,
        away_score=away_score,
        period=period,
        clock_seconds=clock_seconds,
        as_of=_utc_now_iso(),
    )


def resim_live_game(
    features: Any,
    state: NhlLiveGameState,
    *,
    sims: int = _DEFAULT_SIMS,
    profile: Any = None,
    base_seed: Optional[int] = None,
    endgame: Optional[Mapping[str, Any]] = None,
    scoring: Optional[Mapping[str, Any]] = None,
    record_sims: bool = False,
    overtime_sudden_death: Optional[bool] = None,
) -> dict[str, Any] | NhlResimRefusal:
    """Run `sims` resumed games and aggregate the moneyline.

    `overtime_sudden_death` defaults to :func:`live_overtime_sudden_death` (production: on); pass False for
    the old OT (one whole 5:00 segment, goals summed), reproduced seed for seed.

    `endgame` defaults to :func:`live_endgame_calibration` (production); pass
    `LEGACY_LIVE_ENDGAME` for the pre-calibration histogram, reproduced seed for seed.
    `scoring` defaults to :func:`live_scoring_calibration` (production); pass
    `LEGACY_LIVE_SCORING` for today's scoring level and total, reproduced seed for seed.
    `record_sims` (the replay harness only) adds `sim_records`: per sim, `[raw total, the regulation seconds
    its one-goal margin had left (-1 if not end-game eligible), [seconds left at each regulation goal after
    the live state]]` -- what the total's grade needs to apply any (keep, late window, end-game) exactly.

    `features` is a `HockeyGameFeatures` -- the SAME object the pregame board
    builds from -- so the live number rests on the same rates, lineups and
    special teams as the pregame one, differing only in where the game starts.
    That is what makes the two comparable at all.
    """
    from syndicate.features.nhl.sim_engine.hockeysim.models import RateModels, TeamRates
    from syndicate.features.nhl.sim_engine.hockeysim.runtime import (
        run_hockeysim_game_from_state,
    )

    home_players = tuple(getattr(features, "home_players", ()) or ())
    away_players = tuple(getattr(features, "away_players", ()) or ())
    if not home_players or not away_players:
        return NhlResimRefusal("no_rosters", state.game_pk)

    lineup_home = [p.lineup_row() for p in home_players]
    lineup_away = [p.lineup_row() for p in away_players]
    if not any(r.get("line_slot") for r in lineup_home) or not any(
        r.get("line_slot") for r in lineup_away
    ):
        # WITHOUT LINE SLOTS THE ENGINE FALLS TO THE ROSTER-ONLY PATH, which has
        # no line rotation AND NO SCORE EFFECTS -- and the score effects are
        # precisely what makes a resumed state produce a different answer. A
        # resume without them would return something very close to the pregame
        # number while looking live. Refuse instead.
        return NhlResimRefusal("no_line_slots", state.game_pk)

    home_feat, away_feat = getattr(features, "home", None), getattr(features, "away", None)
    if home_feat is None or away_feat is None:
        return NhlResimRefusal("no_team_features", state.game_pk)

    scoring_cal = dict(scoring if scoring is not None else live_scoring_calibration())
    goal_scale = scoring_goal_scale(scoring_cal)
    total_keep = scoring_total_keep(scoring_cal)
    late_seconds = scoring_late_seconds(scoring_cal)
    endgame_in_total = bool(scoring_cal.get("count_endgame_in_total"))
    sudden_death = live_overtime_sudden_death() if overtime_sudden_death is None else bool(overtime_sudden_death)
    rates = RateModels(
        home=TeamRates(
            shots_per_60=float(home_feat.shots_per_60),
            # NHL_LIVE_SCORING_CALIBRATION: the full-game rate brought to this engine's regulation level.
            goals_per_60=float(home_feat.goals_per_60) * goal_scale,
            faceoff_win_pct=float(home_feat.faceoff_win_pct),
        ),
        away=TeamRates(
            shots_per_60=float(away_feat.shots_per_60),
            goals_per_60=float(away_feat.goals_per_60) * goal_scale,
            faceoff_win_pct=float(away_feat.faceoff_win_pct),
        ),
        player_rates={},
    )

    if state.period > _REGULATION_PERIODS:
        # Already in overtime: regulation is spent and the score is tied by
        # definition. The engine's own OT/shootout resolution runs from a tied
        # state, so resuming at the OT period index with no regulation left is
        # the correct restatement.
        period_idx = _REGULATION_PERIODS
        seconds_remaining = state.clock_seconds
    else:
        period_idx = state.period - 1  # scoreboard is 1-based; the engine is 0-based
        seconds_remaining = state.clock_seconds

    roster_home = [p.roster_row() for p in home_players]
    roster_away = [p.roster_row() for p in away_players]
    st_home = dict(getattr(home_feat, "special_teams", {}) or {}) or None
    st_away = dict(getattr(away_feat, "special_teams", {}) or {}) or None

    seed0 = int(base_seed if base_seed is not None else abs(hash(state.game_pk)) % 1_000_003)
    calibration = dict(endgame if endgame is not None else live_endgame_calibration())
    in_regulation = state.period <= _REGULATION_PERIODS      # resumed in OT: no regulation left to end
    p_empty_net = endgame_empty_net_prob(calibration, seconds_left=float("inf")) if in_regulation else 0.0
    cutoff_left = float(regulation_seconds_left(state.period, state.clock_seconds))
    one_goal_seconds: dict[str, dict[str, int]] = {"1": {}, "-1": {}}
    # Its own stream, so the engine's draws (and `off`'s histogram) are identical with it on or off.
    empty_net_rng = random.Random((seed0 * 2_654_435_761 + 0xE6) % (2**32))
    # The total's thinning has its own stream too: the engine's draws AND the end-game's are untouched by it.
    total_rng = random.Random((seed0 * 2_654_435_761 + 0x70) % (2**32))
    home_wins = 0
    empty_net_goals = 0
    margins: list[int] = []
    totals: list[int] = []
    raw_totals: list[int] = []
    # The RAW margins (before the end-game), split by how the sim ended. A grade applies any p to these
    # in expectation without re-simulating (scripts/backtest_nhl_live_puckline.py).
    regulation_margins: list[int] = []
    overtime_margins: list[int] = []
    # The same regulation-end +-1 sims by their RAW total, then by timing bin: what an end-game applied in
    # expectation moves from total t to t + 1 (the total grade, lane nhl-live-total-calibration).
    one_goal_totals: dict[str, dict[str, int]] = {}
    sim_records: list[list[Any]] = []
    for i in range(int(sims)):
        gs, events = run_hockeysim_game_from_state(
            state.home_name,
            state.away_name,
            roster_home,
            roster_away,
            rates,
            period_idx=period_idx,
            seconds_remaining=seconds_remaining,
            home_score=state.home_score,
            away_score=state.away_score,
            lineup_home=lineup_home,
            lineup_away=lineup_away,
            st_home=st_home,
            st_away=st_away,
            profile=profile,
            seed=seed0 + i,
            ot_sudden_death=sudden_death,
        )
        hs, as_ = int(gs.home.score), int(gs.away.score)
        raw_total = hs + as_
        raw_totals.append(raw_total)
        past_regulation = _went_past_regulation(events)
        (overtime_margins if past_regulation else regulation_margins).append(hs - as_)
        empty_net_this_sim = 0
        en_secs = -1.0
        one_goal_end = not past_regulation and abs(hs - as_) == 1
        # Only read when something needs them (off: the one-goal sims only, as before).
        goal_lefts = (regulation_goal_seconds_left(events, start_period_idx=period_idx,
                                                   start_seconds=seconds_remaining)
                      if (one_goal_end or total_keep < 1.0 or record_sims) else [])
        if one_goal_end:
            # `seconds_left_at_last_goal`, from the goal times already read
            left = min(goal_lefts) if goal_lefts else float(cutoff_left)
            en_secs = left if in_regulation else -1.0
            side = one_goal_seconds["1" if hs > as_ else "-1"]
            key = str(int(min(left, _ONE_GOAL_SECONDS_CAP) // _ONE_GOAL_SECONDS_BIN * _ONE_GOAL_SECONDS_BIN))
            side[key] = side.get(key, 0) + 1
            by_total = one_goal_totals.setdefault(str(raw_total), {})
            by_total[key] = by_total.get(key, 0) + 1
            p_sim = endgame_empty_net_prob(calibration, seconds_left=left) if in_regulation else 0.0
            if p_sim > 0.0 and empty_net_rng.random() < p_sim:
                if hs > as_:
                    hs += 1
                else:
                    as_ += 1
                empty_net_goals += 1
                empty_net_this_sim = 1
        if hs > as_:
            home_wins += 1
        margins.append(hs - as_)
        # Off: the raw total, the end-game out of it (today's). On: the engine's regular-play goals thinned to
        # `total_keep`, then the end-game's goal (not the engine's, so never thinned). An overtime state has
        # no regulation goals left, so nothing in it is thinned.
        total = thin_total(raw_total, goal_lefts, total_keep, late_seconds, total_rng)
        totals.append(total + (empty_net_this_sim if endgame_in_total else 0))
        if record_sims:
            sim_records.append([raw_total, round(en_secs, 1), [round(s, 1) for s in goal_lefts]])

    if not margins:
        return NhlResimRefusal("no_sims_run", state.game_pk)

    n = float(len(margins))
    return {
        "home_win_prob": home_wins / n,
        "sims_run": len(margins),
        "home_margin_mean": sum(margins) / n,
        "total_mean": sum(totals) / n,
        # THE DRAWS, not just their mean: `{str(home - away): count}`, HOME-POSITIVE, the shape
        # `price_distribution_market` and `live_display_block` read. With the shootout on (the calibrated
        # profile's setting) it credits the winner one goal (`engine.simulate_with_lineups`), so a final
        # margin is never 0, which is how books settle a puck line.
        # Published for DISPLAY ONLY -- see the module docstring and `build_game_lens`.
        # AFTER the end-game (`NHL_LIVE_ENDGAME_CALIBRATION`).
        "margin_dist": _histogram(margins),
        # BEFORE the end-game, split by how each sim ended (not published; the grade reads them).
        "regulation_margin_dist": _histogram(regulation_margins),
        "overtime_margin_dist": _histogram(overtime_margins),
        # The regulation-end +-1 sims by the regulation time their margin had left (5 s bins, capped).
        "regulation_one_goal_seconds": one_goal_seconds,
        # TOTALS (lane nhl-live-total-calibration; not published): the total's draws as `total_mean` counts
        # them, the RAW engine totals, and the regulation-end +-1 sims by raw total then timing bin.
        "total_dist": _histogram(totals),
        "raw_total_dist": _histogram(raw_totals),
        "regulation_one_goal_totals": one_goal_totals,
        "endgame": {
            "empty_net_p": p_empty_net,
            "ramp_seconds": float(calibration.get("ramp_seconds") or 0.0),
            "empty_net_goals": empty_net_goals,
            "calibration": "on" if float(calibration.get("empty_net_p") or 0.0) > 0.0 else "off",
        },
        # Which scoring level this number carries (NHL_LIVE_SCORING_CALIBRATION). Lane-level; no pricer reads it.
        "scoring": {
            "goal_scale": goal_scale,
            "total_keep": total_keep,
            "total_keep_late_seconds": late_seconds,
            "endgame_in_total": endgame_in_total,
            "calibration": "on" if (goal_scale != 1.0 or total_keep != 1.0 or endgame_in_total) else "off",
        },
        # Which OT this number carries (lane nhl-live-overtime). Lane-level; no pricer reads it.
        "overtime": {
            "rule": "sudden_death" if sudden_death else "full_segment",
            "calibration": "on" if sudden_death else "off",
            "sims_past_regulation": len(overtime_margins),
            # Resumed IN OT: the OT clock the sims played (on) -- off played a fresh 5:00 regardless.
            "resumed_ot_clock_seconds": None if in_regulation else int(state.clock_seconds),
        },
        **({"sim_records": sim_records} if record_sims else {}),
    }


def _histogram(values: Sequence[int]) -> dict[str, int]:
    """`{value: count}` over integer draws, keyed by str so it survives JSON (NFL's and NCAAF's shape)."""
    out: dict[str, int] = {}
    for value in values:
        key = str(int(value))
        out[key] = out.get(key, 0) + 1
    return out


def build_game_lens(
    state: Optional[NhlLiveGameState],
    result: dict[str, Any] | NhlResimRefusal,
    *,
    live_state_as_of: str = "",
) -> list[dict[str, Any]]:
    """The `gameLens` list for one game: exactly one lane, honestly stamped.

    A REFUSAL PUBLISHES A LANE. Publishing nothing would be simpler and worse:
    an absent lane is indistinguishable from a producer that never ran, which
    is the reading that cost WNBA a week.

    THE REFUSED LANE CARRIES NO `modelHomeWinProb` -- not the pregame one, not
    a zero, not a null a downstream `or` could turn into a number (`#414`).
    """
    if isinstance(result, NhlResimRefusal):
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
        # Which end-game this number carries (lane nhl-live-endgame-calibration): a production reading
        # can tell `on` from `off` and see the p this state got. Lane-level, so no pricer reads it.
        "liveEndgame": dict(result.get("endgame") or {}),
        # Which scoring level (lane nhl-live-total-calibration): `goal_scale` and whether the end-game's
        # goals are in `projection.total`. Lane-level, so no pricer reads it.
        "liveScoring": dict(result.get("scoring") or {}),
        # Which OT (lane nhl-live-overtime): sudden death on the clock shown, or the old full segment.
        "liveOvertime": dict(result.get("overtime") or {}),
        # DISPLAY ONLY. `live_gameline_join` reads `projection.total` and
        # `projection.homeMargin` for display and prices NEITHER: totals and
        # puck lines are priced from `totalRunsDist` / `marginDist`, which this
        # lane deliberately does not carry, because no NHL live totals or
        # puck-line estimator has been graded.
        "projection": {
            "homeMargin": result["home_margin_mean"],
            "total": result["total_mean"],
            # THE PUCK LINE'S LIVE NUMBER, FOR DISPLAY (`#773`). NOT `marginDist`: that key opens
            # pricing. The join reads this one only into the Live column and refuses the row
            # `live_margin_published_for_display_only`. `{}` from a result without draws reads as absent.
            "displayMarginDist": result.get("margin_dist") or {},
            "homeScore": state.home_score,
            "awayScore": state.away_score,
            "period": state.period,
            "clockSeconds": state.clock_seconds,
        },
    }]


def live_lens_snapshot_path():
    """Where the tick writes, and the join reads.

    A single always-overwritten file, not date-scoped at the PATH level --
    matching the mlb/nba/wnba/soccer/nfl convention, where the snapshot's own
    `date` field carries which slate it covers. `data_root()` is the MOUNTED
    disk (`SYNDICATE_DATA_ROOT`), never a source-tree-relative path: an input
    under the repo checkout is destroyed by the next deploy
    (`model_engine_standard` §3).

    THIS PATH MUST BE ALLOWLISTED or no other service can read it. See
    `artifact_publisher.HOT_ARTIFACT_PATTERNS` -- the producer runs on
    live-odds-worker and the board is built on refresh-worker, so an
    unallowlisted snapshot is a file that exists and cannot cross.
    """
    from syndicate.features.shared.refresh_state_store import data_root

    return data_root() / "live" / "nhl_live_lens.json"


def _slate_features_root():
    """The NHL artifact root the slate features are read from: the one the PREGAME producer writes.

    WHY THIS EXISTS `[2026-11-08, lane nhl-live-resim-slate-root]`. `build_slate_features(date)` with no
    `root` resolves `hockeysim.features.loaders.nhl_source_root()`, which honours only
    `SYNDICATE_ARTIFACT_ROOT_NHL` and otherwise falls back to `<repo>/data/nhl_source` -- on the fleet the
    CHECKOUT `~/Syndicate`, whose git mirror's odds scoreboards stop at `date=2026-06-14`. The pregame
    producer never hits that: `refresh_odds_sources` passes `--artifact-root <SYNDICATE_DATA_ROOT>/nhl_source`.
    So every live game refused `no_slate_features`. Measured on the fleet 2026-11-08 23:4xZ, same code,
    same date: default root 0 games; `~/syndicate-prod/data/nhl_source` 6 games, including the live
    TBL@WPG (2026020280) the 23:39Z snapshot had refused. NHL live rows carried no live number.

    `SYNDICATE_ARTIFACT_ROOT_NHL` keeps its precedence (None hands the loader its own default, which reads
    it). Otherwise `sources.default_nhl_source_root()`: `SYNDICATE_NHL_SOURCE_ROOT`, then
    `SYNDICATE_DATA_ROOT/nhl_source`, then the repo mirror -- the same chain every other NHL reader uses.
    None if that chain cannot resolve (strict hosted storage with no data root), which is the old behaviour.
    """
    import os

    if str(os.environ.get("SYNDICATE_ARTIFACT_ROOT_NHL") or "").strip():
        return None
    try:
        from syndicate.features.nhl.sources import default_nhl_source_root

        return default_nhl_source_root()
    except Exception:
        return None


def validate_live_lens_snapshot(snapshot: Any) -> bool:
    """Is this snapshot safe to publish?

    Deliberately shape-only, and deliberately NOT a check that any game was
    priced: an empty `games` list on a date with no NHL fixtures is a correct
    snapshot, and refusing to publish it would leave the previous day's file in
    place to be read as today's. The non-finite check is the one that matters --
    a NaN win probability serialises to invalid JSON and poisons every reader.
    """
    if not isinstance(snapshot, dict):
        return False
    if not str(snapshot.get("date") or "").strip():
        return False
    games = snapshot.get("games")
    if not isinstance(games, list):
        return False
    for game in games:
        if not isinstance(game, Mapping):
            return False
        lanes = game.get("gameLens")
        if not isinstance(lanes, list):
            return False
        for lane in lanes:
            if not isinstance(lane, Mapping):
                return False
            prob = lane.get("modelHomeWinProb")
            if prob is None:
                continue
            try:
                value = float(prob)
            except (TypeError, ValueError):
                return False
            # NaN fails every comparison with itself; a probability outside
            # [0, 1] is a bug that must not reach a pricer.
            if value != value or value < 0.0 or value > 1.0:
                return False
    return True


class NhlSlateFetchFailed(RuntimeError):
    """The slate could not be READ. Its own type so it cannot be confused with
    a slate that is genuinely empty -- those have opposite meanings and
    opposite fixes, and conflating them cost a full live slate (below)."""


def fetch_score_rows(date_str: str, *, timeout_seconds: float = 10.0) -> list[dict[str, Any]]:
    """`/v1/score/<date>` games. RAISES `NhlSlateFetchFailed` if it cannot read.

    Reads the SCORE endpoint rather than `/v1/schedule`, which returns
    `clock: null` on live games -- 7 of 7 measured 2026-09-22.

    THE USER-AGENT IS LOAD-BEARING, measured 2026-09-25 against the live
    endpoint, same instant, same URL:

        default urllib UA -> HTTP 403 Forbidden
        "Mozilla/5.0"     -> 200, 11 games

    `api-web.nhle.com` refuses `Python-urllib/3.x`. Without this header EVERY
    fetch 403s, and the old `except Exception: return []` turned that into an
    empty slate -- so the producer reported `ok: true` in under a second while
    six NHL games were live, and the board read `games_in_snapshot: 0` with no
    refusal to look at. Measured on production 2026-09-24 23:37Z and again
    01:39Z; the tick had been publishing an empty slate since it was deployed.
    A date-basis theory (UTC vs Central at midnight) was tested FIRST and
    refuted -- the 23:37Z reading predates the UTC flip.

    SO THE BARE SWALLOW IS GONE TOO, and that is the bigger half. A fetch that
    fails must not be spelled the same way as a slate with no games: `learnings`
    has this as a standing rule (an unknown must not default onto the permissive
    branch) and this is what violating it looks like in production.
    """
    url = _SCORE_URL.format(date=str(date_str or "")[:10])
    request = urllib.request.Request(url, headers=dict(_SCORE_HEADERS))
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as resp:
            payload = json.load(resp)
    except Exception as exc:
        code = getattr(exc, "code", "")
        print(f"[nhl_live_resim] NHL_SCORE_FETCH_FAILED date={str(date_str or '')[:10]} "
              f"{type(exc).__name__} {code}", flush=True)
        raise NhlSlateFetchFailed(f"{type(exc).__name__} {code}".strip()) from exc
    games = payload.get("games") if isinstance(payload, Mapping) else None
    return [g for g in (games or []) if isinstance(g, Mapping)]


def build_live_lens_snapshot(
    date_str: str,
    *,
    sims: int = _DEFAULT_SIMS,
    budget_seconds: float = _DEFAULT_BUDGET_SECONDS,
    score_rows: Optional[Sequence[Mapping[str, Any]]] = None,
    slate_features: Optional[Sequence[Any]] = None,
    player_stats_fetch_json: Any = None,
) -> dict[str, Any]:
    """The shared `gameLens` snapshot for one date.

    A SIMULATION. Runs on the worker that owns the live-lens loop and writes an
    artifact the web service reads; the join never calls this.

    Each LIVE game also carries its box score as `livePlayerStats`
    (`_attach_live_player_stats`) -- read here, on the worker, so the board
    join can show a live prop's Actual without fetching anything.
    `player_stats_fetch_json` is that read's injectable seam; an injected
    `score_rows` with no seam fetches no box at all.

    `score_rows` and `slate_features` are injectable so this is testable
    without the network or a mirrored slate -- production passes neither.
    """
    from syndicate.features.shared.request_path_guard import (
        refuse_if_compute_in_request_path,
    )

    refuse_if_compute_in_request_path("nhl_live_resim_snapshot")

    started = time.monotonic()
    generated_at = _utc_now_iso()
    date_key = str(date_str or "")[:10]

    slate_error: str | None = None
    if score_rows is not None:
        rows = list(score_rows)
    else:
        try:
            rows = fetch_score_rows(date_key)
        except NhlSlateFetchFailed as exc:
            # NOT re-raised: one bad slate must not kill the whole live-lens
            # tick for every other sport. But it is RECORDED, so an empty
            # `games` list can be read as "could not fetch" rather than as
            # "nothing was scheduled".
            rows = []
            slate_error = str(exc) or "fetch_failed"

    if slate_features is None:
        from syndicate.features.nhl.sim_engine.hockeysim.features.loaders import (
            build_slate_features,
        )

        try:
            # The producer's root, not the loader's checkout default -- see `_slate_features_root`.
            slate_features = build_slate_features(date_key, root=_slate_features_root())
        except Exception:
            slate_features = []
    by_pk = {str(getattr(g, "game_pk", "")).strip(): g for g in (slate_features or [])}

    out_games: list[dict[str, Any]] = []
    for row in rows:
        state = live_state_from_score_row(row)
        if isinstance(state, NhlResimRefusal):
            # NAMES COME FROM THE RAW ROW, not from the state -- there is no
            # state, that is what a refusal means. Measured on production
            # 2026-09-25T03:01:14Z: publishing `""` here made the board drop
            # **9 of 11** games as `skipped_no_team_names`, so the refusal this
            # module publishes ON PURPOSE was invisible for exactly the games
            # that refused EARLIEST -- `game_not_started` and `game_final`
            # return before the team block is ever read. A refusal the board
            # cannot match is indistinguishable from a game the producer never
            # saw, which is the ambiguity this whole module exists to remove.
            ref_away, ref_home = _published_team_names(row, by_pk)
            out_games.append({
                "away_name": ref_away,
                "home_name": ref_home,
                "gameLens": build_game_lens(None, state, live_state_as_of=generated_at),
            })
            continue

        features = by_pk.get(state.game_pk)
        if features is None:
            result: dict[str, Any] | NhlResimRefusal = NhlResimRefusal(
                "no_slate_features", state.game_pk
            )
        elif (time.monotonic() - started) >= float(budget_seconds):
            # THE BUDGET IS A REFUSAL, NOT A SHORTER SIM. Cutting `sims` to fit
            # would publish a probability whose interval nobody bounded, and
            # `prob_std_err` derives that interval from `simsRun`.
            result = NhlResimRefusal("budget_exhausted", state.game_pk)
        else:
            result = resim_live_game(features, state, sims=sims)

        # The board's spelling, not the state's short names -- see `_published_team_names`.
        pub_away, pub_home = _published_team_names(row, by_pk)
        out_games.append({
            "away_name": pub_away,
            "home_name": pub_home,
            "gameLens": build_game_lens(state, result, live_state_as_of=state.as_of),
        })

    # LIVE BOX SCORES, AFTER EVERY RE-SIM, so a slow feed can never spend the
    # budget a priced lane needed. See `_attach_live_player_stats`.
    player_stats_tally = _attach_live_player_stats(
        rows,
        out_games,
        fetch_json=player_stats_fetch_json,
        enabled=score_rows is None or player_stats_fetch_json is not None,
    )

    return {
        "sport": "nhl",
        "date": date_key,
        "generatedAt": generated_at,
        "simsPerGame": int(sims),
        "budgetSeconds": float(budget_seconds),
        "elapsedSeconds": round(time.monotonic() - started, 3),
        "games": out_games,
        # COVERAGE, so a zero is never bare. `slateRows` separates "the slate
        # had no games" from "the slate could not be read" (`slateError`), and
        # the refusal breakdown says why a game that WAS read produced no
        # probability. The absence of this block is why the 2026-09-24 failure
        # took a log dig and an endpoint A/B to explain instead of one read.
        "coverage": {
            "slateRows": len(rows),
            "slateError": slate_error,
            # Games the slate FEATURES cover. 0 beside slateRows > 0 is "features unreadable" (the
            # 2026-11-08 wrong-root defect, `_slate_features_root`), not a refusal per game.
            "slateFeatureGames": len(by_pk),
            "games": len(out_games),
            "liveResimmed": sum(
                1 for g in out_games
                for lane in (g.get("gameLens") or [])
                if lane.get("source") == LIVE_RESIM_LENS_SOURCE
            ),
            "refusalsByReason": _refusals_by_reason(out_games),
            "livePlayerStats": player_stats_tally,
        },
    }


# The scoreboard states whose box is a game IN PROGRESS. An intermission is still
# LIVE here (the re-sim refuses it; the box is perfectly readable). Not FINAL/OFF:
# a finished game's board rows are no longer live, so its box has no live reader.
_LIVE_BOX_STATES = frozenset({"LIVE", "CRIT"})
# Wall clock for the box reads of one tick. Two GETs per game the first time
# (box + the once-per-game roster), one after that.
_PLAYER_STATS_BUDGET_SECONDS = 15.0


def _attach_live_player_stats(
    rows: Sequence[Mapping[str, Any]],
    out_games: list[dict[str, Any]],
    *,
    fetch_json: Any = None,
    enabled: bool = True,
    budget_seconds: float = _PLAYER_STATS_BUDGET_SECONDS,
) -> dict[str, Any]:
    """Put each LIVE game's box score on its snapshot entry as `livePlayerStats`.

    WHY HERE `[2026-11-09, lane nhl-nfl-live-prop-actuals]`. Live NHL props had no
    Actual on the board (0 of 29 measured 01:31Z), and the board join must not
    fetch (`board_enrichment` runs in the board cycle). This tick already owns
    every live NHL game, so it reads the box and the join reads the snapshot.
    The box is INDEPENDENT of the re-sim: a game the re-sim refused (intermission,
    no slate features, budget) still has a box, and its Actual is still a fact.

    `rows` and `out_games` are parallel -- the loop above appends exactly one
    entry per score row. A length mismatch means that stopped being true, and it
    attaches nothing rather than pinning one game's box on another.

    Never raises: a box must not cost the tick its snapshot.
    """
    tally: dict[str, Any] = {"enabled": bool(enabled), "liveGames": 0, "attached": 0,
                             "unreadable": 0, "budgetExhausted": 0}
    if not enabled:
        return tally
    if len(rows) != len(out_games):
        tally["misaligned"] = [len(rows), len(out_games)]
        print(f"[nhl_live_resim] LIVE_PLAYER_STATS_MISALIGNED rows={len(rows)} games={len(out_games)}", flush=True)
        return tally
    try:
        from syndicate.features.shared.live_player_actuals import BLOCK_KEY, nhl_live_player_stats
    except Exception as exc:  # noqa: BLE001 -- deploy-skew guard
        tally["error"] = type(exc).__name__
        return tally
    started = time.monotonic()
    for row, game in zip(rows, out_games):
        state = str(row.get("gameState") or row.get("gameStatus") or "").strip().upper()
        if state not in _LIVE_BOX_STATES:
            continue
        tally["liveGames"] += 1
        if time.monotonic() - started >= float(budget_seconds):
            tally["budgetExhausted"] += 1
            continue
        try:
            block = nhl_live_player_stats(row.get("id") or row.get("gamePk"), fetch_json=fetch_json, game_state=state)
        except Exception:  # noqa: BLE001
            block = None
        if block is None:
            tally["unreadable"] += 1
            continue
        game[BLOCK_KEY] = block
        tally["attached"] += 1
    tally["elapsedSeconds"] = round(time.monotonic() - started, 3)
    if tally["liveGames"]:
        print(
            "[nhl_live_resim] LIVE_PLAYER_STATS "
            + " ".join(f"{k}={v}" for k, v in tally.items()),
            flush=True,
        )
    return tally


def _refusals_by_reason(games: list[dict[str, Any]]) -> dict[str, int]:
    """A zero without this is not a result -- the same rule NCAAF and NFL state.

    READS THIS MODULE'S OWN LANE SHAPE, which is not NFL's. Written first as a
    copy of NFL's (`lane["ok"]`, `lane["refusal"]["reason"]`) and shipped that
    way in `fde7e7d4`; NHL lanes carry NEITHER key, so on the real slate it
    reported `liveResimmed: 0` unconditionally and `{'unknown': 11}` for the
    reasons. Telemetry that is confidently wrong is worse than none, and this
    block exists precisely to stop a bare zero -- so it produced the defect it
    was added to prevent. Caught by running it against the live slate rather
    than a fixture.

    The discriminator here is `source`: a refusal is stamped
    `PREGAME_LENS_SOURCE` and carries `liveResimRefusal`.
    """
    reasons: dict[str, int] = {}
    for game in games or []:
        for lane in game.get("gameLens") or []:
            if lane.get("source") == LIVE_RESIM_LENS_SOURCE:
                continue
            reason = str(lane.get("liveResimRefusal") or "unknown")
            reasons[reason] = reasons.get(reason, 0) + 1
    return reasons
