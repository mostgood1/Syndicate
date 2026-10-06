"""NHL power-play TIME: real vs what hockeysim's PP segment sampler implies (lane nhl-pp-time).

Real side, per team-game, from cached NHL play-by-play (api-web `gamecenter/<id>/play-by-play`):

* ``pp_sec``      -- seconds the team had MORE skaters than the opponent while the opponent had
                     fewer than 5 (5v4, 5v3, 4v3, and 6v4/6v3 with the PP team's goalie pulled).
                     Each interval between consecutive plays carries the state of the EARLIER
                     play's ``situationCode`` (digits: away goalie, away skaters, home skaters,
                     home goalie). Error: a PP that expires between plays is credited until the
                     next play (a few seconds per PP).
* ``opp_minors``  -- the OPPONENT's minor penalties (pbp ``details.typeCode == 'MIN'``), i.e. the
                     count hockeysim's ``committed_per_game`` is built from
                     (``nhl_statsweb_loader.py:234-243``, ``special_teams_builder.py:94``).
* ``pp_goals``    -- goals scored by the team in that same PP state.
* ``pp_starts``   -- transitions from a non-PP state into PP for this team.

Sim side (``--sim-roots``): hockeysim gives a team ``opp committed_per_game x 120 s`` of PP in
regulation (``engine.py`` PP segment sampler: ``pp_frac_total = (h+a) x 120 / 3600``, split by
``a_comm/(h+a)``), plus, in an OT period, ``(h+a) x 120 / 300`` of the OT window capped at 0.45.
The committed rate is read from each as-of root's ``team_special_teams_latest.csv``, i.e. the value
the backtest harness fed the engine on that date.

Read-only; prints tables. Usage:
    py -3 scripts/nhl_pp_time_diagnose.py --pbp C:/tmp/nhlprops/ast/shift_cache \
        [--sim-roots C:/tmp/nhlprops/bt_scratch/roots] [--real-toi C:/tmp/nhlprops/ast/real_pp.pkl \
         --actuals C:/tmp/nhlprops/bt_scratch/records.pkl] [--json out.json]
"""
from __future__ import annotations

import argparse
import collections
import csv
import glob
import json
import math
import os
import pickle
import random
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _sec(c: str) -> int:
    m, s = c.split(":")
    return int(m) * 60 + int(s)


def _state(sc: str):
    """(away_skaters, home_skaters, away_goalie_in, home_goalie_in) from a situationCode."""
    sc = str(sc or "1551")
    if len(sc) != 4 or not sc.isdigit():
        sc = "1551"
    return int(sc[1]), int(sc[2]), sc[0] == "1", sc[3] == "1"


def _pp_side(sc: str):
    """'home' / 'away' / None: which team is on a power play in this state."""
    a_sk, h_sk, _ag, _hg = _state(sc)
    if h_sk > a_sk and a_sk < 5:
        return "home"
    if a_sk > h_sk and h_sk < 5:
        return "away"
    return None


