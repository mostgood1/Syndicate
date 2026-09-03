# -*- coding: utf-8 -*-
"""How much precision does the anchor solver's cost buy, and can it be skipped?

Two questions, one reference. Answered `todo.md #622`(2) on 2026-09-02/03.

    --mode cost      grade solver settings against a dense reference
    --mode heldout   fit the pooled slope on TRAIN leagues, score on TEST ones

WHAT `cost` FOUND
    setting     sims/solve   mean seed sd   mean RMSE
    100x7            700         0.0406       0.0491
    100x5 DEFAULT    500         0.0414       0.0497
    100x3            300         0.0527       0.0606
    50x5             250         0.0609       0.0705
    25x5             125         0.0755       0.0871
    12x5              60         0.0944       0.1110
  * The DEFAULT's own seed-to-seed sd (0.0414) is **2.2x the bisection's own
    0.01875 quantisation** -- the solver is noise-dominated, so "precision" is
    already swamped. `solve_market_rating_shift` returns one of exactly
    2^max_iterations lattice points, and every shift in the original 2026-07-20
    validation CSV sits on that lattice using 7 of 32 possible values.
  * `100x7` buys NOTHING for 40% more compute. Never raise iterations.
  * Cutting `simulations` is NOT free: -42% RMSE at half budget.

WHAT `heldout` FOUND
    b_train 3.6955 frozen on epl/la_liga/serie_a/bundesliga (8 fixtures)
    scored on ligue_1/eredivisie/primeira_liga/championship (8 fixtures)
    surrogate      mean |err| 0.0144   (0.0164 excluding a clamp artifact)
    500-sim solver mean |err| 0.0225   (0.0212 excluding it)
    slope bias     b_test 3.803 vs 3.696  ->  +2.9%
  Neither pre-registered kill condition fired, so
  `shift = (logit(target) - logit(p_base)) / b` generalises and costs ZERO extra
  simulations -- `p_base` is already published as `win_probability.home`.
  **BUT the in-sample "2x better" does NOT replicate: 1.3x ex-clamp, sign test
  p=0.289/0.453 (NOT significant), and the reference's own uncertainty (0.0187)
  EXCEEDS the error being claimed. The defensible claim is EQUAL ACCURACY AT
  ZERO COST, not better accuracy.**

THREE METHOD NOTES, each a defect caught before it became a finding
    1. SEEDS MUST BE DISJOINT. `solve_market_rating_shift(seed=S)` draws
       `S .. S+simulations-1`, so seeds spaced by 1 share 99 of 100 draws. A
       first pass read **sd = 0.0000 across 12 "different" seeds** and would have
       been written up as "the solver is deterministic". Spacing here exceeds
       every `simulations` value graded.
    2. `p_base` IS MEASURED INDEPENDENTLY, from a seed block disjoint from the
       reference grid. Taking it from the reference's own shift=0 point shares
       noise with the truth and flatters the surrogate.
    3. THE REFERENCE HAS UNCERTAINTY TOO, and it is reported: a fitted-vs-
       monotone inverse gap of ~0.019 mean, comparable to the estimator errors
       being graded. The ranking survives (one reference for all arms); the
       absolute numbers carry that band.

Needs a local odds CSV for real targets (`<league>/api/odds/game_odds_current.csv`)
and league history for ratings, both under `--source-root`.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics as stats
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

SHIFT_BOUND = 0.30
GOALS_BASED = {"eredivisie", "primeira_liga", "championship", "belgian_pro_league"}
SETTINGS = ((100, 5), (100, 7), (100, 3), (50, 5), (25, 5), (12, 5))
TRAIN_LEAGUES = ("epl", "la_liga", "serie_a", "bundesliga")
TEST_LEAGUES = ("ligue_1", "eredivisie", "primeira_liga", "championship")


def logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def _ratings(league: str, as_of: str, source_root: Path):
    import pandas as pd
    from syndicate.features.soccer.features.loaders import compute_team_ratings
    from syndicate.features.soccer.features.loaders import team_rows_from_match_history
    if league in GOALS_BASED:
        frames = [pd.read_csv(p) for p in sorted((source_root / league / "history").glob("matches_*.csv"))]
        if not frames:
            raise SystemExit(f"no match history for {league}")
        rows = team_rows_from_match_history(pd.concat(frames, ignore_index=True).to_dict("records"))
        return compute_team_ratings(rows, as_of=as_of, window=90)
    frames = [pd.read_csv(p) for p in sorted((source_root / league / "team_history").glob("teams_*.csv"))]
    if not frames:
        raise SystemExit(f"no team history for {league}")
    return compute_team_ratings(pd.concat(frames, ignore_index=True).to_dict("records"),
                                as_of=as_of, window=45)


def load_fixtures(leagues, as_of: str, source_root: Path, per_league: int):
    from syndicate.features.soccer.features.market_odds import home_win_probability_by_event
    from syndicate.features.soccer.features.team_names import match_team_name
    out = []
    for league in leagues:
        path = source_root / league / "api" / "odds" / "game_odds_current.csv"
        if not path.is_file():
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            priced = home_win_probability_by_event(list(csv.DictReader(handle)))
        try:
            ratings = _ratings(league, as_of, source_root)
        except SystemExit:
            continue
        names, taken = list(ratings), 0
        for entry in priced.values():
            if taken >= per_league:
                break
            hk = match_team_name(entry["home_team"], names)
            ak = match_team_name(entry["away_team"], names)
            if hk is None or ak is None or hk == ak:
                continue
            home = {k: v for k, v in ratings[hk].items() if k in ("attack_rating", "defense_rating")}
            away = {k: v for k, v in ratings[ak].items() if k in ("attack_rating", "defense_rating")}
            if home == away:
                continue          # the name match collapsed both sides onto one team
            out.append({"league": league, "label": f"{entry['home_team']} v {entry['away_team']}",
                        "target": float(entry["home_win_probability"]), "home": home, "away": away})
            taken += 1
    return out


def _sim(args):
    from syndicate.features.soccer.features.market_anchoring import _simulated_home_win_probability
    from syndicate.features.soccer.sim_engine.soccersim.calibration_profile import SOCCER_CALIBRATION_PROFILE
    home, away, shift, n, seed = args
    p = _simulated_home_win_probability(home_rating=home, away_rating=away, shift=shift,
                                        profile=SOCCER_CALIBRATION_PROFILE, simulations=n, seed=seed)
    return shift, round(p * n), n


def _solve(args):
    from syndicate.features.soccer.features.market_anchoring import solve_market_rating_shift
    home, away, target, sims, iters, seed = args
    return solve_market_rating_shift(home_rating=home, away_rating=away,
                                     market_home_win_probability=target,
                                     simulations=sims, seed=seed, max_iterations=iters)


def fit_logistic(points):
    """Binomial MLE for p(shift)=sigmoid(a+b*shift); uses every draw rather than
    one bisection path. Returns (a, b, max abs residual) -- the residual is the
    specification check, not decoration."""
    a, b = 0.0, 3.0
    for _ in range(200):
        g0 = g1 = h00 = h01 = h11 = 0.0
        for shift, wins, n in points:
            p = 1.0 / (1.0 + math.exp(-(a + b * shift)))
            w = n * p * (1 - p)
            r = wins - n * p
            g0 += r; g1 += r * shift
            h00 += w; h01 += w * shift; h11 += w * shift * shift
        det = h00 * h11 - h01 * h01
        if abs(det) < 1e-12:
            break
        da = (h11 * g0 - h01 * g1) / det
        db = (h00 * g1 - h01 * g0) / det
        a += da; b += db
        if abs(da) < 1e-10 and abs(db) < 1e-10:
            break
    resid = max(abs(w / n - 1.0 / (1.0 + math.exp(-(a + b * s)))) for s, w, n in points)
    return a, b, resid


def invert(a, b, target):
    return max(-SHIFT_BOUND, min(SHIFT_BOUND, (logit(target) - a) / b))


def invert_monotone(points, target):
    xs = [s for s, _, _ in points]; ys = [w / n for _, w, n in points]
    for i in range(len(xs) - 1):
        lo, hi = ys[i], ys[i + 1]
        if (lo - target) * (hi - target) <= 0 and hi != lo:
            return xs[i] + (target - lo) / (hi - lo) * (xs[i + 1] - xs[i])
    return xs[0] if target < ys[0] else xs[-1]


def reference(pool, fixtures, grid, sims, seed0):
    jobs = [(i, (f["home"], f["away"], s, sims, seed0 + i * 200_000 + gi * 10_000))
            for i, f in enumerate(fixtures) for gi, s in enumerate(grid)]
    out = list(pool.map(_sim, [a for _, a in jobs], chunksize=1))
    per: dict = {}
    for (i, _), row in zip(jobs, out):
        per.setdefault(i, []).append(row)
    return {i: sorted(v) for i, v in per.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=("cost", "heldout"), required=True)
    parser.add_argument("--source-root", default=str(REPO_ROOT / "data" / "soccer_source"))
    parser.add_argument("--as-of", required=True, help="rating as_of date; REQUIRED, never defaulted")
    parser.add_argument("--grid-points", type=int, default=13)
    parser.add_argument("--reference-simulations", type=int, default=600)
    parser.add_argument("--per-league", type=int, default=2)
    parser.add_argument("--seeds", type=int, default=6)
    parser.add_argument("--seed-spacing", type=int, default=5000,
                        help="MUST exceed --reference-simulations and every graded `simulations`")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    source_root = Path(args.source_root)
    grid = [round(-SHIFT_BOUND + i * (2 * SHIFT_BOUND / (args.grid_points - 1)), 5)
            for i in range(args.grid_points)]
    if args.seed_spacing <= max(args.reference_simulations, 100):
        raise SystemExit("--seed-spacing must exceed every simulations value, or the "
                         "'independent' seeds share draws and the control reads sd=0")
    seeds = [1_000_000 + args.seed_spacing * i for i in range(args.seeds)]

    train = load_fixtures(TRAIN_LEAGUES, args.as_of, source_root, args.per_league)
    if not train:
        raise SystemExit("no train fixtures -- need <league>/api/odds/game_odds_current.csv")
    started = time.perf_counter()

    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        ref_train = reference(pool, train, grid, args.reference_simulations, 10_000_000)
        fits = {i: fit_logistic(pts) for i, pts in ref_train.items()}
        b_train = stats.mean(b for _a, b, _r in fits.values())
        print(f"b_train {b_train:.4f}  from {len(train)} fixtures in {sorted({f['league'] for f in train})}",
              flush=True)

        if args.mode == "cost":
            print(f"\n{'setting':>10s} {'sims/solve':>11s} {'mean sd':>9s} {'mean RMSE':>10s}")
            summary = {}
            for sims, iters in SETTINGS:
                sds, rmses = [], []
                for i, f in enumerate(train):
                    a, b, _r = fits[i]
                    truth = invert(a, b, f["target"])
                    got = list(pool.map(_solve, [(f["home"], f["away"], f["target"], sims, iters, s) for s in seeds]))
                    sds.append(stats.pstdev(got))
                    rmses.append(math.sqrt(sum((x - truth) ** 2 for x in got) / len(got)))
                tag = f"{sims}x{iters}" + ("  <-DEFAULT" if (sims, iters) == (100, 5) else "")
                print(f"{tag:>10s} {sims*iters:11d} {stats.mean(sds):9.4f} {stats.mean(rmses):10.4f}", flush=True)
                summary[f"{sims}x{iters}"] = {"sims_per_solve": sims * iters,
                                              "mean_seed_sd": stats.mean(sds),
                                              "mean_rmse": stats.mean(rmses)}
            print(f"\nlattice: 2^iters points, spacing {2*SHIFT_BOUND/2**5:.5f} at iters=5 -- "
                  f"compare it to the seed sd above before buying precision")
            payload = {"mode": "cost", "b_train": b_train, "settings": summary}
        else:
            test = load_fixtures(TEST_LEAGUES, args.as_of, source_root, args.per_league)
            if not test:
                raise SystemExit("no held-out fixtures")
            assert not ({f["league"] for f in test} & {f["league"] for f in train}), "LEAK: test league in train"
            ref_test = reference(pool, test, grid, args.reference_simulations, 20_000_000)
            # p_base from a DISJOINT seed block -- never the reference's own shift=0
            pbase = dict(enumerate(
                w / n for _s, w, n in pool.map(
                    _sim, [(f["home"], f["away"], 0.0, 400, 90_000_000 + i * 500_000)
                           for i, f in enumerate(test)])))
            print(f"\n{'league':15s} {'fixture':30s} {'truth':>8s} {'surrog':>8s} {'sur|e|':>7s} {'solver':>8s} {'sol|e|':>7s}")
            sur_e, sol_e, rows = [], [], []
            for i, f in enumerate(test):
                a, b, resid = fit_logistic(ref_test[i])
                truth = invert(a, b, f["target"])
                mono = invert_monotone(ref_test[i], f["target"])
                sur = max(-SHIFT_BOUND, min(SHIFT_BOUND, (logit(f["target"]) - logit(pbase[i])) / b_train))
                sol = stats.mean(pool.map(_solve, [(f["home"], f["away"], f["target"], 100, 5, s) for s in seeds]))
                sur_e.append(abs(sur - truth)); sol_e.append(abs(sol - truth))
                clamped = abs(abs(truth) - SHIFT_BOUND) < 1e-9 and abs(abs(sur) - SHIFT_BOUND) < 1e-9
                rows.append({"league": f["league"], "fixture": f["label"], "b_fixture": b,
                             "truth": truth, "truth_monotone": mono, "residual": resid,
                             "p_base": pbase[i], "surrogate": sur, "solver": sol,
                             "clamp_artifact": clamped})
                print(f"{f['league']:15s} {f['label'][:30]:30s} {truth:+8.4f} {sur:+8.4f} "
                      f"{abs(sur-truth):7.4f} {sol:+8.4f} {abs(sol-truth):7.4f}"
                      f"{'  <- CLAMP' if clamped else ''}", flush=True)
            keep = [i for i, r in enumerate(rows) if not r["clamp_artifact"]]
            gaps = [abs(r["truth"] - r["truth_monotone"]) for r in rows]
            b_test = [r["b_fixture"] for r in rows]
            print(f"\n   surrogate mean |err| {stats.mean(sur_e):.4f}   solver {stats.mean(sol_e):.4f}   n={len(rows)}")
            if keep and len(keep) < len(rows):
                print(f"   EXCLUDING clamp artifacts: surrogate "
                      f"{stats.mean([sur_e[i] for i in keep]):.4f}   solver "
                      f"{stats.mean([sol_e[i] for i in keep]):.4f}   n={len(keep)}")
                print("   ^ a fixture with BOTH truth and surrogate pinned at the bound scores")
                print("     0.0000 by SATURATION, not accuracy. Report it separately.")
            print(f"   slope bias: b_test {stats.mean(b_test):.3f} vs b_train {b_train:.3f} "
                  f"({stats.mean(b_test)-b_train:+.3f})")
            print(f"   REFERENCE uncertainty (fitted vs monotone) mean {stats.mean(gaps):.4f} "
                  f"max {max(gaps):.4f} -- compare to the errors above before claiming a winner")
            payload = {"mode": "heldout", "b_train": b_train, "rows": rows,
                       "surrogate_mean_abs_err": stats.mean(sur_e),
                       "solver_mean_abs_err": stats.mean(sol_e)}

    print(f"\n{time.perf_counter()-started:.0f}s")
    out = Path(args.out) if args.out else REPO_ROOT / "reports" / "soccer_anchor_backtest" / f"shift_{args.mode}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, default=float), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
