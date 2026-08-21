#!/usr/bin/env python3
"""Three diagnostics on the NFL prop market, using odds already bought.

`report_nfl_props_roi.py` measured the model at -7.35% (best price) / -7.23%
(DraftKings) over 64,007 graded bets, and found that filtering for a LARGER
model-vs-market disagreement made ROI WORSE. That last fact is the interesting
one: it says the model's confidence is anti-informative, which is a different
problem from the model being uninformative (fading it loses 16.9%, so the picks
are correctly signed).

This asks three questions that need no new capture and no model change:

  1. CROSS-BOOK DISPERSION. Where books disagree on the same (player, market,
     line) by more than the vig, one of them is wrong. Is taking the best of N
     books worth anything, measured on ONE bet population rather than comparing
     two differently-sized ones? (The headline -7.35 vs -7.23 compared 48,024
     bets against 13,368 -- reassuring but not controlled. This controls it.)

  2. PER-BOOK ROI. Same picks, priced at each book, restricted to what that
     book actually quoted. A book that is consistently softer is actionable
     without improving the model at all.

  3. CALIBRATION REPAIR, OUT OF SAMPLE. Fit probability -> realized win rate on
     2023-2024, apply to 2025, and re-run the edge filter. If the filter
     becomes monotone once probabilities are repaired, there is a usable signal
     underneath a broken confidence scale. If it stays flat, there is not, and
     no amount of edge-thresholding will help.

Read (3) before spending anything on opening lines or new model inputs.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_roi_module():
    spec = importlib.util.spec_from_file_location(
        "_roi", REPO_ROOT / "scripts" / "report_nfl_props_roi.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def roi_of(bets: list[tuple[float, int, bool]]) -> dict[str, Any] | None:
    """bets = (model_prob, price, won). Flat 1 unit."""
    if not bets:
        return None
    profit = 0.0
    wins = 0
    for _prob, price, won in bets:
        if won:
            profit += (price / 100.0) if price > 0 else (100.0 / abs(price))
            wins += 1
        else:
            profit -= 1.0
    n = len(bets)
    return {"n": n, "hit_rate": round(wins / n, 4),
            "profit_units": round(profit, 1), "roi_pct": round(100.0 * profit / n, 2)}


# ---------------------------------------------------------------------------

def analysis_dispersion(graded: list[dict[str, Any]], roi_mod, *, min_books: int) -> dict[str, Any]:
    print("\n" + "=" * 78)
    print(f"1. CROSS-BOOK DISPERSION  (bets quoted by >= {min_books} books -- one population)")
    print("=" * 78)

    pool = [r for r in graded if len(r["prices"]) >= min_books]
    if not pool:
        print("  no bets meet the book-count floor")
        return {}

    spreads = []
    for record in pool:
        implied = [roi_mod.american_to_implied(p) for p in record["prices"].values()]
        spreads.append(max(implied) - min(implied))
    spreads.sort()

    def pct(fraction: float) -> float:
        return round(spreads[min(len(spreads) - 1, int(fraction * len(spreads)))], 4)

    print(f"  bets: {len(pool):,}   books/bet: median {statistics.median(len(r['prices']) for r in pool):.0f}")
    print(f"  implied-probability spread across books (max - min):")
    print(f"    median {pct(0.50):.4f}   p75 {pct(0.75):.4f}   p90 {pct(0.90):.4f}   p99 {pct(0.99):.4f}")

    # Same bets, three price bases.
    bases: dict[str, list[tuple[float, int, bool]]] = {"best": [], "median": [], "worst": []}
    for record in pool:
        prices = sorted(record["prices"].values())
        bases["worst"].append((record["model_prob"], prices[0], record["won"]))
        bases["median"].append((record["model_prob"], prices[len(prices) // 2], record["won"]))
        bases["best"].append((record["model_prob"], prices[-1], record["won"]))

    print(f"\n  SAME {len(pool):,} bets, priced three ways:")
    print(f"  {'basis':10s} {'hit rate':>9s} {'units':>10s} {'ROI %':>9s}")
    out: dict[str, Any] = {"n": len(pool), "spread_median": pct(0.50), "spread_p90": pct(0.90), "bases": {}}
    for label in ("worst", "median", "best"):
        result = roi_of(bases[label])
        print(f"  {label:10s} {result['hit_rate']:>9.4f} {result['profit_units']:>10.1f} {result['roi_pct']:>+9.2f}")
        out["bases"][label] = result
    gain = out["bases"]["best"]["roi_pct"] - out["bases"]["median"]["roi_pct"]
    print(f"\n  price shopping is worth {gain:+.2f} ROI points (best vs median), on identical bets.")
    out["shopping_gain_pts"] = round(gain, 2)
    return out


def analysis_per_book(graded: list[dict[str, Any]], *, min_bets: int) -> dict[str, Any]:
    print("\n" + "=" * 78)
    print("2. PER-BOOK ROI  (same picks, each book's own price, its own quoted subset)")
    print("=" * 78)
    by_book: dict[str, list[tuple[float, int, bool]]] = defaultdict(list)
    for record in graded:
        for book, price in record["prices"].items():
            by_book[book].append((record["model_prob"], price, record["won"]))

    print(f"  {'book':20s} {'n':>8s} {'hit rate':>9s} {'units':>10s} {'ROI %':>9s}")
    out: dict[str, Any] = {}
    rows = []
    for book, bets in by_book.items():
        result = roi_of(bets)
        if result is None or result["n"] < min_bets:
            continue
        rows.append((book, result))
        out[book] = result
    for book, result in sorted(rows, key=lambda kv: -kv[1]["roi_pct"]):
        print(f"  {book:20s} {result['n']:>8,d} {result['hit_rate']:>9.4f} "
              f"{result['profit_units']:>10.1f} {result['roi_pct']:>+9.2f}")
    return out


def _fit_bins(pairs: list[tuple[float, bool]], *, bins: int) -> list[tuple[float, float, float]]:
    """Equal-count bins over predicted probability -> realized win rate.

    Plain binning rather than isotonic/Platt on purpose: no scipy or sklearn in
    this repo's runtime, and a monotone fit that needs a dependency we do not
    ship is not a fit we can put in production.
    """
    ordered = sorted(pairs, key=lambda pair: pair[0])
    if not ordered:
        return []
    size = max(1, len(ordered) // bins)
    out: list[tuple[float, float, float]] = []
    for start in range(0, len(ordered), size):
        chunk = ordered[start:start + size]
        if len(chunk) < 30:
            if out:
                break
        lo = chunk[0][0]
        hi = chunk[-1][0]
        rate = sum(1 for _p, won in chunk if won) / len(chunk)
        out.append((lo, hi, rate))
    return out


def _apply_bins(fit: list[tuple[float, float, float]], prob: float) -> float:
    for lo, hi, rate in fit:
        if lo <= prob <= hi:
            return rate
    return fit[-1][2] if fit else prob


def analysis_calibration(graded: list[dict[str, Any]], roi_mod, *, train_seasons: list[int],
                         test_season: int, edges: list[float], bins: int) -> dict[str, Any]:
    print("\n" + "=" * 78)
    print(f"3. CALIBRATION REPAIR  (fit {train_seasons}, test {test_season} -- real holdout)")
    print("=" * 78)

    def priced(record):
        prices = record["prices"]
        return max(prices.values()) if prices else None

    train = [r for r in graded if r["season"] in train_seasons and priced(r) is not None]
    test = [r for r in graded if r["season"] == test_season and priced(r) is not None]
    print(f"  train bets: {len(train):,}   test bets: {len(test):,}")
    if len(train) < 500 or len(test) < 500:
        print("  too thin to fit honestly")
        return {}

    fit = _fit_bins([(r["model_prob"], r["won"]) for r in train], bins=bins)
    print(f"\n  fitted map (predicted -> realized, on train):")
    print(f"    {'predicted range':>22s} {'realized':>10s}")
    for lo, hi, rate in fit:
        print(f"    {lo:>10.3f} - {hi:<9.3f} {rate:>10.4f}")

    out: dict[str, Any] = {"train_n": len(train), "test_n": len(test),
                           "fit": [{"lo": lo, "hi": hi, "realized": rate} for lo, hi, rate in fit],
                           "raw": {}, "calibrated": {}}

    print(f"\n  edge filter on the {test_season} holdout, best price:")
    print(f"  {'min edge':>9s} | {'RAW n':>7s} {'ROI %':>8s} | {'CALIBRATED n':>13s} {'ROI %':>8s}")
    for edge in edges:
        raw_bets = []
        cal_bets = []
        for record in test:
            price = priced(record)
            implied = roi_mod.american_to_implied(price)
            if record["model_prob"] - implied >= edge:
                raw_bets.append((record["model_prob"], price, record["won"]))
            if _apply_bins(fit, record["model_prob"]) - implied >= edge:
                cal_bets.append((record["model_prob"], price, record["won"]))
        raw = roi_of(raw_bets)
        cal = roi_of(cal_bets)
        raw_txt = f"{raw['n']:>7,d} {raw['roi_pct']:>+8.2f}" if raw else f"{0:>7d} {'--':>8s}"
        cal_txt = f"{cal['n']:>13,d} {cal['roi_pct']:>+8.2f}" if cal else f"{0:>13d} {'--':>8s}"
        print(f"  {edge:>9.0%} | {raw_txt} | {cal_txt}")
        if raw:
            out["raw"][str(edge)] = raw
        if cal:
            out["calibrated"][str(edge)] = cal
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Market-structure diagnostics for NFL player props")
    parser.add_argument("--seasons", default="2023,2024,2025")
    parser.add_argument("--test-season", type=int, default=2025)
    parser.add_argument("--min-books", type=int, default=4)
    parser.add_argument("--min-bets", type=int, default=500)
    parser.add_argument("--bins", type=int, default=10)
    parser.add_argument("--edges", default="0,0.02,0.05,0.10,0.15")
    parser.add_argument("--out", default="reports/nfl_props_market_diagnostics.json")
    args = parser.parse_args()

    seasons = [int(s) for s in str(args.seasons).split(",") if s.strip()]
    edges = [float(e) for e in str(args.edges).split(",") if e.strip()]
    roi_mod = _load_roi_module()

    print("grading (this reuses backtest_nfl_props.collect_raw) ...", flush=True)
    graded = roi_mod.grade(seasons)
    print(f"graded bets: {len(graded):,}")

    report: dict[str, Any] = {"seasons": seasons, "graded": len(graded)}
    report["dispersion"] = analysis_dispersion(graded, roi_mod, min_books=args.min_books)
    report["per_book"] = analysis_per_book(graded, min_bets=args.min_bets)
    report["calibration"] = analysis_calibration(
        graded, roi_mod,
        train_seasons=[s for s in seasons if s != args.test_season],
        test_season=args.test_season, edges=edges, bins=args.bins,
    )

    out_path = REPO_ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
