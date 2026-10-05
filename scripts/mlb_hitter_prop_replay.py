"""Re-fit MLB hitter-prop probability calibrations on the CURRENT engine (lane mlb-hr-prop-calibration).

Production serves p_*_cal = sigmoid(a * logit(p_raw) + b) per prop key:
  data/tuning/hitter_props_calibration/default.json  (18 keys, re-fit 2026-09-01)
  data/tuning/hitter_hr_calibration/default.json      (hr_1plus, fitted 2026-07-17)
This replays today's engine (`mlb_starter_length_replay.py` loaders, validated
against production) over stored as-of roster_objs, records every lineup batter's
RAW sim P(X >= k), joins the box-score outcome, fits a new (a, b) per key on TUNE
and decides per key on HOLDOUT by the rule pre-registered in .syndicate/lanes.md:
lowest holdout log-loss among {current served map, re-fit map, identity}; replace
the current map only if it wins by >= 0.001 nats/row and its calibration-in-the-
large is no worse.

  --collect  run the replay and write rows (slow)
  --analyze  fit + decide from a rows file (fast, deterministic)
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import math
import os
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mlb_starter_length_replay as rp  # noqa: E402

TUNING = rp.VENDOR / "data" / "tuning"
PROPS_FILE = TUNING / "hitter_props_calibration" / "default.json"
HR_FILE = TUNING / "hitter_hr_calibration" / "default.json"

# prop key -> (stat, threshold); TB is derived
_STAT = {"hits": "H", "doubles": "2B", "triples": "3B", "rbi": "RBI", "runs": "R",
         "sb": "SB", "total_bases": "TB", "hr": "HR"}


def parse_key(key: str) -> tuple[str, int]:
    base, _, k = key.rpartition("_")
    return _STAT[base], int(k.replace("plus", ""))


def _tb(row: dict) -> float:
    h, d2, d3, hr = (float(row.get(k) or 0) for k in ("H", "2B", "3B", "HR"))
    return (h - d2 - d3 - hr) + 2 * d2 + 3 * d3 + 4 * hr


def _val(row: dict, stat: str) -> float:
    return _tb(row) if stat == "TB" else float(row.get(stat) or 0.0)


def keys() -> list[str]:
    props = json.loads(PROPS_FILE.read_text(encoding="utf-8")).get("props") or {}
    return sorted(props) + ["hr_1plus"]


def current_map(key: str) -> dict:
    from sim_engine.prob_calibration import resolve_prop_calibration_cfg

    cfg = json.loads((HR_FILE if key == "hr_1plus" else PROPS_FILE).read_text(encoding="utf-8"))
    return resolve_prop_calibration_cfg(cfg, key) or {}


def apply_map(p: float, m: dict) -> float:
    from sim_engine.prob_calibration import apply_prob_calibration

    return float(apply_prob_calibration(float(p), m))


# ----------------------------------------------------------------- collect
def _sim_game(job: dict) -> dict:
    from sim_engine.data.roster_artifact import read_game_roster_artifact
    from sim_engine.models import GameConfig
    from sim_engine.simulate import simulate_game

    art = read_game_roster_artifact(Path(job["roster_path"]))
    away, home = art["away"], art["home"]
    rec = rp._load_json(job["sim_path"]) if job.get("sim_path") else None
    weather, park, umpire = rp.context_from_sim(rec)
    lineup = [int(b.player.mlbam_id) for ro in (away, home) for b in (ro.lineup.batters or [])]
    specs = [(k,) + parse_key(k) for k in job["keys"]]
    hits = {pid: defaultdict(int) for pid in lineup}
    n = int(job["sims"])
    for i in range(n):
        cfg = GameConfig(rng_seed=int(job["seed"]) + i, weather=weather, park=park, umpire=umpire,
                         manager_pitching="v2", manager_pitching_overrides=job["mp"], pitch_model_overrides=job["pm"])
        bs = simulate_game(away, home, cfg).batter_stats or {}
        for pid in lineup:
            row = bs.get(pid) or bs.get(str(pid)) or {}
            for key, stat, k in specs:
                if _val(row, stat) >= k:
                    hits[pid][key] += 1
    return {"date": job["date"], "game_pk": job["game_pk"], "n": n,
            "p": {str(pid): {key: hits[pid][key] / n for key, _, _ in specs} for pid in lineup}}


def _box_batters(box: dict) -> dict:
    out = {}
    for side in ("away", "home"):
        t = (box.get("teams") or {}).get(side) or {}
        for pkey, pl in (t.get("players") or {}).items():
            st = ((pl.get("stats") or {}).get("batting") or {})
            if not st:
                continue
            out[int(pkey[2:])] = {"PA": int(st.get("plateAppearances") or 0), "H": int(st.get("hits") or 0),
                                  "2B": int(st.get("doubles") or 0), "3B": int(st.get("triples") or 0),
                                  "HR": int(st.get("homeRuns") or 0), "R": int(st.get("runs") or 0),
                                  "RBI": int(st.get("rbi") or 0), "SB": int(st.get("stolenBases") or 0)}
    return out


def collect(args) -> None:
    data_dir = Path(os.path.expanduser(args.data_root))
    cache = Path(os.path.expanduser(args.cache))
    cache.mkdir(parents=True, exist_ok=True)
    mp, pm = rp.forward_overrides()
    ks = keys()
    jobs = []
    for d in sorted(set(args.dates)):
        for g in rp.games_for_date(data_dir, d):
            g.update({"sims": args.sims, "seed": args.seed, "mp": mp, "pm": pm, "keys": ks})
            jobs.append(g)
    with cf.ProcessPoolExecutor(max_workers=args.workers) as ex:
        results = list(ex.map(_sim_game, jobs, chunksize=1))
    rows, counters = [], defaultdict(int)
    for res in results:
        try:
            box = _box_batters(rp.boxscore(res["game_pk"], cache))
        except Exception:
            counters["boxscore_unavailable"] += 1
            continue
        for pid, ps in res["p"].items():
            a = box.get(int(pid))
            if not a or a["PA"] < 1:
                counters["batter_did_not_appear"] += 1
                continue
            y = {}
            for key in ps:
                stat, k = parse_key(key)
                y[key] = int(_val(a, stat) >= k)
            rows.append({"date": res["date"], "game_pk": res["game_pk"], "pid": int(pid), "p": ps, "y": y})
    Path(args.rows).write_text(json.dumps({"counters": dict(counters), "sims": args.sims, "rows": rows}), encoding="utf-8")
    print(json.dumps({"rows": len(rows), "counters": dict(counters)}))


# ----------------------------------------------------------------- analyze
EPS = 1e-4


def _logit(p: float) -> float:
    p = min(max(p, EPS), 1 - EPS)
    return math.log(p / (1 - p))


def _sig(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-z)) if z > -50 else 0.0


def fit_affine(ps: list[float], ys: list[int], lam: float = 10.0, iters: int = 50) -> tuple[float, float]:
    """Penalised logistic fit of y on logit(p): sigmoid(a*x+b), L2 toward (a,b)=(1,0). Newton."""
    xs = [_logit(p) for p in ps]
    a, b = 1.0, 0.0
    for _ in range(iters):
        ga = 2 * lam * (a - 1.0)
        gb = 2 * lam * b
        haa = hbb = 2 * lam
        hab = 0.0
        for x, y in zip(xs, ys):
            q = _sig(a * x + b)
            r = q - y
            w = q * (1 - q)
            ga += r * x
            gb += r
            haa += w * x * x
            hab += w * x
            hbb += w
        det = haa * hbb - hab * hab
        if det <= 0:
            break
        da = (hbb * ga - hab * gb) / det
        db = (haa * gb - hab * ga) / det
        a -= da
        b -= db
        if abs(da) < 1e-8 and abs(db) < 1e-8:
            break
    return a, b


def logloss(ps, ys):
    return sum(-(y * math.log(min(max(p, EPS), 1 - EPS)) + (1 - y) * math.log(1 - min(max(p, EPS), 1 - EPS)))
               for p, y in zip(ps, ys)) / len(ys)


def analyze(args) -> dict:
    data = json.loads(Path(args.rows).read_text(encoding="utf-8"))
    rows = data["rows"]
    cut = args.split
    out = {"rows": len(rows), "split": cut, "keys": {}}
    for key in keys():
        tune = [(r["p"][key], r["y"][key]) for r in rows if r["date"] < cut and key in r["p"]]
        hold = [(r["p"][key], r["y"][key]) for r in rows if r["date"] >= cut and key in r["p"]]
        if len(tune) < 200 or len(hold) < 100:
            out["keys"][key] = {"decision": "INSUFFICIENT_N", "n_tune": len(tune), "n_hold": len(hold)}
            continue
        cur = current_map(key)
        a, b = fit_affine([p for p, _ in tune], [y for _, y in tune], lam=args.lam)
        refit = {"enabled": True, "mode": "affine_logit", "a": a, "b": b}
        hp, hy = [p for p, _ in hold], [y for _, y in hold]
        rate = sum(hy) / len(hy)
        arms = {}
        for name, m in (("current", cur), ("refit", refit), ("identity", None)):
            q = [apply_map(p, m) for p in hp] if m is not None else list(hp)
            arms[name] = {"logloss": logloss(q, hy), "mean_p": sum(q) / len(q), "citl": abs(sum(q) / len(q) - rate)}
        best = min(arms, key=lambda k: arms[k]["logloss"])
        replace = (best != "current"
                   and arms["current"]["logloss"] - arms[best]["logloss"] >= args.min_gain
                   and arms[best]["citl"] <= arms["current"]["citl"])
        out["keys"][key] = {"n_tune": len(tune), "n_hold": len(hold), "holdout_rate": rate,
                            "current": {"a": cur.get("a"), "b": cur.get("b"), "enabled": cur.get("enabled")},
                            "refit": {"a": a, "b": b}, "arms": arms, "best": best,
                            "decision": ("REPLACE_WITH_" + best.upper()) if replace else "KEEP_CURRENT"}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--collect", action="store_true")
    ap.add_argument("--analyze", action="store_true")
    ap.add_argument("--data-root", default=os.environ.get("MLB_BETTING_DATA_ROOT", ""))
    ap.add_argument("--dates", nargs="+")
    ap.add_argument("--sims", type=int, default=200)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--cache", default=os.path.join(os.environ.get("TMPDIR", "/tmp"), "mlb_starter_replay_cache"))
    ap.add_argument("--rows", required=True)
    ap.add_argument("--split", default="2026-07-04")
    ap.add_argument("--lam", type=float, default=10.0)
    ap.add_argument("--min-gain", type=float, default=0.001)
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    if args.collect:
        collect(args)
    if args.analyze:
        rep = analyze(args)
        if args.out:
            Path(args.out).write_text(json.dumps(rep, indent=1), encoding="utf-8")
        for k, v in rep["keys"].items():
            if "arms" in v:
                A = v["arms"]
                print(f"{k:20s} n={v['n_hold']:5d} rate={v['holdout_rate']:.3f} LL cur {A['current']['logloss']:.4f} refit {A['refit']['logloss']:.4f} "
                      f"id {A['identity']['logloss']:.4f} | meanp cur {A['current']['mean_p']:.3f} refit {A['refit']['mean_p']:.3f} id {A['identity']['mean_p']:.3f} -> {v['decision']}")
            else:
                print(k, v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
