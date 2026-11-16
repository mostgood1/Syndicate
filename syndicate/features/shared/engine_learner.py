"""Phase 1B M2: the shadow learner (lane ``engine-learner``; plan ``docs/ai_context/plan_one_engine_pregame_live.md`` §2).

One probability per line at an instant::

    logit p_decision = logit p_prior + sum_e  w_e(cell) * delta_e

* ``p_prior`` is the market prior each expert already carries (Kalshi's mid or the books' fair, live; the record's
  prior, pregame). It enters as an OFFSET: with every weight 0 the learner IS the prior, exactly.
* ``delta_e`` is expert ``e``'s Δlogit on that line at that instant (the experts' ``ExpertOpinion.delta_logit``).
* ``w_e(cell)`` is a sum of one parameter per node on the cell's path -- root -> sport -> family -> market -> segment
  -> phase -> clock bucket -- each with a Gaussian prior N(0, tau^2). That is hierarchical partial pooling: a thin
  leaf borrows its parent's weight and is shrunk toward it, and the root is shrunk toward 0 (nothing is switched off,
  everything starts as "the expert adds nothing").
* A fitted weight is APPLIED only where its lower bound is above 0 (plan: "a weight is applied only when its lower
  bound is above 0"); otherwise that expert contributes 0 on that cell. Negative weights are never applied.

Uncertainty is GAME-CLUSTERED. Live opinions repeat every tick and a game's lines share one final score, so rows are
far from independent: each line is weighted 1 / (its ticks), the weights' standard errors are the cluster-robust
sandwich over games, and every held-out log-loss CI is a bootstrap over games.

Shadow only: nothing imports this module except its script and tests. It reads opinions and outcomes as plain
dicts, so it does not import the experts module (or anything on an order path); the experts' shadow guard
(``test_nothing_in_the_app_reads_the_experts_yet``) holds this file to that by name.
"""
from __future__ import annotations

import math
import random
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np

LEARNER_VERSION = "engine_learner/1"

# The cell tree, root first. Each level is one node on every row's path. The last level is the PRIOR'S AGE: in play a
# book prior can be up to 900 s old while a re-sim knows the current score, so a weight learned against a stale prior
# must not stand for one against a fresh prior (measured on the fleet 11-09: ~10% of live opinions had a prior <= 60 s
# old). The gate reads the fresh stratum.
CELL_LEVELS: tuple[str, ...] = ("sport", "family", "market", "segment", "phase", "bucket", "prior_age")
ROOT = "*"

# Prior SD of every node's parameter (weights are on the Δlogit scale: 1.0 = take the expert at face value).
TAU = 0.5
# One-sided lower bound used to decide whether a fitted weight is applied (95% two-sided).
APPLY_Z = 1.96
# Probability clip, the same bounds the experts use.
P_CLIP = (1e-6, 1.0 - 1e-6)

FAMILY_OF_MARKET: dict[str, str] = {
    "totals": "totals", "totals_alt": "totals",
    "spreads": "spreads", "spreads_alt": "spreads",
    "h2h": "h2h",
}
FAMILY_PROPS = "props"

PRIOR_AGE_BUCKETS: tuple[tuple[float, str], ...] = ((60.0, "a<=60"), (180.0, "a60-180"), (900.0, "a180-900"))
PRIOR_AGE_OLD = "a>900"
PRIOR_AGE_UNKNOWN = "a?"
FRESH_PRIOR = "a<=60"
# The truth's name for a line that pushed: dropped, and counted. A label is the probability the opinion's side
# won, so 0.5 is a legitimate SOFT label (a close at even money) and cannot stand for a push.
PUSH = "push"


def clip(p: float) -> float:
    return min(P_CLIP[1], max(P_CLIP[0], float(p)))


def logit(p: float) -> float:
    q = clip(p)
    return math.log(q / (1.0 - q))


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def family_of(market: str) -> str:
    return FAMILY_OF_MARKET.get(str(market or ""), FAMILY_PROPS)


def prior_age_bucket(age_s: Any) -> str:
    age = _finite(age_s)
    if age is None:
        return PRIOR_AGE_UNKNOWN
    for limit, name in PRIOR_AGE_BUCKETS:
        if age <= limit:
            return name
    return PRIOR_AGE_OLD


def game_id(op: Mapping[str, Any]) -> str:
    """The game an opinion is about, as the live evidence log names it (ESPN's event id). `live_resim` keys its
    opinions by the game-line ledger's event id and records the evidence row's id in `inputs.evidence_event_id`; the
    segment and stat-progress experts key by the evidence id already. One game must be one cluster."""
    inputs = op.get("inputs") or {}
    return str(inputs.get("evidence_event_id") or op.get("event_id") or "")


