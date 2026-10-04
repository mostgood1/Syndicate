"""Fit and validate `nba_prop_calibration.json` (lane `nba-prop-calibration`).

Data: the as-of 2025-26 smart-sim output and actuals collected by `scripts/backtest_nba_lines_props.py`
(run it first; this reads its `--out` cache). Each row is one smart-sim player-game that played, with the sim's
per-stat mean / sd / minutes, the actual box line, and the player's season-to-date rate from games strictly
before the date -- the same quantities `nba_prop_calibration.own_rates` builds from `boxscores_history.csv`.

Method (every transform goes through `syndicate.features.shared.nba_prop_calibration`'s own functions):
  1. TRAIN = smart-sim regular-season dates < --split; TEST = later regular-season dates + playoffs.
  2. Fit w_s (rate shrink, grid over W_BOUNDS) by test-free MAE on TRAIN; players with < MIN_GAMES prior
     games keep the sim mean, exactly as the module does.
  2b. Fit b_s (season-average blend weight on the shrunk mean, grid over B_BOUNDS) by MAE on TRAIN, after w.
  3. Fit k_s (sd scale, grid over K_BOUNDS) by CRPS on TRAIN over the whole predictive distribution, with the
     FINAL mean -- so k is fit for the mean it will be paired with. (A log-loss fit at one book-like line runs to
     the grid edge; see fit().)
  The previous estimator (no blend) is fit and scored beside it, so the blend's increment is measured, not assumed.
  4. Score TEST with the TRAIN constants: MAE vs the served sim and vs the own average; Brier vs the served
     Normal and vs the own-average distribution; game-clustered 95% CIs. pr/pa/ra are scored through
     `combo_scale` (the edges' independence sigma).
  5. Refit on ALL rows -> the production constants written by --write.

Usage:
  py -3 scripts/fit_nba_prop_calibration.py --bt-out C:/tmp/nba_bt/out --write C:/tmp/nba_bt/nba_prop_calibration.json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from syndicate.features.shared import nba_prop_calibration as cal  # noqa: E402

COMBOS = {"pra": ("pts", "reb", "ast"), "pr": ("pts", "reb"), "pa": ("pts", "ast"), "ra": ("reb", "ast")}


def _load_bt():
    spec = importlib.util.spec_from_file_location("_bt_nba", REPO / "scripts" / "backtest_nba_lines_props.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def collect(bt, out: Path) -> List[Dict]:
    class A:  # the harness's args shape
        pass
    a = A()
    a.out = out
    dates = bt._dates(bt.RS_START, bt.PO_END)
    sb = bt.fetch_scoreboards(a, dates)  # cached
    phase_of = {}
    from collections import Counter
    for d, gs in sb.items():
        st = Counter(g["season_type"] for g in gs).most_common(1)[0][0]
        phase_of[d] = "regular" if st == 2 and d <= bt.RS_END else ("playoff" if st == 3 else f"type{st}")
    manifest = json.loads((out / "asof_manifest.json").read_text(encoding="utf-8"))
    hist = bt.History(bt.fetch_player_logs(a))
    rows, counts = bt._collect_sim_players(a, manifest, hist, phase_of)
    print(f"collected {len(rows)} player-games; {dict(counts)}", flush=True)
    return rows


def mean_after(r: Dict, s: str, w: Dict[str, float], b: Dict[str, float] = None) -> float:
    """Final mean via the module's own estimator: rate shrink (w), then season-average blend (b); pra moves by
    the pts+reb+ast deltas; pr/pa/ra are sums. Players with < MIN_GAMES prior games keep the sim mean."""
    b = b or {}
    if s in COMBOS:
        if s != "pra":
            return sum(mean_after(r, p, w, b) for p in COMBOS[s])
        if all(p in w or p in b for p in COMBOS["pra"]):
            return r["mean"]["pra"] + sum(mean_after(r, p, w, b) - r["mean"][p] for p in COMBOS["pra"])
        return r["mean"]["pra"]
    m = r["mean"][s]
    if (s not in w and s not in b) or r["proj_min"] <= 0 or r["n_prior"] < cal.MIN_GAMES:
        return m
    t = cal.shrink_mean(m, r["proj_min"], r["per_min"][s], w[s]) if s in w else m
    return cal.blend_mean(t, r["base"][s], b[s]) if s in b else t


def sd_after(r: Dict, s: str, k: Dict[str, float], scaled: bool = True) -> float:
    if s in COMBOS and s != "pra":
        sds = {p: r["sd"][p] for p in COMBOS[s]}
        base = math.sqrt(sum(v ** 2 for v in sds.values()))
        if not scaled:
            return base
        kk = cal.combo_scale(COMBOS[s], sds, k)
        return base * (kk if kk is not None else 1.0)
    sd = r["sd"][s]
    return sd * (k.get(s, 1.0) if scaled else 1.0)


def actual(r: Dict, s: str) -> float:
    return sum(r["act"][p] for p in COMBOS[s]) if s in COMBOS and s != "pra" else r["act"][s]


def own_avg(r: Dict, s: str) -> float:
    return sum(r["base"][p] for p in COMBOS[s]) if s in COMBOS and s != "pra" else r["base"][s]


def p_over(line: float, mu: float, sd: float) -> float:
    return 1 - 0.5 * (1 + math.erf((line - mu) / (sd * math.sqrt(2))))


def _ll(p: float, y: int) -> float:
    p = min(1 - 1e-3, max(1e-3, p))
    return -(math.log(p) if y else math.log(1 - p))


def _usable(r: Dict, s: str) -> bool:
    parts = COMBOS[s] if s in COMBOS and s != "pra" else (s,)
    return all((r["sd"].get(p) or 0) > 0.05 for p in parts)


def fit(rows: List[Dict], use_blend: bool = True) -> Dict[str, Dict[str, float]]:
    wgrid = [round(i * 0.05, 2) for i in range(int(cal.W_BOUNDS[1] / 0.05) + 1)]
    kgrid = [round(cal.K_BOUNDS[0] + i * 0.05, 2) for i in range(int((cal.K_BOUNDS[1] - cal.K_BOUNDS[0]) / 0.05) + 1)]
    w: Dict[str, float] = {}
    for s in cal.RATE_STATS:
        w[s] = min(wgrid, key=lambda x: sum(abs(mean_after(r, s, {s: x}) - actual(r, s)) for r in rows))
    # season-average blend, fit AFTER w on the shrunk mean (b = weight kept on the shrunk sim mean)
    b: Dict[str, float] = {}
    if use_blend:
        bgrid = [round(i * 0.05, 2) for i in range(int(cal.B_BOUNDS[1] / 0.05) + 1)]
        for s in cal.RATE_STATS:
            b[s] = min(bgrid, key=lambda x: sum(abs(mean_after(r, s, w, {s: x}) - actual(r, s)) for r in rows))
    # k by CRPS over the WHOLE predictive distribution. A log-loss fit at one book-like line runs to the grid
    # edge (k = 3.0 measured): near that line the mean has little resolution, so flattening every probability
    # toward 0.5 wins there while ruining every alternate line -- the same trap lane wnba-prop-dispersion hit.
    k: Dict[str, float] = {}
    for s in cal.SD_STATS:
        q = [r for r in rows if _usable(r, s)]
        pre = [(mean_after(r, s, w, b), sd_after(r, s, {}, scaled=False), actual(r, s)) for r in q]
        k[s] = min(kgrid, key=lambda x: sum(crps_normal(mu, sd * x, y) for mu, sd, y in pre))
    return {"w": w, "b": b, "k": k}


def crps_normal(mu: float, sd: float, y: float) -> float:
    """Closed-form CRPS of N(mu, sd) at y (lower is better; a proper score for the whole distribution)."""
    z = (y - mu) / sd
    pdf = math.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)
    cdf = 0.5 * (1 + math.erf(z / math.sqrt(2)))
    return sd * (z * (2 * cdf - 1) + 2 * pdf - 1 / math.sqrt(math.pi))


def evaluate(bt, rows: List[Dict], c: Dict[str, Dict[str, float]]) -> Dict:
    w, b, k = c["w"], c.get("b") or {}, c["k"]
    res = {}

    def ci(v):
        p, lo, hi = bt._boot_ci(v)
        return {"point": round(p, 5), "ci95": [round(lo, 5), round(hi, 5)]}
    for s in list(cal.SD_STATS) + ["pr", "pa", "ra"]:
        q = [r for r in rows if _usable(r, s)]
        if not q:
            continue
        e_cal = [(r["gid"], abs(mean_after(r, s, w, b) - actual(r, s)) - abs(mean_after(r, s, {}) - actual(r, s))) for r in q]
        e_avg = [(r["gid"], abs(mean_after(r, s, w, b) - actual(r, s)) - abs(own_avg(r, s) - actual(r, s))) for r in q]
        b_srv, b_avg = [], []
        for r in q:
            L = math.floor(own_avg(r, s)) + 0.5
            y = int(actual(r, s) > L)
            p_cal = p_over(L, mean_after(r, s, w, b), sd_after(r, s, k))
            p_srv = p_over(L, mean_after(r, s, {}), sd_after(r, s, k, scaled=False))
            p_own = p_over(L, own_avg(r, s), sd_after(r, s, k))
            b_srv.append((r["gid"], (p_cal - y) ** 2 - (p_srv - y) ** 2))
            b_avg.append((r["gid"], (p_cal - y) ** 2 - (p_own - y) ** 2))

        c_d = [(r["gid"], crps_normal(mean_after(r, s, w, b), sd_after(r, s, k), actual(r, s))
                - crps_normal(mean_after(r, s, {}), sd_after(r, s, k, scaled=False), actual(r, s))) for r in q]
        res[s] = {"n": len(q), "games": len({r["gid"] for r in q}), "dCRPS_vs_served": ci(c_d),
                  "dMAE_vs_served": ci(e_cal), "dMAE_vs_own_avg": ci(e_avg),
                  "dBrier_vs_served": ci(b_srv), "dBrier_vs_own_avg_dist": ci(b_avg)}
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bt-out", type=Path, default=Path(r"C:\tmp\nba_bt\out"))
    ap.add_argument("--split", default="2026-03-01")
    ap.add_argument("--write", type=Path, default=None, help="write the production factor file (fit on ALL rows)")
    args = ap.parse_args()
    bt = _load_bt()
    rows = collect(bt, args.bt_out)
    train = [r for r in rows if r["phase"] == "regular" and r["date"] < args.split]
    test = [r for r in rows if (r["phase"] == "regular" and r["date"] >= args.split) or r["phase"] == "playoff"]
    print(f"train {len(train)} rows / {len({r['gid'] for r in train})} games; test {len(test)} rows / "
          f"{len({r['gid'] for r in test})} games", flush=True)
    c_train = fit(train)
    oos = evaluate(bt, test, c_train)
    c_train_nb = fit(train, use_blend=False)          # the previous (shrink + width only) estimator, for the increment
    oos_nb = evaluate(bt, test, c_train_nb)
    c_all = fit(rows)
    report = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "split": args.split,
              "train": {"rows": len(train), "games": len({r["gid"] for r in train})},
              "test": {"rows": len(test), "games": len({r["gid"] for r in test})},
              "constants_train": c_train, "oos_with_train_constants": oos,
              "constants_train_no_blend": c_train_nb, "oos_no_blend": oos_nb, "constants_all": c_all}
    print(json.dumps(report, indent=1), flush=True)
    (args.bt_out / "fit_nba_prop_calibration.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    if args.write:
        doc = {"w": c_all["w"], "blend": c_all["b"], "sd_scale": c_all["k"],
               "provenance": {"script": "scripts/fit_nba_prop_calibration.py", "generated_at": report["generated_at"],
                              "rows": len(rows), "games": len({r["gid"] for r in rows}),
                              "season": "2025-26 smart-sim (2026-01-21..2026-06-13), pre-tip committed output",
                              "oos_split": args.split}}
        args.write.write_text(json.dumps(doc, indent=1), encoding="utf-8")
        print(f"wrote {args.write}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
