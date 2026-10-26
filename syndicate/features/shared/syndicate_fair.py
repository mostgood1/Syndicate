"""Syndicate Fair v1 -- a learned, sharpness-weighted fair price with its own uncertainty. OFFLINE RESEARCH.

Decision Engine Phase 1 (`#736`; plan `docs/ai_context/plan_syndicate_decision_engine.md` section 3 L1), lane
`syndicate-fair-v1`. Pre-registration: `.syndicate/findings_2026-10-26_syndicate_fair_v1_preregistration.md`.

**NOTHING IN PRODUCTION IMPORTS THIS MODULE.** It is the model `scripts/syndicate_fair_fit.py` fits and scores
against the board's fair (`layer2_board._consensus_fair`, the median of per-book Shin de-vigs). Wiring it into the
DecisionRecord is a separate, later decision that the findings recommend for or against.

THE MODEL
---------
Each book is de-vigged against itself first (production's `opportunity_signals.devig`, Shin -- the same per-book
step the board's consensus takes), giving a probability vector p_b over the line's outcomes. The fair is the
normalised log-linear pool

    log p_fair(o) = sum_b pi_b * log p_b(o) - log Z,        pi_b = w_b / sum_b' w_b'

which for a two-way line is exactly the plan's  logit p_fair = sum_b w_b logit p_b / sum_b w_b  (the normaliser
cancels in the ratio), and extends to a soccer 1X2 without a special case.

The weights are additive on the log scale, so every term can be ridge-shrunk to 0 -- all zero is EQUAL weights:

    log w_b = th[b] + th[b, mfam] + th[b, tts] + th[b, mfam, tts] + th[age] + th[b, age]

with mfam the market family, tts the time-to-start snapshot and age the quote-age bucket. A model is fitted per
evaluation family (sport x kind), so a book's weight in NFL props never borrows from MLB game lines.

THE UNCERTAINTY, on the logit scale of each outcome (one-vs-rest)
-----------------------------------------------------------------
    sigma_fair^2 = D^2 * sum_b pi_b^2  +  r^2_cell

D^2 is the pi-weighted spread of the books' logits around the pooled logit; times sum pi^2 (= 1 / Kish n_eff) it is
the variance of the pooled logit IF the books were independent. They are not -- they share feeds and copy each
other -- so r^2_cell, the residual variance fitted per (mfam, tts) cell on the training rows, carries the rest:
it is the mean squared residual to the close not already explained by the dispersion term, floored at 0.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np

#: Decision snapshots (seconds before commence), in order; the time-to-start dimension of the weights.
TTS_BUCKETS: tuple[str, ...] = ("t24h", "t6h", "t2h", "t30m")
#: Quote-age bucket upper edges, seconds (a change log: age = time since the book last CHANGED this price).
AGE_EDGES_S: tuple[int, ...] = (900, 3600, 3 * 3600, 12 * 3600)
AGE_BUCKETS: tuple[str, ...] = ("<15m", "15m-1h", "1h-3h", "3h-12h")
#: A quote older than this at a snapshot is not used, by either fair (the board's evaluator uses 12h too).
MAX_AGE_S: int = AGE_EDGES_S[-1]
MARKET_FAMILIES: tuple[str, ...] = ("h2h", "spreads", "totals", "game_other", "prop")
P_CLIP = 1e-6


def market_family(market: str, segment: str, kind: str) -> str:
    """'h2h' | 'spreads' | 'totals' (full-game main markets) | 'game_other' (segments, alts, team totals, ...) |
    'prop' (any player market).

    `h2h_3_way` is NOT 'h2h': on basketball/baseball it is the REGULATION result with a draw, a different bet from the
    moneyline (soccer's own 1X2 arrives as plain `h2h` with a draw side)."""
    if kind == "prop":
        return "prop"
    m = str(market or "").strip().lower()
    seg = str(segment or "full").strip().lower()
    if seg not in ("full", "full_game", ""):
        return "game_other"
    if m in ("h2h", "moneyline"):
        return "h2h"
    if m in ("spreads", "spread"):
        return "spreads"
    if m in ("totals", "total"):
        return "totals"
    return "game_other"


def age_bucket(age_s: float) -> int:
    """Index into AGE_BUCKETS; ages past MAX_AGE_S land in the last bucket (callers drop them first)."""
    for i, edge in enumerate(AGE_EDGES_S):
        if age_s < edge:
            return i
    return len(AGE_EDGES_S) - 1


def _clip(p: np.ndarray) -> np.ndarray:
    return np.clip(p, P_CLIP, 1.0 - P_CLIP)


def log_pool(log_probs: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Normalised log-linear pool of per-book probability vectors (rows = books). Returns the pooled probabilities."""
    pi = np.asarray(weights, dtype=float)
    pi = pi / pi.sum()
    z = pi @ np.asarray(log_probs, dtype=float)
    z = z - z.max()
    p = np.exp(z)
    return p / p.sum()


def logit(p: Any) -> Any:
    p = np.clip(p, P_CLIP, 1.0 - P_CLIP)
    return np.log(p) - np.log1p(-p)


# ----------------------------------------------------------------------------- the flattened dataset


@dataclass
class Dataset:
    """Rows = (line, snapshot); entries = (row, book). Outcomes padded to K=3 with a mask.

    `log_p[e, k]` is book e's de-vigged log-probability for outcome k (0 where masked); `target[r, k]` a probability
    vector (the close, or a one-hot outcome); `row_of[e]` the row of entry e (entries of a row are contiguous).
    """
    row_of: np.ndarray            # (E,) int
    book: np.ndarray              # (E,) int  -- index into `books`
    age: np.ndarray               # (E,) int  -- index into AGE_BUCKETS
    log_p: np.ndarray             # (E, 3)
    mfam: np.ndarray              # (R,) int  -- index into MARKET_FAMILIES
    tts: np.ndarray               # (R,) int  -- index into TTS_BUCKETS
    mask: np.ndarray              # (R, 3) bool
    target: np.ndarray            # (R, 3)
    books: list[str] = field(default_factory=list)

    @property
    def n_rows(self) -> int:
        return int(self.mask.shape[0])

    @property
    def row_starts(self) -> np.ndarray:
        """First entry of each row (every row has >= 1 entry; entries are sorted by row)."""
        return np.flatnonzero(np.r_[True, self.row_of[1:] != self.row_of[:-1]])

    def subset(self, rows: np.ndarray) -> "Dataset":
        """The rows (bool mask or int index over rows) and their entries, re-indexed."""
        rows = np.asarray(rows)
        if rows.dtype == bool:
            rows = np.flatnonzero(rows)
        remap = np.full(self.n_rows, -1, dtype=np.int64)
        remap[rows] = np.arange(len(rows))
        keep = remap[self.row_of] >= 0
        new_row = remap[self.row_of[keep]]
        order = np.argsort(new_row, kind="stable")
        return Dataset(row_of=new_row[order], book=self.book[keep][order], age=self.age[keep][order],
                       log_p=self.log_p[keep][order], mfam=self.mfam[rows], tts=self.tts[rows], mask=self.mask[rows],
                       target=self.target[rows], books=self.books)

    def with_target(self, target: np.ndarray) -> "Dataset":
        return Dataset(row_of=self.row_of, book=self.book, age=self.age, log_p=self.log_p, mfam=self.mfam,
                       tts=self.tts, mask=self.mask, target=target, books=self.books)


def build_dataset(rows: Sequence[Mapping[str, Any]], books: Sequence[str], target_key: str = "target") -> Dataset:
    """From row dicts: {'books': [(book, age_s, [p_o...]), ...], 'mfam', 'tts', target_key: [p_o...]}."""
    index = {b: i for i, b in enumerate(books)}
    row_of, book, age, log_p = [], [], [], []
    mfam, tts, mask, target = [], [], [], []
    for r_i, r in enumerate(rows):
        k = len(r[target_key])
        for b, age_s, probs in r["books"]:
            row_of.append(r_i)
            book.append(index[b])
            age.append(age_bucket(age_s))
            lp = [0.0, 0.0, 0.0]
            for j, p in enumerate(probs):
                lp[j] = math.log(min(max(float(p), P_CLIP), 1 - P_CLIP))
            log_p.append(lp)
        mfam.append(MARKET_FAMILIES.index(r["mfam"]))
        tts.append(TTS_BUCKETS.index(r["tts"]))
        mask.append([j < k for j in range(3)])
        target.append(list(r[target_key]) + [0.0] * (3 - k))
    return Dataset(row_of=np.asarray(row_of, dtype=np.int64), book=np.asarray(book, dtype=np.int64),
                   age=np.asarray(age, dtype=np.int64), log_p=np.asarray(log_p, dtype=float).reshape(-1, 3),
                   mfam=np.asarray(mfam, dtype=np.int64), tts=np.asarray(tts, dtype=np.int64),
                   mask=np.asarray(mask, dtype=bool).reshape(-1, 3), target=np.asarray(target, dtype=float).reshape(-1, 3),
                   books=list(books))


# ----------------------------------------------------------------------------- the weight model


class WeightModel:
    """The six additive log-weight terms over one family's books. theta = 0 is equal weights."""

    def __init__(self, books: Sequence[str]):
        self.books = list(books)
        nb, nm, nt, na = len(self.books), len(MARKET_FAMILIES), len(TTS_BUCKETS), len(AGE_BUCKETS)
        sizes = {"b": nb, "bm": nb * nm, "bt": nb * nt, "bmt": nb * nm * nt, "a": na, "ba": nb * na}
        self.offsets: dict[str, int] = {}
        start = 0
        for name, size in sizes.items():
            self.offsets[name] = start
            start += size
        self.n_params = start
        self.theta = np.zeros(self.n_params)

    def term_index(self, ds: Dataset) -> list[np.ndarray]:
        nm, nt, na = len(MARKET_FAMILIES), len(TTS_BUCKETS), len(AGE_BUCKETS)
        b, m, t, a = ds.book, ds.mfam[ds.row_of], ds.tts[ds.row_of], ds.age
        o = self.offsets
        return [o["b"] + b, o["bm"] + b * nm + m, o["bt"] + b * nt + t, o["bmt"] + (b * nm + m) * nt + t,
                o["a"] + a, o["ba"] + b * na + a]

    def design(self, ds: Dataset) -> Any:
        """Sparse (E x n_params) 0/1 matrix: log w = A @ theta, and the gradient is A.T @ d(loss)/d(log w)."""
        from scipy.sparse import csr_matrix

        idx = self.term_index(ds)
        n = len(ds.row_of)
        cols = np.stack(idx, axis=1).ravel()
        rows = np.repeat(np.arange(n), len(idx))
        return csr_matrix((np.ones(len(cols)), (rows, cols)), shape=(n, self.n_params))

    def log_weights(self, ds: Dataset, theta: np.ndarray | None = None, design: Any = None) -> np.ndarray:
        th = self.theta if theta is None else theta
        A = self.design(ds) if design is None else design
        return A @ th

    def weights_table(self, mfam: str, tts: str, age: str = AGE_BUCKETS[0]) -> dict[str, float]:
        """Each book's weight in one cell, relative to the cell's geometric-mean book (1.0 = an equal vote)."""
        m, t, a = MARKET_FAMILIES.index(mfam), TTS_BUCKETS.index(tts), AGE_BUCKETS.index(age)
        nm, nt, na = len(MARKET_FAMILIES), len(TTS_BUCKETS), len(AGE_BUCKETS)
        o, th = self.offsets, self.theta
        lw = {}
        for b, name in enumerate(self.books):
            lw[name] = (th[o["b"] + b] + th[o["bm"] + b * nm + m] + th[o["bt"] + b * nt + t]
                        + th[o["bmt"] + (b * nm + m) * nt + t] + th[o["a"] + a] + th[o["ba"] + b * na + a])
        mean = sum(lw.values()) / max(len(lw), 1)
        return {name: math.exp(v - mean) for name, v in lw.items()}


def _segment_softmax(values: np.ndarray, row_of: np.ndarray, n_rows: int, starts: np.ndarray) -> np.ndarray:
    """softmax of `values` within each row's contiguous run of entries."""
    row_max = np.maximum.reduceat(values, starts)
    ex = np.exp(values - row_max[row_of])
    tot = np.bincount(row_of, weights=ex, minlength=n_rows)
    return ex / tot[row_of]


def pooled(ds: Dataset, log_w: np.ndarray, starts: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(p (R,3), z (R,3) masked-pooled log-probs, pi (E,)) for per-entry log weights."""
    pi = _segment_softmax(log_w, ds.row_of, ds.n_rows, ds.row_starts if starts is None else starts)
    z = np.zeros((ds.n_rows, 3))
    for k in range(3):
        z[:, k] = np.bincount(ds.row_of, weights=pi * ds.log_p[:, k], minlength=ds.n_rows)
    zm = np.where(ds.mask, z, -np.inf)
    zm = zm - zm.max(axis=1, keepdims=True)
    p = np.exp(zm)
    p = p / p.sum(axis=1, keepdims=True)
    return p, z, pi


def cross_entropy(p: np.ndarray, target: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Per-row  -sum_k T_k log p_k  over the unmasked outcomes."""
    return -np.where(mask, target * np.log(_clip(p)), 0.0).sum(axis=1)


def objective(theta: np.ndarray, model: WeightModel, ds: Dataset, lam: float,
              design: Any = None, starts: np.ndarray | None = None) -> tuple[float, np.ndarray]:
    """Mean cross-entropy to the target plus lam * |theta|^2, and its gradient."""
    A = model.design(ds) if design is None else design
    p, z, pi = pooled(ds, A @ theta, starts)
    n = ds.n_rows
    loss = float(cross_entropy(p, ds.target, ds.mask).mean()) + lam * float(theta @ theta)
    resid = np.where(ds.mask, p - ds.target, 0.0)                      # dCE/dz, (R,3)
    g = (resid[ds.row_of] * ds.log_p).sum(axis=1)                       # (E,)
    gbar = (resid * np.where(ds.mask, z, 0.0)).sum(axis=1)              # sum_e pi_e g_e, (R,)
    d_logw = pi * (g - gbar[ds.row_of]) / n
    return loss, 2.0 * lam * theta + A.T @ d_logw


def fit(model: WeightModel, ds: Dataset, lam: float, *, max_iter: int = 300, warm: np.ndarray | None = None) -> dict:
    """L-BFGS on `objective`; sets model.theta. Returns {'loss', 'iters', 'converged'}."""
    from scipy.optimize import minimize

    A, starts = model.design(ds), ds.row_starts
    x0 = np.zeros(model.n_params) if warm is None else np.asarray(warm, dtype=float).copy()
    res = minimize(objective, x0, args=(model, ds, lam, A, starts), jac=True, method="L-BFGS-B",
                   options={"maxiter": max_iter, "gtol": 1e-10, "ftol": 1e-13})
    model.theta = res.x
    return {"loss": float(res.fun), "iters": int(res.nit), "converged": bool(res.success)}


def predict(model: WeightModel, ds: Dataset) -> tuple[np.ndarray, np.ndarray]:
    """(p (R,3), pi (E,)) under the model's current weights."""
    p, _, pi = pooled(ds, model.log_weights(ds))
    return p, pi


# ----------------------------------------------------------------------------- sigma_fair


def dispersion_var(ds: Dataset, pi: np.ndarray, p: np.ndarray) -> np.ndarray:
    """(R,3): D^2 * sum pi^2 per outcome on the one-vs-rest logit scale -- the independent-books variance."""
    n = ds.n_rows
    sum_pi2 = np.bincount(ds.row_of, weights=pi * pi, minlength=n)
    out = np.zeros((n, 3))
    for k in range(3):
        lp_k = ds.log_p[:, k]
        book_logit = lp_k - np.log1p(-np.clip(np.exp(lp_k), P_CLIP, 1 - P_CLIP))
        pool_logit = logit(p[:, k])
        d2 = np.bincount(ds.row_of, weights=pi * (book_logit - pool_logit[ds.row_of]) ** 2, minlength=n)
        out[:, k] = np.where(ds.mask[:, k], d2 * sum_pi2, 0.0)
    return out


def scored_outcomes(mask: np.ndarray) -> np.ndarray:
    """Which outcomes carry a sigma check: outcome 0 of a two-way line (the other is its mirror), all of a 3-way."""
    k = mask.sum(axis=1)
    out = mask.copy()
    out[k == 2, 1] = False
    return out


def fit_residual_var(ds: Dataset, p: np.ndarray, pi: np.ndarray) -> dict[tuple[int, int], float]:
    """r^2 per (mfam, tts): mean over scored outcomes of (logit T - logit p)^2 - dispersion, floored at 0."""
    disp = dispersion_var(ds, pi, p)
    sq = (logit(ds.target) - logit(p)) ** 2
    use = scored_outcomes(ds.mask)
    out: dict[tuple[int, int], float] = {}
    for m in range(len(MARKET_FAMILIES)):
        for t in range(len(TTS_BUCKETS)):
            cell = (ds.mfam == m) & (ds.tts == t)
            sel = use & cell[:, None]
            if sel.any():
                out[(m, t)] = max(0.0, float((sq[sel] - disp[sel]).mean()))
    return out


def sigma_fair(ds: Dataset, p: np.ndarray, pi: np.ndarray, r2: Mapping[tuple[int, int], float]) -> np.ndarray:
    """(R,3) sigma on the logit scale; a cell with no fitted residual takes the largest fitted one (wider, not
    narrower, when unmeasured)."""
    fallback = max(r2.values()) if r2 else 0.0
    cell_r2 = np.array([r2.get((int(m), int(t)), fallback) for m, t in zip(ds.mfam, ds.tts)])
    return np.sqrt(dispersion_var(ds, pi, p) + cell_r2[:, None]) * ds.mask


def sigma_coverage(ds: Dataset, p: np.ndarray, sigma: np.ndarray, k_sigma: float = 1.0) -> tuple[int, int]:
    """(inside, scored): closes whose logit lies within k_sigma * sigma of the fair's logit."""
    use = scored_outcomes(ds.mask)
    inside = np.abs(logit(ds.target) - logit(p)) <= k_sigma * sigma
    return int((inside & use).sum()), int(use.sum())
