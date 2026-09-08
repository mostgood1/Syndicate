# The home-field term — ADOPTED at 1.0169, from three agreeing real slates. The toy calibration (1.0096) was 5.3 sigma wrong and never shipped.

**2026-09-07, lane `mlb-live-segment-pricing`, session 3492626c.**
`GameConfig.home_field_offense_mult`, applied in `simulate.py`.
Calibrator: `scripts/calibrate_mlb_home_field.py`. Tests:
`tests/test_mlb_home_field.py`.

## What was missing

Measured over 1,015 games / 78 dates against MLB StatsAPI finals: the daily
sim's mean predicted home margin is **-0.186 runs** against an actual **+0.021**
— it under-rates the home team by ~0.21 runs on every game, entirely within
innings 1-5 (innings 6+ are unbiased at +0.010). `sim_engine` contained **no
home-field term at all**: the only home/away asymmetry was per-player
`venue_mult_home` / `venue_mult_away` splits, shrunk toward 1.0, plus the
batting-order effect. A league-wide advantage was being asked of noisy,
mean-reverting per-player splits, so on average it vanished.

## The term

`home_field_offense_mult`, default **1.0 — an exact no-op**, applied to
`hr_rate` and `inplay_hit_rate` at the existing batter-rate site, using the
`batting_roster is home` discriminator the venue splits already use.

Home is multiplied by `m` and away by `1/m`. Deliberately not `k_rate`/`bb_rate`,
which would move plate-appearance counts and therefore pitch counts, bullpen
entry timing, and every prop keyed off them — a much wider blast radius for the
same one-dimensional effect.

## Calibration (1,500 games/arm, common random numbers, paired differences)

| m | margin | d(margin) paired | d(total) paired |
|---|---|---|---|
| 1.000 | -0.5447 | — | — |
| 1.005 | -0.4740 | +0.0707 ± 0.0391 | **-0.0533 ± 0.0348** |
| 1.010 | -0.3280 | +0.2167 ± 0.0520 | **-0.0913 ± 0.0522** |
| 1.020 | -0.2373 | +0.3073 ± 0.0705 | **-0.1553 ± 0.0708** |

**Solved: `home_field_offense_mult ≈ 1.0097`** for the measured +0.207-run
deficit, by interpolating between the bracketing arms (the elasticity is convex,
so extrapolating a far arm understates it — the first cut did exactly that and
returned 1.0101 where the local answer is ~1.0097).

## THE TOTALS OBJECTION IS MUCH WEAKER THAN I FIRST REPORTED

**Superseding run: 6,000 games/arm, four times the power, arms spread wider.**

| m | d(margin) paired | elasticity | d(total) paired |
|---|---|---|---|
| 1.010 | — | +0.2158 ± 0.0279 runs/% (7.7σ) | **-0.0418 ± 0.0255** |
| 1.020 | — | +0.1878 ± 0.0181 runs/% (10.4σ) | **-0.0777 ± 0.0353** |
| 1.040 | — | +0.1725 ± 0.0123 runs/% (14.1σ) | **-0.0657 ± 0.0464** |

    SOLVED       home_field_offense_mult ~= 1.0096   (1,500-game run said 1.0097)
    TOTALS TREND -1.552 +/- 0.899 per unit multiplier   (1.7 sigma)
    PROJECTED    -0.0149 runs at the operating multiplier

**The margin calibration is confirmed** — 1.0096 against 1.0097, with the
elasticity now measured at 7.7-14.1 sigma instead of 4.2.

**The totals coupling is not.** At four times the power the trend falls from
**-7.596 ± 0.663 (11.5 sigma)** to **-1.552 ± 0.899 (1.7 sigma)**, and the
projected shift at the operating multiplier falls from **-0.073** to
**-0.0149 runs**. Against a full-game total bias of -0.120 that is a ~12%
worsening, not the ~58% the earlier figure implied.

### Why THIS run is the authoritative one, rather than merely the latest

