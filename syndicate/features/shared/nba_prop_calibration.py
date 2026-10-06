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


# Bumped whenever the TRANSFORM changes (not just the constants), so sims written by the old code read as stale and are
# re-simulated: "2" = mean-preserving ladder scale/shift (2026-10-05); "1" (implicit, unversioned) = round_half_up.
TRANSFORM_VERSION = "2"


def factor_stamp(processed_root: Path) -> Optional[str]:
    """Hash of the factor file's content + TRANSFORM_VERSION (16 hex), or None when the file is absent/unreadable."""
    try:
        import hashlib
        raw = (Path(processed_root) / FACTOR_FILE).read_bytes()
        return hashlib.sha256(raw + b"|transform=" + TRANSFORM_VERSION.encode()).hexdigest()[:16]
    except Exception:  # noqa: BLE001
        return None


def active_stamp(league_code: str, processed_root: Path, env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """The stamp a sim written NOW would carry: the factor file's hash when the calibration would run, else None."""
    if str(league_code or "").strip().lower() != "nba":
        return None
    state = flag_state(env)
    if state == "off":
        return None
    factors, _ = load_factors(processed_root)
    if factors is None or (state == "unset" and not factors.get("enabled")):
        return None
    return factor_stamp(processed_root)


def sim_is_stale(path: Path, *, league_code: str, processed_root: Path, env: Optional[Mapping[str, str]] = None) -> bool:
    """STALE-SIM CHECK (2026-10-04, user decision "borrow the file and add the stale-sim fix"). The smart-sim run
    reuses any existing sim forever, so a sim written under a DIFFERENT calibration than the one now active (pre-enable,
    old constants, or calibrated while it is now off) would be served indefinitely. True -> the caller re-simulates.
    NBA only; never raises (an unreadable sim is not judged stale here -- the caller's own adequacy check owns that)."""
    if str(league_code or "").strip().lower() != "nba":
        return False
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return False
    block = payload.get("nba_prop_calibration") if isinstance(payload, dict) else None
    have = block.get("factor_sha") if isinstance(block, dict) else None
    want = active_stamp(league_code, processed_root, env)
    stale = have != want
    if stale:
        print(f"[nba_prop_calibration] NBA_SIM_STALE path={Path(path).name} have={have} want={want} -> re-simulate", flush=True)
    return stale


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
    """Season-to-date per-minute rates and per-game averages: THIS season's REGULAR-season games strictly before the
    slate, from player_logs.csv (stats.nba Regular Season only, kept current by nba_history_refresh).

    PHASE GUARD (lane nba-season-phase, 2026-10-06). This used to read boxscores_history.csv from Aug 1, which is
    ESPN all-phase: preseason games would have become "season-to-date" after 3 games and stayed mixed into the early
    regular season. Nothing refreshes that file either, so on the fleet it held only 2026 playoff games. Now:
      * preseason or UNKNOWN slate -> no own rates (the prior-season fallback applies; never a guess);
      * regular / play-in / postseason slate -> regular-season rows from this season's ESPN regular-season start.
        Postseason own rows are a design step-4 item (no current playoff history is refreshed)."""
    d = str(date_str)[:10]
    from syndicate.features.shared.nba_season_phase import phase_for_date, phase_start

    phase = phase_for_date(d, processed_root=processed_root)
    if phase not in {"regular", "play_in", "postseason"}:
        return {}, f"own rates not used: slate phase {phase or 'unknown'} (preseason never feeds season-to-date)"
    lo = phase_start(d, "regular", processed_root=processed_root)
    if not lo:
        return {}, "own rates not used: this season's regular-season start is unknown"
    return _rates_from(Path(processed_root) / PRIOR_FILE, lo, d, name_key, f"regular-season games {lo}..{d}")


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


def _rebalance(out: List[int], target: int) -> List[int]:
    """Move the integer total of `out` to `target` one unit at a time, on draws EVENLY SPACED through the value-sorted
    order (so the shape moves as a whole), removing only from positive draws. Deterministic."""
    out = list(out)
    n = len(out)
    for _ in range(64):                      # each pass moves up to n units; 64 passes covers any realistic gap
        gap = target - sum(out)
        if gap == 0 or n == 0:
            break
        elig = [i for i in sorted(range(n), key=lambda i: (out[i], i)) if gap > 0 or out[i] > 0]
        if not elig:
            break
        m = min(abs(gap), len(elig))
        step = len(elig) / m
        for j in range(m):
            out[elig[min(len(elig) - 1, int(j * step + step / 2))]] += 1 if gap > 0 else -1
    return out


def scale_values(vals: List[int], k: float) -> List[int]:
    """Dilate integer draws around their mean by k KEEPING THE MEAN: y = mu + k(v - mu), rounded, floored at 0, then
    the integer total is rebalanced to round(sum(vals)) -- without that, the floor at 0 raises the mean exactly where
    low-count stats (threes/stl/blk) live."""
    n = len(vals)
    if n == 0 or k == 1.0:
        return list(vals)
    mu = sum(vals) / n
    out = [max(0, int(math.floor(mu + k * (v - mu) + 0.5))) for v in vals]
    return _rebalance(out, int(sum(vals)))


def shift_values(vals: List[int], delta: float) -> List[int]:
    """Shift integer draws by delta KEEPING THE MEAN: every draw moves by trunc(delta) (floored at 0), then the total is
    rebalanced to round(sum(vals) + n*delta) (floored at 0) on evenly spaced draws. round_half_up(v + delta) -- this
    module's rule until 2026-10-05 -- is a NO-OP for |delta| < 0.5 (measured live: threes ladders lagged the calibrated
    mean on 125/169 rows); the WNBA shrink's fix (bfa92d5f) is the same idea for positive shifts."""
    n = len(vals)
    if n == 0 or delta == 0.0:
        return list(vals)
    base = int(delta)                         # toward 0, so the floor at 0 bites as little as possible
    out = [max(0, v + base) for v in vals]
    target = max(0, int(round(sum(vals) + n * delta)))
    return _rebalance(out, target)


def transform_values(values: List[int], shift: float, k: float) -> List[int]:
    """The served ladder transform: widen by k around the mean, then shift by the calibrated mean delta. BOTH steps keep
    the mean exactly (up to integer rounding and the floor at 0), so the ladder Layer 2 reads carries the calibrated
    mean (`nba_projections.py` serves the ladder's hitProb and mean, not `<stat>_mean`/`<stat>_sd`)."""
    if not values:
        return []
    return shift_values(scale_values(list(values), k), shift)


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
        # stamped whenever the calibration RUNS (even if no player qualifies) so sim_is_stale cannot loop
        summary["factor_sha"] = factor_stamp(processed_root)
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
        summary.setdefault("factor_sha", factor_stamp(processed_root))
        out["nba_prop_calibration"] = summary
        print(f"[nba_prop_calibration] NBA_PROP_CALIBRATION applied players={summary['players']} "
              f"rate_shrunk={summary['players_rate_shrunk']} prior_season={summary['players_prior_season']} "
              f"ladders={summary['ladders']} rates={rate_reason} prior={prior_reason}", flush=True)
    except Exception as exc:  # noqa: BLE001 -- the sim's result must survive this
        summary["reason"] = f"failed: {type(exc).__name__}: {exc}"
        print(f"[nba_prop_calibration] NBA_PROP_CALIBRATION_FAILED {type(exc).__name__}: {exc}", flush=True)
    return summary


# ---------------------------------------------------------------------------------------------------------------------
# SERVED PROBABILITY: blend toward the de-vigged book (user decision 2026-10-05, "serve the book blend on the board").
#
# Measured (scripts/fit_nba_prop_calibration.py --vs-book / --book-blend, OddsAPI backfill): on 249,884 held-out book
# lines / 400 games the calibrated probability LOSES to the de-vigged book in every market, and the out-of-sample blend
# weight (~0.05) only TIES it -- the model carries no measurable information beyond the line. So the probability the
# board serves for an NBA prop line is p = sigmoid(logit(p_book) + w_stat * (logit(p_model) - logit(p_book))), with w
# from `nba_prop_book_blend.json` (refit on all 336,418 lines; mostly 0). Every line stays on the board with its model
# mean; only the PROBABILITY (and so the edge) moves to what the evidence supports. NBA only.
#
# Kept in its OWN file, not the calibration factor file: the blend never touches the sims, and changing the factor
# file's hash would re-simulate every NBA game for nothing.
#
# SWITCH: on when `nba_prop_book_blend.json` carries "enabled": true; env SYNDICATE_NBA_PROP_BOOK_BLEND=0/off is a kill
# switch; a missing/invalid file, a stat with no weight, or a row with no two-sided book price -> the raw model
# probability, with the reason stamped (never a silent fallback).
# ---------------------------------------------------------------------------------------------------------------------
BOOK_BLEND_FILE = "nba_prop_book_blend.json"
BOOK_BLEND_FLAG = "SYNDICATE_NBA_PROP_BOOK_BLEND"


def _logit(p: float) -> float:
    p = min(1 - 1e-4, max(1e-4, float(p)))
    return math.log(p / (1 - p))


def blend_with_book(p_model: float, p_book: float, w: float) -> float:
    """sigmoid(logit(book) + w (logit(model) - logit(book))): w = 0 is the book, w = 1 the model."""
    z = _logit(p_book) + w * (_logit(p_model) - _logit(p_book))
    return 1 / (1 + math.exp(-z))


@lru_cache(maxsize=4)
def _book_blend_cached(path_s: str, mtime_ns: int, size: int) -> Tuple[Optional[Dict[str, float]], str]:
    try:
        doc = json.loads(Path(path_s).read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, f"book-blend file unreadable: {type(exc).__name__}"
    if not isinstance(doc, dict) or doc.get("enabled") is not True:
        return None, "book-blend file not enabled"
    if str(doc.get("space") or "logit") != "logit":
        return None, f"unsupported blend space {doc.get('space')!r}"
    raw = doc.get("w")
    if not isinstance(raw, dict) or not raw:
        return None, "book-blend file has no 'w' map"
    out: Dict[str, float] = {}
    for key, value in raw.items():
        try:
            v = float(value)
        except (TypeError, ValueError):
            return None, f"w[{key!r}] is not a number"
        if not math.isfinite(v) or not (0.0 <= v <= 1.0):
            return None, f"w[{key!r}] = {v} outside [0, 1]"
        out[str(key).strip().lower()] = v
    phases = doc.get("phase")
    if isinstance(phases, dict):
        for ph, block in phases.items():
            if not isinstance(block, dict):
                return None, f"phase[{ph!r}] is not a map"
            for key, value in block.items():
                try:
                    v = float(value)
                except (TypeError, ValueError):
                    return None, f"phase[{ph!r}][{key!r}] is not a number"
                if not math.isfinite(v) or not (0.0 <= v <= 1.0):
                    return None, f"phase[{ph!r}][{key!r}] = {v} outside [0, 1]"
                out[f"{str(ph).strip().lower()}|{str(key).strip().lower()}"] = v
    return out, "ok"


def book_blend_weights(processed_root: Optional[Path] = None, env: Optional[Mapping[str, str]] = None, *,
                       filename: str = BOOK_BLEND_FILE, flag: str = BOOK_BLEND_FLAG) -> Tuple[Optional[Dict[str, float]], str]:
    """The active per-key weights, or (None, reason). Resolves the NBA processed root when none is given."""
    raw = str((env if env is not None else os.environ).get(flag) or "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return None, f"{flag} off"
    try:
        if processed_root is None:
            from syndicate.features.nba.sources import artifact_processed_root
            processed_root = artifact_processed_root()
        path = Path(processed_root) / filename
        if not path.is_file():
            return None, "book-blend file absent"
        st = path.stat()
        return _book_blend_cached(str(path), st.st_mtime_ns, st.st_size)
    except Exception as exc:  # noqa: BLE001
        return None, f"book-blend unavailable: {type(exc).__name__}"


def served_prop_probability(p_model: Optional[float], p_book: Optional[float], stat: str, *,
                            processed_root: Optional[Path] = None, env: Optional[Mapping[str, str]] = None
                            ) -> Tuple[Optional[float], Dict[str, Any]]:
    """The probability to SERVE for one NBA prop line (P(over)), plus a stamp saying how it was made. Never raises."""
    meta: Dict[str, Any] = {"p_model_raw": None if p_model is None else round(float(p_model), 4)}
    try:
        if p_model is None:
            return None, meta
        weights, reason = book_blend_weights(processed_root, env)
        if weights is None:
            meta["book_blend"] = reason
            return p_model, meta
        key = str(stat or "").strip().lower()
        if key not in weights:
            meta["book_blend"] = f"no weight for {key!r}"
            return p_model, meta
        if p_book is None or not (0.0 < float(p_book) < 1.0):
            meta["book_blend"] = "no two-sided book price for this line"
            return p_model, meta
        w = weights[key]
        p = blend_with_book(float(p_model), float(p_book), w)
        meta.update(book_blend="applied", book_blend_w=w, p_book=round(float(p_book), 4))
        return p, meta
    except Exception as exc:  # noqa: BLE001 -- serving must survive this
        meta["book_blend"] = f"failed: {type(exc).__name__}"
        return p_model, meta


# ---------------------------------------------------------------------------------------------------------------------
# NBA GAME LINES: the same blend, its own file (user decision 2026-10-05, "Blend to market, build it").
#
# Layer 2 priced NBA game lines from the raw smart-sim score histogram, which is not market-anchored. Measured on the
# 2025-26 regular season the raw sim's OOS weight vs the line is 0.00 (margin) / 0.05 (total); in preseason the sim is
# 4-6 pts more lopsided than the market and its totals run high (findings "NBA season phase"). Keys are
# "<market>:<segment>" ("spreads:full"), then "<market>", then "default"; a missing key -> the model WITH a reason.
# ---------------------------------------------------------------------------------------------------------------------
GAME_BLEND_FILE = "nba_game_book_blend.json"
GAME_BLEND_FLAG = "SYNDICATE_NBA_GAME_BOOK_BLEND"


def served_game_probability(p_model: Optional[float], p_fair: Optional[float], market: str, segment: str = "full", *,
                            phase: Optional[str] = None, processed_root: Optional[Path] = None,
                            env: Optional[Mapping[str, str]] = None) -> Tuple[Optional[float], Dict[str, Any]]:
    """The probability to SERVE for one NBA game line (the same side `_attach_sim_probability_edge` prices), plus a
    stamp. `phase` is the game's season phase ("preseason" / "regular" / "postseason", ESPN season.type 1/2/3); a
    phase block in the file overrides the base weights for that phase (user 2026-10-05: a harder preseason shrink).
    UNKNOWN phase does not default permissive: it takes the SMALLEST weight any phase defines for the key. Never
    raises."""
    meta: Dict[str, Any] = {"p_model_raw": None if p_model is None else round(float(p_model), 4),
                            "season_phase": phase or "unknown"}
    try:
        if p_model is None:
            return None, meta
        weights, reason = book_blend_weights(processed_root, env, filename=GAME_BLEND_FILE, flag=GAME_BLEND_FLAG)
        if weights is None:
            meta["book_blend"] = reason
            return p_model, meta
        m, seg = str(market or "").strip().lower(), str(segment or "full").strip().lower()
        fam = m[:-4] if m.endswith("_alt") else m
        keys = (f"{m}:{seg}", f"{fam}:{seg}", m, fam, "default")
        base = next((weights[k] for k in keys if k in weights), None)
        phases = sorted({k.split("|", 1)[0] for k in weights if "|" in k})
        per_phase = {ph: next((weights[f"{ph}|{k}"] for k in keys if f"{ph}|{k}" in weights), base) for ph in phases}
        ph = str(phase or "").strip().lower()
        if ph and ph in per_phase:
            w = per_phase[ph]
        elif ph:
            w = base
        else:
            cands = [x for x in [base, *per_phase.values()] if x is not None]
            w = min(cands) if cands else None
        if w is None:
            meta["book_blend"] = f"no weight for {m}:{seg}"
            return p_model, meta
        if p_fair is None or not (0.0 < float(p_fair) < 1.0):
            meta["book_blend"] = "no two-sided book price for this line"
            return p_model, meta
        p = blend_with_book(float(p_model), float(p_fair), w)
        meta.update(book_blend="applied", book_blend_w=w, p_book=round(float(p_fair), 4))
        return p, meta
    except Exception as exc:  # noqa: BLE001 -- serving must survive this
        meta["book_blend"] = f"failed: {type(exc).__name__}"
        return p_model, meta

