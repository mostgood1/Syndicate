"""Game-line A/B of two pitch-model configs over stored as-of roster_objs (lane mlb-game-profile-pitch-config).

Production's game-ROI profile (served `daily/sims`) runs pitch_model_overrides = {} -- the
multi-profile runner points it at a pitch file that does not exist -- while the props profiles
run the forward file. This replays BOTH configs over the same rosters, context and seeds and
scores each against the final score:

  * full-game total-runs CRPS (proper; needs no book line)
  * home-win Brier
  * runs bias / MAE of the mean
  * first-five total-runs CRPS (StatsAPI linescore)
  * total HR per game bias

Arms: `none` = pm {} (PitchModelConfig class defaults, what the game profile runs today);
`fwd` = the forward pitch file. Manager file and GameConfig defaults are identical in both.
Per-game paired differences carry the uncertainty (a game is the cluster).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import math
import os
import sys
import urllib.request
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mlb_starter_length_replay as rp  # noqa: E402

STATSAPI = "https://statsapi.mlb.com/api/v1"
ARMS = ("none", "fwd")


def crps_discrete(counts: Counter, n: int, actual: int) -> float:
    """CRPS of an integer-valued sample distribution at an integer outcome."""
    hi = max(max(counts) if counts else 0, actual) + 1
    cum, total = 0, 0.0
    for k in range(0, hi + 1):
        cum += counts.get(k, 0)
        f = cum / n
        total += (f - (1.0 if actual <= k else 0.0)) ** 2
    return total


def arm_pm(arm: str) -> dict:
    _mp, pm = rp.forward_overrides()
    return {} if arm == "none" else pm


def _sim_game(job: dict) -> dict:
    from sim_engine.data.roster_artifact import read_game_roster_artifact
    from sim_engine.models import GameConfig
    from sim_engine.simulate import simulate_game

    art = read_game_roster_artifact(Path(job["roster_path"]))
    rec = rp._load_json(job["sim_path"]) if job.get("sim_path") else None
    weather, park, umpire = rp.context_from_sim(rec)
    mp, _pm = rp.forward_overrides()
    pm = arm_pm(job["arm"])
    totals, f5, hrs = Counter(), Counter(), 0.0
    home_wins = 0.0
    n = int(job["sims"])
    for i in range(n):
        cfg = GameConfig(rng_seed=int(job["seed"]) + i, weather=weather, park=park, umpire=umpire,
                         manager_pitching="v2", manager_pitching_overrides=mp, pitch_model_overrides=pm)
        r = simulate_game(art["away"], art["home"], cfg)
        totals[int(r.away_score) + int(r.home_score)] += 1
        f5[sum((r.away_inning_runs or [])[:5]) + sum((r.home_inning_runs or [])[:5])] += 1
        home_wins += 1.0 if r.home_score > r.away_score else 0.0
        hrs += sum(int(v.get("HR") or 0) for v in (r.batter_stats or {}).values())
    return {"date": job["date"], "game_pk": int(job["game_pk"]), "arm": job["arm"], "n": n,
            "totals": dict(totals), "f5": dict(f5), "p_home": home_wins / n, "hr_mean": hrs / n}


def linescore(pk: int, cache: Path) -> dict:
    f = cache / f"linescore_{pk}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    req = urllib.request.Request(f"{STATSAPI}/game/{pk}/linescore", headers={"User-Agent": "syndicate-replay/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read().decode("utf-8"))
    f.write_text(json.dumps(data), encoding="utf-8")
    return data


def actual_from_linescore(ls: dict, box: dict) -> dict | None:
    inn = ls.get("innings") or []
    teams = ls.get("teams") or {}
    a = (teams.get("away") or {}).get("runs")
    h = (teams.get("home") or {}).get("runs")
    if a is None or h is None or len(inn) < 5:
        return None
    f5 = sum(int((x.get("away") or {}).get("runs") or 0) + int((x.get("home") or {}).get("runs") or 0) for x in inn[:5])
    hr = sum(int((((box.get("teams") or {}).get(s) or {}).get("teamStats") or {}).get("batting", {}).get("homeRuns") or 0)
             for s in ("away", "home"))
    return {"total": int(a) + int(h), "home_win": 1.0 if int(h) > int(a) else 0.0, "f5": f5, "hr": hr}


def score(res: dict, act: dict) -> dict:
    n = res["n"]
    tot = Counter({int(k): v for k, v in res["totals"].items()})
    f5 = Counter({int(k): v for k, v in res["f5"].items()})
    mean = sum(k * v for k, v in tot.items()) / n
    return {"crps_total": crps_discrete(tot, n, act["total"]),
            "brier_home": (res["p_home"] - act["home_win"]) ** 2,
            "runs_err": mean - act["total"],
            "abs_runs_err": abs(mean - act["total"]),
            "crps_f5": crps_discrete(f5, n, act["f5"]),
            "hr_err": res["hr_mean"] - act["hr"]}


def paired(rows: list[dict], key: str) -> dict:
    d = [r["fwd"][key] - r["none"][key] for r in rows]
    n = len(d)
    if n < 2:
        return {"n": n}
    m = sum(d) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in d) / (n - 1))
    se = sd / math.sqrt(n)
    return {"n": n, "none": sum(r["none"][key] for r in rows) / n, "fwd": sum(r["fwd"][key] for r in rows) / n,
            "diff_fwd_minus_none": m, "se": se, "ci95": [m - 1.96 * se, m + 1.96 * se]}


def summarise(rows: list[dict]) -> dict:
    return {k: paired(rows, k) for k in ("crps_total", "brier_home", "runs_err", "abs_runs_err", "crps_f5", "hr_err")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", required=True, help="as-of root holding daily/snapshots/<d>/roster_objs")
    ap.add_argument("--dates", nargs="+", required=True)
    ap.add_argument("--windows", nargs="*", default=[], help="name=first..last, scored separately")
    ap.add_argument("--sims", type=int, default=400)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--cache", default=os.path.join(os.environ.get("TMPDIR", "/tmp"), "mlb_starter_replay_cache"))
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    data_dir = Path(os.path.expanduser(args.data_root))
    cache = Path(os.path.expanduser(args.cache))
    cache.mkdir(parents=True, exist_ok=True)
    counters = Counter()
    jobs = []
    for d in sorted(set(args.dates)):
        for g in rp.games_for_date(data_dir, d):
            for arm in ARMS:
                jobs.append(dict(g, arm=arm, sims=args.sims, seed=args.seed))
    by_game: dict[int, dict] = {}
    with cf.ProcessPoolExecutor(max_workers=args.workers) as ex:
        for res in ex.map(_sim_game, jobs, chunksize=1):
            by_game.setdefault(res["game_pk"], {"date": res["date"]})[res["arm"]] = res
    rows = []
    for pk, g in sorted(by_game.items()):
        if not all(a in g for a in ARMS):
            counters["arm_missing"] += 1
            continue
        try:
            act = actual_from_linescore(linescore(pk, cache), rp.boxscore(pk, cache))
        except Exception:
            act = None
        if act is None:
            counters["actual_unavailable"] += 1
            continue
        rows.append({"date": g["date"], "game_pk": pk, "actual": act,
                     "none": score(g["none"], act), "fwd": score(g["fwd"], act),
                     "pm_fwd_hr": arm_pm("fwd").get("hr_rate_mult")})
    rep = {"dates": sorted(set(args.dates)), "sims": args.sims, "seed": args.seed, "counters": dict(counters),
           "games": len(rows), "all": summarise(rows)}
    for w in args.windows:
        name, _, rng = w.partition("=")
        lo, _, hi = rng.partition("..")
        sel = [r for r in rows if lo <= r["date"] <= hi]
        rep[name] = dict(summarise(sel), games=len(sel), dates=len({r["date"] for r in sel}))
    rep["rows"] = rows
    Path(args.out).write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in rep.items() if k != "rows"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
