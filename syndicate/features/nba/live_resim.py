"""NBA LIVE RE-SIM: the native possession engine resumed from the live game state.

    resume_from_summary(summary)            -> (LiveGameState, GameState, ResumeFacts) | NbaResimRefusal
    load_engine_inputs(date, home, away)    -> dict (the pregame engine kwargs) | NbaResimRefusal
    resim_live_game(inputs, game_state, ...)-> result dict | NbaResimRefusal
    build_game_lens(...)                    -> exactly one lane, honestly stamped
    build_live_lens_snapshot(date)          -> the shared `gameLens` snapshot

Phase P3 of `docs/ai_context/basketball_live_native_plan.md`; refusal design in
`docs/ai_context/nba_live_resim_refusal_design.md`; template `syndicate/features/nhl/live_resim.py`.

--------------------------------------------------------------------------
NOTHING HERE IMPORTS `vendor.`
--------------------------------------------------------------------------

Live state comes from P2 (`shared/basketball_live_state.build_live_game_state`, ESPN summary parsed by
Syndicate code). The engine is P1 (`syndicate.features.basketball_engine`, `GameState` resume). The
engine's per-game inputs -- player frames, lineups and weights, `EventSimConfig`, team adjustments,
quarter targets -- are the SAME objects the pregame sim handed the engine, persisted at pregame time by
`persist_engine_inputs` and read back here. The vendored orchestrator that BUILT them pregame is never
called on the live path; rebuilding inputs live would both depend on it and make the live number rest on
different inputs from the pregame one.

--------------------------------------------------------------------------
REFUSE RATHER THAN DEGRADE
--------------------------------------------------------------------------

Every path that cannot produce a resumed-sim number returns `NbaResimRefusal` with a STABLE token
(`docs/ai_context/nba_live_resim_refusal_design.md` §2). A refusal publishes a lane stamped
`pregame_only`, which `live_gameline_join.LIVE_LENS_SOURCES_BY_SPORT["nba"]` does not accept, and which
carries NO probability -- not the pregame one, not a zero (`#414`). The budget is a refusal, not fewer
sims: `simsRun` is what the join's precision gate trusts.

--------------------------------------------------------------------------
RUNS ON A WORKER. NEVER IN A REQUEST HANDLER.
--------------------------------------------------------------------------

`build_live_lens_snapshot` is a simulation and calls `refuse_if_compute_in_request_path`.

--------------------------------------------------------------------------
A GAME STILL LIVE AT MIDNIGHT CENTRAL (#776, lane nba-live-resim-midnight; the college fix is #774)
--------------------------------------------------------------------------

The loop's tick date is the Central date, and at 00:00 CT it read only the NEW date's scoreboard, so a West
Coast game still going at midnight was never re-simmed again. Measured 2026-11-10 on the fleet's own history
(`live_resim_history`, every regular-season slate 10-20..11-09 = 20; 11-03 had no games) and each slate checked
against ESPN's last play: 4 of 20 had regulation or overtime play after the roll -- POR @ LAL 10-27 (Q3 4:05 at midnight CDT, 56.7 min to the end), MIA @ LAC 11-04
(Q4 0:02.7 then overtime, 21.1 min), POR @ LAL 11-06 (Q4 0:14.9, 4.9 min), LAL @ LAC 10-28 (Q4 1:32, 2.6 min). On
the fleet logs, the joins before the 11-05 and 11-07 rolls priced 25-76 NBA game-line rows; every join after it
read `games_in_snapshot=0` (0 projected, `no_live_gameline_projection` on 103-127 rows) until the game ended.

So the LOOP's tick (no explicit date) re-sims the previous date's in-progress games first, for
`SYNDICATE_NBA_LIVE_RESIM_PRIOR_DATE_HOURS` after midnight Central (absent = 4 h, "0" = off, capped at 12), on
THAT date's persisted inputs and props file, and publishes them in the same snapshot with `slateDate` on each row.
The board's game-line join and the chips key this file by event id / team names, never by its `date`, so the
carryover board finds the lane with no reader change. Each date's build gets its OWN rows of the last snapshot as
`previous` (`previous_for_slate`), so stalest-first, the bounded carry and remembered lines run across the roll.
Today's slate gets the budget they leave. A quiet night costs one scoreboard fetch per tick, and none once every
event on it is final (`_PRIOR_SLATE_FINAL`). Tick line, inside the window only: `prior_date= prior_games=
prior_resimmed= prior_carried= prior_skip=`; `games=`, `resimmed=` and `carried=` include those games. The tick
history keeps every row in the TICK's file, as the live evidence log does, and marks a previous date's row
`slate_date`.

Two more readers follow the game across the roll. Both read THIS file, inside the same window and under the same switch:
- live PROPS (#777): the live-lens loop builds the page lens for the new date and appends the previous date's rows
  from here, `slateDate` kept (`nba/live_lens._attach_native_resim` -> `_attach_prior_slate`). So the carryover
  board's props join and web's read-time prop refresh still find them.
- sportsbook QUOTES (#782): when today has no NBA game live, the live-odds-worker's NBA in-play pull launches for the
  previous date if a row of that date here reads `status.detailedState` "In Progress" and `generatedAt` is at
  most 600 s old (`nba/live_lens.prior_slate_in_play`, `run_live_odds_refresh_worker._launch_autorun_nba_live_refresh`).
  So that date's quotes stay observed, and the board's opportunity gate does not dead-lane the game.
`slateDate`, the "In Progress" stamp and an offset-aware `generatedAt` are therefore a contract with those readers:
changing one of them stops the props and the pulls with no error.
"""

from __future__ import annotations

import json
import math
import os
import pickle
import time
import unicodedata
import zlib
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

LIVE_RESIM_LENS_SOURCE = "live_resim"
PREGAME_LENS_SOURCE = "pregame_only"

LEAGUE = "nba"
_REGULATION_PERIODS = 4

# Sims per game per tick, and the tick's wall-clock budget. Measured 2026-10-09 on recorded production
# inputs (Idle, loaded host): 570-690 ms/draw pregame, 415-505 end Q1, 145-215 end Q3, 76-107 at 5:00 Q4.
DEFAULT_SIMS = int(os.environ.get("SYNDICATE_NBA_LIVE_RESIM_SIMS", "200") or 200)
DEFAULT_BUDGET_SECONDS = float(os.environ.get("SYNDICATE_NBA_LIVE_RESIM_BUDGET_SECONDS", "240") or 240)
MIN_SIMS = 100  # below this a lane is refused (`sims_below_floor`), never published thin
# How far ESPN's header score may run ahead of the play log, per side, and still be read as the log lagging (one
# play: a 3, or an and-one). More than this, or the log AHEAD of the header, is `pbp_score_mismatch`.
MAX_HEADER_LEAD = 3

ENGINE_INPUTS_DIRNAME = "engine_inputs"
ENGINE_INPUTS_SCHEMA = 1
_INPUT_KEYS = (
    "home_players", "away_players", "cfg", "home_lineups", "away_lineups", "home_lineup_weights",
    "away_lineup_weights", "target_home_points", "target_away_points", "quarters", "home_team_adj",
    "away_team_adj",
)


# Tricode -> the OddsAPI full name. `live_gameline_join` keys games on (away, home) NAMES and the board's rows
# carry OddsAPI names; ESPN's displayName differs for at least the Clippers ("LA Clippers"), so names are not
# taken from ESPN.
NBA_TEAM_NAMES: dict[str, str] = {
    "ATL": "Atlanta Hawks", "BOS": "Boston Celtics", "BKN": "Brooklyn Nets", "CHA": "Charlotte Hornets",
    "CHI": "Chicago Bulls", "CLE": "Cleveland Cavaliers", "DAL": "Dallas Mavericks", "DEN": "Denver Nuggets",
    "DET": "Detroit Pistons", "GSW": "Golden State Warriors", "HOU": "Houston Rockets", "IND": "Indiana Pacers",
    "LAC": "Los Angeles Clippers", "LAL": "Los Angeles Lakers", "MEM": "Memphis Grizzlies", "MIA": "Miami Heat",
    "MIL": "Milwaukee Bucks", "MIN": "Minnesota Timberwolves", "NOP": "New Orleans Pelicans", "NYK": "New York Knicks",
    "OKC": "Oklahoma City Thunder", "ORL": "Orlando Magic", "PHI": "Philadelphia 76ers", "PHX": "Phoenix Suns",
    "POR": "Portland Trail Blazers", "SAC": "Sacramento Kings", "SAS": "San Antonio Spurs", "TOR": "Toronto Raptors",
    "UTA": "Utah Jazz", "WAS": "Washington Wizards",
}


# Per-league tricode -> OddsAPI full name. P5 (WNBA) registers its own map with `register_team_names("wnba", ...)`.
TEAM_NAMES_BY_LEAGUE: dict[str, dict[str, str]] = {"nba": NBA_TEAM_NAMES}


def register_team_names(league: str, names: Mapping[str, str]) -> None:
    TEAM_NAMES_BY_LEAGUE[str(league).lower()] = {str(k).upper(): str(v) for k, v in names.items()}


def team_name(league: str, code: Any) -> str:
    return (TEAM_NAMES_BY_LEAGUE.get(str(league).lower()) or {}).get(str(code or "").upper(), "")


def props_csv_path(date: str, *, root: Optional[Path] = None, league: str = LEAGUE) -> Path:
    if root is None:
        from syndicate.features.shared.basketball_live_state import source_root

        root = source_root(league)
    return Path(root) / "data" / "processed" / f"oddsapi_player_props_{date}.csv"


@dataclass(frozen=True)
class NbaResimRefusal:
    """Why one game could not be re-simulated. `reason` is a stable token."""

    reason: str
    detail: str = ""


@dataclass(frozen=True)
class ResumeFacts:
    """What the lane shows beside the number: where the game was when it was resumed."""

    event_id: str
    home_code: str
    away_code: str
    home_score: int
    away_score: int
    period: int
    clock_seconds: float
    possession: Optional[str]
    last_seq: int
    as_of: str
    # "official" when the log's scoring plays sum to ESPN's header score; "pbp_lagging_header" when the header is
    # ahead by at most one play (MAX_HEADER_LEAD) and the resume uses the log's own state (<= 1 play stale).
    score_source: str = "official"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------------------------------- live state

def period_points(events: Sequence[Any], period: int) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Points per period 1..`period` from the pbp log's scoring plays (the current period partial)."""
    home = [0] * max(1, period)
    away = [0] * max(1, period)
    for ev in events:
        p = int(getattr(ev, "period", 0) or 0)
        pts = int(getattr(ev, "points", 0) or 0)
        if not pts or p < 1 or p > period:
            continue
        if ev.side == "home":
            home[p - 1] += pts
        elif ev.side == "away":
            away[p - 1] += pts
    return tuple(home), tuple(away)


