"""Re-share a WNBA team's simulated minutes the way teams actually share them (lane `wnba-minutes-redistribution`).

THE DEFECT. Measured 2026-10-04 on the oracle-availability re-run (the sim pool is exactly the players who played,
2026-08-01..10-01, regulation games only; `scripts/diagnose_wnba_minutes_redistribution.py`): the SmartSim spreads a
team's 200 minutes too top-heavily, and when teammates sit it hands their minutes to the regulars in proportion to the
minutes they already have. In reality the freed minutes go further down the bench:
    team-games with >=15 late-out teammate-minutes (79):  top-5 by sim minutes  actual - sim -1.73 [-2.54, -0.88]
                                                          ranks 6-8 +1.25 [+0.54, +1.94], ranks 9+ +1.55 [+0.28, +2.91]
    players averaging < 10 min gain +3.81 in reality vs +1.14 in the sim; 20-30 min players +0.06 vs +1.07.
Even with no late outs the top five are over-projected (-1.20 [-1.94, -0.47]).

THE ESTIMATOR (fitted by `scripts/fit_wnba_minutes_redistribution.py`; parameters in `wnba_sim_minutes_redistribution.json`):
    beta  = clip(b0 + b1 * min(freed, FREED_CAP) / FREED_CAP, 0, BETA_MAX)
    m'_i  = s_i - beta * (s_i - mean(s))              flatten toward the pool mean (sum preserved)
    m''_i = m'_i * (TOTAL - leak) / sum(m')           leave `leak` minutes for players outside the pool
`freed` = as-of mean minutes of the players who played the team's PREVIOUS game and are not in today's pool -- known
before tip (the pool is the sim's own player list; history strictly before the slate date).
Each player's counting-stat means scale by k = m''/s (the per-minute rate is held -- that is lane `wnba-sim-rate-shrink`'s
job, and it runs AFTER this so it sees the new minutes), and every ladder's draws scale by the same k (combos too: a
sum of stats scales like its parts) with largest-remainder rounding, so the ladder mean is k x the old one to 1/n.
NOT the rate shrink's shift-by-delta: a sub-half-unit shift of an integer ladder moves nothing (`scale_values`).

BENCH-ONLY (`"bench_only": true` in the parameter file). The full re-share is REFUTED for props (2026-10-04,
`findings_2026-10-04_wnba_minutes_redistribution.md`): it takes minutes off the regulars at their full per-minute rate,
but the minutes they lose are low-usage ones, so their props got worse. Bench-only applies the re-share only to players
it would GIVE minutes to; everyone it would cut stays exactly as simulated (player minutes then sum to more than 200).

WHAT IT DOES NOT TOUCH. `<stat>_sd`, `<stat>_q`, per-quarter and scenario blocks, team scores (player sums no longer
equal the team total -- this is an estimator on the published prop distribution, not a re-simulation), and any team
whose pool sums to less than half a game of minutes.

INPUT. `boxscores_history.csv` in the WNBA processed root (games strictly before the slate) and the parameter file.
Missing/unreadable -> untouched, a named reason logged (`SIM_MINUTES_REDISTRIBUTION skipped reason=...`). Never raises.
WNBA only; OFF unless `SYNDICATE_WNBA_SIM_MINUTES_REDISTRIBUTION` is truthy.
"""
from __future__ import annotations

import csv
import json
import math
import os
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

FLAG = "SYNDICATE_WNBA_SIM_MINUTES_REDISTRIBUTION"
PARAM_FILE = "wnba_sim_minutes_redistribution.json"
HISTORY_FILE = "boxscores_history.csv"
TOTAL = 200.0
FREED_CAP = 40.0
BETA_MAX = 0.6
LEAK_MAX = 10.0
STATS = ("pts", "reb", "ast", "threes", "stl", "blk", "tov")
LADDER_PARTS = {"pts": ("pts",), "reb": ("reb",), "ast": ("ast",), "threes": ("threes",), "pra": ("pts", "reb", "ast"),
                "pr": ("pts", "reb"), "pa": ("pts", "ast"), "ra": ("reb", "ast")}
ALIASES = {"GS": "GSV", "LV": "LVA", "LA": "LAS", "NY": "NYL", "CONN": "CON", "WAS": "WSH", "PHO": "PHX"}
WNBA_TEAMS = frozenset({"ATL", "CHI", "CON", "DAL", "GSV", "IND", "LAS", "LVA", "MIN", "NYL", "PHX", "POR", "SEA", "TOR", "WSH"})


def flag_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    raw = (env if env is not None else os.environ).get(FLAG)
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}


