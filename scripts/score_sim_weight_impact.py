"""Measure what a sim weight does to the board, against the distribution that
caused it to be zeroed in the first place.

**Reproduce the failure before claiming the fix.** `_SCORE_SIM_WEIGHT` went 0.5
-> 0.0 on 2026-08-08 for a measured reason, recorded in
`opportunity_signals.py:326-356`: across all four MLB market families, the sim's
edge was large and the rows were mostly negative-EV.

    family    n     median edge   negative-EV rows
    spreads    48      10.36        40/48
    totals     35      10.80        32/35
    h2h        24      12.49        23/24
    props     193      11.99       191/193
    ALL       300                  286/300

With `ev ~ -5` against `model_edge ~ +12`, a 0.5 weight makes the blended score
POSITIVE and model-dominated -- so the board stops selecting good bets and
starts selecting *rows where an unvalidated model most disagrees with the
market*. This harness replays that distribution and reports, for any
(weight, cap) pair, the three things that actually decide whether a weight is
safe:

  DOMINATION   how many negative-EV rows the sim promotes to a positive score.
               This is the failure. At 0.5 it is most of them.
  SIDE-PICKING can the board tell two sides of one market apart? At weight 0
               it provably cannot -- EV against a proportional de-vig is
               `1/overround - 1`, IDENTICAL for every side -- so the board
               orders by hold and breaks ties arbitrarily.
  REORDERING   how much the sim is allowed to move a row, in EV points. The
               measure of whether it "matters" at all.

    python3 scripts/score_sim_weight_impact.py

**This is a SCREEN, not a validation.** It answers "can this weight repeat the
2026-08-08 failure", which is a question about arithmetic. It does NOT answer
"is the sim right", which needs `settled > 0` and CLV decomposed by component
(`todo.md #507`). A weight that passes here is safe to try, not proven correct.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# The measured production distribution, family by family, from the comment
# block in opportunity_signals.py. `n` and `negative` are counts of REAL rows.
FAMILIES = [
    ("spreads", 48, 10.36, 40),
    ("totals", 35, 10.80, 32),
    ("h2h", 24, 12.49, 23),
    ("props", 193, 11.99, 191),
]

# What a negative-EV row on that board actually looked like. The comment names
# `ev_pct ~ -5` as the case that flipped positive under a 0.5 weight.
TYPICAL_NEGATIVE_EV = -5.0


def sim_contribution(model_edge: float, weight: float, cap: float | None) -> float:
    raw = weight * model_edge
    if cap is None:
        return raw
    return max(-cap, min(cap, raw))


def report(weight: float, cap: float | None, label: str) -> dict:
    promoted = 0
    negatives = 0
    for _family, n, median_edge, negative in FAMILIES:
        negatives += negative
        contribution = sim_contribution(median_edge, weight, cap)
        # A negative-EV row is PROMOTED when the sim carries it above zero.
        if TYPICAL_NEGATIVE_EV + contribution > 0:
            promoted += negative
        del n
    # Side-picking: two sides of one market carry IDENTICAL ev, so the sim term
    # is the entire difference between them. Any non-zero contribution
    # discriminates; zero cannot.
    side_delta = abs(sim_contribution(11.5, weight, cap) - sim_contribution(-11.5, weight, cap))
    max_move = sim_contribution(15.0, weight, cap)  # _MODEL_EDGE_MAX_POINTS
    return {
        "label": label,
        "weight": weight,
        "cap": cap,
        "promoted": promoted,
        "negatives": negatives,
        "side_delta": side_delta,
        "max_move": max_move,
    }


def main() -> int:
    from syndicate.features.shared.opportunity_signals import (
        _MODEL_EDGE_MAX_POINTS_HINT,
        _SCORE_SIM_CAP_PCT,
        _SCORE_SIM_WEIGHT,
    )

    rows = [
        report(0.5, None, "0.5 uncapped (the 2026-08-08 state)"),
        report(0.0, None, "0.0 (today, gated on S6)"),
        report(_SCORE_SIM_WEIGHT, _SCORE_SIM_CAP_PCT, "current constants"),
    ]
    del _MODEL_EDGE_MAX_POINTS_HINT

    print(f"{'configuration':<36} {'promoted':>18} {'side-pick':>10} {'max move':>9}")
    print("-" * 76)
    for row in rows:
        promoted = f"{row['promoted']}/{row['negatives']}"
        side = "YES" if row["side_delta"] > 1e-9 else "no"
        print(
            f"{row['label']:<36} {promoted:>18} {side:>10} {row['max_move']:>8.2f}p"
        )
    print()
    print("promoted  = negative-EV rows the sim lifts to a positive score. THE FAILURE.")
    print("side-pick = can the board separate two sides of one market at all.")
    print("max move  = most the sim may shift a row, in EV points.")
    print()

    current = rows[-1]
    failures = []
    if current["promoted"] > 0:
        failures.append(
            f"promotes {current['promoted']} negative-EV rows -- this is the 2026-08-08 failure"
        )
    if current["side_delta"] <= 1e-9:
        failures.append("cannot separate two sides of a market -- the sim does not matter")
    if failures:
        for failure in failures:
            print(f"FAIL  {failure}")
        return 1
    print("PASS  the sim discriminates and cannot promote a negative-EV row.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
