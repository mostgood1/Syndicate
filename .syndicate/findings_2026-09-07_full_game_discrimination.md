# The full-game model DOES discriminate. It is beaten by the market, and its signal is concentrated in the first five innings.

**2026-09-07, lane `mlb-live-segment-pricing`, session 3492626c.**
Scripts: `scripts/diagnose_mlb_full_game_discrimination.py`,
`scripts/diagnose_mlb_late_innings.py`.
n=1,015 games / 78 dates (2026-05-28..08-17); market tests n=174 / 16 dates.

## FIRST, A CORRECTION I OWE

I reported that the full-game model "shows no discrimination on 501 games
(0.88 sigma)". **That was the out-of-sample TEST HALF only.** Over the full
1,015-game sample the full-game number separates its terciles by **+0.1124 at
+2.94 sigma**. It discriminates. The claim was drawn from half the data and does
not survive the whole of it, and "no discrimination" was too strong either way.

What survives is the *comparison*: first5 sorts its own outcome at **+4.26
sigma** where full sorts its own at **+2.94**, and the market sorts the
full-game outcome far better than either.

## The deficit is against the MARKET, and it is large

Same 174 games, same outcome:

| | tercile separation | sigma | Brier |
|---|---|---|---|
| **market** | **+0.3103** | **3.52** | **0.22970** |
| model, full-game | +0.1552 | 1.69 | 0.24728 |
| model, first5 applied to the full outcome | +0.1552 | 1.69 | — |

**The market sorts these games about twice as well as the model does.** That is
the finding that matters: full-game MLB moneyline is clearly predictable — the
book demonstrates it on the same games — so the weak sorting is a model deficit
and not market efficiency or an unpredictable sport.

Head to head on price, though, neither wins: model Brier 0.24773 against market
0.24504 over 139 games, and betting the model's disagreement gives +0.18 sigma
(edge>=2%, n=117) and +1.26 sigma (edge>=5%, n=75). No edge demonstrated in
either direction. **Rests on 13 dates and one book per game.**

## Compression is NOT the cause

| | mean | sd | p10 | p90 |
|---|---|---|---|---|
| full | 0.5025 | 0.0888 | 0.397 | 0.611 |
| first5 | 0.5065 | 0.0931 | 0.394 | 0.617 |

The two spread their predictions almost identically. The full-game number is not
packed near 0.50; its predictions simply track outcomes less well.

Worth noting as an open oddity: over nine innings a fixed per-inning edge should
push the win probability FURTHER from 0.50 than over five, yet `full` is very
slightly *less* dispersed than `first5`. Not investigated here.

## Where the signal actually is

Predicted vs actual, decomposed by splitting each game at the fifth inning
(`full` minus `first5` is the model's own implicit forecast for innings 6+):

| quantity | bias | MAE | **corr(pred, actual)** |
|---|---|---|---|
| total runs, innings 1-5 | -0.043 | 2.665 | +0.081 |
| total runs, innings 6+ | -0.077 | 2.390 | +0.075 |
| **home margin, innings 1-5** | **-0.217 (-2.1s)** | 2.549 | **+0.156** |
| **home margin, innings 6+** | +0.010 | 2.205 | **+0.059** |

The margin is what a moneyline turns on, and the model forecasts the first five
innings of it **2.6x better** than the last four (corr +0.156 against +0.059).
The full-game number is the sum of a decent forecast and a weak one, so it is
diluted by construction.

Two supporting numbers:

- Innings 6+ **reverse the leader in 150 of 857 games (17.5%)**. That is the
  ceiling on how much the late component can decide.
- **A systematic home under-prediction in the first five**: margin bias
  **-0.217 runs at -2.1 sigma**, consistent with the calibration tables where
  actual sat above predicted in every bin.

## A HYPOTHESIS I FORMED AND THEN REFUTED

On 371 games where `p_full` and `p_first5` differ by >=3pp, the side `full`
leans toward wins only 44.2% of the time (-2.23 sigma), which reads as the
nine-inning extrapolation ACTIVELY SUBTRACTING from the five-inning signal.

**The direct test says otherwise and wins.** Scoring the model's late-margin
forecast against the actual innings-6+ margin, it leans the right way in
**517 of 913 games = 56.6%, +4.00 sigma**. The late component is weakly
informative, not anti-informative.

The disagreement test was comparing two probabilities about **different
horizons** — P(home wins 5 innings) against P(home wins 9) — which are not on a
common scale, so their difference does not isolate the late component. The
decomposition above does. Recorded because the wrong version was the more
quotable one.

## What to do next

1. **The late-inning margin model is the weakest link with the clearest
   direction** (corr +0.059 against +0.156 early). It decides 17.5% of games.
   Bullpen usage and late-game leverage are the obvious suspects; neither is
   tested here.
2. **The first-five home bias (-0.217 runs) is a correctable calibration
   error**, and it is in the segment the engine already models best.
3. **Get more market history before any of this is judged on edge.** Every
   model-vs-market number here rests on 13-16 dates and one book per game.
