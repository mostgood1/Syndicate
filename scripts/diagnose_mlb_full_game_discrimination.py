"""Why does the FULL-GAME model not discriminate, when first5 does?

THE FINDING THIS CHASES, measured 2026-09-07 out of sample: the pregame first5
number separates its top and bottom terciles by +0.2199 (3.82 sigma, n=423)
while the FULL-GAME number -- the one the board actually prices and bets --
separates by +0.0479 (0.88 sigma, n=501). That is the mature path reading as
noise on 501 games.

FOUR CANDIDATE EXPLANATIONS, and each gets a test that can come back either way.

1. COMPRESSION. If `full` emits probabilities packed near 0.50, terciles differ
   by little and low separation is arithmetic rather than a modelling failure.
   Tested by comparing the SPREAD of predictions, not just the outcomes.

2. NO SIGNAL ANYWHERE IN THE MARKET. Full-game MLB moneyline may simply be hard.
   The discriminating test is whether the MARKET separates on the same games: if
   the book's own price also fails to sort them, 0.88 sigma is the market's
   difficulty and not our deficit. This is the diagnostic that decides whether
   anything here is fixable.

3. THE INFORMATION IS THERE BUT DILUTED. If the first5 probability predicts the
   FULL-GAME outcome BETTER than the full-game probability does, then the engine
   knows something over five innings and loses it over nine -- which is a
   modelling fault with an obvious direction, and immediately actionable.

4. `full` IS JUST A NOISIER `first5`. Correlation between the two, and whether
   `full` adds anything once `first5` is known.

Run:  python scripts/diagnose_mlb_full_game_discrimination.py
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import pathlib
import re
import statistics
import sys
from collections import defaultdict

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.backtest_mlb_first5_skill import (  # noqa: E402
    SEGMENT_INNINGS,
    linescores_for_date,
    load_predictions,
    segment_actual,
)
from scripts.backtest_mlb_first5_vs_market import devig_home  # noqa: E402

MARKET_GLOB = str(REPO / "data" / "mlb_source" / "**" / "market" / "oddsapi" / "**"
                  / "oddsapi_game_lines_*.json")
DATE_RE = re.compile(r"(\d{4})_(\d{2})_(\d{2})")


def two_way(block) -> float | None:
    if not block:
        return None
    ph = float(block.get("home_win_prob") or 0.0)
    pa = float(block.get("away_win_prob") or 0.0)
    return ph / (ph + pa) if ph + pa > 0 else None


def separation(pairs, label, note=""):
    """Top-vs-bottom tercile realised rate, with its sigma. The one statistic a
    calibration shift cannot fake."""
    if len(pairs) < 60:
        print(f"  {label:26s} n={len(pairs):4d}  UNMEASURED (n<60)")
        return None
    ranked = sorted(pairs, key=lambda t: t[0])
    k = len(ranked) // 3
    lo, hi = ranked[:k], ranked[-k:]
    lr = sum(h for _, h in lo) / len(lo)
    hr = sum(h for _, h in hi) / len(hi)
    se = math.sqrt(lr * (1 - lr) / len(lo) + hr * (1 - hr) / len(hi))
    sig = (hr - lr) / se if se > 0 else float("nan")
    print(f"  {label:26s} n={len(pairs):4d}  bottom {lr:.3f}  top {hr:.3f}  "
          f"sep {hr - lr:+.4f}  {sig:+.2f} sigma{note}")
    return hr - lr, sig


def brier(pairs):
    return sum((p - h) ** 2 for p, h in pairs) / len(pairs)


def load_market_full() -> dict:
    """(date, home, away) -> de-vigged P(home) for the FULL-GAME h2h, median of books."""
    per_game = defaultdict(list)
    for path in glob.glob(MARKET_GLOB, recursive=True):
        m = DATE_RE.search(pathlib.Path(path).name)
        if not m:
            continue
        date = "-".join(m.groups())
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except Exception:
            continue
        for game in doc.get("games") or []:
            markets = game.get("markets") or {}
            h2h = (markets.get("h2h")
                   or ((markets.get("segments") or {}).get("full") or {}).get("h2h") or {})
            prob, _ = devig_home(h2h)
            if prob is None:
                continue
            key = (date, str(game.get("home_team") or "").strip().lower(),
                   str(game.get("away_team") or "").strip().lower())
            per_game[key].append(prob)
    return {k: statistics.median(v) for k, v in per_game.items()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.parse_args()

    preds, _ = load_predictions()
    dates = sorted({d for d, _ in preds})
    print(f"MODEL  games={len(preds)}  dates={len(dates)}  {dates[0]}..{dates[-1]}")

    market = load_market_full()
    mkt_dates = sorted({d for d, _, _ in market})
    print(f"MARKET games={len(market)}  dates={len(mkt_dates)}"
          + (f"  {mkt_dates[0]}..{mkt_dates[-1]}" if mkt_dates else ""))

    import urllib.request
    rows = []
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
                pk = int(game.get("gamePk"))
                blocks = preds.get((date, pk))
                if not blocks:
                    continue
                innings = [{"away": ((i.get("away") or {}).get("runs")),
                            "home": ((i.get("home") or {}).get("runs"))}
                           for i in (game.get("linescore") or {}).get("innings") or []]
                full_actual = segment_actual(innings, None)
                f5_actual = segment_actual(innings, SEGMENT_INNINGS["first5"])
                if full_actual is None or full_actual[0] == full_actual[1]:
                    continue
                teams = game.get("teams") or {}
                home_name = str(((teams.get("home") or {}).get("team") or {}).get("name") or "").strip().lower()
                away_name = str(((teams.get("away") or {}).get("team") or {}).get("name") or "").strip().lower()
                rows.append({
                    "date": date,
                    "p_full": two_way(blocks.get("full")),
                    "p_first5": two_way(blocks.get("first5")),
                    "home_won": 1 if full_actual[1] > full_actual[0] else 0,
                    "f5_home_won": (None if f5_actual is None or f5_actual[0] == f5_actual[1]
                                    else (1 if f5_actual[1] > f5_actual[0] else 0)),
                    "market": market.get((date, home_name, away_name)),
                })
    rows = [r for r in rows if r["p_full"] is not None and r["p_first5"] is not None]
    print(f"SCORED n={len(rows)}  dates={len(set(r['date'] for r in rows))}\n")

    # ---------------------------------------------------------------- test 1
    print("TEST 1 -- COMPRESSION: is the spread of PREDICTIONS the problem?")
    for key, label in (("p_full", "full"), ("p_first5", "first5")):
        vals = [r[key] for r in rows]
        print(f"  {label:8s} mean {statistics.mean(vals):.4f}  sd {statistics.pstdev(vals):.4f}  "
              f"p10 {sorted(vals)[len(vals)//10]:.3f}  p90 {sorted(vals)[9*len(vals)//10]:.3f}")
    print("  -> similar sd means compression is NOT the explanation.\n")

    # ---------------------------------------------------------------- test 2
    print("TEST 2 -- DOES THE MARKET SEPARATE THE SAME GAMES? (the diagnostic)")
    joined = [r for r in rows if r["market"] is not None]
    print(f"  market-joined n={len(joined)}  "
          f"dates={len(set(r['date'] for r in joined))}")
    if len(joined) >= 60:
        separation([(r["market"], r["home_won"]) for r in joined], "MARKET -> full outcome")
        separation([(r["p_full"], r["home_won"]) for r in joined], "model full -> full outcome")
        separation([(r["p_first5"], r["home_won"]) for r in joined], "model first5 -> full outcome")
        print(f"  Brier  market {brier([(r['market'], r['home_won']) for r in joined]):.5f}"
              f"   model_full {brier([(r['p_full'], r['home_won']) for r in joined]):.5f}")
    else:
        print("  UNMEASURED (n<60)")
    print()

    # ---------------------------------------------------------------- test 3
    print("TEST 3 -- IS THE INFORMATION THERE BUT DILUTED?  (full sample)")
    separation([(r["p_full"], r["home_won"]) for r in rows], "full   -> FULL outcome")
    separation([(r["p_first5"], r["home_won"]) for r in rows], "first5 -> FULL outcome",
               "   <- if this beats the line above, the engine")
    print("                                                        loses over 9 innings what it "
          "knows over 5")
    f5 = [(r["p_first5"], r["f5_home_won"]) for r in rows if r["f5_home_won"] is not None]
    separation(f5, "first5 -> first5 outcome")
    fullf5 = [(r["p_full"], r["f5_home_won"]) for r in rows if r["f5_home_won"] is not None]
    separation(fullf5, "full   -> first5 outcome")
    print()

    print("  Brier on the FULL outcome, same games:")
    print(f"    from p_full   {brier([(r['p_full'], r['home_won']) for r in rows]):.5f}")
    print(f"    from p_first5 {brier([(r['p_first5'], r['home_won']) for r in rows]):.5f}")
    print()

    # ---------------------------------------------------------------- test 4
    print("TEST 4 -- IS `full` JUST A NOISIER `first5`?")
    xs = [r["p_full"] for r in rows]
    ys = [r["p_first5"] for r in rows]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / len(xs)
    corr = cov / (statistics.pstdev(xs) * statistics.pstdev(ys))
    print(f"  corr(p_full, p_first5) = {corr:.4f}")
    # Where they DISAGREE, which one is right?
    dis = [r for r in rows if abs(r["p_full"] - r["p_first5"]) >= 0.03]
    print(f"  games where they differ by >=3pp: n={len(dis)}")
    if len(dis) >= 60:
        full_right = sum(1 for r in dis
                         if (r["p_full"] > r["p_first5"]) == (r["home_won"] == 1))
        print(f"    the side `full` leans toward wins {full_right}/{len(dis)} = "
              f"{full_right / len(dis):.4f}")
        se = math.sqrt(0.25 / len(dis))
        print(f"    vs 0.5000 coin flip -> {(full_right / len(dis) - 0.5) / se:+.2f} sigma"
              "   (below 0.5 means first5's lean was better)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