The 11.5-sigma figure was a small-sample artifact and its failure mode was
visible before this run existed:

- The regression treated **(0, 0) as a zero-error point**. It is a definition,
  not a measurement.
- **The arms share a baseline**, so their errors are correlated; the residual
  standard error does not know that and reports a fit far tighter than the data
  earns.
- With four nearly-collinear points, near-collinearity IS the whole statistic.

**And it resolves the reading that disagreed.** The m=1.04 point, which came
back +0.0725 ± 0.137 over 400 games against a predicted -0.304, is
**-0.0657 ± 0.0464** at 6,000 games — negative, and *smaller in magnitude than
m=1.02*. So the relationship does not reverse and the 400-game reading was
noise; what is wrong is the assumption that the coupling grows LINEARLY. It
saturates. A trend line fitted through the origin was the wrong model, which is
why it over-projected at every point.

### What this means for the default

The totals cost at the operating multiplier is **-0.015 runs**, against a margin
gain of **+0.207** that closes a 2.1-sigma bias. That trade is defensible, where
the -0.073 figure was not.

**The default still stays 1.0, but the blocker has moved.** It is no longer the
totals coupling; it is that **every number in this table comes from synthetic
identical rosters.** The margin TARGET (+0.207) was measured on real games and
the ELASTICITY that converts it into a multiplier was measured on toy teams, and
mixing them assumes the engine responds the same way to both. Validating the
elasticity on a real slate is the remaining work, and it is a smaller job than
re-fitting totals would have been.

## THE TOY CALIBRATION DOES NOT TRANSFER — 1.0096 IS THE WRONG NUMBER

**Real slate 2026-07-20, 10 games, real probable pitchers, rosters as of that
date. 400 sims x 3 arms, same paired common-random-numbers scheme as the toy
calibrator so the only difference is the rosters.**

| m | real elasticity (runs/%) | toy | difference |
|---|---|---|---|
| 1.010 | **+0.1220 ± 0.0295** | +0.2158 | **-0.0938 (-3.18σ)** |
| 1.020 | **+0.1395 ± 0.0207** | +0.1878 | **-0.0483 (-2.33σ)** |

    SOLVED from the REAL elasticity:  1.0170
    SOLVED from the TOY  elasticity:  1.0096

**The multiplier a real slate needs is ~77% larger than the toy slate said.** At
the operating point the toy calibration overstates what a 1% multiplier buys by
about 43%, so adopting 1.0096 would deliver roughly **+0.117 runs** of the
+0.207 the model owes the home team — a bit over half the correction, and it
would have read as "done".

**The direction was predicted in advance and that is the only comfortable part.**
The harness's own docstring says real <= toy before the run: rates are
multiplied and then CLAMPED (`_clamp_rate(hr, 0.002, 0.12)`, inplay to
0.10-0.45), and a clamp that can never bind on a uniform toy lineup binds on a
real one's extremes — the slate carries `hr_rate` from 0.0000 to 0.0694 against
the toy roster's constant 0.035. A multiplier whose effect is partly clipped
delivers less margin per percent. Predicting the sign is not the same as knowing
the size, and the size is what decided this.

### The totals objection is now independently corroborated as small

Real slate, paired: d(total) **-0.0105 ± 0.0308** at m=1.010 and
**-0.0155 ± 0.0429** at m=1.020. Both consistent with zero, and both consistent
with the high-power synthetic estimate of ~-0.015 runs at the operating point.
Two independent measurements now agree that the totals coupling is small — the
11.5-sigma alarm was the artifact, and it stays retracted.

### ADOPTED 2026-09-08 at 1.0169 — three slates, and they agree

The single-slate number was not enough to turn on, so two more slates were run
and pooled with a heterogeneity check.

