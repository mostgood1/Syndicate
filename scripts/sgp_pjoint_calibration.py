#!/usr/bin/env python
"""Is the SGP builders' `p_joint` calibrated on the settled paper ledger? (lane `sgp-pjoint-calibration`, 2026-10-27)

Pre-registered `1e7793e3` (`.syndicate/findings_2026-10-27_sgp_pjoint_calibration_preregistration.md`); amendment A1
is committed with this code, before the run. OFFLINE: it reads a SNAPSHOT of the fleet's
`cheatsheets/<sport>/sgp_{ledger,graded}.jsonl` and `<sport>_source/sgp/*_sgp_correlations.json`, copied read-only to
`<snap>/<sport>/`. Nothing on the fleet is written.

  py -3 scripts/sgp_pjoint_calibration.py --snap C:/tmp/sgpcal/snap --out C:/tmp/sgpcal/report.json

What it does, by prereg section:
  §2  CLEAN population (status won/lost AND every leg won/lost) as primary; the grader's as-graded population beside it.
      The grader's rule lets a void-leg ticket LOSE but never WIN, so as-graded censors toward a lower hit rate.
  §3  CITL = mean(p_joint) - mean(y), game-clustered (the uncentered `grade_sgp_paper.summarize` SE), Holm over
      {pooled, NHL, NBA, NFL}; a cluster bootstrap beside it; MDE80 = 2.80 x SE for a null.
  §4  logistic recalibration slope / offset intercept, game-clustered sandwich (secondary).
  §5  breakdowns.
  §6  decomposition: ticket arms A (market x independence), B (posterior x independence), C (p_joint); unique legs;
      unique pairs re-priced by the builders' own `rho_for` / `joint_prob`; the attribution rule.
  §7  per-leg / per-pair corrections, leave-one-date-out, re-checked on the served hit-rate family.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.nfl import sgp as core  # noqa: E402

SPORTS = ("nhl", "nba", "nfl", "wnba", "mlb")
GATED = ("nhl", "nba", "nfl")                  # >= 20 settled games each (prereg §3)
FREEZE = "2026-10-26"                          # last ticket date in the test
SEEN_LAST = "2026-10-25"                       # the E4 lead saw tickets through this date
SEED = 20261027
N_BOOT = 2000
ALPHA = 0.05
Z = 1.959963984540054
K_GRID = (10.0, 20.0, 40.0, 80.0, 160.0, 320.0, math.inf)
K_NOW = 40.0                                   # cheat_sheets.PRIOR_STRENGTH at the ledger's build time
LAMBDA_GRID = tuple(round(0.1 * i, 1) for i in range(11))
BANDS = (0.55, 0.65, 0.75, 0.80, 0.85, 0.90, 0.95)
CELLS_FILE = "{sport}_sgp_correlations.json"
BASKETBALL = ("nba", "wnba")
EPS = 1e-6


# ----------------------------------------------------------------------------- reading
def read_jsonl(path: Path) -> list[dict[str, Any]]:
    out = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def side_prob(p_over: Any, side: Any) -> float | None:
    """The leg's own side: P(over) for over / yes, 1 - P(over) for under (prereg §10)."""
    try:
        p = float(p_over)
    except (TypeError, ValueError):
        return None
    return p if str(side or "").lower() in ("over", "yes") else 1.0 - p


