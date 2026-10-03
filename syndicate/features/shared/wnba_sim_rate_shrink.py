"""Shrink the WNBA SmartSim's per-minute prop rates toward each player's own as-of rate (lane `wnba-sim-rate-shrink`).

THE DEFECT. Measured 2026-10-03 on as-of re-runs of the engine (availability rule on, lane `wnba-sim-availability`):
with minutes corrected, the sim's prop means were still worse than the player's own season average (points +0.20
MAE), because most of the sim's per-minute departure from the player's own rate is noise.

THE ESTIMATOR, fitted on May-July and tested on Aug-Sep + playoffs (`scripts/fit_wnba_sim_rate_shrink.py`):
    r = r_own + w_s * (r_sim - r_own)      r_sim = sim mean / sim minutes, r_own = season total / season minutes
    new mean = sim minutes * r             (pts w 0.15, reb 0.15, ast 0.10, threes 0.35)
Each player's `<stat>_mean` moves by delta_s, `pra_mean` by the sum, and every ladder is SHIFTED by its components'
summed delta (v' = max(0, round_half_up(v + delta))) -- width untouched (that is lane `wnba-prop-dispersion`'s job).
Held out: points now tie the player's own average (-0.037 [-0.098, +0.026]); rebounds and RA beat it; book-line Brier
improves on every market vs the availability-only ladders.

WHAT IT DOES NOT TOUCH. `<stat>_sd`, `<stat>_q`, team scores (player sums no longer equal the team total after this --
it is an estimator on the published prop distribution, not a re-simulation), and any player without 3 prior games or
without sim minutes (left exactly as the sim had them).

INPUT. `boxscores_history.csv` in the WNBA processed root, games strictly before the slate; factors from
`wnba_sim_rate_shrink.json` (written by the fit script's `--write-artifact`). Missing/unreadable file -> untouched, a
named reason logged (`SIM_RATE_SHRINK skipped reason=...`). Never raises. WNBA only; OFF unless
`SYNDICATE_WNBA_SIM_RATE_SHRINK` is truthy.
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

FLAG = "SYNDICATE_WNBA_SIM_RATE_SHRINK"
FACTOR_FILE = "wnba_sim_rate_shrink.json"
HISTORY_FILE = "boxscores_history.csv"
COMPONENTS = {"pts": "PTS", "reb": "REB", "ast": "AST", "threes": "FG3M"}
LADDER_PARTS = {"pts": ("pts",), "reb": ("reb",), "ast": ("ast",), "threes": ("threes",), "pra": ("pts", "reb", "ast"),
                "pr": ("pts", "reb"), "pa": ("pts", "ast"), "ra": ("reb", "ast")}
W_BOUNDS = (0.0, 1.2)
MIN_GAMES = 3


def flag_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    raw = (env if env is not None else os.environ).get(FLAG)
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}


def load_weights(processed_root: Path) -> Tuple[Optional[Dict[str, float]], str]:
    path = Path(processed_root) / FACTOR_FILE
    if not path.is_file():
        return None, f"factor file absent: {path}"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, f"factor file unreadable: {type(exc).__name__}"
    raw = doc.get("w") if isinstance(doc, dict) else None
    if not isinstance(raw, dict) or not raw:
        return None, "factor file has no 'w' map"
    out: Dict[str, float] = {}
    for key, value in raw.items():
        if key not in COMPONENTS:
            continue
        try:
            w = float(value)
        except (TypeError, ValueError):
            return None, f"weight for {key!r} is not a number"
        if not (W_BOUNDS[0] <= w <= W_BOUNDS[1]) or not math.isfinite(w):
            return None, f"weight for {key!r} = {w} outside {W_BOUNDS}"
        out[key] = w
    if not out:
        return None, "factor file names no known stat"
    return out, "ok"


@lru_cache(maxsize=8)
def _own_rates_cached(path_s: str, mtime: float, date_str: str) -> Tuple[Tuple[str, Tuple[float, ...]], ...]:
    tot: Dict[str, List[float]] = defaultdict(lambda: [0.0] * (len(COMPONENTS) + 2))   # stats..., MIN, games
    with open(path_s, encoding="utf-8", errors="replace") as fh:
        for r in csv.DictReader(fh):
            d = str(r.get("date") or r.get("GAME_DATE") or "")[:10]
            if not d or d >= date_str:
                continue
            try:
                mins = float(r.get("MIN") or 0)
            except ValueError:
                continue
            if mins <= 0:
                continue
            name = str(r.get("PLAYER_NAME") or "")
            acc = tot[name]
            for i, col in enumerate(COMPONENTS.values()):
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
            out[key] = {s: v[i] / v[-2] for i, s in enumerate(COMPONENTS)}
    return out, "ok"


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


def apply_rate_shrink(out: Any, *, league_code: str, processed_root: Path, build_ladder: Optional[Callable],
                      name_key: Callable[[object], str], env: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    summary: Dict[str, Any] = {"applied": False, "players": 0}
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
        weights, reason = load_weights(processed_root)
        rates, reason2 = own_rates(processed_root, str(out.get("date") or ""), name_key) if weights else ({}, reason)
        if not weights or not rates:
            summary["reason"] = reason if not weights else reason2
            print(f"[wnba_sim_rate_shrink] SIM_RATE_SHRINK skipped reason={summary['reason']}", flush=True)
            return summary
        for side in ("home", "away"):
            for row in out["players"].get(side) or []:
                if not isinstance(row, dict):
                    continue
                own = rates.get(str(name_key(row.get("player_name")) or "").strip().upper())
                mins = row.get("min_mean")
                try:
                    mins = float(mins)
                except (TypeError, ValueError):
                    continue
                if not own or not math.isfinite(mins) or mins <= 0:
                    continue
                delta: Dict[str, float] = {}
                for s, w in weights.items():
                    try:
                        m = float(row.get(f"{s}_mean"))
                    except (TypeError, ValueError):
                        continue
                    if not math.isfinite(m):
                        continue
                    target = mins * (own[s] + w * (m / mins - own[s]))
                    delta[s] = target - m
                    row[f"{s}_mean"] = target
                if not delta:
                    continue
                if all(s in delta for s in ("pts", "reb", "ast")):
                    try:
                        row["pra_mean"] = float(row.get("pra_mean")) + delta["pts"] + delta["reb"] + delta["ast"]
                    except (TypeError, ValueError):
                        pass
                ladders = row.get("prop_ladders") if isinstance(row.get("prop_ladders"), dict) else {}
                dists = row.get("prop_distributions") if isinstance(row.get("prop_distributions"), dict) else None
                for key, parts in LADDER_PARTS.items():
                    if key not in ladders or not all(p in delta for p in parts):
                        continue
                    d = sum(delta[p] for p in parts)
                    vals = _values(ladders[key])
                    if not vals:
                        continue
                    new = build_ladder([max(0, _round_half_up(v + d)) for v in vals])
                    if not new:
                        continue
                    ladders[key] = new
                    if dists is not None and key in dists:
                        dists[key] = {f: new.get(f) for f in ("simCount", "mean", "mode", "modeProb", "minTotal", "maxTotal")}
                        dists[key]["distribution"] = new.get("distribution") if isinstance(new.get("distribution"), dict) else {}
                        dists[key]["ladderShape"] = str(new.get("ladderShape") or "exact")
                row["rate_shrink"] = {k: round(v, 4) for k, v in delta.items()}
                summary["players"] += 1
        summary.update(applied=summary["players"] > 0, w=weights, reason="ok")
        out["rate_shrink"] = summary
        print(f"[wnba_sim_rate_shrink] SIM_RATE_SHRINK applied players={summary['players']}", flush=True)
    except Exception as exc:  # noqa: BLE001 -- the sim's result must survive this
        summary["reason"] = f"failed: {type(exc).__name__}: {exc}"
        print(f"[wnba_sim_rate_shrink] SIM_RATE_SHRINK_FAILED {type(exc).__name__}: {exc}", flush=True)
    return summary
