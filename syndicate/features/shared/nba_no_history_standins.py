"""Stand-ins for NBA players the book prices but the SmartSim cannot see: no row in player_logs.csv (lane
``nba-no-history-admit``, side session of ``nba-current-rosters``).

WHY. The sim's per-team pool is ``props_predictions_<D>.csv``, and ``build_features_for_date_local`` writes a row only
for a player with at least one played ``player_logs.csv`` row (this season, else his most recent prior season). The
fleet's file holds ONLY 2025-26, so on 2026-10-21 eleven players with a posted pre-tip prop line were absent from the
sim (7 rookies: Dybantsa, Boozer, Peterson, Wilson, Acuff, Lendeborg, Wagler; 4 who missed 2025-26: Lillard,
Haliburton, Irving, VanVleet) and their minutes went to teammates (DAL simulated 9 players, P.J. Washington 39.1 min
against his own 30.9). This module puts a stand-in for each of them in the pool.

WHAT A STAND-IN IS, and where each number comes from:

  * WHO: on the team's ESPN current roster for the date (``nba_current_rosters.current_roster_index``), a posted
    pre-tip ``player_*`` line in THIS game (``oddsapi_player_props_<D>.csv``, snapshot before commence), not already
    in the pool under any team, and at least ``MIN_PRESEASON_GAMES`` appearances in this season's preseason box scores
    (``rotation_stints/player_checks_<date>.csv``, the P2 stints producer). The injury feed still applies after this:
    a stand-in the injury map excludes is dropped like any pool row.
  * MINUTES: ``minutes_prior`` = 2.012 + 0.577 x preseason mean minutes + 15.148 x preseason start share, clamped to
    [10, 36]. Fitted on 2025-26 (``player_checks`` season 2026): 394 players with >= 2 preseason games, target = mean
    minutes over the games they played among their team's first 5 regular-season games. In-sample MAE 5.26 min, vs
    7.40 for "regular = preseason mean" (bias -1.13) and 6.92 without the start share. One season, three parameters.
  * RATES: MARKET-IMPLIED. pts / reb / ast / threes / stl / blk / tov = the median over books of the latest pre-tip
    Over line for that stat; a stat with no line gets the league per-minute rate x ``minutes_prior`` (pooled over the
    newest season in ``player_logs.csv``). The sim reads a player with no priors through ``pred_* / sim minutes`` and
    the roll5/roll10 totals; both are set to the same numbers, so his per-minute rates are the line over his minutes.

WHAT IT MUST NEVER DO. The stand-in's own rates ARE the market, so the model has no view on his own props: an edge on
one would be the sim's minutes noise against the book's line. Every stand-in row carries ``pool_source =
SOURCE`` and the sim stamps the names in ``context.no_history_standins``; consumers that price a player's own props
must skip them (see the lane's findings for the list). The stand-in exists to put the right number of minutes and
shots in his TEAMMATES' simulation, nothing else.

SWITCH. ``SYNDICATE_NBA_NO_HISTORY_STANDINS``: ``off`` (default, absent = off -- a new mechanism on a calibrated
engine, model_engine_standard.md), ``shadow`` (compute and log who would be admitted, change nothing), ``on``.
"""
from __future__ import annotations

import csv
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import median
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

FLAG = "SYNDICATE_NBA_NO_HISTORY_STANDINS"
SOURCE = "nba_no_history_standin_v1"
MODES = ("off", "shadow", "on")

# preseason -> regular-season minutes, fitted on 2025-26 (see module docstring)
MIN_INTERCEPT = 2.012
MIN_PER_PRESEASON_MIN = 0.577
MIN_PER_START_SHARE = 15.148
MINUTES_FLOOR = 10.0
MINUTES_CAP = 36.0
MIN_PRESEASON_GAMES = 2