def _f(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def leg_identity(sport: str, date: str, event_id: Any, leg: Mapping[str, Any]) -> tuple:
    return (sport, date, str(event_id), str(leg.get("player")), str(leg.get("market")), str(leg.get("side")).lower(),
            _f(leg.get("line")))


def build_tickets(sport: str, ledger_rows: Iterable[Mapping[str, Any]], graded_rows: Iterable[Mapping[str, Any]],
                  freeze: str = FREEZE) -> tuple[list[dict[str, Any]], Counter]:
    """Every graded ticket dated <= `freeze`, joined to its FIRST ledger record by `sgp_id`, with each leg's market
    (`m`), posterior (`q`) and result. `clean` / `as_graded` mark the two populations (prereg §2)."""
    counts: Counter = Counter()
    ledger: dict[str, Mapping[str, Any]] = {}
    for r in ledger_rows:
        counts["ledger_rows"] += 1
        ledger.setdefault(str(r.get("sgp_id")), r)
    out = []
    for g in graded_rows:
        L = ledger.get(str(g.get("sgp_id")))
        if L is None:
            counts["graded_not_in_ledger"] += 1
            continue
        date = str(L.get("date") or g.get("date") or "")
        if not date or date > freeze:
            counts["after_freeze"] += 1
            continue
        status = str(g.get("status") or "")
        counts[f"status_{status}"] += 1
        pj = _f(L.get("p_joint"))
        if pj is not None and _f(g.get("p_joint")) is not None and abs(pj - float(g["p_joint"])) > 1e-9:
            counts["p_joint_graded_differs"] += 1
        res_by_bet: dict[str, list[str]] = defaultdict(list)
        for gl in g.get("legs") or []:
            res_by_bet[str(gl.get("bet"))].append(str(gl.get("result")))
        legs = []
        gl_list = list(g.get("legs") or [])
        for i, leg in enumerate(L.get("legs") or []):
            bet = str(leg.get("bet"))
            if res_by_bet.get(bet):
                result = res_by_bet[bet].pop(0)
            elif i < len(gl_list):
                result = str(gl_list[i].get("result"))
                counts["leg_matched_by_order"] += 1
            else:
                result = "missing"
                counts["leg_result_missing"] += 1
            legs.append({"bet": bet, "result": result, "m": _f(leg.get("p_market")), "q": side_prob(leg.get("p_over"), leg.get("side")),
                         "p_over": _f(leg.get("p_over")), "side": str(leg.get("side") or "").lower(), "line": _f(leg.get("line")),
                         "market": leg.get("market"), "role": leg.get("role") or "UNK", "player": leg.get("player"),
                         "team": leg.get("team"), "alt": bool(leg.get("alt")), "hits": leg.get("hits"), "games": leg.get("games"),
                         "id": leg_identity(sport, date, L.get("event_id"), leg)})
        as_graded = status in ("won", "lost") and pj is not None
        clean = as_graded and bool(legs) and all(x["result"] in ("won", "lost") for x in legs)
        out.append({"sport": sport, "sgp_id": str(L.get("sgp_id")), "date": date, "event_id": str(L.get("event_id")),
                    "game": f"{sport}|{L.get('event_id')}", "status": status, "y": 1.0 if status == "won" else 0.0,
                    "p_joint": pj, "p_independent": _f(L.get("p_independent")), "family": L.get("family") or "none",
                    "tier": L.get("tier") or "none", "relation": L.get("relation") or "none", "size": len(legs),
                    "same_player": bool(L.get("same_player")), "legs": legs, "as_graded": as_graded, "clean": clean})
        counts["as_graded"] += as_graded
        counts["clean"] += clean
    return out, counts


# ----------------------------------------------------------------------------- statistics
def _cluster_sums(values: np.ndarray, clusters: Sequence[str]) -> tuple[np.ndarray, np.ndarray, list[str]]:
    keys = sorted(set(clusters))
    pos = {k: i for i, k in enumerate(keys)}
    idx = np.array([pos[c] for c in clusters], dtype=int)
    s = np.zeros((len(keys),) + values.shape[1:])
    np.add.at(s, idx, values)
    n = np.bincount(idx, minlength=len(keys)).astype(float)
    return s, n, keys


def cr1_se(d: np.ndarray, clusters: Sequence[str], *, center: bool = True) -> float:
    """sqrt(G/(G-1) * sum_g (sum_{i in g} r_i)^2) / n, r = d - mean(d) (centered) or d itself (the registered §3 form,
    = grade_sgp_paper.summarize)."""
    d = np.asarray(d, dtype=float)
    n = len(d)
    if n == 0:
        return float("nan")
    r = d - d.mean() if center else d
    s, _n, keys = _cluster_sums(r, clusters)
    G = len(keys)
    if G < 2:
        return float("nan")
    return float(math.sqrt(G / (G - 1) * float((s ** 2).sum())) / n)


def _p_two(z: float) -> float:
    return float(math.erfc(abs(z) / math.sqrt(2.0))) if math.isfinite(z) else float("nan")


def boot_ratio_ci(num: np.ndarray, den: np.ndarray, clusters: Sequence[str], *, seed: int = SEED, b: int = N_BOOT) -> list[float]:
    """Percentile CI of sum(num) / sum(den) under a game-cluster bootstrap. `num` may be (n, k): then the CI of each column's ratio."""
    num = np.asarray(num, dtype=float)
    den = np.asarray(den, dtype=float)
    sn, _n, keys = _cluster_sums(num, clusters)
    sd, _n2, _k = _cluster_sums(den, clusters)
    G = len(keys)
    if G < 2:
        return [float("nan"), float("nan")]
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, G, size=(b, G))
    tot_n = sn[idx].sum(axis=1)
    tot_d = sd[idx].sum(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        stat = tot_n / tot_d
    lo, hi = np.nanpercentile(stat, [2.5, 97.5], axis=0)
    return [round(float(lo), 5), round(float(hi), 5)] if np.ndim(lo) == 0 else [[round(float(a), 5), round(float(c), 5)] for a, c in zip(lo, hi)]


def citl(p: Sequence[float], y: Sequence[float], clusters: Sequence[str], *, boot: bool = True) -> dict[str, Any]:
    """§3: mean(p) - mean(y), positive = over-prediction, with the registered (uncentered) game-clustered SE."""
    p = np.asarray(p, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(p)
    if n == 0:
        return {"n": 0}
    d = p - y
    se = cr1_se(d, clusters, center=False)
    est = float(d.mean())
    out = {"n": n, "games": len(set(clusters)), "mean_p": round(float(p.mean()), 4), "hit_rate": round(float(y.mean()), 4),
           "citl": round(est, 4), "se": round(se, 4), "ci": [round(est - Z * se, 4), round(est + Z * se, 4)],
           "p_two_sided": _p_two(est / se) if se and se > 0 else float("nan"), "mde80": round(2.80 * se, 4)}
    if boot:
        out["boot_ci"] = boot_ratio_ci(d, np.ones(n), clusters)
    return out


def paired(d: Sequence[float], clusters: Sequence[str], *, digits: int = 5) -> dict[str, Any]:
    """Mean of a per-unit difference with a centered CR1 game-clustered CI (prereg A1: §6 uses the centered form)."""
    d = np.asarray(d, dtype=float)
    if len(d) == 0:
        return {"n": 0}
    se = cr1_se(d, clusters, center=True)
    est = float(d.mean())
    return {"n": len(d), "games": len(set(clusters)), "mean": round(est, digits), "se": round(se, digits),
            "ci": [round(est - Z * se, digits), round(est + Z * se, digits)],
            "p_two_sided": _p_two(est / se) if se and se > 0 else float("nan")}


def holm(pvals: Mapping[str, float], alpha: float = ALPHA) -> dict[str, dict[str, Any]]:
    keys = sorted(pvals, key=lambda k: (pvals[k] if math.isfinite(pvals[k]) else 1.0))
    m = len(keys)
    out, running, still = {}, 0.0, True
    for i, k in enumerate(keys):
        p = pvals[k] if math.isfinite(pvals[k]) else 1.0
        adj = min(1.0, max(running, (m - i) * p))
        running = adj
        still = still and p <= alpha / (m - i)
        out[k] = {"p": p, "p_holm": adj, "reject": bool(still)}
    return out


def logit(p: Any) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS)
    return np.log(p / (1 - p))


def logistic_fit(y: Sequence[float], X: np.ndarray, clusters: Sequence[str], offset: Any = None,
                 iters: int = 50) -> dict[str, Any]:
    """IRLS logistic regression with a game-clustered sandwich covariance (G/(G-1) small-sample factor)."""
    y = np.asarray(y, dtype=float)
    X = np.asarray(X, dtype=float)
    off = np.zeros(len(y)) if offset is None else np.asarray(offset, dtype=float)
    beta = np.zeros(X.shape[1])
    for _ in range(iters):
        mu = 1 / (1 + np.exp(-(X @ beta + off)))
        W = np.clip(mu * (1 - mu), 1e-9, None)
        H = X.T @ (W[:, None] * X)
        step = np.linalg.solve(H, X.T @ (y - mu))
        beta = beta + step
        if np.max(np.abs(step)) < 1e-10:
            break
    mu = 1 / (1 + np.exp(-(X @ beta + off)))
    bread = np.linalg.inv(X.T @ ((mu * (1 - mu))[:, None] * X))
    scores, _n, keys = _cluster_sums(X * (y - mu)[:, None], clusters)
    G = len(keys)
    meat = scores.T @ scores
    V = (G / (G - 1)) * bread @ meat @ bread if G > 1 else bread
    se = np.sqrt(np.diag(V))
    return {"coef": [round(float(b), 4) for b in beta], "se": [round(float(s), 4) for s in se],
            "ci": [[round(float(b - Z * s), 4), round(float(b + Z * s), 4)] for b, s in zip(beta, se)], "n": len(y), "games": G}


def recal(p: Sequence[float], y: Sequence[float], clusters: Sequence[str]) -> dict[str, Any]:
    """§4: slope b in logit P(y) = a + b logit(p) (tested vs 1), and a0 in logit P(y) = a0 + offset(logit p)."""
    lp = logit(p)
    if len(lp) < 10 or len(set(clusters)) < 3:
        return {"n": len(lp)}
    full = logistic_fit(y, np.column_stack([np.ones(len(lp)), lp]), clusters)
    off = logistic_fit(y, np.ones((len(lp), 1)), clusters, offset=lp)
    b, se_b = full["coef"][1], full["se"][1]
    return {"n": len(lp), "games": full["games"], "a": full["coef"][0], "b": b, "b_ci": full["ci"][1],
            "b_vs_1_p": _p_two((b - 1) / se_b) if se_b else float("nan"), "a0_offset": off["coef"][0], "a0_ci": off["ci"][0]}


def ll(p: Any, y: Any) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS)
    y = np.asarray(y, dtype=float)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


