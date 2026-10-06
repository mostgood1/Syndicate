"""PP/PK unit SHARE of team special-teams time: sim (engine measure `players`) vs real (lane nhl-pp-time).

For each unit label the run carries (`pp_unit` 1/2/none, `pk_unit` 1/2/none): the mean per-player
share of his team's PP (or PK) time in that game. Sim: per-player PP/PK shift seconds / the team's
PP/PK seconds (from the engine measure). Real: NHL stats `skater/timeonice` ppTimeOnIce /
shTimeOnIce per player-game / the team's PP (or SH) time = sum over its skaters / 5 (the
official team PP time agrees with that definition to 0.1 min). Joined on (date, team, player).

    py -3 scripts/nhl_pp_time_unit_split.py --run <eng_*.json> --toi <skater_toi_20252026_2.json> --official <dir>
"""
from __future__ import annotations

import argparse
import collections
import json
import os


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", nargs="+", required=True)
    ap.add_argument("--toi", required=True)
    ap.add_argument("--official", required=True)
    args = ap.parse_args()
    off = json.load(open(os.path.join(args.official, "pptime_20252026_2.json"), encoding="utf-8"))["data"]
    gid_of = {(r["gameDate"], r["teamFullName"]): str(r["gameId"]) for r in off}
    toi = json.load(open(args.toi, encoding="utf-8"))
    real = {(t["gid"], int(t["pid"])): t for t in toi}
    team_real = collections.defaultdict(lambda: [0.0, 0.0])
    for t in toi:
        a = team_real[(t["gid"], t["team"])]
        a[0] += t["pp"]
        a[1] += t["sh"]
    team_abbr_of_gid_pid = {(t["gid"], int(t["pid"])): t["team"] for t in toi}
    for path in args.run:
        d = json.load(open(path, encoding="utf-8"))
        players = d.get("players") or []
        team_sim = collections.defaultdict(lambda: [0.0, 0.0])
        for p in players:
            a = team_sim[(p["date"], p["team"])]
            a[0] += p["pp_sec"]
            a[1] += p["pk_sec"]
        print(f"== {os.path.basename(path)}  ({len(players)} player-games)")
        for kind, unit_key, sim_k, real_k, idx in (("PP", "pp_unit", "pp_sec", "pp", 0), ("PK", "pk_unit", "pk_sec", "sh", 1)):
            acc = collections.defaultdict(lambda: [0.0, 0.0, 0, 0.0, 0.0])
            for p in players:
                gid = gid_of.get((p["date"], p["team"]))
                if gid is None or (gid, int(p["pid"])) not in real:
                    continue
                abbr = team_abbr_of_gid_pid[(gid, int(p["pid"]))]
                ts = team_sim[(p["date"], p["team"])][idx] / 5.0
                tr = team_real[(gid, abbr)][idx] / 5.0
                if ts <= 0 or tr <= 0:
                    continue
                u = p.get(unit_key)
                lab = f"{kind}{u}" if u in (1, 2) else f"no {kind} unit"
                a = acc[(lab, p.get("pos"))]
                a[0] += p[sim_k] / ts
                a[1] += real[(gid, int(p["pid"]))][real_k] / tr
                a[2] += 1
                a[3] += p[sim_k] / 60.0
                a[4] += real[(gid, int(p["pid"]))][real_k] / 60.0
            for (lab, pos), a in sorted(acc.items()):
                n = a[2]
                print(f"  {lab:12} {pos}: n={n:5}  share of team {kind} time sim {a[0]/n:.3f} real {a[1]/n:.3f}"
                      f"  | {kind} min/game sim {a[3]/n:.2f} real {a[4]/n:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
