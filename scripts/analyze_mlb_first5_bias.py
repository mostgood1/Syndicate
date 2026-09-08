"""Is first5's error a systematic BIAS (correctable) or absent signal (not)?

The skill backtest showed `first5` beating climatology by only +0.0147 -- but
every calibration bin had ACTUAL above PREDICTED, which is the signature of a
shift rather than of noise. Those are very different findings: a model with no
discrimination is not worth betting, while a model that discriminates and is
merely mis-centred is worth recalibrating.

FITTED OUT OF SAMPLE, because a shift fitted on the same games it is scored on
would manufacture the improvement it claims to measure. Dates are split in
half chronologically -- the earlier half fits the shift, the later half scores
it -- which is also the direction a deployed model would face.
"""

from __future__ import annotations

import argparse
import math
import pathlib
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


def logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def brier(pairs) -> float:
    return sum((p - h) ** 2 for p, h in pairs) / len(pairs)


def skill(pairs) -> float:
    """Against the climatology of the SAME set -- conservative, in-sample base."""
    rate = sum(h for _, h in pairs) / len(pairs)
    base = sum((rate - h) ** 2 for _, h in pairs) / len(pairs)
    return 1.0 - brier(pairs) / base if base > 0 else float("nan")


def collect(segment: str):
    preds, _ = load_predictions()
    rows = []
    for date in sorted({d for d, _ in preds}):
        lines = linescores_for_date(date)
        if not lines:
            continue
        for (d, pk), blocks in preds.items():
            if d != date:
                continue
            game = lines.get(str(pk))
            if game is None or game["state"] != "final":
                continue
            block = blocks.get(segment)
            if not block:
                continue
            actual = segment_actual(game["innings"], SEGMENT_INNINGS[segment])
            if actual is None:
                continue
            away, home = actual
            if home == away:
                continue                      # decisive games only: the 2-way frame
            ph = float(block.get("home_win_prob") or 0.0)
            pa = float(block.get("away_win_prob") or 0.0)
            if ph + pa <= 0:
                continue
            rows.append((date, ph / (ph + pa), 1 if home > away else 0))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--segment", default="first5")
    args = ap.parse_args()

    rows = collect(args.segment)
    dates = sorted({d for d, _, _ in rows})
    cut = dates[len(dates) // 2]
    fit = [(p, h) for d, p, h in rows if d < cut]
    test = [(p, h) for d, p, h in rows if d >= cut]
    print(f"segment={args.segment}  n={len(rows)}  dates={len(dates)}  "
          f"{dates[0]}..{dates[-1]}")
    print(f"  FIT  {dates[0]}..<{cut}  n={len(fit)}")
    print(f"  TEST {cut}..{dates[-1]}  n={len(test)}")
    if not fit or not test:
        print("UNMEASURED: not enough dates to split")
        return 1

    fit_pred = sum(p for p, _ in fit) / len(fit)
    fit_actual = sum(h for _, h in fit) / len(fit)
    shift = logit(fit_actual) - logit(fit_pred)
    print(f"\nFIT HALF   mean predicted {fit_pred:.4f}  actual {fit_actual:.4f}  "
          f"-> logit shift {shift:+.4f}")

    test_pred = sum(p for p, _ in test) / len(test)
    test_actual = sum(h for _, h in test) / len(test)
    print(f"TEST HALF  mean predicted {test_pred:.4f}  actual {test_actual:.4f}  "
          f"(bias {test_actual - test_pred:+.4f})")

    raw = skill(test)
    shifted = [(sigmoid(logit(p) + shift), h) for p, h in test]
    adj = skill(shifted)
    print(f"\nTEST-HALF SKILL")
    print(f"  as published      Brier {brier(test):.5f}   skill {raw:+.4f}")
    print(f"  + fitted shift    Brier {brier(shifted):.5f}   skill {adj:+.4f}")
    print(f"  delta                                        {adj - raw:+.4f}")

    # Does it DISCRIMINATE at all? Rank correlation is the question a shift
    # cannot fix and a bias correction cannot fake.
    ranked = sorted(test, key=lambda t: t[0])
    n = len(ranked)
    lo = ranked[: n // 3]
    hi = ranked[-(n // 3):]
    lo_rate = sum(h for _, h in lo) / len(lo)
    hi_rate = sum(h for _, h in hi) / len(hi)
    print(f"\nDISCRIMINATION (test half, terciles by predicted probability)")
    print(f"  bottom third  n={len(lo):4d}  pred {sum(p for p,_ in lo)/len(lo):.3f}  "
          f"actual {lo_rate:.3f}")
    print(f"  top third     n={len(hi):4d}  pred {sum(p for p,_ in hi)/len(hi):.3f}  "
          f"actual {hi_rate:.3f}")
    print(f"  separation    {hi_rate - lo_rate:+.4f}"
          f"   <- a shift cannot create this; only real signal can")
    se = math.sqrt(lo_rate * (1 - lo_rate) / len(lo) + hi_rate * (1 - hi_rate) / len(hi))
    print(f"  se {se:.4f}  ->  {abs(hi_rate - lo_rate) / se:.2f} sigma"
          if se > 0 else "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
