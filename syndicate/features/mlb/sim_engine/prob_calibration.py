from __future__ import annotations

import math
from typing import Any, Dict, Optional


def _logit(p: float, eps: float = 1e-12) -> float:
    pp = float(min(1.0 - eps, max(eps, float(p))))
    return float(math.log(pp) - math.log(1.0 - pp))


def _sigmoid(x: float) -> float:
    try:
        return float(1.0 / (1.0 + math.exp(-float(x))))
    except OverflowError:
        return 0.0 if float(x) < 0 else 1.0


def calibrate_prob_affine_logit(p: float, a: float = 1.0, b: float = 0.0, eps: float = 1e-12) -> float:
    """Calibrate probability via: p' = sigmoid(a * logit(p) + b)."""
    z = _logit(float(p), eps=eps)
    return float(min(1.0 - eps, max(eps, _sigmoid(float(a) * z + float(b)))))


def apply_prob_calibration(p: float, cfg: Optional[Dict[str, Any]]) -> float:
    """Apply generic probability calibration.

    Schema supports:
      - {"enabled": true, "mode": "affine_logit", "a": 1.0, "b": 0.0}
      - shrink-to-0.5: {"mode": "shrink_0p5", "alpha": 0.2}
      - tail shrink: {"mode": "tail_shrink", "p0": 0.15, "alpha_max": 0.5}
    """
    if not isinstance(cfg, dict) or not cfg:
        return float(p)
    if str(cfg.get("enabled", "true")).lower() in ("0", "false", "off", "no"):
        return float(p)

    mode = str(cfg.get("mode") or "affine_logit").strip().lower()

    if mode in ("shrink_0p5", "shrink_to_half", "shrink"):
        try:
            alpha = float(cfg.get("alpha", 0.0))
        except Exception:
            alpha = 0.0
        alpha = float(max(0.0, min(1.0, alpha)))
        return float((1.0 - alpha) * float(p) + alpha * 0.5)

    if mode in ("tail_shrink", "tail_shrink_0p5"):
        try:
            p0 = float(cfg.get("p0", 0.15))
        except Exception:
            p0 = 0.15
        try:
            alpha_max = float(cfg.get("alpha_max", 0.5))
        except Exception:
            alpha_max = 0.5
        p0 = float(max(1e-6, min(0.499, p0)))
        alpha_max = float(max(0.0, min(1.0, alpha_max)))

        pp = float(p)
        if p0 <= pp <= (1.0 - p0):
            return pp
        if pp < p0:
            t = float((p0 - pp) / p0)
        else:
            t = float((pp - (1.0 - p0)) / p0)
        alpha = float(max(0.0, min(1.0, alpha_max * t)))
        return float((1.0 - alpha) * pp + alpha * 0.5)

    if mode not in ("affine_logit", "logit_affine"):
        return float(p)

    try:
        a = float(cfg.get("a", 1.0))
        b = float(cfg.get("b", 0.0))
    except Exception:
        return float(p)

    a = float(max(0.05, min(5.0, a)))
    b = float(max(-5.0, min(5.0, b)))
    return calibrate_prob_affine_logit(float(p), a=a, b=b)


def resolve_prop_calibration_cfg(cfg: Optional[Dict[str, Any]], prop_key: str) -> Optional[Dict[str, Any]]:
    """Resolve per-prop calibration config.

    Supported schemas:
      1) Direct schema: {"enabled":true,"mode":"affine_logit","a":1.0,"b":0.0}
      2) Per-prop wrapper:
         {
           "enabled": true,
           "default": { ... },
           "props": {"hits_1plus": { ... }, ...}
         }
    """
    if not isinstance(cfg, dict) or not cfg:
        return None
    if str(cfg.get("enabled", "true")).lower() in ("0", "false", "off", "no"):
        return {"enabled": False}

    props = cfg.get("props")
    if isinstance(props, dict):
        sub = props.get(str(prop_key))
        if isinstance(sub, dict) and sub:
            return sub
        d = cfg.get("default")
        if isinstance(d, dict) and d:
            return d
    return cfg


def apply_prop_prob_calibration(p: float, cfg: Optional[Dict[str, Any]], prop_key: str) -> float:
    """Apply probability calibration for a specific prop key (supports per-prop wrapper configs)."""
    sub = resolve_prop_calibration_cfg(cfg, str(prop_key))
    return apply_prob_calibration(float(p), sub)


# Measured 2026-08-05 over 873 completed games / 66 dates (Render sims vs real
# StatsAPI finals): the sim states a mean per-game run-margin SD of 4.515 while
# the realised residual SD (actual margin - sim mean margin) is 4.733. The sim
# under-disperses full-game run margin by 4.8%, which pushes win probabilities
# too far from 50%.
#
# Scope: FULL-GAME ONLY. The first1/first3/first5 segments were never measured,
# and their dispersion has no reason to share this factor, so applying it there
# would be unvalidated extrapolation.
FULL_GAME_MARGIN_DISPERSION_FACTOR = 1.048


def widen_margin_distribution(dist: Dict[Any, float], factor: float) -> Dict[int, float]:
    """Scale a run-margin count distribution about its own mean by `factor`.

    This is a variance correction, not a calibration fit: the factor comes from
    measured realised-vs-stated dispersion, so it has a physical meaning and no
    free parameters tuned against outcomes.

    `factor > 1` widens (less confident), `1.0` is an exact no-op. Bin k moves
    to `mu + factor * (k - mu)`, which lands between integers, so mass is split
    across the two adjacent bins. Rounding to the nearest bin instead would
    quantise away most of a small adjustment -- the same defect that made
    `recalibrate_so_output` discard sub-half-strikeout corrections before it was
    fixed (see pitcher_so_model.py). Total mass is preserved exactly.
    """
    items = []
    for k, v in (dist or {}).items():
        try:
            kk, vv = float(k), float(v)
        except (TypeError, ValueError):
            continue
        if vv > 0:
            items.append((kk, vv))
    total = sum(v for _, v in items)
    if total <= 0 or not items:
        return {int(k): float(v) for k, v in (dist or {}).items()}
    try:
        f = float(factor)
    except (TypeError, ValueError):
        return {int(k): float(v) for k, v in items}
    if abs(f - 1.0) < 1e-12:
        return {int(k): float(v) for k, v in items}

    mean = sum(k * v for k, v in items) / total
    out: Dict[int, float] = {}
    for k, v in items:
        pos = mean + f * (k - mean)
        lo = math.floor(pos)
        frac = pos - lo
        out[lo] = out.get(lo, 0.0) + v * (1.0 - frac)
        if frac > 0.0:
            out[lo + 1] = out.get(lo + 1, 0.0) + v * frac
    return out


def win_probs_from_margin_distribution(dist: Dict[Any, float]) -> "tuple[float, float, float]":
    """(home_win_prob, away_win_prob, tie_prob) from a home-minus-away margin dist."""
    total = sum(float(v) for v in (dist or {}).values() if float(v) > 0)
    if total <= 0:
        return 0.0, 0.0, 0.0
    home = sum(float(v) for k, v in dist.items() if float(k) > 0 and float(v) > 0)
    away = sum(float(v) for k, v in dist.items() if float(k) < 0 and float(v) > 0)
    tie = sum(float(v) for k, v in dist.items() if float(k) == 0 and float(v) > 0)
    return home / total, away / total, tie / total
