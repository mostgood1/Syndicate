"""Paired comparison of two `backtest_nhl_props.py` runs, per market, at the standard lines (lane nhl-pp-time).

Brier uses the sim's EMPIRICAL P(over) from each projection's histogram (what production attaches
when a line is present), not a Poisson on the mean. MAE is on the projected mean. Every number is
paired on the same (game, player, market) keys and carries a game-clustered 95% bootstrap CI.

Segments: all skaters; ELITE (as-of points/game >= 0.9 over >= 15 prior games, strictly before the
date); PP1 / PP2 / no-PP (the run's own `pp_unit`); goalies for SAVES (the actual starter only).
Regular season and playoffs are reported separately (user decision 2026-10-05: never mix phases).

    py -3 scripts/nhl_props_paired.py --base C:/tmp/nhlprops/bt_pptime_base --var C:/tmp/nhlprops/bt_pptime_pm \
        [--json out.json]
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import pickle
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # records.pkl pickles syndicate types

STAT = {"SOG": "sog", "GOALS": "g", "ASSISTS": "a", "POINTS": "pts", "BLOCKS": "blk", "SAVES": "sv"}
LINES = {"SOG": (1.5, 2.5, 3.5), "GOALS": (0.5,), "ASSISTS": (0.5,), "POINTS": (0.5, 1.5), "BLOCKS": (1.5,),
         "SAVES": (22.5, 25.5, 28.5)}


def load(run: str, arm: str) -> dict:
    out = {}
    for f in glob.glob(os.path.join(run, "sim", f"{arm}_*.json")):
        d = json.load(open(f, encoding="utf-8"))
        for g in d["games"]:
            for p in g.get("players") or []:
                for m, v in (p.get("m") or {}).items():
                    if m in STAT and v.get("lam") is not None and v.get("hist"):
                        h = {int(k): int(c) for k, c in v["hist"].items()}
                        out[(str(g["gid"]), int(p["pid"]), m)] = dict(lam=float(v["lam"]), hist=h, rows=int(v.get("rows") or sum(h.values())),
                                                                       pp_unit=p.get("pp_unit"), pos=p.get("pos"), date=d["date"])
    return out


def p_over(rec: dict, line: float) -> float:
    n = max(1, rec["rows"])
    return sum(c for k, c in rec["hist"].items() if k > line) / n


def boot(groups: dict, B: int = 1000, seed: int = 3):
    keys = list(groups)
    if not keys:
        return None
    tot = sum(sum(v) for v in groups.values())
    n = sum(len(v) for v in groups.values())
    rng = random.Random(seed)
    bs = []
    for _ in range(B):
        s = c = 0.0
        for _k in keys:
            v = groups[keys[rng.randrange(len(keys))]]
            s += sum(v)
            c += len(v)
        bs.append(s / c)
    bs.sort()
    return tot / n, bs[int(0.025 * B)], bs[int(0.975 * B) - 1], n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--var", required=True)
    ap.add_argument("--records", default="")
    ap.add_argument("--json", default="")
    ap.add_argument("--from-date", default="", help="score only dates >= this (held-out window)")
    args = ap.parse_args()
    rec_path = args.records or os.path.join(args.base, "records.pkl")
    acts = pickle.load(open(rec_path, "rb"))["actuals"]

    act = {}
    starters = set()
    by_date = collections.defaultdict(list)
    for gid, g in acts.items():
        by_date[g["date"]].append(g)
        for p in g["players"]:
            if p["pos"] == "G":
                if p.get("toi") and float(p["toi"]) >= 40:
                    starters.add((str(gid), int(p["pid"])))
                act[(str(gid), int(p["pid"]), "SAVES")] = p.get("sv") or 0
            elif p.get("toi"):
                for m, s in STAT.items():
                    if m != "SAVES":
                        act[(str(gid), int(p["pid"]), m)] = p[s]
    # as-of points per game (strictly before the date), skaters
    asof = {}
    run_pts = collections.defaultdict(lambda: [0, 0])
    for d in sorted(by_date):
        for g in by_date[d]:
            for p in g["players"]:
                if p["pos"] != "G" and p.get("toi"):
                    a = run_pts[int(p["pid"])]
                    asof[(str(g["gid"]), int(p["pid"]))] = (a[0] / a[1]) if a[1] >= 15 else None
        for g in by_date[d]:
            for p in g["players"]:
                if p["pos"] != "G" and p.get("toi"):
                    a = run_pts[int(p["pid"])]
                    a[0] += p["pts"]
                    a[1] += 1

    segs = {
        "all": lambda k, r: r["pos"] != "G",
        "elite (asof pts/g>=0.9)": lambda k, r: r["pos"] != "G" and (asof.get((k[0], k[1])) or 0) >= 0.9,
        "PP1": lambda k, r: r["pos"] != "G" and r.get("pp_unit") == 1,
        "PP2": lambda k, r: r["pos"] != "G" and r.get("pp_unit") == 2,
        "no PP unit": lambda k, r: r["pos"] != "G" and r.get("pp_unit") not in (1, 2),
        "goalie starter": lambda k, r: r["pos"] == "G" and (k[0], k[1]) in starters,
    }
    res = {}
    for arm in ("regular", "playoff"):
        a = load(args.base, arm)
        b = load(args.var, arm)
        if args.from_date:
            a = {k: v for k, v in a.items() if v["date"] >= args.from_date}
        res[arm] = {}
        print(f"== {arm}: {os.path.basename(args.var)} vs {os.path.basename(args.base)} (d = var - base; negative is better)")
        for seg, sel in segs.items():
            for m, lines in LINES.items():
                keys = [k for k in b if k[2] == m and k in a and k in act and sel(k, a[k])]
                if (m == "SAVES") != (seg == "goalie starter") or len(keys) < 50:
                    continue
                gm = collections.defaultdict(list)
                bias_a = sum(a[k]["lam"] - act[k] for k in keys) / len(keys)
                bias_b = sum(b[k]["lam"] - act[k] for k in keys) / len(keys)
                for k in keys:
                    gm[k[0]].append(abs(b[k]["lam"] - act[k]) - abs(a[k]["lam"] - act[k]))
                mae = boot(gm)
                row = dict(n=len(keys), mean_actual=sum(act[k] for k in keys) / len(keys), bias_base=bias_a, bias_var=bias_b,
                           mae_d=mae, brier={})
                txt = [f"  {seg:24} {m:7} n={len(keys):6} mean actual {row['mean_actual']:.3f} bias {bias_a:+.3f}->{bias_b:+.3f} "
                       f"MAE d {mae[0]:+.4f} [{mae[1]:+.4f},{mae[2]:+.4f}]"]
                for L in lines:
                    gb = collections.defaultdict(list)
                    for k in keys:
                        y = 1.0 if act[k] > L else 0.0
                        gb[k[0]].append((p_over(b[k], L) - y) ** 2 - (p_over(a[k], L) - y) ** 2)
                    bb = boot(gb)
                    base_brier = sum((p_over(a[k], L) - (1.0 if act[k] > L else 0.0)) ** 2 for k in keys) / len(keys)
                    row["brier"][str(L)] = dict(base=base_brier, d=bb)
                    flag = " WORSE" if bb[1] > 0 else (" better" if bb[2] < 0 else "")
                    txt.append(f"      Brier@{L}: {base_brier:.4f} d {bb[0]:+.5f} [{bb[1]:+.5f},{bb[2]:+.5f}]{flag}")
                print("\n".join(txt))
                res[arm][f"{seg}|{m}"] = row
    if args.json:
        Path(args.json).write_text(json.dumps(res, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
