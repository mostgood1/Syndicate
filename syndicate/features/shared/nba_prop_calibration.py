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
    m1 = sim minutes * r                           (1. rate shrink)
    new <stat>_mean = b_s * m1 + (1 - b_s) * avg_own   (2. season-average blend; avg_own = season-to-date per game)
                                                   (pra_mean moves by the pts+reb+ast deltas)
    new <stat>_sd   = k_s * <stat>_sd              (3. width; pts reb ast threes stl blk tov pra)
Each step is optional per stat (absent from the file -> skipped). k is fit for the FINAL mean, so the three are
one estimator, not three independent knobs.
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
is truthy, or the factor file enables it (see SWITCH).

PRIOR-SEASON FALLBACK (2026-10-04, user decision "build + measure it first"): a player with < MIN_GAMES current-
season games uses his PREVIOUS regular season from `player_logs.csv` (same processed root), with the separate
`prior_season: {w, blend}` constants -- measured on a year-stale proxy to beat the served sim (fit script
`--prior-season-test`). No previous season either (rookies) -> mean untouched. Width is always scaled.

SWITCH (2026-10-04, user decision "file switch, no restart"): ON when the env var is truthy, OR when the env var
is unset AND the factor file carries `"enabled": true`. An explicit falsy env value (0/false/no/off) is a kill
switch that wins over the file. A missing or unreadable file is OFF.
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
PRIOR_FILE = "player_logs.csv"   # previous REGULAR season (stats.nba logs), the opening-night fallback
RATE_STATS = {"pts": "PTS", "reb": "REB", "ast": "AST", "threes": "FG3M", "stl": "STL", "blk": "BLK", "tov": "TOV"}
SD_STATS = ("pts", "reb", "ast", "threes", "stl", "blk", "tov", "pra")
LADDER_PARTS = {"pts": ("pts",), "reb": ("reb",), "ast": ("ast",), "threes": ("threes",), "stl": ("stl",),
                "blk": ("blk",), "tov": ("tov",), "pra": ("pts", "reb", "ast"), "pr": ("pts", "reb"),
                "pa": ("pts", "ast"), "ra": ("reb", "ast")}
W_BOUNDS = (0.0, 1.2)
B_BOUNDS = (0.0, 1.0)
K_BOUNDS = (0.5, 3.0)
MIN_GAMES = 3


