"""Fit the count-shape terms to the REAL count matrix. `#440`.

**Fit to the matrix, not to K/PA.** K/PA is a scalar summary of an 11x5 matrix,
and three earlier attempts to hit it directly failed for the same reason: many
wrong matrices produce the right K/PA. Two of them shipped a fix that took K/PA
from 27% low to 26% high while making the pitch mix worse. The matrix is the
thing that is actually wrong; K/PA is reported here only as a CONSEQUENCE, to
catch a fit that games the summary.

Scored on total absolute deviation across every count x outcome cell, weighted
by how often each count really occurs -- an unweighted score lets 3-0, which is
1% of pitches, drag the fit as hard as 0-0, which is 26%.

Coordinate descent, not a full grid: 4 parameters at 5 values each is 625 sim
batches, and the parameters are close to separable because each one owns a
disjoint set of counts (2-strike / <2-strike / 0-strike-behind).
"""

from __future__ import annotations

import argparse
import csv
import glob
import gzip
import sys
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "vendor" / "mlb_bettingv2"))

RAW = "vendor/mlb_bettingv2/data/raw/statcast/pitches/*/*.csv.gz"
OUTCOMES = ("BALL", "CALLED", "SWING", "FOUL", "IN_PLAY")
COUNTS = ["0-0", "0-1", "0-2", "1-0", "1-1", "1-2", "2-0", "2-1", "2-2", "3-0", "3-1", "3-2"]

_DESC = {
    "ball": "BALL", "blocked_ball": "BALL", "pitchout": "BALL",
    "called_strike": "CALLED",
    "swinging_strike": "SWING", "swinging_strike_blocked": "SWING",
    "missed_bunt": "SWING",
    "foul": "FOUL", "foul_tip": "FOUL", "foul_bunt": "FOUL",
    "hit_into_play": "IN_PLAY", "hit_into_play_score": "IN_PLAY",
    "hit_into_play_no_out": "IN_PLAY",
}


def real_matrix(max_files: int) -> dict:
    out = defaultdict(Counter)
    files = sorted(glob.glob(str(REPO / RAW)))[:max_files]
    for path in files:
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
            for r in csv.DictReader(fh):
                o = _DESC.get((r.get("description") or "").strip().lower())
                if not o:
                    continue
                try:
                    b, s = int(float(r["balls"])), int(float(r["strikes"]))
                except Exception:
                    continue
                if 0 <= b <= 3 and 0 <= s <= 2:
                    out[f"{b}-{s}"][o] += 1
    return out


def sim_matrix(games, sims, seed, overrides):
    from sim_engine.models import GameConfig
    from sim_engine.simulate import simulate_game

    out = defaultdict(Counter)
    pa = k = pitches = 0
    for g in games:
        # GameConfig.pitch_model_overrides is the SUPPORTED channel (simulate.py:2256).
        # setattr on the dataclass does NOT work: dataclass __init__ binds its
        # defaults at class creation, so a later class-attribute write is a no-op
        # and every grid row comes out identical.
        cfg = GameConfig(rng_seed=seed, manager_pitching="v2", pbp="pitch",
                         pitch_model_overrides=dict(overrides or {}))
        for i in range(sims):
            try:
                res = simulate_game(g["away"], g["home"], replace(cfg, rng_seed=seed + i))
            except Exception:
                continue
            for ev in (getattr(res, "pbp", None) or []):
                # the type is "PITCH", uppercase. Filtering on "pitch" matched
                # nothing and the first run of this script reported a deviation
                # of 0.0000 on an empty sim side -- a perfect score for having
                # measured nothing at all.
                if str(ev.get("type") or "").upper() != "PITCH":
                    continue
                c = ev.get("count") or {}
                b, s = c.get("balls"), c.get("strikes")
                call = str(ev.get("call") or "").upper()
                if b is None or s is None or call not in OUTCOMES:
                    continue
                out[f"{int(b)}-{int(s)}"][call] += 1
                pitches += 1
            for _pid, st in res.batter_stats.items():
                pa += int(st.get("PA", 0) or 0)
                k += int(st.get("SO", 0) or 0)
    if pa <= 0 or pitches <= 0:
        # REFUSE rather than return zeros. A zero deviation is the BEST possible
        # score, so an empty sim side does not look like a failure -- it looks
        # like a perfect fit, and coordinate descent would happily "converge".
        raise RuntimeError(
            f"sim produced pa={pa} pitches={pitches}; refusing to score an empty "
            "sim side")
    return out, k / pa, pitches / pa