def resume_from_summary(summary: Mapping[str, Any], *, date: str = "", as_of: str = "", league: str = LEAGUE):
    """ESPN summary -> (LiveGameState, GameState, ResumeFacts), or a named refusal.

    The resume point is AFTER the last logged play. At a period's end (clock 0) the engine starts the
    NEXT period from its tip; at the end of regulation a tied game resumes into overtime and a decided
    one is `regulation_over` (the market is settled or about to be)."""
    from syndicate.features.basketball_engine.resume import GameState
    from syndicate.features.shared import basketball_pbp as pbp
    from syndicate.features.shared.basketball_live_state import build_live_game_state

    if not isinstance(summary, Mapping):
        return NbaResimRefusal("summary_not_a_mapping")
    try:
        rec = pbp.reconstruct(summary, league, date=date)
        state = build_live_game_state(summary, league, date=date)
    except Exception as exc:  # noqa: BLE001 -- a feed we cannot parse is a refusal, named
        return NbaResimRefusal("live_state_unparseable", type(exc).__name__)

    status = str(state.status_state or "").lower()
    if status == "pre":
        return NbaResimRefusal("game_not_started")
    if status == "post" or state.completed:
        return NbaResimRefusal("game_final")
    if status != "in":
        # UNKNOWN IS NOT LIVE (standing rule): never resume a game whose status we cannot read.
        return NbaResimRefusal("game_state_unrecognised", status or "<empty>")
    if not state.event_id:
        return NbaResimRefusal("no_game_id")
    if not rec.events:
        return NbaResimRefusal("no_plays")
    period = int(state.period or 0)
    if period < 1:
        return NbaResimRefusal("no_period")
    clock = state.clock_left
    if clock is None or clock < 0:
        return NbaResimRefusal("no_clock")

    hp, ap = period_points(rec.events, period)
    score_source = "official"
    if (sum(hp), sum(ap)) != (state.home.score, state.away.score):
        lead_h, lead_a = state.home.score - sum(hp), state.away.score - sum(ap)
        if 0 <= lead_h <= MAX_HEADER_LEAD and 0 <= lead_a <= MAX_HEADER_LEAD:
            # ESPN's header score updates before the play reaches the log (P2, 2026-10-10). Resume from the LOG'S
            # state -- period split, clock and score all from one consistent source, at most one play stale --
            # and say so on the lane rather than refusing every such tick.
            score_source = "pbp_lagging_header"
        else:
            # The design's `pbp_score_mismatch`: the log and the official score disagree by more than one play
            # (or the log is AHEAD), so the per-period split is not trustworthy. The backtest excludes the same.
            return NbaResimRefusal("pbp_score_mismatch",
                                   f"pbp {sum(hp)}-{sum(ap)} official {state.home.score}-{state.away.score}")

    # Where to resume.
    reg_periods = int(pbp.rules_for(league).regulation_periods)  # 4 quarters (NBA/WNBA), 2 halves (NCAAB); no default
    if clock <= 0:
        # A period just ended. Resume from the NEXT period's tip -- in regulation always, after Q4 or an
        # OT only if the game is tied (that is overtime); otherwise the game is decided.
        if period >= reg_periods and sum(hp) != sum(ap):
            return NbaResimRefusal("regulation_over")
        r_period, r_secs = period + 1, None
        hp, ap = hp + (0,), ap + (0,)
    else:
        r_period, r_secs = period, int(round(clock))
        # A live five that is not 5 distinct players (P2: ~1 tick in 200, ESPN posts half a substitution first;
        # the next tick heals) is refused for THIS tick, never resumed as a guess. P1's GameState.validate would
        # reject it, and silently sampling a lineup instead would hide it.
        for side in ("home", "away"):
            five = _names(state, side)
            if len(set(five)) != 5:
                return NbaResimRefusal("on_floor_incomplete", f"{side}:{len(set(five))}")

    fouls = {p.name: int(p.pf) for p in state.players if p.pf}
    home_names = {p.name for p in state.players if p.side == "home"}
    gs = GameState(
        period=r_period,
        seconds_remaining=r_secs,
        home_period_pts=hp,
        away_period_pts=ap,
        possession=state.possession_side if (r_secs is not None) else None,
        home_on_floor=tuple(_names(state, "home")) if r_secs is not None else (),
        away_on_floor=tuple(_names(state, "away")) if r_secs is not None else (),
        home_player_fouls={k: v for k, v in fouls.items() if k in home_names},
        away_player_fouls={k: v for k, v in fouls.items() if k not in home_names},
        home_team_fouls=int(state.home.team_fouls_period) if r_secs is not None else 0,
        away_team_fouls=int(state.away.team_fouls_period) if r_secs is not None else 0,
    )
    facts = ResumeFacts(
        event_id=str(state.event_id), home_code=str(state.home.code), away_code=str(state.away.code),
        home_score=int(sum(hp)), away_score=int(sum(ap)), period=period,
        clock_seconds=float(clock), possession=state.possession_side, last_seq=int(state.last_seq),
        as_of=as_of or state.built_at or _utc_now_iso(), score_source=score_source,
    )
    return state, gs, facts


def _names(state: Any, side: str) -> list[str]:
    by_id = {p.player_id: p.name for p in state.players}
    team = state.home if side == "home" else state.away
    return [by_id[pid] for pid in team.on_floor if pid in by_id]


# ------------------------------------------------------------------------------------------- engine inputs

def engine_inputs_dir(date: str, *, root: Optional[Path] = None, league: str = LEAGUE) -> Path:
    if root is None:
        from syndicate.features.shared.basketball_live_state import source_root

        root = source_root(league)
    return Path(root) / "data" / "processed" / ENGINE_INPUTS_DIRNAME / str(date)


def engine_inputs_path(date: str, home: str, away: str, *, root: Optional[Path] = None, league: str = LEAGUE) -> Path:
    return engine_inputs_dir(date, root=root, league=league) / f"{str(home).upper()}_{str(away).upper()}.pkl"


def persist_engine_inputs(date: str, home: str, away: str, kwargs: Mapping[str, Any], *,
                          root: Optional[Path] = None, league: str = LEAGUE) -> Path:
    """Write the pregame engine kwargs for one game (atomic). Called once per game at pregame sim time.

    Pickle, because the kwargs are DataFrames + an `EventSimConfig` + `QuarterResult`s and the engine
    must receive the same objects bit for bit (the recorded-corpus pickles are ~100 KB/game)."""
    path = engine_inputs_path(date, home, away, root=root, league=league)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {k: kwargs[k] for k in _INPUT_KEYS if k in kwargs}
    if "cfg" in body:
        body["cfg"] = _encode_cfg(body["cfg"])
    tmp = path.with_suffix(".tmp")
    with tmp.open("wb") as fh:
        pickle.dump({"schema": ENGINE_INPUTS_SCHEMA, "league": str(league).lower(), "date": str(date), "home": str(home).upper(),
                     "away": str(away).upper(), "written_at": _utc_now_iso(), "kwargs": body}, fh, protocol=4)
    tmp.replace(path)
    return path


# THE CONFIGURED CFG IS NOT PICKLABLE AS AN OBJECT. With `nba_engine_config.json` enabled, the production pregame
# cfg is an instance of a class built at runtime (`_apply_nba_engine_config_local` -> make_dataclass), which pickle
# cannot find by name: measured 2026-10-15, PicklingError "attribute lookup EventSimConfigLocalNbaConfigured on types
# failed". The persist hook swallows errors, so every game would have lost its live inputs SILENTLY the day the file
# went on. A cfg that pickles is stored as before (today's production: unchanged bytes); one that does not is stored
# as its plain field values and rebuilt on load as the engine's own EventSimConfig, carrying
# `league_params_overrides` so the resume picks the same engine the pregame call did.
_CFG_FIELDS_TAG = "__nba_cfg_fields__"


def _encode_cfg(cfg: Any) -> Any:
    if cfg is None:
        return None
    try:
        pickle.dumps(cfg, protocol=4)
        return cfg
    except Exception:  # noqa: BLE001 -- only an unpicklable cfg takes the field path
        import dataclasses

        if not dataclasses.is_dataclass(cfg):
            raise
        return {_CFG_FIELDS_TAG: {f.name: getattr(cfg, f.name) for f in dataclasses.fields(cfg)}}


def decode_inputs(kw: Mapping[str, Any]) -> dict[str, Any]:
    """Persisted kwargs -> engine kwargs: a field-encoded cfg is rebuilt as the engine's EventSimConfig (unknown
    fields dropped), with `league_params_overrides` set on it. Anything else is returned unchanged."""
    out = dict(kw)
    cfg = out.get("cfg")
    if isinstance(cfg, Mapping) and _CFG_FIELDS_TAG in cfg:
        from dataclasses import fields as _fields

        from syndicate.features.basketball_engine.engine import EventSimConfig

        vals = dict(cfg[_CFG_FIELDS_TAG])
        names = {f.name for f in _fields(EventSimConfig)}
        rebuilt = EventSimConfig(**{k: v for k, v in vals.items() if k in names})
        object.__setattr__(rebuilt, "league_params_overrides", vals.get("league_params_overrides"))
        object.__setattr__(rebuilt, "config_sha", vals.get("config_sha"))
        out["cfg"] = rebuilt
    return out


def league_params_overrides_of(inputs: Mapping[str, Any]) -> Optional[tuple]:
    """The LeagueParams overrides the pregame call ran with (nba_engine_config.json), else None."""
    ov = getattr(inputs.get("cfg"), "league_params_overrides", None)
    return tuple(ov) if ov else None


def load_engine_inputs(date: str, home: str, away: str, *, root: Optional[Path] = None, league: str = LEAGUE):
    path = engine_inputs_path(date, home, away, root=root, league=league)
    if not path.exists():
        return NbaResimRefusal("no_pregame_inputs", str(path.name))
    try:
        with path.open("rb") as fh:
            doc = pickle.load(fh)
    except Exception as exc:  # noqa: BLE001
        return NbaResimRefusal("pregame_inputs_unreadable", type(exc).__name__)
    kw = doc.get("kwargs") if isinstance(doc, Mapping) else None
    missing = [k for k in _INPUT_KEYS if not isinstance(kw, Mapping) or k not in kw]
    if missing:
        return NbaResimRefusal("pregame_inputs_incomplete", ",".join(missing))
    return decode_inputs(kw)


# ------------------------------------------------------------------------------------------- names

def normalize_name(name: Any) -> str:
    """The pregame engine's own player key (`normalize_player_name_key`), lowercase.

    THREE SOURCES MEET ON THIS KEY: the engine frames (`player_name`), ESPN's live box and on-floor names, and the
    OddsAPI props CSV. It used to be a weaker key of its own, so two spellings of one player split (`#762` (7),
    measured 2026-11-09 02:36Z, served board, 18 of 399 live NBA prop rows with no live number):
      - `A.J. Green` (CSV) is `a j green` with punctuation turned into spaces, and the engine frame's `AJ Green` is
        `aj green`. So he had no lines, and no live prop row.
      - `Herb Jones` (CSV, ESPN) against `Herbert Jones` (engine): no alias table, so again no lines and no row. ESPN's
        on-floor name could not map to the engine's either.
    The engine key drops periods and apostrophes (`A.J.` = `AJ`, `De'Andre` = `De’Andre` = `DeAndre`), drops
    generational suffixes, and applies the engine's nickname aliases (`HERB JONES` -> `HERBERT JONES`). Every caller
    keys both sides through this one function, so the change can only merge two spellings of a name. It can never
    split one. Anything left that is not a letter, a digit or a space becomes a space, as before."""
    from syndicate.features.nba.live_tick.player_names import normalize_player_name_key

    key = normalize_player_name_key(name, case="lower")
    return " ".join("".join(ch if ch.isalnum() or ch.isspace() else " " for ch in key).split())


def map_state_names(gs: Any, home_frame: Any, away_frame: Any):
    """Re-key the state's ESPN names onto the engine frames' `player_name`.

    An on-floor five with ANY unmatched player is dropped for that side (the engine samples the lineup,
    exactly as at a period tip) rather than resumed with four; how many matched is reported."""
    from dataclasses import replace

    def table(frame):
        out = {}
        try:
            for nm in frame["player_name"].tolist():
                out.setdefault(normalize_name(nm), str(nm))
        except Exception:  # noqa: BLE001
            pass
        return out

    th, ta = table(home_frame), table(away_frame)
    report = {}

    def five(names, t, side):
        mapped = [t.get(normalize_name(n)) for n in names]
        report[f"{side}_on_floor_matched"] = sum(1 for m in mapped if m)
        return tuple(m for m in mapped) if names and all(mapped) and len(mapped) == 5 else ()

    def fouls(d, t):
        return {t[normalize_name(k)]: v for k, v in (d or {}).items() if normalize_name(k) in t}

    new = replace(
        gs,
        home_on_floor=five(gs.home_on_floor, th, "home"),
        away_on_floor=five(gs.away_on_floor, ta, "away"),
        home_player_fouls=fouls(gs.home_player_fouls, th),
        away_player_fouls=fouls(gs.away_player_fouls, ta),
    )
    return new, report