def flag_state(env: Optional[Mapping[str, str]] = None) -> str:
    """'on' / 'off' (explicit kill switch) / 'unset'. The env var always wins over the factor file."""
    raw = str((env if env is not None else os.environ).get(FLAG) or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return "on"
    if raw in {"0", "false", "no", "off"}:
        return "off"
    return "unset"


def flag_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    return flag_state(env) == "on"


def season_start(date_str: str) -> str:
    """NBA season containing `date_str` starts Aug 1 of its first calendar year (preseason Oct, playoffs to June)."""
    y, m = int(date_str[:4]), int(date_str[5:7])
    return f"{y if m >= 8 else y - 1}-08-01"


def shrink_mean(sim_mean: float, sim_minutes: float, own_rate: float, w: float) -> float:
    """The fitted estimator, exactly as the fit script scores it."""
    return sim_minutes * (own_rate + w * (sim_mean / sim_minutes - own_rate))


def blend_mean(mean: float, own_avg: float, b: float) -> float:
    """Season-average blend: b is the weight on the (rate-shrunk) sim mean."""
    return b * mean + (1.0 - b) * own_avg


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
    out: Dict[str, Dict[str, float]] = {"w": {}, "b": {}, "k": {}}
    for block, allowed, bounds, dest in (("w", RATE_STATS, W_BOUNDS, "w"), ("blend", RATE_STATS, B_BOUNDS, "b"),
                                         ("sd_scale", SD_STATS, K_BOUNDS, "k")):
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
    out["pw"], out["pb"] = {}, {}
    prior = doc.get("prior_season")
    if prior is not None:
        if not isinstance(prior, dict):
            return None, "'prior_season' is not a map"
        for block, bounds, dest in (("w", W_BOUNDS, "pw"), ("blend", B_BOUNDS, "pb")):
            raw = prior.get(block) or {}
            if not isinstance(raw, dict):
                return None, f"prior_season.{block} is not a map"
            for key, value in raw.items():
                if key not in RATE_STATS:
                    continue
                try:
                    v = float(value)
                except (TypeError, ValueError):
                    return None, f"prior_season.{block}[{key!r}] is not a number"
                if not math.isfinite(v) or not (bounds[0] <= v <= bounds[1]):
                    return None, f"prior_season.{block}[{key!r}] = {v} outside {bounds}"
                out[dest][key] = v
    out["enabled"] = doc.get("enabled") is True  # type: ignore[assignment]
    if not out["w"] and not out["b"] and not out["k"]:
        return None, "factor file names no known stat"
    return out, "ok"


@lru_cache(maxsize=8)
def _own_rates_cached(path_s: str, mtime: float, date_lo: str, date_hi: str) -> Tuple[Tuple[str, Tuple[float, ...]], ...]:
    """Season totals per player over games with date_lo <= date < date_hi."""
    tot: Dict[str, List[float]] = defaultdict(lambda: [0.0] * (len(RATE_STATS) + 2))   # stats..., MIN, games
    with open(path_s, encoding="utf-8", errors="replace") as fh:
        for r in csv.DictReader(fh):
            d = str(r.get("date") or r.get("GAME_DATE") or "")[:10]
            if not d or d >= date_hi or d < date_lo:
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
    """Season-to-date (this season, strictly before the slate) per-minute rates and per-game averages."""
    d = str(date_str)[:10]
    return _rates_from(Path(processed_root) / HISTORY_FILE, season_start(d), d, name_key, f"season games before {d}")


def prior_rates(processed_root: Path, date_str: str, name_key: Callable[[object], str]) -> Tuple[Dict[str, Dict[str, float]], str]:
    """The PREVIOUS season's per-minute rates / per-game averages (opening-night fallback)."""
    cur = season_start(str(date_str)[:10])
    prev = f"{int(cur[:4]) - 1}{cur[4:]}"
    return _rates_from(Path(processed_root) / PRIOR_FILE, prev, cur, name_key, f"prior-season games {prev}..{cur}")


def _rates_from(path: Path, date_lo: str, date_hi: str, name_key: Callable[[object], str], what: str) -> Tuple[Dict[str, Dict[str, float]], str]:
    if not path.is_file():
        return {}, f"history absent: {path}"
    try:
        rows = _own_rates_cached(str(path), path.stat().st_mtime, date_lo, date_hi)
    except Exception as exc:  # noqa: BLE001
        return {}, f"history unreadable: {type(exc).__name__}"
    out: Dict[str, Dict[str, float]] = {}
    for name, v in rows:
        if v[-1] < MIN_GAMES or v[-2] <= 0:
            continue
        key = str(name_key(name) or "").strip().upper()
        if key:
            rec = {s: v[i] / v[-2] for i, s in enumerate(RATE_STATS)}                  # per minute
            rec.update({f"{s}_avg": v[i] / v[-1] for i, s in enumerate(RATE_STATS)})  # per game
            out[key] = rec
    return out, ("ok" if out else f"no player with >= {MIN_GAMES} {what}")


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
        state = flag_state(env)
        if state == "off":
            summary["reason"] = f"{FLAG} off"
            return summary
        if not isinstance(out, dict) or not isinstance(out.get("players"), dict):
            summary["reason"] = "no players block"
            return summary
        factors, reason = load_factors(processed_root)
        if state == "unset" and not (factors or {}).get("enabled"):
            # FILE SWITCH (user decision 2026-10-04, "file switch, no restart"): with the env var unset, the
            # calibration runs only when the factor file itself says "enabled": true. Unknown never means on.
            summary["reason"] = f"{FLAG} unset and factor file not enabled ({reason})"
            return summary
        if factors is None:
            summary["reason"] = reason
            print(f"[nba_prop_calibration] NBA_PROP_CALIBRATION skipped reason={reason}", flush=True)
            return summary
        summary["switch"] = "env" if state == "on" else "factor_file"
        w, b, k = factors["w"], factors["b"], factors["k"]
        pw, pb = factors.get("pw") or {}, factors.get("pb") or {}
        slate = str(out.get("date") or "")[:10]
        rates, rate_reason = own_rates(processed_root, slate, name_key) if (w or b) else ({}, "no w/blend")
        prior, prior_reason = prior_rates(processed_root, slate, name_key) if (pw or pb) else ({}, "no prior_season block")
        summary["rate_reason"], summary["prior_reason"], summary["players_prior_season"] = rate_reason, prior_reason, 0
        for side in ("home", "away"):
            for row in out["players"].get(side) or []:
                if not isinstance(row, dict):
                    continue
                orig_sd = {s: _f(row.get(f"{s}_sd")) for s in SD_STATS}
                delta: Dict[str, float] = {}
                pkey = str(name_key(row.get("player_name")) or "").strip().upper()
                # in-season data once a player has MIN_GAMES current games; before that, his PREVIOUS season with
                # its own (measured) constants -- the opening-night fallback; neither -> mean untouched
                own, ww, bb, source = rates.get(pkey), w, b, "season"
                if not own and prior.get(pkey):
                    own, ww, bb, source = prior.get(pkey), pw, pb, "prior_season"
                mins = _f(row.get("min_mean"))
                if own and mins and mins > 0:
                    for s in [x for x in RATE_STATS if x in ww or x in bb]:
                        m = _f(row.get(f"{s}_mean"))
                        if m is None:
                            continue
                        target = shrink_mean(m, mins, own[s], ww[s]) if s in ww else m      # 1. rate shrink
                        if s in bb:
                            target = blend_mean(target, own[f"{s}_avg"], bb[s])              # 2. own-average blend
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
                    row["nba_prop_calibration"] = {"mean_delta": {s: round(v, 4) for s, v in delta.items()}, "sd_scale": scaled,
                                                   "source": source if delta else None}
                    summary["players_prior_season"] += bool(delta) and source == "prior_season"
                    summary["players"] += 1
                    summary["players_rate_shrunk"] += bool(delta)
        summary.update(applied=summary["players"] > 0, w=w, b=b, k=k, reason="ok")
        out["nba_prop_calibration"] = summary
        print(f"[nba_prop_calibration] NBA_PROP_CALIBRATION applied players={summary['players']} "
              f"rate_shrunk={summary['players_rate_shrunk']} prior_season={summary['players_prior_season']} "
              f"ladders={summary['ladders']} rates={rate_reason} prior={prior_reason}", flush=True)
    except Exception as exc:  # noqa: BLE001 -- the sim's result must survive this
        summary["reason"] = f"failed: {type(exc).__name__}: {exc}"
        print(f"[nba_prop_calibration] NBA_PROP_CALIBRATION_FAILED {type(exc).__name__}: {exc}", flush=True)
    return summary
