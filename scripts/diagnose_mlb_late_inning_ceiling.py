"""Is the innings-6+ margin model FIXABLE, or is it already near its ceiling?

`findings_2026-09-07_full_game_discrimination.md` flagged the late-inning margin
forecast as the weakest link (corr +0.059 against +0.156 early) and the obvious
thing to fix. This asks whether there is anything there to fix, and the answer
turned out to be no -- so it also finds where the real defect is instead.

FOUR TESTS, each able to come back either way:

  1. BIAS      -- is the late mean wrong? (if so, correct it)
  2. DISPERSION-- does it overstate its own spread? (if so, shrink it)
  3. STABILITY -- does its skill come and go? (if so, find the regime)
  4. CEILING   -- how much late-inning signal EXISTS to be captured?

Test 4 is the one that decides the others' worth. The true team-level late-margin
spread is recovered by subtracting sampling noise from the observed spread of
per-team means; against the per-game noise that sets a maximum achievable
correlation, which is then compared to what the model actually gets.

Run:  python scripts/diagnose_mlb_late_inning_ceiling.py
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import statistics
import sys
import urllib.request
from collections import defaultdict

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.backtest_mlb_first5_skill import load_predictions, segment_actual  # noqa: E402


def corr(xs, ys):
    if len(xs) < 3:
        return float("nan")
    mx, my = statistics.mean(xs), statistics.mean(ys)
    sx, sy = statistics.pstdev(xs), statistics.pstdev(ys)
    if sx == 0 or sy == 0:
        return float("nan")
    return sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / (len(xs) * sx * sy)


def collect():
    preds, _ = load_predictions()
    out = []
    for date in sorted({d for d, _ in preds}):
        url = (f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date}"
               f"&hydrate=linescore")
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                doc = json.load(resp)
        except Exception:
            continue
        for day in doc.get("dates") or []:
            for game in day.get("games") or []:
                if str(((game.get("status") or {}).get("abstractGameState") or "")).lower() != "final":
                    continue
                blocks = preds.get((date, int(game.get("gamePk"))))
                if not blocks or not blocks.get("first5") or not blocks.get("full"):
                    continue
                innings = [{"away": ((i.get("away") or {}).get("runs")),
                            "home": ((i.get("home") or {}).get("runs"))}
                           for i in (game.get("linescore") or {}).get("innings") or []]
                a5 = segment_actual(innings, 5)
                af = segment_actual(innings, None)
                if a5 is None or af is None:
                    continue
                f5, fu = blocks["first5"], blocks["full"]
                try:
                    m5 = float(f5["home_runs_mean"]) - float(f5["away_runs_mean"])
                    mf = float(fu["home_runs_mean"]) - float(fu["away_runs_mean"])
                except (KeyError, TypeError, ValueError):
                    continue
                teams = game.get("teams") or {}
                out.append({
                    "date": date, "month": date[:7],
                    "home": ((teams.get("home") or {}).get("team") or {}).get("name"),
                    "away": ((teams.get("away") or {}).get("team") or {}).get("name"),
                    "pe": m5, "pl": mf - m5, "pf": mf,
                    "ae": a5[1] - a5[0], "al": (af[1] - af[0]) - (a5[1] - a5[0]),
                    "af": af[1] - af[0],
                })
    return out


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    rows = collect()
    n = len(rows)
    print(f"n={n} games, {len({r['date'] for r in rows})} dates\n")
    if n < 200:
        print("UNMEASURED: too few games.")
        return 1

    print("TEST 1 -- BIAS")
    for lbl, p, a in (("innings 1-5", "pe", "ae"), ("innings 6+ ", "pl", "al"),
                      ("full game  ", "pf", "af")):
        d = [r[p] - r[a] for r in rows]
        se = statistics.pstdev(d) / math.sqrt(n)
        print(f"  {lbl}  predicted {statistics.mean(r[p] for r in rows):+.3f}  "
              f"actual {statistics.mean(r[a] for r in rows):+.3f}  "
              f"bias {statistics.mean(d):+.3f} ({statistics.mean(d)/se:+.1f}s)")
    print("  -> a bias concentrated in ONE half is a calibration error there, "
          "not everywhere.\n")

    print("TEST 2 -- DISPERSION: is the stated spread earned? (fit first half, apply to second)")
    dates = sorted({r["date"] for r in rows})
    cut = dates[len(dates) // 2]
    tr = [r for r in rows if r["date"] < cut]
    te = [r for r in rows if r["date"] >= cut]

    def slope(src, p, a):
        xs = [r[p] for r in src]
        ys = [r[a] for r in src]
        sx = statistics.pstdev(xs)
        return corr(xs, ys) * statistics.pstdev(ys) / sx if sx else 0.0

    be, bl = slope(tr, "pe", "ae"), slope(tr, "pl", "al")
    print(f"  early slope {be:+.4f}   late slope {bl:+.4f}   "
          f"(1.0 = take it at face value)")
    mxe = statistics.mean(r["pe"] for r in tr); mye = statistics.mean(r["ae"] for r in tr)
    mxl = statistics.mean(r["pl"] for r in tr); myl = statistics.mean(r["al"] for r in tr)
    act = [r["af"] for r in te]
    print(f"  TEST-half corr with actual full margin:")
    print(f"    as published           {corr([r['pf'] for r in te], act):+.4f}")
    print(f"    shrink LATE only       "
          f"{corr([r['pe'] + (myl + bl*(r['pl']-mxl)) for r in te], act):+.4f}")
    print(f"    shrink BOTH            "
          f"{corr([(mye+be*(r['pe']-mxe)) + (myl+bl*(r['pl']-mxl)) for r in te], act):+.4f}")
    print(f"    se(corr) ~ {1/math.sqrt(len(te)):.4f}\n")

    print("TEST 3 -- STABILITY by month")
    by = defaultdict(list)
    for r in rows:
        by[r["month"]].append(r)
    for m in sorted(by):
        v = by[m]
        if len(v) < 40:
            print(f"  {m}  n={len(v):4d}  UNMEASURED (n<40)")
            continue
        print(f"  {m}  n={len(v):4d}  early {corr([r['pe'] for r in v], [r['ae'] for r in v]):+.4f}"
              f"   late {corr([r['pl'] for r in v], [r['al'] for r in v]):+.4f}"
              f"   se~{1/math.sqrt(len(v)):.4f}")
    print()

    print("TEST 4 -- CEILING: how much late signal EXISTS?")
    pred, act_t = defaultdict(list), defaultdict(list)
    for r in rows:
        pred[r["home"]].append(r["pl"]);  act_t[r["home"]].append(r["al"])
        pred[r["away"]].append(-r["pl"]); act_t[r["away"]].append(-r["al"])
    teams = [t for t in pred if t and len(pred[t]) >= 30]
    px = [statistics.mean(pred[t]) for t in teams]
    ax = [statistics.mean(act_t[t]) for t in teams]
    obs = statistics.pstdev(ax)
    within = statistics.mean(statistics.pvariance(act_t[t]) for t in teams)
    per = statistics.mean(len(act_t[t]) for t in teams)
    noise = math.sqrt(within / per)
    true_sd = math.sqrt(max(obs ** 2 - noise ** 2, 0.0))
    game_sd = statistics.pstdev([r["al"] for r in rows])
    print(f"  teams={len(teams)}  ~{per:.0f} games each")
    print(f"  corr(model team effect, actual team effect) = {corr(px, ax):+.4f}"
          f"   se~{1/math.sqrt(len(teams)):.3f}")
    print(f"  model team spread   {statistics.pstdev(px):.4f}")
    print(f"  observed team spread {obs:.4f}  of which sampling noise {noise:.4f}")
    print(f"  -> TRUE team effect  {true_sd:.4f} runs/game; model expresses "
          f"{statistics.pstdev(px)/true_sd*100:.0f}% of it" if true_sd > 0 else "")
    if true_sd > 0:
        ceiling = true_sd / game_sd
        got = corr([r["pl"] for r in rows], [r["al"] for r in rows])
        print(f"  per-game late margin sd {game_sd:.3f}")
        print(f"  CEILING from team quality alone ~ {ceiling:.4f};  "
              f"model achieves {got:+.4f}  ({got/ceiling*100:.0f}% of it)")
        print("\n  A model already near the ceiling is not the thing to fix.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
