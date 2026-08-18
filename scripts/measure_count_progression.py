"""Measure the REAL outcome-by-count matrix, and the sim's, side by side. `#440`.

Joint calibration of the pitch mix and the two-strike conversion could not reach
target: K/PA stuck at 0.256 vs 0.226 and pitches/PA at 3.55 vs 3.90. The
arithmetic located the residual in COUNT PROGRESSION -- the sim's per-pitch
IN_PLAY rate is correct (16.7% vs 17%) while its PA-level in-play share is 4
points low, which can only happen if counts evolve wrongly.

**Do not grid-search this.** Statcast raw pitches carry `balls`, `strikes`,
`description` and `pitch_type` for every pitch thrown, so P(outcome | count) is
a MEASUREMENT, not a parameter to fit. This prints the real matrix against the
sim's so the discrepancy is visible per count rather than inferred from an
aggregate.

Usage:
  py -3 scripts/measure_count_progression.py --games 4 --sims 8
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
for _p in (str(REPO), str(REPO / "vendor" / "mlb_bettingv2")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

RAW = "vendor/mlb_bettingv2/data/raw/statcast/pitches/*/*.csv.gz"
# statcast `description` -> the engine's call vocabulary
DESC = {
    "ball": "BALL", "blocked_ball": "BALL", "pitchout": "BALL",
    "called_strike": "CALLED_STRIKE",
    "swinging_strike": "SWINGING_STRIKE", "swinging_strike_blocked": "SWINGING_STRIKE",
    "missed_bunt": "SWINGING_STRIKE",
    "foul": "FOUL", "foul_tip": "FOUL", "foul_bunt": "FOUL",
    "hit_into_play": "IN_PLAY", "hit_into_play_score": "IN_PLAY",
    "hit_into_play_no_out": "IN_PLAY",
    "hit_by_pitch": "HIT_BY_PITCH",
}
COUNTS = [(b, s) for b in range(4) for s in range(3)]


def real_matrix(max_files: int) -> dict:
    out = defaultdict(Counter)
    files = sorted(glob.glob(RAW))[:max_files]
    for path in files:
        try:
            with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
                rdr = csv.DictReader(fh)
                for row in rdr:
                    try:
                        b, s = int(row["balls"]), int(row["strikes"])
                    except (TypeError, ValueError, KeyError):
                        continue
                    if not (0 <= b <= 3 and 0 <= s <= 2):
                        continue
                    call = DESC.get(str(row.get("description") or "").strip())
                    if call:
                        out[(b, s)][call] += 1
        except Exception:
            continue
    print(f"  real: {len(files)} statcast files, {sum(sum(c.values()) for c in out.values()):,} pitches")
    return out


def sim_matrix(games: int, sims: int) -> dict:
    from sim_engine.data.roster_artifact import read_game_roster_artifact
    from sim_engine.models import GameConfig
    from sim_engine.simulate import simulate_game
    out = defaultdict(Counter)
    paths = sorted(glob.glob(
        "data/mlb_source/source_artifacts/data/daily_pitcher_props/snapshots/*/roster_objs/roster_obj_*.json"))[:games]
    n = 0
    for p in paths:
        try:
            r = read_game_roster_artifact(Path(p))
        except Exception:
            continue
        cfg = GameConfig(rng_seed=11, manager_pitching="v2", pbp="pitch")
        for i in range(sims):
            res = simulate_game(r["away"], r["home"], replace(cfg, rng_seed=11 + i))
            for ev in (res.pbp or []):
                call = ev.get("call") or ev.get("pitch_call")
                if not call:
                    continue
                # the count is NESTED: {"count": {"balls": n, "strikes": n}}.
                # A flat ev.get("balls") returns None and silently yields ZERO
                # rows -- which is how the first run of this script "succeeded"
                # with an empty sim side.
                cnt = ev.get("count") or {}
                b, s = cnt.get("balls"), cnt.get("strikes")
                if not isinstance(b, int) or not isinstance(s, int):
                    continue
                if 0 <= b <= 3 and 0 <= s <= 2:
                    out[(b, s)][str(call).split(".")[-1]] += 1
                    n += 1
    print(f"  sim:  {len(paths)} games x {sims} sims, {n:,} pitches")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--games", type=int, default=4)
    ap.add_argument("--sims", type=int, default=8)
    ap.add_argument("--files", type=int, default=39)
    args = ap.parse_args()

    real = real_matrix(args.files)
    sim = sim_matrix(args.games, args.sims)
    if not real or not sim:
        print("REFUSED: one side is empty")
        return 1

    keys = ("BALL", "CALLED_STRIKE", "SWINGING_STRIKE", "FOUL", "IN_PLAY")
    print(f"\n  {'count':>6s} | " + " ".join(f"{k[:5]:>13s}" for k in keys))
    print("  " + "-" * 76)
    worst = []
    for c in COUNTS:
        r, s = real.get(c), sim.get(c)
        if not r or not s:
            continue
        rt, st = sum(r.values()), sum(s.values())
        if rt < 200 or st < 200:
            continue
        cells, dev = [], 0.0
        for k in keys:
            rp, sp = r[k] / rt, s[k] / st
            d = sp - rp
            dev += abs(d)
            cells.append(f"{rp:5.1%}/{sp:5.1%}{'*' if abs(d) > 0.05 else ' '}")
        worst.append((dev, c))
        print(f"  {c[0]}-{c[1]:<4d} | " + " ".join(f"{x:>13s}" for x in cells))
    print("\n  cells are REAL/SIM; * marks a gap > 5 points")
    worst.sort(reverse=True)
    print("\n  counts with the largest total deviation:")
    for dev, c in worst[:4]:
        print(f"    {c[0]}-{c[1]}  total abs deviation {dev:.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
