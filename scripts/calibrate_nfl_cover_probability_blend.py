"""Tune a per-market Normal/log-normal BLEND weight for NFL's yardage/
count cover-probability model. (`#471` defect 1, `nfl-player-props-
skew-fix` lane -- follow-up to `compare_nfl_cover_probability_models.py`.)

WHY A BLEND, NOT PURE LOG-NORMAL. `compare_nfl_cover_probability_models.py`
measured a MIXED result: pure log-normal (full method-of-moments skew
correction) improved Brier on 4 of 8 markets (passing_yards/attempts,
rushing_yards/attempts -- the higher-coefficient-of-variation markets) and
WORSENED it on the other 4 (passing_tds, receptions, receiving_yards,
interceptions), by OVERCORRECTING: the mid-decile gap flipped sign and
often grew (e.g. interceptions bucket 6: Normal +0.113 -> LogNormal
-0.143, further from zero, not closer). Shipping pure log-normal
universally would trade one calibration defect for another on half the
markets -- exactly the failure mode this lane's falsification test was
written to catch.

THE FIX: blend the two models' predicted probabilities,
`p = (1-w)*p_normal + w*p_lognormal`, and let each market pick its own
weight `w` in [0, 1] (0 = today's behavior exactly, 1 = full log-normal).
This is the SAME shape as `#471`'s anytime_td shrinkage constant `k` --
one number, tuned out-of-sample, not guessed -- extended to be PER-MARKET
because the comparison already showed different markets need different
amounts of correction.

CLOSED-FORM, NOT A GRID SEARCH: for a FIXED set of (p_normal, p_lognormal,
outcome) triples, Brier(w) = mean((p_normal + w*(p_lognormal-p_normal) -
outcome)^2) is a QUADRATIC in w (Brier is convex per-observation, and a
sum of convex quadratics is convex), so the minimizing w has a closed
form: with d_i = p_lognormal_i - p_normal_i and e_i = p_normal_i -
outcome_i,

    w* = -sum(e_i * d_i) / sum(d_i^2)

clipped to [0, 1] (unclipped w could exceed 1, meaning "even more skew
correction than pure log-normal would help", or go negative, meaning "the
correction points the wrong way" -- both are real possible findings and
are REPORTED, but the constant shipped is clipped so this never becomes
LESS calibrated than pure log-normal or reverses the correction's sign).

Same fit/score discipline as `calibrate_nfl_anytime_td_shrinkage.py`: `w`
is SELECTED on 2022-2023, only ever REPORTED on 2024-2025.

Usage:
  py -3 scripts/calibrate_nfl_cover_probability_blend.py
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
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from backtest_nfl_props import STAT_KEYS
from backtest_nfl_props import collect_raw
from compare_nfl_cover_probability_models import collect_aligned_prob_pairs


def brier(probs: list[float], outcomes: list[int]) -> float:
    return round(fmean((p - o) ** 2 for p, o in zip(probs, outcomes)), 6)


def optimal_blend_weight(normal_probs: list[float], lognormal_probs: list[float], outcomes: list[int]) -> float:
    """Closed-form Brier-minimizing blend weight -- see module docstring
    for the derivation. Returns the UNCLIPPED value; callers decide
    whether/how to clip."""
    numerator = 0.0
    denominator = 0.0
    for p_normal, p_lognormal, outcome in zip(normal_probs, lognormal_probs, outcomes):
        d = p_lognormal - p_normal
        e = p_normal - outcome
        numerator += e * d
        denominator += d * d
    if denominator == 0.0:
        return 0.0  # log-normal is identical to Normal on this sample -- no correction possible or needed
    return -numerator / denominator


def blend_probs(normal_probs: list[float], lognormal_probs: list[float], weight: float) -> list[float]:
    return [(1.0 - weight) * pn + weight * pl for pn, pl in zip(normal_probs, lognormal_probs)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seasons", default="2022,2023,2024,2025")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    seasons = [int(s.strip()) for s in args.seasons.split(",") if s.strip()]
    fit_seasons = [s for s in seasons if s <= 2023]
    score_seasons = [s for s in seasons if s >= 2024]
    print(f"Fit (select w) on seasons: {fit_seasons}")
    print(f"Score (report only) on seasons: {score_seasons}")

    fit_raw, _fit_coverage = collect_raw(fit_seasons)
    score_raw, _score_coverage = collect_raw(score_seasons)

    markets = [s for s in STAT_KEYS if s != "anytime_td"]
    result: dict[str, Any] = {"fit_seasons": fit_seasons, "score_seasons": score_seasons, "markets": {}}

    header = f"  {'market':16s} {'n fit':>7s} {'w* (raw)':>9s} {'w (clipped)':>12s} {'n score':>8s} {'Brier w=0':>10s} {'Brier w*':>9s} {'improvement':>12s}"
    print("\n" + header)
    print("  " + "-" * (len(header) - 2))

    for stat in markets:
        fit_normal, fit_lognormal, fit_outcomes = collect_aligned_prob_pairs(fit_raw, stat)
        score_normal, score_lognormal, score_outcomes = collect_aligned_prob_pairs(score_raw, stat)

        if len(fit_outcomes) < 100 or len(score_outcomes) < 100:
            print(f"  {stat:16s} below 100 in fit or score half, not measurable")
            result["markets"][stat] = {"verdict": "not measurable (sample too small)"}
            continue

        w_raw = optimal_blend_weight(fit_normal, fit_lognormal, fit_outcomes)
        w_clipped = max(0.0, min(1.0, w_raw))

        score_brier_baseline = brier(score_normal, score_outcomes)
        score_blended = blend_probs(score_normal, score_lognormal, w_clipped)
        score_brier_selected = brier(score_blended, score_outcomes)
        improvement = round(score_brier_baseline - score_brier_selected, 6)

        print(f"  {stat:16s} {len(fit_outcomes):7d} {w_raw:>9.3f} {w_clipped:>12.3f} {len(score_outcomes):8d} "
              f"{score_brier_baseline:>10.6f} {score_brier_selected:>9.6f} {improvement:>+12.6f}")

        result["markets"][stat] = {
            "n_fit": len(fit_outcomes), "n_score": len(score_outcomes),
            "w_raw_unclipped": round(w_raw, 4), "w_clipped": round(w_clipped, 4),
            "out_of_sample": {
                "brier_w0_baseline": score_brier_baseline,
                "brier_selected_w": score_brier_selected,
                "improvement": improvement,
            },
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
