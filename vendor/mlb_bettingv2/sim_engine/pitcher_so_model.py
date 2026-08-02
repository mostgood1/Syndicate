from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, Optional

_DEFAULT_MODEL_PATH = (Path(__file__).resolve().parents[1] / "data" / "models" / "pitcher_so_poisson_v1.json").resolve()
_MODEL_CACHE: Dict[str, Any] = {}


def load_so_model(path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Load the pitcher strikeout Poisson model artifact.

    The artifact is plain JSON (feature list, StandardScaler mean/scale,
    Poisson GLM coefficients + intercept) so applying it needs no sklearn
    runtime dependency -- just the dot-product-plus-exp in `predict_so_mean`.
    Cached by resolved path since it's tiny and read-only.
    """
    import json

    resolved = str(Path(path).resolve()) if path else str(_DEFAULT_MODEL_PATH)
    if resolved in _MODEL_CACHE:
        return _MODEL_CACHE[resolved]
    try:
        with open(resolved, "r", encoding="utf-8") as f:
            model = json.load(f)
    except Exception:
        model = None
    _MODEL_CACHE[resolved] = model
    return model


def predict_so_mean(features: Dict[str, float], model: Dict[str, Any]) -> Optional[float]:
    """Predict expected total strikeouts for a start from pregame features.

    `features` must supply every key in `model["features"]` (see
    data/models/pitcher_so_poisson_v1.json's `features` list -- the
    pitcher's own season k_rate/bb_rate/hr_rate/inplay_hit_rate/hbp_rate,
    batters_faced, stamina_pitches, venue_mult, is_home, and the opposing
    lineup's average k_rate/bb_rate/hr_rate/inplay_hit_rate). Returns None
    if any required feature is missing rather than guessing -- a silently
    wrong strikeout prediction is worse than falling back to the sim's own
    estimate.

    sklearn's PoissonRegressor predicts mu = exp(X_scaled @ coef + intercept)
    where X_scaled = (X - scaler_mean) / scaler_scale. Verified this
    pure-python reimplementation matches sklearn's own .predict() output to
    within float64 noise (<1e-15) before this model was trained -- see
    todo.md's pitcher/hitter statistical-model pilot entry.
    """
    try:
        feat_names = model["features"]
        means = model["scaler_mean"]
        scales = model["scaler_scale"]
        coefs = model["coef"]
        intercept = float(model["intercept"])
    except (KeyError, TypeError):
        return None

    z = intercept
    for name, mean, scale, coef in zip(feat_names, means, scales, coefs):
        if name not in features:
            return None
        v = features[name]
        if not isinstance(v, (int, float)):
            return None
        x_scaled = (float(v) - float(mean)) / float(scale) if scale else 0.0
        z += x_scaled * float(coef)

    try:
        return float(math.exp(z))
    except OverflowError:
        return None


def recalibrate_so_output(
    so_dist: Dict[Any, float],
    so_mean_raw: float,
    model_so_mean: float,
    weight: float,
) -> "tuple[Dict[int, float], float]":
    """Blend the sim's own so_dist/so_mean toward the model's prediction.

    `weight=0.0` (the default everywhere this is wired in) returns the
    input distribution completely unchanged -- a true no-op, not just an
    approximation of one.

    Architecture note: this recalibrates the FINAL reported so_mean/so_dist
    for props/betting purposes, not the sim's internal per-PA k_rate. The
    trained model predicts total game strikeouts using both rate signals
    AND workload signals (batters_faced, stamina_pitches) combined, while
    the sim's per-PA rate combination (_combined_k in pitch_model.py) only
    ever sees the rate piece -- workload/PA-count is a completely separate
    subsystem (the manager-hook pull-decision logic in simulate.py).
    Injecting the model into the per-PA rate would require backing out an
    implied rate by dividing the model's total prediction by the sim's own
    separately-estimated PA count, introducing a circular estimation error
    the sim doesn't have today. A post-hoc shift of the bottom-line
    so_mean/so_dist output treats the model as an independent, complete
    predictor of the same target the sim already reports, which is
    architecturally clean and keeps the sim's own pitch-by-pitch mechanics
    (which also drive the correlated full-game simulation used for
    moneyline/totals/spread markets) completely untouched.

    The shift is a bin-by-bin integer translation of the count distribution
    by round(weight * (model_so_mean - so_mean_raw)) -- preserves the sim's
    own distribution SHAPE (variance, skew from real Monte Carlo variance)
    while moving its center toward the model's prediction. Negative bins
    are dropped (a strikeout count can't go below 0).
    """
    w = max(0.0, min(1.0, float(weight)))
    if w <= 0.0 or model_so_mean is None:
        return dict(so_dist), float(so_mean_raw)

    shift = int(round(w * (float(model_so_mean) - float(so_mean_raw))))
    if shift == 0:
        return dict(so_dist), float(so_mean_raw)

    shifted: Dict[int, float] = {}
    for k, v in so_dist.items():
        try:
            kk = int(k) + shift
            vv = float(v)
        except (TypeError, ValueError):
            continue
        if kk < 0 or vv <= 0:
            continue
        shifted[kk] = shifted.get(kk, 0.0) + vv

    total = sum(shifted.values())
    new_mean = (sum(k * v for k, v in shifted.items()) / total) if total > 0 else float(so_mean_raw)
    return shifted, new_mean
