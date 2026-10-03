"""Shrink the WNBA SmartSim's per-minute prop rates toward the player's own as-of rate (lane `wnba-sim-rate-shrink`).

WHY. With minutes fixed (lane `wnba-sim-availability`, held out: minutes bias -3.15 -> +0.15) the sim's points mean is
still worse than the player's own season average (+0.20 MAE), and ~80% of the sim's departures from that average are
noise (departure-signal slope 0.16-0.27, backtest 2026-10-02 section 3c). What is left is the per-minute RATE.

THE ESTIMATOR, exactly as the engine would apply it. For each player and component stat s (pts, reb, ast, threes):
    r_sim = sim mean / sim minutes          r_own = season stat total / season minutes, games STRICTLY before tip (>= 3)
    r     = r_own + w_s * (r_sim - r_own)   new mean m' = sim minutes * r          delta_s = m' - sim mean
and the ladder is SHIFTED by delta (v' = max(0, round_half_up(v + delta))), so its WIDTH is unchanged -- width is fix #1's
job and is re-fit after this. Combos shift by the sum of their components' deltas (PRA = pts+reb+ast, etc.). A player
without 3 prior games, or with no sim minutes, is left as the sim had it (w = 1).

FIT / TEST. w_s on a 0.00..1.20 grid by mean squared error of m' on regular-season dates before --split (default
2026-08-01), from AVAILABILITY-ON re-runs (the stack this would ship on). Test on/after --split and on the playoffs:
MAE vs actual for m' against (a) the raw sim and (b) the player's own season average (the backtest's baseline), paired
game-clustered CIs; Brier at the book line of the shifted ladder vs the raw ladder, read the board's way. A w at a
grid edge is reported as EDGE: w ~ 0 means the sim's rate carries nothing beyond the player's own rate.

Usage (WSL): python scripts/fit_wnba_sim_rate_shrink.py --archive ~/wnba_bt/avail_on --espn-dir ... --box-dir ... \\
                 --odds-dir ... --out ~/wnba_bt/rate_shrink
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("bt_wnba", REPO / "scripts" / "backtest_wnba_lines_props.py")
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)  # type: ignore[union-attr]

COMPONENTS = {"pts": "PTS", "reb": "REB", "ast": "AST", "threes": "FG3M"}
LADDER_PARTS = {"pts": ("pts",), "reb": ("reb",), "ast": ("ast",), "threes": ("threes",), "pra": ("pts", "reb", "ast"),
                "pr": ("pts", "reb"), "pa": ("pts", "ast"), "ra": ("reb", "ast")}
MARKET_OF = {v: k for k, v in B.LADDER_STAT.items()}            # ladder key -> OddsAPI market
W_GRID = [round(0.05 * i, 2) for i in range(25)]                 # 0.00 .. 1.20


def round_half_up(x: float) -> int:
    return int(math.floor(x + 0.5))


def shift(dist: Dict[int, float], delta: float) -> Dict[int, float]:
    out: Dict[int, float] = defaultdict(float)
    for v, m in dist.items():
        out[max(0, round_half_up(v + delta))] += m
    return dict(out)


def p_over(dist: Dict[int, float], line: float) -> float:
    thr = math.floor(float(line)) + 1
    tot = sum(dist.values()) or 1.0
    return sum(m for v, m in dist.items() if v >= thr) / tot


def shrunk_mean(sim_mean: float, sim_min: float, own_rate: Optional[float], w: float) -> float:
    if own_rate is None or not sim_min or sim_min <= 0:
        return sim_mean
    r_sim = sim_mean / sim_min
    return sim_min * (own_rate + w * (r_sim - own_rate))


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
                    cnt["did_not_play"] += 1
                    continue
                base, n = hist.player_avg(pk, g["tip"])
                own_rate = {s: (base[col] / base["MIN"]) if base and n >= 3 and base["MIN"] > 0 else None
                            for s, col in COMPONENTS.items()}
                sim_min = float(pl.get("min_mean") or 0)
                comp = {s: float(pl.get(f"{s}_mean") or 0) for s in COMPONENTS}
                lad = pl.get("prop_ladders") if isinstance(pl.get("prop_ladders"), dict) else {}
                ladders = {}
                for key in LADDER_PARTS:
                    blk = lad.get(key)
                    if isinstance(blk, dict) and isinstance(blk.get("distribution"), dict):
                        ladders[key] = {int(float(v)): float(m) for v, m in blk["distribution"].items()}
                rows.append({"gid": gid, "date": g["date"], "phase": g["phase"], "pk": pk, "sim_min": sim_min,
                             "comp": comp, "own_rate": own_rate,
                             "own_avg": {s: base[col] for s, col in COMPONENTS.items()} if base and n >= 3 else None,
                             "act": {s: act[col] for s, col in COMPONENTS.items()}, "ladders": ladders})
                cnt["rows"] += 1
    print("load:", json.dumps(dict(cnt)), flush=True)
    return rows


def fit_w(train: List[Dict], s: str):
    usable = [r for r in train if r["own_rate"][s] is not None and r["sim_min"] > 0]
    curve = []
    for w in W_GRID:
        curve.append((w, statistics.fmean((shrunk_mean(r["comp"][s], r["sim_min"], r["own_rate"][s], w) - r["act"][s]) ** 2
                                          for r in usable)))
    best = min(curve, key=lambda t: t[1])
    return best[0], curve, best[0] in (W_GRID[0], W_GRID[-1]), len(usable)


def deltas(r: Dict, ws: Dict[str, float]) -> Dict[str, float]:
    return {s: shrunk_mean(r["comp"][s], r["sim_min"], r["own_rate"][s], ws[s]) - r["comp"][s] for s in COMPONENTS}


def score(rows: List[Dict], ws: Dict[str, float], book: Dict) -> Dict:
    out: Dict = {}
    for key, parts in LADDER_PARTS.items():
        usable = [r for r in rows if r["own_avg"] is not None and all(r["own_rate"][s] is not None for s in parts)]
        if not usable:
            continue
        pts = []
        for r in usable:
            d = deltas(r, ws)
            y = sum(r["act"][s] for s in parts)
            raw = sum(r["comp"][s] for s in parts)
            new = raw + sum(d[s] for s in parts)
            own = sum(r["own_avg"][s] for s in parts)
            pts.append((r["gid"], abs(new - y), abs(raw - y), abs(own - y), new - y, raw - y))
        ent = {"n": len(pts), "games": len({p[0] for p in pts}),
               "mae_shrunk": round(statistics.fmean(p[1] for p in pts), 4), "mae_sim": round(statistics.fmean(p[2] for p in pts), 4),
               "mae_own_avg": round(statistics.fmean(p[3] for p in pts), 4),
               "bias_shrunk": round(statistics.fmean(p[4] for p in pts), 4), "bias_sim": round(statistics.fmean(p[5] for p in pts), 4),
               "d_mae_shrunk_minus_sim": B.boot_ci([(p[0], p[1] - p[2]) for p in pts]),
               "d_mae_shrunk_minus_own_avg": B.boot_ci([(p[0], p[1] - p[3]) for p in pts])}
        mk = MARKET_OF.get(key)
        bri = []
        for r in usable:
            dist = r["ladders"].get(key)
            b = (book.get(r["gid"]) or {}).get("props", {}).get((r["pk"], mk)) if mk else None
            y = sum(r["act"][s] for s in parts)
            if not dist or not b or y == b["line"]:
                continue
            d = sum(deltas(r, ws)[s] for s in parts)
            yy = int(y > b["line"])
            p0 = B.clip(p_over(dist, b["line"]))
            p1 = B.clip(p_over(shift(dist, d), b["line"]))
            bri.append((r["gid"], (p1 - yy) ** 2 - (p0 - yy) ** 2, (p1 - yy) ** 2, (B.clip(b["p"]) - yy) ** 2))
        if bri:
            ent.update({"book_n": len(bri), "brier_shrunk": round(statistics.fmean(x[2] for x in bri), 5),
                        "brier_book": round(statistics.fmean(x[3] for x in bri), 5),
                        "d_brier_shrunk_minus_sim": B.boot_ci([(x[0], x[1]) for x in bri])})
        out[key] = ent
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--archive", required=True, help="AVAILABILITY-ON re-run archive")
    ap.add_argument("--espn-dir", required=True)
    ap.add_argument("--box-dir", required=True)
    ap.add_argument("--odds-dir", required=True)
    ap.add_argument("--split", default="2026-08-01")
    ap.add_argument("--out", required=True)
    ap.add_argument("--n-boot", type=int, default=2000)
    ap.add_argument("--write-artifact", default="", help="write wnba_sim_rate_shrink.json (the engine's input) here")
    args = ap.parse_args(argv)
    _boot = B.boot_ci
    B.boot_ci = lambda rows, n_boot=args.n_boot, seed=7: _boot(rows, n_boot, seed)  # noqa: E731
    games = B.load_games(Path(args.espn_dir))
    box, _ = B.load_box(Path(args.box_dir), games)
    hist = B.History(games, box)
    book, _ = B.load_book(Path(args.odds_dir), games)
    rows = load_rows(Path(args.archive), games, box, hist, book)
    train = [r for r in rows if r["phase"] == "regular" and r["date"] < args.split]
    report: Dict = {"split": args.split, "n_train_rows": len(train), "w": {}, "fit": {}}
    for s in COMPONENTS:
        w, curve, edge, n = fit_w(train, s)
        report["w"][s] = w
        report["fit"][s] = {"w": w, "edge": edge, "n": n, "curve_mse": [(a, round(b, 4)) for a, b in curve]}
        print(f"fit {s:6s} w={w}{' EDGE' if edge else ''} n={n}", flush=True)
    for name, pf in (("train", lambda r: r["phase"] == "regular" and r["date"] < args.split),
                     ("test_regular", lambda r: r["phase"] == "regular" and r["date"] >= args.split),
                     ("test_playoff", lambda r: r["phase"] == "playoff")):
        res = score([r for r in rows if pf(r)], report["w"], book)
        report[name] = res
        for key, v in res.items():
            print(f"{name:13s} {key:6s} n={v['n']} mae shrunk/sim/own={v['mae_shrunk']}/{v['mae_sim']}/{v['mae_own_avg']} "
                  f"d_vs_sim={v['d_mae_shrunk_minus_sim']} d_vs_own={v['d_mae_shrunk_minus_own_avg']} "
                  f"brier shrunk/book={v.get('brier_shrunk')}/{v.get('brier_book')} d_brier={v.get('d_brier_shrunk_minus_sim')}", flush=True)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "rate_shrink_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    if args.write_artifact:
        edges = {s for s, f in report["fit"].items() if f["edge"] and f["w"] != 0.0}
        doc = {"version": 1, "w": {s: w for s, w in report["w"].items() if s not in edges}, "skipped_at_grid_edge": sorted(edges),
               "fit": f"MSE of sim minutes x shrunk rate, regular season before {args.split}, availability-on re-runs",
               "producer": "scripts/fit_wnba_sim_rate_shrink.py", "lane": "wnba-sim-rate-shrink"}
        Path(args.write_artifact).write_text(json.dumps(doc, indent=1), encoding="utf-8")
        print(f"wrote {args.write_artifact}: {doc['w']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
