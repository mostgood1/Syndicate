"""Analysis half of the Layer 2 score backtest: does a higher score win more, and what ranks better?

Reads the graded rows `score_ranking_backtest.py pull` writes (one row per priced side, its
outcome beside the fields the ranking is made of). Pure functions, no network.

THE UNIT IS THE GAME for every interval. Rows inside one game share one final score -- an
alternate-line ladder is ten rows and one outcome -- and row-level inference was measured to
inflate significance ~7x in this repo (+21 sigma by row, +2.9 by game;
`findings_2026-09-08_bucket_realised_performance.md`). So the bootstrap resamples GAMES.

HIT RATE IS REPORTED AGAINST BREAK-EVEN, never alone. A +300 bet that hits 30% of the time
is a winner and a -300 bet that hits 70% is a loser; ranking for a raw hit rate would select
favourites, not value. `hit - be` (break-even = 1 / decimal price) is the hit rate that pays.
"""

from __future__ import annotations

import collections
import math
import random
from typing import Any, Callable, Iterable, Mapping, Sequence

SEED = 20260921
EXCHANGE_BOOKS = frozenset({"prophetx", "novig", "kalshi", "polymarket", "sporttrade"})
# The served shortlist drops any row whose implied book total is under 95% (`select_shortlist`
# gate 4), which is exactly ev_pct > 1/0.95 - 1 = 5.263%.
SERVED_EV_CEILING = 100.0 * (1.0 / 0.95 - 1.0)
# `portfolio_commit` refuses ev_pct < 2.0 (`DEFAULT_MIN_EV_PCT`).
BET_EV_FLOOR = 2.0


def decimal_odds(american: float) -> float:
    return 1.0 + (american / 100.0 if american > 0 else 100.0 / abs(american))


def break_even(american: float) -> float:
    return 1.0 / decimal_odds(american)


def usable(row: Mapping[str, Any]) -> bool:
    return row.get("px") not in (None, 0) and row.get("y") is not None and row.get("pnl") is not None


def served_equivalent(row: Mapping[str, Any]) -> bool:
    """A row that could have ranked on the served board: opportunity lane, scored, under the
    implausible-book ceiling. The recorder writes every lane; the board serves one."""
    ev = row.get("ev")
    return (row.get("ln") in (None, "opportunity") and row.get("sc") is not None
            and ev is not None and ev <= SERVED_EV_CEILING)


def bet_window(row: Mapping[str, Any]) -> bool:
    ev = row.get("ev")
    return served_equivalent(row) and ev is not None and ev >= BET_EV_FLOOR


# ---------------------------------------------------------------------------
# statistics
# ---------------------------------------------------------------------------


def summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"n": 0}
    n = len(rows)
    hit = sum(r["y"] for r in rows) / n
    be = sum(break_even(r["px"]) for r in rows) / n
    roi = sum(r["pnl"] for r in rows) / n
    evs = [r["ev"] for r in rows if r.get("ev") is not None]
    return {
        "n": n,
        "games": len({r["game"] for r in rows}),
        "dates": len({r["date"] for r in rows}),
        "hit": hit,
        "be": be,
        "hit_minus_be": hit - be,
        "roi": roi,
        "stated_ev": (sum(evs) / len(evs) / 100.0) if evs else None,
        "median_px": sorted(r["px"] for r in rows)[n // 2],
    }


def game_bootstrap(rows: Sequence[Mapping[str, Any]], metric: Callable[[Sequence[Mapping[str, Any]]], float],
                   *, resamples: int = 1000, seed: int = SEED) -> tuple[float, float] | None:
    """95% interval of `metric` with GAMES resampled (all of a game's rows travel together)."""
    by_game: dict[str, list[Mapping[str, Any]]] = collections.defaultdict(list)
    for row in rows:
        by_game[row["game"]].append(row)
    games = list(by_game.values())
    if len(games) < 5:
        return None
    rng = random.Random(seed)
    values = []
    for _ in range(resamples):
        sample: list[Mapping[str, Any]] = []
        for _ in range(len(games)):
            sample.extend(games[rng.randrange(len(games))])
        values.append(metric(sample))
    values.sort()
    return values[int(0.025 * resamples)], values[int(0.975 * resamples) - 1]


def roi_of(rows: Sequence[Mapping[str, Any]]) -> float:
    return sum(r["pnl"] for r in rows) / len(rows)


def hit_minus_be_of(rows: Sequence[Mapping[str, Any]]) -> float:
    return sum(r["y"] - break_even(r["px"]) for r in rows) / len(rows)


# ---------------------------------------------------------------------------
# row features
# ---------------------------------------------------------------------------


def implied(american: float) -> float:
    return break_even(american)


def book_features(row: Mapping[str, Any]) -> dict[str, Any]:
    """From the openings ledger's `book_prices`: how far the priced book sits from the field."""
    prices = row.get("bp") or {}
    imps = sorted(implied(float(v)) for v in prices.values() if isinstance(v, (int, float)) and v != 0)
    px = row.get("px")
    if not imps or px in (None, 0):
        return {}
    median = imps[len(imps) // 2]
    mine = implied(float(px))
    return {
        "gap_to_median_pp": (median - mine) * 100.0,
        "n_at_or_better": sum(1 for x in imps if x <= mine + 1e-9),
        "n_within_1pp": sum(1 for x in imps if x <= mine + 0.01),
        "n_books": len(imps),
        "exchange": str(row.get("bk") or "").lower() in EXCHANGE_BOOKS,
    }


# ---------------------------------------------------------------------------
# candidate scores -- every one computable from a recorded row
# ---------------------------------------------------------------------------


def score_current(row: Mapping[str, Any]) -> float | None:
    return row.get("sc")


def score_ev(row: Mapping[str, Any]) -> float | None:
    return row.get("ev")


def kelly_growth(p: float, american: float, fraction: float = 0.25) -> float:
    """Expected log-growth (basis points of bankroll) of a `fraction`-Kelly bet at fair `p`.

    The industry's risk-adjusted rank: at equal EV it prefers the likelier outcome, because a
    longshot's variance eats growth. For small edges it is ~ fraction*(2-fraction)/2 * EV^2/(b)
    with b = decimal - 1, i.e. EV squared over the odds -- a longshot needs a much bigger EV to
    rank level with a near-even bet.
    """
    b = decimal_odds(american) - 1.0
    full = (p * (b + 1.0) - 1.0) / b
    if full <= 0:
        return (p * (b + 1.0) - 1.0) * 1e4 * 1e-3  # negative EV: order by EV, far below any positive
    f = fraction * full
    return 1e4 * (p * math.log1p(f * b) + (1.0 - p) * math.log1p(-f))


def score_kelly(row: Mapping[str, Any]) -> float | None:
    p, px = row.get("fp"), row.get("px")
    if p is None or px in (None, 0) or not (0.0 < p < 1.0):
        return None
    return kelly_growth(p, px)


def fair_sigma(row: Mapping[str, Any]) -> float:
    """A stated prior for the absolute error of the fair probability (probability units).

    Grows with thin consensus, stale quotes and live markets. The coefficients are a PRIOR;
    `fit_realization` below is what replaces them with data.
    """
    bq = row.get("bq") or 1
    sigma = 0.012 + 0.03 / math.sqrt(max(1.0, float(bq)))
    age = row.get("ba")
    if age is not None and age > 3600:
        sigma += 0.01
    if row.get("phase") == "live":
        sigma += 0.02
    if row.get("family") == "game_alt":
        sigma += 0.01
    return sigma


def score_lcb(row: Mapping[str, Any], z: float = 1.0) -> float | None:
    """EV at the fair's lower confidence bound: the EV that survives plausible fair error."""
    p, px = row.get("fp"), row.get("px")
    if p is None or px in (None, 0) or not (0.0 < p < 1.0):
        return None
    lower = max(1e-4, p - z * fair_sigma(row))
    return 100.0 * (lower * decimal_odds(px) - 1.0)


def power_from_multiplicative(p_mult: float, overround: float) -> float | None:
    """Re-express a two-way MULTIPLICATIVE fair as the POWER-devig fair of the same market.

    The recorder keeps only the fair, not each book's two prices, so this reconstructs the
    implied pair a typical book would show (q = p * O, 1 - p) * O) and power-devigs it:
    find k with q1**k + q2**k = 1. Power removes more margin from the longshot than
    multiplicative does -- the favourite-longshot bias every de-vig guide names.
    """
    if not (0.0 < p_mult < 1.0) or overround <= 1.0:
        return p_mult
    q1, q2 = p_mult * overround, (1.0 - p_mult) * overround
    if q1 >= 1.0 or q2 >= 1.0:
        return None
    lo, hi = 1.0, 4.0
    for _ in range(60):
        k = (lo + hi) / 2.0
        if q1 ** k + q2 ** k > 1.0:
            lo = k
        else:
            hi = k
    k = (lo + hi) / 2.0
    a, b = q1 ** k, q2 ** k
    return a / (a + b)


KALSHI_BASE_RATE = 0.07
# Series at half rate (venue_fees.py docstring, read live 2026-08-29 / 09-01): MLB game, total,
# spread and the batter-prop series. Everything else this platform trades is 1.0.
POLYMARKET_NOTIONAL_RATE = 0.015


def fee_adjusted_decimal(row: Mapping[str, Any]) -> float | None:
    """The decimal odds a TAKER actually gets after the venue's fee (industry EV is net of fees).

    Kalshi charges 0.07 * m * P * (1 - P) per $1 contract; Polymarket ~1.5% of notional
    (`venue_fees.py`). A +113 Kalshi price at the full rate costs 0.0175 per 0.47 contract --
    3.7% of stake, the whole EV of a typical board row.
    """
    px = row.get("px")
    if px in (None, 0):
        return None
    dec = decimal_odds(float(px))
    book = str(row.get("bk") or "").lower()
    price = 1.0 / dec
    if book == "kalshi":
        half = row.get("sport") == "mlb" and (row.get("family") in ("game_main", "game_alt")
                                               or row.get("family") == "prop")
        fee = KALSHI_BASE_RATE * (0.5 if half else 1.0) * price * (1.0 - price)
        return 1.0 / (price + fee)
    if book == "polymarket":
        return 1.0 / (price * (1.0 + POLYMARKET_NOTIONAL_RATE))
    return dec


def posterior_ev(row: Mapping[str, Any], *, prior_ev: float = -0.02, tau: float = 0.02,
                 sigma_scale: float = 1.0, net_of_fees: bool = True) -> float | None:
    """Empirical-Bayes EV (fraction per unit): the stated EV shrunk toward the market's prior.

    The optimizer's curse, made explicit: the board SELECTS the rows with the largest stated
    EV, and a stated EV is (true EV + fair error * decimal). Selecting the max of noisy
    estimates selects the noise. With a normal prior on true EV (mean `prior_ev`, sd `tau`) and
    estimate noise sd = decimal * sigma_p, the posterior mean is
        prior + w * (stated - prior),   w = tau^2 / (tau^2 + (decimal * sigma_p)^2)
    so a longshot (large decimal), a thin or stale consensus, a live quote or an alternate line
    (large sigma_p) is shrunk hardest -- exactly the rows at the top of today's board.
    """
    p = row.get("fp")
    dec = fee_adjusted_decimal(row) if net_of_fees else (
        decimal_odds(float(row["px"])) if row.get("px") not in (None, 0) else None)
    if p is None or dec is None or not (0.0 < p < 1.0):
        return None
    stated = p * dec - 1.0
    noise = dec * fair_sigma(row) * sigma_scale
    w = tau * tau / (tau * tau + noise * noise)
    return prior_ev + w * (stated - prior_ev)


def _normal_pdf(x: float, sd: float) -> float:
    return math.exp(-0.5 * (x / sd) ** 2) / (sd * math.sqrt(2.0 * math.pi))


def robust_posterior_ev(row: Mapping[str, Any], *, prior_ev: float = -0.02, tau: float = 0.02,
                        sigma_scale: float = 1.0, contamination: float = 0.15,
                        error_sd: float = 0.10, net_of_fees: bool = True) -> float | None:
    """Posterior EV under a CONTAMINATED noise model -- the one that re-descends.

    The plain normal posterior is monotone in stated EV: shrunk, but a bigger stated edge
    still ranks higher. Production says otherwise (paper orders 09-08..09-20: ROI +4.7% at
    stated EV 2-3, -4.4% at 4-5.27, -26.7% above 5.27), because a large stated edge is more
    often a stale / mismatched / thin quote than a large real edge. Model that directly:
        stated = true + e,   e ~ (1-c) N(0, s^2) + c N(0, S^2)
    with s = decimal * sigma_p (ordinary fair error) and S = `error_sd` (a quote that is
    simply wrong). The posterior mean mixes the two component posteriors by their marginal
    likelihoods; far out in the tail the "wrong quote" component wins and the posterior falls
    back toward the prior. That is the standard robust-Bayes answer to the optimizer's curse.
    """
    p = row.get("fp")
    dec = fee_adjusted_decimal(row) if net_of_fees else (
        decimal_odds(float(row["px"])) if row.get("px") not in (None, 0) else None)
    if p is None or dec is None or not (0.0 < p < 1.0):
        return None
    stated = p * dec - 1.0
    s = dec * fair_sigma(row) * sigma_scale
    posts, weights = [], []
    for weight, noise in ((1.0 - contamination, s), (contamination, math.hypot(s, error_sd))):
        total = math.sqrt(tau * tau + noise * noise)
        weights.append(weight * _normal_pdf(stated - prior_ev, total))
        posts.append(prior_ev + (tau * tau / (tau * tau + noise * noise)) * (stated - prior_ev))
    norm = sum(weights)
    if norm <= 0:
        return prior_ev
    return sum(w * m for w, m in zip(weights, posts)) / norm


def score_robust_ev(row: Mapping[str, Any]) -> float | None:
    value = robust_posterior_ev(row)
    return None if value is None else 100.0 * value


def score_posterior_ev(row: Mapping[str, Any]) -> float | None:
    value = posterior_ev(row)
    return None if value is None else 100.0 * value


def score_posterior_kelly(row: Mapping[str, Any]) -> float | None:
    """Kelly growth at the POSTERIOR probability: shrink first, then risk-adjust."""
    post = posterior_ev(row)
    dec = fee_adjusted_decimal(row)
    if post is None or dec is None:
        return None
    p_post = min(0.999, max(0.001, (1.0 + post) / dec))
    b = dec - 1.0
    full = (p_post * dec - 1.0) / b
    if full <= 0:
        return (p_post * dec - 1.0) * 10.0
    f = 0.25 * full
    return 1e4 * (p_post * math.log1p(f * b) + (1.0 - p_post) * math.log1p(-f))


# ---------------------------------------------------------------------------
# market-efficiency calibration: how much of the price gap is real?
# ---------------------------------------------------------------------------


def _logit(p: float) -> float:
    p = min(1.0 - 1e-6, max(1e-6, p))
    return math.log(p / (1.0 - p))


def efficiency_features(row: Mapping[str, Any]) -> list[float] | None:
    """[1, logit(fair), gap<0, gap>0, gap>2pp-logit] with gap = logit(fair) - logit(price implied).

    If our fair were the truth, the outcome would depend on logit(fair) alone (coefficient 1)
    and the gap terms would be 0. If the OFFERED price were the truth -- the book that looks
    generous actually knows something, or its quote is simply stale -- the gap coefficient
    goes to -1. So `1 + coef(gap>0)` is the REALIZATION FRACTION of a positive stated edge,
    and the third term lets a large gap realize differently from a small one (the winner's
    curse lives in the tail).
    """
    p, px = row.get("fp"), row.get("px")
    if p is None or px in (None, 0) or not (0.0 < p < 1.0):
        return None
    gap = _logit(p) - _logit(break_even(float(px)))
    return [1.0, _logit(p), min(gap, 0.0), max(gap, 0.0), max(gap - 0.08, 0.0)]


def fit_logistic(xs: Sequence[Sequence[float]], ys: Sequence[float], *, l2: float = 1.0,
                 prior: Sequence[float] | None = None, iterations: int = 50) -> list[float]:
    """Ridge logistic regression by IRLS, shrunk toward `prior` (default: the 'fair is right'
    coefficients [0, 1, 0, 0, 0]) rather than toward zero -- with thin buckets the honest
    fallback is 'trust the de-vig', not 'predict 50%'."""
    import numpy as np

    X = np.asarray(xs, dtype=float)
    y = np.asarray(ys, dtype=float)
    k = X.shape[1]
    beta0 = np.asarray(prior if prior is not None else [0.0, 1.0] + [0.0] * (k - 2), dtype=float)
    beta = beta0.copy()
    penalty = l2 * np.eye(k)
    penalty[0, 0] = l2 * 1e-3
    for _ in range(iterations):
        eta = np.clip(X @ beta, -30, 30)
        mu = 1.0 / (1.0 + np.exp(-eta))
        w = mu * (1.0 - mu) + 1e-9
        grad = X.T @ (y - mu) - penalty @ (beta - beta0)
        hess = (X * w[:, None]).T @ X + penalty
        step = np.linalg.solve(hess, grad)
        beta = beta + step
        if float(np.max(np.abs(step))) < 1e-8:
            break
    return [float(b) for b in beta]


def predict_logistic(beta: Sequence[float], x: Sequence[float]) -> float:
    eta = sum(b * v for b, v in zip(beta, x))
    eta = max(-30.0, min(30.0, eta))
    return 1.0 / (1.0 + math.exp(-eta))


def log_loss(rows_and_probs: Iterable[tuple[Mapping[str, Any], float]]) -> float:
    total, n = 0.0, 0
    for row, p in rows_and_probs:
        p = min(1 - 1e-6, max(1e-6, p))
        total += -(row["y"] * math.log(p) + (1 - row["y"]) * math.log(1 - p))
        n += 1
    return total / max(n, 1)


def game_weights(rows: Sequence[Mapping[str, Any]]) -> list[float]:
    """1 / (rows in the game): each GAME carries equal weight in a fit, so a 40-rung ladder on
    one final score cannot outvote 40 independent games."""
    counts = collections.Counter(r["game"] for r in rows)
    return [1.0 / counts[r["game"]] for r in rows]


def fit_weighted_logistic(rows: Sequence[Mapping[str, Any]], *, l2: float = 1.0) -> list[float] | None:
    feats = [(efficiency_features(r), r) for r in rows]
    feats = [(x, r) for x, r in feats if x is not None]
    if len(feats) < 50:
        return None
    import numpy as np

    X = np.asarray([x for x, _ in feats], dtype=float)
    y = np.asarray([r["y"] for _, r in feats], dtype=float)
    wts = np.asarray(game_weights([r for _, r in feats]), dtype=float)
    k = X.shape[1]
    beta0 = np.asarray([0.0, 1.0] + [0.0] * (k - 2))
    beta = beta0.copy()
    penalty = l2 * np.eye(k)
    penalty[0, 0] = l2 * 1e-3
    for _ in range(60):
        eta = np.clip(X @ beta, -30, 30)
        mu = 1.0 / (1.0 + np.exp(-eta))
        w = wts * (mu * (1.0 - mu) + 1e-9)
        grad = X.T @ (wts * (y - mu)) - penalty @ (beta - beta0)
        hess = (X * w[:, None]).T @ X + penalty
        step = np.linalg.solve(hess, grad)
        beta = beta + step
        if float(np.max(np.abs(step))) < 1e-8:
            break
    return [float(b) for b in beta]


def calibrated_probability(row: Mapping[str, Any], beta: Sequence[float]) -> float | None:
    x = efficiency_features(row)
    return None if x is None else predict_logistic(beta, x)


# ---------------------------------------------------------------------------
# tables
# ---------------------------------------------------------------------------


def deciles(rows: Sequence[Mapping[str, Any]], key: Callable[[Mapping[str, Any]], float | None], k: int = 10
            ) -> list[dict[str, Any]]:
    scored = [(key(r), r) for r in rows]
    scored = [(s, r) for s, r in scored if s is not None]
    scored.sort(key=lambda item: -item[0])
    n = len(scored)
    out = []
    for i in range(k):
        chunk = scored[i * n // k:(i + 1) * n // k]
        if not chunk:
            continue
        seg = [r for _, r in chunk]
        summary = summarize(seg)
        summary.update({"decile": i + 1, "score_hi": chunk[0][0], "score_lo": chunk[-1][0]})
        out.append(summary)
    return out


def top_k_per_date(rows: Sequence[Mapping[str, Any]], key: Callable[[Mapping[str, Any]], float | None],
                   k: int, *, group: Callable[[Mapping[str, Any]], Any] = lambda r: r["date"],
                   per_game: int | None = None) -> list[Mapping[str, Any]]:
    """The top `k` rows by `key` within each group (default: each date), optionally at most
    `per_game` per game -- the shape of a board a bettor actually reads."""
    groups: dict[Any, list[tuple[float, Mapping[str, Any]]]] = collections.defaultdict(list)
    for row in rows:
        value = key(row)
        if value is not None:
            groups[group(row)].append((value, row))
    picked: list[Mapping[str, Any]] = []
    for items in groups.values():
        items.sort(key=lambda item: -item[0])
        per: collections.Counter = collections.Counter()
        taken = 0
        for _, row in items:
            if taken >= k:
                break
            if per_game is not None and per[row["game"]] >= per_game:
                continue
            per[row["game"]] += 1
            picked.append(row)
            taken += 1
    return picked


def fmt(summary: Mapping[str, Any], ci: tuple[float, float] | None = None) -> str:
    if not summary.get("n"):
        return "n=0"
    stated = summary.get("stated_ev")
    text = (f"n={summary['n']:>5} g={summary['games']:>4} d={summary['dates']} "
            f"hit={summary['hit']:.3f} be={summary['be']:.3f} hit-be={summary['hit_minus_be']:+.3f} "
            f"roi={summary['roi']:+.3f} ev={'' if stated is None else f'{stated:+.3f}'} px~{summary['median_px']:+.0f}")
    if ci:
        text += f" roiCI[{ci[0]:+.3f},{ci[1]:+.3f}]"
    return text