def load_params(processed_root: Path) -> Tuple[Optional[Dict[str, float]], str]:
    path = Path(processed_root) / PARAM_FILE
    if not path.is_file():
        return None, f"parameter file absent: {path}"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, f"parameter file unreadable: {type(exc).__name__}"
    raw = doc.get("params") if isinstance(doc, dict) else None
    if not isinstance(raw, dict):
        return None, "parameter file has no 'params' map"
    out: Dict[str, float] = {}
    for key, lo, hi in (("b0", -BETA_MAX, BETA_MAX), ("b1", -BETA_MAX, 2 * BETA_MAX), ("leak", 0.0, LEAK_MAX)):
        try:
            v = float(raw[key])
        except (KeyError, TypeError, ValueError):
            return None, f"parameter {key!r} missing or not a number"
        if not math.isfinite(v) or not (lo <= v <= hi):
            return None, f"parameter {key!r} = {v} outside [{lo}, {hi}]"
        out[key] = v
    bench_only = raw.get("bench_only", False)
    if not isinstance(bench_only, bool):
        return None, f"parameter 'bench_only' = {bench_only!r} is not true/false"
    out["bench_only"] = 1.0 if bench_only else 0.0
    return out, "ok"


def _team(raw: object) -> str:
    t = str(raw or "").strip().upper()
    return ALIASES.get(t, t)


@lru_cache(maxsize=8)
def _history_cached(path_s: str, mtime: float) -> Tuple[Tuple[str, str, str, str, float], ...]:
    """(date, game_id, team, player_name, minutes) for every row with a date and a WNBA team, file order."""
    rows: List[Tuple[str, str, str, str, float]] = []
    with open(path_s, encoding="utf-8", errors="replace") as fh:
        for r in csv.DictReader(fh):
            d = str(r.get("date") or r.get("GAME_DATE") or "")[:10]
            team = _team(r.get("TEAM_ABBREVIATION"))
            if not d or team not in WNBA_TEAMS:
                continue
            try:
                mins = float(r.get("MIN") or 0)
            except ValueError:
                continue
            rows.append((d, str(r.get("game_id") or r.get("gameId") or ""), team, str(r.get("PLAYER_NAME") or ""), mins))
    return tuple(rows)


@lru_cache(maxsize=16)
def _asof_index(path_s: str, mtime: float, date_str: str, name_key: Callable[[object], str]
                ) -> Tuple[Dict[str, frozenset], Dict[str, float]]:
    """({team: players who played its last game before date_str}, {player: as-of mean minutes over games played})."""
    rows = _history_cached(path_s, mtime)
    keys: Dict[str, str] = {}
    last_date: Dict[str, str] = {}
    mins: Dict[str, List[float]] = defaultdict(list)
    for d, _gid, team, name, m in rows:
        if d >= date_str:
            continue
        if d > last_date.get(team, ""):
            last_date[team] = d
        if m > 0:
            if name not in keys:
                keys[name] = str(name_key(name) or "").strip().upper()
            mins[keys[name]].append(m)
    played_last: Dict[str, set] = defaultdict(set)
    for d, _gid, team, name, m in rows:
        if m > 0 and d == last_date.get(team) and name in keys:
            played_last[team].add(keys[name])
    return ({t: frozenset(v) for t, v in played_last.items()},
            {k: sum(v) / len(v) for k, v in mins.items() if v})


def freed_minutes(processed_root: Path, date_str: str, team: str, pool_keys: set,
                  name_key: Callable[[object], str]) -> Tuple[Optional[float], str]:
    """As-of mean minutes of players who played `team`'s previous game (before `date_str`) and are not in `pool_keys`."""
    path = Path(processed_root) / HISTORY_FILE
    if not path.is_file():
        return None, f"history absent: {path}"
    try:
        played_last, asof = _asof_index(str(path), path.stat().st_mtime, str(date_str)[:10], name_key)
    except Exception as exc:  # noqa: BLE001
        return None, f"history unreadable: {type(exc).__name__}"
    team = _team(team)
    if team not in played_last:
        return None, "team has no prior game"
    return sum(asof.get(k, 0.0) for k in played_last[team] - set(pool_keys) if k), "ok"


def reshare(sim_minutes: List[float], freed: float, params: Mapping[str, float]) -> List[float]:
    """The estimator on one team's pool. Pure; returns the new minutes in the same order."""
    n = len(sim_minutes)
    if n == 0:
        return []
    beta = params["b0"] + params["b1"] * min(max(freed, 0.0), FREED_CAP) / FREED_CAP
    beta = min(max(beta, 0.0), BETA_MAX)
    mean = sum(sim_minutes) / n
    flat = [s - beta * (s - mean) for s in sim_minutes]
    tot = sum(flat)
    if tot <= 0:
        return list(sim_minutes)
    scale = (sum(sim_minutes) - params["leak"]) / tot
    return [max(0.0, v * scale) for v in flat]