def real_from_pbp(path: str) -> list[dict]:
    p = json.load(open(path, encoding="utf-8"))
    gid = str(p.get("id"))
    gtype = int(p.get("gameType") or 0)
    season = int(p.get("season") or 0)
    home_id = int(p["homeTeam"]["id"])
    away_id = int(p["awayTeam"]["id"])
    abbr = {"home": p["homeTeam"]["abbrev"], "away": p["awayTeam"]["abbrev"]}
    side_of = {home_id: "home", away_id: "away"}
    plays = sorted(p.get("plays") or [], key=lambda x: int(x.get("sortOrder") or 0))
    out = {s: dict(pp_sec=0.0, pp_sec_reg=0.0, pp_sec_ot=0.0, opp_minors=0, opp_minors_reg=0, pp_goals=0,
                   pp_starts=0, coincidental=0) for s in ("home", "away")}
    went_ot = False
    by_period = collections.defaultdict(list)
    for pl in plays:
        per = int((pl.get("periodDescriptor") or {}).get("number") or 0)
        ptype = str((pl.get("periodDescriptor") or {}).get("periodType") or "REG")
        if ptype == "SO" or per >= 5 and gtype == 2:
            continue
        by_period[(per, ptype)].append(pl)
    for (per, ptype), pls in by_period.items():
        if ptype == "OT":
            went_ot = True
        prev_t = 0
        prev_side = None
        prev_sc = "1551"
        pen_times = collections.defaultdict(lambda: collections.Counter())
        for pl in pls:
            t = _sec(pl.get("timeInPeriod") or "00:00")
            dt = max(0, t - prev_t)
            if prev_side is not None and dt > 0:
                out[prev_side]["pp_sec"] += dt
                out[prev_side]["pp_sec_ot" if ptype == "OT" else "pp_sec_reg"] += dt
            sc = pl.get("situationCode") or prev_sc
            side = _pp_side(sc)
            kind = pl.get("typeDescKey")
            if kind == "goal":
                owner = side_of.get(int((pl.get("details") or {}).get("eventOwnerTeamId") or 0))
                if owner and _pp_side(sc) == owner:
                    out[owner]["pp_goals"] += 1
            if kind == "penalty":
                d = pl.get("details") or {}
                owner = side_of.get(int(d.get("eventOwnerTeamId") or 0))
                if owner and str(d.get("typeCode") or "").upper() == "MIN":
                    other = "away" if owner == "home" else "home"
                    out[other]["opp_minors"] += 1
                    if ptype != "OT":
                        out[other]["opp_minors_reg"] += 1
                    pen_times[t][owner] += 1
            if side is not None and side != prev_side:
                out[side]["pp_starts"] += 1
            prev_t, prev_side, prev_sc = t, side, sc
        # coincidental minors: same clock second, both teams penalised
        for t, c in pen_times.items():
            k = min(c["home"], c["away"])
            if k:
                out["home"]["coincidental"] += k
                out["away"]["coincidental"] += k
    rows = []
    for s in ("home", "away"):
        o = "away" if s == "home" else "home"
        rows.append(dict(gid=gid, season=season, gtype=gtype, date=str(p.get("gameDate") or ""), side=s,
                         team=abbr[s], opp=abbr[o], went_ot=went_ot, **out[s]))
    return rows


def _mean_ci(x: list[float], cluster: list[str] | None = None, B: int = 1000, seed: int = 7):
    n = len(x)
    if not n:
        return float("nan"), float("nan"), float("nan")
    m = sum(x) / n
    rng = random.Random(seed)
    if cluster is None:
        cluster = list(range(n))
    groups = collections.defaultdict(list)
    for v, c in zip(x, cluster):
        groups[c].append(v)
    keys = list(groups)
    bs = []
    for _ in range(B):
        tot = cnt = 0
        for _k in range(len(keys)):
            g = groups[keys[rng.randrange(len(keys))]]
            tot += sum(g)
            cnt += len(g)
        bs.append(tot / cnt)
    bs.sort()
    return m, bs[int(0.025 * B)], bs[int(0.975 * B) - 1]


def _ratio_ci(num: list[float], den: list[float], cluster: list[str], B: int = 1000, seed: int = 7):
    groups = collections.defaultdict(lambda: [0.0, 0.0])
    for a, b, c in zip(num, den, cluster):
        groups[c][0] += a
        groups[c][1] += b
    keys = list(groups)
    rng = random.Random(seed)
    r = sum(num) / max(1e-9, sum(den))
    bs = []
    for _ in range(B):
        a = b = 0.0
        for _k in range(len(keys)):
            g = groups[keys[rng.randrange(len(keys))]]
            a += g[0]
            b += g[1]
        bs.append(a / max(1e-9, b))
    bs.sort()
    return r, bs[int(0.025 * B)], bs[int(0.975 * B) - 1]