# ------------------------------------------------------------------------------------------- the re-sim

# THE LIVE MECHANISMS (engine.py EventSimConfig, default-off). NOT ENABLED IN PRODUCTION: their rates need a
# re-fit, and re-fits are ON HOLD until #473 (NBA team_adj unfed) -- user decision 2026-10-09. The env switch exists
# so the backtest and the fleet can measure a mechanism without a code change; ABSENT IS OFF, checked not assumed.
LIVE_MECHANISMS_ENV = "SYNDICATE_NBA_LIVE_MECHANISMS"


def live_mechanisms_from_env(env: Optional[Mapping[str, str]] = None) -> dict[str, Any]:
    """`SYNDICATE_NBA_LIVE_MECHANISMS='{"endgame_foul_window_s": 120, ...}'` -> fields. Absent, empty, unparseable
    or naming a field the engine does not have -> {} (OFF), never a partial guess."""
    import json
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
    return dict(parsed)


def with_live_mechanisms(inputs: Mapping[str, Any], mechanisms: Mapping[str, Any]) -> dict[str, Any]:
    """The pregame inputs with `cfg` rebuilt as the ENGINE's EventSimConfig: every value the pregame config carries,
    plus `mechanisms`. Empty `mechanisms` returns the inputs untouched (the pregame config object itself)."""
    if not mechanisms:
        return dict(inputs)
    from dataclasses import fields as _fields

    from syndicate.features.basketball_engine.engine import EventSimConfig

    base = inputs.get("cfg")
    names = {f.name for f in _fields(EventSimConfig)}
    vals = {f.name: getattr(base, f.name) for f in (_fields(base) if base is not None else ()) if f.name in names}
    cfg = EventSimConfig(**{**vals, **dict(mechanisms)})
    ov = getattr(base, "league_params_overrides", None)
    if ov:  # keep the pregame engine choice (nba_engine_config.json) through the rebuild
        object.__setattr__(cfg, "league_params_overrides", ov)
    sha = getattr(base, "config_sha", None)
    if sha:
        object.__setattr__(cfg, "config_sha", sha)
    return {**dict(inputs), "cfg": cfg}


def resume_engine_label(league: str = LEAGUE, overrides: Optional[tuple] = None, config_sha: Optional[str] = None) -> str:
    """Which engine a live resume runs: the league, the #473 no-stack switch and, when nba_engine_config.json set
    LeagueParams overrides on the pregame call, a short digest of them -- the lane's audit trail."""
    try:
        from syndicate.features.shared.basketball_props_smart_sim import _engine_for_league_local

        params = _engine_for_league_local(league, overrides).params
        value = getattr(params, "team_prior_stacks_on_target", None)
        # None = the league defers to the config's own `team_prior_stacks_on_target` (vendored default: stack).
        label = f"{params.code}:stack={'cfg' if value is None else bool(value)}"
        if overrides:
            label += f":lp={zlib.crc32(repr(tuple(overrides)).encode('utf-8')) & 0xFFFFFFFF:08x}"
        if config_sha:  # sha256 of nba_engine_config.json's bytes, stamped on the pregame cfg (calibration lane)
            label += f":cfg={str(config_sha)[:8]}"
        return label
    except Exception as exc:  # noqa: BLE001
        return f"unknown:{type(exc).__name__}"


def stable_seed(event_id: str, last_seq: int) -> int:
    """Same game + same logged state -> same seed, so an unchanged state reproduces its number."""
    return zlib.crc32(f"nba-live-resim|{event_id}|{int(last_seq)}".encode("utf-8")) & 0x7FFFFFFF


def resim_live_game(inputs: Mapping[str, Any], game_state: Any, *, sims: int = DEFAULT_SIMS, base_seed: int = 0,
                    deadline: Optional[float] = None, simulate: Optional[Callable[..., Any]] = None,
                    clock: Callable[[], float] = time.monotonic, league: str = LEAGUE):
    """Run `sims` resumed games from `game_state`; aggregate full-game and per-period distributions.

    `deadline` is a `clock()` value. Hitting it before `sims` draws finish is `budget_exhausted` -- the
    partial draws are DISCARDED, never published as a thinner number."""
    import numpy as np

    if simulate is None:
        # THE SAME ENGINE OBJECT THE PREGAME SIM USES. `_engine_for_league_local("nba")` binds the league params AND
        # production's lineup sampler, and since #473 (a31ba2bf) the params carry `team_prior_stacks_on_target=False`
        # while SYNDICATE_NBA_TEAM_INPUTS is on. Building `league_params("nba")` here would resume with the team prior
        # STACKED on the target -- a different engine from the one that produced the pregame number. The flag is a
        # process env, so both workers must carry the same value; `resumeEngine` on the lane records which ran.
        from syndicate.features.shared.basketball_props_smart_sim import _engine_for_league_local

        # The SAME engine the pregame call picked: nba_engine_config.json's LeagueParams overrides ride on the cfg
        # (`_call_native_engine_local` does exactly this). None = today's engine.
        engine = _engine_for_league_local(league, league_params_overrides_of(inputs))

        def simulate(rng, gs):  # noqa: E306
            return engine.simulate_pbp_game_boxscore(rng=rng, **dict(inputs), state=gs)

    if sims < MIN_SIMS:
        return NbaResimRefusal("sims_below_floor", f"{sims}<{MIN_SIMS}")
    rng = np.random.default_rng(int(base_seed))
    totals: list[int] = []
    margins: list[int] = []
    periods_h: list[list[int]] = []
    periods_a: list[list[int]] = []
    ot_h: list[int] = []
    ot_a: list[int] = []
    reg_ties = 0
    rem: dict[str, dict[str, dict[str, list[int]]]] = {"home": {}, "away": {}}
    for i in range(int(sims)):
        if deadline is not None and clock() >= deadline:
            return NbaResimRefusal("budget_exhausted", f"{i}/{sims}")
        try:
            hb, ab, hq, aq = simulate(rng, game_state)
        except Exception as exc:  # noqa: BLE001
            return NbaResimRefusal("engine_resume_rejected", type(exc).__name__)
        _collect_player_remainders(rem, "home", hb, i)
        _collect_player_remainders(rem, "away", ab, i)
        # THE FULL GAME INCLUDES OVERTIME (todo #763). The engine returns REGULATION periods in `hq`/`aq` and keeps
        # every overtime in the box's `ot_pts`, so summing `hq` alone scored a simulated overtime game as a regulation
        # tie: its total missed the OT points and it counted as a home non-win. Measured over 6,215 live lanes
        # (10-13..11-05): 2.9% of draws tied in regulation, 9.2% in Q4's last 5:00 within 5 points -- and all 41 lanes
        # resumed IN overtime published `modelHomeWinProb` 0.0. Quarters stay regulation-only; `h2` takes the OT
        # (`_segments`).
        ot_home, ot_away = _ot_points(hb), _ot_points(ab)
        h, a = int(sum(hq)) + ot_home, int(sum(aq)) + ot_away
        totals.append(h + a)
        margins.append(h - a)
        periods_h.append([int(x) for x in hq])
        periods_a.append([int(x) for x in aq])
        ot_h.append(ot_home)
        ot_a.append(ot_away)
        # THE DRAW'S OWN OVERTIME CHANCE (todo #789). `hq`/`aq` hold the full regulation (banked periods included),
        # so a draw whose regulation ends level is one that played overtime -- the event the full-game numbers above
        # fold in and can no longer show (the margin histogram has no 0 once OT is played). Measured 2026-11-11
        # (#788): the re-sim's whole late close-game miss was the 8 overtime games of 160, +21 points each, and
        # whether it priced that chance right could not be checked because nothing kept it.
        reg_ties += int(sum(hq)) == int(sum(aq))
    n = len(totals)
    wins = sum(1 for m in margins if m > 0)
    out: dict[str, Any] = {
        "sims_run": n,
        "home_win_prob": wins / n,
        "overtime_prob": reg_ties / n,
        "total_mean": float(np.mean(totals)),
        "home_margin_mean": float(np.mean(margins)),
        "total_dist": _hist(totals),
        "margin_dist": _hist(margins),
        "segments": _segments(periods_h, periods_a, ot_h, ot_a, period=getattr(game_state, "period", None)),
        "player_remainders": _player_remainder_hists(rem, n),
    }
    # (lane nba-no-history-admit) a no-history stand-in plays in the resumed game -- his teammates' minutes depend on
    # it -- but his own remainder is the posted line played back, so it is never published: no live prop row can
    # price him. The flag rides on the persisted pool frames (`pool_source`); frames without it are untouched.
    hidden = _hide_standin_remainders(out["player_remainders"], inputs)
    if hidden:
        out["no_history_standins_hidden"] = hidden
    return out


def _hide_standin_remainders(remainders: dict[str, dict[str, Any]], inputs: Mapping[str, Any]) -> list[str]:
    from syndicate.features.shared.nba_no_history_standins import SOURCE

    names: set[str] = set()
    for key in ("home_players", "away_players"):
        frame = inputs.get(key)
        try:
            if frame is not None and "pool_source" in frame.columns:
                names |= set(frame.loc[frame["pool_source"].astype(str) == SOURCE, "player_name"].astype(str))
        except Exception:  # noqa: BLE001 -- a frame this cannot read carries no stand-in flag
            continue
    hidden: list[str] = []
    for side_rows in remainders.values():
        for name in [n for n in side_rows if n in names]:
            side_rows.pop(name)
            hidden.append(name)
    return sorted(hidden)


# Per-player REST-OF-GAME stats. A resumed run's player box lines are the remainder only (resume.py), so the
# final for a prop is actual-so-far + this. Keyed by the engine frame's `player_name`.
#
# STEALS / BLOCKS / TURNOVERS (2026-10-20, user: "fix the live prop matching so more props get projections"). The engine
# box already carries `stl`/`blk`/`tov` (engine.py `finalize`) and the pregame props sim prices them off the same
# engine (orchestrator/smart_sim.py collects all seven), so the live tier publishing only four left those board rows
# with no live number at all.
PROP_STATS: tuple[tuple[str, str], ...] = (("pts", "points"), ("reb", "rebounds"), ("ast", "assists"), ("threes", "threes"),
                                           ("stl", "steals"), ("blk", "blocks"), ("tov", "turnovers"))
# COMBINATION MARKETS, SUMMED PER DRAW. Each draw is one simulated rest-of-game, so `pra` for draw i is that draw's
# pts + reb + ast and the correlation between them survives. Convolving the marginal histograms instead would assume a
# player's points and rebounds independent. Measured 2026-10-20 19:35 CT (PHI @ NYK live): 73 of 166 live NBA prop rows
# on the board were these four markets, and 0 of them could join a live projection because none was produced.
COMBO_STATS: dict[str, tuple[str, ...]] = {
    "pr": ("pts", "reb"),
    "pa": ("pts", "ast"),
    "ra": ("reb", "ast"),
    "pra": ("pts", "reb", "ast"),
}
# DOUBLE-DOUBLE / TRIPLE-DOUBLE (`#762` (c), user "Yes, build it" 2026-11-06). A COUNT, the grader's own framing
# (`bet_status_nba._MARKET_TO_DOUBLES`): how many of these five stats finish at 10 or more, so Yes on a double-double
# is OVER 1.5 and on a triple-double OVER 2.5. It is a JOINT threshold, which is why the pregame join refuses it (the
# pregame sim ships per-stat marginals) and why this is computed per DRAW: each draw is one simulated rest-of-game, so
# a player's points and rebounds reach ten together or not in that draw. Measured 2026-11-05: 12 of ~280 live NBA prop
# rows were these two markets and none had a live number.
DOUBLE_STATS: tuple[str, ...] = ("pts", "reb", "ast", "stl", "blk")
DOUBLE_THRESHOLD = 10
DOUBLES_LINES: dict[str, float] = {"dd": 1.5, "td": 2.5}
# Per player, the joint rest-of-game draws of DOUBLE_STATS, each capped at DOUBLE_THRESHOLD: `"p,r,a,s,b" -> draws`.
# The cap is lossless (banked >= 0, so a remainder of 10 already reaches 10) and keeps the key space to the draws.
# In memory only: the snapshot publishes `liveProps` rows, never `player_remainders`.
DOUBLES_JOINT_KEY = "doubles_joint"


