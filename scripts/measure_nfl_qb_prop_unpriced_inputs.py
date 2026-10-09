"""Do WIND or the QB's PRACTICE status carry information beyond the NFL QB prop line?

Lane `nfl-qb-prop-unpriced-inputs`, pre-registered in `.syndicate/lanes.md` (c6269fc6) before any number.
Per input x and market: y ~ a + b1*logit(p_book) + b2*x, fitted on real 2023 OddsAPI quotes (kickoff -10 min,
two-sided, de-vigged per book), applied unchanged to real 2024 quotes. All two-sided rows (an input the line misses
applies whether or not the model prices the row). Official grading (rows from
`diagnose_nfl_passing_yards_prop.py build --seasons 2023,2024`). 2025 not read.

    x = wind   : nflverse schedules `wind` (mph) for outdoor/open-roof games; dome / closed / missing = 0
    x = limited: 1 when the QB's nflverse injury-report row that week has practice_status Limited or
                 Did Not Participate, else 0

    py -3 scripts/measure_nfl_qb_prop_unpriced_inputs.py
"""
from __future__ import annotations

import csv
import json
import math
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts import diagnose_nfl_passing_yards_prop as D  # noqa: E402
from scripts.measure_nfl_qb_prop_info_beyond_line import _ll, _logit, fit_logistic  # noqa: E402

ROWS = D.OUT / "rows_2023-2024.jsonl"
NFLVERSE = D.ROOT / "tracking" / "nflverse"
STATS = ("passing_yards", "passing_attempts")
LIMITED = {"Limited Participation in Practice", "Did Not Participate In Practice"}


def wind_by_game() -> dict[str, float]:
    out = {}
    with (NFLVERSE / "schedules_games.csv").open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if r.get("season") not in ("2023", "2024"):
                continue
            indoor = r.get("roof") in ("dome", "closed")
            out[r["game_id"]] = 0.0 if indoor or not r.get("wind") else float(r["wind"])
    return out


def limited_by_player_week() -> set[tuple[int, int, str]]:
    out = set()
    for season in (2023, 2024):
        with (NFLVERSE / "injuries" / f"injuries_{season}.csv").open(encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                if r.get("game_type") == "REG" and (r.get("practice_status") or "").strip() in LIMITED:
                    out.add((season, int(r["week"]), r["gsis_id"]))
    return out


def _boot_ci(vals_by_game: dict, rng: random.Random, n: int = 1000) -> tuple[float, float]:
    gs = list(vals_by_game)
    bs = []
    for _ in range(n):
        s = [x for g in (rng.choice(gs) for _ in gs) for x in vals_by_game[g]]
        bs.append(statistics.fmean(s))
    bs.sort()
    return bs[int(0.025 * n)], bs[int(0.975 * n) - 1]


def main() -> int:
    from scripts.football_scenario_rates import idle_self
    idle_self()  # the production fleet shares this machine
    wind = wind_by_game()
    limited = limited_by_player_week()
    rows_all = [r for r in map(json.loads, ROWS.open(encoding="utf-8")) if r["actual"] != r["line"]]
    report: dict = {"rows_file": str(ROWS)}
    rng = random.Random(7)
    for stat in STATS:
        rows = [r for r in rows_all if r["stat"] == stat]
        for r in rows:
            r["x_wind"] = wind.get(r["gid"], 0.0)
            r["x_limited"] = 1.0 if (r["season"], r["week"], r["pid"]) in limited else 0.0
            r["lb"] = _logit(r["p_book"])
        for name in ("x_wind", "x_limited"):
            fit = [r for r in rows if r["season"] == 2023]
            held = [r for r in rows if r["season"] == 2024]
            X = [(r["lb"], r[name]) for r in fit]
            ys = [r["y"] for r in fit]
            a, b1, b2 = fit_logistic(X, ys)
            by_g = defaultdict(list)
            for i, r in enumerate(fit):
                by_g[r["gid"]].append(i)
            gs = list(by_g)
            boot = []
            for _ in range(300):
                idx = [i for g in (rng.choice(gs) for _ in gs) for i in by_g[g]]
                boot.append(fit_logistic([X[i] for i in idx], [ys[i] for i in idx], iters=25)[2])
            boot.sort()
            comb = lambda r: 1 / (1 + math.exp(-max(min(a + b1 * r["lb"] + b2 * r[name], 30), -30)))  # noqa: E731
            d_by = defaultdict(list)
            for r in held:
                d_by[r["gid"]].append(_ll(comb(r), r["y"]) - _ll(r["p_book"], r["y"]))
            lo, hi = _boot_ci(d_by, rng)
            S = {"fit_2023": {"n": len(fit), "games": len(gs), "n_x_nonzero": sum(1 for r in fit if r[name]),
                              "b1_book": round(b1, 4), "b2": round(b2, 4), "b2_ci95": [round(boot[7], 4), round(boot[292], 4)]},
                 "held_2024": {"n": len(held), "games": len(d_by), "n_x_nonzero": sum(1 for r in held if r[name]),
                               "LL_book": round(statistics.fmean(_ll(r["p_book"], r["y"]) for r in held), 4),
                               "LL_combined": round(statistics.fmean(_ll(comb(r), r["y"]) for r in held), 4),
                               "combined_minus_book": round(statistics.fmean(x for v in d_by.values() for x in v), 4),
                               "ci95": [round(lo, 4), round(hi, 4)]}}
            sig = S["fit_2023"]["b2_ci95"][0] > 0 or S["fit_2023"]["b2_ci95"][1] < 0
            S["verdict"] = ("USABLE INFORMATION BEYOND THE LINE" if sig and hi < 0 else
                            "b2 != 0 IN FIT, NOT USABLE OUT OF SAMPLE" if sig else "NO INFORMATION BEYOND THE LINE")
            report[f"{stat}:{name}"] = S
            print(stat, name, json.dumps(S), flush=True)
    out = D.OUT / "unpriced_inputs_report.json"
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
