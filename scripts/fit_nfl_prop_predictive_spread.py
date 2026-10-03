"""Fit: a PREDICTIVE spread for NFL continuous prop markets, re-fitting the constants it sits on.

Lane `nfl-prop-predictive-spread` (2026-10-03). Measurement only: this script edits nothing in
production. It decides WHAT to change in `player_stats.py` / `props.py`; the change is a later step.

WHY. Lane `nfl-lines-props-backtest` (findings 2026-10-02, section 7) measured the NFL prop loss vs
the de-vigged book as RELIABILITY, not resolution: Murphy reliability 10-300x the book's, resolution
at or above it. A flat x2.5-3 on the spread closed 56-74% of the 2025 Brier gap for receptions and
receiving_yards. A flat k is a symptom fit. The hypothesis is a MECHANISM: the probability at the
line treats the season-to-date rate as KNOWN, but a player's true level drifts with role and usage.

ARMS, per market (all through production's own Normal + `_lognormal_cover_probability` mixture):
  prod       production exactly (current spread-shrinkage K, current blend weight)
  flat_k     sd' = k*sd                                   (the diagnosis benchmark)
  sampling   sd' = sd*sqrt(1+1/n)                         (rate SAMPLING error only)
  drift      sd' = sqrt(sd^2 + (c*mean)^2)                (rate DRIFT, c = drift as a share of the mean)
  drift_refit  drift with spread-shrinkage K in {off,3,6,12} and blend weight in {0,.25,.5,.75,1}
               re-fitted JOINTLY with c, which `model_engine_standard.md` requires when a mechanism
               is added to a calibrated engine
Every parameter is chosen on 2023-2024 ONLY, by Brier. Scored on held-out 2025 and on 2026 wk2:
Brier, the gap to the de-vigged book closed, paired game-clustered CIs vs production and vs the book,
Murphy reliability/resolution, and the CALIBRATION SLOPE of logistic(y ~ a + b*logit(p)). A slope
far below 1 means the change is shrinking a weak signal toward the base rate rather than fixing the
spread. That is a peer's MLB caution (2026-10-03), and it looks identical in the Brier column.

CONTROL. At (production K, c=0, production blend) the arm must reproduce production's
`_nfl_prop_model_probability` on every row (max |diff| asserted < 1e-9). Otherwise nothing below
grades the served model.

PRE-REGISTERED (lane block): MET if, for receptions AND receiving_yards, the chosen arm closes >= 50%
of the 2025 gap, and no continuous market's 2025 Brier gets worse vs prod with a CI excluding 0.
FALSIFIED (mechanism wrong) if the drift arm closes < 30% for those two while flat_k closes more.

Usage:
  py -3 scripts/fit_nfl_prop_predictive_spread.py --root C:/tmp/nflbt/root/nfl_source --out C:/tmp/nflbt/spread
"""
from __future__ import annotations

import argparse
import json
import math
import os
import pickle
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("bt_lines_props", REPO / "scripts" / "backtest_nfl_lines_props.py")
bt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bt)  # type: ignore[union-attr]

CONTINUOUS = ("receptions", "receiving_yards", "rushing_yards", "rushing_attempts", "passing_yards", "passing_attempts")
K_VARIANTS = ("prod", "off", 3.0, 6.0, 12.0)
C_GRID = tuple(round(0.1 * i, 2) for i in range(0, 31))          # drift share of the mean, 0..3.0
W_GRID = (0.0, 0.25, 0.5, 0.75, 1.0)
FLATK_GRID = (0.4, 0.5, 0.7, 0.85, 1.0, 1.15, 1.3, 1.5, 1.75, 2.0, 2.5, 3.0, 4.0)
FIT, HOLDOUT, CURRENT = (2023, 2024), (2025,), (2026,)


# ---------------------------------------------------------------------------
# rows
# ---------------------------------------------------------------------------

def build_rows(root: Path, out: Path) -> Dict[str, List[Dict[str, Any]]]:
    cache = out / "prop_rows.pkl"
    if cache.exists():
        with cache.open("rb") as fh:
            return pickle.load(fh)
    sched = bt.load_schedule(root)
    seasons = [2023, 2024, 2025, 2026]
    bt.score_props(root, sched, seasons, {"all": seasons}, min_n=30)
    rows = {s: list(bt._SELF["prob_rows"].get(s, [])) for s in CONTINUOUS}
    with cache.open("wb") as fh:
        pickle.dump(rows, fh)
    return rows


