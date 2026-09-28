# NFL prop model: the distribution is far too narrow, and the spread never got the small-sample treatment the MEAN did

`[measured 2026-09-28 on the served payload + read from source, lane
layer2-triad-alignment, session 4ab694ed]`

Follows `findings_2026-09-28_model_edge_coverage.md`, which established that 86%
of NFL model edges exceed the 15-point guard and only 3% reach the board. This
diagnoses WHY the probabilities are extreme.

## Two independent defects, not one

### A. THE DISTRIBUTION IS TOO NARROW — mechanism identified

Implied sd, back-derived from the model's own published rows
(`sigma = (projected - line) / z(model_prob_over)`, one row per
player/market/line, served payload 2026-09-28):

    market              n   implied sd   plausible real sd   ratio
    Rushing Attempts    3        0.97           ~4.5         0.21x
    Receptions          4        0.70           ~2.0         0.35x
    Passing Yards       2       23.86          ~65.0         0.37x
    Passing TDs         1        0.50           ~1.0         0.50x
    Receiving Yards    10       18.06          ~28.0         0.64x
    Rushing Yards       8       19.63          ~30.0         0.65x
    Passing Attempts    1        5.78           ~6.0         0.96x
    Interceptions       1        1.00           ~0.8         1.25x

An implied sd of **0.97 on rushing ATTEMPTS** says the model believes a back's
carry count is known to within one carry. The "plausible" column is MY estimate
and is the weakest number here — but the count markets do not need it: 0.70 for
receptions is indefensible against any reasonable figure.

**THE SOURCE**, `syndicate/features/nfl/player_stats.py:541`:

    return statistics.fmean(values), statistics.pstdev(values), len(values)

Two things are wrong with that line for this use.

1. **`pstdev` is the POPULATION sd (divides by n).** These values are a SAMPLE of
   a player's games used to estimate his true game-to-game spread, so the sample
   estimator (n-1) is the right one. Understatement by n:

       n=2  29.3%      n=3  18.4%      n=4  13.4%      n=8  6.5%

   `player_rate` filters `row["week"] < week`, so at week 4 n is typically 3.

2. **NOTHING SHRINKS THE SPREAD TOWARD A PRIOR, and this is the dominant term.**
   The floor is `n >= 2`. A two- or three-game sample sd is not an estimate of
   dispersion, and it fails ASYMMETRICALLY: a player with consistent recent usage
   (17, 16, 18 carries) yields `pstdev ~= 0.82`, and the model then asserts near
   certainty. That reproduces the observed 0.97 for Rushing Attempts exactly, and
   D'Andre Swift's served row is the shape it predicts -- projected 17.0 against
   a 14.5 line, `model_prob_over = 0.9952`.

   **The repo already established this exact defect for the MEAN and fixed it.**
   `#471`: the raw per-player MLE badly underestimates `anytime_td` at small n
   (players at a rolling 0.0 over 2-4 games had a real ~13-14% hit rate), fixed
   with Gamma-Poisson shrinkage whose constant `ANYTIME_TD_SHRINKAGE_K = 12.0`
   was SWEPT and SELECTED (`scripts/calibrate_nfl_anytime_td_shrinkage.py`, fit
   2022-23, reported 2024-25, Brier 0.1973 -> 0.1680 on 8,464 held-out rows).
   **The identical argument applies to the SPREAD of every other market and was
   never made.** The machinery, the harness and the precedent all already exist.

A third, smaller contributor, recorded because it is deliberate and documented
(`props.py:630`): the game-context multiplier scales the **mean only** -- "a
scoring-environment shift is not evidence about that dispersion". Defensible in
isolation, but it means a mean pushed away from the line does not widen with it.

### B. THE MEAN IS OFTEN FAR FROM THE LINE — separate, NOT diagnosed here

    player            market            line   projected   delta
    Denzel Boston     Receiving Yards   35.5      77.00    +41.5
    Kalif Raymond     Receiving Yards   23.5      62.00    +38.5
    Kyle Monangai     Rushing Yards     38.5      73.50    +35.0
    Deshaun Watson    Passing Yards    187.5     221.50    +34.0
    Quinshon Judkins  Rushing Yards     55.5      27.00    -28.5
    Makai Lemon       Receiving Yards   27.5       4.50    -23.0

A projection of 77 receiving yards against a market line of 35.5 is not a
calibration subtlety. **Widening the distribution would make these rows less
confidently wrong, not right.** This needs its own diagnosis (usage share, the
game-context multiplier, or the underlying rate) and is NOT addressed by the
fix for A.

## What was NOT verified

I could not reproduce the probabilities from the raw game logs:
`resolve_player_id(2026, ...)` returns nothing in a session worktree, because
`data/` is excluded from worktrees by default. So:

- the implied sds are **back-derived from the served payload** (production data,
  certain);
- the estimator and the absence of shrinkage are **read from source** (certain);
- the link between them -- that a specific player's consistent 3-game sample
  produced that specific sd -- is **arithmetic and consistent with every row**,
  but the individual game logs were NOT inspected.

## The fix, and the constraint on it

Shrink the per-player sd toward a market/positional population sd with weight
`k/(n+k)`, k swept and selected exactly as `ANYTIME_TD_SHRINKAGE_K` was, and
switch `pstdev` -> `stdev`. `scripts/backtest_nfl_props.py` and
`scripts/calibrate_nfl_anytime_td_shrinkage.py` are the templates.

**THE CONSTRAINT, and it is the model-engine standard's own rule:**
`_COVER_PROBABILITY_BLEND_WEIGHT` (`props.py:205`) is a FITTED table --
`passing_yards 0.689`, `rushing_attempts 0.550`, `receptions 0.137` -- calibrated
by `scripts/calibrate_nfl_cover_probability_blend.py` **on top of the current,
too-narrow sd**. Widening the sd changes the quantity those weights were fitted
to absorb, so the blend must be RE-FITTED in the same pass.
`docs/ai_context/model_engine_standard.md`: adding a mechanism to a calibrated
engine requires re-fitting the rates that were absorbing it, and two mechanisms
shipped together produced a NEGATIVE interaction in 4 of 4 markets.

Do not raise `_MODEL_EDGE_MAX_POINTS` to let these rows through in the meantime.
