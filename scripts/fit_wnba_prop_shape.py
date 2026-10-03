"""A per-player count SHAPE for WNBA rebounds, assists and threes ladders (lane `wnba-prop-shape`).

WHY. After fixes #2 (availability) and #3 (rate shrink) the prop MEAN is right, and widening the sim ladder does
nothing for these three markets -- yet the player's own average with the player's own spread prices the book line
better than the sim ladder (rebounds 0.2494 vs 0.2524, assists 0.2511 vs 0.2556, threes 0.2466 vs 0.2524; lane
`wnba-prop-dispersion` section 6). For low counts the sim's draw-shape is the defect, not its width.

THE CANDIDATE, exactly as the engine would apply it. Keep the stack's mean m (the sim's `<stat>_mean` after fix #3);
replace the ladder's shape by a negative binomial with mean m and variance D * m, where
    D = (n * D_own + k * D_league) / (n + k)
    D_own    = variance / mean of the player's own counts over games STRICTLY before tip (MIN > 0, n >= 2)
    D_league = the same ratio pooled over every player-game before the split date (fixed; stated as such)
and D <= 1 collapses to Poisson (no under-dispersed family is fitted). One k per stat on a grid, chosen on May-July by
the RANKED PROBABILITY SCORE over the whole distribution -- NOT by the book line, where a flatter forecast always
looks better (lane `wnba-prop-dispersion`, section 2).

REPORTED, held out (Aug-Sep regular; playoffs): Brier at the book line for the NB vs the sim ladder vs the own-average
normal vs the book, paired game-clustered CIs; RPS NB vs sim ladder; reliability deciles at the book line.

Usage (WSL): python scripts/fit_wnba_prop_shape.py --archive ~/wnba_bt/stack --espn-dir ... --box-dir ... --odds-dir ...
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import statistics
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("bt_wnba", REPO / "scripts" / "backtest_wnba_lines_props.py")
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)  # type: ignore[union-attr]

STATS = {"reb": ("REB", "player_rebounds"), "ast": ("AST", "player_assists"), "threes": ("FG3M", "player_threes")}
K_GRID = [0.0, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 1e9]       # 1e9 = league dispersion only
MAX_T = 60


def nb_pmf(m: float, d: float, upto: int = MAX_T) -> List[float]:
    """P(X = x), x = 0..upto. Mean m, variance d*m; d <= 1 -> Poisson. Normalised over the truncated support."""
    m = max(1e-6, float(m))
    out: List[float] = []
    if d <= 1.0 + 1e-9:
        for x in range(upto + 1):
            out.append(math.exp(-m + x * math.log(m) - math.lgamma(x + 1)))
    else:
        r = m / (d - 1.0)
        p = r / (r + m)
        for x in range(upto + 1):
            out.append(math.exp(math.lgamma(x + r) - math.lgamma(r) - math.lgamma(x + 1) + r * math.log(p) + x * math.log(1 - p)))
    s = sum(out)
    return [v / s for v in out]


def p_over_pmf(pmf: List[float], line: float) -> float:
    thr = math.floor(float(line)) + 1
    return sum(pmf[thr:]) if thr < len(pmf) else 0.0


def rps_pmf(pmf: List[float], y: float) -> float:
    s, surv = 0.0, 1.0
    for t in range(1, len(pmf)):
        surv -= pmf[t - 1]
        s += (surv - (1.0 if y >= t else 0.0)) ** 2
    return s


def dist_to_pmf(dist: Dict[int, float], upto: int = MAX_T) -> List[float]:
    tot = sum(dist.values()) or 1.0
    pmf = [0.0] * (upto + 1)
    for v, m in dist.items():
        pmf[min(max(int(v), 0), upto)] += m / tot
    return pmf


def shrunk_d(counts: List[float], d_league: float, k: float) -> float:
    n = len(counts)
    if n < 2:
        return d_league
    mu = statistics.fmean(counts)
    d_own = (statistics.pvariance(counts) / mu) if mu > 0 else d_league
    return (n * d_own + k * d_league) / (n + k)


def load_rows(archive: Path, games: Dict, box: Dict, hist, book: Dict) -> List[Dict]:
    idx = B._pair_index(games)
    rows: List[Dict] = []
    cnt = Counter()
    for p in sorted(archive.glob("*/smart_sim_*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        gid = B.match_game(idx, str(d.get("date")), str(d.get("home")).upper(), str(d.get("away")).upper())
        if not gid:
            continue
        g = games[gid]
        for side in ("home", "away"):
            for pl in (d.get("players") or {}).get(side) or []:
                pk = B.norm_name(pl.get("player_name"))
                act = box.get(gid, {}).get(pk)
                if not act:
                    continue
                prior = [r for t, r in hist.player.get(pk, []) if t < g["tip"]]
                lad = pl.get("prop_ladders") if isinstance(pl.get("prop_ladders"), dict) else {}
                for s, (col, mk) in STATS.items():
                    blk = lad.get(s)
                    m = pl.get(f"{s}_mean")
                    if not isinstance(blk, dict) or not isinstance(blk.get("distribution"), dict) or m is None:
                        continue
                    b = (book.get(gid) or {}).get("props", {}).get((pk, mk))
                    counts = [r[col] for r in prior]
                    rows.append({"gid": gid, "date": g["date"], "phase": g["phase"], "s": s, "m": float(m),
                                 "dist": {int(float(v)): float(c) for v, c in blk["distribution"].items()},
                                 "counts": counts, "y": act[col], "line": b["line"] if b else None,
                                 "p_book": b["p"] if b else None})
                    cnt[f"rows:{s}"] += 1
    print("load:", json.dumps(dict(cnt)), flush=True)
    return rows


def league_d(rows: List[Dict], split: str, s: str) -> float:
    """Pooled within-player variance / mean over player histories as of the split (train period only)."""
    num = den = 0.0
    seen = set()
    for r in rows:
        if r["s"] != s or r["date"] >= split:
            continue
        key = (id(r["counts"]), len(r["counts"]))
        if key in seen or len(r["counts"]) < 2:
            continue
        seen.add(key)
        mu = statistics.fmean(r["counts"])
        if mu > 0:
            num += statistics.pvariance(r["counts"]) * len(r["counts"])
            den += mu * len(r["counts"])
    return num / den if den else 1.0


def evaluate(rows: List[Dict], k: float, dl: float) -> Dict:
    nb_rps, sim_rps, at_line = [], [], []
    for r in rows:
        pmf = nb_pmf(r["m"], shrunk_d(r["counts"], dl, k))
        nb_rps.append((r["gid"], rps_pmf(pmf, r["y"])))
        sim_rps.append((r["gid"], rps_pmf(dist_to_pmf(r["dist"]), r["y"])))
        if r["line"] is not None and r["y"] != r["line"]:
            yy = int(r["y"] > r["line"])
            own_p = None
            if len(r["counts"]) >= 3:
                mu, sd = statistics.fmean(r["counts"]), statistics.pstdev(r["counts"])
                own_p = B.normal_over(mu, sd)(r["line"]) if sd > 0 else None
            at_line.append({"gid": r["gid"], "y": yy, "nb": B.clip(p_over_pmf(pmf, r["line"])),
                            "sim": B.clip(B.p_over_dist(r["dist"], r["line"]) if hasattr(B, "p_over_dist") else
                                          _p_over_dist(r["dist"], r["line"])),
                            "own": B.clip(own_p) if own_p is not None else None, "book": B.clip(r["p_book"])})
    return {"nb_rps": nb_rps, "sim_rps": sim_rps, "at_line": at_line}


def _p_over_dist(dist: Dict[int, float], line: float) -> float:
    thr = math.floor(float(line)) + 1
    tot = sum(dist.values()) or 1.0
    return sum(m for v, m in dist.items() if v >= thr) / tot


def summarize(e: Dict) -> Dict:
    out: Dict = {"n_rows": len(e["nb_rps"]),
                 "rps_nb": round(statistics.fmean(x for _, x in e["nb_rps"]), 5),
                 "rps_sim": round(statistics.fmean(x for _, x in e["sim_rps"]), 5),
                 "d_rps_nb_minus_sim": B.boot_ci([(g, a - b) for (g, a), (_g, b) in zip(e["nb_rps"], e["sim_rps"])])}
    L = e["at_line"]
    if L:
        sq = lambda key: [(x[key] - x["y"]) ** 2 for x in L]  # noqa: E731
        out.update({"book_n": len(L), "brier_nb": round(statistics.fmean(sq("nb")), 5),
                    "brier_sim": round(statistics.fmean(sq("sim")), 5), "brier_book": round(statistics.fmean(sq("book")), 5),
                    "d_brier_nb_minus_sim": B.boot_ci([(x["gid"], (x["nb"] - x["y"]) ** 2 - (x["sim"] - x["y"]) ** 2) for x in L]),
                    "d_brier_nb_minus_book": B.boot_ci([(x["gid"], (x["nb"] - x["y"]) ** 2 - (x["book"] - x["y"]) ** 2) for x in L]),
                    "reliability_nb": B.reliability([x["nb"] for x in L], [x["y"] for x in L], 10)})
        own = [x for x in L if x["own"] is not None]
        if own:
            out["brier_own_normal"] = round(statistics.fmean((x["own"] - x["y"]) ** 2 for x in own), 5)
            out["d_brier_nb_minus_own_normal"] = B.boot_ci([(x["gid"], (x["nb"] - x["y"]) ** 2 - (x["own"] - x["y"]) ** 2) for x in own])
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--archive", required=True)
    ap.add_argument("--espn-dir", required=True)
    ap.add_argument("--box-dir", required=True)
    ap.add_argument("--odds-dir", required=True)
    ap.add_argument("--split", default="2026-08-01")
    ap.add_argument("--out", required=True)
    ap.add_argument("--n-boot", type=int, default=2000)
    ap.add_argument("--write-artifact", default="")
    args = ap.parse_args(argv)
    _boot = B.boot_ci
    B.boot_ci = lambda rows, n_boot=args.n_boot, seed=7: _boot(rows, n_boot, seed)  # noqa: E731
    games = B.load_games(Path(args.espn_dir))
    box, _ = B.load_box(Path(args.box_dir), games)
    hist = B.History(games, box)
    book, _ = B.load_book(Path(args.odds_dir), games)
    rows = load_rows(Path(args.archive), games, box, hist, book)
    report: Dict = {"split": args.split, "stats": {}}
    for s in STATS:
        R = [r for r in rows if r["s"] == s]
        dl = league_d(R, args.split, s)
        train = [r for r in R if r["phase"] == "regular" and r["date"] < args.split]
        curve = [(k, statistics.fmean(x for _, x in evaluate(train, k, dl)["nb_rps"])) for k in K_GRID]
        k = min(curve, key=lambda t: t[1])[0]
        ent = {"d_league": round(dl, 4), "k": k, "k_at_grid_edge": k in (K_GRID[0], K_GRID[-1]),
               "fit_curve_rps": [(a, round(b, 5)) for a, b in curve]}
        for name, pf in (("train", lambda r: r["phase"] == "regular" and r["date"] < args.split),
                         ("test_regular", lambda r: r["phase"] == "regular" and r["date"] >= args.split),
                         ("test_playoff", lambda r: r["phase"] == "playoff")):
            sub = [r for r in R if pf(r)]
            if sub:
                ent[name] = summarize(evaluate(sub, k, dl))
        report["stats"][s] = ent
        t = ent.get("test_regular", {})
        print(f"{s:6s} D_league={dl:.3f} k={k}{' EDGE' if ent['k_at_grid_edge'] else ''} | test brier nb/sim/own/book="
              f"{t.get('brier_nb')}/{t.get('brier_sim')}/{t.get('brier_own_normal')}/{t.get('brier_book')} "
              f"d_nb-sim={t.get('d_brier_nb_minus_sim')} d_nb-book={t.get('d_brier_nb_minus_book')} "
              f"d_nb-own={t.get('d_brier_nb_minus_own_normal')} rps nb/sim={t.get('rps_nb')}/{t.get('rps_sim')} "
              f"d_rps={t.get('d_rps_nb_minus_sim')}", flush=True)
        po = ent.get("test_playoff", {})
        print(f"       playoffs n={po.get('book_n')} d_nb-sim={po.get('d_brier_nb_minus_sim')} d_rps={po.get('d_rps_nb_minus_sim')}", flush=True)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "shape_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    if args.write_artifact:
        doc = {"version": 1, "stats": {s: {"k": e["k"], "d_league": e["d_league"]} for s, e in report["stats"].items()
                                       if not (e["k_at_grid_edge"] and e["k"] == 0.0)},
               "fit": f"RPS over the whole distribution, regular season before {args.split}, fix #2+#3 stack",
               "producer": "scripts/fit_wnba_prop_shape.py", "lane": "wnba-prop-shape"}
        Path(args.write_artifact).write_text(json.dumps(doc, indent=1), encoding="utf-8")
        print(f"wrote {args.write_artifact}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
