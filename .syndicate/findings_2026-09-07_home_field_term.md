# The home-field term, built and calibrated. Default 1.0, because turning it on moves TOTALS.

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

## WHY THE DEFAULT STAYS 1.0

**Totals may be coupled to this term, and that is enough to hold it.**

Look at the last column: -0.053, -0.091, -0.155, monotone in the multiplier —
each at 1.5-2.2 sigma. Three same-sign readings rising with the parameter is a
suggestive pattern.

**The TREND across arms settles what no single arm could:**

    d(total) per unit multiplier = -7.596 +/- 0.663   (11.5 sigma)
    projected at the solved m=1.0097:  -0.0734 runs

That is the right statistic here — each arm individually is 1.5-2.2 sigma, but
they are not independent tests of nothing, they are points on a line, and the
line is what the term does. A per-arm threshold could never see it, which is why
the check now regresses instead.

**ONE READING STILL DISAGREES, and it is recorded rather than dropped.** At
m=1.04 over 400 games the paired shift came back **+0.0725 +/- 0.137** — the
other direction. The trend predicts -0.304 there, so the two differ by ~2.7
sigma. That is more than low power: either the arms' shared baseline makes their
near-collinearity flatter than it deserves (their errors are correlated, which
the regression's residual standard error does not know), or the relationship
reverses above m=1.02.

It does not change the decision, because m=1.04 is four times the operating
multiplier and nobody would run there. But it is not explained, and a claim that
the coupling is linear all the way up is not supported. A 6,000-game run at the
OPERATING point is what the decision rests on.

What holds the default at 1.0:

- Today's full-game total bias is **-0.120 runs**. The projected **-0.073** at
  the operating multiplier takes it to **~-0.19** — the term fixes the margin
  and breaks the total, trading a 2.1-sigma margin bias for a larger totals one.
- Totals are a **separately priced market**. A margin fix that silently pays for
  itself out of totals is exactly the interaction
  `model_engine_standard.md` warns about, having measured two mechanisms landing
  together and producing a NEGATIVE result in 4 of 4 markets.

A plausible mechanism if the coupling is real, offered as hypothesis and not as
measured cause: boosting the home side makes it lead more often, so the bottom
of the ninth is skipped more often and total runs fall. That would be real
baseball rather than an implementation bug, and would explain why the symmetric
application reduces the coupling without removing it.

The term is built, calibrated, tested and **off**. What it needs before adoption
is the high-power totals reading, and — if the coupling is confirmed — a paired
adjustment that restores the total. That is a fit, not a flag flip.

## A second finding, unrelated to the term

**With identical rosters on both sides the engine gives the AWAY team
-0.5447 ± 0.1677 runs (3.25 sigma).** With equal teams the expected margin
should be the batting-order effect alone — the home side not batting in the
ninth when ahead, and walk-offs truncating the half-inning. Both are real, so
this is not automatically a defect, and it must **not** be read as "the missing
home advantage": the calibration target is the real-roster gap, not the distance
from this synthetic baseline to zero. Worth a separate look.

## Three guards of my own that were wrong, in both directions

Recorded because each passed or failed while the thing it guarded was
mis-stated.

1. **The totals check used a per-arm 3-sigma bar** and waved through a monotone
   drift at 2.20 sigma. A guard encoding an assumption about HOW something fails
   is silent in the real failure mode. Now regresses d(total) on the multiplier
   and tests the SLOPE plus sign consistency.
2. **The elasticity used unpaired standard errors** while every arm replays the
   same seeds. Each arm's margin carried +/-0.17 against an effect of 0.22,
   making a real 4.2-sigma elasticity look like noise. Pairing removes the
   shared randomness.
3. **Then I overcorrected TWICE.** Having found the monotone drift I wrote
   `test_the_coupling_is_downward`, asserting a SIGN on a 400-game sample whose
   paired standard error (~0.137) is twice the effect. It failed at +0.0725.
   Asserting a direction the sample cannot resolve is the same error as the lax
   threshold it replaced, pointed the other way. Replaced with a BOUND, which
   400 games can resolve; the sign question belongs to the calibrator at full
   power.

And having seen the sign test fail, I briefly wrote the coupling down as unproven — before running the trend statistic that establishes it at 11.5 sigma. Three positions in one session, each stated before the measurement that decides it.

The first version of `TestTheTotalsCoupling` was called
`TestItDoesNotMoveTotals` and asserted the opposite of what the calibrator
suggested. It passed. The second asserted the calibrator's direction as fact.
It failed. The measurement that decides between them had not been run when
either was written.
