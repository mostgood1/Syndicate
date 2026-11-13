"""A side correction for the board's two-sided PROP fair (lane `prop-fair-side-lean`, 2026-11-13).

Measured on the board's graded population (10-17..11-08, `findings_2026-11-13_prop_fair_side_lean.md`): NBA prop
overs hit 3.4 pts below the consensus no-vig fair, flat across markets, fair levels and pricing books. A de-vig
method cannot remove a lean at prices near even money, where every method returns the same number, so the correction
is a calibration term on the fair rather than a different de-vig:

    logit(p_over') = logit(p_over) + delta[sport]        p_under' = 1 - p_over'

`delta` is the maximum-likelihood intercept of the outcome on the fair as an offset, fitted on graded rows framed on
the over. It is shrunk toward 0 by its own precision (`shrunk`), so a sport with little evidence moves little.

PURE: no I/O and no wiring. Nothing on the board reads this module; wiring it into the fair (lane `fair-price-v2`'s
`_resolve_fair` / `_consensus_fair`) is a user decision.
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Mapping

EPS = 1e-6
PRIOR_SD = 0.10          # logit units: a 0.10 shift is ~2.5 pts at even money


def _logit(p: float) -> float:
    p = min(max(float(p), EPS), 1.0 - EPS)
    return math.log(p / (1.0 - p))


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x)) if x >= 0 else math.exp(x) / (1.0 + math.exp(x))


def shift(p_over: float, delta: float) -> float:
    """The over's fair moved by `delta` in logit units."""
    return _sigmoid(_logit(p_over) + delta)


def fit_delta(rows: Iterable[tuple[float, float]], *, iters: int = 50) -> dict[str, Any] | None:
    """MLE of `delta` from (p_over, y_over) pairs, y in {0, 1}: Newton on the one-parameter offset logistic.

    Returns the estimate, its standard error (from the observed information) and n; None without rows."""
    pairs = [(_logit(p), float(y)) for p, y in rows if y in (0.0, 1.0)]
    if not pairs:
        return None
    d = 0.0
    info = 0.0
    for _ in range(iters):
        grad = info = 0.0
        for off, y in pairs:
            q = _sigmoid(off + d)
            grad += y - q
            info += q * (1.0 - q)
        if info <= 0:
            return None
        step = grad / info
        d += step
        if abs(step) < 1e-10:
            break
    return {"delta": d, "se": 1.0 / math.sqrt(info), "n": len(pairs)}


def shrunk(fit: Mapping[str, Any] | None, *, prior_sd: float = PRIOR_SD) -> float:
    """The fitted delta, shrunk toward 0 by a normal prior N(0, prior_sd^2): delta * w, w = prior / (prior + se^2).

    NOTE the row-level se understates the uncertainty of a game-correlated sample; callers that have game counts
    should inflate it (see `inflate_se`)."""
    if not fit:
        return 0.0
    v = prior_sd ** 2
    return float(fit["delta"]) * v / (v + float(fit["se"]) ** 2)


def inflate_se(fit: Mapping[str, Any] | None, *, design_effect: float) -> dict[str, Any] | None:
    """A copy of `fit` with its se scaled by sqrt(design_effect) -- the variance ratio of the game-clustered mean to
    the row-level one, measured by the caller."""
    if not fit:
        return None
    return dict(fit, se=float(fit["se"]) * math.sqrt(max(design_effect, 1.0)))


def adjusted(p: float, *, side: str, delta: float) -> float:
    """`p` (the fair of `side`) after the over's correction. Over/yes moves by +delta; under/no is its complement."""
    s = str(side or "").strip().lower()
    if s in ("over", "yes"):
        return shift(p, delta)
    if s in ("under", "no"):
        return 1.0 - shift(1.0 - p, delta)
    return p


def log_loss(p: float, y: float) -> float:
    p = min(max(p, EPS), 1.0 - EPS)
    return -(y * math.log(p) + (1.0 - y) * math.log(1.0 - p))
