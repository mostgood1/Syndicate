# -*- coding: utf-8 -*-
"""H31, offline: is a PER-LEAGUE momentum weight worth more than one global weight for next-goal DIRECTION?

Lane `soccer-live-model-study`, `#664` item 7. The rules are the registration, not this file:
`.syndicate/log/2026-09-17.md` ~15:50 CT. Nothing here changes the engine -- production consumes no
momentum at all today (it is display only), so H31 cannot ship anything by itself.

One row per goal at t >= 600 s in `reports/soccer_backtest/fotmob_2y.json.gz`:

    y       1 if the HOME side scored it
    tilt    mean vendor momentum over the 600 s before it (positive = home pressure)
    score   home minus away goals before it, capped at +-2
    xgdiff  home minus away cumulative xG before it

    D0  controls only                     D1  + a global gamma * tilt
    D2  + per-league gamma_L = gamma + delta_L, ridge on delta_L, strength cross-validated on TRAIN

TEST = matches whose FotMob id hashes to 0 mod 3 (not a time split: MLS appears in one season only).

    py -3 scripts/soccer_season_audit/live_direction_study.py --repo-root <checkout> --out <dir>
"""
from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import random
import sys
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

TILT_WINDOW_SECONDS = 600.0
MIN_GOAL_SECONDS = 600.0
SCORE_CAP = 2
LAMBDA_GRID = (0.1, 1.0, 10.0, 100.0, 1000.0)
CV_FOLDS = 5
BOOT_REPS, BOOT_SEED = 2000, 11
TEST_MOD = 3


# ---------------------------------------------------------------------------- rows (pure)

def is_test(match_id: str) -> bool:
    return int(hashlib.sha1(str(match_id).encode("utf-8")).hexdigest(), 16) % TEST_MOD == 0


def tilt_before(momentum: list[dict], t: float, window: float = TILT_WINDOW_SECONDS) -> float | None:
    values = [float(m["value"]) for m in momentum if t - window <= float(m["t"]) <= t]
    return sum(values) / len(values) if values else None


def goal_rows(match: dict) -> list[dict]:
    """One row per goal that has a full tilt window behind it."""
    momentum = match.get("vendor_momentum") or []
    shots = match.get("shots") or []
    goals = sorted((match.get("goals") or []), key=lambda g: float(g["t"]))
    rows = []
    for goal in goals:
        t = float(goal["t"])
        if t < MIN_GOAL_SECONDS:
            continue
        tilt = tilt_before(momentum, t)
        if tilt is None:
            continue
        home_before = sum(1 for g in goals if float(g["t"]) < t and g.get("home"))
        away_before = sum(1 for g in goals if float(g["t"]) < t and not g.get("home"))
        xg_home = sum(float(s.get("xg") or 0.0) for s in shots if float(s["t"]) < t and s.get("home"))
        xg_away = sum(float(s.get("xg") or 0.0) for s in shots if float(s["t"]) < t and not s.get("home"))
        rows.append({
            "match_id": str(match.get("match_id")), "lg": match.get("league"), "date": str(match.get("date"))[:10],
            "y": 1.0 if goal.get("home") else 0.0, "tilt": tilt,
            "score": float(max(-SCORE_CAP, min(SCORE_CAP, home_before - away_before))),
            "xgdiff": xg_home - xg_away,
        })
    return rows


def load_rows(repo_root: Path) -> tuple[list[dict], collections.Counter]:
    path = Path(repo_root) / "reports" / "soccer_backtest" / "fotmob_2y.json.gz"
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        matches = json.load(handle)["matches"]
    funnel = collections.Counter()
    rows = []
    for match in matches:
        funnel["matches"] += 1
        if not match.get("vendor_momentum"):
            funnel["no_momentum"] += 1
            continue
        got = goal_rows(match)
        funnel["goals_kept"] += len(got)
        funnel["matches_with_a_goal_row"] += 1 if got else 0
        rows.extend(got)
    return rows, funnel


# ---------------------------------------------------------------------------- model