# market (oddsapi key without the "player_" prefix) -> sim stat
STAT_MARKETS = {
    "points": "pts",
    "rebounds": "reb",
    "assists": "ast",
    "threes": "threes",
    "steals": "stl",
    "blocks": "blk",
    "turnovers": "tov",
}
LOGS_STAT_COLS = {"pts": "PTS", "reb": "REB", "ast": "AST", "threes": "FG3M", "stl": "STL", "blk": "BLK", "tov": "TOV"}
# league per-minute rates when player_logs.csv is unreadable: the fleet's file measured 2026-10-20 (2025-26 regular
# season, SEASON_ID 22025, every row with MIN > 0; sum stat / sum minutes)
FALLBACK_RATES_PM = {"pts": 0.4790, "reb": 0.1814, "ast": 0.1108, "threes": 0.0551, "stl": 0.0349, "blk": 0.0201,
                     "tov": 0.0572}
ROLL_WINDOWS = (3, 5, 10)


def mode(env: Optional[Mapping[str, str]] = None) -> str:
    raw = str((env if env is not None else os.environ).get(FLAG) or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return "on"
    if raw == "shadow":
        return "shadow"
    return "off"


def minutes_prior(preseason_mean_minutes: float, start_share: float) -> float:
    m = MIN_INTERCEPT + MIN_PER_PRESEASON_MIN * float(preseason_mean_minutes) + MIN_PER_START_SHARE * float(start_share)
    return float(min(MINUTES_CAP, max(MINUTES_FLOOR, m)))


def _season_end_year(date_str: str) -> int:
    y, m = int(str(date_str)[:4]), int(str(date_str)[5:7])
    return y + 1 if m >= 7 else y


@dataclass
class StandIn:
    player_name: str
    team: str
    opponent: str
    is_home: bool
    player_id: Optional[int]
    espn_id: str
    position: str
    preseason_games: int
    preseason_mean_minutes: float
    start_share: float
    minutes: float
    lines: Dict[str, float] = field(default_factory=dict)
    rates_pm: Dict[str, float] = field(default_factory=dict)
    rate_source: Dict[str, str] = field(default_factory=dict)


def _read_csv(path: Path) -> List[Dict[str, str]]:
    try:
        with Path(path).open(encoding="utf-8", errors="replace", newline="") as fh:
            return list(csv.DictReader(fh))
    except (OSError, csv.Error):
        return []


def posted_lines(processed_root: Path, date_str: str, *, to_tri: Callable[[Any], str], name_key: Callable[[Any], str]
                 ) -> Dict[Tuple[frozenset, str], Dict[str, float]]:
    """{(frozenset({home, away}), name_key): {stat: median over books of each book's latest pre-tip Over line}}."""
    latest: Dict[Tuple[frozenset, str, str, str], Tuple[str, float]] = {}
    for r in _read_csv(Path(processed_root) / f"oddsapi_player_props_{str(date_str)[:10]}.csv"):
        market = str(r.get("market") or "")
        if not market.startswith("player_") or market.endswith("_alternate"):
            continue
        stat = STAT_MARKETS.get(market[len("player_"):])
        if stat is None or str(r.get("outcome_name") or "").strip().lower() != "over":
            continue
        snap, commence = str(r.get("snapshot_ts") or ""), str(r.get("commence_time") or "")
        if commence and snap and snap[:19] >= commence[:19]:
            continue  # posted after tip: not a pre-tip line
        try:
            point = float(r.get("point"))
        except (TypeError, ValueError):
            continue
        home, away, key = to_tri(r.get("home_team")), to_tri(r.get("away_team")), name_key(r.get("player_name"))
        if not (home and away and key):
            continue
        slot = (frozenset((home, away)), key, stat, str(r.get("bookmaker") or ""))
        if slot not in latest or snap >= latest[slot][0]:
            latest[slot] = (snap, point)
    pooled: Dict[Tuple[frozenset, str], Dict[str, List[float]]] = {}
    for (event, key, stat, _book), (_snap, point) in latest.items():
        pooled.setdefault((event, key), {}).setdefault(stat, []).append(point)
    return {k: {stat: float(median(v)) for stat, v in stats.items()} for k, stats in pooled.items()}


def preseason_minutes(processed_root: Path, date_str: str) -> Dict[str, List[Tuple[float, int]]]:
    """{espn player id: [(box minutes, starter 0/1), ...]} over this season's preseason games dated before the slate.
    ``player_checks`` labels a season by its END year (2026-10 games are season 2027)."""
    season = str(_season_end_year(date_str))
    slate = str(date_str)[:10]
    season_open = f"{int(season) - 1}-09-01"  # no NBA preseason game is earlier; skips last season's ~700 files
    out: Dict[str, List[Tuple[float, int]]] = {}
    for path in sorted((Path(processed_root) / "rotation_stints").glob("player_checks_*.csv")):
        day = path.stem[len("player_checks_"):]
        if day >= slate or day < season_open:
            continue
        for r in _read_csv(path):
            if str(r.get("league") or "nba").lower() != "nba" or str(r.get("season")) != season:
                continue
            if str(r.get("season_type") or "").lower() != "preseason":
                continue
            try:
                minutes = float(r.get("box_minutes") or 0.0)
            except ValueError:
                continue
            if minutes <= 0.0:
                continue
            pid = str(r.get("player_id") or "").strip()
            if pid:
                out.setdefault(pid, []).append((minutes, 1 if str(r.get("starter") or "0").strip() in {"1", "True", "true"} else 0))
    return out


def league_rates_pm(processed_root: Path) -> Dict[str, float]:
    """Per-minute league rates over the newest season in player_logs.csv (sum stat / sum minutes, MIN > 0)."""
    rows = _read_csv(Path(processed_root) / "player_logs.csv")
    if not rows:
        return dict(FALLBACK_RATES_PM)
    newest = max((str(r.get("SEASON_ID") or "") for r in rows), default="")
    tot = {k: 0.0 for k in LOGS_STAT_COLS}
    mins = 0.0
    for r in rows:
        if str(r.get("SEASON_ID") or "") != newest:
            continue
        try:
            m = float(r.get("MIN") or 0.0)
        except ValueError:
            continue
        if m <= 0.0:
            continue
        mins += m
        for stat, col in LOGS_STAT_COLS.items():
            try:
                tot[stat] += float(r.get(col) or 0.0)
            except ValueError:
                pass
    if mins <= 0.0:
        return dict(FALLBACK_RATES_PM)
    return {stat: tot[stat] / mins for stat in LOGS_STAT_COLS}


def build_standins(*, processed_root: Path, date_str: str, props_df, name_key: Callable[[Any], str],
                   to_tri: Callable[[Any], str], roster=None) -> Tuple[List[StandIn], Dict[str, Any]]:
    """Every stand-in for the slate's games, and a diagnostic of who was considered and why each was not admitted."""
    from syndicate.features.shared.nba_current_rosters import current_roster_index, roster_path

    processed_root = Path(processed_root)
    date_s = str(date_str)[:10]
    diag: Dict[str, Any] = {"date": date_s, "admitted": [], "skipped": {}}
    idx = roster if roster is not None else current_roster_index(processed_root, date_s)
    if idx is None:
        diag["reason"] = "no_current_roster"
        return [], diag
    roster_rows = {}
    for r in _read_csv(roster_path(processed_root, idx.season)):
        k = name_key(r.get("PLAYER"))
        if k:
            roster_rows[(str(r.get("TEAM_ABBREVIATION") or "").strip().upper(), k)] = r
    in_pool = set()
    home_votes: Dict[Tuple[str, str], int] = {}  # (team, opp) -> rows saying team is home minus rows saying away
    if props_df is not None and not getattr(props_df, "empty", True):
        for name in props_df.get("player_name", []):
            in_pool.add(name_key(name))
        if {"team", "opponent"}.issubset(set(props_df.columns)):
            flags = props_df["is_home"].tolist() if "is_home" in props_df.columns else [None] * len(props_df)
            for team, opp, flag in zip(props_df["team"], props_df["opponent"], flags):
                t, o = to_tri(team), to_tri(opp)
                if not (t and o):
                    continue
                try:
                    vote = 1 if float(flag) >= 0.5 else -1
                except (TypeError, ValueError):
                    vote = 0
                home_votes[(t, o)] = home_votes.get((t, o), 0) + vote
                home_votes[(o, t)] = home_votes.get((o, t), 0) - vote
    games = {(t, o) if v >= 0 else (o, t) for (t, o), v in home_votes.items() if t < o}
    if not games:
        diag["reason"] = "no_slate_games_in_pool"
        return [], diag
    lines = posted_lines(processed_root, date_s, to_tri=to_tri, name_key=name_key)
    pre = preseason_minutes(processed_root, date_s)
    rates = league_rates_pm(processed_root)
    out: List[StandIn] = []
    for home, away in sorted(games):
        event = frozenset((home, away))
        for team, opp in ((home, away), (away, home)):
            for (tri, k), r in sorted(roster_rows.items()):
                if tri != team or k in in_pool:
                    continue
                posted = lines.get((event, k))
                if not posted:
                    continue  # unpriced: the book does not expect him to play -- not this module's population
                label = f"{r.get('PLAYER')} ({team})"
                games_pre = pre.get(str(r.get("ESPN_ID") or "").strip(), [])
                if len(games_pre) < MIN_PRESEASON_GAMES:
                    diag["skipped"][label] = f"preseason_games={len(games_pre)}<{MIN_PRESEASON_GAMES}"
                    continue
                pre_mean = sum(m for m, _ in games_pre) / len(games_pre)
                share = sum(s for _, s in games_pre) / len(games_pre)
                mins = round(minutes_prior(pre_mean, share), 2)
                pid_raw = str(r.get("PLAYER_ID") or "").strip()
                try:
                    pid = int(float(pid_raw)) if pid_raw else None
                except ValueError:
                    pid = None
                s = StandIn(player_name=str(r.get("PLAYER") or ""), team=team, opponent=opp, is_home=(team == home),
                            player_id=pid, espn_id=str(r.get("ESPN_ID") or ""), position=str(r.get("POSITION") or ""),
                            preseason_games=len(games_pre), preseason_mean_minutes=round(pre_mean, 2),
                            start_share=round(share, 3), minutes=mins)
                for stat in LOGS_STAT_COLS:
                    if stat in posted:
                        s.lines[stat] = posted[stat]
                        s.rates_pm[stat] = posted[stat] / mins
                        s.rate_source[stat] = "line"
                    else:
                        s.rates_pm[stat] = float(rates.get(stat, FALLBACK_RATES_PM[stat]))
                        s.rate_source[stat] = "league_pm"
                out.append(s)
                diag["admitted"].append(label)
    return out, diag


def standin_rows(standins: List[StandIn], *, date_str: str) -> List[Dict[str, Any]]:
    """props_predictions-shaped rows: the columns the sim's pool, minutes and prior blend read, all consistent with
    ``minutes`` and the per-minute rates, plus ``pool_source``."""
    rows: List[Dict[str, Any]] = []
    for s in standins:
        rec: Dict[str, Any] = {
            "player_id": s.player_id, "player_name": s.player_name, "team": s.team, "opponent": s.opponent,
            "asof_date": str(date_str)[:10], "is_home": 1.0 if s.is_home else 0.0, "home": bool(s.is_home),
            "position": s.position, "pool_source": SOURCE,
        }
        for w in ROLL_WINDOWS:
            rec[f"roll{w}_min"] = s.minutes
        for stat, rate in s.rates_pm.items():
            mean = rate * s.minutes
            rec[f"pred_{stat}"] = mean
            for w in ROLL_WINDOWS:
                rec[f"roll{w}_{stat}"] = mean
        rec["pred_pra"] = rec["pred_pts"] + rec["pred_reb"] + rec["pred_ast"]
        rows.append(rec)
    return rows


def add_standins(props_df, *, processed_root: Path, date_str: str, league_code: str, to_tri: Callable[[Any], str],
                 name_key: Optional[Callable[[Any], str]] = None, env: Optional[Mapping[str, str]] = None):
    """``props_df`` with a stand-in row appended per admitted player when the switch is ``on``; unchanged otherwise.
    Never raises: any failure returns ``props_df`` as given (the pre-change pool exactly). ``name_key`` defaults to
    the current-roster file's own key, so roster, odds and pool names are all matched one way."""
    m = mode(env)
    if m == "off" or str(league_code or "").strip().lower() != "nba":
        return props_df
    try:
        import pandas as pd

        if name_key is None:
            from syndicate.features.shared.nba_current_rosters import name_key

        standins, diag = build_standins(processed_root=processed_root, date_str=date_str, props_df=props_df,
                                        name_key=name_key, to_tri=to_tri)
        diag["mode"] = m
        diag["detail"] = [{k: v for k, v in asdict(s).items() if k in ("player_name", "team", "minutes", "preseason_games",
                                                                        "preseason_mean_minutes", "start_share", "lines")}
                          for s in standins]
        print("[nba_no_history_standins] NBA_NO_HISTORY_STANDINS " + json.dumps(diag, default=str), flush=True)
        if m != "on" or not standins:
            return props_df
        extra = pd.DataFrame(standin_rows(standins, date_str=date_str))
        return pd.concat([props_df, extra], ignore_index=True, sort=False)
    except Exception as exc:  # the pool without stand-ins is the safe state
        print(f"[nba_no_history_standins] NBA_NO_HISTORY_STANDINS_FAILED {type(exc).__name__}: {exc}", flush=True)
        return props_df


def standin_names_by_team(props_df) -> Dict[str, List[str]]:
    """{team: [player_name]} of the stand-in rows in a pool (empty when there are none) -- the sim's context stamp."""
    out: Dict[str, List[str]] = {}
    if props_df is None or getattr(props_df, "empty", True) or "pool_source" not in props_df.columns:
        return out
    sub = props_df[props_df["pool_source"].astype(str) == SOURCE]
    for team, name in zip(sub["team"].astype(str), sub["player_name"].astype(str)):
        out.setdefault(team.strip().upper(), []).append(name)
    return out


def tag_sim_output(out, props_df, teams) -> Dict[str, List[Dict[str, Any]]]:
    """Take a sim's stand-ins OUT of its per-player output and record them in ``context.no_history_standins``.

    The stand-in was in the simulation (he took his minutes and shots from his teammates), but his own row is the
    market's line played back, so it must not reach anything that prices a player: every pregame pricer reads
    ``players[]`` -- the props_predictions merge APPENDS any sim player it has no row for, ``cards_sim_detail`` copies
    every row into the ladders the board and the order plan join on, the prop-evidence and market-board views index
    it by name. Removing the row here closes all of them at one point. The context entry keeps minutes and means
    only (no ladders, no distributions), for audit. A sim without stand-ins is left exactly as it was."""
    names = standin_names_by_team(props_df)
    wanted = {str(t or "").strip().upper() for t in teams}
    names = {t: v for t, v in names.items() if t in wanted}
    if not names or not isinstance(out, dict):
        return {}
    from syndicate.features.shared.nba_current_rosters import name_key

    keys = {name_key(n) for v in names.values() for n in v}
    prior_min: Dict[str, float] = {}
    try:
        sub = props_df[props_df["pool_source"].astype(str) == SOURCE]
        for n, m in zip(sub["player_name"], sub["roll10_min"]):
            prior_min[name_key(n)] = float(m)
    except Exception:
        prior_min = {}
    record: Dict[str, List[Dict[str, Any]]] = {t: [] for t in names}
    players = out.get("players") if isinstance(out.get("players"), dict) else {}
    side_team = {"home": str(out.get("home") or "").strip().upper(), "away": str(out.get("away") or "").strip().upper()}
    for side, side_rows in list(players.items()):
        kept = []
        for row in side_rows or []:
            if isinstance(row, dict) and name_key(row.get("player_name")) in keys:
                team = side_team.get(side) or next((t for t, v in names.items() if row.get("player_name") in v), "")
                record.setdefault(team, []).append({
                    "player_name": row.get("player_name"), "pool_source": SOURCE,
                    "minutes_prior": prior_min.get(name_key(row.get("player_name"))),
                    **{k: row.get(k) for k in ("min_mean", "pts_mean", "reb_mean", "ast_mean", "threes_mean") if k in row},
                })
                continue
            kept.append(row)
        players[side] = kept
    if not isinstance(out.get("context"), dict):
        out["context"] = {}
    out["context"]["no_history_standins"] = record
    return record


def is_standin(row: Mapping[str, Any]) -> bool:
    """True for a sim player row (or a pool row) that is a stand-in -- the check every own-prop consumer applies."""
    try:
        return str(row.get("pool_source") or "") == SOURCE
    except AttributeError:
        return False
