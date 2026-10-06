"""H25: NHL goalie SAVES priced by a negative binomial around the sim mean (lane `nhl-saves-overdispersion`).

The registry measurement (lane nhl-saves-skill-registry) found production's SAVES prices LOSE to the de-vigged book,
Brier +0.0274 [+0.0162, +0.0388], with the mean right and the spread overconfident: production prices P(over) by
Poisson from the sim's mean. This fits NB(mean = lam, size k) -- variance lam + lam^2 / k -- and tests it.

  fit   k by maximum likelihood on every sim-starter goalie who played on harness dates BEFORE 2026-01-01
        (props harness arm prior_dfo: production-form lam; boxscore saves), not only those with book lines.
  test  HOLDOUT = harness dates 2026-01-01..01-31: at every book SAVES line (OddsAPI historical closes,
        `C:/tmp/nhllines/odds_saves`, de-vigged), paired Brier NB - Poisson and each vs the book, game-clustered.
        The full window is printed too (in-sample for the fit dates).

Usage: py -3 scripts/nhl_saves_overdispersion.py
"""
from __future__ import annotations

import importlib.util
import json
import math
import pickle
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
_spec = importlib.util.spec_from_file_location("_svb", REPO / "scripts" / "nhl_saves_vs_book.py")
SVB = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SVB)

CUT = "2026-01-01"


def nb_logpmf(x: int, mu: float, k: float) -> float:
    if k == math.inf:
        return -mu + x * math.log(mu) - math.lgamma(x + 1)
    return (math.lgamma(x + k) - math.lgamma(k) - math.lgamma(x + 1)
            + k * math.log(k / (k + mu)) + x * math.log(mu / (k + mu)))


def nb_p_over(line: float, mu: float, k: float) -> float:
    mu = max(1e-9, float(mu))
    return max(0.0, min(1.0, 1.0 - sum(math.exp(nb_logpmf(i, mu, k)) for i in range(int(math.floor(line)) + 1))))


def fit_k(pairs: List[Tuple[float, int]]) -> Tuple[float, Dict]:
    grid = [round(1.0 * 1.15 ** i, 3) for i in range(0, 60)] + [math.inf]
    ll = {k: sum(nb_logpmf(y, mu, k) for mu, y in pairs) for k in grid}
    best = max(ll, key=ll.get)
    disp = sum((y - mu) ** 2 for mu, y in pairs) / sum(mu for mu, y in pairs)
    return best, {"n": len(pairs), "ll_best": round(ll[best], 2), "ll_poisson": round(ll[math.inf], 2),
                  "var_over_mean": round(disp, 3), "mean_lam": round(sum(m for m, _ in pairs) / len(pairs), 2),
                  "mean_saves": round(sum(y for _, y in pairs) / len(pairs), 2)}


def boot(rows: List[Tuple[str, float]], n: int = 4000, seed: int = 23) -> Tuple[float, float, float]:
    by = defaultdict(list)
    for g, v in rows:
        by[g].append(v)
    gids = sorted(by)
    rng = random.Random(seed)
    bs = []
    for _ in range(n):
        s = c = 0
        for g in (rng.choice(gids) for _ in gids):
            s += sum(by[g]); c += len(by[g])
        bs.append(s / c)
    bs.sort()
    return sum(v for _, v in rows) / len(rows), bs[int(0.025 * n)], bs[int(0.975 * n) - 1]


