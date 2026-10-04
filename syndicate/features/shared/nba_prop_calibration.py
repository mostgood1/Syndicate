"""NBA SmartSim prop calibration: per-minute RATE SHRINK of the means + SD SCALE of the widths
(lane `nba-lines-props-backtest`).

THE DEFECTS, measured 2026-10-03 on the 2025-26 season (`scripts/backtest_nba_lines_props.py --diagnose`; pre-tip
committed smart-sim output, stats.nba actuals; fit < 2026-03-01, scored on 403 later games incl. playoffs):
  * the sim's per-minute rates are noisier than the player's own: replacing/shrinking them cut test MAE on every
    market (pts -0.37), and the served means lose to the player's own average in 9/11 markets;
  * the served `<stat>_sd` is too narrow: IQR(z)/1.349 = pts 1.52, reb 1.44, ast 1.39, pra 1.85, so the market
    board's Normal probability is badly calibrated (pts reliability term 0.037).

THE ESTIMATOR (constants from `nba_prop_calibration.json`, written by `scripts/fit_nba_prop_calibration.py`):
    r = r_own + w_s * (r_sim - r_own)    r_sim = sim mean / sim minutes, r_own = season-to-date total / minutes
    new <stat>_mean = sim minutes * r              (pra_mean moves by the pts+reb+ast deltas)
    new <stat>_sd   = k_s * <stat>_sd              (pts reb ast threes stl blk tov pra)
Ladders follow the same transforms so every consumer sees one distribution: SHIFTED by the summed component delta
(as `wnba_sim_rate_shrink`), then DILATED around their mean by k (as `wnba_prop_dispersion`); pr/pa/ra ladders use
k_combo = sqrt(sum (k_i sd_i)^2) / sqrt(sum sd_i^2), the same independence the edges' combo sigma assumes.

WHAT IT DOES NOT TOUCH. Team scores and quarters (an estimator on the published prop distribution, not a
re-simulation), `<stat>_q`, players with fewer than MIN_GAMES season games or no sim minutes (left exactly as the
sim had them -- their sd is still scaled, because the width defect is not a rate defect).

INPUT. `boxscores_history.csv` in the NBA processed root (rebuilt each run by
`refresh_nba_oddsapi_props._refresh_boxscores_history_artifact`), games STRICTLY before the slate and on/after the
season start (Aug 1). Missing/invalid factor file or history -> untouched, a named reason printed
(`NBA_PROP_CALIBRATION skipped reason=...`). Never raises. NBA only; OFF unless `SYNDICATE_NBA_PROP_CALIBRATION`
is truthy.
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

FLAG = "SYNDICATE_NBA_PROP_CALIBRATION"
FACTOR_FILE = "nba_prop_calibration.json"
HISTORY_FILE = "boxscores_history.csv"
RATE_STATS = {"pts": "PTS", "reb": "REB", "ast": "AST", "threes": "FG3M", "stl": "STL", "blk": "BLK", "tov": "TOV"}
SD_STATS = ("pts", "reb", "ast", "threes", "stl", "blk", "tov", "pra")
LADDER_PARTS = {"pts": ("pts",), "reb": ("reb",), "ast": ("ast",), "threes": ("threes",), "stl": ("stl",),
                "blk": ("blk",), "tov": ("tov",), "pra": ("pts", "reb", "ast"), "pr": ("pts", "reb"),
                "pa": ("pts", "ast"), "ra": ("reb", "ast")}
W_BOUNDS = (0.0, 1.2)
K_BOUNDS = (0.5, 3.0)
MIN_GAMES = 3


def flag_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    raw = (env if env is not None else os.environ).get(FLAG)
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}


def season_start(date_str: str) -> str:
    """NBA season containing `date_str` starts Aug 1 of its first calendar year (preseason Oct, playoffs to June)."""
    y, m = int(date_str[:4]), int(date_str[5:7])
    return f"{y if m >= 8 else y - 1}-08-01"


def shrink_mean(sim_mean: float, sim_minutes: float, own_rate: float, w: float) -> float:
    """The fitted estimator, exactly as the fit script scores it."""
    return sim_minutes * (own_rate + w * (sim_mean / sim_minutes - own_rate))


def combo_scale(parts: Tuple[str, ...], sds: Mapping[str, float], k: Mapping[str, float]) -> Optional[float]:
    num = den = 0.0
    for p in parts:
        sd, kp = sds.get(p), k.get(p)
        if sd is None or kp is None or not math.isfinite(sd) or sd <= 0:
            return None
        num += (kp * sd) ** 2
        den += sd ** 2
    return math.sqrt(num / den) if den > 0 else None


def load_factors(processed_root: Path) -> Tuple[Optional[Dict[str, Dict[str, float]]], str]:
    path = Path(processed_root) / FACTOR_FILE
    if not path.is_file():
        return None, f"factor file absent: {path}"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, f"factor file unreadable: {type(exc).__name__}"
    if not isinstance(doc, dict):
        return None, "factor file is not an object"
    out: Dict[str, Dict[str, float]] = {"w": {}, "k": {}}
    for block, allowed, bounds, dest in (("w", RATE_STATS, W_BOUNDS, "w"), ("sd_scale", SD_STATS, K_BOUNDS, "k")):
        raw = doc.get(block)
        if raw is None:
            continue
        if not isinstance(raw, dict):
            return None, f"'{block}' is not a map"
        for key, value in raw.items():
            if key not in allowed:
                continue
            try:
                v = float(value)
            except (TypeError, ValueError):
                return None, f"{block}[{key!r}] is not a number"
            if not math.isfinite(v) or not (bounds[0] <= v <= bounds[1]):
                return None, f"{block}[{key!r}] = {v} outside {bounds}"
            out[dest][key] = v
    if not out["w"] and not out["k"]:
        return None, "factor file names no known stat"
    return out, "ok"


@lru_cache(maxsize=8)
def _own_rates_cached(path_s: str, mtime: float, date_str: str) -> Tuple[Tuple[str, Tuple[float, ...]], ...]:
    start = season_start(date_str)
    tot: Dict[str, List[float]] = defaultdict(lambda: [0.0] * (len(RATE_STATS) + 2))   # stats..., MIN, games
    with open(path_s, encoding="utf-8", errors="replace") as fh:
        for r in csv.DictReader(fh):
            d = str(r.get("date") or r.get("GAME_DATE") or "")[:10]
            if not d or d >= date_str or d < start:
                continue
            try:
                mins = float(r.get("MIN") or 0)
            except ValueError:
                continue
            if not math.isfinite(mins) or mins <= 0:
                continue
            acc = tot[str(r.get("PLAYER_NAME") or "")]
            for i, col in enumerate(RATE_STATS.values()):
                try:
                    acc[i] += float(r.get(col) or 0)
                except ValueError:
                    pass
            acc[-2] += mins
            acc[-1] += 1
    return tuple((name, tuple(v)) for name, v in tot.items())


def own_rates(processed_root: Path, date_str: str, name_key: Callable[[object], str]) -> Tuple[Dict[str, Dict[str, float]], str]:
    path = Path(processed_root) / HISTORY_FILE
    if not path.is_file():
        return {}, f"history absent: {path}"
    try:
        rows = _own_rates_cached(str(path), path.stat().st_mtime, str(date_str)[:10])
    except Exception as exc:  # noqa: BLE001
        return {}, f"history unreadable: {type(exc).__name__}"
    out: Dict[str, Dict[str, float]] = {}
    for name, v in rows:
        if v[-1] < MIN_GAMES or v[-2] <= 0:
            continue
        key = str(name_key(name) or "").strip().upper()
        if key:
            out[key] = {s: v[i] / v[-2] for i, s in enumerate(RATE_STATS)}
    return out, ("ok" if out else f"no player with >= {MIN_GAMES} season games before {date_str}")


def _round_half_up(x: float) -> int:
    return int(math.floor(x + 0.5))


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


def transform_values(values: List[int], shift: float, k: float) -> List[int]:
    """Shift by the mean delta, then dilate around the shifted mean by k (the two ladder transforms, in order)."""
    if not values:
        return []
    shifted = [v + shift for v in values]
    mu = sum(shifted) / len(shifted)
    return [max(0, _round_half_up(mu + k * (v - mu))) for v in shifted]


def _f(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def apply_nba_prop_calibration(out: Any, *, league_code: str, processed_root: Path, build_ladder: Optional[Callable],
                               name_key: Callable[[object], str], env: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """Calibrate every player's prop means/sds/ladders in a smart-sim result, in place. Returns (and stamps on the
    result as `nba_prop_calibration`) what it did, so a reader can tell a calibrated row from an untouched one."""
    summary: Dict[str, Any] = {"applied": False, "players": 0, "players_rate_shrunk": 0, "ladders": 0}
    try:
        if str(league_code or "").strip().lower() != "nba":
            summary["reason"] = "not nba"
            return summary
        if not flag_enabled(env):
            summary["reason"] = f"{FLAG} off"
            return summary
        if not isinstance(out, dict) or not isinstance(out.get("players"), dict):
            summary["reason"] = "no players block"
            return summary
        factors, reason = load_factors(processed_root)
        if factors is None:
            summary["reason"] = reason
            print(f"[nba_prop_calibration] NBA_PROP_CALIBRATION skipped reason={reason}", flush=True)
            return summary
        w, k = factors["w"], factors["k"]
        rates, rate_reason = own_rates(processed_root, str(out.get("date") or "")[:10], name_key) if w else ({}, "no w")
        summary["rate_reason"] = rate_reason
        for side in ("home", "away"):
            for row in out["players"].get(side) or []:
                if not isinstance(row, dict):
                    continue
                orig_sd = {s: _f(row.get(f"{s}_sd")) for s in SD_STATS}
                delta: Dict[str, float] = {}
                own = rates.get(str(name_key(row.get("player_name")) or "").strip().upper()) if rates else None
                mins = _f(row.get("min_mean"))
                if own and mins and mins > 0:
                    for s, ws in w.items():
                        m = _f(row.get(f"{s}_mean"))
                        if m is None:
                            continue
                        target = shrink_mean(m, mins, own[s], ws)
                        delta[s] = target - m
                        row[f"{s}_mean"] = target
                    if all(s in delta for s in ("pts", "reb", "ast")) and _f(row.get("pra_mean")) is not None:
                        row["pra_mean"] = float(row["pra_mean"]) + delta["pts"] + delta["reb"] + delta["ast"]
                scaled = {}
                for s, ks in k.items():
                    sd = orig_sd.get(s)
                    if sd is not None and sd > 0:
                        row[f"{s}_sd"] = sd * ks
                        scaled[s] = ks
                ladders = row.get("prop_ladders") if isinstance(row.get("prop_ladders"), dict) else {}
                dists = row.get("prop_distributions") if isinstance(row.get("prop_distributions"), dict) else None
                if callable(build_ladder):
                    for key, parts in LADDER_PARTS.items():
                        payload = ladders.get(key)
                        if not isinstance(payload, Mapping):
                            continue
                        shift = sum(delta[p] for p in parts) if all(p in delta for p in parts) else 0.0
                        kk = k.get(key) if len(parts) == 1 or key == "pra" else combo_scale(parts, orig_sd, k)
                        kk = kk if kk is not None else 1.0
                        if shift == 0.0 and kk == 1.0:
                            continue
                        vals = _values(payload)
                        new = build_ladder(transform_values(vals, shift, kk)) if vals else None
                        if not new:
                            continue
                        ladders[key] = new
                        if dists is not None and key in dists:
                            dists[key] = {f: new.get(f) for f in ("simCount", "mean", "mode", "modeProb", "minTotal", "maxTotal")}
                            dists[key]["distribution"] = new.get("distribution") if isinstance(new.get("distribution"), dict) else {}
                            dists[key]["ladderShape"] = str(new.get("ladderShape") or "exact")
                        summary["ladders"] += 1
                if delta or scaled:
                    row["nba_prop_calibration"] = {"mean_delta": {s: round(v, 4) for s, v in delta.items()}, "sd_scale": scaled}
                    summary["players"] += 1
                    summary["players_rate_shrunk"] += bool(delta)
        summary.update(applied=summary["players"] > 0, w=w, k=k, reason="ok")
        out["nba_prop_calibration"] = summary
        print(f"[nba_prop_calibration] NBA_PROP_CALIBRATION applied players={summary['players']} "
              f"rate_shrunk={summary['players_rate_shrunk']} ladders={summary['ladders']} rates={rate_reason}", flush=True)
    except Exception as exc:  # noqa: BLE001 -- the sim's result must survive this
        summary["reason"] = f"failed: {type(exc).__name__}: {exc}"
        print(f"[nba_prop_calibration] NBA_PROP_CALIBRATION_FAILED {type(exc).__name__}: {exc}", flush=True)
    return summary