# ----------------------------------------------------------------------------- copula reconstruction (§6c)
def _type(sport: str, leg: Mapping[str, Any]) -> str:
    market = str(leg.get("market") or "")
    if sport in BASKETBALL:
        from syndicate.features.shared.basketball_sgp_pool import SHEET_TO_CODE

        market = SHEET_TO_CODE.get(market, market)
    return f"{market}|{leg.get('role') or 'UNK'}"


def core_leg(sport: str, leg: Mapping[str, Any], p_side: float | None = None) -> dict[str, Any]:
    """The builders' leg shape (`nfl.sgp` docstring) at a chosen side probability (default: the ledger's own `q`)."""
    q = leg["q"] if p_side is None else p_side
    q = min(max(float(q), EPS), 1 - EPS)
    over = leg["side"] in ("over", "yes")
    return {"player": leg.get("player"), "team": leg.get("team"), "market": leg.get("market"), "side": leg["side"] or "over",
            "p_over": q if over else 1.0 - q, "p_side": q, "type": _type(sport, leg)}


def scale_cells(cells: Mapping[str, Any], lam: float) -> dict[str, Any]:
    """The correlations file with every cell's rho multiplied by `lam` (§7 copula candidate)."""
    out = copy.deepcopy(dict(cells))
    for level in ("type", "market"):
        for cell in ((out.get("cells") or {}).get(level) or {}).values():
            if isinstance(cell, dict) and cell.get("rho") is not None:
                cell["rho"] = float(cell["rho"]) * lam
    return out


def price_tickets(sport: str, tickets: Sequence[Mapping[str, Any]], cells: Mapping[str, Any],
                  side_probs: Callable[[Mapping[str, Any], Mapping[str, Any]], float] | None = None) -> np.ndarray:
    """P(every leg wins) for each ticket via `nfl.sgp.ticket_joints` (exact for 2 legs, the builders' QMC for 3+)."""
    out = np.full(len(tickets), np.nan)
    by_size: dict[int, list[int]] = defaultdict(list)
    for i, t in enumerate(tickets):
        if t["legs"] and all(x["q"] is not None for x in t["legs"]):
            by_size[len(t["legs"])].append(i)
    for _k, idx in by_size.items():
        legsets = [[core_leg(sport, x, side_probs(tickets[i], x) if side_probs else None) for x in tickets[i]["legs"]] for i in idx]
        pj, _lv = core.ticket_joints(legsets, cells, core.relation_of)
        out[idx] = pj
    return out