def spread_variants(rows: Dict[str, List[Dict[str, Any]]]) -> Dict[Tuple, Dict[Any, Optional[float]]]:
    """sd under each spread-shrinkage variant, recomputed through production's `player_rate_with_prior`
    with its module constants patched (restored after). Keyed by (season, week, pid, stat)."""
    from syndicate.features.nfl import player_stats as ps
    keys = {(r["season"], r["week"], r["pid"], s) for s, rr in rows.items() for r in rr}
    out: Dict[Tuple, Dict[Any, Optional[float]]] = {k: {} for k in keys}
    k0, by0 = ps.SPREAD_SHRINKAGE_K, dict(ps.SPREAD_SHRINKAGE_K_BY_MARKET)
    env0 = os.environ.get("SYNDICATE_NFL_SPREAD_SHRINKAGE")
    try:
        for var in K_VARIANTS:
            ps.SPREAD_SHRINKAGE_K, ps.SPREAD_SHRINKAGE_K_BY_MARKET = k0, dict(by0)
            os.environ.pop("SYNDICATE_NFL_SPREAD_SHRINKAGE", None)
            if var == "off":
                os.environ["SYNDICATE_NFL_SPREAD_SHRINKAGE"] = "off"
            elif var != "prod":
                ps.SPREAD_SHRINKAGE_K = float(var)
                ps.SPREAD_SHRINKAGE_K_BY_MARKET = {}
            for (season, week, pid, stat) in keys:
                _m, sd, _n, _src = ps.player_rate_with_prior(season, week, pid, stat)
                out[(season, week, pid, stat)][var] = sd
    finally:
        ps.SPREAD_SHRINKAGE_K, ps.SPREAD_SHRINKAGE_K_BY_MARKET = k0, by0
        if env0 is None:
            os.environ.pop("SYNDICATE_NFL_SPREAD_SHRINKAGE", None)
        else:
            os.environ["SYNDICATE_NFL_SPREAD_SHRINKAGE"] = env0
    return out


# ---------------------------------------------------------------------------
# probability: production's own components, mixed with a chosen weight
# ---------------------------------------------------------------------------

def components(mean: float, sd: float, line: float) -> Tuple[float, Optional[float]]:
    from syndicate.features.nfl import props as P
    normal = 1.0 - statistics.NormalDist(mean, sd).cdf(line)
    return normal, P._lognormal_cover_probability(mean, sd, line)


def mix(normal: float, logn: Optional[float], w: float) -> float:
    # identical to `_nfl_prop_model_probability`'s continuous branch, including its fallback
    if w <= 0.0 or logn is None:
        return normal
    return (1.0 - w) * normal + w * logn


def sd_for(arm: Dict[str, Any], r: Dict[str, Any], sdv: Dict[Any, Optional[float]]) -> Optional[float]:
    sd = sdv.get(arm.get("K", "prod"))
    if sd is None or sd <= 0:
        return None
    kind = arm["kind"]
    if kind == "flat_k":
        return sd * arm["k"]
    if kind == "sampling":
        return sd * math.sqrt(1.0 + 1.0 / max(1, r["n"]))
    if kind in ("drift", "drift_refit"):
        return math.sqrt(sd * sd + (arm["c"] * max(0.0, r["mean"])) ** 2)
    return sd


def prob(arm: Dict[str, Any], r: Dict[str, Any], sdv: Dict[Any, Optional[float]], w_prod: float) -> Optional[float]:
    sd = sd_for(arm, r, sdv)
    if sd is None:
        return None
    n_, l_ = components(r["mean"], sd, r["line"])
    return mix(n_, l_, arm.get("w", w_prod))


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------

def _logit(p: float) -> float:
    p = bt._clip(p)
    return math.log(p / (1 - p))


def calibration_slope(ps: List[float], ys: List[int]) -> Tuple[float, float]:
    """logistic(y ~ a + b*logit(p)) by Newton; (a, b). b=1, a=0 is perfect calibration."""
    xs = [_logit(p) for p in ps]
    a, b = 0.0, 1.0
    for _ in range(50):
        ga = gb = haa = hab = hbb = 0.0
        for x, y in zip(xs, ys):
            q = 1 / (1 + math.exp(-(a + b * x)))
            ga += y - q
            gb += (y - q) * x
            w = q * (1 - q)
            haa += w
            hab += w * x
            hbb += w * x * x
        det = haa * hbb - hab * hab
        if det <= 0:
            break
        da = (hbb * ga - hab * gb) / det
        db = (haa * gb - hab * ga) / det
        a, b = a + da, b + db
        if abs(da) < 1e-8 and abs(db) < 1e-8:
            break
    return round(a, 4), round(b, 4)


def brier(rows, ps) -> float:
    return sum((bt._clip(p) - r["y"]) ** 2 for r, p in zip(rows, ps)) / len(rows)


