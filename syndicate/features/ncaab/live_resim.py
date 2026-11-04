"""NCAAB LIVE RE-SIM: P1's native possession engine, resumed under NCAAB rules from P2's live state.

    load_player_priors(date)                 -> PlayerPriors | NcaabResimRefusal
    build_engine_inputs(date, home, away)    -> dict (engine kwargs) | NcaabResimRefusal
    resume_from_summary(summary)             -> (LiveGameState, GameState, ResumeFacts) | NcaabResimRefusal
    resim_live_game(inputs, game_state, ...) -> result dict | NcaabResimRefusal
    build_live_lens_snapshot(date)           -> the shared `gameLens` snapshot

Phase P4 of `docs/ai_context/basketball_live_native_plan.md` (lane `ncaab-native-live-tier`).
User decision 2026-10-12: P1's PLAYER-level engine, fed by a new NCAAB player-prior producer
(`scripts/build_ncaab_player_priors.py`). Template: `syndicate/features/nba/live_resim.py` (P3);
its name helpers are imported, not copied.

--------------------------------------------------------------------------
NOTHING HERE IMPORTS `vendor.`
--------------------------------------------------------------------------

WHERE THE INPUTS COME FROM, which is the one real difference from NBA. NBA resumes from the
kwargs its PREGAME sim persisted. NCAAB has no pregame sim, so the inputs are BUILT here from
two Syndicate tables, both dated and both read strictly before the game:

  * team prior   `ncaab/live_team_model.prior_for_game` (efficiency ratings): possessions and
                 the points targets.
  * player rows  `player_priors_<season>_asof_<date>.csv`: `_sim_min` (projected minutes scaled
                 to the league's 200 team-minutes), `starter_prob`, `pred_pts`, `_prior_<k>_pm`.

A team with fewer than MIN_ROTATION projected players refuses (`thin_rotation`); an unrated team
refuses by the team model's own token. Nothing is defaulted.

--------------------------------------------------------------------------
REFUSE RATHER THAN DEGRADE -- and NAME every refusal
--------------------------------------------------------------------------

A refusal publishes a `pregame_only` lane with NO probability (`#414`), which
`live_gameline_join.LIVE_LENS_SOURCES_BY_SPORT["ncaab"]` rejects by its stamp. The budget is a
refusal, not fewer sims (`simsRun` is what the join's precision gate trusts).

The served full-game MARGIN is market-anchored (user 2026-11-03): see "margin anchor" below.

--------------------------------------------------------------------------
THE SLATE IS BIGGER THAN NBA'S, so a tick ROTATES
--------------------------------------------------------------------------

An NCAAB night has 50-150 games live at once (169 events on the 2025-26 opener). One tick
cannot re-sim them all at player level, so each tick starts where the last one stopped
(`_ROTATION_CURSOR`), re-sims until the budget, and CARRIES FORWARD every other game's last
published lane unchanged -- its `liveStateAsOf` is the time it was computed, so the join's own
freshness gate judges it. A game never computed yet publishes `budget_exhausted`.

--------------------------------------------------------------------------
RUNS ON A WORKER. NEVER IN A REQUEST HANDLER. A DEDICATED THREAD, OFF BY DEFAULT.
--------------------------------------------------------------------------

`build_live_lens_snapshot` calls `refuse_if_compute_in_request_path`. Like NBA it is not a
`_LIVE_LENS_SPORTS` builder: tens of seconds per game would stall every other sport's lens. It
runs only when `SYNDICATE_NCAAB_LIVE_RESIM` is on (absent = off, checked, not assumed).

--------------------------------------------------------------------------
WOMEN'S COLLEGE BASKETBALL: `league="wncaab"` (lane wncaab-module, user 2026-11-03 "Build it")
--------------------------------------------------------------------------

The same tick, resumed from the women's live state: four 10:00 quarters, so `resume_from_summary`
resumes inside a quarter and the result carries q1..q4 plus h1 = Q1+Q2, h2 = Q3+Q4. Inputs come from
the women's dated tables (`wncaab_source/data/processed/`), with no men-fitted adjustment (no half
split, no live mechanisms). It writes `live/wncaab_live_resim.json` and logs WNCAAB_LIVE_RESIM_TICK.

Its own thread, started beside the men's (`start_ncaab_live_resim_loop`). `SYNDICATE_WNCAAB_LIVE_RESIM`
switches it; ABSENT, IT FOLLOWS `SYNDICATE_NCAAB_LIVE_RESIM` -- so it runs exactly where the men's
re-sim runs (the live-odds-worker) and nowhere else, and `SYNDICATE_WNCAAB_LIVE_RESIM=0` stops it
alone. Its budget is its own (`SYNDICATE_WNCAAB_LIVE_RESIM_BUDGET_SECONDS`, default 120 s: the
women's slate is about half the men's, and both threads share one interpreter).
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import os
import re
import threading
import time
import zlib
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

LIVE_RESIM_LENS_SOURCE = "live_resim"
PREGAME_LENS_SOURCE = "pregame_only"
LEAGUE = "ncaab"
WOMENS_LEAGUE = "wncaab"

DEFAULT_SIMS = int(os.environ.get("SYNDICATE_NCAAB_LIVE_RESIM_SIMS", "200") or 200)
DEFAULT_BUDGET_SECONDS = float(os.environ.get("SYNDICATE_NCAAB_LIVE_RESIM_BUDGET_SECONDS", "240") or 240)
WNCAAB_DEFAULT_BUDGET_SECONDS = 120.0
MIN_SIMS = 100
MAX_HEADER_LEAD = 3
MIN_ROTATION = 7  # projected players with minutes; fewer cannot field the engine's lineups
TEAM_MINUTES = 200.0  # NCAAB regulation team-minutes (basketball_engine.league.NCAAB)
# Size budget (docs/ai_context/ncaab_live_tier.md): <= 20 KB/game at 200 games is 4 MB, half the
# 8 MiB keyvalue cap. A lane here carries NO per-player rows and NO pbp history.
MAX_SNAPSHOT_BYTES = 4_000_000
MAX_LANE_BYTES = 20_000

RATE_STATS = ("pts", "fga", "fgm", "threes_att", "threes", "fta", "ftm", "oreb", "dreb", "reb", "ast", "tov", "stl", "blk", "pf")
_PRIORS_RE = re.compile(r"player_priors_(\d{4})_asof_(\d{8})\.csv$")


@dataclass(frozen=True)
class NcaabResimRefusal:
    reason: str
    detail: str = ""


@dataclass(frozen=True)
class ResumeFacts:
    event_id: str
    home_id: str
    away_id: str
    home_score: int
    away_score: int
    period: int
    clock_seconds: float
    possession: Optional[str]
    last_seq: int
    as_of: str
    score_source: str = "official"
    tip_wallclock: str = ""  # the first play's ESPN wall clock: the actual tip, the margin anchor's close cutoff


@dataclass(frozen=True)
class PlayerPriors:
    season: int
    as_of: dt.date
    source: str
    by_team: Mapping[str, Sequence[Mapping[str, Any]]]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _regulation_periods(league: str) -> int:
    """2 halves (NCAAB) or 4 quarters (WNCAAB), from the one college league description."""
    from syndicate.features.college_basketball.league import league_for

    return int(league_for(league).periods)


# ------------------------------------------------------------------------------------------- inputs

def _processed_dirs(league: str = "ncaab") -> list[Path]:
    from syndicate.features.ncaab.live_team_model import ratings_dirs

    return ratings_dirs(league)


def load_player_priors(game_date: dt.date, *, dirs: Optional[Sequence[Path]] = None):
    """The newest `player_priors_<season>_asof_<d>.csv` with d <= the game date, for its season.

    A priors table dated D is built from games STRICTLY BEFORE D (`build_ncaab_player_priors.py`),
    so D == the game date carries no leakage -- unlike the ratings tables, whose as_of is the last
    game INCLUDED. No table for the season refuses (`no_player_priors`); the preseason has none
    until the first night's games are in, and that is said, not hidden.
    """
    from syndicate.features.ncaab.live_team_model import espn_season_for

    season = espn_season_for(game_date)
    found: list[tuple[dt.date, Path]] = []
    for d in dirs if dirs is not None else _processed_dirs():
        if not Path(d).is_dir():
            continue
        for path in Path(d).glob(f"player_priors_{season}_asof_*.csv"):
            m = _PRIORS_RE.search(path.name)
            if not m:
                continue
            as_of = dt.datetime.strptime(m.group(2), "%Y%m%d").date()
            if as_of <= game_date:
                found.append((as_of, path))
    if not found:
        return NcaabResimRefusal("no_player_priors", f"season {season} <= {game_date}")
    as_of, path = max(found)
    by_team: dict[str, list[dict[str, Any]]] = {}
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            by_team.setdefault(str(row.get("team_id") or ""), []).append(row)
    # A TEAM WITH NO IN-SEASON ROWS YET TAKES ITS PRESEASON ROWS (2026-11-02, lane ncaab-board-slate, user-approved
    # loan). The in-season table carries only teams with box rows, so the first few finals replaced the preseason
    # table for EVERY team: on the 11-02 opener `player_priors_2027_asof_20261102` held 4 teams while
    # `player_preseason_2027_asof_20261101` held 346, and every other game refused. The builder blends the same
    # preseason rows into a team once it has played; a team that has not played gets them unblended.
    preseason = _newest_preseason(season, game_date, dirs)
    if preseason is not None:
        with preseason.open(encoding="utf-8", newline="") as fh:
            filled: dict[str, list[dict[str, Any]]] = {}
            for row in csv.DictReader(fh):
                tid = str(row.get("team_id") or "")
                if tid not in by_team:
                    filled.setdefault(tid, []).append(row)
        by_team.update(filled)
    return PlayerPriors(season=season, as_of=as_of, source=str(path), by_team=by_team)


_PRESEASON_RE = re.compile(r"player_preseason_(\d{4})_asof_(\d{8})\.csv$")


def _newest_preseason(season: int, game_date: dt.date, dirs: Optional[Sequence[Path]]) -> Optional[Path]:
    found: list[tuple[dt.date, Path]] = []
    for d in dirs if dirs is not None else _processed_dirs():
        if not Path(d).is_dir():
            continue
        for path in Path(d).glob(f"player_preseason_{season}_asof_*.csv"):
            m = _PRESEASON_RE.search(path.name)
            if m and dt.datetime.strptime(m.group(2), "%Y%m%d").date() <= game_date:
                found.append((dt.datetime.strptime(m.group(2), "%Y%m%d").date(), path))
    return max(found)[1] if found else None


def _num(value: Any) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return 0.0
    return out if out == out else 0.0


def team_frame(rows: Sequence[Mapping[str, Any]], *, team_code: str, date: str):
    """Engine player frame for one team, or a refusal. Minutes scaled to TEAM_MINUTES."""
    import pandas as pd

    active = [r for r in rows if _num(r.get("min_proj")) > 0]
    if len(active) < MIN_ROTATION:
        return NcaabResimRefusal("thin_rotation", f"{team_code}:{len(active)}<{MIN_ROTATION}")
    total = sum(_num(r.get("min_proj")) for r in active)
    scale = TEAM_MINUTES / total if total > 0 else 0.0
    ordered = sorted(active, key=lambda r: -_num(r.get("starter_prob")) - 1e-3 * _num(r.get("min_proj")))
    starters = {id(r) for r in ordered[:5]}
    records = []
    for r in active:
        sim_min = min(40.0, _num(r.get("min_proj")) * scale)
        rec = {
            "player_name": str(r.get("player_name") or ""),
            "athlete_id": str(r.get("athlete_id") or ""),
            "team": str(team_code),
            "asof_date": str(date),
            "_sim_min": sim_min,
            "starter_prob": _num(r.get("starter_prob")),
            "is_starter": id(r) in starters,
            "pred_pts": sim_min * _num(r.get("pts_pm")),
        }
        for k in RATE_STATS:
            rec[f"_prior_{k}_pm"] = _num(r.get(f"{k}_pm"))
        records.append(rec)
    return pd.DataFrame.from_records(records)


def build_engine_inputs(date: str, home_id: str, away_id: str, *, neutral: bool, home_code: str = "",
                        away_code: str = "", priors: Any = None, team_prior: Any = None,
                        dirs: Optional[Sequence[Path]] = None, league: str = LEAGUE):
    """The engine kwargs for one NCAAB game, built from Syndicate's own dated tables.

    `league="wncaab"` (lane wncaab-module, user-approved loan 2026-11-02) reads the women's tables and runs NO
    men-fitted adjustment: the half split (H1_SHARE is the men's 47.43%) and the live mechanisms (fitted on
    men's games) stay off for the women until women's fits exist. Every NCAAB value is unchanged."""
    from syndicate.features.basketball_engine.engine import EventSimConfig
    from syndicate.features.ncaab import live_team_model as tm

    day = dt.date.fromisoformat(str(date))
    if dirs is None and league != LEAGUE:
        dirs = _processed_dirs(league)
    if team_prior is None:
        team_prior = tm.prior_for_game(day, str(home_id), str(away_id), neutral=bool(neutral), dirs=dirs)
    if isinstance(team_prior, tm.NcaabPriorRefusal):
        return NcaabResimRefusal(team_prior.reason, team_prior.detail)
    if priors is None:
        priors = load_player_priors(day, dirs=dirs)
    if isinstance(priors, NcaabResimRefusal):
        return priors
    frames = {}
    for side, tid, code in (("home", str(home_id), home_code or str(home_id)), ("away", str(away_id), away_code or str(away_id))):
        rows = priors.by_team.get(tid) or []
        if not rows:
            return NcaabResimRefusal("team_has_no_player_priors", f"{side}:{tid}")
        frame = team_frame(rows, team_code=code, date=str(date))
        if isinstance(frame, NcaabResimRefusal):
            return frame
        frames[side] = frame
    mechanisms = live_mechanisms_from_env() if league == LEAGUE else {}
    half_split = half_split_enabled() and league == LEAGUE
    return {
        "home_players": frames["home"],
        "away_players": frames["away"],
        "cfg": EventSimConfig(possessions_per_game=float(team_prior.possessions), **mechanisms),
        "target_home_points": float(team_prior.home_points),
        "target_away_points": float(team_prior.away_points),
        "quarters": half_targets(team_prior.home_points, team_prior.away_points) if half_split else None,
        "_provenance": {
            "league": league,
            "halfSplit": half_split,
            "mechanisms": sorted(mechanisms),
            "ratingsAsOf": team_prior.ratings_as_of.isoformat(),
            "priorSeasonFallback": bool(team_prior.prior_season_fallback),
            "playerPriorsAsOf": priors.as_of.isoformat(),
            "pregameTotal": round(float(team_prior.total), 2),
            "pregameHomeMargin": round(float(team_prior.home_margin), 2),
            # `college_basketball/prior_calibration.py` (2026-11-03): the fit the targets above carry, and the raw prior.
            "priorCalibration": getattr(team_prior, "calibration", None),
            "rawPregameTotal": _round_or_none(getattr(team_prior, "raw_total", None)),
            "rawPregameHomeMargin": _round_or_none(getattr(team_prior, "raw_home_margin", None)),
            "effMultBounds": eff_mult_bounds(league),
        },
    }


def eff_mult_bounds(league: str = LEAGUE) -> dict[str, list[float]]:
    """The engine's efficiency-multiplier bounds for `league` (`basketball_engine/league.py`). They sit in the
    pregame inputs key, so a new bound re-sims a published game."""
    from syndicate.features.basketball_engine import league_params

    params = league_params(league)
    return {"solve": [float(b) for b in params.exact_target_solve_bounds], "final": [float(b) for b in params.eff_mult_final_bounds]}


def _round_or_none(value: Any) -> Optional[float]:
    return None if value is None else round(float(value), 2)


_ENGINES: dict[bool, Any] = {}
_ENGINE_LOCK = threading.Lock()
# The engine's exact points-per-possession target solve (`engine.py` EXACT_TARGET_CALIBRATION, a
# LeagueParams field, False for NCAAB in league.py). The P4 backtest (2026-10-12) found the default
# approximate solve overshoots NCAAB totals by +6..+10 at the tip; this switch is the measured fix
# candidate. ABSENT IS OFF until the re-backtest decides (`ncaab_live_tier.md`).
EXACT_TARGET_ENV = "SYNDICATE_NCAAB_EXACT_TARGET"


def exact_target_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    raw = str((env if env is not None else os.environ).get(EXACT_TARGET_ENV, "") or "").strip().lower()
    return raw in {"1", "true", "on", "yes"}


def ncaab_engine(exact_target: Optional[bool] = None, league: str = LEAGUE):
    """P1's engine bound to NCAAB params and production's lineup sampler. Never NBA's: the smart sim's
    `_engine_for_league_local` maps every non-WNBA code to NBA, so it is NOT used here. `league="wncaab"`
    binds the women's params (four quarters) -- `basketball_engine.league.WNCAAB`."""
    exact = exact_target_enabled() if exact_target is None else bool(exact_target)
    key = (league, exact)
    with _ENGINE_LOCK:
        if key not in _ENGINES:
            import dataclasses

            from syndicate.features.basketball_engine import league_params
            from syndicate.features.basketball_engine.league_engine import LeagueEngine
            from syndicate.features.shared.basketball_props_smart_sim import _sample_lineup_local

            params = league_params(league)
            if exact:
                params = dataclasses.replace(params, exact_target_calibration=True)
            _ENGINES[key] = LeagueEngine(params, sample_lineup=_sample_lineup_local)
        return _ENGINES[key]


_ENGINE_KWARGS = ("home_players", "away_players", "cfg", "target_home_points", "target_away_points", "quarters")

# THE HALF SPLIT (estimator, default OFF until the paired backtest decides). NCAAB first halves score 47.43% of a
# game's points (2025-26 regular season, measured 2026-10-12); the engine splits a target evenly, so it projected
# first halves ~7.5 too high and second halves short. The engine already reads per-period targets (`quarters`:
# home/away_pts_mu, sigma, corr) and shifts each period's pace and efficiency toward them (sqrt split, clipped
# +-6%). Sigma is set to the engine's 2% floor (sd_frac) so the input moves the MEAN and adds almost no noise: the
# sim's own randomness already produces the measured ~10% half-to-half variation.
HALF_SPLIT_ENV = "SYNDICATE_NCAAB_HALF_SPLIT"
H1_SHARE = 0.4743
_HALF_SIGMA_FRAC = 0.02


# ENGINE MECHANISMS (default OFF): `SYNDICATE_NCAAB_LIVE_MECHANISMS='{"endgame_foul_window_s": 120, ...}'` sets
# EventSimConfig fields on the NCAAB engine config -- P3's end-game intentional fouling and the bonus free-throw
# mechanism among them. Absent, empty, unparseable or naming a field the engine does not have -> {} (OFF), never a
# partial guess (NBA's `live_mechanisms_from_env` rule). Lists become tuples (`endgame_foul_p_by_deficit`).
LIVE_MECHANISMS_ENV = "SYNDICATE_NCAAB_LIVE_MECHANISMS"


def live_mechanisms_from_env(env: Optional[Mapping[str, str]] = None) -> dict[str, Any]:
    from dataclasses import fields as _fields

    from syndicate.features.basketball_engine.engine import EventSimConfig

    raw = (env if env is not None else os.environ).get(LIVE_MECHANISMS_ENV, "")
    if not str(raw or "").strip():
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {}
    known = {f.name for f in _fields(EventSimConfig)}
    if not isinstance(parsed, dict) or not parsed or set(parsed) - known:
        return {}
    return {k: tuple(v) if isinstance(v, list) else v for k, v in parsed.items()}


def half_split_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    raw = str((env if env is not None else os.environ).get(HALF_SPLIT_ENV, "") or "").strip().lower()
    return raw in {"1", "true", "on", "yes"}


def half_targets(home_points: float, away_points: float) -> list[dict[str, float]]:
    out = []
    for share in (H1_SHARE, 1.0 - H1_SHARE):
        hm, am = float(home_points) * share, float(away_points) * share
        out.append({"home_pts_mu": hm, "away_pts_mu": am, "home_pts_sigma": _HALF_SIGMA_FRAC * hm,
                    "away_pts_sigma": _HALF_SIGMA_FRAC * am, "corr": 1.0})
    return out


# ------------------------------------------------------------------------------------------- live state

def _period_points(events: Sequence[Any], period: int) -> tuple[tuple[int, ...], tuple[int, ...]]:
    from syndicate.features.nba.live_resim import period_points

    return period_points(events, period)


def resume_from_summary(summary: Mapping[str, Any], *, date: str = "", as_of: str = "", league: str = LEAGUE):
    """ESPN summary -> (LiveGameState, GameState, ResumeFacts), or a named refusal. NBA's resume, the league's
    clock: two halves (NCAAB) or four quarters (WNCAAB)."""
    from syndicate.features.basketball_engine.resume import GameState
    from syndicate.features.shared import basketball_pbp as pbp
    from syndicate.features.shared.basketball_live_state import build_live_game_state

    if not isinstance(summary, Mapping):
        return NcaabResimRefusal("summary_not_a_mapping")
    try:
        rec = pbp.reconstruct(summary, league, date=date)
        state = build_live_game_state(summary, league, date=date)
    except Exception as exc:  # noqa: BLE001
        return NcaabResimRefusal("live_state_unparseable", type(exc).__name__)
    status = str(state.status_state or "").lower()
    if status == "pre":
        return NcaabResimRefusal("game_not_started")
    if status == "post" or state.completed:
        return NcaabResimRefusal("game_final")
    if status != "in":
        return NcaabResimRefusal("game_state_unrecognised", status or "<empty>")
    if not state.event_id:
        return NcaabResimRefusal("no_game_id")
    if not rec.events:
        return NcaabResimRefusal("no_plays")
    period = int(state.period or 0)
    if period < 1:
        return NcaabResimRefusal("no_period")
    clock = state.clock_left
    if clock is None or clock < 0:
        return NcaabResimRefusal("no_clock")
    hp, ap = _period_points(rec.events, period)
    score_source = "official"
    if (sum(hp), sum(ap)) != (state.home.score, state.away.score):
        lead_h, lead_a = state.home.score - sum(hp), state.away.score - sum(ap)
        if 0 <= lead_h <= MAX_HEADER_LEAD and 0 <= lead_a <= MAX_HEADER_LEAD:
            score_source = "pbp_lagging_header"
        else:
            return NcaabResimRefusal("pbp_score_mismatch",
                                     f"pbp {sum(hp)}-{sum(ap)} official {state.home.score}-{state.away.score}")
    if clock <= 0:
        if period >= _regulation_periods(league) and sum(hp) != sum(ap):
            return NcaabResimRefusal("regulation_over")
        r_period, r_secs = period + 1, None
        hp, ap = hp + (0,), ap + (0,)
    else:
        r_period, r_secs = period, int(round(clock))
        for side in ("home", "away"):
            five = _names(state, side)
            if len(set(five)) != 5:
                return NcaabResimRefusal("on_floor_incomplete", f"{side}:{len(set(five))}")
    fouls = {p.name: int(p.pf) for p in state.players if p.pf}
    home_names = {p.name for p in state.players if p.side == "home"}
    gs = GameState(
        period=r_period,
        seconds_remaining=r_secs,
        home_period_pts=hp,
        away_period_pts=ap,
        possession=state.possession_side if r_secs is not None else None,
        home_on_floor=tuple(_names(state, "home")) if r_secs is not None else (),
        away_on_floor=tuple(_names(state, "away")) if r_secs is not None else (),
        home_player_fouls={k: v for k, v in fouls.items() if k in home_names},
        away_player_fouls={k: v for k, v in fouls.items() if k not in home_names},
        home_team_fouls=int(state.home.team_fouls_period) if r_secs is not None else 0,
        away_team_fouls=int(state.away.team_fouls_period) if r_secs is not None else 0,
    )
    facts = ResumeFacts(
        event_id=str(state.event_id), home_id=str(state.home.team_id), away_id=str(state.away.team_id),
        home_score=int(sum(hp)), away_score=int(sum(ap)), period=period, clock_seconds=float(clock),
        possession=state.possession_side, last_seq=int(state.last_seq),
        as_of=as_of or state.built_at or _utc_now_iso(), score_source=score_source,
        tip_wallclock=min((str(e.wallclock) for e in rec.events if getattr(e, "wallclock", "")), default=""),
    )
    return state, gs, facts


def _names(state: Any, side: str) -> list[str]:
    by_id = {p.player_id: p.name for p in state.players}
    team = state.home if side == "home" else state.away
    return [by_id[pid] for pid in team.on_floor if pid in by_id]


# ------------------------------------------------------------------------------------------- the re-sim

def stable_seed(event_id: str, last_seq: int, league: str = LEAGUE) -> int:
    return zlib.crc32(f"{league}-live-resim|{event_id}|{int(last_seq)}".encode("utf-8")) & 0x7FFFFFFF


def _hist(values: Sequence[int]) -> dict[str, int]:
    return {str(k): int(v) for k, v in sorted(Counter(int(x) for x in values).items())}


def resim_live_game(inputs: Mapping[str, Any], game_state: Any, *, sims: int = DEFAULT_SIMS, base_seed: int = 0,
                    deadline: Optional[float] = None, simulate: Optional[Callable[..., Any]] = None,
                    clock: Callable[[], float] = time.monotonic, league: str = LEAGUE):
    """`sims` resumed games from `game_state`; full-game and per-half distributions.

    Hitting `deadline` before `sims` draws finish is `budget_exhausted` -- partial draws are
    DISCARDED, never published as a thinner number."""
    import numpy as np

    if sims < MIN_SIMS:
        return NcaabResimRefusal("sims_below_floor", f"{sims}<{MIN_SIMS}")
    if simulate is None:
        engine = ncaab_engine(league=league)
        kwargs = {k: inputs[k] for k in _ENGINE_KWARGS}

        def simulate(rng, gs):  # noqa: E306
            return engine.simulate_pbp_game_boxscore(rng=rng, **kwargs, state=gs)

    rng = np.random.default_rng(int(base_seed))
    totals: list[int] = []
    margins: list[int] = []
    # Regulation periods per sim: halves for the men, quarters for the women (`league="wncaab"`).
    regulation = _regulation_periods(league)
    periods: list[tuple[tuple[int, ...], tuple[int, ...]]] = []
    for i in range(int(sims)):
        if deadline is not None and clock() >= deadline:
            return NcaabResimRefusal("budget_exhausted", f"{i}/{sims}")
        try:
            _hb, _ab, hq, aq = simulate(rng, game_state)
        except Exception as exc:  # noqa: BLE001
            return NcaabResimRefusal("engine_resume_rejected", type(exc).__name__)
        h, a = int(sum(hq)), int(sum(aq))
        totals.append(h + a)
        margins.append(h - a)
        if len(hq) >= regulation and len(aq) >= regulation:
            periods.append((tuple(int(x) for x in hq[:regulation]), tuple(int(x) for x in aq[:regulation])))
    n = len(totals)
    segments: dict[str, Any] = {}
    layout = ({"h1": (0,), "h2": (1,)} if regulation == 2 else
              {"q1": (0,), "q2": (1,), "q3": (2,), "q4": (3,), "h1": (0, 1), "h2": (2, 3)})
    for name, idx in layout.items():
        tot = [sum(h[i] for i in idx) + sum(a[i] for i in idx) for h, a in periods]
        mar = [sum(h[i] for i in idx) - sum(a[i] for i in idx) for h, a in periods]
        if tot:
            segments[name] = {"total_mean": sum(tot) / len(tot), "total_dist": _hist(tot), "margin_dist": _hist(mar)}
    return {
        "sims_run": n,
        "home_win_prob": sum(1 for m in margins if m > 0) / n,
        "total_mean": float(np.mean(totals)),
        "home_margin_mean": float(np.mean(margins)),
        "total_dist": _hist(totals),
        "margin_dist": _hist(margins),
        "segments": segments,
    }


# ------------------------------------------------------------------------------------------- names

def odds_team_names(date: str, *, dirs: Optional[Sequence[Path]] = None, league: str = LEAGUE) -> dict[str, str]:
    """canonical team -> the OddsAPI name the board's rows carry, from `odds_<date>.csv`.

    `live_gameline_join` keys on exact lower-cased names, so the lane must carry the BOARD's
    spelling. Any failure -> {} and every game falls back to ESPN's display name, which the lane
    labels (`nameSource`)."""
    from syndicate.features.shared.team_aliases import canonical_team

    out: dict[str, str] = {}
    roots = list(dirs) if dirs is not None else _processed_dirs(league)
    for d in roots:
        base = Path(d).parent.parent if Path(d).name == "processed" else Path(d)
        for path in base.rglob(f"odds_{date}.csv"):
            try:
                with path.open(encoding="utf-8", newline="") as fh:
                    for row in csv.DictReader(fh):
                        for col in ("home_team", "away_team", "home_team_name", "away_team_name"):
                            name = str(row.get(col) or "").strip()
                            canon = canonical_team(league, name) if name else None
                            if canon and canon not in out:
                                out[canon] = name
            except Exception:  # noqa: BLE001
                continue
        if out:
            break
    return out


def board_name(espn_display: str, odds_names: Mapping[str, str], league: str = LEAGUE) -> tuple[str, str]:
    from syndicate.features.shared.team_aliases import canonical_team

    canon = canonical_team(league, espn_display) if espn_display else None
    if canon and canon in odds_names:
        return odds_names[canon], "odds"
    return espn_display, "espn_display"


# ------------------------------------------------------------------------------------------- margin anchor

# LIVE MARGINS ARE MARKET-ANCHORED (user 2026-11-03 "Anchor them", both leagues). The sim's margins run at about
# 0.69 of the market's (2026-11-02, 102 games), so a live spread or moneyline priced straight off the sim carried
# that scale defect as an "edge": measured on the first live women's game, ECU -26.5 read -27 pp. Pregame, the
# same defect is answered by serving the de-vigged fair (`college_game_projections`); live, that would erase the
# in-game information too. So the live FULL-GAME margin is shifted by the game's PREGAME gap -- the closing
# consensus home margin minus the pregame sim's home margin, frozen at tip -- SCALED BY THE SHARE OF REGULATION
# STILL TO PLAY (the gap is the sim's error over the possessions it simulates; the scored points are real). At the
# tip the anchored margin IS the market's; every edge after that comes from what the sim makes of the game state.
# Totals stay raw (the pregame decision), and so do the half/quarter histograms, which the live join does not price.
#
# A game with no closing spread or no pregame sim margin REFUSES by name (`no_margin_anchor`) before it is simmed:
# a raw margin would bring the defect back, and such a game has no priced board row to lose. ABSENT IS ON (the
# user's decision); `SYNDICATE_COLLEGE_LIVE_MARGIN_ANCHOR=0` serves the raw sim again.
MARGIN_ANCHOR_ENV = "SYNDICATE_COLLEGE_LIVE_MARGIN_ANCHOR"
_ANCHOR_SOURCES_TTL_S = 600.0


def margin_anchor_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    raw = str((env if env is not None else os.environ).get(MARGIN_ANCHOR_ENV, "") or "").strip().lower()
    return raw not in {"0", "false", "off", "no"}


@dataclass(frozen=True)
class MarginAnchor:
    market_home_margin: float  # closing consensus, in the LIVE home orientation
    sim_home_margin: float     # the pregame sim's mean, same orientation
    books: int

    @property
    def offset(self) -> float:
        return self.market_home_margin - self.sim_home_margin

    def as_dict(self) -> dict[str, Any]:
        return {"marketHomeMargin": round(self.market_home_margin, 2), "simHomeMargin": round(self.sim_home_margin, 2),
                "offset": round(self.offset, 2), "books": self.books, "source": "book_quotes_close+pregame_sim"}


def _join_key(league: str, name: Any) -> str:
    from syndicate.features.shared.team_aliases import chip_join_key

    text = str(name or "").strip()
    return chip_join_key(league, text) or text.lower()


def _utc(value: Any) -> Optional[datetime]:
    """An ISO timestamp as an aware UTC datetime, or None. PARSED, never compared as text: the quote log writes
    `commence_time` as `2026-11-03 16:00:00+00:00` and `snapshot_ts` as `2026-11-03T16:00:02...`, and as strings
    every same-day quote sorts AFTER its own commence (' ' < 'T') -- measured on the 11-03 women's shard."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# (observed at, book, home spread line, commence) for one game's full-game home-spread quotes.
SpreadQuote = tuple[datetime, str, float, Optional[datetime]]


def home_spread_quotes(league: str, date_str: str, *, rows: Optional[Any] = None) -> dict[tuple[str, str], list[SpreadQuote]]:
    """(home_key, away_key) -> every full-game HOME spread quote of the date's quote-log shard (Central kickoff date)."""
    from collections import defaultdict

    if rows is None:
        from syndicate.features.shared.odds_book_quotes import iter_book_quotes

        rows = iter_book_quotes(league, date_str)
    out: dict[tuple[str, str], list[SpreadQuote]] = defaultdict(list)
    for row in rows:
        if (not isinstance(row, Mapping) or row.get("market") != "spreads" or row.get("selection") != "home"
                or str(row.get("segment") or "full") not in ("full", "full_game") or row.get("line") is None):
            continue
        seen = _utc(row.get("snapshot_ts") or row.get("captured_at"))
        if seen is None:
            continue
        try:
            line = float(row["line"])
        except (TypeError, ValueError):
            continue
        key = (_join_key(league, row.get("home_team")), _join_key(league, row.get("away_team")))
        out[key].append((seen, str(row.get("bookmaker") or ""), line, _utc(row.get("commence_time"))))
    return dict(out)


def closing_home_margin(quotes: Sequence[SpreadQuote], *, tip: Optional[datetime] = None) -> Optional[tuple[float, int]]:
    """(closing consensus home margin, books): each book's LAST home spread observed strictly before the tip,
    then the median across books (per book, not per line, so a line a book stopped offering never votes; the
    rule of `odds_book_quotes.closing_quotes`). Home margin = -home spread.

    The cutoff is the ACTUAL tip -- the first play's ESPN wall clock -- when known, else the scheduled commence.
    College games tip minutes after the listed time, and the women's feed can post a game's first line at the
    listed time itself (ECU 11-03: first quote 16:00:02Z for a 16:00:00Z listing)."""
    from statistics import median

    latest: dict[str, tuple[datetime, float]] = {}
    for seen, book, line, commence in quotes:
        cutoff = tip or commence
        if cutoff is None or seen >= cutoff:
            continue
        if book not in latest or seen > latest[book][0]:
            latest[book] = (seen, line)
    if not latest:
        return None
    return float(median(-line for _seen, line in latest.values())), len(latest)


def pregame_sim_margins(league: str, date_str: str) -> dict[str, tuple[float, str]]:
    """ESPN event id -> (pregame sim home margin, the sim's home ESPN id), from `pregame_sim_<date>.json`."""
    from syndicate.features.college_basketball.pregame_sim import read_pregame_sims

    out: dict[str, tuple[float, str]] = {}
    for event_id, game in ((read_pregame_sims(str(date_str), league) or {}).get("games") or {}).items():
        margin = game.get("home_margin_mean") if isinstance(game, Mapping) else None
        if margin is None:
            continue
        out[str(event_id)] = (float(margin), str((game.get("home") or {}).get("espn_id") or ""))
    return out


def margin_anchor_for(facts: ResumeFacts, names: Mapping[str, str], *, league: str,
                      market: Mapping[tuple[str, str], Sequence[SpreadQuote]],
                      sims: Mapping[str, tuple[float, str]]):
    """The game's anchor in the LIVE home orientation, or `no_margin_anchor`. A neutral-site game can be oriented
    differently by the odds feed or the slate than by ESPN's summary; both are flipped onto the live home side."""
    sim = sims.get(str(facts.event_id))
    if sim is None:
        return NcaabResimRefusal("no_margin_anchor", "no pregame sim margin for this game")
    sim_margin, sim_home = sim
    if sim_home and sim_home not in (str(facts.home_id), str(facts.away_id)):
        return NcaabResimRefusal("no_margin_anchor", f"pregame sim home {sim_home} is neither side")
    if sim_home and sim_home != str(facts.home_id):
        sim_margin = -sim_margin
    home, away = _join_key(league, names.get("home")), _join_key(league, names.get("away"))
    tip = _utc(facts.tip_wallclock)
    for key, flip in (((home, away), False), ((away, home), True)):
        close = closing_home_margin(market.get(key) or (), tip=tip)
        if close is not None:
            market_margin, books = close
            return MarginAnchor(market_home_margin=-market_margin if flip else market_margin,
                                sim_home_margin=sim_margin, books=books)
    return NcaabResimRefusal("no_margin_anchor", "no closing full-game spread in the quote log")


def remaining_regulation_fraction(facts: ResumeFacts, league: str = LEAGUE) -> float:
    """Share of regulation still to play at the resume point: 1.0 at the tip, 0.5 at halftime, 0.0 in overtime."""
    from syndicate.features.college_basketball.league import league_for

    spec = league_for(league)
    period = int(facts.period or 1)
    if period > spec.periods:
        return 0.0
    remaining = (spec.periods - period) * spec.period_seconds + max(0.0, min(float(facts.clock_seconds or 0.0), spec.period_seconds))
    return max(0.0, min(1.0, remaining / float(spec.periods * spec.period_seconds)))


def anchor_result(result: Mapping[str, Any], anchor: MarginAnchor, *, remaining_fraction: float = 1.0) -> dict[str, Any]:
    """Shift the full-game margin histogram by the anchor's offset SCALED BY THE SHARE OF REGULATION STILL TO
    PLAY, and re-derive the win probability from it.

    WHY SCALED (measured 2026-11-03 16:45Z, the first anchored board build): the pregame gap is the sim's error over
    a WHOLE game -- its rates understate the stronger side -- and the points already scored are real, not simmed.
    Shifting the full +10.37 at 2:11 of the women's Q2 (55% of regulation left) moved ECU's margin 17.5 -> 27.8
    against a live market of 21.5: a +20 pp spread "edge" that was the anchor itself. Scaled, the shift is +5.8
    (-> 23.2). At the tip the two agree.

    The join reads integer margins and integer counts (`live_gameline_join._two_way_home_prob`), so a fractional
    offset splits each bucket between its two neighbours, allocated by CUMULATIVE rounding: the counts stay
    integers, their total is unchanged, and the mean moves by the offset to within 1/sims. A shifted margin of 0
    (a game cannot end tied) counts half to each side. The sim's own numbers stay on the result (`raw_*`)."""
    import math

    fraction = max(0.0, min(1.0, float(remaining_fraction)))
    offset = float(anchor.offset) * fraction
    base = math.floor(offset)
    frac = offset - base
    shifted: Counter = Counter()
    cumulative = 0.0
    allocated = 0
    for raw_margin, raw_count in sorted(((int(k), int(v)) for k, v in (result.get("margin_dist") or {}).items()), key=lambda kv: kv[0]):
        cumulative += raw_count * frac
        up = int(round(cumulative)) - allocated
        allocated += up
        if raw_count - up:
            shifted[raw_margin + base] += raw_count - up
        if up:
            shifted[raw_margin + base + 1] += up
    n = sum(shifted.values())
    out = dict(result)
    out["raw_home_win_prob"] = result.get("home_win_prob")
    out["raw_home_margin_mean"] = result.get("home_margin_mean")
    out["margin_anchor"] = {**anchor.as_dict(), "remainingFraction": round(fraction, 4), "appliedOffset": round(offset, 2)}
    if n <= 0:
        return out
    out["margin_dist"] = {str(m): c for m, c in sorted(shifted.items())}
    out["home_margin_mean"] = sum(m * c for m, c in shifted.items()) / n
    out["home_win_prob"] = (sum(c for m, c in shifted.items() if m > 0) + 0.5 * shifted.get(0, 0)) / n
    return out


_ANCHOR_CACHE: dict[tuple[str, str], MarginAnchor] = {}
_ANCHOR_SOURCES: dict[tuple[str, str], tuple[float, Any, Any]] = {}


def _anchor_sources(league: str, date_str: str, clock: Callable[[], float] = time.monotonic):
    """(closing margins, pregame sim margins) for a league-date, read at most every 10 minutes. An anchor once found
    is cached per game for the process (`_ANCHOR_CACHE`), so it never drifts during a game."""
    key = (league, str(date_str))
    hit = _ANCHOR_SOURCES.get(key)
    if hit is not None and clock() - hit[0] < _ANCHOR_SOURCES_TTL_S:
        return hit[1], hit[2]
    market = home_spread_quotes(league, str(date_str))
    sims = pregame_sim_margins(league, str(date_str))
    _ANCHOR_SOURCES[key] = (clock(), market, sims)
    return market, sims


# ------------------------------------------------------------------------------------------- the lane

def build_game_lens(facts: Optional[ResumeFacts], result: Any, *, live_state_as_of: str = "",
                    match_report: Optional[Mapping[str, Any]] = None,
                    provenance: Optional[Mapping[str, Any]] = None) -> list[dict[str, Any]]:
    """Exactly one lane, honestly stamped. A refusal is a lane with NO probability (`#414`)."""
    if isinstance(result, NcaabResimRefusal) or facts is None:
        reason = result.reason if isinstance(result, NcaabResimRefusal) else "no_resume_state"
        detail = result.detail if isinstance(result, NcaabResimRefusal) else ""
        return [{
            "key": "live", "label": "Live", "source": PREGAME_LENS_SOURCE,
            "closed": reason in ("game_final", "regulation_over"),
            "liveResimRefusal": reason, "liveResimRefusalDetail": detail[:200],
            "liveStateAsOf": live_state_as_of,
        }]
    lane = {
        "key": "live", "label": "Live", "source": LIVE_RESIM_LENS_SOURCE, "closed": False,
        "modelHomeWinProb": result["home_win_prob"],
        "simsRun": result["sims_run"],
        "liveStateAsOf": live_state_as_of or facts.as_of,
        "projection": {
            "homeMargin": result["home_margin_mean"],
            "total": result["total_mean"],
            "homeScore": facts.home_score,
            "awayScore": facts.away_score,
            "period": facts.period,
            "clockSeconds": facts.clock_seconds,
            "scoreSource": facts.score_source,
            "totalRunsDist": result["total_dist"],
            "marginDist": result["margin_dist"],
            "segments": result.get("segments") or {},
        },
        "resumeMatch": dict(match_report or {}),
        "inputs": dict(provenance or {}),
    }
    if result.get("margin_anchor"):
        # The served margin is anchored; the sim's own numbers stay beside it.
        lane["rawModelHomeWinProb"] = result.get("raw_home_win_prob")
        lane["projection"]["rawHomeMargin"] = result.get("raw_home_margin_mean")
        lane["projection"]["marginAnchor"] = result["margin_anchor"]
    return [lane]


def _lane_row(event_id: str, names: Mapping[str, str], facts: Optional[ResumeFacts], result: Any,
              match: Optional[Mapping[str, Any]] = None, provenance: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    return {
        "event_id": event_id,
        # FULL BOARD NAMES under `home`/`away` on success AND refusal (NHL's rule): a refusal the board
        # cannot key is invisible.
        "home": names.get("home", ""),
        "away": names.get("away", ""),
        "home_name": names.get("home", ""),
        "away_name": names.get("away", ""),
        "home_id": names.get("home_id", ""),
        "away_id": names.get("away_id", ""),
        "nameSource": names.get("source", ""),
        "status": {"detailedState": "In Progress" if facts else "Unknown"},
        "gameLens": build_game_lens(facts, result, live_state_as_of=facts.as_of if facts else "",
                                    match_report=match, provenance=provenance),
    }


def _refusals_by_reason(games: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for g in games:
        for lane in g.get("gameLens") or []:
            if lane.get("source") == PREGAME_LENS_SOURCE:
                r = str(lane.get("liveResimRefusal") or "unknown")
                out[r] = out.get(r, 0) + 1
    return out


def live_lens_snapshot_path(league: str = LEAGUE) -> Path:
    from syndicate.features.shared.refresh_state_store import data_root

    return data_root() / "live" / f"{league}_live_resim.json"


def _previous_lanes(date_str: str, league: str = LEAGUE) -> dict[str, dict[str, Any]]:
    """The last published snapshot's game rows for this date, keyed by event id (for carry-forward)."""
    try:
        from syndicate.features.shared.refresh_state_store import read_json_file

        prev = read_json_file(live_lens_snapshot_path(league))
    except Exception:  # noqa: BLE001
        return {}
    if not isinstance(prev, Mapping) or str(prev.get("date")) != str(date_str):
        return {}
    return {str(g.get("event_id")): dict(g) for g in prev.get("games") or [] if isinstance(g, Mapping)}


# Keyed by date for NCAAB (its key since P4) and by "<league>|<date>" for any other league, so the two
# threads never move each other's cursor.
_ROTATION_CURSOR: dict[str, int] = {}


def _cursor_key(date_str: str, league: str) -> str:
    return str(date_str) if league == LEAGUE else f"{league}|{date_str}"


def _carry(game: Mapping[str, Any]) -> dict[str, Any]:
    """A previous tick's game row, re-published unchanged except for the carry marks. The LANE flag is
    what the join reads (`live_gameline_join`: `liveStateCarriedForward`, MLB's convention); its
    `liveStateAsOf` stays the time it was computed, so freshness is judged on the real age."""
    out = {**game, "carriedForward": True}
    out["gameLens"] = [{**lane, "liveStateCarriedForward": True} for lane in game.get("gameLens") or []]
    return out


def _neutral(summary: Mapping[str, Any]) -> bool:
    comp = ((summary.get("header") or {}).get("competitions") or [{}])[0]
    return bool(comp.get("neutralSite"))


def _espn_names(summary: Mapping[str, Any]) -> dict[str, str]:
    comp = ((summary.get("header") or {}).get("competitions") or [{}])[0]
    out: dict[str, str] = {}
    for c in comp.get("competitors") or []:
        side = str(c.get("homeAway") or "")
        team = c.get("team") or {}
        if side in ("home", "away"):
            out[side] = str(team.get("displayName") or team.get("location") or "")
            out[f"{side}_id"] = str(team.get("id") or c.get("id") or "")
    return out


def build_live_lens_snapshot(date_str: str, *, sims: int = DEFAULT_SIMS, budget_seconds: float = DEFAULT_BUDGET_SECONDS,
                             fetch_scoreboard: Optional[Callable[..., Any]] = None,
                             fetch_summary: Optional[Callable[..., Any]] = None,
                             dirs: Optional[Sequence[Path]] = None,
                             previous: Optional[Mapping[str, Mapping[str, Any]]] = None,
                             clock: Callable[[], float] = time.monotonic, league: str = LEAGUE,
                             d1_ids: Optional[frozenset[str]] = None) -> dict[str, Any]:
    from syndicate.features.shared import basketball_pbp as pbp
    from syndicate.features.nba.live_resim import map_state_names
    from syndicate.features.ncaab import slate
    from syndicate.features.shared.request_path_guard import refuse_if_compute_in_request_path

    refuse_if_compute_in_request_path(f"{league}_live_resim_snapshot")
    fetch_scoreboard = fetch_scoreboard or pbp.fetch_scoreboard
    fetch_summary = fetch_summary or pbp.fetch_summary
    started = clock()
    deadline = started + float(budget_seconds)
    previous = dict(previous) if previous is not None else _previous_lanes(date_str, league)
    if dirs is None and league != LEAGUE:
        dirs = _processed_dirs(league)
    day = dt.date.fromisoformat(str(date_str))
    priors = load_player_priors(day, dirs=dirs)
    odds_names = odds_team_names(str(date_str), dirs=dirs, league=league)
    events = [ev for ev in pbp.scoreboard_events(fetch_scoreboard(league, str(date_str).replace("-", "")))
              if str(ev.get("status_state") or ev.get("state") or "").lower() == "in"]
    # BOARD GAMES ONLY (2026-11-04, lane wncaab-module): `groups=50` returns every game a D1 team plays, and
    # the board keeps D1 vs D1 (`slate.parse_scoreboard`). A game against a non-D1 school cost a summary
    # fetch every tick only to be refused for its unrated side -- 3 of the 4 live women's games at midday
    # on 11-04. Same registry as the slate; a side ESPN does not name is kept and refused downstream by
    # name, and an empty registry filters nothing rather than emptying the tick.
    d1 = slate._d1_ids(league) if d1_ids is None else d1_ids
    live_count = len(events)
    if d1:
        events = [ev for ev in events
                  if {s for s in (str(ev.get("home_id") or ""), str(ev.get("away_id") or "")) if s} <= d1]
    ids = [str(ev.get("event_id") or ev.get("id") or "") for ev in events]
    cursor_key = _cursor_key(str(date_str), league)
    anchor_on = margin_anchor_enabled()
    if anchor_on:
        # Never carry forward a priced lane computed before the anchor existed: it would republish the raw margin.
        previous = {eid: g for eid, g in previous.items()
                    if all(lane.get("source") != LIVE_RESIM_LENS_SOURCE or (lane.get("projection") or {}).get("marginAnchor")
                           for lane in g.get("gameLens") or [])}
    start = _ROTATION_CURSOR.get(cursor_key, 0) % max(1, len(ids)) if ids else 0
    order = ids[start:] + ids[:start]
    games: dict[str, dict[str, Any]] = {}
    counts = {"live": len(ids), "resimmed": 0, "refused": 0, "carried_forward": 0, "not_reached": 0,
              "dropped_non_d1": live_count - len(ids)}
    next_cursor = start
    for pos, event_id in enumerate(order):
        if clock() >= deadline:
            for rest in order[pos:]:
                if rest in previous:
                    games[rest] = _carry(previous[rest])
                    counts["carried_forward"] += 1
                else:
                    games[rest] = _lane_row(rest, {}, None, NcaabResimRefusal("budget_exhausted", "not_reached"))
                    counts["not_reached"] += 1
            break
        next_cursor = (start + pos + 1) % max(1, len(ids))
        try:
            summary = fetch_summary(league, event_id)
        except Exception as exc:  # noqa: BLE001
            games[event_id] = _lane_row(event_id, {}, None, NcaabResimRefusal("summary_fetch_failed", type(exc).__name__))
            counts["refused"] += 1
            continue
        espn = _espn_names(summary)
        home_name, src_h = board_name(espn.get("home", ""), odds_names, league=league)
        away_name, src_a = board_name(espn.get("away", ""), odds_names, league=league)
        names = {"home": home_name, "away": away_name, "home_id": espn.get("home_id", ""),
                 "away_id": espn.get("away_id", ""), "source": src_h if src_h == src_a else f"{src_a}/{src_h}"}
        resumed = resume_from_summary(summary, date=str(date_str), league=league)
        if isinstance(resumed, NcaabResimRefusal):
            games[event_id] = _lane_row(event_id, names, None, resumed)
            counts["refused"] += 1
            continue
        _state, gs, facts = resumed
        inputs = build_engine_inputs(str(date_str), facts.home_id, facts.away_id, neutral=_neutral(summary),
                                     priors=priors, dirs=dirs, league=league)
        if isinstance(inputs, NcaabResimRefusal):
            games[event_id] = _lane_row(event_id, names, facts, inputs)
            counts["refused"] += 1
            continue
        anchor = None
        if anchor_on:
            anchor = _ANCHOR_CACHE.get((league, str(facts.event_id)))
            if anchor is None:
                try:
                    market, sim_margins = _anchor_sources(league, str(date_str))
                    anchor = margin_anchor_for(facts, names, league=league, market=market, sims=sim_margins)
                except Exception as exc:  # noqa: BLE001 -- unreadable sources are this game's named refusal
                    anchor = NcaabResimRefusal("no_margin_anchor", f"anchor sources unreadable: {type(exc).__name__}")
                if isinstance(anchor, MarginAnchor):
                    _ANCHOR_CACHE[(league, str(facts.event_id))] = anchor
            if isinstance(anchor, NcaabResimRefusal):
                games[event_id] = _lane_row(event_id, names, facts, anchor)
                counts["refused"] += 1
                continue
        gs, match = map_state_names(gs, inputs["home_players"], inputs["away_players"])
        result = resim_live_game(inputs, gs, sims=sims, base_seed=stable_seed(facts.event_id, facts.last_seq, league),
                                 deadline=deadline, clock=clock, league=league)
        if isinstance(anchor, MarginAnchor) and not isinstance(result, NcaabResimRefusal):
            result = anchor_result(result, anchor, remaining_fraction=remaining_regulation_fraction(facts, league))
        if isinstance(result, NcaabResimRefusal) and result.reason == "budget_exhausted" and event_id in previous:
            games[event_id] = _carry(previous[event_id])
            counts["carried_forward"] += 1
            next_cursor = (start + pos) % max(1, len(ids))
            continue
        games[event_id] = _lane_row(event_id, names, facts, result, match, inputs.get("_provenance"))
        counts["resimmed" if not isinstance(result, NcaabResimRefusal) else "refused"] += 1
    _ROTATION_CURSOR[cursor_key] = next_cursor
    out_games = [games[i] for i in ids if i in games]
    return {
        "sport": league,
        "date": str(date_str),
        "generatedAt": _utc_now_iso(),
        "source": LIVE_RESIM_LENS_SOURCE,
        "simsPerGame": int(sims),
        "budgetSeconds": float(budget_seconds),
        "elapsedSeconds": round(clock() - started, 2),
        "playerPriors": priors.source if isinstance(priors, PlayerPriors) else f"refused:{priors.reason}",
        "oddsNamesIndexed": len(odds_names),
        "marginAnchor": "on" if anchor_on else "off",
        "counts": counts,
        "games": out_games,
        "refusalsByReason": _refusals_by_reason(out_games),
    }


# ------------------------------------------------------------------------------------------- size, tick, loop

def fit_snapshot_to_budget(snapshot: dict[str, Any], *, max_bytes: int = MAX_SNAPSHOT_BYTES,
                           max_lane_bytes: int = MAX_LANE_BYTES) -> tuple[dict[str, Any], int]:
    """Measure; drop the HISTOGRAMS of any lane over its per-game budget (the means and the
    probability stay), then of every lane if the whole snapshot is still over. Game lines are
    never dropped for size; a lane that lost its distribution says so (`distDroppedForSize`)."""
    def size(obj: Any) -> int:
        return len(json.dumps(obj, separators=(",", ":")))

    def strip(game: dict[str, Any]) -> None:
        for lane in game.get("gameLens") or []:
            proj = lane.get("projection")
            if isinstance(proj, dict) and proj.get("totalRunsDist") is not None:
                for key in ("totalRunsDist", "marginDist", "segments"):
                    proj.pop(key, None)
                lane["distDroppedForSize"] = True

    for g in snapshot.get("games") or []:
        if size(g) > max_lane_bytes:
            strip(g)
    total = size(snapshot)
    if total > max_bytes:
        for g in snapshot.get("games") or []:
            strip(g)
        snapshot["distDroppedForSize"] = True
        total = size(snapshot)
    return snapshot, total


LIVE_RESIM_ENV = "SYNDICATE_NCAAB_LIVE_RESIM"
LIVE_RESIM_INTERVAL_ENV = "SYNDICATE_NCAAB_LIVE_RESIM_INTERVAL_SECONDS"
WNCAAB_LIVE_RESIM_ENV = "SYNDICATE_WNCAAB_LIVE_RESIM"

_LOOP_THREADS: dict[str, threading.Thread] = {}
_LOOP_STOP = threading.Event()
_LOOP_LOCK = threading.Lock()
_ON = {"1", "true", "on", "yes"}


def _env_name(league: str, suffix: str = "") -> str:
    return f"SYNDICATE_{league.upper()}_LIVE_RESIM{suffix}"


def ncaab_live_resim_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    raw = str((env if env is not None else os.environ).get(LIVE_RESIM_ENV, "") or "").strip().lower()
    return raw in _ON


def wncaab_live_resim_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    """`SYNDICATE_WNCAAB_LIVE_RESIM` when set; ABSENT, the men's switch (module docstring says why)."""
    source = env if env is not None else os.environ
    raw = str(source.get(WNCAAB_LIVE_RESIM_ENV, "") or "").strip().lower()
    if not raw:
        return ncaab_live_resim_enabled(source)
    return raw in _ON


def live_resim_enabled(league: str = LEAGUE, env: Optional[Mapping[str, str]] = None) -> bool:
    return wncaab_live_resim_enabled(env) if league == WOMENS_LEAGUE else ncaab_live_resim_enabled(env)


def _interval_seconds(env: Optional[Mapping[str, str]] = None, league: str = LEAGUE) -> float:
    raw = str((env if env is not None else os.environ).get(_env_name(league, "_INTERVAL_SECONDS"), "") or "").strip()
    try:
        return max(30.0, float(raw or 120))
    except ValueError:
        return 120.0


def _tick_kwargs(league: str, env: Optional[Mapping[str, str]] = None) -> dict[str, Any]:
    """The women's sims / budget from their own env names; NCAAB keeps its import-time defaults."""
    if league == LEAGUE:
        return {}
    source = env if env is not None else os.environ
    try:
        sims = int(str(source.get(_env_name(league, "_SIMS"), "") or "").strip() or DEFAULT_SIMS)
    except ValueError:
        sims = DEFAULT_SIMS
    try:
        budget = float(str(source.get(_env_name(league, "_BUDGET_SECONDS"), "") or "").strip() or WNCAAB_DEFAULT_BUDGET_SECONDS)
    except ValueError:
        budget = WNCAAB_DEFAULT_BUDGET_SECONDS
    return {"sims": sims, "budget_seconds": budget}


def run_live_resim_tick(date_str: Optional[str] = None, *, league: str = LEAGUE, **kwargs: Any) -> dict[str, Any]:
    """One tick: build, size-fit, write. Prints one line, prefix <LEAGUE>_LIVE_RESIM_TICK."""
    from syndicate.features.shared.refresh_state_store import write_json_file
    from syndicate.features.shared.timezone import central_today_iso

    date_str = date_str or central_today_iso()
    started = time.monotonic()
    snapshot = build_live_lens_snapshot(date_str, league=league, **{**_tick_kwargs(league), **kwargs})
    snapshot, size = fit_snapshot_to_budget(snapshot)
    status = {
        "date": date_str,
        **(snapshot.get("counts") or {}),
        "refusals": snapshot.get("refusalsByReason") or {},
        "bytes": size,
        "written": False,
    }
    if size <= MAX_SNAPSHOT_BYTES:
        write_json_file(live_lens_snapshot_path(league), snapshot)
        status["written"] = True
    status["elapsed_s"] = round(time.monotonic() - started, 1)
    print(f"{league.upper()}_LIVE_RESIM_TICK " + " ".join(f"{k}={v}" for k, v in status.items()), flush=True)
    return status


def _loop(league: str = LEAGUE) -> None:
    while not _LOOP_STOP.is_set():
        try:
            run_live_resim_tick(league=league)
        except Exception as exc:  # noqa: BLE001
            print(f"{league.upper()}_LIVE_RESIM_TICK_ERROR {type(exc).__name__}: {str(exc)[:300]}", flush=True)
        _LOOP_STOP.wait(_interval_seconds(league=league))


def _start_loop(league: str) -> bool:
    if not live_resim_enabled(league):
        return False
    with _LOOP_LOCK:
        running = _LOOP_THREADS.get(league)
        if running is not None and running.is_alive():
            return False
        _LOOP_STOP.clear()
        thread = threading.Thread(target=_loop, args=(league,), name=f"syndicate-{league}-live-resim", daemon=True)
        _LOOP_THREADS[league] = thread
        thread.start()
        print(f"{league.upper()}_LIVE_RESIM_LOOP_STARTED interval_s={_interval_seconds(league=league)}", flush=True)
        return True


def start_wncaab_live_resim_loop() -> bool:
    """The women's thread, once per process, only when `wncaab_live_resim_enabled()`."""
    return _start_loop(WOMENS_LEAGUE)


def start_ncaab_live_resim_loop() -> bool:
    """Start the men's thread once per process, only when `SYNDICATE_NCAAB_LIVE_RESIM` is on. Returns whether
    THE MEN'S thread started.

    It also starts the women's thread (`start_wncaab_live_resim_loop`, its own switch), because this is the
    one call `live_lens_loop` makes for college basketball and that file belongs to another lane
    (wnba-native-live-cutover)."""
    started = _start_loop(LEAGUE)
    try:
        start_wncaab_live_resim_loop()
    except Exception as exc:  # noqa: BLE001 -- never let the women's thread stop the men's
        print(f"WNCAAB_LIVE_RESIM_LOOP_START_FAILED {type(exc).__name__}: {exc}", flush=True)
    return started
