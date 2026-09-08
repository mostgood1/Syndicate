"""Is the spreads edge a SIGNAL or a few lucky games?

`bucket_realised_performance.py` put `spreads q4_late` at +14.22pp over 93 games
(+2.93 sigma) and `q2_midearly` at +12.26pp (+2.49). At one bet per game those
are ~13 and ~11 extra wins. A handful of games going the right way would produce
exactly that, and the bucket table cannot tell the two apart.

FOUR TESTS, and they are not interchangeable.

1. **BY DATE.** Games on one day share weather, umpires, and a single roster
   build. If the edge lives on one or two dates it is a day, not an edge.

2. **LEAVE-ONE-DATE-OUT.** The sharper form of (1): recompute the edge with each
   date removed in turn and report the worst case. An edge that survives every
   deletion is not resting on one day.

3. **DOES IT SCALE WITH DISAGREEMENT?** This is the one that can actually
   distinguish signal from luck. A real edge should be LARGER where the model
   disagrees with the market more — that is what "the model knows something"
   means mechanically. Luck has no reason to be monotone in disagreement size.
   Ranked into terciles by |model − market|; a flat or inverted profile is
   evidence AGAINST a real edge even if the pooled number is significant.

4. **CONCENTRATION IS BOUNDED HERE, AND SAYING SO MATTERS.** Each game
   contributes `won − implied`, bounded in roughly ±0.5 because the outcome is
   binary and every bet is one unit. This is NOT a P&L where one position can
   dominate, so "a few games carried it" can only ever mean "a few games' worth
   of coin flips", never "one outlier". The per-game spread is printed to make
   that concrete rather than assumed.

Run:
    python scripts/bucket_edge_concentration.py --market spreads --band q4_late
"""

from __future__ import annotations

import argparse
import math
import pathlib
import statistics
import sys
from collections import defaultdict

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.bucket_realised_performance import (  # noqa: E402
    band_for,
    finals_for,
    ledger_rows,
    resolve,
    secret,
)


def collect(sport: str, days: int, market: str, band: str, spread_sign: float):
    token = secret("ADMIN_TOKEN")
    rows = ledger_rows(sport, days, token)
    dates = {str(r.get("date") or "")[:10] for r in rows if r.get("date")}
    finals = finals_for({d for d in dates if d})
    seen: dict = {}
    out = []
    for r in rows:
        if str(r.get("market") or "").strip().lower() != market:
            continue
        if band_for(r.get("progress_fraction")) != band:
            continue
        if str(r.get("game_state") or "") != "live":
            continue
        mp, model = r.get("market_fair_prob"), r.get("model_home_win_prob")
        pk = str(r.get("game_pk") or "")
        if mp is None or model is None or pk not in finals:
            continue
        won, ok = resolve(r, finals[pk], spread_sign)
        if not ok:
            continue
        stamp = str(r.get("recorded_at") or "")
        prior = seen.get(pk)
        if prior is not None and prior[0] <= stamp:
            continue
        model, mp = float(model), float(mp)
        backs_first = model > mp
        entry = {
            "game": pk, "date": str(r.get("date") or ""),
            "won": won if backs_first else (not won),
            "implied": mp if backs_first else (1.0 - mp),
            "disagree": abs(model - mp),
        }
        if prior is not None:
            out.remove(prior[1])
        seen[pk] = (stamp, entry)
        out.append(entry)
    return out


