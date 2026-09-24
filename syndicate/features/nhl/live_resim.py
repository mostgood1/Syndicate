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

THE REST-OF-GAME MARGIN AND TOTAL DISTRIBUTIONS ARE **NOT** PUBLISHED, though
this re-sim has them in hand. `live_gameline_join` would price totals and
puck lines off them the moment they appeared, and **no NHL live totals
estimator has ever been graded**. `#499` is the precedent in the other
direction: WNBA totals became priceable only after a 249-game backtest produced
a measured interval. The projection block carries live MEANS for display and
nothing a pricer reads.

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

_SCORE_URL = "https://api-web.nhle.com/v1/score/{date}"


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

    home_name = str(home.get("name", {}).get("default") if isinstance(home.get("name"), Mapping) else home.get("name") or "").strip()
    away_name = str(away.get("name", {}).get("default") if isinstance(away.get("name"), Mapping) else away.get("name") or "").strip()
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
) -> dict[str, Any] | NhlResimRefusal:
    """Run `sims` resumed games and aggregate the moneyline.

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

    rates = RateModels(
        home=TeamRates(
            shots_per_60=float(home_feat.shots_per_60),
            goals_per_60=float(home_feat.goals_per_60),
            faceoff_win_pct=float(home_feat.faceoff_win_pct),
        ),
        away=TeamRates(
            shots_per_60=float(away_feat.shots_per_60),
            goals_per_60=float(away_feat.goals_per_60),
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
    home_wins = 0
    margins: list[int] = []
    totals: list[int] = []
    for i in range(int(sims)):
        gs, _events = run_hockeysim_game_from_state(
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
        )
        hs, as_ = int(gs.home.score), int(gs.away.score)
        if hs > as_:
            home_wins += 1
        margins.append(hs - as_)
        totals.append(hs + as_)

    if not margins:
        return NhlResimRefusal("no_sims_run", state.game_pk)

    n = float(len(margins))
    return {
        "home_win_prob": home_wins / n,
        "sims_run": len(margins),
        "home_margin_mean": sum(margins) / n,
        "total_mean": sum(totals) / n,
    }


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
        # DISPLAY ONLY. `live_gameline_join` reads `projection.total` and
        # `projection.homeMargin` for display and prices NEITHER: totals and
        # puck lines are priced from distributions this lane deliberately does
        # not carry, because no NHL live totals estimator has been graded.
        "projection": {
            "homeMargin": result["home_margin_mean"],
            "total": result["total_mean"],
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


def fetch_score_rows(date_str: str, *, timeout_seconds: float = 10.0) -> list[dict[str, Any]]:
    """`/v1/score/<date>` games, or `[]`.

    Reads the SCORE endpoint rather than `/v1/schedule`, which returns
    `clock: null` on live games -- 7 of 7 measured 2026-09-22.
    """
    url = _SCORE_URL.format(date=str(date_str or "")[:10])
    try:
        with urllib.request.urlopen(url, timeout=timeout_seconds) as resp:
            payload = json.load(resp)
    except Exception:
        return []
    games = payload.get("games") if isinstance(payload, Mapping) else None
    return [g for g in (games or []) if isinstance(g, Mapping)]


def build_live_lens_snapshot(
    date_str: str,
    *,
    sims: int = _DEFAULT_SIMS,
    budget_seconds: float = _DEFAULT_BUDGET_SECONDS,
    score_rows: Optional[Sequence[Mapping[str, Any]]] = None,
    slate_features: Optional[Sequence[Any]] = None,
) -> dict[str, Any]:
    """The shared `gameLens` snapshot for one date.

    A SIMULATION. Runs on the worker that owns the live-lens loop and writes an
    artifact the web service reads; the join never calls this.

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

    rows = list(score_rows) if score_rows is not None else fetch_score_rows(date_key)

    if slate_features is None:
        from syndicate.features.nhl.sim_engine.hockeysim.features.loaders import (
            build_slate_features,
        )

        try:
            slate_features = build_slate_features(date_key)
        except Exception:
            slate_features = []
    by_pk = {str(getattr(g, "game_pk", "")).strip(): g for g in (slate_features or [])}

    out_games: list[dict[str, Any]] = []
    for row in rows:
        state = live_state_from_score_row(row)
        if isinstance(state, NhlResimRefusal):
            out_games.append({
                "away_name": "",
                "home_name": "",
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

        out_games.append({
            "away_name": state.away_name,
            "home_name": state.home_name,
            "gameLens": build_game_lens(state, result, live_state_as_of=state.as_of),
        })

    return {
        "sport": "nhl",
        "date": date_key,
        "generatedAt": generated_at,
        "simsPerGame": int(sims),
        "budgetSeconds": float(budget_seconds),
        "elapsedSeconds": round(time.monotonic() - started, 3),
        "games": out_games,
    }