def reconstruct(sport: str, tickets: Sequence[Mapping[str, Any]], cells: Mapping[str, Any] | None) -> dict[str, Any]:
    """§6c gate: the ledger's p_joint re-priced from its own legs; <= 0.002 (2 legs) / 0.01 (3+) on >= 95%."""
    if not cells:
        return {"ok": False, "reason": "no correlations file", "n": len(tickets)}
    rep = price_tickets(sport, tickets, cells)
    pj = np.array([t["p_joint"] if t["p_joint"] is not None else np.nan for t in tickets])
    tol = np.array([0.002 if t["size"] == 2 else 0.01 for t in tickets])
    good = np.abs(rep - pj) <= tol
    n = int(np.isfinite(rep).sum())
    frac = float(good.sum() / len(tickets)) if len(tickets) else float("nan")
    by_date: dict[str, list[bool]] = defaultdict(list)
    for t, g in zip(tickets, good):
        by_date[t["date"]].append(bool(g))
    return {"ok": bool(frac >= 0.95), "n": len(tickets), "priced": n, "reproduced": int(good.sum()), "frac": round(frac, 4),
            "max_abs_err": round(float(np.nanmax(np.abs(rep - pj))), 5) if n else None,
            "frac_by_date": {d: round(sum(v) / len(v), 3) for d, v in sorted(by_date.items())},
            "_good": good.tolist(), "_rep": rep.tolist()}


