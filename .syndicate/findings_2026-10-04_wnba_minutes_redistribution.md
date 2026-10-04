# FINDINGS — WNBA minutes re-share: the diagnosis holds, the fix is REFUTED for props

**Lane** `wnba-minutes-redistribution`, session `39b666bb`. **Date** 2026-10-04. **Measurement only**; the estimator is
on main (`wnba_sim_minutes_redistribution.py`, flag `SYNDICATE_WNBA_SIM_MINUTES_REDISTRIBUTION`, default OFF) and is
**not hooked into the engine**. Recommendation: do not hook it.

## Data

- Oracle-availability re-run (pool = exactly who played), now the full season: **2026-05-08..10-01, 116 slate dates,
  340 games**, 0 errors. May–Jul part run today (74 dates, 216 games). Archive `~/wnba_bt/oracle`.
- Fit: **May–Jul, 377 regulation team-games** (OT skipped). Test: **Aug–Oct, 227 team-games, 42 dates**.
- Props scoring: paired rows (same game × player × market, both arms priced it, the player played, two-sided book
  line), oracle arm 7,528 rows and real-rule (stack) arm 7,292, over 114 regular-season + 9 playoff games. Book =
  OddsAPI historical, tip −60.

## 1. Diagnosis (holds)

`scripts/diagnose_wnba_minutes_redistribution.py` on the oracle arm, Aug–Oct. On days with ≥15 late-out teammate
minutes (79 team-games), actual − sim minutes by rank in sim minutes:
- **ranks 1–5: −1.73 [−2.54, −0.88]**
- ranks 6–8: +1.25 [+0.54, +1.94]
- ranks 9+: +1.55 [+0.28, +2.91]

Players averaging under 10 min gain +3.81 in reality vs +1.14 in the sim; 20–30-min players gain +0.06 vs +1.07.
With no late outs the top five are still −1.20 [−1.94, −0.47]. About 2.5 min per team-game go to players outside the
pool.

## 2. The fit

β = clip(b0 + b1·min(freed, 40)/40, 0, 0.6) flattens the pool toward its mean; `leak` minutes are left for players
outside the pool. **b0 −0.2, b1 0.45, leak 4.0**, interior after widening the b0 grid to −0.6, so there is no
flattening until about 18 freed minutes. Train minutes SSE 134,367 → 131,300.

Held-out minutes (all pool players):

| cell | n | bias (actual − sim) current → new | MAE Δ (new − current) |
|---|---|---|---|
| all | 2,246 | −0.23 → +0.17 [+0.10, +0.24] | +0.002 [−0.063, +0.066] |
| freed ≥15, ranks 1–5 | 430 | **−1.61 → −0.21** | −0.038 [−0.260, +0.212] |
| freed ≥15, ranks 6–8 | 258 | +1.07 → +0.72 | **−0.120 [−0.238, −0.012]** |
| freed ≥15, ranks 9+ | 139 | +1.38 → +0.16 | +0.214 [−0.068, +0.485] |

It fixes the tier biases, but minutes MAE does not move. Each player carries about 5 minutes of noise, and the
re-share is a small fraction of that.

## 3. Props: worse (the decisive test)

Brier, redistributed − current, regular season (negative = better):

| market | oracle arm | real-rule (stack) arm |
|---|---|---|
| points | +0.0014 [−0.0012, +0.0040] | **+0.0019 [+0.0009, +0.0029]** |
| rebounds | +0.0015 [−0.0008, +0.0036] | **+0.0011 [+0.0004, +0.0019]** |
| assists | **+0.0031 [+0.0006, +0.0057]** | **+0.0006 [+0.0001, +0.0013]** |
| threes | +0.0002 [−0.0003, +0.0009] | +0.0000 |
| PRA | **+0.0073 [+0.0027, +0.0117]** | **+0.0088 [+0.0059, +0.0118]** |
| PR | **+0.0044 [+0.0010, +0.0080]** | **+0.0066 [+0.0046, +0.0087]** |
| PA | **+0.0072 [+0.0032, +0.0116]** | **+0.0076 [+0.0054, +0.0098]** |
| RA | +0.0035 [−0.0008, +0.0080] | **+0.0033 [+0.0016, +0.0052]** |

On priced rows (the regulars), mean prop bias moves the wrong way in both arms. Oracle-arm points −0.05 → −0.45 and
PRA −0.23 → −0.95; stack-arm points −0.21 → −0.46. The late-out minutes surprise on priced rows (the lane goal's
measure) goes from **−0.57 to +0.86**: it overshoots the other way. The book-information slope is unchanged
(points 0.73 → 0.71).

**Lane goal: NOT MET on all three counts** — minutes surprise not within ±0.2 (+0.86), points/PRA bias not within
±0.2, and Brier is worse on several markets.

## 4. Why: minutes are not interchangeable

The re-share moves minutes correctly but prices them wrongly. It holds each player's per-minute rate, so a regular who
loses 1.5 minutes loses 1.5 × her season rate in points. The minutes she does not actually play are disproportionately
low-usage minutes: garbage time, foul trouble, rest stretches. The out-of-pool leak points the same way — minutes that
go to deep-bench players nobody prices. The per-minute rate falls in exactly the minutes this estimator removes. The
book prices the regulars' points as if those minutes barely matter, and it is right.

This is the `model_engine_standard.md` warning in practice: a mechanism, minutes, was corrected in isolation inside a
calibrated chain, and the rates it feeds were fitted on the old minutes.

## 5. What would be worth trying (not done)

1. **Fit on the props target, not minutes.** Choose b0/b1/leak (and a separate per-minute-value factor for the
   removed minutes) to minimise May–Jul Brier against the book line, with the rate shrink applied. This needs May–Jul
   oracle sims shrunk post-hoc — cheap; the archive exists now.
2. **Bench-only variant.** Move freed minutes only to players below the pool mean and leave the regulars' props alone.
   The priced-row harm comes from taking minutes off regulars.
3. **Drop it.** The availability ceiling (`findings_2026-10-04_wnba_oracle_availability.md`) already says the props
   gain available from availability is small. This lane's result says the minutes channel is not where the
   regulars' props error lives either.

## 6. Side finding: the rate shrink drops sub-half-unit changes

The fix #3 rate shrink (`wnba_sim_rate_shrink.py`) SHIFTS integer ladders by the mean delta with half-up rounding.
The same convention here left threes ladders byte-identical and assists nearly so, so a change of less than half a unit
never reaches the board. That may be why threes was the rate shrink's one failing market. This module now scales draws
with largest-remainder rounding (`scale_values`, with a discriminating test). The rate shrink was not changed here;
it belongs to its own lane (held, flag OFF).
