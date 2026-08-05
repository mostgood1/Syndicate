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


_FRACTION_EPS = 1e-9


def _translate_bins(so_dist: Dict[Any, float], shift: int) -> Dict[int, float]:
    """Translate a strikeout count distribution by a whole number of Ks.

    Bins that would land below zero are dropped rather than clamped onto
    bin 0 -- a strikeout count can't be negative, and piling that mass onto
    zero would invent probability the sim never produced.
    """
    out: Dict[int, float] = {}
    for k, v in so_dist.items():
        try:
            kk = int(k) + int(shift)
            vv = float(v)
        except (TypeError, ValueError):
            continue
        if kk < 0 or vv <= 0:
            continue
        out[kk] = out.get(kk, 0.0) + vv
    return out


def recalibrate_so_output(
    so_dist: Dict[Any, float],
    so_mean_raw: float,
    model_so_mean: float,
    weight: float,
) -> "tuple[Dict[int, float], float]":
    """Blend the sim's own so_dist/so_mean toward the model's prediction.

    `weight=0.0` returns the input distribution completely unchanged -- a
    true no-op, not just an approximation of one. (The library-level
    default stays 0.0; production's CLI default is 1.0.)

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

    The shift moves the distribution by the FRACTIONAL amount
    `weight * (model_so_mean - so_mean_raw)`, as a mixture of the two
    adjacent whole-K translations weighted by the fractional part. This
    replaced an `int(round(...))` translation that silently discarded any
    model correction under half a strikeout.

    Why that mattered: measured over 312 real starts (15 dates, real Monte
    Carlo so_dist paired with the real OddsAPI line), one K of shift moves
    P(over) by 16.3pp on average, so the discarded fractional part cost
    `frac x 16.3pp` of mispricing -- 8.2pp at its worst, and 3-4pp averaged
    over any plausible model-vs-sim disagreement spread. Median two-sided
    hold on those same K lines is 5.98%, i.e. ~3pp of edge to break even:
    the rounding was throwing away more probability mass than the edge the
    model exists to find, and at a disagreement sigma of 0.5 K it discarded
    roughly two thirds of the model's corrections entirely.

    A mixture is the natural way to translate a lattice distribution by a
    non-integer amount, and it keeps the mean exact. It does add
    `frac * (1 - frac)` (at most 0.25 K^2) of variance versus a pure
    translation. That is deliberate and small: the sim's own so_dist runs
    UNDERdispersed (median variance/mean 0.754 across those 312 starts, so
    a negative binomial refit is the wrong tool here -- it cannot represent
    variance below the mean), and 0.25 K^2 against a typical ~4 K^2 is far
    cheaper than the 16pp-per-K centering error it removes.

    NOTE: this now emits FRACTIONAL bin counts. Consumers that read
    so_dist must not truncate counts to int -- see `_prob_over_line_from_dist`
    / `_mean_from_dist` in tools/daily_update_multi_profile.py, which were
    made float-safe alongside this change.
    """
    w = max(0.0, min(1.0, float(weight)))
    if w <= 0.0 or model_so_mean is None:
        return dict(so_dist), float(so_mean_raw)

    delta = w * (float(model_so_mean) - float(so_mean_raw))
    lower_shift = math.floor(delta)
    frac = float(delta - lower_shift)

    if frac <= _FRACTION_EPS:
        if lower_shift == 0:
            return dict(so_dist), float(so_mean_raw)
        shifted = _translate_bins(so_dist, lower_shift)
    elif frac >= 1.0 - _FRACTION_EPS:
        if lower_shift + 1 == 0:
            return dict(so_dist), float(so_mean_raw)
        shifted = _translate_bins(so_dist, lower_shift + 1)
    else:
        lower_bins = _translate_bins(so_dist, lower_shift)
        upper_bins = _translate_bins(so_dist, lower_shift + 1)
        shifted = {}
        for k, v in lower_bins.items():
            shifted[k] = shifted.get(k, 0.0) + v * (1.0 - frac)
        for k, v in upper_bins.items():
            shifted[k] = shifted.get(k, 0.0) + v * frac

    total = sum(shifted.values())
    new_mean = (sum(k * v for k, v in shifted.items()) / total) if total > 0 else float(so_mean_raw)
    return shifted, new_mean