def sim_committed_by_date(roots: str) -> dict:
    """{date: {team: committed_per_game}} from each as-of root's team_special_teams file."""
    out = {}
    for r in sorted(glob.glob(os.path.join(roots, "*"))):
        f = os.path.join(r, "data", "processed", "team_special_teams_latest.csv")
        if not os.path.exists(f):
            continue
        with open(f, encoding="utf-8", newline="") as fh:
            out[os.path.basename(r)] = {row["team"].strip().upper(): float(row.get("committed_per_game") or 3.0)
                                        for row in csv.DictReader(fh) if row.get("team")}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pbp", required=True)
    ap.add_argument("--sim-roots", default="")
    ap.add_argument("--real-toi", default="")
    ap.add_argument("--actuals", default="")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    rows = []
    for f in sorted(glob.glob(os.path.join(args.pbp, "pbp_*.json"))):
        try:
            rows.extend(real_from_pbp(f))
        except Exception as exc:  # a malformed cache file is reported, not fatal
            print("skip", os.path.basename(f), type(exc).__name__)
    print(f"team-games parsed: {len(rows)}")

    def table(label, sel):
        x = [r for r in rows if sel(r)]
        if not x:
            return None
        cl = [r["gid"] for r in x]
        n = len(x)
        pp_min = _mean_ci([r["pp_sec"] / 60 for r in x], cl)
        minors = _mean_ci([r["opp_minors"] for r in x], cl)
        imp = _mean_ci([r["opp_minors"] * 2.0 for r in x], cl)
        ratio = _ratio_ci([r["pp_sec"] / 60 for r in x], [r["opp_minors"] * 2.0 for r in x], cl)
        starts = sum(r["pp_starts"] for r in x) / n
        g = sum(r["pp_goals"] for r in x) / n
        coin = sum(r["coincidental"] for r in x) / n
        per_start = sum(r["pp_sec"] for r in x) / max(1, sum(r["pp_starts"] for r in x)) / 60
        print(f"{label:28} n={n:5} games={len(set(cl)):4} | PP min/team-game {pp_min[0]:.3f} [{pp_min[1]:.3f},{pp_min[2]:.3f}]"
              f" | opp minors {minors[0]:.3f} -> x2min {imp[0]:.3f} | real/(minors x 2) {ratio[0]:.3f} [{ratio[1]:.3f},{ratio[2]:.3f}]"
              f" | PP starts {starts:.3f} ({per_start:.3f} min each) | PP goals {g:.3f} | coincidental minors {coin:.3f}"
              f" | OT share of PP {sum(r['pp_sec_ot'] for r in x)/max(1,sum(r['pp_sec'] for r in x)):.3f}")
        return dict(n=n, games=len(set(cl)), pp_min=pp_min, opp_minors=minors, ratio=ratio, starts=starts,
                    min_per_start=per_start, pp_goals=g, coincidental=coin)

    res = {}
    for season in (20242025, 20252026):
        for gt, lab in ((2, "regular"), (3, "playoffs")):
            res[f"{season}_{lab}"] = table(f"{season} {lab}", lambda r, s=season, g=gt: r["season"] == s and r["gtype"] == g)

    if args.real_toi and args.actuals:
        real = pickle.load(open(args.real_toi, "rb"))
        acts = pickle.load(open(args.actuals, "rb"))["actuals"]
        team_of = {}
        for g in acts.values():
            for pl in g["players"]:
                team_of[(str(g["gid"]), int(pl["pid"]))] = pl["team"]
        tsum = collections.Counter()
        for (gid, pid), v in real["pp_toi"].items():
            t = team_of.get((str(gid), int(pid)))
            if t:
                tsum[(str(gid), t)] += float(v)
        pbp_idx = {(r["gid"], r["team"]): r for r in rows if r["season"] == 20252026 and r["gtype"] == 2}
        both = [(tsum[k] / 5 / 60, pbp_idx[k]["pp_sec"] / 60) for k in tsum if k in pbp_idx]
        if both:
            a = sum(x for x, _ in both) / len(both)
            b = sum(y for _, y in both) / len(both)
            print(f"cross-check 2025-26 regular, {len(both)} team-games: skater PP TOI sum/5 {a:.3f} min vs pbp state {b:.3f} min")
            res["toi_crosscheck"] = dict(n=len(both), toi_sum_over_5=a, pbp=b)

    if args.sim_roots:
        comm = sim_committed_by_date(args.sim_roots)
        x = [r for r in rows if r["season"] == 20252026 and r["gtype"] == 2 and r["date"] in comm]
        sim_min, real_min, cl = [], [], []
        for r in x:
            c = comm[r["date"]]
            opp_c = c.get(r["opp"].upper(), 3.0)
            own_c = c.get(r["team"].upper(), 3.0)
            reg = opp_c * 2.0
            ot = 0.0
            if r["went_ot"]:
                frac = min(0.45, (opp_c + own_c) * 120.0 / 300.0)
                ot = frac * 5.0 * (opp_c / max(1e-6, opp_c + own_c))  # OT window <= 5 min; ends early on a goal
            sim_min.append(reg + ot)
            real_min.append(r["pp_sec"] / 60)
            cl.append(r["gid"])
        if x:
            rr = _ratio_ci(sim_min, real_min, cl)
            print(f"SIM (implied by as-of committed_per_game), 2025-26 regular, {len(x)} team-games on {len(set(r['date'] for r in x))} dates:"
                  f" sim {sum(sim_min)/len(x):.3f} vs real {sum(real_min)/len(x):.3f} min/team-game -> {rr[0]:.3f}x [{rr[1]:.3f},{rr[2]:.3f}]"
                  f" (OT part is an upper bound: assumes the full 5-min OT)")
            res["sim_implied"] = dict(n=len(x), dates=len(set(r['date'] for r in x)), sim=sum(sim_min) / len(x),
                                      real=sum(real_min) / len(x), ratio=rr)
    if args.json:
        Path(args.json).write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