def pair_rows(sport: str, tickets: Sequence[Mapping[str, Any]], cells: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Unique within-ticket leg pairs with both legs won/lost, each with its signed copula rho (§6c)."""
    seen, out = set(), []
    for t in tickets:
        legs = t["legs"]
        for i in range(len(legs)):
            for j in range(i + 1, len(legs)):
                a, b = legs[i], legs[j]
                if a["result"] not in ("won", "lost") or b["result"] not in ("won", "lost") or a["m"] is None or b["m"] is None:
                    continue
                key = (t["game"], t["date"], frozenset({a["id"], b["id"]}))
                if key in seen:
                    continue
                seen.add(key)
                ca, cb = core_leg(sport, a), core_leg(sport, b)
                rel = core.relation_of(ca, cb)
                rho, level = core.rho_for(cells, ca["type"], cb["type"], rel)
                out.append({"game": t["game"], "date": t["date"], "relation": rel, "rho": float(rho), "level": level,
                            "a": a, "b": b, "ya": 1.0 if a["result"] == "won" else 0.0, "yb": 1.0 if b["result"] == "won" else 0.0})
    return out


def pair_joint(r: Mapping[str, Any], pa: float, pb: float, rho: float) -> float:
    """P(both legs' sides win) at side probabilities pa, pb under the builders' copula (`nfl.sgp.joint_prob`)."""
    A, B = dict(core_leg("x", r["a"], pa)), dict(core_leg("x", r["b"], pb))
    return float(core.joint_prob(A, B, rho))


def four_cell_ll(pa: float, pb: float, p11: float, ya: float, yb: float) -> float:
    cells = {(1, 1): p11, (1, 0): pa - p11, (0, 1): pb - p11, (0, 0): 1 - pa - pb + p11}
    return -math.log(max(cells[(int(ya), int(yb))], EPS))


def pair_scores(pairs: Sequence[Mapping[str, Any]], marg: str = "m", lam: float = 1.0) -> dict[str, np.ndarray]:
    pa = np.array([r["a"][marg] for r in pairs], dtype=float)
    pb = np.array([r["b"][marg] for r in pairs], dtype=float)
    pc = np.array([pair_joint(r, a, b, lam * r["rho"]) for r, a, b in zip(pairs, pa, pb)])
    pi = pa * pb
    ya = np.array([r["ya"] for r in pairs])
    yb = np.array([r["yb"] for r in pairs])
    llc = np.array([four_cell_ll(a, b, c, x, z) for a, b, c, x, z in zip(pa, pb, pc, ya, yb)])
    lli = np.array([four_cell_ll(a, b, c, x, z) for a, b, c, x, z in zip(pa, pb, pi, ya, yb)])
    return {"pa": pa, "pb": pb, "pc": pc, "pi": pi, "both": ya * yb, "llc": llc, "lli": lli}


# ----------------------------------------------------------------------------- legs (§6b)
def unique_legs(tickets: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen, out = set(), []
    for t in tickets:
        for leg in t["legs"]:
            if leg["result"] not in ("won", "lost") or leg["id"] in seen:
                continue
            seen.add(leg["id"])
            out.append(dict(leg, game=t["game"], date=t["date"], sport=t["sport"], family=t["family"],
                            y=1.0 if leg["result"] == "won" else 0.0))
    return out


def band(p: float | None) -> str:
    if p is None:
        return "none"
    lo = 0.0
    for edge in BANDS:
        if p < edge:
            return f"{lo:.2f}-{edge:.2f}"
        lo = edge
    return f">={BANDS[-1]:.2f}"


def leg_block(legs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    legs = [x for x in legs if x["m"] is not None and x["q"] is not None]
    if not legs:
        return {"n": 0}
    m = np.array([x["m"] for x in legs])
    q = np.array([x["q"] for x in legs])
    y = np.array([x["y"] for x in legs])
    g = [x["game"] for x in legs]
    return {"n": len(legs), "games": len(set(g)), "hit_rate": round(float(y.mean()), 4), "mean_m": round(float(m.mean()), 4),
            "mean_q": round(float(q.mean()), 4), "g_m": paired(m - y, g, digits=4), "g_q": paired(q - y, g, digits=4),
            "LL_q_minus_m": paired(ll(q, y) - ll(m, y), g)}


def posterior(m: float, hits: Any, games: Any, k: float) -> float:
    """`cheat_sheets.consistency_posterior` at prior strength k (inf = the market alone)."""
    h, n = _f(hits), _f(games)
    if h is None or not n or math.isinf(k):
        return m
    return (k * m + h) / (k + n)


# ----------------------------------------------------------------------------- §7 corrections
def _lodo(units: Sequence[Mapping[str, Any]], fit: Callable[[list], Any], score: Callable[[Any, list], np.ndarray]) -> tuple[np.ndarray, dict]:
    """Leave-one-date-out: fit on every other date, score the held-out date. Returns the per-unit scores (unit order)
    and the parameter chosen per held-out date."""
    out = np.full(len(units), np.nan)
    params = {}
    dates = sorted({u["date"] for u in units})
    for d in dates:
        train = [u for u in units if u["date"] != d]
        test_idx = [i for i, u in enumerate(units) if u["date"] == d]
        if not train or not test_idx:
            continue
        theta = fit(train)
        params[d] = theta
        out[test_idx] = score(theta, [units[i] for i in test_idx])
    return out, params


def fit_k(legs: list) -> float:
    best = None
    for k in K_GRID:
        tot = float(ll([posterior(x["m"], x["hits"], x["games"], k) for x in legs], [x["y"] for x in legs]).sum())
        if best is None or tot < best[1] - 1e-12:
            best = (k, tot)
    return best[0]


def fit_devig(legs: list) -> tuple[float, float]:
    y = np.array([x["y"] for x in legs])
    lm = logit([x["m"] for x in legs])
    r = logistic_fit(y, np.column_stack([np.ones(len(lm)), lm]), [x["game"] for x in legs])
    return float(r["coef"][0]), float(r["coef"][1])


def devig(m: float, ab: tuple[float, float]) -> float:
    z = ab[0] + ab[1] * float(logit(m))
    return float(1 / (1 + math.exp(-z)))


def fit_lambda(pairs: list) -> float:
    best = None
    for lam in LAMBDA_GRID:
        tot = float(pair_scores(pairs, "m", lam)["llc"].sum())
        if best is None or tot < best[1] - 1e-12:
            best = (lam, tot)
    return best[0]


def corrections(sport_tickets: Mapping[str, list], sport_legs: Mapping[str, list], sport_pairs: Mapping[str, list],
                cells_by_sport: Mapping[str, Any], recon_ok: Mapping[str, bool], flagged: Mapping[str, set]) -> dict[str, Any]:
    """§7 for every sport with a flagged component: per-leg / per-pair candidates, leave-one-date-out, and the
    out-of-fold ticket CITL on the served hit-rate family (learnings 2026-09-21)."""
    out: dict[str, Any] = {}
    for sport, comps in flagged.items():
        if not comps:
            continue
        res: dict[str, Any] = {"flagged": sorted(comps)}
        legs = [x for x in sport_legs.get(sport, []) if x["m"] is not None and x["q"] is not None]
        k_by_date: dict[str, float] = {}
        ab_by_date: dict[str, tuple[float, float]] = {}
        lam_by_date: dict[str, float] = {}
        now_ll = ll([x["q"] for x in legs], [x["y"] for x in legs])
        if "nudge" in comps and legs:
            oof, k_by_date = _lodo(legs, fit_k, lambda k, us: ll([posterior(u["m"], u["hits"], u["games"], k) for u in us], [u["y"] for u in us]))
            res["nudge"] = {"k_by_date": {d: (None if math.isinf(k) else k) for d, k in k_by_date.items()},
                            "k_all": (lambda k: None if math.isinf(k) else k)(fit_k(legs)),
                            "oof_LL_minus_now": paired(oof - now_ll, [x["game"] for x in legs])}
        if "marginals" in comps and len({x["date"] for x in legs}) >= 3:
            oof, ab_by_date = _lodo(legs, fit_devig, lambda ab, us: ll([devig(u["m"], ab) for u in us], [u["y"] for u in us]))
            res["devig"] = {"ab_all": [round(v, 4) for v in fit_devig(legs)],
                            "oof_LL_minus_now": paired(oof - now_ll, [x["game"] for x in legs]),
                            "oof_LL_minus_market": paired(oof - ll([x["m"] for x in legs], [x["y"] for x in legs]), [x["game"] for x in legs])}
        pairs = sport_pairs.get(sport, [])
        if "copula" in comps and pairs:
            now = pair_scores(pairs, "m", 1.0)["llc"]
            oof, lam_by_date = _lodo(pairs, fit_lambda, lambda lam, us: pair_scores(us, "m", lam)["llc"])
            res["copula"] = {"lambda_all": fit_lambda(pairs), "lambda_by_date": lam_by_date,
                             "oof_LL_minus_now": paired(oof - now, [r["game"] for r in pairs])}
        # (ii) the acted-on subset: served hit-rate tickets re-priced out of fold
        cells = cells_by_sport.get(sport)
        served = [t for t in sport_tickets.get(sport, []) if t["clean"] and t["family"] == "hit_rate"
                  and all(x["m"] is not None and x["q"] is not None for x in t["legs"])]
        if served and cells and recon_ok.get(sport):
            def leg_p(t, x):
                m = x["m"]
                if t["date"] in ab_by_date:
                    m = devig(m, ab_by_date[t["date"]])
                if t["date"] in k_by_date:
                    return posterior(m, x["hits"], x["games"], k_by_date[t["date"]])
                if t["date"] in ab_by_date:
                    return m
                return x["q"]
            new = np.full(len(served), np.nan)
            for d in sorted({t["date"] for t in served}):
                idx = [i for i, t in enumerate(served) if t["date"] == d]
                c = scale_cells(cells, lam_by_date[d]) if d in lam_by_date else cells
                new[idx] = price_tickets(sport, [served[i] for i in idx], c, leg_p)
            ok = np.isfinite(new)
            g = [t["game"] for t, o in zip(served, ok) if o]
            y = [t["y"] for t, o in zip(served, ok) if o]
            res["served_hit_rate_oof"] = {"now": citl([t["p_joint"] for t, o in zip(served, ok) if o], y, g, boot=False),
                                          "corrected": citl(new[ok], y, g, boot=False)}
        out[sport] = res
    return out


# ----------------------------------------------------------------------------- the report
def breakdown(tickets: Sequence[Mapping[str, Any]], key: Callable[[Mapping[str, Any]], Any], min_n: int = 1) -> dict[str, Any]:
    groups: dict[str, list] = defaultdict(list)
    for t in tickets:
        groups[str(key(t))].append(t)
    return {k: citl([t["p_joint"] for t in v], [t["y"] for t in v], [t["game"] for t in v], boot=False)
            for k, v in sorted(groups.items()) if len(v) >= min_n}


def decompose(tickets: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """§6a: arms A / B / C on the clean tickets whose every leg carries p_market."""
    ts = [t for t in tickets if all(x["m"] is not None and x["q"] is not None for x in t["legs"])]
    if not ts:
        return {"n": 0}
    A = np.array([math.prod(x["m"] for x in t["legs"]) for t in ts])
    B = np.array([math.prod(x["q"] for x in t["legs"]) for t in ts])
    C = np.array([t["p_joint"] for t in ts])
    y = np.array([t["y"] for t in ts])
    g = [t["game"] for t in ts]
    led = np.array([t["p_independent"] if t["p_independent"] is not None else np.nan for t in ts])
    rep = np.abs(B - led) <= 0.002
    out = {"n": len(ts), "excluded_missing_m": len(tickets) - len(ts), "B_reproduces_p_independent": round(float(np.mean(rep)), 4),
           "G_A": citl(A, y, g, boot=False), "G_B": citl(B, y, g, boot=False), "G_C": citl(C, y, g, boot=False),
           "D_nudge": paired(B - A, g, digits=4), "D_copula": paired(C - B, g, digits=4),
           "LL_B_minus_A": paired(ll(B, y) - ll(A, y), g), "LL_C_minus_B": paired(ll(C, y) - ll(B, y), g),
           "LL_C_minus_A": paired(ll(C, y) - ll(A, y), g)}
    num = np.column_stack([A - y, B - A, C - B])
    den = (C - y)
    out["shares_of_G_C_boot_ci"] = dict(zip(("G_A", "D_nudge", "D_copula"), boot_ratio_ci(num, np.repeat(den[:, None], 3, axis=1), g)))
    out["shares_of_G_C"] = {k: (round(float(v.sum() / den.sum()), 3) if abs(den.sum()) > 0 else None)
                            for k, v in zip(("G_A", "D_nudge", "D_copula"), num.T)}
    return out


def censor_term(as_graded: Sequence[Mapping[str, Any]], clean: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """G_censor = CITL(as-graded) - CITL(clean), with a joint game-cluster bootstrap (§2)."""
    if not as_graded or not clean:
        return {}
    games = sorted({t["game"] for t in as_graded})
    pos = {g: i for i, g in enumerate(games)}
    G = len(games)
    sa, na, sc, nc = (np.zeros(G) for _ in range(4))
    for t in as_graded:
        sa[pos[t["game"]]] += t["p_joint"] - t["y"]
        na[pos[t["game"]]] += 1
    for t in clean:
        sc[pos[t["game"]]] += t["p_joint"] - t["y"]
        nc[pos[t["game"]]] += 1
    est = sa.sum() / na.sum() - sc.sum() / nc.sum()
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, G, size=(N_BOOT, G))
    stat = sa[idx].sum(1) / na[idx].sum(1) - sc[idx].sum(1) / np.maximum(nc[idx].sum(1), 1)
    lo, hi = np.percentile(stat, [2.5, 97.5])
    return {"G_censor": round(float(est), 4), "boot_ci": [round(float(lo), 4), round(float(hi), 4)],
            "n_as_graded": len(as_graded), "n_clean": len(clean), "won_with_void_leg_possible": False}


def attribute(sport: str, verdict: Mapping[str, Any], dec: Mapping[str, Any], legs: Mapping[str, Any],
              pairs: Mapping[str, Any], censor: Mapping[str, Any], recon_ok: bool) -> dict[str, Any]:
    """§6e for a sport whose §3 test rejected (sign mirrored for UNDER)."""
    s = 1.0 if verdict.get("direction") == "OVER" else -1.0

    def above(ci) -> bool:  # the CI lies wholly on the gap's side of 0
        return bool(ci) and (ci[0] > 0 if s > 0 else ci[1] < 0)

    flags = set()
    notes = {}
    if above(censor.get("boot_ci")):
        flags.add("grading_censoring")
    if above((dec.get("G_A") or {}).get("ci")) or above((legs.get("g_m") or {}).get("ci")):
        flags.add("marginals")
    dn = (dec.get("D_nudge") or {}).get("mean")
    if dn is not None and dn * s > 0:
        llq = (legs.get("LL_q_minus_m") or {}).get("ci")
        if llq and llq[0] > 0:                        # the posterior is WORSE than the market on the same legs
            flags.add("nudge")
        else:
            notes["nudge"] = "adds D_nudge mechanically; not shown wrong at the leg level"
    dc = (dec.get("D_copula") or {}).get("mean")
    if dc is not None and dc * s > 0:
        dk = (pairs.get("D_K") or {}).get("ci")
        exc_c = (pairs.get("excess_vs_copula") or {}).get("ci")
        exc_i = (pairs.get("excess_vs_indep") or {}).get("ci")
        if not recon_ok:
            notes["copula"] = "NOT RECONSTRUCTED: attribution rests on D_copula alone"
        elif (dk and dk[0] > 0) or (exc_c and exc_c[1] < 0 and exc_i and exc_i[0] <= 0 <= exc_i[1]):
            flags.add("copula")
        else:
            notes["copula"] = "adds D_copula mechanically; the pair test does not show the correlation wrong"
    notes["haircut"] = "0 by construction (prereg §6d): ASSUMED_BOOK_DISCOUNT never enters p_joint"
    return {"flags": sorted(flags), "notes": notes}


def run(snap: Path) -> dict[str, Any]:
    report: dict[str, Any] = {"prereg": "1e7793e3", "freeze": FREEZE, "seen_last": SEEN_LAST, "coverage": {}}
    all_tickets: dict[str, list] = {}
    cells_by: dict[str, Any] = {}
    for sport in SPORTS:
        base = snap / sport
        tickets, counts = build_tickets(sport, read_jsonl(base / "sgp_ledger.jsonl"), read_jsonl(base / "sgp_graded.jsonl"))
        all_tickets[sport] = tickets
        try:
            cells_by[sport] = json.loads((base / CELLS_FILE.format(sport=sport)).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cells_by[sport] = None
        dates = sorted({t["date"] for t in tickets})
        clean = [t for t in tickets if t["clean"]]
        report["coverage"][sport] = {"dates": {"first": dates[0] if dates else None, "last": dates[-1] if dates else None, "n": len(dates)},
                                     "counts": dict(counts), "clean_games": len({t["game"] for t in clean}),
                                     "as_graded_games": len({t["game"] for t in tickets if t["as_graded"]}),
                                     "unseen_slice_clean": sum(1 for t in clean if t["date"] > SEEN_LAST)}
        print(f"SGPCAL_COVERAGE {sport} " + json.dumps(report["coverage"][sport]), flush=True)

    clean_all = [t for s in SPORTS for t in all_tickets[s] if t["clean"]]
    # §3 primary
    prim = {"pooled": clean_all, **{s: [t for t in all_tickets[s] if t["clean"]] for s in SPORTS}}
    results = {k: citl([t["p_joint"] for t in v], [t["y"] for t in v], [t["game"] for t in v]) for k, v in prim.items() if v}
    h = holm({k: results[k]["p_two_sided"] for k in ("pooled",) + GATED if k in results})
    for k, r in results.items():
        if k in h:
            r["holm"] = h[k]
            r["verdict"] = (("MISCALIBRATED_OVER" if r["citl"] > 0 else "MISCALIBRATED_UNDER") if h[k]["reject"] else "NOT_SHOWN")
            r["direction"] = "OVER" if r["citl"] > 0 else "UNDER"
        else:
            r["verdict"] = "REPORTED_NOT_GATED"
        print(f"SGPCAL_PRIMARY {k} n={r['n']} games={r['games']} p={r['mean_p']} hit={r['hit_rate']} citl={r['citl']} "
              f"ci={r['ci']} boot={r.get('boot_ci')} p2={r['p_two_sided']:.4g} {r['verdict']}", flush=True)
    report["primary"] = results
    report["gap_is_real"] = any(results[k].get("holm", {}).get("reject") for k in results if "holm" in results[k])
    # as-graded beside it + censoring
    report["as_graded"] = {}
    report["censor"] = {}
    for k in ("pooled",) + SPORTS:
        ag = [t for s in SPORTS for t in all_tickets[s] if t["as_graded"]] if k == "pooled" else [t for t in all_tickets[k] if t["as_graded"]]
        cl = prim.get(k) or []
        if ag:
            report["as_graded"][k] = citl([t["p_joint"] for t in ag], [t["y"] for t in ag], [t["game"] for t in ag], boot=False)
            report["censor"][k] = censor_term(ag, cl)
    # §4
    report["slope"] = {k: recal([t["p_joint"] for t in v], [t["y"] for t in v], [t["game"] for t in v]) for k, v in prim.items() if v}
    # §5
    report["breakdowns"] = {}
    for k, v in prim.items():
        if not v:
            continue
        report["breakdowns"][k] = {
            "size": breakdown(v, lambda t: t["size"]), "family": breakdown(v, lambda t: t["family"]),
            "family_tier": breakdown(v, lambda t: f"{t['family']}/{t['tier']}"), "relation": breakdown(v, lambda t: t["relation"]),
            "slice": breakdown(v, lambda t: "seen_<=10-25" if t["date"] <= SEEN_LAST else "unseen_10-26"),
            "family_size": breakdown(v, lambda t: f"{t['family']}/{t['size']}")}
    edges = np.quantile([t["p_joint"] for t in clean_all], np.linspace(0, 1, 11)) if clean_all else []
    report["reliability_pooled"] = breakdown(clean_all, lambda t: int(min(9, np.searchsorted(edges[1:-1], t["p_joint"], side="right"))))
    nhl_fam = [t for t in prim.get("nhl") or [] if t["family"] != "none"]
    report["robust_nhl_without_family_none"] = citl([t["p_joint"] for t in nhl_fam], [t["y"] for t in nhl_fam],
                                                    [t["game"] for t in nhl_fam], boot=False) if nhl_fam else {}
    # §6
    report["decomposition"], report["legs"], report["pairs"], report["reconstruction"], report["attribution"] = {}, {}, {}, {}, {}
    sport_legs, sport_pairs, recon_ok = {}, {}, {}
    for sport in SPORTS:
        tickets = all_tickets[sport]
        clean = [t for t in tickets if t["clean"]]
        report["decomposition"][sport] = decompose(clean) if clean else {"n": 0}
        legs = unique_legs(tickets)
        sport_legs[sport] = legs
        lb = {"all": leg_block(legs), "pool_alt": leg_block([x for x in legs if x["alt"]]),
              "sheet_rows": leg_block([x for x in legs if not x["alt"]]),
              "band": {b: leg_block(v) for b, v in sorted(_group(legs, lambda x: band(x["m"])).items())},
              "hits": {b: leg_block(v) for b, v in sorted(_group([x for x in legs if x["alt"]], lambda x: _hits_bucket(x)).items())},
              "market": {b: leg_block(v) for b, v in sorted(_group(legs, lambda x: x["market"]).items())}}
        withm = [x for x in legs if x["m"] is not None]
        if len(withm) >= 30 and len({x["game"] for x in withm}) >= 3:
            lr = logistic_fit([x["y"] for x in withm], np.column_stack([np.ones(len(withm)), logit([x["m"] for x in withm])]),
                              [x["game"] for x in withm])
            lb["recal_m"] = {"alpha": lr["coef"][0], "beta": lr["coef"][1], "ci": lr["ci"], "n": lr["n"], "games": lr["games"]}
        kchk = [x for x in withm if x["q"] is not None and _f(x["hits"]) is not None and _f(x["games"])]
        lb["q_reproduces_k40"] = round(float(np.mean([abs(posterior(x["m"], x["hits"], x["games"], K_NOW) - x["q"]) <= 0.002 for x in kchk])), 4) if kchk else None
        report["legs"][sport] = lb
        rec = reconstruct(sport, [t for t in tickets if t["p_joint"] is not None], cells_by[sport])
        recon_ok[sport] = rec.get("ok", False)
        report["reconstruction"][sport] = {k: v for k, v in rec.items() if not k.startswith("_")}
        pairs = pair_rows(sport, tickets, cells_by[sport]) if cells_by[sport] else []
        sport_pairs[sport] = pairs
        report["pairs"][sport] = _pair_block(pairs)
        print(f"SGPCAL_DECOMP {sport} " + json.dumps({k: report["decomposition"][sport].get(k) for k in ("n", "G_A", "G_B", "G_C", "D_nudge", "D_copula")}, default=str), flush=True)
        print(f"SGPCAL_LEGS {sport} " + json.dumps(lb["all"], default=str), flush=True)
        print(f"SGPCAL_RECON {sport} " + json.dumps(report["reconstruction"][sport], default=str)[:400], flush=True)
        print(f"SGPCAL_PAIRS {sport} " + json.dumps(report["pairs"][sport].get("all"), default=str), flush=True)
    pooled_dec = decompose(clean_all)
    report["decomposition"]["pooled"] = pooled_dec
    report["legs"]["pooled"] = {"all": leg_block([x for s in SPORTS for x in sport_legs[s]])}
    report["pairs"]["pooled"] = _pair_block([r for s in SPORTS for r in sport_pairs[s]])
    flagged: dict[str, set] = {}
    for k in ("pooled",) + SPORTS:
        r = results.get(k) or {}
        if not (r.get("holm") or {}).get("reject"):
            continue
        att = attribute(k, r, report["decomposition"].get(k) or {}, (report["legs"].get(k) or {}).get("all") or {},
                        (report["pairs"].get(k) or {}).get("all") or {}, report["censor"].get(k) or {},
                        all(recon_ok.values()) if k == "pooled" else recon_ok.get(k, False))
        report["attribution"][k] = att
        print(f"SGPCAL_ATTRIBUTION {k} " + json.dumps(att), flush=True)
        targets = SPORTS if k == "pooled" else (k,)
        for s in targets:
            flagged.setdefault(s, set()).update(c for c in att["flags"] if c in ("marginals", "nudge", "copula"))
    report["corrections"] = corrections(all_tickets, sport_legs, sport_pairs, cells_by, recon_ok, flagged)
    for s, c in report["corrections"].items():
        print(f"SGPCAL_CORRECTION {s} " + json.dumps(c, default=str)[:1500], flush=True)
    return report


def _group(xs, key):
    out = defaultdict(list)
    for x in xs:
        out[str(key(x))].append(x)
    return out


def _hits_bucket(x) -> str:
    h = _f(x.get("hits"))
    return "none" if h is None else ("<=7" if h <= 7 else str(int(h)))


def _pair_block(pairs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    def one(rs):
        if not rs:
            return {"n": 0}
        sc = pair_scores(rs, "m")
        g = [r["game"] for r in rs]
        out = {"n": len(rs), "games": len(set(g)), "both_rate": round(float(sc["both"].mean()), 4),
               "mean_P_c": round(float(sc["pc"].mean()), 4), "mean_P_i": round(float(sc["pi"].mean()), 4),
               "excess_vs_copula": paired(sc["both"] - sc["pc"], g, digits=4), "excess_vs_indep": paired(sc["both"] - sc["pi"], g, digits=4),
               "D_K": paired(sc["llc"] - sc["lli"], g), "rho_levels": dict(Counter(r["level"] for r in rs)),
               "mean_rho": round(float(np.mean([r["rho"] for r in rs])), 4)}
        if all(r["a"]["q"] is not None and r["b"]["q"] is not None for r in rs):
            sq = pair_scores(rs, "q")
            out["q_marginals"] = {"excess_vs_copula": paired(sq["both"] - sq["pc"], g, digits=4), "D_K": paired(sq["llc"] - sq["lli"], g)}
        return out
    return {"all": one(list(pairs)), **{rel: one([r for r in pairs if r["relation"] == rel]) for rel in ("same_player", "teammate", "opponent")}}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--snap", required=True, help="snapshot root: <snap>/<sport>/sgp_{ledger,graded}.jsonl + cells")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    report = run(Path(args.snap))
    Path(args.out).write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    print(f"SGPCAL_DONE gap_is_real={report['gap_is_real']} out={args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