def scale_values(vals: List[int], k: float) -> List[int]:
    """Each draw times k, rounded so the draws' SUM is round(k * sum): floor every draw, then give +1 to the draws with
    the largest remainders (ties in draw order). A plain half-up rounding of v*k (or of v + delta) moves nothing when
    the change is under half a unit -- measured 2026-10-04: threes ladders came out byte-identical and the assists
    Brier delta was [0.0, 0.0008] -- so a low-count stat would silently ignore the minutes change."""
    if not vals:
        return []
    xs = [max(0.0, v * k) for v in vals]
    base = [int(math.floor(x)) for x in xs]
    extra = int(round(sum(xs))) - sum(base)
    order = sorted(range(len(xs)), key=lambda i: (-(xs[i] - base[i]), i))
    for i in order[:max(0, extra)]:
        base[i] += 1
    return base


def _values(payload: Mapping[str, Any]) -> List[int]:
    dist = payload.get("distribution")
    vals: List[int] = []
    if isinstance(dist, Mapping):
        for total, count in dist.items():
            try:
                vals.extend([int(float(total))] * int(count))
            except (TypeError, ValueError):
                return []
    return vals


def apply_minutes_redistribution(out: Any, *, league_code: str, processed_root: Path, build_ladder: Optional[Callable],
                                 name_key: Callable[[object], str], env: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    summary: Dict[str, Any] = {"applied": False, "players": 0, "teams": {}}
    try:
        if str(league_code or "").strip().lower() != "wnba":
            summary["reason"] = "not wnba"
            return summary
        if not flag_enabled(env):
            summary["reason"] = f"{FLAG} off"
            return summary
        if not isinstance(out, dict) or not isinstance(out.get("players"), dict) or not callable(build_ladder):
            summary["reason"] = "no players block or no ladder builder"
            return summary
        params, reason = load_params(processed_root)
        if not params:
            summary["reason"] = reason
            print(f"[wnba_sim_minutes_redistribution] SIM_MINUTES_REDISTRIBUTION skipped reason={reason}", flush=True)
            return summary
        date_s = str(out.get("date") or "")
        for side in ("home", "away"):
            rows = [r for r in (out["players"].get(side) or []) if isinstance(r, dict)]
            sims: List[float] = []
            for r in rows:
                try:
                    v = float(r.get("min_mean"))
                except (TypeError, ValueError):
                    v = float("nan")
                sims.append(v)
            if not rows or not all(math.isfinite(v) and v >= 0 for v in sims) or sum(sims) < TOTAL / 2:
                summary["teams"][side] = "skipped: pool minutes missing or < half a game"
                continue
            team = rows[0].get("team") or out.get(side)
            pool = {str(name_key(r.get("player_name")) or "").strip().upper() for r in rows}
            freed, why = freed_minutes(processed_root, date_s, str(team or ""), pool, name_key)
            if freed is None:
                freed = 0.0
            new = reshare(sims, freed, params)
            summary["teams"][side] = {"team": team, "freed": round(freed, 2), "freed_reason": why}
            for r, s, m in zip(rows, sims, new):
                if s <= 0:
                    continue
                if params.get("bench_only") and m <= s:
                    # Bench-only: a player the re-share would cut is left EXACTLY as simulated, minutes included --
                    # cutting min_mean alone would let the rate shrink (which reads mean / min_mean) re-take the loss.
                    continue
                k = m / s
                delta: Dict[str, float] = {}
                for st in STATS:
                    try:
                        mu = float(r.get(f"{st}_mean"))
                    except (TypeError, ValueError):
                        continue
                    if math.isfinite(mu):
                        delta[st] = mu * (k - 1.0)
                        r[f"{st}_mean"] = mu * k
                if all(st in delta for st in ("pts", "reb", "ast")):
                    try:
                        r["pra_mean"] = float(r.get("pra_mean")) + delta["pts"] + delta["reb"] + delta["ast"]
                    except (TypeError, ValueError):
                        pass
                r["min_mean"] = m
                ladders = r.get("prop_ladders") if isinstance(r.get("prop_ladders"), dict) else {}
                dists = r.get("prop_distributions") if isinstance(r.get("prop_distributions"), dict) else None
                for key in LADDER_PARTS:
                    if key not in ladders:
                        continue
                    vals = _values(ladders[key])
                    if not vals:
                        continue
                    built = build_ladder(scale_values(vals, k))
                    if not built:
                        continue
                    ladders[key] = built
                    if dists is not None and key in dists:
                        dists[key] = {f: built.get(f) for f in ("simCount", "mean", "mode", "modeProb", "minTotal", "maxTotal")}
                summary["players"] += 1
        summary["applied"] = summary["players"] > 0
        summary["params"] = params
        summary["reason"] = "ok" if summary["applied"] else "no team re-shared"
        print(f"[wnba_sim_minutes_redistribution] SIM_MINUTES_REDISTRIBUTION applied players={summary['players']}", flush=True)
        return summary
    except Exception as exc:  # noqa: BLE001
        summary["reason"] = f"error: {type(exc).__name__}"
        print(f"[wnba_sim_minutes_redistribution] SIM_MINUTES_REDISTRIBUTION skipped reason={summary['reason']}", flush=True)
        return summary