def _ot_points(box: Any) -> int:
    """A team's overtime points in one draw: the engine's `box["ot_pts"]` (one entry per OT period), 0 without OT."""
    ot = box.get("ot_pts") if isinstance(box, Mapping) else None
    return int(sum(int(x) for x in ot)) if isinstance(ot, (list, tuple)) else 0


def _collect_player_remainders(rem: dict, side: str, box: Any, draw: int) -> None:
    rows = (box or {}).get("players") if isinstance(box, Mapping) else None
    for row in rows or []:
        name = str(row.get("player_name") or "").strip()
        if not name:
            continue
        slot = rem[side].setdefault(name, {k: [] for k, _ in PROP_STATS})
        for key, _label in PROP_STATS:
            vals = slot[key]
            vals.extend([0] * (draw - len(vals)))  # absent from earlier boxes = scored 0 there
            vals.append(int(row.get(key) or 0))


def _player_remainder_hists(rem: dict, n: int) -> dict[str, dict[str, dict[str, dict[str, int]]]]:
    out: dict[str, dict[str, dict[str, dict[str, int]]]] = {"home": {}, "away": {}}
    for side, players in rem.items():
        for name, stats in players.items():
            # Every list padded to n draws, index = draw (`_collect_player_remainders` pads the same way), so the combo
            # sums below line up draw for draw.
            padded = {key: stats.get(key, []) + [0] * (n - len(stats.get(key, []))) for key, _label in PROP_STATS}
            for combo, parts in COMBO_STATS.items():
                padded[combo] = [sum(vals) for vals in zip(*(padded[part] for part in parts))]
            hists: dict[str, Any] = {key: _hist(vals) for key, vals in padded.items() if any(vals)}
            if hists:
                hists[DOUBLES_JOINT_KEY] = _doubles_joint(padded, n)
                out[side][name] = hists
    return out


def _doubles_joint(padded: Mapping[str, Sequence[int]], n: int) -> dict[str, int]:
    """`"p,r,a,s,b" -> draws` over DOUBLE_STATS, each remainder capped at DOUBLE_THRESHOLD (see DOUBLES_JOINT_KEY)."""
    cols = [list(padded.get(key) or []) + [0] * (n - len(padded.get(key) or [])) for key in DOUBLE_STATS]
    joint: Counter = Counter(",".join(str(min(int(v), DOUBLE_THRESHOLD)) for v in draw) for draw in zip(*cols))
    return {key: int(count) for key, count in sorted(joint.items())}


# ESPN box column -> PROP_STATS key (ESPN's NBA box: MIN PTS FG 3PT FT REB AST TO STL BLK OREB DREB PF +/-).
_BOX_COLUMNS: tuple[tuple[str, str], ...] = (("PTS", "pts"), ("REB", "reb"), ("AST", "ast"), ("3PT", "threes"),
                                             ("STL", "stl"), ("BLK", "blk"), ("TO", "tov"))


def actuals_from_summary(summary: Mapping[str, Any]) -> dict[str, dict[str, int]]:
    """Banked production per player NAME from the LIVE box score (ESPN updates it in game).

    `{normalized name: {"pts","reb","ast","threes","stl","blk","tov"}}`. A malformed cell is skipped, never read as 0:
    a missing actual and a genuine zero are different facts (`wnba_live_prop_rows.to_snapshot_live_props`). Combos are
    summed from these in `build_live_props`, never read from the box."""
    out: dict[str, dict[str, int]] = {}
    for block in ((summary or {}).get("boxscore") or {}).get("players") or []:
        for stat in block.get("statistics") or []:
            names = [str(n) for n in stat.get("names") or []]
            idx = {k: names.index(k) for k, _key in _BOX_COLUMNS if k in names}
            for a in stat.get("athletes") or []:
                nm = normalize_name(((a.get("athlete") or {}).get("displayName")) or "")
                vals = a.get("stats") or []
                if not nm or not vals:
                    continue
                row: dict[str, int] = {}
                for col, key in _BOX_COLUMNS:
                    i = idx.get(col)
                    if i is None or i >= len(vals):
                        continue
                    raw = str(vals[i]).split("-", 1)[0]
                    try:
                        row[key] = int(float(raw))
                    except ValueError:
                        continue
                if row:
                    out[nm] = row
    return out


# Stat key -> the OddsAPI market key the board rows carry, so a liveProps row joins on its `prop` with no alias.
BOARD_PROP_MARKETS = {
    "pts": "player_points", "reb": "player_rebounds", "ast": "player_assists", "threes": "player_threes",
    "stl": "player_steals", "blk": "player_blocks", "tov": "player_turnovers",
    "pr": "player_points_rebounds", "pa": "player_points_assists", "ra": "player_rebounds_assists",
    "pra": "player_points_rebounds_assists",
    "dd": "player_double_double", "td": "player_triple_double",
}
_CSV_MARKET_TO_STAT = {v: k for k, v in BOARD_PROP_MARKETS.items()}


def lines_from_props_csv(path: Path, home_name: str, away_name: str) -> dict[tuple[str, str], tuple[float, ...]]:
    """`(normalized player, stat) -> every line posted` for ONE game from Syndicate's captured OddsAPI props CSV.

    EVERY LINE, NOT THE MODE (2026-10-20). This used to return one line per (player, stat), the mode across books, and
    the board joins on (player, market, LINE): a book posting 24.5 beside the consensus 25.5 kept its row unpriced
    although the same remainder histogram prices any line. Measured 19:35 CT on PHI @ NYK: 18 live board rows missed
    for exactly that, their player and market projected at another line. Over AND under count -- a line quoted on one
    side only is still a line the board can show. Scoped to the game by both full team names. Any failure -> {}."""
    import csv
    from collections import Counter as _Counter

    counts: dict[tuple[str, str], Any] = {}
    try:
        with Path(path).open("r", encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                teams = (str(row.get("home_team") or "").strip(), str(row.get("away_team") or "").strip())
                if teams != (home_name, away_name):
                    continue
                stat = _CSV_MARKET_TO_STAT.get(str(row.get("market") or "").strip().lower())
                outcome = str(row.get("outcome_name") or "").strip().lower()
                if stat in DOUBLES_LINES:
                    # Yes/No with no point (`#762` (c)): the line is the count's own, 1.5 / 2.5.
                    if outcome not in ("yes", "no"):
                        continue
                    key = (normalize_name(row.get("player_name")), stat)
                    counts.setdefault(key, _Counter())[DOUBLES_LINES[stat]] += 1
                    continue
                if not stat or outcome not in ("over", "under"):
                    continue
                try:
                    line = float(row.get("point"))
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(line):
                    continue
                key = (normalize_name(row.get("player_name")), stat)
                counts.setdefault(key, _Counter())[line] += 1
    except Exception:  # noqa: BLE001
        return {}
    return {key: tuple(sorted(c)) for key, c in counts.items()}


# LINES MOVE BETWEEN THIS TICK AND THE BOARD BUILD. The CSV is the latest in-play pull (every ~4 min) and the board
# joins on (player, market, LINE) at its own build time, so an exact-line producer misses every line that moved in
# between. Measured 2026-10-20 (same-instant A/B on PHI @ NYK, board 7:35 PM vs CSV 7:44 PM): 41 of 166 live rows
# missed on the line alone. The remainder histogram prices ANY line, so each posted line is published with its
# neighbours, +-LIVE_LINE_WINDOW in whole steps; a neighbour only ever joins a board row that shows that line.
LIVE_LINE_WINDOW = 3


def with_neighbour_lines(lines: Mapping[tuple[str, str], Any], window: int = LIVE_LINE_WINDOW) -> dict[tuple[str, str], tuple[float, ...]]:
    """Each posted line plus line +- 1..window (never below 0.5): `(player, stat) -> sorted lines`."""
    out: dict[tuple[str, str], tuple[float, ...]] = {}
    for key, posted in lines.items():
        base = (posted,) if isinstance(posted, (int, float)) else tuple(posted)
        if key[1] in DOUBLES_LINES:
            # A yes/no market's line is fixed by its definition and never moves; a neighbour would be another market.
            out[key] = tuple(sorted(float(line) for line in base))
            continue
        grid = {float(line) + step for line in base for step in range(-int(window), int(window) + 1)}
        out[key] = tuple(sorted(line for line in grid if line >= 0.5))
    return out


# A MARKET THE BOOKS PULLED KEEPS ITS LIVE NUMBER, DISPLAY ONLY (`#762` (6), user "Yes, build it" 2026-11-08).
#
# MEASURED 2026-11-07 on the fleet, 21 NBA board builds 00:07-05:31Z: 1,926 of 14,478 live prop row-builds (13.3%) had
# their player in the lens and no live number. 1,598 of them had NO line at all for that market, and the share rose to
# 79% (197 of 249) at 05:14Z with two games in the fourth. The props CSV holds each game's LATEST pull, and books take
# player props down as a game goes on (at 05:32Z it held 14 `player_points` rows over 7 games), while the board's GRID
# keeps the row.
#
# THOSE ARE JOIN ROW-BUILDS, NOT SERVED ROWS (corrected 2026-11-08 22:10Z, after this loaded). The served board drops a
# live row whose quote went unobserved for 300 s (`opportunity_gate.live_quote_unobserved`, dead lane, never
# shortlisted), and a pulled line is by construction unobserved: of 151 pulled lines found in the quote state, 146 were
# last seen over 300 s before, and 0 of 43 served live NBA prop rows were pulled ones. So the served effect of this
# block is a row inside that window. The 11-07 served gap was 16 of 123 rows, all one accented name (`7d72f8e9d`).
#
# So each game row remembers every line it has seen posted (`postedLines`, same date only), and a remembered line the
# latest pull no longer carries is published FLAGGED: `quotePulled`, NO `liveModelProbOver` (`unpricedReason:
# quote_pulled`), its probability only under `liveDisplayProbOver`. Its quote is dead -- there is no price to beat --
# so the board shows the Live proj. and the actual and prices nothing. Fail-safe both ways: a reader that drops the
# flag still finds no live probability, and the prop join refuses a row without one (`no_live_probability`).
#
# Window +-1, not +-3: a pulled line is what the board last saw, which is a line this loop read or one step from it
# (a pull between two ticks). The +-3 window is for lines that move while the market is up.
PULLED_LINES_ENV = "SYNDICATE_NBA_LIVE_PROPS_PULLED_LINES"
PULLED_LINE_WINDOW = 1
# A bound, not a tuning knob: a points line that walks 22.5 -> 35.5 over a game is 14 lines.
MAX_REMEMBERED_LINES_PER_KEY = 24


def pulled_lines_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    """On unless `SYNDICATE_NBA_LIVE_PROPS_PULLED_LINES` says 0/false/off/no. Off = the latest pull only, as before."""
    raw = str((env if env is not None else os.environ).get(PULLED_LINES_ENV, "") or "").strip().lower()
    return raw not in ("0", "false", "off", "no")


def _posted_lines_payload(lines: Mapping[tuple[str, str], Any]) -> list[list[Any]]:
    """`(player, stat) -> lines` as JSON: `[[player, stat, [lines]], ...]`, sorted so a tick's bytes are stable."""
    out: list[list[Any]] = []
    for (player, stat), posted in sorted(lines.items()):
        values = (posted,) if isinstance(posted, (int, float)) else tuple(posted)
        out.append([str(player), str(stat), sorted(float(v) for v in values)])
    return out


def _posted_lines_from_payload(payload: Any) -> dict[tuple[str, str], tuple[float, ...]]:
    """The inverse of `_posted_lines_payload`. Anything malformed is skipped, never guessed."""
    out: dict[tuple[str, str], tuple[float, ...]] = {}
    for item in payload if isinstance(payload, list) else ():
        if not isinstance(item, (list, tuple)) or len(item) != 3 or not isinstance(item[2], (list, tuple)):
            continue
        values = []
        for value in item[2]:
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number):
                values.append(number)
        if values:
            out[(str(item[0]), str(item[1]))] = tuple(sorted(set(values)))
    return out