def evaluate(rows: List[Dict[str, Any]], ps: List[float], ps_prod: List[float]) -> Dict[str, Any]:
    b_model = brier(rows, ps)
    b_prod = brier(rows, ps_prod)
    b_book = sum((r["p_book"] - r["y"]) ** 2 for r in rows) / len(rows)
    d_book = bt.boot_ci([(r["gid"], (bt._clip(p) - r["y"]) ** 2 - (r["p_book"] - r["y"]) ** 2) for r, p in zip(rows, ps)])
    d_prod = bt.boot_ci([(r["gid"], (bt._clip(p) - r["y"]) ** 2 - (bt._clip(q) - r["y"]) ** 2) for r, p, q in zip(rows, ps, ps_prod)])
    gap = b_prod - b_book
    a, b = calibration_slope(ps, [r["y"] for r in rows])
    return {"n": len(rows), "games": len({r["gid"] for r in rows}), "brier": round(b_model, 5),
            "brier_prod": round(b_prod, 5), "brier_book": round(b_book, 5),
            "gap_closed_pct": round(100 * (b_prod - b_model) / gap, 1) if gap > 0 else None,
            "dbrier_vs_prod": {"point": round(d_prod[0], 5), "ci95": [round(d_prod[1], 5), round(d_prod[2], 5)]},
            "dbrier_vs_book": {"point": round(d_book[0], 5), "ci95": [round(d_book[1], 5), round(d_book[2], 5)]},
            "calibration_intercept": a, "calibration_slope": b,
            "murphy": bt.murphy([bt._clip(p) for p in ps], [r["y"] for r in rows]),
            "mean_p": round(statistics.fmean(ps), 4), "base_rate": round(statistics.fmean(r["y"] for r in rows), 4)}


def fit_market(stat: str, rows: List[Dict[str, Any]], sdv: Dict[Tuple, Dict[Any, Optional[float]]]) -> Dict[str, Any]:
    from syndicate.features.nfl import props as P
    w_prod = P._COVER_PROBABILITY_BLEND_WEIGHT.get(stat, 0.0)
    key = lambda r: (r["season"], r["week"], r["pid"], stat)  # noqa: E731
    usable = [r for r in rows if sdv[key(r)].get("prod")]
    F = bt._sub([r for r in usable if r["season"] in FIT], cap=20000)
    prod_arm = {"kind": "prod"}

    # CONTROL: the arm machinery at production settings == production's function, every row
    worst = 0.0
    for r in usable:
        mine = prob(prod_arm, r, sdv[key(r)], w_prod)
        theirs = P._nfl_prop_model_probability(stat=stat, mean=r["mean"], stdev=sdv[key(r)]["prod"], n=r["n"], line=r["line"])
        if theirs is None or mine is None:
            continue
        worst = max(worst, abs(mine - theirs), abs(theirs - r["p_model"]))
    assert worst < 1e-9, f"{stat}: control failed, max |diff| {worst}"

    def fit_brier(arm):
        tot = cnt = 0
        for r in F:
            p = prob(arm, r, sdv[key(r)], w_prod)
            if p is None:
                continue
            tot += (bt._clip(p) - r["y"]) ** 2
            cnt += 1
        return tot / cnt if cnt else float("inf")

    arms: Dict[str, Dict[str, Any]] = {"prod": prod_arm}
    arms["flat_k"] = min(({"kind": "flat_k", "k": k} for k in FLATK_GRID), key=fit_brier)
    arms["sampling"] = {"kind": "sampling"}
    arms["drift"] = min(({"kind": "drift", "c": c} for c in C_GRID), key=fit_brier)
    # joint: K x c x w. Components are computed once per (K, c); the w grid is a cheap remix.
    best, best_b = None, float("inf")
    for K in K_VARIANTS:
        for c in C_GRID:
            comp = []
            for r in F:
                sd = sd_for({"kind": "drift", "c": c, "K": K}, r, sdv[key(r)])
                comp.append(None if sd is None else components(r["mean"], sd, r["line"]))
            for w in W_GRID:
                tot = cnt = 0
                for r, cp in zip(F, comp):
                    if cp is None:
                        continue
                    tot += (bt._clip(mix(cp[0], cp[1], w)) - r["y"]) ** 2
                    cnt += 1
                b = tot / cnt if cnt else float("inf")
                if b < best_b:
                    best, best_b = {"kind": "drift_refit", "K": K, "c": c, "w": w}, b
    arms["drift_refit"] = best

    out: Dict[str, Any] = {"w_prod": w_prod, "n_usable": len(usable), "n_fit_rows_used": len(F),
                           "control_max_abs_diff": worst, "arms": {}}
    for name, arm in arms.items():
        A: Dict[str, Any] = {"params": arm, "fit_brier": round(fit_brier(arm), 5)}
        for label, seasons in (("2025 holdout", HOLDOUT), ("2026 in-season", CURRENT)):
            T = [r for r in usable if r["season"] in seasons]
            if len(T) < 50:
                A[label] = {"n": len(T), "status": "INSUFFICIENT_N"}
                continue
            ps = [prob(arm, r, sdv[key(r)], w_prod) for r in T]
            pp = [prob(prod_arm, r, sdv[key(r)], w_prod) for r in T]
            keep = [i for i, (p, q) in enumerate(zip(ps, pp)) if p is not None and q is not None]
            A[label] = evaluate([T[i] for i in keep], [ps[i] for i in keep], [pp[i] for i in keep])
        out["arms"][name] = A
    chosen = min((a for a in out["arms"] if a != "prod"), key=lambda a: out["arms"][a]["fit_brier"])
    out["chosen_by_fit_brier"] = chosen
    return out


