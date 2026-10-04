"""Where do an absent player's minutes go -- in the sim vs in reality? (lane `wnba-minutes-redistribution`)

Under oracle availability (the pool is exactly who played), the WNBA SmartSim still over-projects the remaining priced
players' minutes on late-out days (findings_2026-10-04_wnba_oracle_availability.md: -0.57 min surprise). Team minutes
are fixed, so that excess must be minutes that in reality go somewhere the sim does not put them. Per team-game
(regulation only -- OT games excluded so every team plays exactly 200 minutes):

  1. POOL LEAK: actual minutes of players who played but are NOT in the sim pool (sim gives them 0).
  2. TIERS: pool players ranked by sim minutes (1-5, 6-8, 9+); mean actual - sim per tier.
  3. AS-OF SHARE: each player's as-of season minutes share of the team; when teammates are absent, how the freed
     minutes (sim vs actual) split by that share -- proportional (the sim's scale+cap rule) or flatter.

Every mean carries a game-clustered bootstrap CI, split by late-out band (none / <15 / >=15 teammate-minutes).

Usage (WSL): python scripts/diagnose_wnba_minutes_redistribution.py --archive ~/wnba_bt/oracle_shrunk
             --espn-dir ... --box-dir ... --out ~/wnba_bt/redistribution_diag
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


B = _load("bt_wnba", "backtest_wnba_lines_props.py")
BI = _load("bi_wnba", "analyze_wnba_book_information.py")
AV = BI.AV

BANDS = (("no late outs", 0.0, 0.001), ("late outs < 15 min", 0.001, 15.0), ("late outs >= 15 min", 15.0, 1e9))
TIERS = (("rank 1-5", 1, 5), ("rank 6-8", 6, 8), ("rank 9+", 9, 99))


def asof_minutes(games: Dict, box_all: Dict) -> Dict[Tuple[str, str], Dict[str, float]]:
    """{(gid, team): {player: as-of mean minutes over games PLAYED before this tip}}."""
    hist: Dict[Tuple[str, str], List[float]] = defaultdict(list)
    out: Dict[Tuple[str, str], Dict[str, float]] = {}
    for g in sorted(games.values(), key=lambda x: x["tip"]):
        if g["id"] not in box_all:
            continue
        for team in (g["home"], g["away"]):
            roster = box_all[g["id"]].get(team, {})
            out[(g["id"], team)] = {k: statistics.fmean(hist[(team, k)]) for k in roster if hist[(team, k)]}
            for k, m in roster.items():
                if m > 0:
                    hist[(team, k)].append(m)
    return out


def team_rows(archive: Path, games: Dict, box_all: Dict, lo: Dict, asof: Dict) -> List[Dict]:
    idx = B._pair_index(games)
    rows: List[Dict] = []
    for p in sorted(archive.glob("*/smart_sim_*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        gid = B.match_game(idx, str(d.get("date")), str(d.get("home")).upper(), str(d.get("away")).upper())
        if not gid or gid not in box_all:
            continue
        g = games[gid]
        for side, team in (("home", g["home"]), ("away", g["away"])):
            actual = {k: m for k, m in box_all[gid].get(team, {}).items() if m > 0}
            if not actual or sum(actual.values()) > 201.0:      # OT or broken box -> skip
                continue
            sim = {}
            for pl in (d.get("players") or {}).get(side) or []:
                k = B.norm_name(pl.get("player_name"))
                try:
                    sim[k] = float(pl.get("min_mean") or 0.0)
                except (TypeError, ValueError):
                    continue
            if not sim:
                continue
            ranked = sorted(sim, key=lambda k: -sim[k])
            rows.append({"gid": gid, "team": team, "late": lo.get((gid, team), 0.0), "sim": sim, "actual": actual,
                         "rank": {k: i + 1 for i, k in enumerate(ranked)}, "asof": asof.get((gid, team), {}),
                         "sim_total": sum(sim.values()), "leak": sum(m for k, m in actual.items() if k not in sim)})
    return rows


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--archive", required=True)
    ap.add_argument("--espn-dir", required=True)
    ap.add_argument("--box-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--n-boot", type=int, default=1000)
    args = ap.parse_args(argv)
    games = B.load_games(Path(args.espn_dir))
    box_all = AV.load_box_all(Path(args.box_dir), games)
    lo = BI.late_outs(games, box_all)
    rows = team_rows(Path(args.archive), games, box_all, lo, asof_minutes(games, box_all))
    rep: Dict = {"team_games": len(rows), "bands": {}}
    ci = lambda pairs: B.boot_ci(pairs, args.n_boot)
    for name, lo_c, hi_c in BANDS:
        R = [r for r in rows if lo_c <= r["late"] < hi_c]
        if not R:
            continue
        ent: Dict = {"team_games": len(R), "games": len({r["gid"] for r in R}),
                     "sim_pool_total": round(statistics.fmean(r["sim_total"] for r in R), 2),
                     "pool_leak_minutes": ci([(r["gid"], r["leak"]) for r in R]),
                     "pool_size_sim": round(statistics.fmean(len(r["sim"]) for r in R), 2),
                     "players_who_played": round(statistics.fmean(len(r["actual"]) for r in R), 2)}
        tiers = {}
        for tname, a, b in TIERS:
            pr = [(r["gid"], r["actual"].get(k, 0.0) - r["sim"][k]) for r in R for k in r["sim"] if a <= r["rank"][k] <= b]
            if pr:
                tiers[tname] = {"n": len(pr), "actual_minus_sim": ci(pr)}
        ent["tiers"] = tiers
        # as-of share: freed minutes vs the player's as-of minutes, sim vs actual (players with an as-of history)
        gain_sim, gain_act = [], []
        for r in R:
            for k in r["sim"]:
                base = r["asof"].get(k)
                if base is None:
                    continue
                gain_sim.append((r["gid"], r["sim"][k] - base))
                gain_act.append((r["gid"], r["actual"].get(k, 0.0) - base))
        ent["gain_vs_asof_sim"] = ci(gain_sim) if gain_sim else None
        ent["gain_vs_asof_actual"] = ci(gain_act) if gain_act else None
        # by as-of minutes level: where the sim adds vs where reality adds
        lv = {}
        for lname, a, b in (("as-of < 10 min", 0, 10), ("10-20", 10, 20), ("20-30", 20, 30), ("30+", 30, 99)):
            ps = [(r["gid"], r["sim"][k] - r["asof"][k], r["actual"].get(k, 0.0) - r["asof"][k])
                  for r in R for k in r["sim"] if k in r["asof"] and a <= r["asof"][k] < b]
            if len(ps) >= 20:
                lv[lname] = {"n": len(ps), "sim_gain": ci([(p[0], p[1]) for p in ps]),
                             "actual_gain": ci([(p[0], p[2]) for p in ps]),
                             "actual_minus_sim": ci([(p[0], p[2] - p[1]) for p in ps])}
        ent["by_asof_level"] = lv
        rep["bands"][name] = ent
        print(f"== {name}: team-games {ent['team_games']}, sim pool total {ent['sim_pool_total']}, pool size {ent['pool_size_sim']} "
              f"vs played {ent['players_who_played']}, LEAK {ent['pool_leak_minutes']}", flush=True)
        for t, v in tiers.items():
            print(f"   tier {t:10s} n {v['n']:5d} actual-sim {v['actual_minus_sim']}", flush=True)
        for t, v in lv.items():
            print(f"   level {t:15s} n {v['n']:5d} sim gain {v['sim_gain']['point']:+.2f} actual gain {v['actual_gain']['point']:+.2f} "
                  f"actual-sim {v['actual_minus_sim']}", flush=True)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "redistribution_diag.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