def _prior_posted_lines(previous: Optional[Mapping[str, Any]], date_str: str) -> dict[str, dict[tuple[str, str], tuple[float, ...]]]:
    """event_id -> the lines the previous snapshot remembered for that game.

    Every game row counts -- a refused or carried one too -- so one refused tick does not forget a game's lines. Same
    date only, like `_prior_live_rows`."""
    if not isinstance(previous, Mapping) or str(previous.get("date") or "") != str(date_str):
        return {}
    out: dict[str, dict[tuple[str, str], tuple[float, ...]]] = {}
    for game in previous.get("games") or []:
        if isinstance(game, Mapping) and game.get("postedLines"):
            out[str(game.get("event_id") or "")] = _posted_lines_from_payload(game.get("postedLines"))
    return out


def _merge_posted_lines(prior: Optional[Mapping[tuple[str, str], Any]], current: Mapping[tuple[str, str], Any],
                        cap: int = MAX_REMEMBERED_LINES_PER_KEY) -> dict[tuple[str, str], tuple[float, ...]]:
    """Every line seen for each (player, stat), this pull's and the remembered ones. Past `cap`, the lines nearest
    this pull's (or, with none, the remembered ones') centre are kept."""
    out: dict[tuple[str, str], tuple[float, ...]] = {}
    for key in set(prior or {}) | set(current):
        now_posted = current.get(key)
        now_values = () if now_posted is None else ((now_posted,) if isinstance(now_posted, (int, float)) else tuple(now_posted))
        old = (prior or {}).get(key) or ()
        old_values = (old,) if isinstance(old, (int, float)) else tuple(old)
        values = sorted({float(v) for v in (*old_values, *now_values)})
        if len(values) > cap:
            anchor = now_values or old_values
            centre = sum(float(v) for v in anchor) / len(anchor)
            values = sorted(sorted(values, key=lambda v: (abs(v - centre), v))[:cap])
        out[key] = tuple(values)
    return out


def pulled_lines(remembered: Mapping[tuple[str, str], Any], current: Mapping[tuple[str, str], Any],
                 window: int = PULLED_LINE_WINDOW) -> dict[tuple[str, str], tuple[float, ...]]:
    """The remembered lines (+-`window`) that `current` -- this pull's lines WITH their neighbours -- does not cover."""
    out: dict[tuple[str, str], tuple[float, ...]] = {}
    for key, lines in with_neighbour_lines(remembered, window=window).items():
        covered = set(current.get(key) or ())
        gone = tuple(line for line in lines if line not in covered)
        if gone:
            out[key] = gone
    return out


def _banked(act: Optional[Mapping[str, int]], key: str) -> Optional[int]:
    """Actual so far for a stat or a combo; None unless EVERY component is read (a missing actual is not a zero)."""
    if act is None:
        return None
    parts = COMBO_STATS.get(key, (key,))
    if any(part not in act for part in parts):
        return None
    return int(sum(int(act[part]) for part in parts))


def _as_pulled(row: dict[str, Any]) -> dict[str, Any]:
    """A row at a line the books no longer post: its probability moves to `liveDisplayProbOver`, and
    `liveModelProbOver` -- the only field the prop join prices from -- is None (see `PULLED_LINES_ENV`)."""
    row["liveDisplayProbOver"] = row.get("liveModelProbOver")
    row["liveModelProbOver"] = None
    row["unpricedReason"] = "quote_pulled"
    row["quotePulled"] = True
    return row


def _line_values(posted: Any) -> tuple[float, ...]:
    if posted is None:
        return ()
    return (posted,) if isinstance(posted, (int, float)) else tuple(posted)


def build_live_props(result: Mapping[str, Any], actuals: Mapping[str, Mapping[str, int]],
                     lines: Mapping[tuple[str, str], Any],
                     pulled: Optional[Mapping[tuple[str, str], Any]] = None) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """`liveProps` rows in the snapshot contract `live_projection_join.build_live_prop_index` reads.

    A row exists for every LINE posted (a probability needs something to be about) where the player has a
    banked actual (a missing actual is not a zero; a combo needs every component). P(over) = share of draws whose
    actual + remainder exceeds the line. An exact 0 or 1 is a statement about the sample, so it is published as None
    with the reason.

    `pulled` holds lines the books posted earlier in the game and have since taken down (`pulled_lines`). They get the
    same rows, flagged by `_as_pulled`, counted in `pulled_rows` and never in `priced`."""
    rows: list[dict[str, Any]] = []
    counts = {"players_simmed": 0, "rows": 0, "priced": 0, "no_actual": 0, "certainty_refused": 0, "doubles_rows": 0,
              "pulled_rows": 0}
    pulled = pulled or {}
    stat_keys = tuple(key for key, _label in PROP_STATS) + tuple(COMBO_STATS)
    sims_run = int(result.get("sims_run") or 0)
    for side in ("home", "away"):
        for name, hists in ((result.get("player_remainders") or {}).get(side) or {}).items():
            counts["players_simmed"] += 1
            nk = normalize_name(name)
            act = actuals.get(nk)
            for key in stat_keys:
                live_lines = _line_values(lines.get((nk, key)))
                gone_lines = tuple(line for line in _line_values(pulled.get((nk, key))) if line not in live_lines)
                if not live_lines and not gone_lines:
                    continue
                banked = _banked(act, key)
                hist = hists.get(key) or {"0": sims_run}
                total = sum(int(v) for v in hist.values())
                for line, gone in (*((v, False) for v in live_lines), *((v, True) for v in gone_lines)):
                    if banked is None:
                        counts["no_actual"] += 1
                        continue
                    if total <= 0:
                        continue
                    over = sum(int(c) for v, c in hist.items() if banked + int(v) > line)
                    mean_rem = sum(int(v) * int(c) for v, c in hist.items()) / total
                    p_over: Optional[float] = round(over / total, 4)
                    reason = None
                    if p_over in (0.0, 1.0):
                        p_over, reason = None, "certainty_refused"
                        if not gone:
                            counts["certainty_refused"] += 1
                    elif not gone:
                        counts["priced"] += 1
                    row = {
                        "playerName": name,
                        "prop": BOARD_PROP_MARKETS[key],
                        "line": line,
                        "liveProjection": round(banked + mean_rem, 3),
                        "liveModelProbOver": p_over,
                        "actualSoFar": float(banked),
                        "simsRun": sims_run,
                        "side": side,
                    }
                    if reason:
                        row["unpricedReason"] = reason
                    if gone:
                        _as_pulled(row)
                        counts["pulled_rows"] += 1
                    rows.append(row)
                    counts["rows"] += 1
            for key, line in DOUBLES_LINES.items():
                gone = lines.get((nk, key)) is None
                if gone and pulled.get((nk, key)) is None:
                    continue
                row = _doubles_row(name, side, key, line, hists.get(DOUBLES_JOINT_KEY), act, sims_run, counts,
                                   pulled=gone)
                if row is not None:
                    rows.append(row)
    return rows, counts


def _doubles_row(name: str, side: str, key: str, line: float, joint: Optional[Mapping[str, int]],
                 act: Optional[Mapping[str, int]], sims_run: int, counts: dict[str, int],
                 pulled: bool = False) -> Optional[dict[str, Any]]:
    """One double-double / triple-double `liveProps` row: the count of DOUBLE_STATS finishing at 10+.

    `liveProjection` is the mean final count, `actualSoFar` the count already at 10+, P(over) the share of draws whose
    final count clears the line. Same rules as every other row: every component must be banked (a missing actual is
    not a zero), and an exact 0 or 1 is refused with its reason."""
    if act is None or any(stat not in act for stat in DOUBLE_STATS):
        counts["no_actual"] += 1
        return None
    banked = [int(act[stat]) for stat in DOUBLE_STATS]
    draws = joint if joint else {",".join("0" for _ in DOUBLE_STATS): sims_run}
    total = 0
    over = 0
    count_sum = 0
    for draw_key, draw_count in draws.items():
        remainder = [int(v) for v in str(draw_key).split(",")]
        if len(remainder) != len(DOUBLE_STATS):
            continue
        final = sum(1 for b, r in zip(banked, remainder) if b + r >= DOUBLE_THRESHOLD)
        total += int(draw_count)
        count_sum += final * int(draw_count)
        if final > line:
            over += int(draw_count)
    if total <= 0:
        return None
    p_over: Optional[float] = round(over / total, 4)
    row: dict[str, Any] = {
        "playerName": name,
        "prop": BOARD_PROP_MARKETS[key],
        "line": line,
        "liveProjection": round(count_sum / total, 3),
        "liveModelProbOver": p_over,
        "actualSoFar": float(sum(1 for b in banked if b >= DOUBLE_THRESHOLD)),
        "simsRun": sims_run,
        "side": side,
    }
    if p_over in (0.0, 1.0):
        row["liveModelProbOver"] = None
        row["unpricedReason"] = "certainty_refused"
        if not pulled:
            counts["certainty_refused"] += 1
    elif not pulled:
        counts["priced"] += 1
    if pulled:
        _as_pulled(row)
        counts["pulled_rows"] = counts.get("pulled_rows", 0) + 1
    counts["rows"] += 1
    counts["doubles_rows"] += 1
    return row


def _hist(values: Sequence[int]) -> dict[str, int]:
    return {str(k): int(v) for k, v in sorted(Counter(int(x) for x in values).items())}


_SEGMENT_PERIODS: dict[str, tuple[int, ...]] = {"q1": (0,), "q2": (1,), "q3": (2,), "q4": (3,), "h1": (0, 1),
                                                 "h2": (2, 3)}


def _segments(ph: list[list[int]], pa: list[list[int]], oth: Sequence[int] = (), ota: Sequence[int] = (), *,
              period: Any = None) -> dict[str, dict[str, Any]]:
    """Quarter and half totals/margins, binned the way the books settle them (`#762`).

    `q4` is the fourth quarter alone; `h2` is q3 + q4 + EVERY overtime, the rule all four books in
    `bet_status_nba._OVERTIME_RULES` settle a second half on (it used to be regulation-only, so a simulated OT
    game's second half was short its OT points). `sims` is the draw count each block rests on. `settled` is True
    once the live game (`period`, 1-based) has moved past the segment's last period: its histogram is then the real
    score, not a projection. `h2` closes only with the game, so it is never settled while the game is live."""
    out: dict[str, dict[str, Any]] = {}
    try:
        live_period = int(period) if period is not None else None
    except (TypeError, ValueError):
        live_period = None
    for name, idx in _SEGMENT_PERIODS.items():
        tot, mar = [], []
        for i, (h, a) in enumerate(zip(ph, pa)):
            if len(h) < 4 or len(a) < 4:
                continue
            hs, as_ = sum(h[j] for j in idx), sum(a[j] for j in idx)
            if name == "h2":
                hs += int(oth[i]) if i < len(oth) else 0
                as_ += int(ota[i]) if i < len(ota) else 0
            tot.append(hs + as_)
            mar.append(hs - as_)
        if tot:
            last_period = idx[-1] + 1
            out[name] = {"total_mean": sum(tot) / len(tot), "total_dist": _hist(tot), "margin_dist": _hist(mar),
                         "sims": len(tot),
                         "settled": name != "h2" and live_period is not None and live_period > last_period}
    return out


# ------------------------------------------------------------------------------------------- the lane

