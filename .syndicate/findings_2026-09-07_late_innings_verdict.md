# The late-inning margin model is NOT broken. The defect is a missing home-field advantage.

**2026-09-07, lane `mlb-live-segment-pricing`, session 3492626c.**
n=1,015 games / 78 dates (2026-05-28..08-17). Follows
`findings_2026-09-07_full_game_discrimination.md`, which flagged the innings-6+
margin (corr +0.059) as the weakest link and the thing to fix.

**It is not the thing to fix.** Four tests, each of which could have come back
the other way, say the late component is calibrated and operating near the
ceiling of what innings 6+ allow.

## Test 1 — it is unbiased

| home margin | predicted mean | actual mean | bias |
|---|---|---|---|
| innings 1-5 | +0.049 | +0.266 | **-0.217 (-2.1 sigma)** |
| innings 6+ | -0.235 | -0.245 | **+0.010 (+0.1 sigma)** |

The late component's mean is right to within a hundredth of a run. **The bias is
entirely in the FIRST FIVE innings** — the opposite of where the previous
finding pointed.

## Test 2 — its dispersion is earned, and shrinking it gains nothing

Fitting the optimal linear slope on the first half of dates and applying it to
the second: early slope **+0.666**, late slope **+0.963**. A slope near 1.0
means the model's stated late spread is very nearly what it earns — there is no
over-confidence to shrink away.

Out of sample, correlation with the actual full-game margin:

    as published            +0.1290
    shrink LATE only        +0.1298      (se ~0.0446 -- no gain)
    shrink BOTH components  +0.1194      (worse)

## Test 3 — month-to-month variation is noise, not a collapse

| month | n | corr early | corr late |
|---|---|---|---|
| 2026-06 | 395 | +0.083 | +0.107 |
| 2026-07 | 370 | +0.120 | +0.099 |
| 2026-08 | 199 | +0.319 | +0.003 |

August's late reading looks like a collapse and is not one: the gap against
June/July is ~1.15 sigma on combined standard errors. Reported so nobody else
chases it.

## Test 4 — team differentiation works, and the ceiling is low

Per-team late-inning margin, signed from each team's own perspective, 30 teams
at ~68 games each:

- **corr(model team effect, actual team effect) = +0.6725** (se ~0.183, 3.7
  sigma). The bullpen modelling captures which teams are good late.
- Model spread across teams **0.1521** against an observed **0.4249** — but the
  observed figure is mostly sampling noise. Expected sd if all teams were
  identical is **0.3633**, so the TRUE team effect is
  `sqrt(0.4249^2 - 0.3633^2) = 0.220` runs. The model expresses **69%** of it.

**That last number sets the ceiling.** A true team-effect sd of 0.220 against a
game-level late-margin sd of 3.009 implies a maximum achievable correlation of
about **0.073** from team quality alone. The model achieves **0.059** — roughly
80% of what is there.

Innings 6+ are close to unpredictable in principle. That is why the late
correlation is a third of the early one, and it is not a defect that better
bullpen modelling would repay much.

## The defect that IS there, and its size

The model's mean predicted full-game home margin is **-0.186** runs against an
actual **+0.021** — it under-rates the home team by **~0.21 runs**, and the
whole of that sits in innings 1-5.

**`sim_engine` contains no home-field advantage term.** No `hfa`, no
`home_field`, no `home_advantage` anywhere in the package. The only home/away
asymmetry is per-player `venue_mult_home` / `venue_mult_away` splits (noisy and
shrunk toward 1.0 by `pitcher_home_away_alpha`) plus the structural batting-order
effect of the home team not batting in the ninth when ahead.

At an MLB full-game margin sd near 4.5, 0.21 runs is worth roughly **1.9 points
of win probability**, applied in the same direction on every game — home
under-priced, away over-priced. That is the shape of a systematic edge leak, and
unlike the late-inning correlation it has no ceiling problem: it is a bias, and
biases are correctable.

It also explains the calibration tables directly, where actual sat above
predicted in **every** bin for every segment.

## What to do

1. **Add an explicit home-field term**, default OFF behind a flag, sized against
   this measurement and evaluated out of sample.
2. **It is a MECHANISM added to a calibrated engine**, so
   `docs/ai_context/model_engine_standard.md` applies: the rates currently
   absorbing the missing advantage have to be re-fitted, or the totals
   calibration moves with the margin. Two mechanisms landed together once before
   and produced a NEGATIVE interaction in 4 of 4 markets.
3. Do **not** spend further effort on innings 6+ margin accuracy. It is at ~80%
   of a ceiling of ~0.073.