def _finite(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


# ----------------------------------------------------------------------------- examples


@dataclass(slots=True)
class Example:
    """One line at one instant, with every usable expert's Δ and the line's outcome."""

    key: str                    # line_key|t
    line_key: str
    cluster: str                # sport|event_id -- the game
    date: str                   # slate date (the runner's), for forward splits
    cell: tuple[str, ...]       # values for CELL_LEVELS
    logit_prior: float
    deltas: dict[str, float]
    y: float                    # 1 if the opinion's side won, 0 if it lost (pushes are dropped)
    weight: float = 1.0         # 1 / ticks of this line
    prior_age_s: float | None = None


@dataclass(slots=True)
class BuildStats:
    opinions: int = 0
    refused: int = 0
    unusable: int = 0           # no prior or no Δ
    prior_disagree: int = 0     # two experts on one line-instant with different priors (first kept)
    no_truth: int = 0
    push: int = 0
    by_truth_refusal: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    examples: int = 0
    lines: int = 0
    games: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "opinions": self.opinions, "refused": self.refused, "unusable": self.unusable,
            "prior_disagree": self.prior_disagree, "no_truth": self.no_truth, "push": self.push,
            "by_truth_refusal": dict(sorted(self.by_truth_refusal.items())),
            "examples": self.examples, "lines": self.lines, "games": self.games,
        }


TruthFn = Callable[[Mapping[str, Any]], "tuple[float | None, str | None]"]


def cell_of(op: Mapping[str, Any]) -> tuple[str, ...]:
    market = str(op.get("market") or "")
    return (
        str(op.get("sport") or ""),
        family_of(market),
        market,
        str(op.get("segment") or "full"),
        str(op.get("phase") or ""),
        str(op.get("clock_bucket") or ""),
        prior_age_bucket(op.get("prior_age_s")),
    )


def build_examples(
    opinions: Iterable[tuple[str, Mapping[str, Any]]],
    truth: TruthFn,
) -> tuple[list[Example], BuildStats]:
    """Group usable opinions by (line_key, t) into examples and attach each line's outcome.

    ``opinions`` yields (slate date, opinion dict). ``truth(op)`` returns (y, refusal): y = the probability that
    the opinion's side wins -- 1.0 / 0.0 for an outcome, a soft label in (0, 1) for a close -- or None with a named
    refusal; the refusal ``PUSH`` is a push (dropped, counted).
    """
    stats = BuildStats()
    grouped: dict[str, Example] = {}
    for date, op in opinions:
        stats.opinions += 1
        if op.get("refusal"):
            stats.refused += 1
            continue
        p_prior = _finite(op.get("p_prior"))
        delta = _finite(op.get("delta_logit"))
        line_key = str(op.get("line_key") or "")
        if p_prior is None or delta is None or not line_key:
            stats.unusable += 1
            continue
        key = f"{line_key}|{op.get('t') or ''}"
        ex = grouped.get(key)
        if ex is None:
            y, refusal = truth(op)
            if refusal == PUSH:
                stats.push += 1
                continue
            if y is None or not 0.0 <= y <= 1.0:
                stats.no_truth += 1
                stats.by_truth_refusal[refusal or "label_out_of_range"] += 1
                continue
            ex = Example(
                key=key, line_key=line_key,
                cluster=f"{op.get('sport') or ''}|{game_id(op)}",
                date=str(date), cell=cell_of(op), logit_prior=logit(p_prior), deltas={}, y=float(y),
                prior_age_s=_finite(op.get("prior_age_s")),
            )
            grouped[key] = ex
        elif abs(ex.logit_prior - logit(p_prior)) > 1e-9:
            stats.prior_disagree += 1
        ex.deltas[str(op.get("expert") or "")] = delta
    examples = list(grouped.values())
    ticks: dict[str, int] = defaultdict(int)
    for ex in examples:
        ticks[ex.line_key] += 1
    for ex in examples:
        ex.weight = 1.0 / ticks[ex.line_key]
    stats.examples = len(examples)
    stats.lines = len(ticks)
    stats.games = len({ex.cluster for ex in examples})
    return examples, stats


# ----------------------------------------------------------------------------- the model


def node_path(cell: Sequence[str]) -> list[str]:
    """Root first: '*', 'nba', 'nba/totals', ... one node per CELL_LEVELS entry."""
    out = [ROOT]
    for i in range(len(cell)):
        out.append("/".join(cell[: i + 1]))
    return out


