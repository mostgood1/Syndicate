"""NHL regulation 3-way (60-minute home / tie / away) vs the de-vigged book close (lane `nhl-lines-backtest`).

The one game-line market the 2026-10-03 vs-book leg could not score: OddsAPI carries `h2h_3_way` only on the
per-event endpoint, so `backtest_nhl_game_lines.py odds3way` pulls it per game at the same snapshot time as
the other closes (3 minutes before the scheduled start) and merges a proportional 3-way de-vig, averaged over
the books quoting all three outcomes, into `<out>/book.json` (reg_home / reg_tie / reg_away).

MODEL, production form. Per game, the as-of production lambdas `backtest_nhl_game_lines.py sim` stored
(`<out>/sim/games.json`, `predict_game` output on the as-of roots) go through production's OWN calibrated
game-market sim, seed for seed: `adapters.NHL_GAME_MARKET_CALIBRATION` (regulation_scale, tie_weight,
empty_net_p, full-game settlement), `adapters.game_seed(date, game_pk)`, `_DEFAULT_GAME_SIMS`. The
pre-2026-10-03 legacy probabilities stored in the same file are reported beside it.

SCORING: multiclass Brier (sum over the 3 outcomes) and multiclass log-loss, model - book per game, with a
DATE-clustered bootstrap 95% CI (`backtest_nhl_game_lines._boot_diff`). Regular season and playoffs are
separate; mean tie probability model vs book vs actual is printed.

Usage: py -3 scripts/nhl_game_lines_3way_vs_book.py --out C:/tmp/nhllines
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Dict, List, Tuple

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
_spec = importlib.util.spec_from_file_location("_bgl", REPO / "scripts" / "backtest_nhl_game_lines.py")
BGL = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(BGL)


def production_3way(hp: List[float], ap: List[float], date: str, gid: str) -> Tuple[float, float, float]:
    from syndicate.features.nhl.sim_engine.hockeysim import adapters as A
    from syndicate.features.nhl.sim_engine.hockeysim.game_market_sim import simulate_from_period_lambdas

    cal = A.NHL_GAME_MARKET_CALIBRATION
    s = float(cal.get("regulation_scale") or 1.0)
    cfg = A.GameMarketSimConfig(n_sims=A._DEFAULT_GAME_SIMS, random_state=A.game_seed(date, gid),
                                empty_net_p=cal.get("empty_net_p"), tie_weight=float(cal.get("tie_weight") or 0.0),
                                full_game_settlement=bool(cal.get("full_game_settlement")),
                                ot_home_win_prob=float(cal.get("ot_home_win_prob") or 0.5))
    p = simulate_from_period_lambdas([x * s for x in hp], [x * s for x in ap], total_line=None, cfg=cfg)
    return p["p_reg_home"], p["p_reg_tie"], p["p_reg_away"]


def mc_brier(p: Tuple[float, float, float], k: int) -> float:
    return sum((p[i] - (1.0 if i == k else 0.0)) ** 2 for i in range(3))


def mc_ll(p: Tuple[float, float, float], k: int) -> float:
    return -math.log(min(1 - 1e-6, max(1e-6, p[k])))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="C:/tmp/nhllines")
    ap.add_argument("--min-n", type=int, default=100)
    a = ap.parse_args()
    out = Path(a.out)
    act = json.loads((out / "actuals.json").read_text(encoding="utf-8"))
    book = json.loads((out / "book.json").read_text(encoding="utf-8"))
    games = {g["gid"]: g for d in json.loads((out / "sim" / "games.json").read_text(encoding="utf-8"))["dates"] for g in d["games"]}
    rows: Dict[str, List[Dict]] = {}
    miss = {"no_book_3way": 0, "no_model": 0}
    for gid, r in act.items():
        b = book.get(gid) or {}
        if "reg_home" not in b:
            miss["no_book_3way"] += 1
            continue
        g = games.get(gid)
        if g is None:
            miss["no_model"] += 1
            continue
        k = 0 if r["reg_h"] > r["reg_a"] else (1 if r["reg_h"] == r["reg_a"] else 2)
        prod = production_3way(g["hp"], g["ap"], g["date"], gid)
        legacy = (g["raw"]["p_reg_home"], g["raw"]["p_reg_tie"], g["raw"]["p_reg_away"])
        bk = (b["reg_home"], b["reg_tie"], b["reg_away"])
        rows.setdefault(r["arm"], []).append({"date": g["date"], "k": k, "prod": prod, "legacy": legacy, "book": bk,
                                              "books": b.get("books_3way")})
    print(f"joined: { {arm: len(v) for arm, v in rows.items()} }; dropped {miss}")
    report = {}
    for arm, R in sorted(rows.items()):
        tie_act = statistics.fmean(1.0 if x["k"] == 1 else 0.0 for x in R)
        print(f"\n== {arm}: n={len(R)} games, {len({x['date'] for x in R})} dates, books/game "
              f"{statistics.fmean(x['books'] for x in R):.1f}")
        print(f"   tie rate: actual {tie_act:.3f} | book {statistics.fmean(x['book'][1] for x in R):.3f} | "
              f"model (production) {statistics.fmean(x['prod'][1] for x in R):.3f} | legacy {statistics.fmean(x['legacy'][1] for x in R):.3f}")
        report[arm] = {"n": len(R), "tie_actual": tie_act}
        for m in ("prod", "legacy"):
            for name, f in (("Brier3", mc_brier), ("LL3", mc_ll)):
                d = BGL._boot_diff([(x["date"], f(x[m], x["k"]) - f(x["book"], x["k"])) for x in R])
                vd = BGL._verdict(*d, len(R), a.min_n)
                lvl = statistics.fmean(f(x[m], x["k"]) for x in R)
                lb = statistics.fmean(f(x["book"], x["k"]) for x in R)
                report[arm][f"{m}.{name}"] = {"model": lvl, "book": lb, "d": d, "verdict": vd}
                print(f"   {m:<6} {name}: model {lvl:.4f} book {lb:.4f}  model-book {d[0]:+.4f} [{d[1]:+.4f}, {d[2]:+.4f}] {vd}")
            for i, side in enumerate(("home", "tie", "away")):
                d = BGL._boot_diff([(x["date"], (x[m][i] - (x["k"] == i)) ** 2 - (x["book"][i] - (x["k"] == i)) ** 2) for x in R])
                report[arm][f"{m}.{side}"] = d
                print(f"      {side:<4} dBrier model-book {d[0]:+.4f} [{d[1]:+.4f}, {d[2]:+.4f}]")
    (out / "reg3way_vs_book.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
