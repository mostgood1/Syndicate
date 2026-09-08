# NFL: the units hypothesis is FALSIFIED, and a market sign was inverted

`[lane nfl-rating-units, session 520cd594, 2026-09-07]`

Two results. The second was not what this lane set out to find and is the more
consequential of the pair.

## 1. THE UNITS HYPOTHESIS IS WRONG. The defect is the SCALE constant.

This lane opened on a hypothesis, written before testing, that NFL's projections
are undifferentiated **because** `_mean_epa` rates teams per PLAY where a margin
model needs points per GAME -- a diagnosis this repo had already made for NCAAF
and abandoned PPA over.

**That is not the cause.** Per-play and per-game differentials are the same
signal:

| | 2024 | 2025 |
|---|---|---|
| Pearson r between the two differentials | **0.99689** | **0.99668** |
| SD ratio (per-game / per-play) | 60.40 | 60.26 |

The conversion divides by games instead of plays, and plays-per-game barely
varies across teams, so it is **a linear rescaling that carries no new
information**. Head to head on held-out 2025, each with its own fitted
coefficient, they are indistinguishable:

| held-out 2025 | per-game | per-play | market | flat |
|---|---|---|---|---|
| MAE | 10.58 | 10.60 | **9.79** | 11.02 |
| RMSE | 13.41 | 13.48 | **12.34** | -- |
| straight-up | 60.2% | 60.6% | **64.2%** | -- |
| predicted margin SD | 5.16 | 5.11 | 6.13 | -- |

This is exactly the falsification the lane wrote down in advance: *"the flatness
comes from somewhere else."* It does. **`NFL_RATING_SCALE = 10.0` is simply the
wrong constant for the units it is applied to** -- the flatness (`margin_mean`
stdev 2.16, 93.8% of games inside P(home) 0.35-0.65) is a scale error, not a
denominator error.

### The scale, derived out-of-sample rather than fitted to a target

Walk-forward: a week-`w` game rates both teams only from plays strictly before
week `w`, prior season entire for weeks 1-2. No game contributes to its own
rating. OLS of ACTUAL MARGIN on the rating differential, fitted on train seasons
and scored on a season the fit never saw.

    fit [2023]       -> test 2024:  b=+0.322   predicted SD 4.28
    fit [2024]       -> test 2025:  b=+0.493   predicted SD 6.30
    fit [2023, 2024] -> test 2025:  b=+0.404   predicted SD 5.16

Mapping the pooled slope through the lane's own anchor (margin SD 11.44 at
`NFL_RATING_SCALE=10` with per-game ratings) gives an engine constant of 8.441
and therefore **`NFL_RATING_SCALE` ~ 20.9**, assuming `margin_mean` is linear in
the differential.

**This independently lands on the ~20 the docstring identified and deliberately
refused to use**, and that matters: it refused because 20 had been chosen to make
output SD match the market's 5.69, which is fitting to a target. An OLS against
realised margins, scored out-of-sample, is a different basis and reaches the same
place. The objection is answered.

**The slope is NOT precisely determined** -- 0.322 to 0.493 across splits, ~+/-20%.
Report ~20, not 20.9.

### What this does NOT license

The model beats a flat baseline (10.58 vs 11.02) and **loses to the close**
(10.58 vs 9.79; 60.2% vs 64.2% straight up). That reproduces
`findings_2026-09-06_refusal_audit.md`'s independent `test MAE 10.495 vs market
9.722, t = +3.34` closely enough to count as confirmation from a second
implementation.

So the correct scale makes the board COHERENT -- it stops presenting 93.8% of
games as coin flips, which is a false display -- and does **not** make the model
fit to price against the market. Those are separate decisions and the second one
is still NO.

## 2. `market_margin` was INVERTED for every NFL regular-season game

Found while building the backtest above, from a reading that could not be true:
the market appeared to pick winners **34.7%** of the time.

**Mechanism.** `schedule_{season}.csv` is written by `fetch_nfl_schedule.py`,
which copies nflverse `games.csv` VERBATIM. nflverse's `spread_line` is already
**home-margin-positive** (a home favourite is `+8.5`; verified on DAL @ PHI,
`spread_line=8.5`, PHI won by 4). `backfill_nfl_performance.load_completed_games`
negated it.

**Measured by running the repo's own function over real 2025 results:**

    market_margin agrees with the actual winner   34.7%   (n=271)
    the market's true rate on the same games      65.3%   (MAE 9.72)
    after the fix                                 65.3%

Almost exactly one-minus the truth, which is the signature of a sign error rather
than a weak signal.

**WHY IT SURVIVED, and this is the transferable part.** The comment justifying
the negation cited two SIBLING call sites -- the preseason branch in the same
function, and `backfill_smartsim2_performance.py` -- and both of those are
CORRECT, because they negate a SPORTSBOOK spread, which genuinely is bet
notation. Two sources, two conventions, one negation applied to both. **Check the
SOURCE's convention, never a sibling call site's.**

A test asserted the wrong value and passed: `test_reads_completed_game_with_negated_market_margin`
encoded the same misreading as the code. A second test carried it too. Both
corrected, plus a sign-only property probe so a future half-fix cannot pass.

**Blast radius:** NFL REGULAR-SEASON performance records only. Preseason is
unaffected (line ~243 overrides with the sportsbook value). The
`t=+3.34` model-vs-market conclusion is NOT affected -- that came from the
refusal audit's own path, and its market MAE of 9.722 is the correct-orientation
number, which my 9.79 independently reproduces.

## Evidence

- pbp: nflverse 2022-2025, fetched via `scripts/fetch_nfl_pbp.py`
  (46,452 / 47,274 REG plays for 2025 / 2024).
- Outcomes and closing lines: nflverse `games.csv`, 272 REG games per season.
- Backtest harness: `scripts/backtest_nfl_rating_units.py`.