@dataclass(slots=True)
class Fit:
    params: list[tuple[str, str]]           # (expert, node)
    theta: np.ndarray
    cov: np.ndarray                          # cluster-robust (sandwich) covariance of theta
    tau: float
    n_examples: int
    n_games: int
    converged: bool
    message: str
    index: dict[tuple[str, str], int] = field(default_factory=dict)
    _cache: dict[tuple[str, tuple[str, ...]], tuple[float, float]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.index = {p: i for i, p in enumerate(self.params)}

    def weight(self, expert: str, cell: Sequence[str]) -> tuple[float, float]:
        """(weight, standard error) of ``expert`` on ``cell``: the sum of its path's parameters. A node the fit
        never saw contributes 0 (it falls back to its parents)."""
        key = (expert, tuple(cell))
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        idx = [self.index[(expert, n)] for n in node_path(cell) if (expert, n) in self.index]
        if not idx:
            out = (0.0, 0.0)
        else:
            w = float(self.theta[idx].sum())
            var = float(self.cov[np.ix_(idx, idx)].sum())
            out = (w, math.sqrt(max(0.0, var)))
        self._cache[key] = out
        return out

    def applied_weight(self, expert: str, cell: Sequence[str], z: float = APPLY_Z) -> float:
        w, se = self.weight(expert, cell)
        return w if w - z * se > 0.0 else 0.0


def _design(examples: Sequence[Example], index: Mapping[tuple[str, str], int]):
    from scipy import sparse

    rows, cols, vals = [], [], []
    for r, ex in enumerate(examples):
        path = node_path(ex.cell)
        for expert, delta in ex.deltas.items():
            for node in path:
                j = index.get((expert, node))
                if j is not None:
                    rows.append(r)
                    cols.append(j)
                    vals.append(delta)
    return sparse.csr_matrix((vals, (rows, cols)), shape=(len(examples), len(index)))


def fit(examples: Sequence[Example], *, tau: float = TAU, max_iter: int = 500) -> Fit:
    """MAP fit of every (expert, node) parameter: weighted log loss with the prior as offset + sum theta^2/(2 tau^2)."""
    from scipy.optimize import minimize

    seen: dict[tuple[str, str], None] = {}
    for ex in examples:
        for expert in ex.deltas:
            for node in node_path(ex.cell):
                seen.setdefault((expert, node), None)
    params = sorted(seen)
    index = {p: i for i, p in enumerate(params)}
    if not params or not examples:
        return Fit(params=params, theta=np.zeros(len(params)), cov=np.zeros((len(params), len(params))), tau=tau,
                   n_examples=len(examples), n_games=len({e.cluster for e in examples}), converged=True,
                   message="nothing to fit")
    X = _design(examples, index)
    off = np.array([ex.logit_prior for ex in examples])
    y = np.array([ex.y for ex in examples])
    w = np.array([ex.weight for ex in examples])
    inv_t2 = 1.0 / (tau * tau)

    def objective(theta: np.ndarray) -> tuple[float, np.ndarray]:
        eta = off + X @ theta
        # log(1 + e^eta) - y*eta, stably
        loss = float(np.sum(w * (np.logaddexp(0.0, eta) - y * eta))) + 0.5 * inv_t2 * float(theta @ theta)
        grad = X.T @ (w * (sigmoid(eta) - y)) + inv_t2 * theta
        return loss, np.asarray(grad).ravel()

    res = minimize(objective, np.zeros(len(params)), jac=True, method="L-BFGS-B",
                   options={"maxiter": max_iter, "gtol": 1e-9})
    theta = np.asarray(res.x)
    eta = off + X @ theta
    p = sigmoid(eta)
    from scipy import sparse

    # Sparse throughout: a night is ~10^5 rows x ~10^3 parameters, so a dense design would be gigabytes.
    H = (X.T @ X.multiply((w * p * (1.0 - p))[:, None])).toarray() + inv_t2 * np.eye(len(params))
    H_inv = np.linalg.pinv(H)
    # Cluster-robust meat: sum over games of (the game's score)(the game's score)^T.
    games = sorted({ex.cluster for ex in examples})
    gi = {c: i for i, c in enumerate(games)}
    G = sparse.csr_matrix((np.ones(len(examples)), ([gi[ex.cluster] for ex in examples], np.arange(len(examples)))),
                          shape=(len(games), len(examples)))
    S = (G @ X.multiply((w * (p - y))[:, None])).toarray()
    meat = S.T @ S
    g = len(games)
    if g > 1:
        meat *= g / (g - 1)
    cov = H_inv @ meat @ H_inv
    return Fit(params=params, theta=theta, cov=cov, tau=tau, n_examples=len(examples), n_games=g,
               converged=bool(res.success), message=str(res.message))


def p_decision(ex: Example, model: Fit | None, *, applied: bool = True, z: float = APPLY_Z) -> float:
    """The learner's probability for the opinion's side. ``model=None`` is the prior (the off switch)."""
    eta = ex.logit_prior
    if model is not None:
        for expert, delta in ex.deltas.items():
            w = model.applied_weight(expert, ex.cell, z) if applied else model.weight(expert, ex.cell)[0]
            eta += w * delta
    return _sig(eta)


def _sig(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


# ----------------------------------------------------------------------------- held-out evaluation


def log_loss(p: float, y: float) -> float:
    q = clip(p)
    return -(y * math.log(q) + (1.0 - y) * math.log(1.0 - q))


def group_key(ex: Example) -> tuple[str, ...]:
    """The gate's reporting unit: sport x family x phase."""
    return ex.cell[0], ex.cell[1], ex.cell[4]


def group_age_key(ex: Example) -> tuple[str, ...]:
    """sport x family x phase x prior-age bucket: the reading that separates an edge over a FRESH prior from a
    stale prior's lag."""
    return ex.cell[0], ex.cell[1], ex.cell[4], ex.cell[6]


def evaluate(
    examples: Sequence[Example], model: Fit | None, *, applied: bool = True, boot: int = 1000, seed: int = 736,
    by: Callable[[Example], tuple[str, ...]] = group_key,
) -> dict[tuple[str, ...], dict[str, Any]]:
    """Per sport x family x phase: weighted mean log loss of p_decision minus the prior's, with a 95% CI from a
    bootstrap over games. Negative = the learner beats the prior."""
    per_game: dict[tuple[str, ...], dict[str, list[float]]] = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0.0]))
    counts: dict[tuple[str, ...], list[int]] = defaultdict(lambda: [0, 0])
    lines: dict[tuple[str, ...], set[str]] = defaultdict(set)
    for ex in examples:
        k = by(ex)
        p = p_decision(ex, model, applied=applied)
        prior_ll = log_loss(_sig(ex.logit_prior), ex.y)
        acc = per_game[k][ex.cluster]
        acc[0] += ex.weight * (log_loss(p, ex.y) - prior_ll)
        acc[1] += ex.weight
        acc[2] += ex.weight * prior_ll
        counts[k][0] += 1
        lines[k].add(ex.line_key)
    rng = random.Random(seed)
    out: dict[tuple[str, ...], dict[str, Any]] = {}
    for k in sorted(per_game):
        games = list(per_game[k].values())
        diff = sum(g[0] for g in games)
        wsum = sum(g[1] for g in games)
        prior_ll = sum(g[2] for g in games)
        mean = diff / wsum if wsum else 0.0
        draws: list[float] = []
        if len(games) > 1:
            for _ in range(boot):
                sample = [games[rng.randrange(len(games))] for _ in games]
                ws = sum(g[1] for g in sample)
                if ws:
                    draws.append(sum(g[0] for g in sample) / ws)
            draws.sort()
        lo = draws[int(0.025 * len(draws))] if draws else None
        hi = draws[min(len(draws) - 1, int(0.975 * len(draws)))] if draws else None
        out[k] = {
            "examples": counts[k][0], "lines": len(lines[k]), "games": len(games),
            "prior_log_loss": round(prior_ll / wsum, 6) if wsum else None,
            "delta_log_loss": round(mean, 6), "ci95": [None if lo is None else round(lo, 6),
                                                       None if hi is None else round(hi, 6)],
            "beats_prior": hi is not None and hi < 0.0,
        }
    return out


