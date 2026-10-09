"""Does production's NFL QB prop probability carry information BEYOND the de-vigged book line?

Lane `nfl-qb-prop-info-beyond-line`, pre-registered in `.syndicate/lanes.md` (c7a2085e) before any number:

    y ~ a + b1*logit(p_book) + b2*logit(p_model)

fitted on real 2023 OddsAPI quotes (kickoff -10 min, two-sided, de-vigged per book), applied unchanged to real 2024
quotes. b2 > 0 with a game-clustered CI excluding 0 means the model adds information the line lacks; the 2024 paired
log-loss of the combined probability against the book alone says whether that information is usable out of sample.

Rows: `scripts/diagnose_nfl_passing_yards_prop.py build --seasons 2023,2024` (OFFICIAL attempts). p_model is
recomputed per row through the CURRENT production functions (018a7c64: starts-only rate, official attempts,
under-2-starts refusal -> row excluded). 2025 is not read.

    py -3 scripts/measure_nfl_qb_prop_info_beyond_line.py
"""
from __future__ import annotations

import json
import math
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts import diagnose_nfl_passing_yards_prop as D  # noqa: E402

ROWS = D.OUT / "rows_2023-2024.jsonl"
STATS = ("passing_yards", "passing_attempts")


def _logit(p: float) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def _ll(p: float, y: int) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return -math.log(p if y else 1 - p)


def fit_logistic(X: list[tuple[float, float]], ys: list[int], iters: int = 60) -> tuple[float, float, float]:
    """Newton-Raphson for y ~ a + b1*x1 + b2*x2 (3 parameters, closed-form 3x3 solve)."""
    a, b1, b2 = 0.0, 1.0, 0.0
    for _ in range(iters):
        g = [0.0, 0.0, 0.0]
        H = [[0.0] * 3 for _ in range(3)]
        for (x1, x2), y in zip(X, ys):
            z = a + b1 * x1 + b2 * x2
            mu = 1 / (1 + math.exp(-max(min(z, 30), -30)))
            v = (1.0, x1, x2)
            w = mu * (1 - mu)
            for i in range(3):
                g[i] += (y - mu) * v[i]
                for j in range(3):
                    H[i][j] += w * v[i] * v[j]
        step = _solve3(H, g)
        if step is None:
            break
        a, b1, b2 = a + step[0], b1 + step[1], b2 + step[2]
        if sum(abs(s) for s in step) < 1e-9:
            break
    return a, b1, b2


def _solve3(H: list[list[float]], g: list[float]) -> list[float] | None:
    M = [row[:] + [g[i]] for i, row in enumerate(H)]
    for c in range(3):
        piv = max(range(c, 3), key=lambda r: abs(M[r][c]))
        if abs(M[piv][c]) < 1e-12:
            return None
        M[c], M[piv] = M[piv], M[c]
        for r in range(3):
            if r != c:
                f = M[r][c] / M[c][c]
                M[r] = [M[r][k] - f * M[c][k] for k in range(4)]
    return [M[i][3] / M[i][i] for i in range(3)]


def build(stat: str) -> list[dict]:
    from syndicate.features.nfl import player_stats as ps
    from syndicate.features.nfl import props as P

    out = []
    for r in map(json.loads, ROWS.open(encoding="utf-8")):
        if r["stat"] != stat or r["actual"] == r["line"]:
            continue
        if ps.qb_starts_refused(r["season"], r["week"], r["pid"], stat, r["rsrc"]):
            continue
        mean, sd, n = r["mean_raw"], r["sd"], r["n"]
        if stat in ps.QB_STARTS_ONLY_RATE_STATS and ps.qb_starts_only_rate_enabled():
            mean, sd, n = ps.qb_starts_only_rate(r["season"], r["week"], r["pid"], stat, r["rsrc"])
        p = P._nfl_prop_model_probability(stat=stat, mean=mean * r["ctx"], stdev=sd, n=n, line=r["line"])
        if p is None:
            continue
        out.append({"gid": r["gid"], "season": r["season"], "y": int(r["actual"] > r["line"]),
                    "lb": _logit(r["p_book"]), "lm": _logit(p), "p_book": r["p_book"], "p_model": p})
    return out


def main() -> int:
    from scripts.football_scenario_rates import idle_self
    idle_self()  # the production fleet shares this machine
    D.H.configure_env(D.ROOT)
    D.H._patch_game_log_cache()
    report: dict = {"rows_file": str(ROWS)}
    for stat in STATS:
        rows = build(stat)
        fit = [r for r in rows if r["season"] == 2023]
        held = [r for r in rows if r["season"] == 2024]
        X = [(r["lb"], r["lm"]) for r in fit]
        ys = [r["y"] for r in fit]
        a, b1, b2 = fit_logistic(X, ys)
        by_g = defaultdict(list)
        for i, r in enumerate(fit):
            by_g[r["gid"]].append(i)
        gs = list(by_g)
        rng = random.Random(7)
        boot = []
        for _ in range(300):
            idx = [i for g in (rng.choice(gs) for _ in gs) for i in by_g[g]]
            boot.append(fit_logistic([X[i] for i in idx], [ys[i] for i in idx], iters=25)[2])
        boot.sort()
        comb = lambda r: 1 / (1 + math.exp(-max(min(a + b1 * r["lb"] + b2 * r["lm"], 30), -30)))  # noqa: E731
        d_by = defaultdict(list)
        for r in held:
            d_by[r["gid"]].append(_ll(comb(r), r["y"]) - _ll(r["p_book"], r["y"]))
        hg = list(d_by)
        hb = []
        for _ in range(1000):
            s = [x for g in (rng.choice(hg) for _ in hg) for x in d_by[g]]
            hb.append(statistics.fmean(s))
        hb.sort()
        L = lambda rs, k: statistics.fmean(_ll(r[k], r["y"]) for r in rs)  # noqa: E731
        S = {
            "fit_2023": {"n": len(fit), "games": len(gs), "a": round(a, 4), "b1_book": round(b1, 4),
                         "b2_model": round(b2, 4), "b2_ci95": [round(boot[7], 4), round(boot[292], 4)]},
            "held_2024": {"n": len(held), "games": len(hg), "LL_book": round(L(held, "p_book"), 4),
                          "LL_model": round(L(held, "p_model"), 4),
                          "LL_combined": round(statistics.fmean(_ll(comb(r), r["y"]) for r in held), 4),
                          "combined_minus_book": round(statistics.fmean(x for v in d_by.values() for x in v), 4),
                          "ci95": [round(hb[25], 4), round(hb[974], 4)]},
        }
        b2_sig = S["fit_2023"]["b2_ci95"][0] > 0
        usable = S["held_2024"]["ci95"][1] < 0
        S["verdict"] = ("INFORMATION BEYOND THE LINE, USABLE" if b2_sig and usable else
                        "b2 > 0 IN FIT, NOT USABLE OUT OF SAMPLE" if b2_sig else "NO INFORMATION BEYOND THE LINE")
        report[stat] = S
        print(stat, json.dumps(S), flush=True)
    out = D.OUT / "info_beyond_line_report.json"
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
