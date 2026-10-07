"""Phase A of lane `football-sim-player-attribution`: the measured tables the attribution layer reads.

Pre-registered in `.syndicate/findings_2026-10-07_football_player_attribution.md` (buckets, smoothing,
FIT seasons) before this file existed.

  P(pass | down, to-go, score diff, time, yards)  -- for a sim play that GAINED yards, which kind was it
  P(interception | turnover), P(pass | lost fumble)

Source: nflverse pbp, REG season, FIT 2023-24 only. Plays: `play_type` pass/run, not aborted, not a
spike/kneel; for the pass/run table also not a sack and not an incomplete pass (the sim names those
outcomes itself, so they are never ambiguous).

    py -3 scripts/football_attribution_tables.py --seasons 2023,2024
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from syndicate.features.football.sim_engine.smartsim2 import player_attribution as A  # noqa: E402

PBP = Path(r"C:\Users\tempadmin\OneDrive\Coding\Syndicate\data\nfl_source\tracking\nflverse\pbp")
SMOOTH = 20.0
OUT = Path(r"C:\tmp\football_scenarios\attribution")


def _i(x, d=0):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return d


def measure(seasons: List[int]) -> Dict:
    cell: Dict[Tuple, List[int]] = defaultdict(lambda: [0, 0])     # [pass, total]
    pooled: Dict[Tuple, List[int]] = defaultdict(lambda: [0, 0])
    to = {"int": 0, "fumble_pass": 0, "fumble_run": 0}
    # Amendment A2: the REAL yards of completions and runs per (type, down, to-go, sign), non-TD
    ydist: Dict[str, List[int]] = defaultdict(list)
    n_rows = 0
    for season in seasons:
        with (PBP / f"pbp_{season}.csv").open(encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                if r.get("season_type") != "REG" or r.get("play_type") not in ("pass", "run"):
                    continue
                if r.get("aborted_play") == "1" or r.get("qb_kneel") == "1" or r.get("qb_spike") == "1":
                    continue
                down = _i(r.get("down"))
                if not 1 <= down <= 4:
                    continue
                is_pass = r["play_type"] == "pass"
                if r.get("interception") == "1":
                    to["int"] += 1
                    continue
                if r.get("fumble_lost") == "1":
                    to["fumble_pass" if is_pass else "fumble_run"] += 1
                    continue
                if r.get("sack") == "1" or (is_pass and r.get("incomplete_pass") == "1"):
                    continue
                q = _i(r.get("qtr"))
                key = A.pass_rate_key(down=down, distance=_i(r.get("ydstogo"), 10),
                                      score_diff=_i(r.get("score_differential")), quarter=q,
                                      clock=_i(r.get("quarter_seconds_remaining")),
                                      yards=_i(r.get("yards_gained")))
                y = _i(r.get("yards_gained"))
                if r.get("touchdown") != "1":
                    ydist[f"{'comp' if is_pass else 'run'}|{down}|{key[1]}|{'neg' if y < 0 else 'nonneg'}"].append(y)
                cell[key][0] += int(is_pass)
                cell[key][1] += 1
                pooled[key[:2]][0] += int(is_pass)
                pooled[key[:2]][1] += 1
                n_rows += 1
    table = {}
    for key, (p, n) in cell.items():
        pp, pn = pooled[key[:2]]
        prior = pp / pn if pn else 0.5
        table["|".join(map(str, key))] = {"p": round((p + SMOOTH * prior) / (n + SMOOTH), 4), "n": n}
    pooled_out = {"|".join(map(str, k)): {"p": round(p / n, 4), "n": n} for k, (p, n) in pooled.items() if n}
    n_to = sum(to.values())
    n_fum = to["fumble_pass"] + to["fumble_run"]
    quant = {}
    for k, ys in ydist.items():
        ys.sort()
        quant[k] = {"q": [ys[min(len(ys) - 1, int(i * (len(ys) - 1) / 100))] for i in range(101)], "n": len(ys)}
    return {"seasons": seasons, "n_rows": n_rows, "yards_quantiles": quant, "pass_rate": table, "pass_rate_pooled": pooled_out,
            "p_int_given_turnover": round(to["int"] / n_to, 4), "p_pass_given_fumble": round(to["fumble_pass"] / n_fum, 4),
            "turnover_counts": to, "smoothing": SMOOTH}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seasons", required=True)
    args = ap.parse_args()
    seasons = [int(s) for s in args.seasons.split(",")]
    if 2025 in seasons:
        raise SystemExit("2025 is the held-out props season; tables are FIT-only")
    t = measure(seasons)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"attribution_tables_{'-'.join(map(str, seasons))}.json"
    path.write_text(json.dumps(t, indent=1), encoding="utf-8")
    print(f"{t['n_rows']} gaining plays, {len(t['pass_rate'])} cells -> {path}")
    print(f"P(INT | turnover) {t['p_int_given_turnover']}  P(pass | lost fumble) {t['p_pass_given_fumble']}  {t['turnover_counts']}")
    for k, v in sorted(t["pass_rate_pooled"].items()):
        print(f"  down|togo {k:6} P(pass) {v['p']:.3f}  n={v['n']}")


if __name__ == "__main__":
    main()