def main() -> int:
    from syndicate.features.nhl.confirmed_goalies import name_key
    out = Path("C:/tmp/nhllines")
    games = SVB.sim_games(Path("C:/tmp/nhllines/props_ab_v2/prior_dfo/sim"))
    acts = pickle.load(open("C:/tmp/nhlprops/bt_lqp_0.5/records.pkl", "rb"))["actuals"]
    fit_pairs, lines, all_pairs = [], [], []
    for gid, g in games.items():
        played = {p["pid"]: p for p in (acts.get(gid) or {}).get("players", []) if p["pos"] == "G" and p["toi"] > 0}
        starters = [x for x in g["goalies"] if x["sim_starter"] and x["lam"] and x["pid"] in played]
        if g["date"] < CUT:
            fit_pairs += [(x["lam"], int(played[x["pid"]]["sv"])) for x in starters]
        all_pairs += [(g["date"], x["lam"], int(played[x["pid"]]["sv"])) for x in starters]
        f = out / "odds_saves" / f"{gid}.json"
        if not f.exists():
            continue
        for (player, line), ps in SVB.book_lines(json.loads(f.read_text(encoding="utf-8")).get("snap")).items():
            hits = [x for x in starters if name_key(x["name"]) == name_key(player)]
            if len(hits) != 1:
                continue
            x = hits[0]
            lines.append({"gid": gid, "date": g["date"], "line": line, "lam": x["lam"],
                          "y": 1 if played[x["pid"]]["sv"] > line else 0, "pk": sum(ps) / len(ps)})
    k, fitinfo = fit_k(fit_pairs)
    print(f"fit (dates < {CUT}): k = {k} | {fitinfo}", flush=True)
    report = {"k": k, "fit": fitinfo}
    for name, R in (("HOLDOUT 2026-01-01..01-31", [r for r in lines if r["date"] >= CUT]), ("ALL 56 dates (fit dates in-sample)", lines)):
        for r in R:
            r["pp"] = SVB._p_over(r["line"], r["lam"])
            r["pn"] = nb_p_over(r["line"], r["lam"], k)
        b = lambda p, y: (p - y) ** 2
        d_np = boot([(r["gid"], b(r["pn"], r["y"]) - b(r["pp"], r["y"])) for r in R])
        d_nk = boot([(r["gid"], b(r["pn"], r["y"]) - b(r["pk"], r["y"])) for r in R])
        d_pk = boot([(r["gid"], b(r["pp"], r["y"]) - b(r["pk"], r["y"])) for r in R])
        bm = lambda key: sum(b(r[key], r["y"]) for r in R) / len(R)
        print(f"== {name}: n={len(R)} lines, {len({r['gid'] for r in R})} games | Brier NB {bm('pn'):.5f} Poisson {bm('pp'):.5f} book {bm('pk'):.5f}")
        print(f"   NB - Poisson {d_np[0]:+.5f} [{d_np[1]:+.5f}, {d_np[2]:+.5f}] | NB - book {d_nk[0]:+.5f} [{d_nk[1]:+.5f}, {d_nk[2]:+.5f}] | "
              f"Poisson - book {d_pk[0]:+.5f} [{d_pk[1]:+.5f}, {d_pk[2]:+.5f}]", flush=True)
        report[name] = {"n": len(R), "games": len({r['gid'] for r in R}), "brier_nb": bm("pn"), "brier_poisson": bm("pp"),
                        "brier_book": bm("pk"), "nb_minus_poisson": d_np, "nb_minus_book": d_nk, "poisson_minus_book": d_pk}
    if "--twofold" in sys.argv:
        dates = sorted({d for d, _m, _y in all_pairs})
        half_a = set(dates[: len(dates) // 2])
        ka, ia = fit_k([(m, y) for d, m, y in all_pairs if d in half_a])
        kb, ib = fit_k([(m, y) for d, m, y in all_pairs if d not in half_a])
        k_all, i_all = fit_k([(m, y) for _d, m, y in all_pairs])
        print(f"H26 two-fold: half A {min(half_a)}..{max(half_a)} k={ka} {ia} | half B k={kb} {ib} | ALL-dates k={k_all} {i_all}", flush=True)
        b = lambda p, y: (p - y) ** 2
        for r in lines:
            kk = kb if r["date"] in half_a else ka          # price each line with the OTHER half's k
            r["pn2"] = nb_p_over(r["line"], r["lam"], kk)
            r["pp"] = SVB._p_over(r["line"], r["lam"])
        d_np = boot([(r["gid"], b(r["pn2"], r["y"]) - b(r["pp"], r["y"])) for r in lines])
        d_nk = boot([(r["gid"], b(r["pn2"], r["y"]) - b(r["pk"], r["y"])) for r in lines])
        bm = lambda key: sum(b(r[key], r["y"]) for r in lines) / len(lines)
        verdict = "PASS (ship)" if d_np[2] < 0 else "FAIL (do not ship)"
        print(f"H26 pooled out-of-fold: n={len(lines)} lines | Brier NB {bm('pn2'):.5f} Poisson {bm('pp'):.5f} book {bm('pk'):.5f}")
        print(f"   NB - Poisson {d_np[0]:+.5f} [{d_np[1]:+.5f}, {d_np[2]:+.5f}] -> {verdict} | NB - book {d_nk[0]:+.5f} [{d_nk[1]:+.5f}, {d_nk[2]:+.5f}]", flush=True)
        report["H26"] = {"k_half_a": ka, "k_half_b": kb, "k_all": k_all, "fit_all": i_all, "n": len(lines),
                         "brier_nb": bm("pn2"), "brier_poisson": bm("pp"), "brier_book": bm("pk"),
                         "nb_minus_poisson": d_np, "nb_minus_book": d_nk, "verdict": verdict}
    (out / "saves_overdispersion.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
