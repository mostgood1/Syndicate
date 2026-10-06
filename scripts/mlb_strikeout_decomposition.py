"""Where does the MLB engine's strikeout excess come from? (lane mlb-strikeout-bias)

The starter-length replay found starter K +0.87/start [+0.66, +1.07] on the current
engine, with pitch count unbiased. K/start = (K/BF) x BF, and BF = pitches / (P/PA),
so the excess must sit in one of:
  * K per batter faced (the pitch-level swing/whiff/called-strike mix),
  * batters faced (09-14 flagged a PA-start counter: sim BF exceeded outs+H+BB by
    1.67/start against an actual -0.24), or
  * pitches per PA (shorter PAs -> more BF for the same pitches).
This replays the CURRENT engine over the same stored as-of roster_objs as
`mlb_starter_length_replay.py` (same loaders, validated against production), and
reports each term against the box score, for the starter AND for the whole staff
(team K/BF), so a starter-vs-bullpen allocation artifact is separable from a
per-PA defect. BF integrity: BF - (OUTS + H + BB + HBP) per start, model vs actual.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mlb_starter_length_replay as rp  # noqa: E402

STAT_KEYS = ("OUTS", "P", "SO", "H", "BB", "HBP", "BF", "ER")


def _sim_game(job: dict) -> dict:
    from sim_engine.data.roster_artifact import read_game_roster_artifact
    from sim_engine.models import GameConfig
    from sim_engine.simulate import simulate_game

    art = read_game_roster_artifact(Path(job["roster_path"]))
    away, home = art["away"], art["home"]
    rec = rp._load_json(job["sim_path"]) if job.get("sim_path") else None
    weather, park, umpire = rp.context_from_sim(rec)
    starters = {"away": int(away.lineup.pitcher.player.mlbam_id), "home": int(home.lineup.pitcher.player.mlbam_id)}
    bats = {side: {int(b.player.mlbam_id) for b in list(ro.lineup.batters or []) + list(ro.lineup.bench or [])}
            for side, ro in (("away", away), ("home", home))}
    bat = {"away": defaultdict(float), "home": defaultdict(float)}
    staff = {"away": {int(p.player.mlbam_id) for p in [away.lineup.pitcher] + list(away.lineup.bullpen or [])},
             "home": {int(p.player.mlbam_id) for p in [home.lineup.pitcher] + list(home.lineup.bullpen or [])}}
    st = {s: defaultdict(float) for s in starters}
    team = {s: defaultdict(float) for s in starters}
    runs = 0.0
    n = int(job["sims"])
    for i in range(n):
        cfg = GameConfig(rng_seed=int(job["seed"]) + i, weather=weather, park=park, umpire=umpire,
                         manager_pitching="v2", manager_pitching_overrides=job["mp"], pitch_model_overrides=job["pm"],
                         pbp="pa", **(job.get("cfg") or {}))
        r = simulate_game(away, home, cfg)
        runs += float(r.away_score) + float(r.home_score)
        for ev in r.pbp or []:
            if ev.get("type") == "PA" and int(ev.get("outs_after", 0)) - int(ev.get("outs_before", 0)) >= 2:
                fside = "home" if int(ev.get("fielding_team_id", 0)) == int(home.team.team_id) else "away"
                team[fside]["DP"] += 1.0
        r.pbp = []
        for bid_raw, brow in (r.batter_stats or {}).items():
            bid = int(bid_raw)
            side = "away" if bid in bats["away"] else ("home" if bid in bats["home"] else None)
            if side:
                for k in ("HR", "H", "BB", "PA", "SO", "HBP"):
                    bat[side][k] += float(brow.get(k) or 0.0)
        ps = r.pitcher_stats or {}
        for side, pid in starters.items():
            row = ps.get(pid) or ps.get(str(pid)) or {}
            for k in STAT_KEYS:
                st[side][k] += float(row.get(k) or 0.0)
            o = float(row.get("OUTS") or 0.0)
            st[side]["LE9"] += 1.0 if o <= 9 else 0.0
            st[side]["EQ15"] += 1.0 if o == 15 else 0.0
        for pid_raw, row in ps.items():
            pid = int(pid_raw)
            side = "away" if pid in staff["away"] else ("home" if pid in staff["home"] else None)
            if side:
                for k in ("SO", "BF", "P", "PO"):
                    team[side][k] += float(row.get(k) or 0.0)
    return {"date": job["date"], "game_pk": job["game_pk"], "starters": starters,
            "starter": {s: {k: v / n for k, v in d.items()} for s, d in st.items()},
            "team": {s: {k: v / n for k, v in d.items()} for s, d in team.items()},
            "total_runs": runs / n,
            "batting": {s: {k: v / n for k, v in d.items()} for s, d in bat.items()}}


def _actual(box: dict) -> dict:
    out = {}
    for side in ("away", "home"):
        t = (box.get("teams") or {}).get(side) or {}
        order = t.get("pitchers") or []
        if not order:
            continue
        pid = int(order[0])
        s = (((t.get("players") or {}).get(f"ID{pid}") or {}).get("stats") or {}).get("pitching") or {}
        ip = str(s.get("inningsPitched") or "0.0")
        whole, _, frac = ip.partition(".")
        tp = ((t.get("teamStats") or {}).get("pitching") or {})
        tb = ((t.get("teamStats") or {}).get("batting") or {})
        ob = (((box.get("teams") or {}).get("home" if side == "away" else "away") or {}).get("teamStats") or {}).get("batting") or {}
        out[side] = {"pid": pid,
                     "starter": {"OUTS": int(s.get("outs", int(whole or 0) * 3 + int(frac or 0))),
                                 "P": int(s.get("numberOfPitches") or s.get("pitchesThrown") or 0),
                                 "SO": int(s.get("strikeOuts") or 0), "H": int(s.get("hits") or 0),
                                 "BB": int(s.get("baseOnBalls") or 0), "HBP": int(s.get("hitByPitch") or 0),
                                 "BF": int(s.get("battersFaced") or 0), "ER": int(s.get("earnedRuns") or 0)},
                     "runs": int(((box.get("teams") or {}).get("away") or {}).get("teamStats", {}).get("batting", {}).get("runs") or 0)
                             + int(((box.get("teams") or {}).get("home") or {}).get("teamStats", {}).get("batting", {}).get("runs") or 0),
                     "batting": {"HR": int(tb.get("homeRuns") or 0), "H": int(tb.get("hits") or 0),
                                 "BB": int(tb.get("baseOnBalls") or 0), "PA": int(tb.get("plateAppearances") or 0),
                                 "SO": int(tb.get("strikeOuts") or 0), "HBP": int(tb.get("hitByPitch") or 0)},
                     "team": {"SO": int(tp.get("strikeOuts") or 0), "BF": int(tp.get("battersFaced") or 0),
                              "PO": int(tp.get("pickoffs") or 0), "DP": int(ob.get("groundIntoDoublePlay") or 0),
                              "P": int(tp.get("numberOfPitches") or tp.get("pitchesThrown") or 0)}}
    return out


def _ratio(rows, num, den, who):
    a = sum(r[who][num] for r in rows)
    b = sum(r[who][den] for r in rows)
    return a / b if b else None


def summarise(rows: list[dict], draws: int) -> dict:
    out = {"n_starts": len(rows), "games": len({r["game_pk"] for r in rows})}
    for who in ("starter", "team"):
        o = {}
        keys = STAT_KEYS if who == "starter" else ("SO", "BF", "P")
        for k in keys:
            m = sum(r["model_" + who][k] for r in rows) / len(rows)
            a = sum(r["actual_" + who][k] for r in rows) / len(rows)
            o[k] = {"model": m, "actual": a, "bias": m - a}
        for name, num, den in (("K_per_BF", "SO", "BF"), ("P_per_BF", "P", "BF")):
            mod = sum(r["model_" + who][num] for r in rows) / sum(r["model_" + who][den] for r in rows)
            act = sum(r["actual_" + who][num] for r in rows) / sum(r["actual_" + who][den] for r in rows)
            est, lo, hi = rp.boot_ci(rows, lambda rs, num=num, den=den, who=who: (
                sum(r["model_" + who][num] for r in rs) / sum(r["model_" + who][den] for r in rs)
                - sum(r["actual_" + who][num] for r in rs) / sum(r["actual_" + who][den] for r in rs)), draws)
            o[name] = {"model": mod, "actual": act, "diff": est, "ci": [lo, hi]}
        out[who] = o
    s = out["starter"]
    # BF integrity: BF should equal OUTS + H + BB + HBP (+ ROE/CI/FC-without-out, which are rare)
    mod_gap = sum(r["model_starter"]["BF"] - (r["model_starter"]["OUTS"] + r["model_starter"]["H"] + r["model_starter"]["BB"] + r["model_starter"]["HBP"]) for r in rows) / len(rows)
    act_gap = sum(r["actual_starter"]["BF"] - (r["actual_starter"]["OUTS"] + r["actual_starter"]["H"] + r["actual_starter"]["BB"] + r["actual_starter"]["HBP"]) for r in rows) / len(rows)
    out["bf_integrity_gap"] = {"model": mod_gap, "actual": act_gap}
    games = {r["game_pk"]: (r["model_runs"], r["actual_runs"]) for r in rows}
    out["game_total"] = {"model": sum(m for m, _ in games.values()) / len(games),
                         "actual": sum(a for _, a in games.values()) / len(games), "games": len(games)}
    out["SO_mae"] = sum(abs(r["model_starter"]["SO"] - r["actual_starter"]["SO"]) for r in rows) / len(rows)
    b, lo, hi = rp.boot_ci(rows, lambda rs: sum(r["model_starter"]["SO"] - r["actual_starter"]["SO"] for r in rs) / len(rs), draws)
    out["SO_bias_ci"] = [b, lo, hi]
    # Batting components per team-game. A starter row is keyed to the PITCHING side, so
    # its batting row is that side's own offense: one team-game per starter row.
    bat = {}
    for k in ("HR", "H", "BB", "SO", "HBP", "PA"):
        m = sum(r["model_bat"].get(k, 0.0) for r in rows) / len(rows)
        a = sum(r["actual_bat"].get(k, 0) for r in rows) / len(rows)
        bb_, lo_, hi_ = rp.boot_ci(rows, lambda rs, k=k: sum(r["model_bat"].get(k, 0.0) - r["actual_bat"].get(k, 0) for r in rs) / len(rs), draws)
        bat[k] = {"model": m, "actual": a, "bias": bb_, "ci": [lo_, hi_]}
    for k in ("HR", "H", "BB", "SO", "HBP"):
        mp_ = sum(r["model_bat"].get("PA", 0.0) for r in rows)
        ap_ = sum(r["actual_bat"].get("PA", 0) for r in rows)
        bat[k + "_per_PA"] = {"model": sum(r["model_bat"].get(k, 0.0) for r in rows) / mp_ if mp_ else None,
                              "actual": sum(r["actual_bat"].get(k, 0) for r in rows) / ap_ if ap_ else None}
    out["batting"] = bat
    out["team_DP_per_game"] = {"model": sum(r["model_team"].get("DP", 0.0) for r in rows) / len(rows),
                               "actual": sum(r["actual_team"].get("DP", 0) for r in rows) / len(rows)}
    out["starter_share_le9"] = {"model": sum(r["model_starter"].get("LE9", 0.0) for r in rows) / len(rows),
                                "actual": sum(1.0 for r in rows if r["actual_starter"]["OUTS"] <= 9) / len(rows)}
    out["starter_share_eq15"] = {"model": sum(r["model_starter"].get("EQ15", 0.0) for r in rows) / len(rows),
                                 "actual": sum(1.0 for r in rows if r["actual_starter"]["OUTS"] == 15) / len(rows)}
    out["team_PO_per_game"] = {"model": sum(r["model_team"].get("PO", 0.0) for r in rows) / len(rows),
                               "actual": sum(r["actual_team"].get("PO", 0) for r in rows) / len(rows)}
    out["objective"] = objective(out)
    # K/start decomposition: model K = (model K/BF)(model BF); swap one term at a time
    kbf_m, kbf_a = s["K_per_BF"]["model"], s["K_per_BF"]["actual"]
    bf_m, bf_a = s["BF"]["model"], s["BF"]["actual"]
    out["K_excess_split"] = {"total": kbf_m * bf_m - kbf_a * bf_a,
                             "from_K_per_BF": (kbf_m - kbf_a) * bf_a,
                             "from_BF": kbf_a * (bf_m - bf_a),
                             "interaction": (kbf_m - kbf_a) * (bf_m - bf_a)}
    return out



# The pre-registered combined-calibration objective (lanes.md, mlb-combined-calibration).
# Scales: 5% of actual for per-PA rates, 0.5 outs, 0.03 shares, 0.05 DP/PO per team-game,
# 0.10 BF balance, 0.30 runs/game.
def objective(s: dict) -> dict:
    st, b = s["starter"], s["batting"]
    rel = lambda m, a: (m - a) / (0.05 * a) if a else 0.0  # noqa: E731
    terms = {
        "HBP_per_PA": rel(b["HBP_per_PA"]["model"], b["HBP_per_PA"]["actual"]),
        "K_per_BF": rel(st["K_per_BF"]["model"], st["K_per_BF"]["actual"]),
        "P_per_BF": rel(st["P_per_BF"]["model"], st["P_per_BF"]["actual"]),
        "BB_per_PA": rel(b["BB_per_PA"]["model"], b["BB_per_PA"]["actual"]),
        "HR_per_PA": rel(b["HR_per_PA"]["model"], b["HR_per_PA"]["actual"]),
        "H_per_PA": rel(b["H_per_PA"]["model"], b["H_per_PA"]["actual"]),
        "DP_per_game": (s["team_DP_per_game"]["model"] - s["team_DP_per_game"]["actual"]) / 0.05,
        "PO_per_game": (s.get("team_PO_per_game", {"model": 0, "actual": 0})["model"] - s.get("team_PO_per_game", {"model": 0, "actual": 0})["actual"]) / 0.05,
        "BF_balance": (s["bf_integrity_gap"]["model"] - s["bf_integrity_gap"]["actual"]) / 0.10,
        "outs_mean": (st["OUTS"]["model"] - st["OUTS"]["actual"]) / 0.5,
        "share_le9": (s["starter_share_le9"]["model"] - s["starter_share_le9"]["actual"]) / 0.03,
        "share_eq15": (s["starter_share_eq15"]["model"] - s["starter_share_eq15"]["actual"]) / 0.03,
        "runs_per_game": (s["game_total"]["model"] - s["game_total"]["actual"]) / 0.30,
    }
    return {"total": sum(v * v for v in terms.values()), "terms": terms}

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", default=os.environ.get("MLB_BETTING_DATA_ROOT", ""))
    ap.add_argument("--dates", nargs="+", required=True)
    ap.add_argument("--sims", type=int, default=200)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--draws", type=int, default=1000)
    ap.add_argument("--set", action="append", help="manager-pitching override key=value")
    ap.add_argument("--pm-set", action="append", help="pitch-model override key=value")
    ap.add_argument("--cfg-set", action="append", help="GameConfig field key=value (e.g. bip_dp_rate=0.12)")
    ap.add_argument("--cache", default=os.path.join(os.environ.get("TMPDIR", "/tmp"), "mlb_starter_replay_cache"))
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    data_dir = Path(os.path.expanduser(args.data_root))
    cache = Path(os.path.expanduser(args.cache))
    cache.mkdir(parents=True, exist_ok=True)
    mp, pm = rp.forward_overrides()
    cfgx = {}
    for src, dst in ((args.set, mp), (args.pm_set, pm), (args.cfg_set, cfgx)):
        for kv in src or []:
            k, _, v = kv.partition("=")
            try:
                dst[k.strip()] = json.loads(v)
            except ValueError:
                dst[k.strip()] = v
    jobs = []
    for d in sorted(set(args.dates)):
        for g in rp.games_for_date(data_dir, d):
            g.update({"sims": args.sims, "seed": args.seed, "mp": mp, "pm": pm, "cfg": cfgx})
            jobs.append(g)
    counters = defaultdict(int)
    rows = []
    with cf.ProcessPoolExecutor(max_workers=args.workers) as ex:
        results = list(ex.map(_sim_game, jobs, chunksize=1))
    for res in results:
        try:
            act = _actual(rp.boxscore(res["game_pk"], cache))
        except Exception:
            counters["boxscore_unavailable"] += 1
            continue
        for side, pid in res["starters"].items():
            a = act.get(side)
            if not a or a["pid"] != pid:
                counters["starter_mismatch_excluded"] += 1
                continue
            if not a["starter"]["BF"] or not a["team"]["BF"]:
                counters["actual_bf_missing"] += 1
                continue
            rows.append({"date": res["date"], "game_pk": res["game_pk"], "pid": pid,
                         "model_runs": res["total_runs"], "actual_runs": a["runs"],
                         "model_bat": res["batting"][side], "actual_bat": a["batting"],
                         "model_starter": res["starter"][side], "actual_starter": a["starter"],
                         "model_team": res["team"][side], "actual_team": a["team"]})
    dates = sorted(set(args.dates))
    cut = dates[int(len(dates) * 2 / 3)] if len(dates) >= 3 else None
    rep = {"dates": dates, "sims": args.sims, "seed": args.seed, "mp": mp, "pm_set": args.pm_set or [], "cfg_set": args.cfg_set or [],
           "counters": dict(counters), "all": summarise(rows, args.draws)}
    if cut:
        rep["split_date"] = cut
        rep["tune"] = summarise([r for r in rows if r["date"] < cut], args.draws)
        rep["holdout"] = summarise([r for r in rows if r["date"] >= cut], args.draws)
    Path(args.out).write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: rep[k] for k in ("counters", "all")}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