def forward_split(examples: Sequence[Example], first_test_date: str) -> tuple[list[Example], list[Example]]:
    """Hold out, WHOLE, every game (cluster) with an example dated on or after ``first_test_date``; train on the rest.

    A game's pregame lines are listed on slates before the game, so a split by example date alone put 127 games of the
    2026-11-16 dev run on both sides (their outcome in training, their live lines in test). The runner dates each
    example by its GAME (``scripts/engine_learner.py`` ``game_dated``); this rule holds even where it cannot."""
    test_games = {ex.cluster for ex in examples if ex.date >= first_test_date}
    train = [ex for ex in examples if ex.cluster not in test_games]
    test = [ex for ex in examples if ex.cluster in test_games]
    return train, test


def weight_table(model: Fit, examples: Sequence[Example], *, z: float = APPLY_Z) -> list[dict[str, Any]]:
    """Per (expert, leaf cell) seen in ``examples``: the fitted weight, its SE, whether it is applied, and n."""
    n: dict[tuple[str, tuple[str, ...]], int] = defaultdict(int)
    for ex in examples:
        for expert in ex.deltas:
            n[(expert, ex.cell)] += 1
    rows = []
    for (expert, cell), count in sorted(n.items()):
        w, se = model.weight(expert, cell)
        rows.append({"expert": expert, "cell": "/".join(cell), "n": count, "w": round(w, 4), "se": round(se, 4),
                     "applied": w - z * se > 0.0})
    return rows
