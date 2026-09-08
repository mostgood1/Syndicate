"""ONE calibration hook for the board's pricing seam (`lane pricing-plane-v1`, P5).

Every sport arrives at `layer2_board._model_edge_for` with a probability-space
edge, `edge_vs_market_pct = model_prob - fair`, and the sizer later recovers
the probability as `fair + model_edge_pct / 100` (`portfolio_commit.py:311`).
So a calibration that is going to change what the board ranks and the sizer
stakes has to act on the PROBABILITY and re-difference it -- not rescale the
edge -- and the row has to keep the raw number beside the calibrated one, or a
curve that hides what it changed is indistinguishable from a model that was
always right (`nfl_game_projections.py` states the same rule for its totals).

WHAT THIS IS NOT. The repo already has five ways to calibrate a probability:
basketball props apply a monotone curve at pricing
(`basketball_props_edges._apply_prob_curve`), MLB hitter props are calibrated
at SIM time (`p_*_cal`), NFL blends distributions per market, football and
soccer engines carry a versioned engine profile, and the rest have nothing.
This module is the SIXTH consumer but not a sixth STORAGE approach: the profile
is a versioned artifact written and read through
`calibration_profile_store`, exactly as football's engine profile is.

Curve families, deliberately few:

  identity        p_cal = p                                (no cell => this)
  affine_logit    logit(p_cal) = a + b * logit(p)          two numbers
  isotonic        monotone breakpoints, linear interpolation, clamped to the
                  fitted range -- the same shape `_apply_prob_curve` reads,
                  so a basketball curve could be re-expressed here verbatim

`calibrate` NEVER raises and never returns a number outside [0, 1]. A cell it
cannot parse is identity with the reason on the meta, because a curve that
fails closed by throwing takes the whole board build with it, and one that
fails closed by silently returning `p` is exactly the unfed-input defect the
model-engine standard exists to stop -- so the meta says which happened.

THE FITTERS LIVE HERE TOO (`fit_affine_logit`, `fit_isotonic`, `brier`,
`log_loss`) so that the harness that writes a profile and the seam that reads
it agree on the curve's definition by construction. Pure Python on purpose:
this is imported on the web service's board path, which must not pay for
numpy to apply two multiplications.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from syndicate.features.shared.calibration_profile_store import (
    load_versioned_profile,
    save_versioned_profile,
)

PROFILE_KEY = "probability_calibration"
PROFILE_FILENAME = f"{PROFILE_KEY}.json"

METHOD_IDENTITY = "identity"
METHOD_AFFINE_LOGIT = "affine_logit"
METHOD_ISOTONIC = "isotonic"
METHODS = (METHOD_IDENTITY, METHOD_AFFINE_LOGIT, METHOD_ISOTONIC)

#: Wildcard segment inside a cell key: `"<market>|*"` answers for every segment
#: that has no cell of its own.
ANY_SEGMENT = "*"

#: Logit clamp. `logit(0)` is -inf and a curve fitted on real rows never saw
#: an exact certainty (`probability_refusal` blanks them upstream), so the
#: input is pinned to this band before the transform.
_LOGIT_EPS = 1e-6


# --------------------------------------------------------------------------
# Profile
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ProbabilityCalibrationProfile:
    """Per-sport bundle of per-(market, segment) cells.

    `cells` maps `"<market>|<segment>"` to a cell dict carrying at least
    `method`; `affine_logit` cells carry `a`, `b`; `isotonic` cells carry `x`,
    `y`. Every cell written by the harness also carries `version`,
    `fitted_on`, `n`, `n_test`, `held_out_brier_raw`, `held_out_brier_cal`,
    `held_out_logloss_raw`, `held_out_logloss_cal`, `scorer_version`,
    `artifact_root` -- provenance the reader reports verbatim and never
    invents.
    """

    version: str = METHOD_IDENTITY
    sport: str | None = None
    cells: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "sport": self.sport,
            "cells": {str(k): dict(v) for k, v in dict(self.cells).items()},
        }


IDENTITY_PROFILE = ProbabilityCalibrationProfile()


def cell_key(market: Any, segment: Any = None) -> str:
    """`"<market>|<segment>"`, normalised the way every reader and writer uses it."""
    market_key = str(market or "").strip().lower()
    segment_key = str(segment or "").strip().lower() or ANY_SEGMENT
    return f"{market_key}|{segment_key}"


def _sport_slug(sport: Any) -> str:
    return str(sport or "").strip().lower()


def profile_path(sport: Any, *, data_root: Path | str | None = None) -> Path:
    """`<SYNDICATE_DATA_ROOT>/<sport>_source/calibration/probability_calibration.json`.

    Sited under the existing `*_source/calibration/*.json` allowlist glob and
    declared by name in `artifact_publisher.HOT_ARTIFACT_PATTERNS`, so the
    file can be published to the worker AND audited through
    `/api/ops/artifacts/*`. A path outside the allowlist is a local guess.
    """
    if data_root is None:
        from syndicate.features.shared.refresh_state_store import data_root as _data_root

        root = _data_root()
    else:
        root = Path(data_root)
    return root / f"{_sport_slug(sport)}_source" / "calibration" / PROFILE_FILENAME


def load_profile(
    sport: Any, *, data_root: Path | str | None = None
) -> tuple[ProbabilityCalibrationProfile, dict[str, Any]]:
    """The sport's profile, or `IDENTITY_PROFILE` when absent/unreadable.

    Goes through `calibration_profile_store.load_versioned_profile`, so a
    corrupt artifact degrades to identity exactly the way a missing one does,
    and the metadata says which (`source: default|artifact`).
    """
    path = profile_path(sport, data_root=data_root)
    profile, metadata = load_versioned_profile(default_profile=IDENTITY_PROFILE, artifact_path=path)
    if not isinstance(profile.cells, Mapping):
        return IDENTITY_PROFILE, metadata
    return profile, metadata


def save_profile(
    profile: ProbabilityCalibrationProfile,
    *,
    data_root: Path | str | None = None,
    fit_from: dict[str, Any] | None = None,
) -> Path:
    """Write the profile as a versioned artifact (same envelope football uses)."""
    path = profile_path(profile.sport, data_root=data_root)
    return save_versioned_profile(profile, artifact_path=path, version=profile.version, fit_from=fit_from)


# A tiny read-through cache keyed by path, invalidated on mtime/size so a
# rewritten artifact is picked up without a process restart. The board build
# calls `calibrate` once per side per row -- thousands of times -- and a JSON
# parse per call would be the wrong trade.
_PROFILE_CACHE: dict[str, tuple[tuple[int, int] | None, ProbabilityCalibrationProfile, dict[str, Any]]] = {}


def _stat_signature(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def cached_profile(
    sport: Any, *, data_root: Path | str | None = None
) -> tuple[ProbabilityCalibrationProfile, dict[str, Any]]:
    path = profile_path(sport, data_root=data_root)
    key = str(path)
    signature = _stat_signature(path)
    hit = _PROFILE_CACHE.get(key)
    if hit is not None and hit[0] == signature:
        return hit[1], hit[2]
    profile, metadata = load_profile(sport, data_root=data_root)
    _PROFILE_CACHE[key] = (signature, profile, metadata)
    return profile, metadata


def clear_profile_cache() -> None:
    _PROFILE_CACHE.clear()


# --------------------------------------------------------------------------
# Env switch
# --------------------------------------------------------------------------

ENV_FLAG = "SYNDICATE_PRICING_CALIBRATION"


def pricing_calibration_enabled() -> bool:
    """`SYNDICATE_PRICING_CALIBRATION` absent/`off` => bypass entirely.

    ABSENT IS OFF. The seam must be bit-identical to today's board until
    someone turns it on, and a flag whose absent value were "on" would apply an
    identity transform AND stamp four new fields on every served row on the
    deploy that shipped it.
    """
    raw = str(os.environ.get(ENV_FLAG) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


# --------------------------------------------------------------------------
# The transform
# --------------------------------------------------------------------------


def _clamp01(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


def _logit(p: float) -> float:
    p = min(max(p, _LOGIT_EPS), 1.0 - _LOGIT_EPS)
    return math.log(p / (1.0 - p))


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    ez = math.exp(z)
    return ez / (1.0 + ez)


def _as_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def apply_affine_logit(p: float, a: float, b: float) -> float:
    return _clamp01(_sigmoid(a + b * _logit(p)))


def apply_isotonic(p: float, xs: Sequence[float], ys: Sequence[float]) -> float:
    """Piecewise-linear through monotone breakpoints, clamped to the fitted range.

    Below `xs[0]` returns `ys[0]`, above `xs[-1]` returns `ys[-1]`: the curve
    never extrapolates past the probabilities it was fitted on. Same shape and
    same clamping `basketball_props_edges._apply_prob_curve` uses, so the two
    agree on what a curve means.
    """
    if not xs:
        return _clamp01(p)
    if p <= xs[0]:
        return _clamp01(ys[0])
    if p >= xs[-1]:
        return _clamp01(ys[-1])
    lo, hi = 0, len(xs) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if xs[mid] <= p:
            lo = mid
        else:
            hi = mid
    x0, x1, y0, y1 = xs[lo], xs[hi], ys[lo], ys[hi]
    if x1 <= x0:
        return _clamp01(y0)
    t = (p - x0) / (x1 - x0)
    return _clamp01(y0 + t * (y1 - y0))


def _validate_isotonic(cell: Mapping[str, Any]) -> tuple[list[float], list[float]] | str:
    xs_raw = cell.get("x")
    ys_raw = cell.get("y")
    if not isinstance(xs_raw, (list, tuple)) or not isinstance(ys_raw, (list, tuple)):
        return "isotonic cell needs list x and y"
    if len(xs_raw) < 2 or len(xs_raw) != len(ys_raw):
        return "isotonic cell needs >=2 breakpoints with matching lengths"
    xs: list[float] = []
    ys: list[float] = []
    for xv, yv in zip(xs_raw, ys_raw):
        x = _as_float(xv)
        y = _as_float(yv)
        if x is None or y is None:
            return "isotonic breakpoint is not a number"
        xs.append(x)
        ys.append(y)
    if any(xs[i + 1] <= xs[i] for i in range(len(xs) - 1)):
        return "isotonic x must be strictly increasing"
    if any(ys[i + 1] < ys[i] - 1e-12 for i in range(len(ys) - 1)):
        return "isotonic y must be non-decreasing"
    if any(y < -1e-9 or y > 1.0 + 1e-9 for y in ys):
        return "isotonic y outside [0, 1]"
    return xs, ys


def resolve_cell(
    profile: ProbabilityCalibrationProfile | None, market: Any, segment: Any
) -> tuple[str | None, Mapping[str, Any] | None]:
    """The cell for (market, segment), falling back to (market, *)."""
    if profile is None or not isinstance(profile.cells, Mapping) or not profile.cells:
        return None, None
    exact = cell_key(market, segment)
    cell = profile.cells.get(exact)
    if isinstance(cell, Mapping):
        return exact, cell
    wildcard = cell_key(market, ANY_SEGMENT)
    cell = profile.cells.get(wildcard)
    if isinstance(cell, Mapping):
        return wildcard, cell
    return None, None


def calibrate(
    sport: Any,
    market: Any,
    segment: Any,
    p: Any,
    *,
    profile: ProbabilityCalibrationProfile | None,
) -> tuple[float | None, dict[str, Any]]:
    """`(p_cal, meta)`. Identity when there is no profile or no cell.

    `meta` always carries `method` (one of `METHODS`), `version` (the
    profile's, or None when there is no profile) and `cell` (the key that
    answered, or None). A cell that could not be applied reports
    `method: identity` plus `cell_error`, so an unfed curve is visible on the
    row rather than silent.
    """
    value = _as_float(p)
    base_version = profile.version if profile is not None and profile is not IDENTITY_PROFILE else None
    meta: dict[str, Any] = {"method": METHOD_IDENTITY, "version": base_version, "cell": None, "sport": _sport_slug(sport)}
    if value is None:
        return None, meta
    value = _clamp01(value)
    key, cell = resolve_cell(profile, market, segment)
    if cell is None:
        return value, meta
    meta["cell"] = key
    if cell.get("version") is not None:
        meta["version"] = cell.get("version")
    method = str(cell.get("method") or "").strip().lower()
    if method == METHOD_IDENTITY or not method:
        return value, meta
    if method == METHOD_AFFINE_LOGIT:
        a = _as_float(cell.get("a"))
        b = _as_float(cell.get("b"))
        if a is None or b is None:
            meta["cell_error"] = "affine_logit cell needs numeric a and b"
            return value, meta
        meta["method"] = METHOD_AFFINE_LOGIT
        return apply_affine_logit(value, a, b), meta
    if method == METHOD_ISOTONIC:
        parsed = _validate_isotonic(cell)
        if isinstance(parsed, str):
            meta["cell_error"] = parsed
            return value, meta
        xs, ys = parsed
        meta["method"] = METHOD_ISOTONIC
        return apply_isotonic(value, xs, ys), meta
    meta["cell_error"] = f"unknown method {method!r}"
    return value, meta


# --------------------------------------------------------------------------
# Scoring and fitting (shared with the harness)
# --------------------------------------------------------------------------


def brier(ps: Sequence[float], ys: Sequence[int]) -> float | None:
    if not ps:
        return None
    return sum((float(p) - float(y)) ** 2 for p, y in zip(ps, ys)) / len(ps)


def log_loss(ps: Sequence[float], ys: Sequence[int]) -> float | None:
    if not ps:
        return None
    total = 0.0
    for p, y in zip(ps, ys):
        q = min(max(float(p), _LOGIT_EPS), 1.0 - _LOGIT_EPS)
        total += -math.log(q) if y else -math.log(1.0 - q)
    return total / len(ps)


def fit_affine_logit(ps: Sequence[float], ys: Sequence[int], *, iterations: int = 200) -> tuple[float, float]:
    """Maximum-likelihood `(a, b)` for `logit(p_cal) = a + b*logit(p)` -- Platt
    scaling on the logit. Newton's method on the two-parameter log-loss with a
    small ridge so a separable or degenerate cell cannot run to infinity."""
    if not ps:
        return 0.0, 1.0
    zs = [_logit(_clamp01(float(p))) for p in ps]
    a, b = 0.0, 1.0
    ridge = 1e-4
    for _ in range(iterations):
        g_a = g_b = 0.0
        h_aa = h_ab = h_bb = 0.0
        for z, y in zip(zs, ys):
            q = _sigmoid(a + b * z)
            r = q - float(y)
            w = q * (1.0 - q)
            g_a += r
            g_b += r * z
            h_aa += w
            h_ab += w * z
            h_bb += w * z * z
        n = float(len(zs))
        g_a = g_a / n + ridge * a
        g_b = g_b / n + ridge * (b - 1.0)
        h_aa = h_aa / n + ridge
        h_ab = h_ab / n
        h_bb = h_bb / n + ridge
        det = h_aa * h_bb - h_ab * h_ab
        if det <= 1e-12:
            break
        da = (h_bb * g_a - h_ab * g_b) / det
        db = (h_aa * g_b - h_ab * g_a) / det
        a -= da
        b -= db
        if abs(da) < 1e-10 and abs(db) < 1e-10:
            break
    return a, b


def fit_isotonic(ps: Sequence[float], ys: Sequence[int]) -> tuple[list[float], list[float]]:
    """Pool-adjacent-violators, returned as breakpoints `(x, y)`.

    `x` is each pooled block's mean probability and `y` its observed rate, so
    `apply_isotonic` interpolates BETWEEN block centres rather than producing
    a step function -- the same continuous shape the basketball curve carries.
    Ties in `p` are merged before pooling so `x` is strictly increasing.
    """
    if not ps:
        return [], []
    pairs = sorted((float(p), float(y)) for p, y in zip(ps, ys))
    # Blocks: [sum_p, sum_y, count]
    blocks: list[list[float]] = []
    for p, y in pairs:
        if blocks and abs(blocks[-1][0] / blocks[-1][2] - p) < 1e-12:
            blocks[-1][0] += p
            blocks[-1][1] += y
            blocks[-1][2] += 1
        else:
            blocks.append([p, y, 1.0])
    # PAVA on the block means.
    stack: list[list[float]] = []
    for block in blocks:
        stack.append(list(block))
        while len(stack) >= 2 and (stack[-2][1] / stack[-2][2]) > (stack[-1][1] / stack[-1][2]):
            last = stack.pop()
            stack[-1][0] += last[0]
            stack[-1][1] += last[1]
            stack[-1][2] += last[2]
    xs = [b[0] / b[2] for b in stack]
    ys_out = [_clamp01(b[1] / b[2]) for b in stack]
    if len(xs) == 1:
        # A single block is a constant; express it as two breakpoints so the
        # cell validates (>= 2 points) and reads as the flat line it is.
        xs = [0.0, 1.0]
        ys_out = [ys_out[0], ys_out[0]]
    return xs, ys_out


def profile_from_json(payload: Mapping[str, Any]) -> ProbabilityCalibrationProfile:
    """Build a profile from an already-parsed `fields` payload (tests, harness)."""
    cells = payload.get("cells")
    return ProbabilityCalibrationProfile(
        version=str(payload.get("version") or METHOD_IDENTITY),
        sport=payload.get("sport"),
        cells=dict(cells) if isinstance(cells, Mapping) else {},
    )


def read_profile_file(path: Path) -> ProbabilityCalibrationProfile | None:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None
    fields_payload = payload.get("fields") if isinstance(payload, Mapping) else None
    if not isinstance(fields_payload, Mapping):
        return None
    return profile_from_json(fields_payload)


__all__ = [
    "ANY_SEGMENT",
    "ENV_FLAG",
    "IDENTITY_PROFILE",
    "METHODS",
    "METHOD_AFFINE_LOGIT",
    "METHOD_IDENTITY",
    "METHOD_ISOTONIC",
    "PROFILE_FILENAME",
    "PROFILE_KEY",
    "ProbabilityCalibrationProfile",
    "apply_affine_logit",
    "apply_isotonic",
    "brier",
    "cached_profile",
    "calibrate",
    "cell_key",
    "clear_profile_cache",
    "fit_affine_logit",
    "fit_isotonic",
    "load_profile",
    "log_loss",
    "pricing_calibration_enabled",
    "profile_from_json",
    "profile_path",
    "read_profile_file",
    "resolve_cell",
    "save_profile",
]