def verdict(markets: Dict[str, Any]) -> Dict[str, Any]:
    def hold(stat, arm):
        return markets[stat]["arms"][arm]["2025 holdout"]
    met_two = all((hold(s, markets[s]["chosen_by_fit_brier"]).get("gap_closed_pct") or 0) >= 50
                  for s in ("receptions", "receiving_yards"))
    worse = [s for s in markets if hold(s, markets[s]["chosen_by_fit_brier"])["dbrier_vs_prod"]["ci95"][0] > 0]
    falsified = all((hold(s, "drift").get("gap_closed_pct") or 0) < 30 and
                    (hold(s, "flat_k").get("gap_closed_pct") or 0) > (hold(s, "drift").get("gap_closed_pct") or 0)
                    for s in ("receptions", "receiving_yards"))
    return {"receptions_and_receiving_closed_ge_50pct": met_two, "markets_worse_than_prod_ci": worse,
            "mechanism_falsified": falsified,
            "PRE_REGISTERED_RESULT": "MET" if met_two and not worse else ("FALSIFIED" if falsified else "NOT MET")}


def write_md(rep: Dict[str, Any], path: Path) -> None:
    L = ["# NFL prop predictive-spread fit", "", f"generated {rep['generated_at']}; fit {list(FIT)}, scored on 2025 holdout and 2026 wk2", "",
         f"**pre-registered verdict:** `{json.dumps(rep['verdict'])}`", ""]
    for stat, M in rep["markets"].items():
        L += [f"## {stat} (prod blend w={M['w_prod']}; chosen by fit Brier: **{M['chosen_by_fit_brier']}**; control max|diff| {M['control_max_abs_diff']:.1e})", "",
              "| arm | params | 2025 n | Brier | prod | book | gap closed % | d vs prod [CI] | d vs book [CI] | slope (int) | Murphy rel/res | 2026 gap closed % | 2026 slope |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for name, A in M["arms"].items():
            h, c = A["2025 holdout"], A.get("2026 in-season", {})
            if "brier" not in h:
                continue
            L.append(f"| {name} | `{json.dumps({k: v for k, v in A['params'].items() if k != 'kind'})}` | {h['n']} | {h['brier']} | {h['brier_prod']} | {h['brier_book']} | "
                     f"{h['gap_closed_pct']} | {bt._fmt_ci(h['dbrier_vs_prod'])} | {bt._fmt_ci(h['dbrier_vs_book'])} | {h['calibration_slope']} ({h['calibration_intercept']}) | "
                     f"{h['murphy'].get('reliability')}/{h['murphy'].get('resolution')} | {c.get('gap_closed_pct', '')} | {c.get('calibration_slope', '')} |")
        L.append("")
    path.write_text("\n".join(L), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--markets", default=",".join(CONTINUOUS))
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    env = bt.configure_env(a.root.resolve())
    bt._patch_game_log_cache()
    rows = build_rows(a.root.resolve(), a.out)
    markets = [m for m in a.markets.split(",") if m]
    sdv = spread_variants({m: rows[m] for m in markets})
    rep: Dict[str, Any] = {"generated_at": datetime.now(timezone.utc).isoformat(), "env": env, "markets": {}}
    for m in markets:
        print(f"[fit] {m}: {len(rows[m])} rows", flush=True)
        rep["markets"][m] = fit_market(m, rows[m], sdv)
        (a.out / "fit_nfl_prop_predictive_spread.json").write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    rep["verdict"] = verdict(rep["markets"]) if set(("receptions", "receiving_yards")) <= set(markets) else {}
    (a.out / "fit_nfl_prop_predictive_spread.json").write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    write_md(rep, a.out / "fit_nfl_prop_predictive_spread.md")
    print(json.dumps(rep["verdict"]), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
