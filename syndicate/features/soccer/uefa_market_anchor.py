"""UEFA club ratings anchored to the market's past prices (todo #699 follow-up).

Research code; nothing in the sim, the board or a worker imports it. The registration is
`.syndicate/findings_2026-10-19_uefa_market_anchored.md` section 1.

THE MODEL. A base model supplies each match's goal rates `(lam_h, lam_a)` (the #699 step-3 model:
production ratings + CONST league offsets + out-of-scope FITTED ratings). Each club gets a correction
`(alpha_c, delta_c)` in log-goal-rate units:

    log lam'_h = log lam_h + alpha[home] - delta[away]
    log lam'_a = log lam_a + alpha[away] - delta[home]

fit by weighted CROSS-ENTROPY TO THE DE-VIGGED CLOSE (the target is the market's 1X2, not the outcome)
with a ridge penalty tau/2 * sum(alpha^2 + delta^2). The base rates are fixed. 1X2 comes from
independent Poisson truncated at MAX_GOALS and renormalised, exactly as `uefa_league_offsets.outcome_probs`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson

MAX_GOALS = 10
TAU_GRID: tuple[float, ...] = (1.0, 3.0, 10.0, 30.0, 100.0)
HALF_LIFE_DAYS = 365


@dataclass
class AnchorMatch:
    home_id: str
    away_id: str
    lam_h: float
    lam_a: float
    p_close: tuple[float, float, float]  # home, draw, away (de-vigged)
    y: int  # 0 home / 1 draw / 2 away (90 minutes)


_G = np.arange(MAX_GOALS + 1)
_HOME = np.tril(np.ones((MAX_GOALS + 1, MAX_GOALS + 1)), -1).astype(bool)  # i > j
_DRAW = np.eye(MAX_GOALS + 1, dtype=bool)
_AWAY = np.triu(np.ones((MAX_GOALS + 1, MAX_GOALS + 1)), 1).astype(bool)


def probs_from_rates(lam_h: float, lam_a: float) -> tuple[float, float, float]:
    grid = np.outer(poisson.pmf(_G, lam_h), poisson.pmf(_G, lam_a))
    z = grid.sum()
    return float(grid[_HOME].sum() / z), float(grid[_DRAW].sum() / z), float(grid[_AWAY].sum() / z)


def _probs_and_grads(lh: np.ndarray, la: np.ndarray):
    """Vectorised 1X2 (n, 3) and d q_k / d log lam_h, d log lam_a (n, 3) each."""
    ph = poisson.pmf(_G[None, :], lh[:, None])  # (n, G)
    pa = poisson.pmf(_G[None, :], la[:, None])
    grid = ph[:, :, None] * pa[:, None, :]  # (n, G, G)
    # d P(i,j) / d log lam_h = P(i,j) * (i - lam_h); same for away with j.
    gi = grid * (_G[None, :, None] - lh[:, None, None])
    gj = grid * (_G[None, None, :] - la[:, None, None])
    masks = (_HOME, _DRAW, _AWAY)
    P = np.stack([grid[:, m].sum(axis=1) for m in masks], axis=1)  # (n, 3)
    dPh = np.stack([gi[:, m].sum(axis=1) for m in masks], axis=1)
    dPa = np.stack([gj[:, m].sum(axis=1) for m in masks], axis=1)
    Z = P.sum(axis=1, keepdims=True)
    q = P / Z
    dqh = (dPh - q * dPh.sum(axis=1, keepdims=True)) / Z
    dqa = (dPa - q * dPa.sum(axis=1, keepdims=True)) / Z
    return q, dqh, dqa


@dataclass
class AnchorFit:
    corrections: dict[str, tuple[float, float]]  # club -> (alpha, delta)
    tau: float
    n_matches: int

    def rates(self, m: AnchorMatch) -> tuple[float, float]:
        ah, dh = self.corrections.get(str(m.home_id), (0.0, 0.0))
        aa, da = self.corrections.get(str(m.away_id), (0.0, 0.0))
        return m.lam_h * math.exp(ah - da), m.lam_a * math.exp(aa - dh)

    def probs(self, m: AnchorMatch) -> tuple[float, float, float]:
        return probs_from_rates(*self.rates(m))


def fit_anchor(matches: Sequence[AnchorMatch], *, tau: float, weights: Sequence[float] | None = None) -> AnchorFit:
    """Ridge-penalised weighted cross-entropy to the close. Clubs not in `matches` get no entry (= 0)."""
    if weights is not None and len(weights) != len(matches):
        raise ValueError("weights must have one entry per match")
    if not matches:
        return AnchorFit({}, tau, 0)
    w = np.ones(len(matches)) if weights is None else np.asarray(weights, dtype=float)
    clubs = sorted({str(m.home_id) for m in matches} | {str(m.away_id) for m in matches})
    ix = {c: i for i, c in enumerate(clubs)}
    C = len(clubs)
    hi = np.array([ix[str(m.home_id)] for m in matches])
    ai = np.array([ix[str(m.away_id)] for m in matches])
    lh0 = np.array([m.lam_h for m in matches], dtype=float)
    la0 = np.array([m.lam_a for m in matches], dtype=float)
    target = np.array([m.p_close for m in matches], dtype=float)

    def objective(theta):
        alpha, delta = theta[:C], theta[C:]
        eh = alpha[hi] - delta[ai]
        ea = alpha[ai] - delta[hi]
        q, dqh, dqa = _probs_and_grads(lh0 * np.exp(eh), la0 * np.exp(ea))
        q = np.clip(q, 1e-15, None)
        ce = -(target * np.log(q)).sum(axis=1)
        loss = float((w * ce).sum()) + 0.5 * tau * float(theta @ theta)
        # d ce / d log lam = -sum_k t_k / q_k * dq_k
        gh = -(target / q * dqh).sum(axis=1) * w
        ga = -(target / q * dqa).sum(axis=1) * w
        g_alpha = tau * alpha.copy()
        g_delta = tau * delta.copy()
        np.add.at(g_alpha, hi, gh)
        np.add.at(g_alpha, ai, ga)
        np.add.at(g_delta, ai, -gh)
        np.add.at(g_delta, hi, -ga)
        return loss, np.concatenate([g_alpha, g_delta])

    theta = minimize(objective, np.zeros(2 * C), jac=True, method="L-BFGS-B").x
    return AnchorFit({c: (float(theta[i]), float(theta[C + i])) for c, i in ix.items()}, tau, len(matches))


def log_loss(probs: Sequence[float], y: int) -> float:
    return -math.log(max(float(probs[y]), 1e-15))


def mean_outcome_log_loss(fit: AnchorFit, matches: Sequence[AnchorMatch]) -> float:
    return float(np.mean([log_loss(fit.probs(m), m.y) for m in matches])) if matches else float("nan")


def select_tau(train: Sequence[AnchorMatch], weights: Sequence[float], val: Sequence[AnchorMatch], *,
               grid: Sequence[float] = TAU_GRID) -> tuple[float, dict[str, float]]:
    """The registered inner rule: lowest OUTCOME log loss on `val`; ties go to the larger tau."""
    scores: dict[str, float] = {}
    best: tuple[float, float] | None = None
    for tau in sorted(grid, reverse=True):
        ll = mean_outcome_log_loss(fit_anchor(train, tau=tau, weights=weights), val)
        scores[f"{tau:g}"] = ll
        if best is None or ll < best[0] - 1e-12:
            best = (ll, tau)
    assert best is not None
    return best[1], scores


def recency_weights(days: Sequence[str], anchor_day: str, half_life_days: float = HALF_LIFE_DAYS) -> list[float]:
    from datetime import date

    a = date.fromisoformat(anchor_day[:10])
    return [0.5 ** ((a - date.fromisoformat(d[:10])).days / half_life_days) for d in days]
