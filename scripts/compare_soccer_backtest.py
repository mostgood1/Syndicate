#!/usr/bin/env python3
"""Compare a soccer backtest run against the 2026-08-15 baseline, league by league.

Reads the four-step procedure in lane `soccer-model-dispersion` so it does not have
to be re-derived at 1am:

  1. `matches_scored` must EQUAL the baseline per league. The scored set is gated on
     model success (`backtest_soccer_h2h_calibration.py:228-241` -- a match is only
     appended if the MODEL produced a parseable probability), so a differing count
     means the two runs are on DIFFERENT SETS and the Brier comparison is VOID, not
     merely noisy. Checked first, and a mismatch suppresses the verdict.
  2. Only then is `market_brier` a control. It is model-independent PER MATCH, so
     with an identical set it must be identical. Equal counts + moved market Brier
     = something is wrong.
  3. Then `model_brier` vs baseline, and the sign test across leagues.
  4. Then `model_home_prob_stdev` -- the under-dispersion metric.

USAGE
    python scripts/compare_soccer_backtest.py                       # auto-discovers
    python scripts/compare_soccer_backtest.py --run <file-or-dir>
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BT = REPO / "reports/soccer_backtest"
BASELINE = BT / "h2h_calibration_2026-08-15_limit120_n1112.json"


def load_rows(target: Path) -> dict[str, dict]:
    """Accept a single multi-league JSON or a directory of per-league JSONs."""
    files = sorted(target.glob("*.json")) if target.is_dir() else [target]
    rows: dict[str, dict] = {}
    for f in files:
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"  ! unreadable {f.name}: {type(exc).__name__}")
            continue
        for row in (payload if isinstance(payload, list) else [payload]):
            if isinstance(row, dict) and row.get("league"):
                rows[row["league"]] = row
    return rows


def sign_test_p(worse: int, better: int) -> float:
    """Exact two-sided binomial p at q=0.5, matching the baseline's own method."""
    n = worse + better
    if n == 0:
        return float("nan")
    k = min(worse, better)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, default=BT / "parallel")
    ap.add_argument("--baseline", type=Path, default=BASELINE)
    args = ap.parse_args()

    base = load_rows(args.baseline)
    run = load_rows(args.run)
    if not run:
        print(f"no result rows under {args.run} -- still running?")
        return 2

    print(f"baseline : {args.baseline.name}  ({len(base)} leagues)")
    print(f"run      : {args.run}  ({len(run)} leagues)\n")

    # ---- step 1+2: the control -------------------------------------------------
    print("STEP 1-2  CONTROL: matches_scored must match, then market_brier")
    void: list[str] = []
    for lg in sorted(run):
        b, r = base.get(lg), run[lg]
        if b is None:
            print(f"  {lg:20s} no baseline row -- cannot compare")
            void.append(lg)
            continue
        nb, nr = b.get("matches_scored"), r.get("matches_scored")
        mb, mr = b.get("market_brier"), r.get("market_brier")
        if nb != nr:
            print(f"  {lg:20s} VOID  matches_scored {nb} -> {nr}  (different sets)")
            void.append(lg)
        elif mb != mr:
            print(f"  {lg:20s} SUSPECT  n={nr} ok but market_brier {mb} -> {mr}")
            void.append(lg)
        else:
            print(f"  {lg:20s} ok    n={nr}  market_brier {mr} unchanged")

    comparable = [lg for lg in sorted(run) if lg not in void]
    print(f"\n  comparable leagues: {len(comparable)} of {len(run)}")
    if not comparable:
        print("\n  NO VALID COMPARISON. Stop here -- do not read the model numbers.")
        return 1

    # ---- step 3: model Brier ---------------------------------------------------
    print("\nSTEP 3  MODEL BRIER  (lower is better; gap = model - market)")
    print(f"  {'league':20s} {'base gap':>9s} {'new gap':>9s} {'delta':>8s}  verdict")
    worse = better = 0
    deltas = []
    for lg in comparable:
        b, r = base[lg], run[lg]
        gb = b.get("brier_gap_model_minus_market")
        gr = r.get("brier_gap_model_minus_market")
        if gb is None or gr is None:
            continue
        d = round(gr - gb, 4)
        deltas.append(d)
        beat = gr <= 0
        # A TIE IS A TIE. Testing only `d < 0` labelled `gr == gb` as "regressed",
        # which the self-test against the baseline exposed: comparing the baseline
        # to ITSELF printed nine regressions and a mean delta of +0.0000. Harmless
        # arithmetic, actively misleading label -- and "regressed" is exactly the
        # word someone would act on.
        if gr > gb:
            worse += 1
            label = "regressed"
        elif gr < gb:
            better += 1
            label = "improved"
        else:
            label = "unchanged"
        print(f"  {lg:20s} {gb:+9.4f} {gr:+9.4f} {d:+8.4f}  "
              f"{'BEATS MARKET' if beat else label}")

    beats = [lg for lg in comparable
             if (run[lg].get("brier_gap_model_minus_market") or 1) <= 0]
    print(f"\n  improved vs baseline : {better} / {len(comparable)}")
    print(f"  regressed            : {worse} / {len(comparable)}")
    print(f"  mean gap delta       : {sum(deltas)/len(deltas):+.4f}" if deltas else "")
    print(f"  leagues BEATING the market: {len(beats)}  {beats if beats else ''}")
    print(f"  sign test on improved/regressed: p = {sign_test_p(worse, better):.3f}")
    print("  (baseline was 8 of 9 WORSE than market, p=0.039)")

    # ---- step 4: dispersion ----------------------------------------------------
    print("\nSTEP 4  DISPERSION  model_home_prob_stdev, PER LEAGUE")
    print("  NOTE: 0.1575/0.1811 quoted elsewhere are CROSS-LEAGUE MEANS, not any")
    print("  one league's value. Compare each league to ITS OWN baseline row.")
    print(f"  {'league':20s} {'base':>7s} {'new':>7s} {'delta':>8s} {'market':>8s}")
    narrower = 0
    bm = nm = mm = 0.0
    for lg in comparable:
        b, r = base[lg], run[lg]
        sb, sr = b.get("model_home_prob_stdev"), r.get("model_home_prob_stdev")
        mk = b.get("market_home_prob_stdev")
        if sb is None or sr is None:
            continue
        bm += sb; nm += sr; mm += (mk or 0)
        if sr < (mk or 0):
            narrower += 1
        print(f"  {lg:20s} {sb:7.4f} {sr:7.4f} {sr-sb:+8.4f} {mk:8.4f}")
    n = len(comparable)
    if n:
        print(f"\n  cross-league mean stdev: baseline {bm/n:.4f} -> run {nm/n:.4f}"
              f"   (market {mm/n:.4f})")
        print(f"  still narrower than market in {narrower} of {n} leagues"
              f"   (baseline: 8 of 9)")

    print("\nVERDICT")
    if len(beats) == 0:
        print("  The model still loses to the closing line in every comparable league.")
    else:
        print(f"  Beats the market in {len(beats)}: {beats}")
        print("  CAUTION: the baseline called belgian_pro_league's -0.0011 at n=120")
        print("  'noise at n=120 and must not be reported as a win'. One league is")
        print("  not a result; the sign test across all nine is.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
