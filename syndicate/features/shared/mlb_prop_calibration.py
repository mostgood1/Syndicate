"""What the backtest says the MLB hitter-prop projections are actually worth.

`#428`, second model measured. Produced by
`scripts/backtest_mlb_props.py --limit 14`, which joins production
`daily_summary_<date>.json` projections to real MLB StatsAPI box scores on
`batter_id` (an EXACT id join -- `batter_id` IS the StatsAPI person id, so none
of the name-matching failure `#218` records applies here).

THE HEADLINE, AND IT IS NEITHER "SKILLED" NOR "NO SKILL": the model is
**BIASED, NOT BLIND**. Every counting market carries real signal and every one
of them loses to a constant baseline, purely by sitting too high.

    market  n      corr    MAE model  MAE base  MAE de-biased  bias    inflation
    hits    2487   0.1607     0.7321    0.6978         0.6971  +0.237     +28.6%
    tb      2487   0.1523     1.3652    1.3167         1.2911  +0.239     +17.7%
    rbi     2487   0.1316     0.6394    0.6040         0.5830  +0.128     +30.5%
    runs    2487   0.1620     0.5799    0.5698         0.5455  +0.115     +25.9%
    2b      2487   0.0278     0.2793    0.2468         0.2459  +0.046     +32.5%
    3b      2487   0.0179     0.0303    0.0254         0.0268  +0.005     +40.1%
    sb      2487   0.1605     0.1151    0.1336         0.1289  -0.016     -22.2%

Remove the mean error and **5 of 7 markets beat the baseline**. So the ranking
information is real; the LEVEL is wrong. That is a calibration problem, the same
shape `#367` found on NFL totals (+5.6 bias, fixed by `calibrated_total`), and
it is why publishing "no measured skill" here would have been actively wrong --
it would have suppressed a model that needs correcting, not retiring.

WHY THE LEVEL IS WRONG -- TWO STACKED CAUSES, MEASURED SEPARATELY:

  * opportunity is over-predicted: `pa_mean` **+18.4%** vs real plate
    appearances, `ab_mean` +17.2% vs real at-bats;
  * production PER opportunity is ALSO over-predicted: per-PA rates still run
    **+12.2%** after normalising by PA.

Normalising by opportunity removes **55%** of the count bias -- substantial, and
NOT all of it. **A playing-time fix alone will not remove the inflation**, and
anyone told otherwise will be surprised. Fix opportunity first because it sits
upstream of every market, then re-measure; per-market calibration will still be
needed.

SCOPE AND LIMITS, so this block is not read as more than it is:
  * 2,487 player-games over 14 dates (2026-08-01..2026-08-14), one season, one
    stretch of one season. It is a real sample, not a long one.
  * players who did not bat (0 PA) are EXCLUDED -- a projection for someone who
    never appeared is an unplayed prediction, not a wrong one, and including
    them drags every actual toward zero.
  * `hits_runs_rbis` is deliberately ABSENT below. In this window it was the
    degenerate constant `0.0` that `#429` fixed on 2026-08-14, so it cannot be
    measured from this data. Leaving it out means `projection_skill` reports it
    `unmeasured`, which is the truth. Re-measure it after a window of
    post-fix dates.
  * `2b`/`3b` correlate at 0.03/0.02 -- close enough to nothing that their
    verdicts say so regardless of the de-biasing arithmetic.
"""

from __future__ import annotations

from typing import Any

SAMPLE_PLAYER_GAMES = 2487
SAMPLE_DATES = "2026-08-01..2026-08-14"

# Keyed by the market as it appears on board rows. `batter_home_runs` and
# `batter_hits_runs_rbis` are deliberately absent -- not measured, so they stay
# honestly `unmeasured` rather than inheriting a neighbour's number.
_MARKET_SKILL: dict[str, dict[str, Any]] = {
    "batter_hits": {
        "correlation": 0.1607, "mae_model": 0.7321, "mae_constant_baseline": 0.6978,
        "mae_debiased": 0.6971, "mean_bias": 0.2371, "inflation_pct": 28.6,
        "verdict": "biased high ~29%; real ranking signal, loses to the mean until de-biased",
    },
    "batter_total_bases": {
        "correlation": 0.1523, "mae_model": 1.3652, "mae_constant_baseline": 1.3167,
        "mae_debiased": 1.2911, "mean_bias": 0.2391, "inflation_pct": 17.7,
        "verdict": "biased high ~18%; real ranking signal, loses to the mean until de-biased",
    },
    "batter_rbis": {
        "correlation": 0.1316, "mae_model": 0.6394, "mae_constant_baseline": 0.6040,
        "mae_debiased": 0.5830, "mean_bias": 0.1283, "inflation_pct": 30.5,
        "verdict": "biased high ~31%; real ranking signal, loses to the mean until de-biased",
    },
    "batter_runs_scored": {
        "correlation": 0.1620, "mae_model": 0.5799, "mae_constant_baseline": 0.5698,
        "mae_debiased": 0.5455, "mean_bias": 0.1148, "inflation_pct": 25.9,
        "verdict": "biased high ~26%; real ranking signal, loses to the mean until de-biased",
    },
    "batter_doubles": {
        "correlation": 0.0278, "mae_model": 0.2793, "mae_constant_baseline": 0.2468,
        "mae_debiased": 0.2459, "mean_bias": 0.0463, "inflation_pct": 32.5,
        "verdict": "almost no signal (r=0.03) and biased high ~33%",
    },
    "batter_triples": {
        "correlation": 0.0179, "mae_model": 0.0303, "mae_constant_baseline": 0.0254,
        "mae_debiased": 0.0268, "mean_bias": 0.0052, "inflation_pct": 40.1,
        "verdict": "no measured skill (r=0.02); loses to the mean even de-biased",
    },
    "batter_stolen_bases": {
        "correlation": 0.1605, "mae_model": 0.1151, "mae_constant_baseline": 0.1336,
        "mae_debiased": 0.1289, "mean_bias": -0.0159, "inflation_pct": -22.2,
        "verdict": "the only market that beats the mean as-published; biased LOW ~22%",
    },
}

# Measured alongside the markets and kept here because it is the single most
# actionable number in this file: it is upstream of every market above.
OPPORTUNITY_BIAS: dict[str, Any] = {
    "pa_mean_inflation_pct": 18.4,
    "ab_mean_inflation_pct": 17.2,
    "per_pa_rate_inflation_pct": 12.2,
    "share_of_count_bias_explained_by_opportunity_pct": 55,
    "note": (
        "Fix opportunity first -- it sits upstream of every market. But it "
        "explains only 55% of the count bias, so a playing-time correction "
        "ALONE will not remove the inflation."
    ),
}


def skill_note(market: Any) -> dict[str, Any] | None:
    """The compact per-row block, or None for an unmeasured market.

    DELIBERATELY SMALL. This lands on every prop row on every MLB board, and
    `#374` records `extraHitterProps` reaching 68% of the MLB live-lens payload
    at 117 keys per record. The full numbers live in `_MARKET_SKILL` for anyone
    who wants them; the row carries four keys.

    Returning None for an unmeasured market is load-bearing:
    `projection_skill.attach_projection_skill` then stamps `unmeasured`, which
    is the honest answer, instead of this module inventing one.
    """
    entry = _MARKET_SKILL.get(str(market or "").strip().lower())
    if not entry:
        return None
    return {
        "sample_games": SAMPLE_PLAYER_GAMES,
        "seasons": SAMPLE_DATES,
        "correlation": entry["correlation"],
        "verdict": entry["verdict"],
    }
