# MLB current engine vs the de-vigged book, OUT OF SAMPLE (07-16..09-27) `[2026-10-09, lane mlb-oos-market-backtest, NO DEPLOY]`

## Method

- **Script.** `scripts/backtest_mlb_lines_props.py`, unchanged (the 10-02 method: game-clustered paired CIs, NHL verdict rule).
- **Coverage.** All five families cover the same 74 dates (07-16..09-27). Intersection: game lines 74, props 74. Regular season only.

### Odds

- **Source.** OddsAPI historical, one pregame instant per game (first pitch - 10 min).
- **Markets (19).**
  - Full-game and F5: ML, run line, total.
  - F3 and F1: totals.
  - Props: 6 hitter, 5 pitcher.
- **Assembly.** Written in the live fetcher's own shape: its assembly code, with the HTTP seams swapped.
- **Spend.** 186,984 credits (user OK under 200k). Scratch only: `C:/tmp/mlb_hist_odds`.

### Sims

- **Pipeline.** Production's `_sim_many`, 500 sims/game, over the StatsAPI as-of rebuild: 985 games, lineup projection B, as-of stats.
- **Config.** Game-profile `cfg_kwargs` and calibration maps read from production's 10-08 `meta.json`.
- **Arms.**
  - **fwd** = production from 988fa33d (forward pitch file).
  - **none** = the game profile before it (class defaults).
- **Deliberate omission.** `apply_conditional_mix_to_rosters` is not applied: it uses a season-level table, which would leak.

### Not measurable

- **batter_home_runs.** Every historical quote is one-sided (Over 0.5 only, 1,423 of 1,436 sampled), so it can't be de-vigged.
- **F1/F3 moneylines.** Not fetched (not in the 19 markets).

## Headline

**The current engine beats the de-vigged book in 0 of 18 markets with book rows. It is at parity in 3 (F1 total, F3 total, pitcher walks) and significantly worse in 15.** This is the same verdict as the 10-02 in-window run, now out of sample and on the current config.

## The 10-09 game-profile fix vs the book (dBrier model-book; lower is better)

| market | before (none) | now (fwd) |
|---|---|---|
| full total | +0.0163 | **+0.0118** |
| full moneyline | +0.0114 | +0.0097 |
| full run line | +0.0077 | +0.0071 |
| F5 total | +0.0129 | +0.0110 |
| F5 ML / F5 run line | +0.0123 / +0.0103 | +0.0132 / +0.0120 |
| F3 total | +0.0055 | +0.0036 |
| runs scored (prop) | +0.0066 | +0.0037 |
| RBI | +0.0034 | +0.0024 |
| hits / TB / H+R+RBI | +0.0053 / +0.0057 / +0.0058 | +0.0055 / +0.0055 / +0.0052 |
| pitcher K | +0.0292 | +0.0305 |
| pitcher outs | +0.0629 | **+0.0493** |
| pitcher ER / H allowed | +0.0099 / +0.0139 | +0.0110 / +0.0127 |
| pitcher walks | +0.0068 (WORSE) | **+0.0010 (PARITY)** |

The fix narrowed the gap in 11 of 18 markets and widened it slightly in 5: F5 ML, F5 run line, K, ER, hits. The largest gains are in totals, outs, walks and runs-scored props.

## WHY (fwd arm): the remaining loss is calibration, not information

The Brier split puts almost the whole gap in **reliability**. The model's probabilities are far more spread than the outcomes justify:

| market | slope model / book | sd p model / book | reliability model / book | resolution model / book |
|---|---|---|---|---|
| full total | **0.059** / 0.778 | 0.107 / 0.019 | 0.0126 / 0.0002 | 0.0013 / 0.0009 |
| full ML | 0.512 / 1.164 | 0.113 / 0.086 | 0.0055 / 0.0014 | 0.0059 / 0.0090 |
| F5 total | 0.066 / 0.411 | 0.106 / 0.027 | 0.0133 / 0.0005 | 0.0023 / 0.0000 |
| pitcher outs | 0.107 / 1.102 | 0.202 / 0.063 | **0.0445** / 0.0004 | 0.0012 / 0.0036 |
| pitcher K | 0.107 / 1.288 | 0.176 / 0.063 | 0.0238 / 0.0009 | 0.0008 / 0.0066 |
| batter hits | 0.703 / 1.136 | 0.136 / 0.101 | 0.0023 / 0.0003 | 0.0094 / 0.0126 |

- **Full-game totals.** The model's over-probability varies with sd 0.107 where the book's varies 0.019. Its slope on outcomes is 0.06: the variation is almost pure noise. The total-runs resolution is already above the book's (0.0013 vs 0.0009).
- **Pitcher outs.**
  - The model's mean p(over) is 0.398 against an outcome rate of 0.510.
  - The sim's outs distribution is too narrow: dispersion 0.70.
  - The model mean ranks starts worse than the pitcher's own history (corr 0.095 vs 0.371).
  - This is the 10-02 "starter length" defect, smaller (point bias -0.38, was +4.75) but still the largest single gap.
- **Hitter props** are closest to the book (gap ~0.002-0.006). Their resolution is near the book's.

## Implications (not acted on)

1. **Calibration.** A per-market calibration layer (shrink the probability toward 0.5 or toward the book, or a fitted slope) attacks exactly the reliability term. That term is the bulk of the gap in totals, F5 and the pitcher markets. This is what the daily-optimizer's w* measures. It needs a fit window disjoint from this one: no clean 2026 regular season remains, so fit on 07-16..08-21 and judge on 08-22..09-27, disclosed.
2. **Pitcher outs/K.** Narrow distribution plus poor ranking. Starter length still drives both pitcher markets.

## Caveats

- **Lineups.** Projected (B, 0.846 overlap with the actual nine); the book saw actual lineups for late quotes.
- **Season-level pitch-mix table.** Omitted; production applies it.
- **Sample size.** 500 sims/game adds a little Monte Carlo noise to p, which slightly inflates the model's spread. It cannot produce a slope of 0.06.
