"""A negative-binomial SHAPE for WNBA rebounds / assists / threes prop ladders (lane `wnba-prop-shape`).

THE DEFECT. With the mean fixed (lanes `wnba-sim-availability` + `wnba-sim-rate-shrink`), the sim's own ladders for
these low-count stats still priced the book line worse than the player's own average with the player's own spread,
and widening them did nothing: the draw-SHAPE was the defect.

THE ESTIMATOR, fitted on May-July and tested on Aug-Sep + playoffs (`scripts/fit_wnba_prop_shape.py`). Keep the
row's `<stat>_mean` m (already fix #3's when that flag is on); replace the ladder by a negative binomial with mean m
and variance D * m,
    D = (n * D_own + k * D_league) / (n + k)      (D <= 1 -> Poisson)
D_own from the player's own prior games. The fit chose k at "league only" for rebounds and threes and k = 64 for
assists: a player's own dispersion carried no signal; the SHAPE (near-Poisson, D ~1.1-1.2) is what helped. Held out,
pooled over the three markets: book-line Brier -0.0042 [-0.0065, -0.0018] vs the sim ladder; whole-ladder RPS better
on each market. The ladder is materialised as `simCount` values by largest-remainder rounding of the pmf, so every
reader (`wnba_projections._hit_prob_over`, prop evidence) sees an ordinary ladder.

NOT TOUCHED: the combo ladders (PR/PA/RA/PRA stay the sim's joint draws), `<stat>_mean`, `<stat>_sd`.
INPUTS: `wnba_prop_shape.json` (k, D_league per stat) and `boxscores_history.csv` (games before the slate) in the WNBA
processed root. Missing/broken -> untouched with a named reason. Never raises. WNBA only; OFF unless
`SYNDICATE_WNBA_PROP_SHAPE` is set.

GATING (FILE SWITCH, 2026-10-05, user "enable the prop shape and dispersion fixes"): env truthy -> on; env
0/false/no/off -> off, a kill switch over everything; env UNSET -> on only if the factor file carries
`"enabled": true`. The per-run SmartSim subprocess reads the file, so enabling needs no role restart.
"""
from __future__ import annotations

import csv
import json
import math
import os
import statistics
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

FLAG = "SYNDICATE_WNBA_PROP_SHAPE"
FACTOR_FILE = "wnba_prop_shape.json"
HISTORY_FILE = "boxscores_history.csv"
STATS = {"reb": "REB", "ast": "AST", "threes": "FG3M"}
MAX_T = 60
D_BOUNDS = (0.5, 5.0)


