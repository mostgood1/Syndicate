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
"""

from __future__ import annotations

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


def props_csv_path(date: str, *, root: Optional[Path] = None) -> Path:
    if root is None:
        from syndicate.features.shared.basketball_live_state import source_root

        root = source_root(LEAGUE)
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


def resume_from_summary(summary: Mapping[str, Any], *, date: str = "", as_of: str = ""):
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
        rec = pbp.reconstruct(summary, LEAGUE, date=date)
        state = build_live_game_state(summary, LEAGUE, date=date)
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
    if (sum(hp), sum(ap)) != (state.home.score, state.away.score):
        # The design's `pbp_score_mismatch`: the log's scoring plays and the official score disagree, so
        # the per-period split the engine resumes from is not trustworthy. The backtest excludes the same.
        return NbaResimRefusal("pbp_score_mismatch",
                               f"pbp {sum(hp)}-{sum(ap)} official {state.home.score}-{state.away.score}")

    # Where to resume.
    if clock <= 0:
        # A period just ended. Resume from the NEXT period's tip -- in regulation always, after Q4 or an
        # OT only if the game is tied (that is overtime); otherwise the game is decided.
        if period >= _REGULATION_PERIODS and sum(hp) != sum(ap):
            return NbaResimRefusal("regulation_over")
        r_period, r_secs = period + 1, None
        hp, ap = hp + (0,), ap + (0,)
    else:
        r_period, r_secs = period, int(round(clock))

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
        home_score=int(state.home.score), away_score=int(state.away.score), period=period,
        clock_seconds=float(clock), possession=state.possession_side, last_seq=int(state.last_seq),
        as_of=as_of or state.built_at or _utc_now_iso(),
    )
    return state, gs, facts


def _names(state: Any, side: str) -> list[str]:
    by_id = {p.player_id: p.name for p in state.players}
    team = state.home if side == "home" else state.away
    return [by_id[pid] for pid in team.on_floor if pid in by_id]


# ------------------------------------------------------------------------------------------- engine inputs

def engine_inputs_dir(date: str, *, root: Optional[Path] = None) -> Path:
    if root is None:
        from syndicate.features.shared.basketball_live_state import source_root

        root = source_root(LEAGUE)
    return Path(root) / "data" / "processed" / ENGINE_INPUTS_DIRNAME / str(date)


def engine_inputs_path(date: str, home: str, away: str, *, root: Optional[Path] = None) -> Path:
    return engine_inputs_dir(date, root=root) / f"{str(home).upper()}_{str(away).upper()}.pkl"


def persist_engine_inputs(date: str, home: str, away: str, kwargs: Mapping[str, Any], *,
                          root: Optional[Path] = None) -> Path:
    """Write the pregame engine kwargs for one game (atomic). Called once per game at pregame sim time.

    Pickle, because the kwargs are DataFrames + an `EventSimConfig` + `QuarterResult`s and the engine
    must receive the same objects bit for bit (the recorded-corpus pickles are ~100 KB/game)."""
    path = engine_inputs_path(date, home, away, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {k: kwargs[k] for k in _INPUT_KEYS if k in kwargs}
    tmp = path.with_suffix(".tmp")
    with tmp.open("wb") as fh:
        pickle.dump({"schema": ENGINE_INPUTS_SCHEMA, "league": LEAGUE, "date": str(date), "home": str(home).upper(),
                     "away": str(away).upper(), "written_at": _utc_now_iso(), "kwargs": body}, fh, protocol=4)
    tmp.replace(path)
    return path


def load_engine_inputs(date: str, home: str, away: str, *, root: Optional[Path] = None):
    path = engine_inputs_path(date, home, away, root=root)
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
    return dict(kw)


# ------------------------------------------------------------------------------------------- names

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def normalize_name(name: Any) -> str:
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode("ascii").lower()
    s = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in s)
    parts = [p for p in s.split() if p not in _SUFFIXES]
    return " ".join(parts)


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

def stable_seed(event_id: str, last_seq: int) -> int:
    """Same game + same logged state -> same seed, so an unchanged state reproduces its number."""
    return zlib.crc32(f"nba-live-resim|{event_id}|{int(last_seq)}".encode("utf-8")) & 0x7FFFFFFF


def resim_live_game(inputs: Mapping[str, Any], game_state: Any, *, sims: int = DEFAULT_SIMS, base_seed: int = 0,
                    deadline: Optional[float] = None, simulate: Optional[Callable[..., Any]] = None,
                    clock: Callable[[], float] = time.monotonic):
    """Run `sims` resumed games from `game_state`; aggregate full-game and per-period distributions.

    `deadline` is a `clock()` value. Hitting it before `sims` draws finish is `budget_exhausted` -- the
    partial draws are DISCARDED, never published as a thinner number."""
    import numpy as np

    if simulate is None:
        from syndicate.features import basketball_engine as eng
        from syndicate.features.shared.basketball_props_smart_sim import _sample_lineup_local

        lp = eng.league_params(LEAGUE)

        def simulate(rng, gs):  # noqa: E306
            return eng.simulate_pbp_game_boxscore(rng=rng, **dict(inputs), league=lp,
                                                  sample_lineup=_sample_lineup_local, state=gs)

    if sims < MIN_SIMS:
        return NbaResimRefusal("sims_below_floor", f"{sims}<{MIN_SIMS}")
    rng = np.random.default_rng(int(base_seed))
    totals: list[int] = []
    margins: list[int] = []
    periods_h: list[list[int]] = []
    periods_a: list[list[int]] = []
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
        h, a = int(sum(hq)), int(sum(aq))
        totals.append(h + a)
        margins.append(h - a)
        periods_h.append([int(x) for x in hq])
        periods_a.append([int(x) for x in aq])
    n = len(totals)
    wins = sum(1 for m in margins if m > 0)
    out: dict[str, Any] = {
        "sims_run": n,
        "home_win_prob": wins / n,
        "total_mean": float(np.mean(totals)),
        "home_margin_mean": float(np.mean(margins)),
        "total_dist": _hist(totals),
        "margin_dist": _hist(margins),
        "segments": _segments(periods_h, periods_a),
        "player_remainders": _player_remainder_hists(rem, n),
    }
    return out


# Per-player REST-OF-GAME stats. A resumed run's player box lines are the remainder only (resume.py), so the
# final for a prop is actual-so-far + this. Keyed by the engine frame's `player_name`.
PROP_STATS: tuple[tuple[str, str], ...] = (("pts", "points"), ("reb", "rebounds"), ("ast", "assists"), ("threes", "threes"))


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
            hists = {}
            for key, _label in PROP_STATS:
                vals = stats[key] + [0] * (n - len(stats[key]))
                if any(vals):
                    hists[key] = _hist(vals)
            if hists:
                out[side][name] = hists
    return out


def actuals_from_summary(summary: Mapping[str, Any]) -> dict[str, dict[str, int]]:
    """Banked production per player NAME from the LIVE box score (ESPN updates it in game).

    `{normalized name: {"pts","reb","ast","threes"}}`. A malformed cell is skipped, never read as 0: a missing
    actual and a genuine zero are different facts (`wnba_live_prop_rows.to_snapshot_live_props`)."""
    out: dict[str, dict[str, int]] = {}
    for block in ((summary or {}).get("boxscore") or {}).get("players") or []:
        for stat in block.get("statistics") or []:
            names = [str(n) for n in stat.get("names") or []]
            idx = {k: names.index(k) for k in ("PTS", "REB", "AST", "3PT") if k in names}
            for a in stat.get("athletes") or []:
                nm = normalize_name(((a.get("athlete") or {}).get("displayName")) or "")
                vals = a.get("stats") or []
                if not nm or not vals:
                    continue
                row: dict[str, int] = {}
                for col, key in (("PTS", "pts"), ("REB", "reb"), ("AST", "ast"), ("3PT", "threes")):
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


BOARD_PROP_MARKETS = {"pts": "player_points", "reb": "player_rebounds", "ast": "player_assists", "threes": "player_threes"}
_CSV_MARKET_TO_STAT = {v: k for k, v in BOARD_PROP_MARKETS.items()}


def lines_from_props_csv(path: Path, home_name: str, away_name: str) -> dict[tuple[str, str], float]:
    """`(normalized player, stat) -> line` for ONE game from Syndicate's captured OddsAPI props CSV.

    One line per (player, stat): the MODE across books, ties broken low (the WNBA rule,
    `wnba/live_lens.py::_lines_from_odds_csv`). Scoped to the game by both full team names.
    Any failure -> {} (no row is priced)."""
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
                if not stat or str(row.get("outcome_name") or "").strip().lower() != "over":
                    continue
                try:
                    line = float(row.get("point"))
                except (TypeError, ValueError):
                    continue
                key = (normalize_name(row.get("player_name")), stat)
                counts.setdefault(key, _Counter())[line] += 1
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for key, c in counts.items():
        top = max(c.values())
        out[key] = min(v for v, k in c.items() if k == top)
    return out


def build_live_props(result: Mapping[str, Any], actuals: Mapping[str, Mapping[str, int]],
                     lines: Mapping[tuple[str, str], float]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """`liveProps` rows in the snapshot contract `live_projection_join.build_live_prop_index` reads.

    A row exists only where a LINE exists (a probability needs something to be about) and the player has a
    banked actual (a missing actual is not a zero). P(over) = share of draws whose actual + remainder exceeds
    the line. An exact 0 or 1 is a statement about the sample, so it is published as None with the reason."""
    rows: list[dict[str, Any]] = []
    counts = {"players_simmed": 0, "rows": 0, "priced": 0, "no_actual": 0, "certainty_refused": 0}
    for side in ("home", "away"):
        for name, hists in ((result.get("player_remainders") or {}).get(side) or {}).items():
            counts["players_simmed"] += 1
            nk = normalize_name(name)
            act = actuals.get(nk)
            for key, _label in PROP_STATS:
                line = lines.get((nk, key))
                if line is None:
                    continue
                if act is None or key not in act:
                    counts["no_actual"] += 1
                    continue
                hist = hists.get(key) or {"0": int(result.get("sims_run") or 0)}
                total = sum(int(v) for v in hist.values())
                if total <= 0:
                    continue
                banked = int(act[key])
                over = sum(int(c) for v, c in hist.items() if banked + int(v) > line)
                mean_rem = sum(int(v) * int(c) for v, c in hist.items()) / total
                p_over: Optional[float] = round(over / total, 4)
                reason = None
                if p_over in (0.0, 1.0):
                    p_over, reason = None, "certainty_refused"
                    counts["certainty_refused"] += 1
                else:
                    counts["priced"] += 1
                row = {
                    "playerName": name,
                    "prop": BOARD_PROP_MARKETS[key],
                    "line": line,
                    "liveProjection": round(banked + mean_rem, 3),
                    "liveModelProbOver": p_over,
                    "actualSoFar": float(banked),
                    "simsRun": int(result.get("sims_run") or 0),
                    "side": side,
                }
                if reason:
                    row["unpricedReason"] = reason
                rows.append(row)
                counts["rows"] += 1
    return rows, counts


def _hist(values: Sequence[int]) -> dict[str, int]:
    return {str(k): int(v) for k, v in sorted(Counter(int(x) for x in values).items())}


def _segments(ph: list[list[int]], pa: list[list[int]]) -> dict[str, dict[str, Any]]:
    """Quarter and half totals/margins (regulation only; OT sits in the full-game numbers)."""
    segs: dict[str, tuple[int, ...]] = {"q1": (0,), "q2": (1,), "q3": (2,), "q4": (3,), "h1": (0, 1), "h2": (2, 3)}
    out: dict[str, dict[str, Any]] = {}
    for name, idx in segs.items():
        tot, mar = [], []
        for h, a in zip(ph, pa):
            if len(h) < 4 or len(a) < 4:
                continue
            hs, as_ = sum(h[i] for i in idx), sum(a[i] for i in idx)
            tot.append(hs + as_)
            mar.append(hs - as_)
        if tot:
            out[name] = {"total_mean": sum(tot) / len(tot), "total_dist": _hist(tot), "margin_dist": _hist(mar)}
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
        "simsRun": result["sims_run"],
        "liveStateAsOf": live_state_as_of or facts.as_of,
        "projection": {
            "homeMargin": result["home_margin_mean"],
            "total": result["total_mean"],
            "homeScore": facts.home_score,
            "awayScore": facts.away_score,
            "period": facts.period,
            "clockSeconds": facts.clock_seconds,
            # Full-game histograms. Priced by `price_distribution_market` ONLY once the backtest gate has
            # passed for the market (design §5); until then nba is not in `_LIVE_GAMELINE_SPORTS`.
            "totalRunsDist": result["total_dist"],
            "marginDist": result["margin_dist"],
            "segments": result.get("segments") or {},
        },
        "resumeMatch": dict(match_report or {}),
    }]


# ------------------------------------------------------------------------------------------- the snapshot

def live_lens_snapshot_path():
    from syndicate.features.shared.refresh_state_store import data_root

    return data_root() / "live" / "nba_live_resim.json"


def _game_identity(summary: Mapping[str, Any]) -> tuple[str, str, str]:
    from syndicate.features.shared import basketball_pbp as pbp

    meta = pbp.game_meta(summary, LEAGUE)
    return meta.event_id, meta.home.code, meta.away.code


def build_live_lens_snapshot(date_str: str, *, sims: int = DEFAULT_SIMS, budget_seconds: float = DEFAULT_BUDGET_SECONDS,
                             fetch_scoreboard: Optional[Callable[..., Any]] = None,
                             fetch_summary: Optional[Callable[..., Any]] = None,
                             inputs_root: Optional[Path] = None,
                             clock: Callable[[], float] = time.monotonic) -> dict[str, Any]:
    from syndicate.features.shared import basketball_pbp as pbp
    from syndicate.features.shared.request_path_guard import refuse_if_compute_in_request_path

    refuse_if_compute_in_request_path("nba_live_resim_snapshot")
    fetch_scoreboard = fetch_scoreboard or pbp.fetch_scoreboard
    fetch_summary = fetch_summary or pbp.fetch_summary
    started = clock()
    deadline = started + float(budget_seconds)
    games: list[dict[str, Any]] = []
    scoreboard = fetch_scoreboard(LEAGUE, str(date_str).replace("-", ""))
    events = pbp.scoreboard_events(scoreboard)
    for ev in events:
        event_id = str(ev.get("event_id") or ev.get("id") or "")
        state = str(ev.get("status_state") or ev.get("state") or "").lower()
        if state != "in":
            continue
        try:
            summary = fetch_summary(LEAGUE, event_id)
        except Exception as exc:  # noqa: BLE001
            games.append(_lane_row(event_id, "", "", None, NbaResimRefusal("summary_fetch_failed", type(exc).__name__)))
            continue
        _eid, home, away = _game_identity(summary)
        resumed = resume_from_summary(summary, date=str(date_str))
        if isinstance(resumed, NbaResimRefusal):
            games.append(_lane_row(event_id, home, away, None, resumed))
            continue
        _state, gs, facts = resumed
        inputs = load_engine_inputs(str(date_str), home, away, root=inputs_root)
        if isinstance(inputs, NbaResimRefusal):
            games.append(_lane_row(event_id, home, away, facts, inputs))
            continue
        gs, match = map_state_names(gs, inputs["home_players"], inputs["away_players"])
        if clock() >= deadline:
            games.append(_lane_row(event_id, home, away, facts, NbaResimRefusal("budget_exhausted", "before_start")))
            continue
        result = resim_live_game(inputs, gs, sims=sims, base_seed=stable_seed(facts.event_id, facts.last_seq),
                                 deadline=deadline, clock=clock)
        row = _lane_row(event_id, home, away, facts, result, match)
        if not isinstance(result, NbaResimRefusal):
            lines = lines_from_props_csv(props_csv_path(str(date_str), root=inputs_root),
                                         row["home_name"], row["away_name"])
            props, coverage = build_live_props(result, actuals_from_summary(summary), lines)
            row["liveProps"] = props
            row["livePropsCoverage"] = {**coverage, "lines_available": len(lines)}
        games.append(row)
    return {
        "sport": LEAGUE,
        "date": str(date_str),
        "generatedAt": _utc_now_iso(),
        "source": LIVE_RESIM_LENS_SOURCE,
        "simsPerGame": int(sims),
        "budgetSeconds": float(budget_seconds),
        "elapsedSeconds": round(clock() - started, 2),
        "games": games,
        "refusalsByReason": _refusals_by_reason(games),
    }


def _lane_row(event_id: str, home: str, away: str, facts: Optional[ResumeFacts], result: Any,
              match: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "home": home,
        "away": away,
        # SHARED BY THE SUCCESS AND THE REFUSAL PATH (NHL's rule): a refusal the board cannot key is invisible.
        "home_name": NBA_TEAM_NAMES.get(str(home).upper(), ""),
        "away_name": NBA_TEAM_NAMES.get(str(away).upper(), ""),
        # The props join decides live/final from this text; only games resumed from an `in` state reach here
        # with facts, and a refused game says nothing it does not know.
        "status": {"detailedState": "In Progress" if facts else "Unknown"},
        "gameLens": build_game_lens(facts, result, live_state_as_of=facts.as_of if facts else "",
                                    match_report=match),
    }


def _refusals_by_reason(games: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for g in games:
        for lane in g.get("gameLens") or []:
            if lane.get("source") == PREGAME_LENS_SOURCE:
                r = str(lane.get("liveResimRefusal") or "unknown")
                out[r] = out.get(r, 0) + 1
    return out