def build_game_lens(facts: Optional[ResumeFacts], result: Any, *, live_state_as_of: str = "",
                    match_report: Optional[Mapping[str, Any]] = None) -> list[dict[str, Any]]:
    """The `gameLens` list for one game: exactly one lane, honestly stamped.

    A REFUSAL PUBLISHES A LANE -- an absent lane is indistinguishable from a producer that never ran --
    and the refused lane carries no `modelHomeWinProb` at all (`#414`)."""
    if isinstance(result, NbaResimRefusal) or facts is None:
        reason = result.reason if isinstance(result, NbaResimRefusal) else "no_resume_state"
        detail = result.detail if isinstance(result, NbaResimRefusal) else ""
        return [{
            "key": "live",
            "label": "Live",
            "source": PREGAME_LENS_SOURCE,
            "closed": reason in ("game_final", "regulation_over"),
            "liveResimRefusal": reason,
            "liveResimRefusalDetail": detail,
            "liveStateAsOf": live_state_as_of,
        }]
    return [{
        "key": "live",
        "label": "Live",
        "source": LIVE_RESIM_LENS_SOURCE,
        "closed": False,
        "modelHomeWinProb": result["home_win_prob"],
        # Share of draws whose regulation ended tied (#789). `.get`: a result built before the field (a test double,
        # an old caller) publishes no number rather than a made-up 0.
        "modelOvertimeProb": result.get("overtime_prob"),
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
            # Full-game histograms. Priced by `price_distribution_market` ONLY once the backtest gate has
            # passed for the market (design §5); until then nba is not in `_LIVE_GAMELINE_SPORTS`.
            "totalRunsDist": result["total_dist"],
            "marginDist": result["margin_dist"],
            "segments": result.get("segments") or {},
        },
        "resumeMatch": dict(match_report or {}),
    }]


# ------------------------------------------------------------------------------------------- the snapshot

def live_lens_snapshot_path(league: str = LEAGUE):
    from syndicate.features.shared.refresh_state_store import data_root

    return data_root() / "live" / f"{str(league).lower()}_live_resim.json"


def _game_identity(summary: Mapping[str, Any], league: str = LEAGUE) -> tuple[str, str, str]:
    from syndicate.features.shared import basketball_pbp as pbp

    meta = pbp.game_meta(summary, league)
    return meta.event_id, meta.home.code, meta.away.code


# ------------------------------------------------------------------------------------------- budget fairness
#
# THE BUDGET USED TO STARVE THE SAME GAMES EVERY TICK. Games were walked in ESPN scoreboard order under ONE
# shared deadline, so when a tick could not fit the slate, the games at the end of the scoreboard were the
# ones refused -- and they were the same games every tick. Measured on the 2026-11-02 slate (11-12 games
# live at once, 16 of 20 ticks at 01Z-02Z exhausted the 240 s budget): the first 6 games in scoreboard order
# were re-simmed on 98-100% of ticks, the last 4 on 64-70%, and UTA@SAS was refused 10 ticks running (~1 h
# with no live number on the board). On 2026-11-04 00:50Z the 5th live game was refused the same way.
#
# Two changes, both here:
#   1. STALEST FIRST. Games no tick has re-simmed yet (just tipped) go first, then the rest by the age of
#      their last re-simmed state. A slate bigger than one tick's capacity then rotates instead of starving
#      its tail. (NFL/NCAAF go cheapest-first; for basketball that would starve exactly the just-tipped games.)
#   2. CARRY THE LAST GOOD LANE, BOUNDED. A game the budget did not reach this tick republishes its previous
#      `live_resim` lane and props, stamped `carriedForward`, with its ORIGINAL `liveStateAsOf` -- the number
#      is a real full-sims result for the state it says, never a thinner one (`simsRun` stays true). Past
#      `carry_max_age_seconds` of that state it is refused as before (`budget_exhausted`): one missed tick is
#      bridged, a starved game is not papered over.
#
# Carried lanes are NOT new measurements: the tick history records them as the refusal the tick produced
# (`history_rows`), and `run_live_resim_tick`'s `resimmed` counts only fresh lanes.

CARRY_ENV = "SYNDICATE_NBA_LIVE_RESIM_CARRY"
CARRY_MAX_AGE_ENV = "SYNDICATE_NBA_LIVE_RESIM_CARRY_MAX_AGE_SECONDS"
# SIZED FROM THE CADENCE MEASURED UNDER LOAD, not the documented one. At peak (2026-11-02 01-02Z, 2026-11-05 01Z)
# a tick runs the full 240 s budget and then waits its 120 s interval, so ticks land ~360 s apart. A game
# re-simmed FIRST in tick k carries a state ~5 s into that tick; when tick k+1 reaches it after its own 240 s it
# is ~595 s old. 600 s (the live quote-age ceiling) would refuse about a quarter of single-tick carries; 900 s
# covers one missed tick at peak with margin, and no more than that: stalest-first re-sims it on the tick after.
DEFAULT_CARRY_MAX_AGE_SECONDS = 900.0


def carry_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    raw = str((env if env is not None else os.environ).get(CARRY_ENV, "") or "").strip().lower()
    return raw not in ("0", "false", "off", "no")


def carry_max_age_seconds(env: Optional[Mapping[str, str]] = None) -> float:
    """A bad or non-positive value falls back to the default rather than meaning "carry forever"."""
    raw = str((env if env is not None else os.environ).get(CARRY_MAX_AGE_ENV, "") or "").strip()
    try:
        value = float(raw) if raw else DEFAULT_CARRY_MAX_AGE_SECONDS
    except ValueError:
        return DEFAULT_CARRY_MAX_AGE_SECONDS
    return value if value > 0 and math.isfinite(value) else DEFAULT_CARRY_MAX_AGE_SECONDS


