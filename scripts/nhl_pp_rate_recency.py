"""Offline test of as-of penalty-rate estimators for hockeysim PP TIME (lane nhl-pp-time, pre-registered 2026-10-08).

hockeysim gives a team ``opponent committed_per_game x pp_seconds_per_minor`` of PP per game under
pp_time_model="per_minor", so an estimator of the opponent's committed-minor rate can be scored without a
sim: predicted PP minutes = rate x SEC / 60, against the official NHL ``team/powerplaytime`` timeOnIcePp.

Estimators (strictly before each game's date; minors = pbp ``details.typeCode == "MIN"``, the builder's count):
  A      season-to-date mean of the team's committed minors (production's as-of special-teams rate)
  B_h    exponentially weighted mean over the team's own games, half-life h games (A until 5 games)
  C_h    B_h x league ratio (trailing-20-day league minors per team-game / season-to-date league mean)

    py -3 scripts/nhl_pp_rate_recency.py --pbp C:/tmp/nhlprops/ast/shift_cache --official <dir> [--sec 88.9]
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[0]))
from nhl_pp_time_diagnose import real_from_pbp  # noqa: E402

HALF_LIVES = (5, 10, 20)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pbp", required=True)
    ap.add_argument("--official", required=True)
    ap.add_argument("--season", type=int, default=20252026)
    ap.add_argument("--sec", type=float, default=88.9)
    ap.add_argument("--start", default="2025-11-01")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    rows = []
    for f in sorted(glob.glob(os.path.join(args.pbp, f"pbp_{str(args.season)[:4]}02*.json"))):
        rows.extend(real_from_pbp(f))
    rows = [r for r in rows if r["season"] == args.season and r["gtype"] == 2]
    # committed minors of team T in game g = the OPPONENT row's opp_minors
    by_gid = collections.defaultdict(dict)
    for r in rows:
        by_gid[r["gid"]][r["side"]] = r
    games = []  # (date, gid, team, committed)
    for gid, sides in by_gid.items():
        if len(sides) != 2:
            continue
        h, a = sides["home"], sides["away"]
        games.append((h["date"], gid, h["team"], a["opp_minors"]))
        games.append((a["date"], gid, a["team"], h["opp_minors"]))
    games.sort()
    off = json.load(open(os.path.join(args.official, f"pptime_{args.season}_2.json"), encoding="utf-8"))["data"]
    real = {(str(o["gameId"]), "home" if o["homeRoad"] == "H" else "away"): float(o["timeOnIcePp"]) / 60 for o in off}

    # walk dates; estimates use only games on earlier dates
    hist = collections.defaultdict(list)  # team -> [committed,...] in order
    league = []  # (date, committed) per team-game
    est = {}     # (gid, team) -> {name: rate}
    dates = sorted({g[0] for g in games})
    by_date = collections.defaultdict(list)
    for g in games:
        by_date[g[0]].append(g)
    import datetime as _dt
    for d in dates:
        dd = _dt.date.fromisoformat(d)
        lg_all = [c for _, c in league]
        lg_recent = [c for dl, c in league if (dd - _dt.date.fromisoformat(dl)).days <= 20]
        lratio = (sum(lg_recent) / len(lg_recent)) / (sum(lg_all) / len(lg_all)) if lg_recent and lg_all else 1.0
        for _, gid, team, _c in by_date[d]:
            hx = hist[team]
            if not hx:
                continue
            e = {"A": sum(hx) / len(hx)}
            for h in HALF_LIVES:
                if len(hx) < 5:
                    b = e["A"]
                else:
                    w = [0.5 ** ((len(hx) - 1 - i) / h) for i in range(len(hx))]
                    b = sum(wi * x for wi, x in zip(w, hx)) / sum(w)
                e[f"B{h}"] = b
                e[f"C{h}"] = b * lratio
            est[(gid, team)] = e
        for _, gid, team, c in by_date[d]:
            hist[team].append(c)
            league.append((d, c))

    # score: predicted PP minutes for side S = opponent's estimate x sec/60
    recs = []
    for gid, sides in by_gid.items():
        if len(sides) != 2:
            continue
        for s, o in (("home", "away"), ("away", "home")):
            d = sides[s]["date"]
            if d < args.start or (gid, s) not in real:
                continue
            e = est.get((gid, sides[o]["team"]))
            if not e:
                continue
            recs.append(dict(date=d, month=d[:7], real=real[(gid, s)], **{k: v * args.sec / 60 for k, v in e.items()}))
    names = ["A"] + [f"B{h}" for h in HALF_LIVES] + [f"C{h}" for h in HALF_LIVES]

    def score(sel):
        x = [r for r in recs if sel(r)]
        if not x:
            return None
        rl = sum(r["real"] for r in x)
        return {"n": len(x), **{k: (round(sum(r[k] for r in x) / rl, 4), round(sum(abs(r[k] - r["real"]) for r in x) / len(x), 4)) for k in names}}

    out = {"fit_nov_dec": score(lambda r: r["date"] < "2026-01-01"), "holdout_jan_apr": score(lambda r: r["date"] >= "2026-01-01")}
    for m in sorted({r["month"] for r in recs}):
        out[m] = score(lambda r, m=m: r["month"] == m)
    print(f"sec/minor {args.sec}; cells = (sim/real total PP-time ratio, team-game MAE in PP minutes)")
    print(f"{'window':16} {'n':>5} " + " ".join(f"{k:>16}" for k in names))
    for w, v in out.items():
        if v:
            print(f"{w:16} {v['n']:5} " + " ".join(f"{str(v[k]):>16}" for k in names))
    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