def edge_of(vals):
    if not vals:
        return float("nan"), float("nan"), 0
    rate = sum(1 for v in vals if v["won"]) / len(vals)
    implied = statistics.mean(v["implied"] for v in vals)
    edge = (rate - implied) * 100
    se = math.sqrt(max(rate * (1 - rate), 1e-9) / len(vals)) * 100
    return edge, se, len(vals)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sport", default="mlb")
    ap.add_argument("--days", type=int, default=10)
    ap.add_argument("--market", default="spreads")
    ap.add_argument("--band", default="q4_late")
    ap.add_argument("--spread-sign", type=float, default=-1.0,
                    help="convention chosen by the calibration gate; -1 for MLB spreads")
    args = ap.parse_args()

    vals = collect(args.sport, args.days, args.market, args.band, args.spread_sign)
    edge, se, n = edge_of(vals)
    if n < 30:
        print(f"UNMEASURED: n={n}")
        return 1
    print(f"\n{args.market} {args.band}: n={n} games   edge {edge:+.2f}pp "
          f"+/-{se:.2f} ({edge/se:+.2f} sigma)")
    wins = sum(1 for v in vals if v["won"])
    print(f"  {wins} wins of {n}; the market implied "
          f"{statistics.mean(v['implied'] for v in vals)*n:.1f} -> "
          f"{wins - statistics.mean(v['implied'] for v in vals)*n:+.1f} extra wins")

    # ---------------------------------------------------------------- test 1
    print(f"\nBY DATE")
    by_date = defaultdict(list)
    for v in vals:
        by_date[v["date"]].append(v)
    for d in sorted(by_date):
        e, s, k = edge_of(by_date[d])
        flag = "" if k >= 8 else "   (thin)"
        print(f"  {d}  n={k:3d}  edge {e:+7.2f}pp{flag}")

    # ---------------------------------------------------------------- test 2
    print(f"\nLEAVE-ONE-DATE-OUT (worst case is what matters)")
    worst = None
    for d in sorted(by_date):
        keep = [v for v in vals if v["date"] != d]
        e, s, k = edge_of(keep)
        if worst is None or e < worst[1]:
            worst = (d, e, s, k)
        print(f"  drop {d}  n={k:3d}  edge {e:+7.2f}pp +/-{s:.2f} ({e/s:+.2f} s)")
    if worst:
        d, e, s, k = worst
        print(f"  WORST: dropping {d} leaves {e:+.2f}pp ({e/s:+.2f} sigma) on n={k}")
        if e / s < 2.0:
            print(f"  ** the edge does NOT survive removing one day at 2 sigma. "
                  f"It is resting on {d}. **")
        else:
            print(f"  the edge survives removing any single day at >=2 sigma.")

    # ---------------------------------------------------------------- test 3
    print(f"\nDOES IT SCALE WITH DISAGREEMENT? (terciles by |model - market|)")
    ranked = sorted(vals, key=lambda v: v["disagree"])
    t = len(ranked) // 3
    for name, chunk in (("low   ", ranked[:t]), ("mid   ", ranked[t:2 * t]),
                        ("high  ", ranked[2 * t:])):
        e, s, k = edge_of(chunk)
        dis = statistics.mean(v["disagree"] for v in chunk) * 100
        print(f"  {name} |disagree| {dis:5.2f}pp  n={k:3d}  edge {e:+7.2f}pp "
              f"+/-{s:.2f} ({e/s:+.2f} sigma)")
    lo_e, _s, _k = edge_of(ranked[:t])
    hi_e, _s2, _k2 = edge_of(ranked[2 * t:])
    print(f"  high minus low: {hi_e - lo_e:+.2f}pp")
    if hi_e > lo_e:
        print("  MONOTONE in the right direction -- the edge is larger where the "
              "model\n  disagrees more, which is what a real signal looks like.")
    else:
        print("  ** NOT monotone. The edge is no larger where the model disagrees "
              "MORE.\n  A model that knows something should profit most where it "
              "differs most;\n  a flat or inverted profile is evidence against a "
              "real edge. **")

    # ---------------------------------------------------------------- test 4
    contrib = [(1.0 if v["won"] else 0.0) - v["implied"] for v in vals]
    print(f"\nPER-GAME CONTRIBUTION (bounded by construction: binary outcome, "
          f"one unit each)")
    print(f"  min {min(contrib):+.3f}  max {max(contrib):+.3f}  "
          f"sd {statistics.pstdev(contrib):.3f}")
    top = sorted(contrib, reverse=True)[:5]
    print(f"  top 5 games contribute {sum(top):+.2f} of a total "
          f"{sum(contrib):+.2f} ({sum(top)/sum(contrib)*100 if sum(contrib) else float('nan'):.0f}%)")
    print("  A P&L can be carried by one position. This cannot: every game is one\n"
          "  unit on a binary outcome, so 'concentrated' here means 'a few coin\n"
          "  flips', never 'one outlier'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
