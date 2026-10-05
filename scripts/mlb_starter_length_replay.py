"""Replay the CURRENT MLB engine on stored, as-of roster objects and grade starter length.

Lane `mlb-starter-length`. The as-of backtest (findings 2026-10-02) found starter
outs +4.75 on the May–July engine. 09-14 found +7.1% on the post-refit engine, plus
too few early exits: 14% of real starts end at <=9 outs, against 1.7% in the sim.
The stored projections cannot answer either question for TODAY's code: the May–July
files were made by older code, and the later ones are post-start re-sims.

So this replays today's `simulate_game` over the EXACT inputs the sim consumed on
each date: `snapshots/<date>/roster_objs/roster_obj_*.json` (`roster_artifact.read_game_roster_artifact`).
Park, weather and umpire are rebuilt from the stored sim record of the same game.
The config is production's: the forward tuning files, `manager_pitching='v2'`.
The actual starter outs come from StatsAPI box scores. A start whose actual starter
is not the roster's starter is EXCLUDED and counted (an opener, or a late scratch).

Override any hook knob with `--set key=value` (merged over the forward
manager-pitching overrides) to measure a candidate on the same inputs. Same seeds,
so baseline-vs-candidate differences are paired.

VALIDATE FIRST: `--validate-date D` compares the replay's starter `outs_mean` against
the stored sim's `pitcher_props.outs_mean` for a date the CURRENT code produced. If the
two disagree beyond Monte Carlo noise, the replay is not production and nothing it
says counts.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import glob
import json
import math
import os
import random
import re
import sys
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VENDOR = REPO / "vendor" / "mlb_bettingv2"
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

STATSAPI = "https://statsapi.mlb.com/api/v1"


# ------------------------------------------------------------------ inputs
def _load_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def forward_overrides() -> tuple[dict, dict]:
    from sim_engine.forward_tuning import (
        FORWARD_MANAGER_PITCHING_OVERRIDES_PATH as MP,
        FORWARD_PITCH_MODEL_OVERRIDES_PATH as PM,
    )
    mp = {k: v for k, v in _load_json(MP).items() if not k.startswith("_")}
    pm = {k: v for k, v in _load_json(PM).items() if not k.startswith("_")}
    return mp, pm


def context_from_sim(rec: dict | None):
    """Rebuild park/weather/umpire from the stored sim record (None -> neutral)."""
    from sim_engine.models import ParkFactors, UmpireFactors, WeatherFactors

    if not rec:
        return None, None, None
    w = rec.get("weather") or {}
    p = rec.get("park") or {}
    u = rec.get("umpire") or {}
    weather = park = umpire = None
    try:
        weather = WeatherFactors(source=str(w.get("source") or ""), condition=str(w.get("condition") or ""),
                                 temperature_f=w.get("temperature_f"), wind_speed_mph=w.get("wind_speed_mph"),
                                 wind_direction=str(w.get("wind_direction") or ""), wind_raw=str(w.get("wind_raw") or ""),
                                 is_dome=w.get("is_dome"))
    except Exception:
        weather = None
    try:
        pm = p.get("multipliers") or {}
        park = ParkFactors(source=str(p.get("source") or ""), venue_id=p.get("venue_id"),
                           venue_name=str(p.get("venue_name") or ""), roof_type=str(p.get("roof_type") or ""),
                           roof_status=str(p.get("roof_status") or ""),
                           hr_mult_override=pm.get("hr_mult"), inplay_hit_mult_override=pm.get("inplay_hit_mult"),
                           xb_share_mult_override=pm.get("xb_share_mult"))
    except Exception:
        park = None
    try:
        umpire = UmpireFactors(source=str(u.get("source") or ""), home_plate_umpire_id=u.get("home_plate_umpire_id"),
                               called_strike_mult=float(u.get("called_strike_mult") or 1.0))
    except Exception:
        umpire = None
    return weather, park, umpire


def games_for_date(data_dir: Path, date: str, stored: str = "frozen") -> list[dict]:
    """`stored` picks which sim record supplies context and the validation target:
    "frozen" (sims_pregame first) for backtests, "live" when validating against the
    sim built from the CURRENT roster_objs (a post-start re-sim rewrites both)."""
    snap = data_dir / "daily" / "snapshots" / date / "roster_objs"
    sims = {}
    frozen = glob.glob(str(data_dir / "daily" / "sims_pregame" / date / "sim_*.json"))
    live = glob.glob(str(data_dir / "daily" / "sims" / date / "sim_*.json"))
    for f in (frozen + live if stored == "frozen" else live + frozen):
        m = re.search(r"pk(\d+)", Path(f).name)
        if m and int(m.group(1)) not in sims:
            sims[int(m.group(1))] = f
    out = []
    for f in sorted(glob.glob(str(snap / "roster_obj_*.json"))):
        m = re.search(r"pk(\d+)", Path(f).name)
        if not m:
            continue
        pk = int(m.group(1))
        out.append({"date": date, "game_pk": pk, "roster_path": f, "sim_path": sims.get(pk)})
    return out


# -------------------------------------------------------------------- sim
def _sim_one_game(job: dict) -> dict:
    from sim_engine.data.roster_artifact import read_game_roster_artifact
    from sim_engine.models import GameConfig
    from sim_engine.simulate import simulate_game

    art = read_game_roster_artifact(Path(job["roster_path"]))
    away, home = art["away"], art["home"]
    rec = _load_json(job["sim_path"]) if job.get("sim_path") else None
    weather, park, umpire = context_from_sim(rec)
    starters = {"away": int(away.lineup.pitcher.player.mlbam_id), "home": int(home.lineup.pitcher.player.mlbam_id)}
    acc = {side: defaultdict(list) for side in starters}
    totals = []
    for i in range(int(job["sims"])):
        cfg = GameConfig(rng_seed=int(job["seed"]) + i, weather=weather, park=park, umpire=umpire,
                         manager_pitching="v2", manager_pitching_overrides=job["mp"],
                         pitch_model_overrides=job["pm"])
        r = simulate_game(away, home, cfg)
        ps = r.pitcher_stats or {}
        for side, pid in starters.items():
            row = ps.get(pid) or ps.get(str(pid)) or {}
            for k in ("OUTS", "P", "SO", "H", "ER", "BB", "BF"):
                acc[side][k].append(float(row.get(k) or 0.0))
        try:
            totals.append(float(r.away_score) + float(r.home_score))
        except Exception:
            pass
    stored = {}
    if rec:
        for pid, pp in ((rec.get("sim") or {}).get("pitcher_props") or {}).items():
            stored[int(pid)] = pp.get("outs_mean")
    return {"date": job["date"], "game_pk": job["game_pk"], "starters": starters,
            "dists": {side: dict(v) for side, v in acc.items()},
            "total_runs_mean": (sum(totals) / len(totals)) if totals else None,
            "stored_outs_mean": {str(k): v for k, v in stored.items()},
            "had_context": rec is not None}


# ---------------------------------------------------------------- actuals
def boxscore(pk: int, cache: Path):
    f = cache / f"box_{pk}.json"
    if f.exists():
        return _load_json(f)
    req = urllib.request.Request(f"{STATSAPI}/game/{pk}/boxscore", headers={"User-Agent": "syndicate-replay/1.0"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode("utf-8"))
            break
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))
    f.write_text(json.dumps(data), encoding="utf-8")
    return data


def actual_starters(box: dict) -> dict:
    out = {}
    for side in ("away", "home"):
        t = (box.get("teams") or {}).get(side) or {}
        order = t.get("pitchers") or []
        if not order:
            continue
        pid = int(order[0])
        st = (((t.get("players") or {}).get(f"ID{pid}") or {}).get("stats") or {}).get("pitching") or {}
        ip = str(st.get("inningsPitched") or "0.0")
        whole, _, frac = ip.partition(".")
        outs = st.get("outs")
        if outs is None:
            outs = int(whole or 0) * 3 + int(frac or 0)
        out[side] = {"pid": pid, "OUTS": int(outs), "P": int(st.get("numberOfPitches") or st.get("pitchesThrown") or 0),
                     "SO": int(st.get("strikeOuts") or 0), "H": int(st.get("hits") or 0),
                     "ER": int(st.get("earnedRuns") or 0), "BB": int(st.get("baseOnBalls") or 0)}
    return out


# ------------------------------------------------------------------ stats
def boot_ci(rows, fn, draws=1000, seed=7):
    by = defaultdict(list)
    for r in rows:
        by[r["game_pk"]].append(r)
    keys = list(by)
    if not keys:
        return None, None, None
    est = fn([r for k in keys for r in by[k]])
    rng = random.Random(seed)
    vals = []
    for _ in range(draws):
        samp = [r for _k in keys for r in by[keys[rng.randrange(len(keys))]]]
        v = fn(samp)
        if v is not None:
            vals.append(v)
    vals.sort()
    return est, vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1]


def summarise(starts: list[dict], draws: int) -> dict:
    mean = lambda xs: sum(xs) / len(xs) if xs else None  # noqa: E731
    out = {"n_starts": len(starts), "games": len({s["game_pk"] for s in starts}),
           "dates": len({s["date"] for s in starts})}
    if not starts:
        return out
    for k in ("OUTS", "P", "SO", "H", "ER", "BB"):
        b, lo, hi = boot_ci(starts, lambda rs, k=k: mean([r["model"][k] - r["actual"][k] for r in rs]), draws)
        out[k] = {"model_mean": mean([s["model"][k] for s in starts]), "actual_mean": mean([s["actual"][k] for s in starts]),
                  "bias": b, "bias_ci": [lo, hi],
                  "mae": mean([abs(s["model"][k] - s["actual"][k]) for s in starts])}
    out["share_le9_outs"] = {"model": mean([s["model"]["p_le9"] for s in starts]),
                             "actual": mean([1.0 if s["actual"]["OUTS"] <= 9 else 0.0 for s in starts])}
    out["share_eq15_outs"] = {"model": mean([s["model"]["p_eq15"] for s in starts]),
                              "actual": mean([1.0 if s["actual"]["OUTS"] == 15 else 0.0 for s in starts])}
    out["share_ge18_outs"] = {"model": mean([s["model"]["p_ge18"] for s in starts]),
                              "actual": mean([1.0 if s["actual"]["OUTS"] >= 18 else 0.0 for s in starts])}
    # PIT of the actual outs inside the sim distribution (0.5 = centred), and the CRPS proxy
    out["outs_pit_mean"] = mean([s["model"]["pit"] for s in starts])
    out["outs_crps"] = mean([s["model"]["crps"] for s in starts])
    return out


def crps_discrete(samples: list[float], y: float) -> float:
    n = len(samples)
    if not n:
        return float("nan")
    s = sorted(samples)
    t1 = sum(abs(x - y) for x in s) / n
    # E|X-X'| via sorted formula
    acc = 0.0
    for i, x in enumerate(s):
        acc += x * (2 * i - n + 1)
    t2 = 2.0 * acc / (n * n)
    return t1 - 0.5 * t2


def run(args) -> dict:
    data_dir = Path(os.path.expanduser(args.data_root))
    cache = Path(os.path.expanduser(args.cache))
    cache.mkdir(parents=True, exist_ok=True)
    mp, pm = forward_overrides()
    for kv in args.set or []:
        k, _, v = kv.partition("=")
        try:
            mp[k.strip()] = json.loads(v)
        except ValueError:
            mp[k.strip()] = v
    dates = sorted(set(args.dates))
    jobs = []
    for d in dates:
        for g in games_for_date(data_dir, d, args.stored):
            g.update({"sims": args.sims, "seed": args.seed, "mp": mp, "pm": pm})
            jobs.append(g)
    counters = defaultdict(int)
    counters["games_with_roster_obj"] = len(jobs)
    results = []
    with cf.ProcessPoolExecutor(max_workers=args.workers) as ex:
        for res in ex.map(_sim_one_game, jobs, chunksize=1):
            results.append(res)
    starts = []
    validate = []
    for res in results:
        if not res["had_context"]:
            counters["games_no_stored_context"] += 1
        for side, pid in res["starters"].items():
            st = res["stored_outs_mean"].get(str(pid))
            outs = res["dists"][side].get("OUTS") or []
            if st is not None and outs:
                validate.append({"game_pk": res["game_pk"], "replay": sum(outs) / len(outs), "stored": float(st)})
        if args.validate_only:
            continue
        try:
            act = actual_starters(boxscore(res["game_pk"], cache))
        except Exception:
            counters["boxscore_unavailable"] += 1
            continue
        for side, pid in res["starters"].items():
            a = act.get(side)
            if not a:
                counters["actual_missing"] += 1
                continue
            if a["pid"] != pid:
                counters["starter_mismatch_excluded"] += 1
                continue
            d = res["dists"][side]
            outs = d.get("OUTS") or []
            if not outs:
                counters["model_empty"] += 1
                continue
            n = len(outs)
            y = a["OUTS"]
            m = {k: sum(v) / len(v) for k, v in d.items() if v}
            m["p_le9"] = sum(1 for x in outs if x <= 9) / n
            m["p_eq15"] = sum(1 for x in outs if x == 15) / n
            m["p_ge18"] = sum(1 for x in outs if x >= 18) / n
            m["pit"] = (sum(1 for x in outs if x < y) + 0.5 * sum(1 for x in outs if x == y)) / n
            m["crps"] = crps_discrete(outs, y)
            starts.append({"date": res["date"], "game_pk": res["game_pk"], "pid": pid, "model": m, "actual": a})
    rep = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "dates": dates,
           "sims_per_game": args.sims, "seed": args.seed, "overrides_applied": args.set or [],
           "manager_pitching_overrides_effective": mp, "counters": dict(counters)}
    if validate:
        diffs = [v["replay"] - v["stored"] for v in validate]
        rep["validation"] = {"n_starters": len(validate), "mean_replay": sum(v["replay"] for v in validate) / len(validate),
                             "mean_stored": sum(v["stored"] for v in validate) / len(validate),
                             "mean_diff": sum(diffs) / len(diffs),
                             "max_abs_diff": max(abs(x) for x in diffs), "rows": validate}
    if not args.validate_only:
        rep["all"] = summarise(starts, args.draws)
        cut = dates[int(len(dates) * 2 / 3)] if len(dates) >= 3 else None
        if cut:
            rep["split_date"] = cut
            rep["tune"] = summarise([s for s in starts if s["date"] < cut], args.draws)
            rep["holdout"] = summarise([s for s in starts if s["date"] >= cut], args.draws)
        rep["total_runs_model_mean"] = (sum(r["total_runs_mean"] for r in results if r["total_runs_mean"] is not None)
                                        / max(1, sum(1 for r in results if r["total_runs_mean"] is not None)))
        if args.dump_starts:
            rep["starts"] = starts
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", default=os.environ.get("MLB_BETTING_DATA_ROOT", ""),
                    help="the MLB data dir holding daily/ (fleet: .../mlb_source/source_artifacts/data)")
    ap.add_argument("--dates", nargs="+", required=True)
    ap.add_argument("--sims", type=int, default=200)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--draws", type=int, default=1000)
    ap.add_argument("--set", action="append", help="manager-pitching override key=value (JSON value)")
    ap.add_argument("--cache", default=os.path.join(os.environ.get("TMPDIR", "/tmp"), "mlb_starter_replay_cache"))
    ap.add_argument("--validate-only", action="store_true")
    ap.add_argument("--stored", choices=["frozen", "live"], default="frozen")
    ap.add_argument("--dump-starts", action="store_true")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    rep = run(args)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    brief = {k: rep.get(k) for k in ("counters", "validation", "split_date", "all", "tune", "holdout", "total_runs_model_mean")}
    if brief.get("validation"):
        brief["validation"] = {k: v for k, v in brief["validation"].items() if k != "rows"}
    print(json.dumps(brief, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
