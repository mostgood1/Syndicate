"""Isolate innings 6-9. Is the LATE part of the full-game model the deficit?

WHERE THIS COMES FROM. On 1,015 games the model's five-inning number sorts
outcomes far better than its nine-inning number sorts theirs (first5 -> first5
+4.26 sigma; full -> full +2.94 sigma), and on the 371 games where the two
disagree by >=3pp the direction `full` leans is WRONG 55.8% of the time
(-2.23 sigma). That is the signature of a nine-inning extrapolation that
SUBTRACTS from a five-inning signal rather than adding to it.

`full` and `first5` are two readouts of one simulation, so their DIFFERENCE is
the model's implicit forecast for innings 6 onward, and it can be scored on its
own:

    predicted_late = full.total_mean - first5.total_mean
    actual_late    = actual_total    - actual_first5

That comparison needs no new model and no new data. If `predicted_late` is
biased or uncorrelated with `actual_late`, the late-inning component is the
thing to fix, and the fix has an obvious direction.

MARGIN MATTERS MORE THAN TOTAL for a moneyline, so the same split is run on the
home-minus-away margin, which is what actually decides the bet.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import statistics
import sys
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.backtest_mlb_first5_skill import (  # noqa: E402
    SEGMENT_INNINGS,
    load_predictions,
    segment_actual,
)


def mean_or_none(block, key):
    try:
        return float(block[key])
    except (TypeError, KeyError, ValueError):
        return None


def corr(xs, ys):
    if len(xs) < 3:
        return float("nan")
    mx, my = statistics.mean(xs), statistics.mean(ys)
    sx, sy = statistics.pstdev(xs), statistics.pstdev(ys)
    if sx == 0 or sy == 0:
        return float("nan")
    return sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / (len(xs) * sx * sy)


def report(label, pred, act):
    n = len(pred)
    if n < 60:
        print(f"  {label:34s} n={n:4d}  UNMEASURED (n<60)")
        return
    bias = statistics.mean(p - a for p, a in zip(pred, act))
    mae = statistics.mean(abs(p - a) for p, a in zip(pred, act))
    se = statistics.pstdev([p - a for p, a in zip(pred, act)]) / math.sqrt(n)
    r = corr(pred, act)
    print(f"  {label:34s} n={n:4d}  bias {bias:+.3f} +/-{se:.3f} "
          f"({bias / se:+.1f}s)  MAE {mae:.3f}  corr {r:+.3f}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.parse_args()

    preds, _ = load_predictions()
    dates = sorted({d for d, _ in preds})

    tot_p5, tot_a5, tot_pl, tot_al = [], [], [], []
    mar_p5, mar_a5, mar_pl, mar_al = [], [], [], []
    late_flip = 0
    late_games = 0

    for date in dates:
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
                if not blocks:
                    continue
                f5b, fub = blocks.get("first5"), blocks.get("full")
                if not f5b or not fub:
                    continue
                innings = [{"away": ((i.get("away") or {}).get("runs")),
                            "home": ((i.get("home") or {}).get("runs"))}
                           for i in (game.get("linescore") or {}).get("innings") or []]
                a5 = segment_actual(innings, SEGMENT_INNINGS["first5"])
                afu = segment_actual(innings, None)
                if a5 is None or afu is None:
                    continue
                p5_away, p5_home = mean_or_none(f5b, "away_runs_mean"), mean_or_none(f5b, "home_runs_mean")
                pf_away, pf_home = mean_or_none(fub, "away_runs_mean"), mean_or_none(fub, "home_runs_mean")
                if None in (p5_away, p5_home, pf_away, pf_home):
                    continue

                tot_p5.append(p5_away + p5_home); tot_a5.append(a5[0] + a5[1])
                tot_pl.append((pf_away + pf_home) - (p5_away + p5_home))
                tot_al.append((afu[0] + afu[1]) - (a5[0] + a5[1]))

                mar_p5.append(p5_home - p5_away); mar_a5.append(a5[1] - a5[0])
                mar_pl.append((pf_home - pf_away) - (p5_home - p5_away))
                mar_al.append((afu[1] - afu[0]) - (a5[1] - a5[0]))

                # How often do innings 6+ REVERSE who is ahead? This is the
                # ceiling on how much the late component can matter at all.
                lead5 = a5[1] - a5[0]
                leadf = afu[1] - afu[0]
                if lead5 != 0 and leadf != 0:
                    late_games += 1
                    if (lead5 > 0) != (leadf > 0):
                        late_flip += 1

    print(f"n={len(tot_p5)} games\n")
    print("TOTAL RUNS")
    report("innings 1-5   pred vs actual", tot_p5, tot_a5)
    report("innings 6+    pred vs actual", tot_pl, tot_al)
    print("\nHOME MARGIN  (what a moneyline actually turns on)")
    report("innings 1-5   pred vs actual", mar_p5, mar_a5)
    report("innings 6+    pred vs actual", mar_pl, mar_al)

    if late_games:
        print(f"\nHOW OFTEN INNINGS 6+ REVERSE THE LEADER: "
              f"{late_flip}/{late_games} = {late_flip / late_games:.4f}")
        print("  That is the share of games where the late component decides the "
              "moneyline.\n  A model with no late signal loses at most this much "
              "sorting power -- and\n  a model with NEGATIVE late signal loses more, "
              "because it moves the wrong way.")

    # The sharpest cut: among games the late innings REVERSED, did the model's
    # late margin forecast lean the right way?
    lean_right = 0
    lean_n = 0
    for pl, al in zip(mar_pl, mar_al):
        if abs(pl) < 0.05:
            continue
        lean_n += 1
        if (pl > 0) == (al > 0):
            lean_right += 1
    if lean_n >= 60:
        rate = lean_right / lean_n
        se = math.sqrt(0.25 / lean_n)
        print(f"\nDOES THE LATE MARGIN FORECAST LEAN THE RIGHT WAY?  "
              f"{lean_right}/{lean_n} = {rate:.4f}  "
              f"({(rate - 0.5) / se:+.2f} sigma vs a coin flip)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