def flag_state(env: Optional[Mapping[str, str]] = None) -> str:
    """'on' / 'off' (explicit kill switch) / 'unset'. The env var always wins over the factor file."""
    raw = str((env if env is not None else os.environ).get(FLAG) or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return "on"
    if raw in {"0", "false", "no", "off"}:
        return "off"
    return "unset"


def file_enabled(processed_root: Path) -> Tuple[bool, str]:
    """True only when the factor file parses and says `"enabled": true` (the JSON boolean, nothing truthy-ish)."""
    path = Path(processed_root) / FACTOR_FILE
    if not path.is_file():
        return False, f"factor file absent: {path}"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return False, f"factor file unreadable: {type(exc).__name__}"
    if isinstance(doc, dict) and doc.get("enabled") is True:
        return True, "ok"
    return False, "factor file not enabled"


def flag_enabled(env: Optional[Mapping[str, str]] = None, processed_root: Optional[Path] = None) -> bool:
    state = flag_state(env)
    if state != "unset":
        return state == "on"
    return bool(processed_root is not None and file_enabled(processed_root)[0])


def nb_pmf(m: float, d: float, upto: int = MAX_T) -> List[float]:
    """P(X = x), x = 0..upto; mean m, variance d*m; d <= 1 -> Poisson. Same as `fit_wnba_prop_shape.nb_pmf`."""
    m = max(1e-6, float(m))
    out: List[float] = []
    if d <= 1.0 + 1e-9:
        for x in range(upto + 1):
            out.append(math.exp(-m + x * math.log(m) - math.lgamma(x + 1)))
    else:
        r = m / (d - 1.0)
        p = r / (r + m)
        for x in range(upto + 1):
            out.append(math.exp(math.lgamma(x + r) - math.lgamma(r) - math.lgamma(x + 1) + r * math.log(p) + x * math.log(1 - p)))
    s = sum(out)
    return [v / s for v in out]


def materialise(pmf: List[float], n: int) -> List[int]:
    """n integer values whose histogram is the pmf by largest-remainder rounding (deterministic)."""
    raw = [p * n for p in pmf]
    base = [int(math.floor(x)) for x in raw]
    short = n - sum(base)
    order = sorted(range(len(raw)), key=lambda i: raw[i] - base[i], reverse=True)
    for i in order[:max(0, short)]:
        base[i] += 1
    vals: List[int] = []
    for x, c in enumerate(base):
        vals.extend([x] * c)
    return vals


def load_factors(processed_root: Path) -> Tuple[Optional[Dict[str, Dict[str, float]]], str]:
    path = Path(processed_root) / FACTOR_FILE
    if not path.is_file():
        return None, f"factor file absent: {path}"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, f"factor file unreadable: {type(exc).__name__}"
    raw = doc.get("stats") if isinstance(doc, dict) else None
    if not isinstance(raw, dict) or not raw:
        return None, "factor file has no 'stats' map"
    out: Dict[str, Dict[str, float]] = {}
    for s, v in raw.items():
        if s not in STATS or not isinstance(v, dict):
            continue
        try:
            k, dl = float(v["k"]), float(v["d_league"])
        except (KeyError, TypeError, ValueError):
            return None, f"entry for {s!r} lacks numeric k / d_league"
        if k < 0 or not (D_BOUNDS[0] <= dl <= D_BOUNDS[1]):
            return None, f"entry for {s!r} out of bounds (k={k}, d_league={dl})"
        out[s] = {"k": k, "d_league": dl}
    if not out:
        return None, "factor file names no known stat"
    return out, "ok"


@lru_cache(maxsize=8)
def _counts_cached(path_s: str, mtime: float, date_str: str) -> Tuple[Tuple[str, Tuple[Tuple[float, ...], ...]], ...]:
    acc: Dict[str, List[Tuple[float, ...]]] = defaultdict(list)
    with open(path_s, encoding="utf-8", errors="replace") as fh:
        for r in csv.DictReader(fh):
            d = str(r.get("date") or r.get("GAME_DATE") or "")[:10]
            if not d or d >= date_str:
                continue
            try:
                if float(r.get("MIN") or 0) <= 0:
                    continue
                acc[str(r.get("PLAYER_NAME") or "")].append(tuple(float(r.get(c) or 0) for c in STATS.values()))
            except ValueError:
                continue
    return tuple((name, tuple(v)) for name, v in acc.items())


def player_counts(processed_root: Path, date_str: str, name_key: Callable[[object], str]) -> Dict[str, Dict[str, List[float]]]:
    path = Path(processed_root) / HISTORY_FILE
    if not path.is_file():
        return {}
    try:
        rows = _counts_cached(str(path), path.stat().st_mtime, str(date_str)[:10])
    except Exception:  # noqa: BLE001
        return {}
    out: Dict[str, Dict[str, List[float]]] = {}
    for name, games in rows:
        key = str(name_key(name) or "").strip().upper()
        if key:
            out[key] = {s: [g[i] for g in games] for i, s in enumerate(STATS)}
    return out


def shrunk_d(counts: List[float], d_league: float, k: float) -> float:
    n = len(counts)
    if n < 2:
        return d_league
    mu = statistics.fmean(counts)
    d_own = (statistics.pvariance(counts) / mu) if mu > 0 else d_league
    return (n * d_own + k * d_league) / (n + k)


def apply_prop_shape(out: Any, *, league_code: str, processed_root: Path, build_ladder: Optional[Callable],
                     name_key: Callable[[object], str], env: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    summary: Dict[str, Any] = {"applied": False, "players": 0, "ladders": 0}
    try:
        if str(league_code or "").strip().lower() != "wnba":
            summary["reason"] = "not wnba"
            return summary
        state = flag_state(env)
        if state == "off":
            summary["reason"] = f"{FLAG} off"
            return summary
        if state == "unset":
            on, why = file_enabled(processed_root)
            if not on:
                summary["reason"] = f"{FLAG} unset and {why}"
                return summary
        summary["switch"] = "env" if state == "on" else "file"
        if not isinstance(out, dict) or not isinstance(out.get("players"), dict) or not callable(build_ladder):
            summary["reason"] = "no players block or no ladder builder"
            return summary
        factors, reason = load_factors(processed_root)
        if factors is None:
            summary["reason"] = reason
            print(f"[wnba_prop_shape] PROP_SHAPE skipped reason={reason}", flush=True)
            return summary
        counts = player_counts(processed_root, str(out.get("date") or ""), name_key)
        for side in ("home", "away"):
            for row in out["players"].get(side) or []:
                if not isinstance(row, dict) or not isinstance(row.get("prop_ladders"), dict):
                    continue
                ladders = row["prop_ladders"]
                dists = row.get("prop_distributions") if isinstance(row.get("prop_distributions"), dict) else None
                own = counts.get(str(name_key(row.get("player_name")) or "").strip().upper(), {})
                touched: Dict[str, float] = {}
                for s, f in factors.items():
                    try:
                        m = float(row.get(f"{s}_mean"))
                    except (TypeError, ValueError):
                        continue
                    if not math.isfinite(m) or m < 0 or s not in ladders:
                        continue
                    n = int((ladders[s] or {}).get("simCount") or 500)
                    d = shrunk_d(own.get(s, []), f["d_league"], f["k"])
                    new = build_ladder(materialise(nb_pmf(m, d), n))
                    if not new:
                        continue
                    ladders[s] = new
                    if dists is not None and s in dists:
                        dists[s] = {k2: new.get(k2) for k2 in ("simCount", "mean", "mode", "modeProb", "minTotal", "maxTotal")}
                        dists[s]["distribution"] = new.get("distribution") if isinstance(new.get("distribution"), dict) else {}
                        dists[s]["ladderShape"] = "nb_shape"
                    touched[s] = round(d, 4)
                    summary["ladders"] += 1
                if touched:
                    row["prop_shape"] = touched
                    summary["players"] += 1
        summary.update(applied=summary["ladders"] > 0, reason="ok")
        out["prop_shape"] = summary
        print(f"[wnba_prop_shape] PROP_SHAPE applied players={summary['players']} ladders={summary['ladders']}", flush=True)
    except Exception as exc:  # noqa: BLE001
        summary["reason"] = f"failed: {type(exc).__name__}: {exc}"
        print(f"[wnba_prop_shape] PROP_SHAPE_FAILED {type(exc).__name__}: {exc}", flush=True)
    return summary