| slate | games | m=1.010 elasticity | m=1.020 |
|---|---|---|---|
| 2026-06-18 | 9 | +0.1111 ± 0.0320 | +0.1489 ± 0.0215 |
| 2026-07-20 | 10 | +0.1220 ± 0.0295 | +0.1395 ± 0.0207 |
| 2026-08-05 | 10 | +0.1332 ± 0.0294 | +0.1101 ± 0.0191 |
| **POOLED** | 29 | **+0.1227 ± 0.0175** | **+0.1312 ± 0.0118** |
| toy | — | +0.2158 (**−5.3σ**) | +0.1878 (**−4.8σ**) |

    SOLVED  home_field_offense_mult = 1.0169   (1 se: 1.0148 .. 1.0197)

**Cochran's Q is 0.3 on df=2** at the operating arm (2.1 on df=2 at m=1.020), so
the slates are measuring one constant and pooling is legitimate. That check was
put in *before* the run precisely because it could have failed: the elasticity
depends on how often the rate clamps bind, which depends on roster composition,
and June and August teams are not the same teams. Had Q come back large the
finding would have been that the multiplier is **not a constant** — a more
interesting result than a clean average, and one that would have blocked
adoption. It did not.

The pooled value lands at 1.0169 against the single 2026-07-20 slate's 1.0170 —
corroborated rather than merely repeated, since the other two slates moved it by
0.0001.

**Totals held on a third independent measurement.** Pooled across real slates:
**−0.0108 ± 0.0181 (0.6σ)** at m=1.010 and **−0.0262 ± 0.0242 (1.1σ)** at
m=1.020, agreeing with the high-power synthetic estimate of ~−0.015 runs. The
11.5σ alarm remains retracted as a small-sample artifact.

### What adoption does and does not do

- `GameConfig.home_field_offense_mult` now defaults to **1.0169**. Passing
  **1.0** explicitly still disables the term exactly, so anything needing the
  pre-adoption numbers (a backtest against historical output) can get them.
- The test that pinned the default as an exact no-op **now asserts the
  opposite**: that the default is the calibrated value AND that it actually
  reaches the simulation. Its failure on the flip was the test working.
- **This is a code change on `main`. It is not in production.** `autoDeploy` is
  off for `.py`, so the MLB sim keeps running the old behaviour until a deploy
  is taken — separately gated, and a deploy kills an in-flight sim.
- Expected effect once deployed: the home margin bias of −0.207 runs closes, and
  with it the calibration skew where ACTUAL sat above PREDICTED in every bin of
  every segment. Worth **~1.9 points of win probability**, applied the same way
  on every game.

## A second finding, unrelated to the term

**With identical rosters on both sides the engine gives the AWAY team
-0.5447 ± 0.1677 runs (3.25 sigma).** With equal teams the expected margin
should be the batting-order effect alone — the home side not batting in the
ninth when ahead, and walk-offs truncating the half-inning. Both are real, so
this is not automatically a defect, and it must **not** be read as "the missing
home advantage": the calibration target is the real-roster gap, not the distance
from this synthetic baseline to zero. Worth a separate look.

## FOUR positions I took on the totals question, each before the measurement

Kept in full because the pattern matters more than any one of them.

1. **A per-arm 3-sigma bar** waved a monotone drift through at 2.20 sigma —
   structurally blind to a trend.
2. **Unpaired standard errors** while every arm replays the same seeds, making a
   real elasticity look like noise (±0.17 against an effect of 0.22).
3. **Asserted the SIGN** on a 400-game sample whose paired error (~0.137) is
   twice the effect. It failed at +0.0725. The test was
   `test_the_coupling_is_downward`; its predecessor was
   `TestItDoesNotMoveTotals` and asserted the opposite. Both passed or failed
   for reasons unrelated to the truth.
4. **Reported the coupling as established at 11.5 sigma** off a trend line whose
   tightness came from four near-collinear points, a fixed origin, and
   correlated errors. Four times the sample put it at 1.7 sigma.

The through-line: every one of those was a statement about a quantity I had not
yet measured at adequate power, and in three of the four the *shape* of the
error was visible at the time — a threshold that could not see a trend, a
standard error that ignored pairing, a regression that trusted a definitional
point. The one thing that consistently worked was running it again with more
games.
