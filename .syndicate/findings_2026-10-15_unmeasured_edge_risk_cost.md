# The `unmeasured → 1.0` default costs ~nothing. The real asymmetry: the board can PENALISE measured badness and cannot REWARD measured goodness

`[2026-10-15 19:0x–19:2xZ, session 4ab694ed, lane unmeasured-edge-risk-cost, taking the open residual of the 72.7% lead]`

## The question

The 72.7% lead's own correction left one thing open as a risk question rather
than a defect: `skill_reliability` returns **1.0** for any note whose status is
not `measured` — deliberately, *"Unknown must not be punished with an invented
midpoint any more than it may be rewarded with one."* On the served board that
covers **1,175 rows (37.4%)**, including **nba 32/32** and **nhl 174/183**
entirely. Does that default cost anything?

A bucket is `insufficient` because it is individually below the grading
threshold, so no single one can answer this. **Pooled they can.**

## 1. Pooled, the unmeasured population is NOT materially worse — hypothesis confirmed

Model scorecard `20261015`, 28d window, 351 cells. Sign convention read from the
data, not assumed: `brier_diff == model_brier - market_brier`, verified on a real
cell (`0.070954 - 0.075288 = -0.004334`, matching its own `brier_diff`), so
**negative = model beats market**. Games-weighted:

| verdict | cells | graded games | model Brier | market Brier | weighted `brier_diff` |
|---|---|---|---|---|---|
| insufficient | 276 | 896 | 0.236933 | 0.230033 | **+0.006900** |
| parity | 64 | 3,843 | 0.214353 | 0.210072 | **+0.004281** |
| loses_to_market | 9 | 676 | 0.225726 | 0.205462 | **+0.020263** |
| beats_market | 2 | 159 | 0.069486 | 0.073700 | **−0.004214** |

| pooled | cells | games | `brier_diff` |
|---|---|---|---|
| **INSUFFICIENT** (the 1.0-by-default population) | 276 | **896** | **+0.006900** |
| **MEASURED** (parity + loses + beats) | 75 | **4,678** | **+0.006301** |

**Gap: +0.000599.** The unmeasured population is 0.0006 Brier worse than the
measured one, over 896 and 4,678 graded games respectively — neither a thin
frame. **So the `unknown → 1.0` default is not mis-ranking anything:** unmeasured
rows are not meaningfully worse than the measured rows they rank beside.

## 2. And the reason is worse than the question assumed

**Every verdict class except `beats_market` is positive — the market is better.**
`parity` is **+0.004281**, which is a CI spanning zero, *not* a model matching
the market. Only **2 of 351** cells (159 of 6,093 graded games) beat the market.

So the 72.7% headline **understates** it. The lead said 72.7% of ranking model
edges come from a model that loses or was never backtested. On Brier, the
*measured* ones have no edge either: pooled measured is **+0.0063**, essentially
the same as pooled unmeasured. The population does not split into good and
unknown — it splits into bad and unmeasured-but-equally-bad.

## 3. The 14 `beats_market` buckets, and why ZERO served rows say so

The scorecard headline reads `beats_market: 14` of `tested: 3878`, while the 28d
and 7d windows expose only **2 each** (the same markets in both). The 14 are in
`measured_bucket_skill_overlay.json` — **the file the board actually reads** —
under a different name: its vocabulary is `skill_loss` (29) and
**`skill_pocket` (14)**, with `beats_market` appearing zero times. `validated=43`
= 29 + 14. So the headline and the overlay agree; only the word differs.

**All 14 pockets are soccer, pregame, full-game**, across four markets sliced by
conditioning dimension (66–88 games each, every CI excluding zero):

| bucket | games | `brier_diff` | `established_loss_rel` |
|---|---|---|---|
| `soccer|player_shots_on_target|full|pregame|price=long` | 85 | −0.005581 | **None** |
| `soccer|player_assists|full|pregame|quote_age=aging` | 66 | −0.005572 | **None** |
| `soccer|player_shots|full|pregame|price=long` | 88 | −0.004835 | **None** |
| `soccer|player_last_goal_scorer|full|pregame|…` | 79, 73 | −0.004010, −0.001413 | **None** |
| …and 9 more `player_shots_on_target` / `player_assists` slices | 73–85 | −0.0041 to −0.0046 | **None** |

And on the served board, those exact markets:

- **`player_shots_on_target`: 416 rows**, `status=measured`, `class=parity`,
  verdict *"at the price: no established loss, ROI on model EV>0 −7.1%
  [−41.3%, +31.1%] over 210 bets, 143 matches"* → factor **1.0**.
- **`player_assists`: 129 rows**, `status=unmeasured`, verdict *"model never
  backtested — projection is unvalidated"* → factor **1.0**.

**So 14-vs-0 resolves two different ways, one per market, and both candidate
explanations were right:**

1. **`player_assists` is a genuine propagation gap.** The scorecard validated it
   as a skill pocket on 74 games with a CI excluding zero, and **129 served rows
   say the model was never backtested.** The board is carrying "unvalidated" for
   a bucket its own nightly grader validated.
2. **`player_shots_on_target` is two instruments.** Brier says pocket; the served
   verdict is ROI-at-the-price and reads parity. Both are true statements about
   different metrics, and neither is wrong.

## 4. THE FINDING: a pocket earns nothing

`established_loss_rel` is **`None` on all 14 pockets**, and the union of fields a
pocket carries is `brier_diff, ci95, dates, established_loss_rel, games,
market_brier, verdict` — **there is no reward field at all.**

`skill_reliability` computes `max(SKILL_FLOOR, 1.0 - SKILL_GAIN * loss)` from
`established_loss_rel`, and returns **1.0** when it is absent. The daily
optimizer's overlay factor is recorded in `state_model.md` as `[0.5, 1.0]` and
"never withholds" — also capped at 1.0.

> **So a bucket measured to BEAT the market, on 85 games with a CI excluding
> zero, ranks identically to a model that was never backtested. The system can
> down-weight measured badness and has no mechanism to up-weight measured
> goodness.**

That is the real content of the 72.7% lead, and it is the opposite of a penalty
problem. The four soccer pregame prop markets that demonstrably beat the market —
the only four in the whole graded population — receive no ranking advantage for
it.

## What this means, stated as decisions for a human

1. **Do not change the `unknown → 1.0` default.** It costs 0.0006 Brier against
   the measured population. The docstring's reasoning holds and the number now
   backs it.
2. **The `player_assists` propagation gap is a real, small, fixable defect.** 129
   served rows carry "never backtested" for a bucket validated by the nightly
   grader. Worth tracing from the overlay to the row's `model_skill`.
3. **A reward path is a modelling/risk decision, not a bug.** Rewarding a pocket
   means letting a 66–88-game result raise a row's rank, and the repo has already
   paid for over-trusting thin samples. The honest framing is that the asymmetry
   is currently *deliberate by omission* — nobody decided pockets earn nothing;
   there is simply no field for it.
4. **Stop quoting "72.7% from models with no demonstrated edge" as if the other
   27% have one.** Pooled measured is +0.0063 Brier — worse than the market.
   Only 2 cells of 351 are negative.

## Method note

Every figure is read from the fleet's own published scorecard and overlay, at
`nice -n 19`. The sign convention was verified against a real cell rather than
assumed. Pooling is games-weighted and both denominators are stated. The 14 was
reconciled to the overlay's `skill_pocket` rather than left as an unexplained
discrepancy with the windows' 2. The served-row join used the row cap defeated
(`1,407 == total_rows`). `layer2_board.py` was NOT touched — it is held by four
other lanes — and nothing in this lane changes code.
