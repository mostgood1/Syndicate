# NFL prop mean inputs: pbp usage does NOT give the prop probability information at the line (2026-10-03)

Lane `nfl-prop-mean-inputs` (session 05b01a84). Measurement only: no production file edited, no deploy.
Script `scripts/fit_nfl_prop_mean_inputs.py`. The prediction was pre-registered and landed (`8373d26d`)
BEFORE the run. Outputs: `C:\tmp\nflbt\meaninputs\` (clean run).

The first run had two harness bugs; its outputs are kept as `C:\tmp\nflbt\meaninputs_run1_buggy\`:
- `ewma` read a game-log key that is never written, so its mean was 0 for both attempts markets;
- `share_inj` let an Out backup QB's prior-season share inflate a starter by up to x10.

Both were fixed, with a regression test, and the run repeated. The bar markets' `share` / `ewma` numbers
are identical across the two runs.

## Verdict: lane bar NOT MET; the pre-registered falsification holds in substance

**Bar:** calibration slope at the line > 0, game-clustered CI excluding 0, for receptions AND
receiving_yards, with a Brier gain over production. Fitted on 2023-24 by Brier, scored on 2025.

| market (2025) | production slope [CI] | best usage arm: slope [CI] | Brier vs production [CI] | vs book [CI] | corr(mean−line, actual−line) [CI], best arm |
|---|---|---|---|---|---|
| receptions | 0.107 [0.005, 0.203] | share (h=6): 0.135 [0.026, 0.244] | −0.0045 [−0.0083, −0.0006] | +0.0209 [+0.0138, +0.0278] | 0.063 [0.020, 0.109] (production 0.077) |
| receiving_yards | −0.066 [−0.155, 0.031] | **none > 0** (share −0.024 [−0.126, 0.093]) | share −0.0080 [−0.0139, −0.0024] | +0.0223 | ≈ 0.00 for every arm |
| rushing_yards | −0.010 | share_inj 0.072 [−0.032, 0.185] | share −0.0076 [−0.0138, −0.0014] | +0.0167 | 0.084 [0.020, 0.149] |
| rushing_attempts | 0.084 | share_inj 0.117 [−0.027, 0.294] | ewma −0.0030 [−0.0060, −0.0000] | +0.0143 | 0.071 [−0.002, 0.145] |
| passing_yards | −0.064 | ≈ 0 | n.s. | +0.043 | negative / ≈ 0 |
| passing_attempts | −0.002 | ≈ 0 (2025); share 0.49 [0.02, 1.99] on 2026 wk2, n tiny | n.s. | +0.024 | negative / ≈ 0 |

- **Receptions:** clears the bar only in form. PRODUCTION already has a slope CI above 0 (0.107), and
  `share` moves it to 0.135, an overlapping CI.
- **receiving_yards:** no arm moves it.
- **Information beyond the line:** corr(mean − line, actual − line) is ≤ 0.08 in every market and arm.
  For receiving_yards and passing it is ≈ 0 or negative. Pre-registered: < 0.05. That holds within
  noise; rushing_yards share_inj reaches 0.084, CI [0.020, 0.149].
- **Every arm still loses to the de-vigged book** with a CI excluding 0. Usage buys small Brier gains
  over production (−0.003 to −0.008); the gap to the book is +0.014 to +0.047.
- **Pre-registered prediction of a slope of 0.2-0.4 on receptions/receiving: WRONG.** Observed 0.135 and
  ≈ 0.
- **Controls:**
  - the production arm reproduced the served probability on every row (max |diff| 0.0);
  - every input is dated before the game (1 of ~5,400 injury status rows modified after gameday in
    2023-24; 2025-26 rows carry no `date_modified`).

## What it means

The line's information is not in pbp-derivable usage: target, carry and attempt share, team volume,
efficiency, or the official Out list.

That fits what the book plausibly prices that pbp never shows:
- practice participation and its timing;
- inactive lists 90 minutes before kickoff;
- coaching role announcements and snap-share plans;
- matchup and coverage plans.

Some of these are public, but none is in this repo's as-of data. The NFL prop model's season-to-date
mean is about as informative as a usage model, and both are near-uninformative at a priced line.

## Options (for the user; no recommendation to hide any line)

1. **Stop modelling the prop MEAN from pbp alone.** Further pbp features are unlikely to move the slope;
   this run tried recency, share and injury redistribution.
2. **New information, measured the same way:**
   - snap counts / route participation (nflverse `snap_counts`, not cached here);
   - practice participation (in the nflverse injury file: `practice_status`, unused so far);
   - game-day inactives (ESPN capture exists on the fleet since 2026-09-28, lane
     `nfl-game-day-injuries`; forward-only, no history).

   Practice status is the cheapest: it is already on disk.
3. **Accept that the model ≈ the market at the line.** Use the per-line machinery for what is measured
   to pay: price shopping across books (+2.95 ROI pts, `reports/nfl_props_roi.json`). This needs no model
   edge.

## Addendum: practice status (2026-10-03 ~20:30Z) -- also fails; lane CLOSED per its pre-registered rule

Arm `practice` = production mean x a per-status factor, sum(actual)/sum(mean) over unique player-games,
fitted on 2023-24. Statuses: Full / Limited / DNP from nflverse `practice_status`, or `none` when the
player is not on the report. Scored on 2025; outputs in `C:\tmp\nflbt\practice\`.

| market | fitted factors: none / full / limited / dnp (fit n) | 2025 slope: production -> practice | Brier vs production [CI] | Limited/DNP subgroup (player-games) |
|---|---|---|---|---|
| receptions | 1.118 / 1.063 / 1.049 / 0.952 (2,676 / 483 / 229 / 49) | 0.107 -> 0.109 | **+0.0035 [+0.0006, +0.0064] WORSE** | 168: no gain (+0.0034, CI spans 0) |
| receiving_yards | 1.126 / 1.070 / 1.058 / 1.041 | −0.066 -> −0.060 | **+0.0038 [+0.0013, +0.0061] WORSE** | 169: no gain |
| rushing_yards | 1.081 / 0.971 / 1.040 / 0.764 (dnp n = 8) | −0.010 -> −0.014 | +0.0008 n.s. | 47: no gain |
| rushing_attempts | 1.101 / 1.062 / 1.052 / 0.904 (dnp n = 5) | 0.084 -> 0.081 | −0.0020 n.s. | 39 |
| passing_yards / attempts | ~1.05 for all statuses | ≈ 0 | n.s. | < 50, not scored |

- **Coverage bounded it, as pre-registered.** Only 21% of quoted player-games carry any status, and
  6.6% are Limited/DNP.
- **The fitted factors are mostly a LEVEL SHIFT.** Players NOT on the report are under-projected by
  8-13% on the quoted population, the same selection bias found in the backtest. That shift did not
  carry over to 2025.
- **The "Limited/DNP factor < 1" prediction was WRONG.** Limited players are not over-projected relative
  to the rest.
- **"The book already prices it" held within noise.** In the subgroup, the practice arm's corr(mean −
  line, actual − line) is 0.19 [−0.02, 0.37] for receptions, against production's 0.22 [0.01, 0.41],
  on 168 player-games.

**Conclusion for the lane.** Neither pbp usage (recency, share, injury redistribution) nor practice
status gives the NFL prop probability information at a priced line. The line's information is not in
any as-of public data this repo holds. Per the pre-registered rule, the lane closes: GOAL NOT MET.