def _parse_as_of(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _prior_live_rows(previous: Optional[Mapping[str, Any]], date_str: str) -> dict[str, dict[str, Any]]:
    """event_id -> the previous snapshot's game row, for games whose lane was a `live_resim` result.

    Same date only: a snapshot left over from yesterday must neither reorder nor feed today's tick."""
    if not isinstance(previous, Mapping) or str(previous.get("date") or "") != str(date_str):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for game in previous.get("games") or []:
        if not isinstance(game, Mapping):
            continue
        lanes = game.get("gameLens") or []
        lane = lanes[0] if lanes and isinstance(lanes[0], Mapping) else {}
        if lane.get("source") == LIVE_RESIM_LENS_SOURCE and _parse_as_of(lane.get("liveStateAsOf")) is not None:
            out[str(game.get("event_id") or "")] = dict(game)
    return out


def _stalest_first(events: Sequence[Mapping[str, Any]], prior: Mapping[str, Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Never-re-simmed games first (scoreboard order kept among them), then oldest re-simmed state first."""
    def key(item: tuple[int, Mapping[str, Any]]) -> tuple[int, float, int]:
        index, ev = item
        row = prior.get(str(ev.get("event_id") or ev.get("id") or ""))
        if row is None:
            return (0, 0.0, index)
        as_of = _parse_as_of(((row.get("gameLens") or [{}])[0]).get("liveStateAsOf"))
        return (1, as_of.timestamp() if as_of else 0.0, index)

    return [ev for _i, ev in sorted(enumerate(events), key=key)]


def _carried_row(prior_row: Mapping[str, Any], refusal: "NbaResimRefusal", *, now: datetime, max_age: float,
                 refused_state_as_of: str = "") -> Optional[dict[str, Any]]:
    """The previous tick's row republished, or None when its state is older than `max_age`."""
    lanes = prior_row.get("gameLens") or []
    lane = dict(lanes[0]) if lanes and isinstance(lanes[0], Mapping) else {}
    as_of = _parse_as_of(lane.get("liveStateAsOf"))
    if as_of is None:
        return None
    age = (now - as_of).total_seconds()
    if age > max_age:
        return None
    # A carried lane's own carry stamps are replaced, never stacked: the age is always from the original state.
    lane.update({
        "carriedForward": True,
        "carriedRefusal": refusal.reason,
        "carriedRefusalDetail": refusal.detail,
        "carriedAgeSeconds": round(max(0.0, age), 1),
        "refusedStateAsOf": refused_state_as_of,
    })
    row = dict(prior_row)
    row["gameLens"] = [lane]
    return row


def build_live_lens_snapshot(date_str: str, *, sims: int = DEFAULT_SIMS, budget_seconds: float = DEFAULT_BUDGET_SECONDS,
                             fetch_scoreboard: Optional[Callable[..., Any]] = None,
                             fetch_summary: Optional[Callable[..., Any]] = None,
                             inputs_root: Optional[Path] = None,
                             clock: Callable[[], float] = time.monotonic, league: str = LEAGUE,
                             previous: Optional[Mapping[str, Any]] = None,
                             carry: Optional[bool] = None,
                             carry_max_age: Optional[float] = None,
                             now: Optional[datetime] = None,
                             remember_lines: Optional[bool] = None) -> dict[str, Any]:
    """`previous` is the last snapshot this loop wrote. Without it the tick behaves as before: scoreboard order,
    nothing carried. With it, games run stalest-first and a budget refusal republishes the game's last lane
    within `carry_max_age` (see "budget fairness" above), and each game's remembered lines publish the ones the
    books have since pulled, flagged (`PULLED_LINES_ENV`; `remember_lines` overrides the env)."""
    from syndicate.features.shared import basketball_pbp as pbp
    from syndicate.features.shared.request_path_guard import refuse_if_compute_in_request_path

    refuse_if_compute_in_request_path("nba_live_resim_snapshot")
    fetch_scoreboard = fetch_scoreboard or pbp.fetch_scoreboard
    fetch_summary = fetch_summary or pbp.fetch_summary
    carry = carry_enabled() if carry is None else bool(carry)
    carry_max_age = carry_max_age_seconds() if carry_max_age is None else float(carry_max_age)
    remember_lines = pulled_lines_enabled() if remember_lines is None else bool(remember_lines)
    prior = _prior_live_rows(previous, str(date_str))
    prior_lines = _prior_posted_lines(previous, str(date_str)) if remember_lines else {}
    started = clock()
    deadline = started + float(budget_seconds)
    games: list[dict[str, Any]] = []
    scoreboard = fetch_scoreboard(league, str(date_str).replace("-", ""))
    events = pbp.scoreboard_events(scoreboard)
    live_events = [ev for ev in events if str(ev.get("status_state") or ev.get("state") or "").lower() == "in"]

    def _carry_or_refuse(event_id: str, home: str, away: str, facts: Optional[ResumeFacts],
                         refusal: NbaResimRefusal, match: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
        if carry and event_id in prior:
            carried = _carried_row(prior[event_id], refusal, now=now or datetime.now(timezone.utc),
                                   max_age=carry_max_age, refused_state_as_of=facts.as_of if facts else "")
            if carried is not None:
                return carried
        return _lane_row(event_id, home, away, facts, refusal, match, league=league)

    for ev in _stalest_first(live_events, prior):
        event_id = str(ev.get("event_id") or ev.get("id") or "")
        try:
            summary = fetch_summary(league, event_id)
        except Exception as exc:  # noqa: BLE001
            games.append(_lane_row(event_id, "", "", None, NbaResimRefusal("summary_fetch_failed", type(exc).__name__),
                                   league=league))
            continue
        _eid, home, away = _game_identity(summary, league)
        resumed = resume_from_summary(summary, date=str(date_str), league=league)
        if isinstance(resumed, NbaResimRefusal):
            games.append(_lane_row(event_id, home, away, None, resumed, league=league))
            continue
        _state, gs, facts = resumed
        inputs = load_engine_inputs(str(date_str), home, away, root=inputs_root, league=league)
        if isinstance(inputs, NbaResimRefusal):
            games.append(_lane_row(event_id, home, away, facts, inputs, league=league))
            continue
        gs, match = map_state_names(gs, inputs["home_players"], inputs["away_players"])
        mechanisms = live_mechanisms_from_env()
        inputs = with_live_mechanisms(inputs, mechanisms)
        match = {**match, "mechanisms": sorted(mechanisms), "resumeEngine": resume_engine_label(league, league_params_overrides_of(inputs),
                                                                   getattr(inputs.get("cfg"), "config_sha", None))}
        if clock() >= deadline:
            games.append(_carry_or_refuse(event_id, home, away, facts, NbaResimRefusal("budget_exhausted", "before_start")))
            continue
        result = resim_live_game(inputs, gs, sims=sims, base_seed=stable_seed(facts.event_id, facts.last_seq),
                                 deadline=deadline, clock=clock, league=league)
        if isinstance(result, NbaResimRefusal) and result.reason == "budget_exhausted":
            games.append(_carry_or_refuse(event_id, home, away, facts, result, match))
            continue
        row = _lane_row(event_id, home, away, facts, result, match, league=league)
        if not isinstance(result, NbaResimRefusal):
            lines = lines_from_props_csv(props_csv_path(str(date_str), root=inputs_root, league=league),
                                         row["home_name"], row["away_name"])
            current = with_neighbour_lines(lines)
            remembered = _merge_posted_lines(prior_lines.get(event_id), lines) if remember_lines else {}
            gone = pulled_lines(remembered, current) if remember_lines else {}
            props, coverage = build_live_props(result, actuals_from_summary(summary), current, pulled=gone)
            row["liveProps"] = props
            row["livePropsCoverage"] = {**coverage, "lines_available": len(lines),
                                        "lines_posted": sum(len(v) for v in lines.values()),
                                        "line_window": LIVE_LINE_WINDOW,
                                        "lines_remembered": sum(len(v) for v in remembered.values()),
                                        "keys_pulled": len(gone), "pulled_line_window": PULLED_LINE_WINDOW,
                                        "remember_lines": bool(remember_lines)}
            if remember_lines:
                row["postedLines"] = _posted_lines_payload(remembered)
        games.append(row)
    if remember_lines:
        # A REFUSED TICK MUST NOT FORGET A GAME'S LINES. A carried row already holds its own (`_carried_row` copies the
        # prior row whole); any other row that published none takes the previous snapshot's.
        for game in games:
            event_id = str(game.get("event_id") or "")
            if "postedLines" not in game and prior_lines.get(event_id):
                game["postedLines"] = _posted_lines_payload(prior_lines[event_id])
    return {
        "sport": str(league).lower(),
        "date": str(date_str),
        "generatedAt": _utc_now_iso(),
        "source": LIVE_RESIM_LENS_SOURCE,
        "simsPerGame": int(sims),
        "budgetSeconds": float(budget_seconds),
        "elapsedSeconds": round(clock() - started, 2),
        "games": games,
        "refusalsByReason": _refusals_by_reason(games),
        "carriedForward": sum(1 for g in games for lane in g.get("gameLens") or [] if lane.get("carriedForward")),
    }


# ------------------------------------------------------------------------------------- the midnight roll (#776)
# Module docstring, "A GAME STILL LIVE AT MIDNIGHT CENTRAL", has the measurement.
PRIOR_DATE_HOURS_ENV = "SYNDICATE_NBA_LIVE_RESIM_PRIOR_DATE_HOURS"
DEFAULT_PRIOR_DATE_HOURS = 4.0
MAX_PRIOR_DATE_HOURS = 12.0
# The key a previous date's game row carries in today's snapshot, so a reader that files rows by date can tell it
# from today's rows.
SLATE_DATE_KEY = "slateDate"
# (league, date) whose ESPN scoreboard read every event final: nothing on it can go live again, so later ticks in
# the window skip the fetch. Per process; a restart re-reads it once.
_PRIOR_SLATE_FINAL: set[tuple[str, str]] = set()


def prior_date_hours(env: Optional[Mapping[str, str]] = None) -> float:
    """Hours after midnight Central during which the loop's tick also re-sims the previous date's in-progress
    games. Absent, unparseable, negative or not finite = DEFAULT_PRIOR_DATE_HOURS; "0" turns it off; capped at
    MAX_PRIOR_DATE_HOURS."""
    raw = str((env if env is not None else os.environ).get(PRIOR_DATE_HOURS_ENV, "") or "").strip()
    try:
        value = float(raw) if raw else DEFAULT_PRIOR_DATE_HOURS
    except ValueError:
        return DEFAULT_PRIOR_DATE_HOURS
    if not math.isfinite(value) or value < 0:
        return DEFAULT_PRIOR_DATE_HOURS
    return min(value, MAX_PRIOR_DATE_HOURS)


def prior_slate_date(now: Optional[datetime] = None, *, hours: Optional[float] = None) -> Optional[str]:
    """The previous Central date while `now` is less than `hours` past midnight Central; else None (always None
    when `hours` is 0). Elapsed time is measured in UTC, so a DST night counts real hours."""
    from datetime import timedelta

    from syndicate.features.shared.timezone import CENTRAL_TIMEZONE

    window = prior_date_hours() if hours is None else float(hours)
    if window <= 0:
        return None
    central = (now or datetime.now(timezone.utc)).astimezone(CENTRAL_TIMEZONE)
    midnight = central.replace(hour=0, minute=0, second=0, microsecond=0)
    if central.astimezone(timezone.utc) - midnight.astimezone(timezone.utc) >= timedelta(hours=window):
        return None
    return (central.date() - timedelta(days=1)).isoformat()


def previous_for_slate(previous: Optional[Mapping[str, Any]], date_str: str) -> Optional[dict[str, Any]]:
    """The last snapshot cut to ONE slate's rows, shaped as that slate's own snapshot (`date` = `date_str`) so
    `_prior_live_rows` and `_prior_posted_lines` read it unchanged. A row belongs to its `slateDate`, else to the
    snapshot's `date`: the first tick after the roll hands the previous date the whole pre-midnight snapshot, a
    later tick hands it the rows stamped with it, and today never sees them. Every other key is the snapshot's own.
    None when there is no snapshot."""
    if not isinstance(previous, Mapping):
        return None
    snap_date = str(previous.get("date") or "")
    games = [g for g in previous.get("games") or []
             if isinstance(g, Mapping) and str(g.get(SLATE_DATE_KEY) or snap_date) == str(date_str)]
    return {**previous, "date": str(date_str), "games": games}


def prior_slate_snapshot(prior_date: str, *, fetch_scoreboard: Optional[Callable[..., Any]] = None,
                         league: str = LEAGUE, **kwargs: Any) -> tuple[Optional[dict[str, Any]], str]:
    """(the previous date's snapshot, "") when a game on it is still in progress; else (None, why it was skipped).
    The build is `build_live_lens_snapshot` on THAT date -- its persisted engine inputs, its props file -- fed the
    scoreboard read here, so a quiet night costs one scoreboard fetch and nothing else. `kwargs` go to the build
    (the caller passes `previous` already cut to this slate)."""
    from syndicate.features.shared import basketball_pbp as pbp

    key = (str(league).lower(), str(prior_date))
    if key in _PRIOR_SLATE_FINAL:
        return None, "slate_final"
    fetch = fetch_scoreboard or pbp.fetch_scoreboard
    try:
        board = fetch(league, str(prior_date).replace("-", ""))
    except Exception as exc:  # noqa: BLE001 -- named on the tick line; today's slate still runs
        return None, f"scoreboard_fetch_failed:{type(exc).__name__}"
    states = [str(ev.get("status_state") or ev.get("state") or "").lower() for ev in pbp.scoreboard_events(board)]
    if "in" not in states:
        if states and all(state == "post" for state in states):
            _PRIOR_SLATE_FINAL.add(key)
            return None, "slate_final"
        return None, "none_in_progress"
    snapshot = build_live_lens_snapshot(str(prior_date), fetch_scoreboard=lambda *_a, **_k: board, league=league,
                                        **kwargs)
    return snapshot, ""


def merge_prior_slate(snapshot: Mapping[str, Any], prior: Mapping[str, Any]) -> dict[str, Any]:
    """Today's snapshot with the previous date's games in front, each stamped `slateDate`. The refusal and carry
    counts and the tick's cost add up; `priorSlate` keeps the previous date's own. An event on both dates'
    scoreboards keeps today's row."""
    out = dict(snapshot)
    today_games = list(snapshot.get("games") or [])
    today_ids = {str(g.get("event_id")) for g in today_games if isinstance(g, Mapping)}
    prior_date = str(prior.get("date") or "")
    prior_games = [{**g, SLATE_DATE_KEY: prior_date} for g in prior.get("games") or []
                   if isinstance(g, Mapping) and str(g.get("event_id")) not in today_ids]
    out["games"] = prior_games + today_games
    out["refusalsByReason"] = _refusals_by_reason(out["games"])
    out["carriedForward"] = sum(1 for g in out["games"] for lane in g.get("gameLens") or [] if lane.get("carriedForward"))
    out["elapsedSeconds"] = round(float(snapshot.get("elapsedSeconds") or 0.0) + float(prior.get("elapsedSeconds") or 0.0), 2)
    out["priorSlate"] = {"date": prior_date, "games": len(prior_games),
                         "resimmed": _fresh_lanes(prior_games),
                         "carriedForward": sum(1 for g in prior_games for lane in g.get("gameLens") or []
                                               if lane.get("carriedForward")),
                         "elapsedSeconds": prior.get("elapsedSeconds"),
                         "refusalsByReason": dict(prior.get("refusalsByReason") or {}),
                         "dropped_also_today": len(prior.get("games") or []) - len(prior_games)}
    return out


def _fresh_lanes(games: Sequence[Mapping[str, Any]]) -> int:
    """Lanes re-simmed THIS tick: a carried lane was not."""
    return sum(1 for g in games for lane in g.get("gameLens") or []
               if lane.get("source") == LIVE_RESIM_LENS_SOURCE and not lane.get("carriedForward"))


def _lane_row(event_id: str, home: str, away: str, facts: Optional[ResumeFacts], result: Any,
              match: Optional[Mapping[str, Any]] = None, *, league: str = LEAGUE) -> dict[str, Any]:
    home_name = team_name(league, home)
    away_name = team_name(league, away)
    return {
        "event_id": event_id,
        # FULL NAMES under `home`/`away`: `live_gameline_join` keys on the first of (matchup, away/home,
        # away_name/home_name) that yields two names, so tricodes here would win and match no board row.
        # SHARED BY THE SUCCESS AND THE REFUSAL PATH (NHL's rule): a refusal the board cannot key is invisible.
        "home": home_name,
        "away": away_name,
        "home_name": home_name,
        "away_name": away_name,
        "home_code": str(home).upper(),
        "away_code": str(away).upper(),
        # The props join decides live/final from this text; only games resumed from an `in` state reach here
        # with facts, and a refused game says nothing it does not know.
        "status": {"detailedState": "In Progress" if facts else "Unknown"},
        "gameLens": build_game_lens(facts, result, live_state_as_of=facts.as_of if facts else "",
                                    match_report=match),
    }


def _refusals_by_reason(games: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """What THIS tick refused. A carried lane is still a refusal this tick (`carriedRefusal`); carrying is
    counted separately (`carriedForward`), so the budget running out never disappears from the tick line."""
    out: dict[str, int] = {}
    for g in games:
        for lane in g.get("gameLens") or []:
            if lane.get("source") == PREGAME_LENS_SOURCE:
                r = str(lane.get("liveResimRefusal") or "unknown")
            elif lane.get("carriedForward"):
                r = str(lane.get("carriedRefusal") or "unknown")
            else:
                continue
            out[r] = out.get(r, 0) + 1
    return out


# ------------------------------------------------------------------------------------------- the tick / loop
#
# A DEDICATED THREAD, NOT A `_LIVE_LENS_SPORTS` BUILDER. The shared live-lens loop builds every sport in turn, and
# a re-sim at 100-200 sims/game takes tens of seconds per game (measured 2026-10-09, engine column memo on: ~0.25
# s/draw at end Q1, ~0.05 at 5:00 Q4). Inside that loop it would delay every other sport's lens. Here it runs on its
# own cadence and writes `live/nba_live_resim.json`; the board's gameline join reads that file
# (`board_enrichment._LIVE_GAMELINE_SNAPSHOT_PATHS["nba"]`) and the NBA page lens merges its lanes and props in.
#
# OFF UNLESS `SYNDICATE_NBA_LIVE_RESIM` IS SET. Absent is off, checked not assumed: turning on a CPU-heavy loop is a
# fleet decision, and a restart for another lane must not switch it on by accident.

LIVE_RESIM_ENV = "SYNDICATE_NBA_LIVE_RESIM"
LIVE_RESIM_INTERVAL_ENV = "SYNDICATE_NBA_LIVE_RESIM_INTERVAL_SECONDS"
# Well under the 8 MB keyvalue cap (2026-10-08: the NBA lens was refused at 9.6 MB for per-player rows). Over
# this, props are dropped (`props_over_size_budget`); game lines are never dropped for size.
MAX_SNAPSHOT_BYTES = 6_000_000

import threading as _threading  # noqa: E402

_LOOP_THREAD: Optional[_threading.Thread] = None
_LOOP_STOP = _threading.Event()
_LOOP_LOCK = _threading.Lock()


def nba_live_resim_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    raw = str((env if env is not None else os.environ).get(LIVE_RESIM_ENV, "") or "").strip().lower()
    return raw in {"1", "true", "on", "yes"}


def _interval_seconds(env: Optional[Mapping[str, str]] = None) -> float:
    raw = str((env if env is not None else os.environ).get(LIVE_RESIM_INTERVAL_ENV, "") or "").strip()
    try:
        return max(30.0, float(raw or 120))
    except ValueError:
        return 120.0


def fit_snapshot_to_budget(snapshot: dict[str, Any], *, max_bytes: int = MAX_SNAPSHOT_BYTES) -> tuple[dict[str, Any], int]:
    """Measure the serialized snapshot; over budget, drop props (never game lines) and say so per game."""
    import json

    size = len(json.dumps(snapshot, separators=(",", ":")))
    if size <= max_bytes:
        return snapshot, size
    for g in snapshot.get("games") or []:
        if g.get("liveProps"):
            g["liveProps"] = []
            g["livePropsRefusal"] = "props_over_size_budget"
    snapshot["propsDroppedForSize"] = True
    return snapshot, len(json.dumps(snapshot, separators=(",", ":")))


# SHADOW HISTORY (2026-10-16). The tick OVERWRITES `live/nba_live_resim.json`, so a shadow season leaves nothing to
# grade. THE VALID READ failed (findings_2026-10-09 §13); the next gate is FORWARD, on the 2026-27 regular season --
# the only untouched holdout -- and needs every tick's lanes kept. One compact row per game per tick, appended to
# `<data root>/nba_source/data/processed/live_resim_history/<date>.jsonl` (~2-3 KB/row with the two histograms;
# ~2 MB/day on a 10-game slate). Local disk only, never keyvalue, never read on a request path. Absent env = ON
# whenever the re-sim loop runs (the loop itself is SYNDICATE_NBA_LIVE_RESIM-gated); `off` disables it. A failure
# is printed and swallowed: history can never stop a tick.
LIVE_RESIM_HISTORY_ENV = "SYNDICATE_NBA_LIVE_RESIM_HISTORY"


def live_resim_history_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    raw = str((env if env is not None else os.environ).get(LIVE_RESIM_HISTORY_ENV) or "").strip().lower()
    return raw not in ("0", "false", "off", "no")


def live_resim_history_path(date_str: str, *, root: Optional[Path] = None, league: str = LEAGUE) -> Path:
    if root is None:
        from syndicate.features.shared.refresh_state_store import data_root

        root = data_root()
    return Path(root) / f"{league}_source" / "data" / "processed" / "live_resim_history" / f"{date_str}.jsonl"


def history_rows(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One compact row per game lane in a snapshot: state, the published numbers and their histograms, provenance."""
    rows: list[dict[str, Any]] = []
    for g in snapshot.get("games") or []:
        for lane in g.get("gameLens") or []:
            if lane.get("carriedForward"):
                # A CARRIED LANE IS NOT A NEW MEASUREMENT -- its numbers are already in the history under their own
                # `as_of`. Record what this tick actually produced: the refusal, exactly as before carrying existed.
                lane = {"source": PREGAME_LENS_SOURCE, "liveResimRefusal": lane.get("carriedRefusal"),
                        "liveStateAsOf": lane.get("refusedStateAsOf") or "", "carriedForward": True}
            proj = lane.get("projection") or {}
            rows.append({
                "t": snapshot.get("generatedAt"), "date": snapshot.get("date"), "event_id": g.get("event_id"),
                "home_code": g.get("home_code"), "away_code": g.get("away_code"),
                "source": lane.get("source"), "refusal": lane.get("liveResimRefusal"),
                "as_of": lane.get("liveStateAsOf"),
                "period": proj.get("period"), "clock_s": proj.get("clockSeconds"),
                "home_score": proj.get("homeScore"), "away_score": proj.get("awayScore"),
                "score_source": proj.get("scoreSource"),
                "total": proj.get("total"), "margin": proj.get("homeMargin"), "p_home": lane.get("modelHomeWinProb"),
                "p_ot": lane.get("modelOvertimeProb"),  # #789: graded against whether the game went to overtime
                "sims": lane.get("simsRun"), "total_dist": proj.get("totalRunsDist"), "margin_dist": proj.get("marginDist"),
                "segments": {k: (v or {}).get("total_mean") for k, v in (proj.get("segments") or {}).items()},
                "resume": lane.get("resumeMatch"),
            })
            if lane.get("carriedForward"):
                rows[-1]["carried_forward"] = True
            if g.get(SLATE_DATE_KEY):
                # #776: a previous date's game re-simmed after midnight. The row stays in the TICK's file under the
                # tick's `date` (the live evidence log files it the same way); this says which slate it belongs to.
                rows[-1]["slate_date"] = g.get(SLATE_DATE_KEY)
    return rows


def append_tick_history(snapshot: Mapping[str, Any], date_str: str, *, root: Optional[Path] = None) -> int:
    rows = history_rows(snapshot)
    if not rows:
        return 0
    path = live_resim_history_path(date_str, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, separators=(",", ":"), default=str) + "\n")
    return len(rows)


def run_live_resim_tick(date_str: Optional[str] = None, **kwargs: Any) -> dict[str, Any]:
    """One tick: build, size-check, write. Returns a small status dict (also printed, prefix NBA_LIVE_RESIM_TICK).

    With no `date_str` (the loop), for `prior_date_hours()` after midnight Central the previous date's in-progress
    games are re-simmed first and published in the same snapshot (`merge_prior_slate`, #776); today's slate gets
    the budget they leave. An explicit `date_str` re-sims that date only, as before."""
    from syndicate.features.shared.refresh_state_store import write_json_file
    from syndicate.features.shared.timezone import CENTRAL_TIMEZONE

    prior_date = None
    if not date_str:
        # ONE clock read for both dates, so a tick that straddles 00:00 CT cannot pair the new day with no window.
        clock_now = kwargs.get("now") or datetime.now(timezone.utc)
        date_str = clock_now.astimezone(CENTRAL_TIMEZONE).date().isoformat()
        prior_date = prior_slate_date(clock_now)
    started = time.monotonic()
    if "previous" not in kwargs:
        # The last snapshot this loop wrote -- what the budget-fairness order and the carry read. Unreadable is
        # the pre-carry behaviour (scoreboard order, nothing carried), never a failed tick.
        try:
            from syndicate.features.shared.refresh_state_store import read_json_file

            kwargs["previous"] = read_json_file(live_lens_snapshot_path())
        except Exception:  # noqa: BLE001
            kwargs["previous"] = None
    previous = kwargs.pop("previous")
    # Each date's build sees only its own rows of the last snapshot. For a snapshot with no `slateDate` row (every
    # snapshot before #776, and every one outside the window) this is exactly what the build read before.
    build_kwargs = {**kwargs, "previous": previous_for_slate(previous, date_str)}
    prior, prior_skip = None, ""
    if prior_date and prior_date != date_str:
        try:
            prior, prior_skip = prior_slate_snapshot(prior_date, **{**kwargs,
                                                                    "previous": previous_for_slate(previous, prior_date)})
        except Exception as exc:  # noqa: BLE001 -- the previous date must never cost today's slate its tick
            prior, prior_skip = None, f"error:{type(exc).__name__}"
            print(f"NBA_LIVE_RESIM_PRIOR_ERROR date={prior_date} {type(exc).__name__}: {str(exc)[:300]}", flush=True)
        if prior is not None:
            budget = float(build_kwargs.get("budget_seconds", DEFAULT_BUDGET_SECONDS))
            build_kwargs["budget_seconds"] = max(0.0, budget - float(prior.get("elapsedSeconds") or 0.0))
    snapshot = build_live_lens_snapshot(date_str, **build_kwargs)
    if prior is not None:
        snapshot = merge_prior_slate(snapshot, prior)
    snapshot, size = fit_snapshot_to_budget(snapshot)
    status = {
        "date": date_str,
        "games": len(snapshot.get("games") or []),
        # FRESH lanes only: a carried lane was not re-simmed this tick.
        "resimmed": _fresh_lanes(snapshot.get("games") or []),
        "carried": snapshot.get("carriedForward") or 0,
    }
    if prior_date:
        # #776: only inside the window after midnight Central, and before `refusals` so every field a reader already
        # parses keeps its place. The counts above already include these games.
        prior_counts = snapshot.get("priorSlate") or {}
        status.update({"prior_date": prior_date, "prior_games": int(prior_counts.get("games") or 0),
                       "prior_resimmed": int(prior_counts.get("resimmed") or 0),
                       "prior_carried": int(prior_counts.get("carriedForward") or 0),
                       "prior_skip": prior_skip or "-"})
    status.update({"refusals": snapshot.get("refusalsByReason") or {}, "bytes": size, "written": False,
                   "elapsed_s": None})
    if size <= MAX_SNAPSHOT_BYTES:
        write_json_file(live_lens_snapshot_path(), snapshot)
        status["written"] = True
    if live_resim_history_enabled():
        try:
            status["history_rows"] = append_tick_history(snapshot, date_str)
        except Exception as exc:  # noqa: BLE001 -- history must never stop the tick
            status["history_rows"] = f"FAILED:{type(exc).__name__}"
    status["elapsed_s"] = round(time.monotonic() - started, 1)
    print("NBA_LIVE_RESIM_TICK " + " ".join(f"{k}={v}" for k, v in status.items()), flush=True)
    return status


def _loop() -> None:
    while not _LOOP_STOP.is_set():
        try:
            run_live_resim_tick()
        except Exception as exc:  # noqa: BLE001 -- a bad tick must not kill the loop; it is named, never silent
            print(f"NBA_LIVE_RESIM_TICK_ERROR {type(exc).__name__}: {str(exc)[:300]}", flush=True)
        _LOOP_STOP.wait(_interval_seconds())


def start_nba_live_resim_loop() -> bool:
    """Start the dedicated thread once per process, only when `SYNDICATE_NBA_LIVE_RESIM` is on."""
    global _LOOP_THREAD
    if not nba_live_resim_enabled():
        return False
    with _LOOP_LOCK:
        if _LOOP_THREAD is not None and _LOOP_THREAD.is_alive():
            return False
        _LOOP_STOP.clear()
        _LOOP_THREAD = _threading.Thread(target=_loop, name="syndicate-nba-live-resim", daemon=True)
        _LOOP_THREAD.start()
        print("NBA_LIVE_RESIM_LOOP_STARTED interval_s=%s" % _interval_seconds(), flush=True)
        return True
