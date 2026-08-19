"""Compare cover-probability models for NFL's yardage/count player-prop
markets: the current Normal-CDF vs a log-normal (method-of-moments)
candidate. (`#471` defect 1, `nfl-player-props-skew-fix` lane.)

WHY. `scripts/backtest_nfl_props.py` Section 2 measured every count/
yardage market overconfident near its own mean -- predicts ~50% cover at
`line == mean`, real hit rate ~37-44%. `Normal(mean, stdev)` is symmetric
by construction; real NFL box-score stats (yards, receptions, attempts)
are right-skewed (a hard floor at 0, occasional big games) -- mean >
median, so the true P(actual > mean) is BELOW 50%, exactly the direction
and shape of the measured gap.

THE CANDIDATE HAS NO TUNABLE PARAMETER, unlike `#471`'s anytime_td
shrinkage constant. A log-normal fit via method-of-moments is fully
determined by the SAME (mean, stdev) `player_rate` already computes --
sigma^2 = ln(1 + variance/mean^2), mu = ln(mean) - sigma^2/2 -- so there
is nothing to select on one half of the data and validate on the other.
This script is a plain side-by-side comparison over the WHOLE sample,
with a season-half breakdown printed for transparency (not as a fit/score
split, since nothing is fit).

REUSES scripts/backtest_nfl_props.py's own `collect_raw` (already
includes the shipped anytime_td shrinkage fix for that one market) rather
than re-deriving the season/player/week collection a third time.

Usage:
  py -3 scripts/compare_nfl_cover_probability_models.py --seasons 2022,2023,2024,2025
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from statistics import fmean
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from backtest_nfl_props import STAT_KEYS
from backtest_nfl_props import collect_raw

_OFFSETS = (-1.0, -0.5, 0.0, 0.5, 1.0)


def normal_cover_probability(mean: float, stdev: float, line: float) -> float | None:
    """The model currently shipping -- identical to
    syndicate.features.nfl.props._nfl_prop_model_probability's non-
    anytime_td branch, reproduced here (not imported) so this script can
    be run standalone against the substrate without importing Flask-
    adjacent modules; kept byte-for-byte identical on purpose."""
    if stdev is None or stdev <= 0:
        return None
    return 1.0 - statistics.NormalDist(mean, stdev).cdf(line)


def lognormal_params_from_moments(mean: float, stdev: float) -> tuple[float, float] | None:
    """Method-of-moments fit: the (mu, sigma) of the log-normal
    distribution with the SAME mean and variance as the input -- exactly
    the two numbers player_rate already computes, no new upstream data
    needed. None when undefined: mean<=0 (no log-normal has that mean --
    can only happen if a player's entire prior sample is 0, e.g. a
    passer's rushing_yards) or the moment equations degenerate."""
    if mean is None or mean <= 0 or stdev is None or stdev <= 0:
        return None
    variance = stdev * stdev
    sigma_sq = math.log(1.0 + variance / (mean * mean))
    if sigma_sq <= 0:
        return None
    mu = math.log(mean) - sigma_sq / 2.0
    return mu, math.sqrt(sigma_sq)


def lognormal_cover_probability(mean: float, stdev: float, line: float) -> float | None:
    if line <= 0:
        return None  # no real NFL prop line is <= 0; fall back rather than guess
    params = lognormal_params_from_moments(mean, stdev)
    if params is None:
        return None
    mu, sigma = params
    z = (math.log(line) - mu) / sigma
    return 1.0 - statistics.NormalDist(0.0, 1.0).cdf(z)


def brier(probs: list[float], outcomes: list[int]) -> float:
    return round(fmean((p - o) ** 2 for p, o in zip(probs, outcomes)), 6)


def reliability_buckets(probs: list[float], outcomes: list[int], n_buckets: int = 10) -> list[dict[str, Any]]:
    paired = sorted(zip(probs, outcomes), key=lambda pair: pair[0])
    bucket_size = len(paired) // n_buckets
    buckets = []
    for i in range(n_buckets):
        start = i * bucket_size
        end = (i + 1) * bucket_size if i < n_buckets - 1 else len(paired)
        chunk = paired[start:end]
        if not chunk:
            continue
        avg_pred = fmean(p for p, _ in chunk)
        hit_rate = fmean(o for _, o in chunk)
        buckets.append({"bucket": i + 1, "n": len(chunk), "avg_predicted": round(avg_pred, 4),
                         "actual_hit_rate": round(hit_rate, 4), "gap": round(avg_pred - hit_rate, 4)})
    return buckets


def collect_aligned_prob_pairs(raw_rows: list[dict[str, Any]], stat: str) -> tuple[list[float], list[float], list[int]]:
    """Normal-probability, log-normal-probability, and outcome, for the
    SAME rows -- aligned by construction (built in one pass) rather than
    two independent passes trusted to line up. A threshold is dropped
    entirely if EITHER model can't price it (log-normal can return None
    in strictly more cases than Normal: mean<=0, or a synthetic line
    landing <=0), so both models are always compared on an identical
    population."""
    normal_probs: list[float] = []
    lognormal_probs: list[float] = []
    outcomes: list[int] = []
    for row in raw_rows:
        if row["stat"] != stat:
            continue
        mean, stdev, actual = row["pred_mean"], row["pred_stdev"], row["actual"]
        for offset in _OFFSETS:
            line = mean + offset * (stdev or 0.0)
            if line <= 0:
                continue
            p_normal = normal_cover_probability(mean, stdev, line)
            p_lognormal = lognormal_cover_probability(mean, stdev, line)
            if p_normal is None or p_lognormal is None:
                continue
            normal_probs.append(p_normal)
            lognormal_probs.append(p_lognormal)
            outcomes.append(1 if actual > line else 0)
    return normal_probs, lognormal_probs, outcomes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seasons", default="2022,2023,2024,2025")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    seasons = [int(s.strip()) for s in args.seasons.split(",") if s.strip()]
    print(f"Loading real nflverse play-by-play for seasons: {seasons} ...")
    raw_rows, coverage = collect_raw(seasons)
    print(f"coverage: {coverage}")

    markets = [s for s in STAT_KEYS if s != "anytime_td"]
    result: dict[str, Any] = {"seasons": seasons, "markets": {}}

    header = f"  {'market':16s} {'n':>7s} {'Normal Brier':>13s} {'LogNormal Brier':>16s} {'improvement':>12s}"
    print("\n" + header)
    print("  " + "-" * (len(header) - 2))

    for stat in markets:
        normal_probs, lognormal_probs, outcomes = collect_aligned_prob_pairs(raw_rows, stat)

        if len(outcomes) < 100:
            print(f"  {stat:16s} {len(outcomes):7d} below 100, not measurable")
            result["markets"][stat] = {"n": len(outcomes), "verdict": "not measurable"}
            continue

        b_normal = brier(normal_probs, outcomes)
        b_lognormal = brier(lognormal_probs, outcomes)
        improvement = round(b_normal - b_lognormal, 6)
        print(f"  {stat:16s} {len(outcomes):7d} {b_normal:>13.6f} {b_lognormal:>16.6f} {improvement:>+12.6f}")

        normal_buckets = reliability_buckets(normal_probs, outcomes)
        lognormal_buckets = reliability_buckets(lognormal_probs, outcomes)
        result["markets"][stat] = {
            "n": len(outcomes), "brier_normal": b_normal, "brier_lognormal": b_lognormal,
            "improvement": improvement,
            "normal_buckets": normal_buckets, "lognormal_buckets": lognormal_buckets,
        }

    print("\nPER-MARKET RELIABILITY, mid-deciles only (buckets 4-7, where the defect was measured):")
    for stat, entry in result["markets"].items():
        if "normal_buckets" not in entry:
            continue
        print(f"\n  {stat}:")
        print(f"    {'bucket':>8s} {'Normal gap':>12s} {'LogNormal gap':>14s}")
        for nb, lb in zip(entry["normal_buckets"][3:7], entry["lognormal_buckets"][3:7]):
            print(f"    {nb['bucket']:>8d} {nb['gap']:>+12.3f} {lb['gap']:>+14.3f}")

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
