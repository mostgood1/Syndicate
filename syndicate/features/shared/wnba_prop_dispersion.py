"""Widen WNBA SmartSim prop ladders to their measured width (lane `wnba-prop-dispersion`).

THE DEFECT. Measured 2026-10-02/03 on an as-of re-run of this engine over the 2026 WNBA season (4,618 player-games,
lane `wnba-lines-props-backtest`): the sim's per-player prop distributions are too NARROW -- realised residual sd /
sim sd = 1.39 points, 1.41 rebounds, 1.45 assists, 1.23 threes, 1.58 PRA; the sim's own 80% intervals cover
58-84%. The board reads P(over) straight off these ladders (`wnba_projections._hit_prob_over`), so every prop
probability was overconfident.

THE ESTIMATOR. Per market, every simulated value v becomes max(0, round_half_up(mu + k * (v - mu))), mu = the
ladder's own mean, and the ladder is rebuilt from the widened values with the vendor's own builder. k comes from
`wnba_prop_dispersion.json` (written by `scripts/fit_wnba_prop_dispersion.py --write-artifact`): fit on the
whole-ladder ranked probability score over May-July, tested on Aug-Sep and the playoffs. It is an ESTIMATOR, not a
mechanism: it changes how wide the published distribution is, not what the sim does.

WHAT IT DOES NOT DO, stated so nobody reads it as more. It does not move the mean (only rounding and the clip at 0
shift it, measured +0.01..+0.13). It does not create information: at the book's own line the sim's P(over) has NO
discrimination for points/rebounds/PRA (observed over-rate flat 0.44-0.57 across every predicted decile), and
widening only removes overconfidence. The remaining gap to the book is the mean (minutes) -- fixes 2 and 3.

GATING. WNBA only. OFF unless `SYNDICATE_WNBA_PROP_DISPERSION` is truthy (default OFF until a user decision). A
missing or unreadable factor file leaves the ladders untouched and says why (`PROP_DISPERSION ... reason=...`) --
never a silent neutral default (model_engine_standard §4.2). Never raises: the sim's result must survive this.

GATING (FILE SWITCH, 2026-10-05, user "enable the prop shape and dispersion fixes"): env truthy -> on; env
0/false/no/off -> off, a kill switch over everything; env UNSET -> on only if the factor file carries
`"enabled": true`. The per-run SmartSim subprocess reads the file, so enabling needs no role restart.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

FLAG = "SYNDICATE_WNBA_PROP_DISPERSION"
FILE_NAME = "wnba_prop_dispersion.json"
LADDER_KEYS = ("pts", "reb", "ast", "threes", "pra", "pr", "pa", "ra")
K_BOUNDS = (0.5, 3.0)   # a factor outside this is a broken fit, refused rather than applied


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
    path = Path(processed_root) / FILE_NAME
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


def load_factors(processed_root: Path) -> Tuple[Optional[Dict[str, float]], str]:
    """(factors, reason). factors is None with a NAMED reason when the file cannot be used."""
    path = Path(processed_root) / FILE_NAME
    if not path.is_file():
        return None, f"factor file absent: {path}"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, f"factor file unreadable: {type(exc).__name__}"
    raw = doc.get("k") if isinstance(doc, dict) else None
    if not isinstance(raw, dict) or not raw:
        return None, "factor file has no 'k' map"
    out: Dict[str, float] = {}
    for key, value in raw.items():
        try:
            k = float(value)
        except (TypeError, ValueError):
            return None, f"factor for {key!r} is not a number"
        if key not in LADDER_KEYS:
            continue
        if not (K_BOUNDS[0] <= k <= K_BOUNDS[1]) or not math.isfinite(k):
            return None, f"factor for {key!r} = {k} outside {K_BOUNDS}"
        out[key] = k
    if not out:
        return None, "factor file names no known ladder key"
    return out, "ok"


def _round_half_up(x: float) -> int:
    return int(math.floor(x + 0.5))


def dilate_values(values: List[int], k: float) -> List[int]:
    """The fitted estimator, exactly as `fit_wnba_prop_dispersion.dilate` scores it."""
    if not values:
        return []
    mu = sum(values) / len(values)
    return [max(0, _round_half_up(mu + k * (v - mu))) for v in values]


def _values_from_ladder(payload: Mapping[str, Any]) -> List[int]:
    dist = payload.get("distribution")
    if not isinstance(dist, Mapping):
        return []
    values: List[int] = []
    for total, count in dist.items():
        try:
            values.extend([int(float(total))] * int(count))
        except (TypeError, ValueError):
            return []
    return values


def apply_prop_dispersion(out: Any, *, league_code: str, processed_root: Path, build_ladder: Optional[Callable],
                          env: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """Widen every player's prop ladders in a smart-sim result, in place. Returns (and stamps on the result as
    `prop_dispersion`) what it did, so a reader can tell an applied ladder from an untouched one."""
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
            print(f"[wnba_prop_dispersion] PROP_DISPERSION skipped reason={reason}", flush=True)
            return summary
        for side in ("home", "away"):
            for row in out["players"].get(side) or []:
                if not isinstance(row, dict) or not isinstance(row.get("prop_ladders"), dict):
                    continue
                ladders, dists = row["prop_ladders"], row.get("prop_distributions")
                touched = {}
                for key, k in factors.items():
                    payload = ladders.get(key)
                    if not isinstance(payload, Mapping):
                        continue
                    values = _values_from_ladder(payload)
                    if not values:
                        continue
                    new = build_ladder(dilate_values(values, k))
                    if not new:
                        continue
                    ladders[key] = new
                    if isinstance(dists, dict) and key in dists:
                        dists[key] = {f: new.get(f) for f in ("simCount", "mean", "mode", "modeProb", "minTotal",
                                                               "maxTotal")}
                        dists[key]["distribution"] = new.get("distribution") if isinstance(new.get("distribution"), dict) else {}
                        dists[key]["ladderShape"] = str(new.get("ladderShape") or "exact")
                    touched[key] = k
                    summary["ladders"] += 1
                if touched:
                    row["prop_dispersion"] = touched
                    summary["players"] += 1
        summary["applied"] = summary["ladders"] > 0
        summary["k"] = factors
        summary["reason"] = "ok" if summary["applied"] else "no ladder carried a distribution"
        out["prop_dispersion"] = summary
        print(f"[wnba_prop_dispersion] PROP_DISPERSION applied players={summary['players']} "
              f"ladders={summary['ladders']}", flush=True)
    except Exception as exc:  # noqa: BLE001 -- the sim's result must survive a widening failure
        summary["reason"] = f"failed: {type(exc).__name__}: {exc}"
        print(f"[wnba_prop_dispersion] PROP_DISPERSION_FAILED {type(exc).__name__}: {exc}", flush=True)
    return summary