def design(rows: list[dict], leagues: list[str]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(X, y, penalty_mask). Columns: 1, score, xgdiff, tilt, then tilt x league (penalised)."""
    index = {lg: i for i, lg in enumerate(leagues)}
    X = np.zeros((len(rows), 4 + len(leagues)))
    y = np.zeros(len(rows))
    for i, r in enumerate(rows):
        X[i, 0] = 1.0
        X[i, 1] = r["score"]
        X[i, 2] = r["xgdiff"]
        X[i, 3] = r["tilt"]
        j = index.get(r["lg"])
        if j is not None:
            X[i, 4 + j] = r["tilt"]
        y[i] = r["y"]
    mask = np.zeros(X.shape[1])
    mask[4:] = 1.0                      # only the per-league deviations are penalised
    return X, y, mask


def fit(X: np.ndarray, y: np.ndarray, penalty_mask: np.ndarray, lam: float) -> np.ndarray:
    def objective(beta):
        z = X @ beta
        ll = float(np.sum(np.logaddexp(0.0, z) - y * z))          # no overflow at large |z|
        return ll + 0.5 * lam * float(np.sum(penalty_mask * beta * beta))

    def gradient(beta):
        p = 1.0 / (1.0 + np.exp(-(X @ beta)))
        return X.T @ (p - y) + lam * penalty_mask * beta

    result = minimize(objective, np.zeros(X.shape[1]), jac=gradient, method="L-BFGS-B", options={"maxiter": 500})
    return result.x


def log_loss(X: np.ndarray, y: np.ndarray, beta: np.ndarray) -> np.ndarray:
    z = X @ beta
    return np.logaddexp(0.0, z) - y * z          # per row


def pick_lambda(train: list[dict], leagues: list[str], folds: int = CV_FOLDS, seed: int = 7) -> tuple[float, dict]:
    """Cross-validated over MATCHES, never over goals: two goals in one match share a tilt series."""
    match_ids = sorted({r["match_id"] for r in train})
    rng = random.Random(seed)
    rng.shuffle(match_ids)
    fold_of = {m: i % folds for i, m in enumerate(match_ids)}
    scores = {}
    for lam in LAMBDA_GRID:
        total, n = 0.0, 0
        for f in range(folds):
            tr = [r for r in train if fold_of[r["match_id"]] != f]
            va = [r for r in train if fold_of[r["match_id"]] == f]
            if not tr or not va:
                continue
            Xtr, ytr, mask = design(tr, leagues)
            Xva, yva, _ = design(va, leagues)
            beta = fit(Xtr, ytr, mask, lam)
            total += float(np.sum(log_loss(Xva, yva, beta)))
            n += len(va)
        scores[lam] = total / max(n, 1)
    return min(LAMBDA_GRID, key=lambda l: scores[l]), scores


def paired_boot_by_match(rows: list[dict], a: np.ndarray, b: np.ndarray, reps: int = BOOT_REPS, seed: int = BOOT_SEED):
    """mean(loss_a - loss_b), match-clustered percentile CI."""
    by = collections.defaultdict(list)
    for r, la, lb in zip(rows, a, b):
        by[r["match_id"]].append(float(la - lb))
    units = list(by.values())
    stat = lambda s: sum(sum(u) for u in s) / max(sum(len(u) for u in s), 1)  # noqa: E731
    point = stat(units)
    rng = random.Random(seed)
    k = len(units)
    vals = sorted(stat([units[rng.randrange(k)] for _ in range(k)]) for _ in range(reps))
    return point, (vals[int(0.025 * reps)], vals[int(0.975 * reps) - 1]), k


def auc(pairs: list[tuple[float, float]]) -> float:
    """P(a positive scores above a negative), ties at half."""
    pos = sorted(s for s, y in pairs if y > 0.5)
    neg = sorted(s for s, y in pairs if y <= 0.5)
    if not pos or not neg:
        return float("nan")
    import bisect
    total = 0.0
    for s in pos:
        total += bisect.bisect_left(neg, s) + 0.5 * (bisect.bisect_right(neg, s) - bisect.bisect_left(neg, s))
    return total / (len(pos) * len(neg))


def verdict(d2_vs_d1) -> str:
    _, (lo, hi), _ = d2_vs_d1
    return "SUPPORTED" if (hi == hi and hi < 0) else "FALSIFIED"


# ---------------------------------------------------------------------------- study

def study(rows: list[dict]) -> dict:
    leagues = sorted({r["lg"] for r in rows})
    train = [r for r in rows if not is_test(r["match_id"])]
    test = [r for r in rows if is_test(r["match_id"])]
    lam, lam_scores = pick_lambda(train, leagues)

    Xtr, ytr, mask = design(train, leagues)
    Xte, yte, _ = design(test, leagues)
    keep_d0 = np.ones_like(mask)
    keep_d0[3:] = 0.0                                     # D0: no tilt at all
    keep_d1 = np.ones_like(mask)
    keep_d1[4:] = 0.0                                     # D1: one global tilt weight

    beta_d0 = fit(Xtr * keep_d0, ytr, mask, 0.0) * keep_d0
    beta_d1 = fit(Xtr * keep_d1, ytr, mask, 0.0) * keep_d1
    beta_d2 = fit(Xtr, ytr, mask, lam)

    loss_d0 = log_loss(Xte, yte, beta_d0)
    loss_d1 = log_loss(Xte, yte, beta_d1)
    loss_d2 = log_loss(Xte, yte, beta_d2)

    per_league = {}
    for i, lg in enumerate(leagues):
        sub = [r for r in test if r["lg"] == lg]
        per_league[lg] = {
            "goals_test": len(sub),
            "goals_train": sum(1 for r in train if r["lg"] == lg),
            "gamma_L": float(beta_d2[3] + beta_d2[4 + i]),
            "tilt_auc_test": auc([(r["tilt"], r["y"]) for r in sub]),
        }
    out = {
        "goals": len(rows), "train_goals": len(train), "test_goals": len(test),
        "train_matches": len({r["match_id"] for r in train}), "test_matches": len({r["match_id"] for r in test}),
        "lambda": lam, "lambda_cv": lam_scores,
        "gamma_global_d1": float(beta_d1[3]), "gamma_global_d2": float(beta_d2[3]),
        "test_logloss": {"D0": float(np.mean(loss_d0)), "D1": float(np.mean(loss_d1)), "D2": float(np.mean(loss_d2))},
        "test_auc_tilt": auc([(r["tilt"], r["y"]) for r in test]),
        "d2_vs_d1": paired_boot_by_match(test, loss_d2, loss_d1),
        "d1_vs_d0": paired_boot_by_match(test, loss_d1, loss_d0),
        "per_league": per_league,
    }
    out["verdict"] = verdict(out["d2_vs_d1"])
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo-root", required=True, help="a checkout holding reports/soccer_backtest/fotmob_2y.json.gz")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    rows, funnel = load_rows(Path(args.repo_root))
    print("funnel", dict(funnel), flush=True)
    res = study(rows)
    res["funnel"] = dict(funnel)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "live_direction_study.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    print(f"goals {res['goals']} (TRAIN {res['train_goals']} in {res['train_matches']} matches, TEST {res['test_goals']} in {res['test_matches']})  "
          f"lambda {res['lambda']}  gamma global D1 {res['gamma_global_d1']:+.4f} D2 {res['gamma_global_d2']:+.4f}  tilt AUC (test) {res['test_auc_tilt']:.3f}")
    print("TEST log loss: " + " | ".join(f"{k} {v:.5f}" for k, v in res["test_logloss"].items()))
    for name in ("d2_vs_d1", "d1_vs_d0"):
        p, (lo, hi), k = res[name]
        print(f"  {name}: mean log-loss diff {p:+.5f} [{lo:+.5f}, {hi:+.5f}] over {k} matches")
    for lg, v in sorted(res["per_league"].items(), key=lambda kv: -kv[1]["gamma_L"]):
        print(f"  {lg:20s} train {v['goals_train']:5d} test {v['goals_test']:5d}  gamma_L {v['gamma_L']:+.4f}  tilt AUC {v['tilt_auc_test']:.3f}")
    print("H31:", res["verdict"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
