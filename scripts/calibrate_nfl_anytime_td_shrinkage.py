"""Tune `player_stats.ANYTIME_TD_SHRINKAGE_K` out-of-sample. (`#471`
follow-up, `nfl-player-props-calibration-fix` lane.)

`scripts/backtest_nfl_props.py` measured the defect this fixes: players
with a raw rolling `anytime_td` mean of exactly 0.0 (2-4 scoreless games)
had a REAL hit rate of ~13-14% that week, not 0%. `player_stats.
shrink_count_mean` blends the raw rate toward a data-derived, no-lookahead
league prior via `posterior_mean = (n*raw + k*prior) / (n+k)`. This script
answers the one question that formula doesn't answer on its own: what `k`?

METHOD, mirroring backtest_nfl_props.py's own out-of-sample discipline
(never re-derive a number here that script already computes): collect
every real `anytime_td` (player, week) observation 2022-2025 ONCE (raw
mean/n/actual + the pre-week league prior at that exact week -- all cheap,
already-cached substrate), then for a range of candidate `k` values,
compute the shrunk probability and score Brier. **`k` is SELECTED on
2022-2023 and only ever REPORTED, never re-selected, on 2024-2025** -- the
identical fit/score split the main backtest uses for its bias correction,
for the same reason: picking k on the same rows it's scored against would
be circular, an in-sample fit dressed up as a result.

Usage:
  py -3 scripts/calibrate_nfl_anytime_td_shrinkage.py
  py -3 scripts/calibrate_nfl_anytime_td_shrinkage.py --candidates 0,1,2,3,4,6,8,12,20
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from statistics import fmean
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.nfl import player_stats


def _all_player_ids(season: int) -> list[str]:
    ids: set[str] = set()
    for play in player_stats.load_player_plays(season):
        for key in ("passer_player_id", "rusher_player_id", "receiver_player_id"):
            pid = play.get(key)
            if pid:
                ids.add(pid)
    return sorted(ids)


def collect_anytime_td_substrate(seasons: list[int]) -> list[dict[str, Any]]:
    """One row per (season, player, week) with a resolvable raw anytime_td
    rate: {season, week, raw_mean, n, prior_mean, prior_n, actual}. Raw
    mean/n reuse a locally cached game log (same rationale as
    backtest_nfl_props.py's `_cached_game_log` -- `player_rate` rescans
    the whole season's plays on every call, which is fine once per player
    but not thousands of times). The league prior comes straight from
    `player_stats._anytime_td_league_prior`, which is already lru_cached
    per season and cheap (a dict of ~18 weeks), so no local re-derivation
    is needed for that half."""
    rows: list[dict[str, Any]] = []
    log_cache: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for season in seasons:
        for pid in _all_player_ids(season):
            key = (season, pid)
            if key not in log_cache:
                log_cache[key] = player_stats.player_game_log(season, pid)
            log = log_cache[key]
            for entry in log:
                week = entry["week"]
                values = [row["anytime_td"] for row in log if row["week"] < week]
                if len(values) < 2:
                    continue
                raw_mean = fmean(values)
                prior_mean, prior_n = player_stats._anytime_td_league_prior(season, week)
                if prior_n == 0:
                    continue
                rows.append({
                    "season": season, "week": week, "raw_mean": raw_mean, "n": len(values),
                    "prior_mean": prior_mean, "prior_n": prior_n, "actual": entry["anytime_td"],
                })
    return rows


def brier_for_k(rows: list[dict[str, Any]], k: float) -> tuple[float, int]:
    probs = []
    outcomes = []
    for row in rows:
        shrunk = player_stats.shrink_count_mean(row["raw_mean"], row["n"], row["prior_mean"], k)
        prob = max(0.0, min(1.0, shrunk))
        probs.append(prob)
        outcomes.append(1 if row["actual"] >= 1 else 0)
    return round(fmean((p - o) ** 2 for p, o in zip(probs, outcomes)), 6), len(rows)


def bucket_gap_at_zero(rows: list[dict[str, Any]], k: float) -> dict[str, Any]:
    """The exact defect #471 measured: among rows with raw_mean == 0.0,
    what does the shrunk model now predict, and what really happens?"""
    zero_rows = [r for r in rows if r["raw_mean"] == 0.0]
    if not zero_rows:
        return {"n": 0}
    shrunk_probs = [max(0.0, min(1.0, player_stats.shrink_count_mean(r["raw_mean"], r["n"], r["prior_mean"], k))) for r in zero_rows]
    actual_hit_rate = fmean(1 if r["actual"] >= 1 else 0 for r in zero_rows)
    return {"n": len(zero_rows), "avg_predicted": round(fmean(shrunk_probs), 4), "actual_hit_rate": round(actual_hit_rate, 4)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seasons", default="2022,2023,2024,2025")
    parser.add_argument("--candidates", default="0,1,2,3,4,5,6,8,10,12,16,20,30",
                         help="k values to sweep, comma-separated (0 = no shrinkage, the pre-fix baseline)")
    parser.add_argument("--out", default="", help="write the RESULT JSON block to this path too")
    args = parser.parse_args()

    seasons = [int(s.strip()) for s in args.seasons.split(",") if s.strip()]
    fit_seasons = [s for s in seasons if s <= 2023]
    score_seasons = [s for s in seasons if s >= 2024]
    print(f"Fit (select k) on seasons: {fit_seasons}")
    print(f"Score (report only) on seasons: {score_seasons}")

    fit_rows = collect_anytime_td_substrate(fit_seasons)
    score_rows = collect_anytime_td_substrate(score_seasons)
    print(f"fit rows: {len(fit_rows)}, score rows: {len(score_rows)}")

    candidates = [float(c.strip()) for c in args.candidates.split(",") if c.strip() != ""]
    print(f"\n{'k':>6s} {'fit Brier':>10s} {'fit n':>7s}")
    fit_results = []
    for k in candidates:
        brier, n = brier_for_k(fit_rows, k)
        fit_results.append((k, brier, n))
        print(f"{k:>6.1f} {brier:>10.6f} {n:>7d}")

    best_k, best_brier, _n = min(fit_results, key=lambda row: row[1])
    print(f"\nSELECTED k = {best_k} (lowest fit Brier = {best_brier}), NOT re-selected on the score half.")

    print("\nOUT-OF-SAMPLE REPORT (2024-2025, k fixed at the selected value, unshrunk k=0 baseline shown for comparison):")
    baseline_brier, score_n = brier_for_k(score_rows, 0.0)
    selected_brier, _n2 = brier_for_k(score_rows, best_k)
    print(f"  n={score_n}")
    print(f"  k=0 (no shrinkage, pre-fix)  Brier = {baseline_brier}")
    print(f"  k={best_k} (selected)        Brier = {selected_brier}")
    print(f"  improvement: {round(baseline_brier - selected_brier, 6)}")

    print("\nTHE EXACT DEFECT #471 MEASURED (raw_mean == 0.0 rows), out-of-sample:")
    zero_baseline = bucket_gap_at_zero(score_rows, 0.0)
    zero_selected = bucket_gap_at_zero(score_rows, best_k)
    print(f"  k=0:          {zero_baseline}")
    print(f"  k={best_k}: {zero_selected}")

    result = {
        "fit_seasons": fit_seasons, "score_seasons": score_seasons,
        "fit_n": len(fit_rows), "score_n": len(score_rows),
        "fit_sweep": [{"k": k, "brier": b, "n": n} for k, b, n in fit_results],
        "selected_k": best_k,
        "out_of_sample": {
            "n": score_n, "brier_k0_baseline": baseline_brier, "brier_selected_k": selected_brier,
            "improvement": round(baseline_brier - selected_brier, 6),
        },
        "zero_mean_bucket_out_of_sample": {"k0_baseline": zero_baseline, "selected_k": zero_selected},
    }
    print("\nRESULT block:")
    print(json.dumps(result, indent=2))

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"\nWritten to {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