def score(real, sim) -> float:
    """Usage-weighted total absolute deviation. Lower is better."""
    total_real = sum(sum(v.values()) for v in real.values())
    dev = 0.0
    for c in COUNTS:
        r, s = real.get(c), sim.get(c)
        if not r or not s:
            continue
        rn, sn = sum(r.values()), sum(s.values())
        if rn <= 0 or sn <= 0:
            continue
        w = rn / total_real
        dev += w * sum(abs(r[o] / rn - s[o] / sn) for o in OUTCOMES)
    return dev


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--games", type=int, default=4)
    ap.add_argument("--sims", type=int, default=12)
    ap.add_argument("--seed", type=int, default=404)
    ap.add_argument("--max-files", type=int, default=999)
    ap.add_argument("--rounds", type=int, default=2)
    args = ap.parse_args()

    from sim_engine.data.roster_artifact import read_game_roster_artifact
    import sim_engine.pitch_model as PM

    print("loading real matrix", flush=True)
    real = real_matrix(args.max_files)
    print(f"  {sum(sum(v.values()) for v in real.values()):,} real pitches", flush=True)

    paths = sorted(glob.glob(str(REPO / "data/mlb_source/source_artifacts/data/**/"
                                    "roster_objs/roster_obj_*.json"), recursive=True))
    games = []
    for p in paths:
        if len(games) >= args.games:
            break
        try:
            r = read_game_roster_artifact(Path(p))
            if r.get("home") is not None:
                games.append(r)
        except Exception:
            pass
    if not games:
        print("REFUSED: no rosters")
        return 1

    # file-level injection: mutating __dataclass_fields__ defaults does NOT
    # affect construction, which once produced 9 identical grid rows measuring
    # nothing at all.
    # (no set_param: overrides travel through GameConfig, see sim_matrix)

    GRID = {
        "two_strike_waste_ball_boost": [1.0, 1.15, 1.3, 1.45, 1.6],
        "two_strike_called_damp":      [1.0, 0.55, 0.42, 0.32, 0.24],
        "early_count_foul_boost":      [1.0, 1.3, 1.55, 1.8, 2.05],
        "behind_count_called_boost":   [1.0, 1.25, 1.5, 1.75],
    }
    best = {k: 1.0 for k in GRID}
    m, kpa, ppa = sim_matrix(games, args.sims, args.seed, best)
    cur = score(real, m)

    # REACHABILITY before correctness: if a deliberately extreme override does
    # not move the score, the injection is not reaching the engine and every
    # number below is meaningless. This is the check that was missing when the
    # first run reported a perfect 0.0000 on an empty sim side.
    probe = dict(best, two_strike_called_damp=0.10, early_count_foul_boost=2.5)
    pm, _pk, _pp = sim_matrix(games, args.sims, args.seed, probe)
    if abs(score(real, pm) - cur) < 1e-9:
        print("REFUSED: overrides do not reach the engine (probe changed nothing)")
        return 1
    print(f"  reachability OK: probe moved dev {cur:.4f} -> {score(real, pm):.4f}", flush=True)
    print(f"\nbaseline (all no-op): dev {cur:.4f}   K/PA {kpa:.4f}   pitches/PA {ppa:.2f}", flush=True)

    for rnd in range(args.rounds):
        print(f"\n--- round {rnd+1} ---", flush=True)
        for name, values in GRID.items():
            best_v, best_s, best_k, best_p = best[name], cur, None, None
            for v in values:
                if v == best[name]:
                    continue
                trial = dict(best, **{name: v})
                m, kpa, ppa = sim_matrix(games, args.sims, args.seed, trial)
                sc = score(real, m)
                if sc < best_s:
                    best_v, best_s, best_k, best_p = v, sc, kpa, ppa
            if best_v != best[name]:
                print(f"  {name:<30} {best[name]} -> {best_v}   dev {cur:.4f} -> {best_s:.4f}"
                      f"   K/PA {best_k:.4f}  p/PA {best_p:.2f}", flush=True)
                best[name] = best_v
                cur = best_s
            else:
                print(f"  {name:<30} unchanged at {best[name]}", flush=True)

    m, kpa, ppa = sim_matrix(games, args.sims, args.seed, best)
    print("\n" + "=" * 62)
    print("FITTED")
    for k, v in best.items():
        print(f"  {k:<32} {v}")
    print(f"\n  weighted matrix deviation {cur:.4f}")
    print(f"  K/PA        {kpa:.4f}   (real 0.226)")
    print(f"  pitches/PA  {ppa:.2f}   (real ~3.90)")
    print("\n  K/PA is a CONSEQUENCE here, not the target -- reported to catch a")
    print("  fit that improved the summary while making the matrix worse.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
