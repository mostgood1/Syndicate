# Where the live moneyline's Brier gap to the market comes from (todo #780; lane live-moneyline-gap-diagnosis)

- **User** 2026-11-13 "Diagnose it now".
- **Substrate:** production. The fleet's live gameline ledgers (h2h / full rows, one per state, ledger dates <= 11-12),
  against ESPN finals in the ledger's home orientation. Read on the fleet host at nice 19.
- **Script:** `scripts/live_moneyline_gap.py`. Full output: `C:\tmp\livegrade\load780\ml_gap_1113.txt`.
- **Hypotheses H1-H4** were committed to the lane before anything ran (`d900e6554`, 20:30Z).
- **Prediction:** "H3 carries the largest share in NBA; H4 holds in both". The first half was WRONG; the second was right.

## The gap, reproduced

| sport | graded states / games | Brier model | market | model - market | priced rows only |
|---|---|---|---|---|---|
| NBA | 3,962 / 162 | 0.1626 | 0.1445 | **+0.018 +- 0.011** | +0.042 +- 0.026 (1,484) |
| NCAAB | 3,557 / 381 | 0.1181 | 0.1092 | **+0.009 +- 0.005** | +0.021 +- 0.012 (1,295) |
| NCAAF (contrast) | 13,560 / 324 | 0.1643 | 0.1570 | +0.007 +- 0.008 | +0.017 +- 0.016 |
| WNCAAB (contrast) | 488 / 61 | 0.0921 | 0.0991 | -0.007 +- 0.010 | -0.013 +- 0.018 |

The fit script's walk-forward figures (+0.020 / +0.009) came from 3,544 / 3,047 of these states. The PRICED rows
(the edges the board publishes) are worse than the population.

## Verdicts

### H1, signed bias

- **NBA: FALSIFIED. The model is calibrated.**
  - Signed residual: model +0.003 +- 0.067, market -0.016 +- 0.064.
  - The model's favourite wins exactly what it claims (-0.000 +- 0.045).
  - Logistic calibration: model intercept +0.02 [-0.36, +0.34], slope 0.97 [0.73, 1.30].
  - The MARKET's fair price is the one off: slope 1.47 [1.19, 1.89]. It is compressed toward 0.5, the
    favourite-longshot shape of a de-vigged price. It still wins on Brier.
- **NCAAB: a home lean both share, the model's beyond noise.**
  - Model intercept +0.44 [+0.09, +0.93]; market +0.22 [-0.18, +0.69].
  - In the 0.3-0.6 bins, home wins 0.55-0.66 where the model says 0.36-0.56 and the market 0.39-0.59.
  - The signed residuals overlap (model +0.045 +- 0.043, market +0.034 +- 0.042), so by the pre-stated test H1 is
    falsified as the gap's cause. The lean is real and early-season (11 dates of November non-conference games). It is
    a lead, not this gap.

### H2, stage

Model - market Brier by progress (points scored / the model's total mean):

| sport | < 0.15 (tip) | 0.15-0.40 | 0.40-0.75 | >= 0.75 |
|---|---|---|---|---|
| NBA | **+0.039 +- 0.015** | **+0.029 +- 0.014** | +0.011 +- 0.010 | +0.012 +- 0.019 |
| NCAAB | +0.006 +- 0.006 | +0.010 +- 0.007 | +0.007 +- 0.005 | +0.014 +- 0.014 |
| NCAAF | +0.018 +- 0.015 | +0.011 +- 0.011 | +0.004 +- 0.009 | +0.001 +- 0.006 |

- **NBA: SUPPORTED.** Early is about 3x late, and only the early bands exclude 0.
- **NCAAB: FALSIFIED.** It is flat.
- **The prior could not be tested directly:** `pregame_home_win_prob` is None on every NBA and NCAAB h2h row.

### H3, staleness

- **NBA: FALSIFIED.**
  - By state age (< 30 / 30-60 / 60-120 / 120-300 s): +0.019 / +0.019 / +0.020 / +0.017. Within 0.003.
  - By the quote's lead over the state: +0.017 (quote not newer) / +0.021 / +0.026 / -0.002 (>= 120 s, 104 states).
    Not monotone.
- **NCAAB: weak, not falsified.**
  - By state age: flat.
  - By the quote's lead: +0.006 +- 0.006 (quote not newer), rising to +0.015 +- 0.006 (quote >= 120 s newer, 636 states,
    18%).
  - A minor share of the gap at most.

### H4, information (logistic y ~ a + b1 logit p_model + b2 logit p_market, game bootstrap)

| sport | b1 model | b2 market |
|---|---|---|
| NBA | **-0.46 [-0.87, -0.09]** | 2.00 [1.53, 2.71] |
| NCAAB | -0.15 [-0.47, +0.15] | 1.29 [0.87, 1.76] |
| NCAAF | **+0.30 [+0.05, +0.58]** | 0.73 [0.32, 1.15] |

- **HOLDS in NBA and NCAAB: the market encompasses the model.** In NBA the model's coefficient is NEGATIVE beyond
  noise: given the market, the model's number points the wrong way.
- **NCAAF is the counter-case.** Its model carries information beyond the market, while being over-confident (slope
  0.78).

## Where the NBA gap sits

The states where the model disagrees with the market by >= 10 pp:

| sport | states | the model's side wins | model said | market said | model - market Brier | share of the gap |
|---|---|---|---|---|---|---|
| NBA | 974 (25%) | **0.401 +- 0.097** | 0.644 | 0.480 | +0.062 +- 0.036 | ~85% |
| NCAAB | 432 (12%) | 0.347 +- 0.088 | 0.554 | 0.398 | +0.048 +- 0.031 | ~65% |
| NCAAF | 4,457 | 0.650 +- 0.063 | 0.770 | 0.609 | +0.017 | (the model's side beats the market's price) |

- **The NBA disagreements are worst early:** +0.095 +- 0.034 at tip, +0.081 +- 0.035 at 0.15-0.40, +0.039 at
  0.40-0.75.
- **At tip, 112 of 339 NBA states (33%) are already >= 10 pp from the market.** In NCAAB it is 51 of 454 (11%).
- **The lead table:**
  - When the home team trails by 10+, the model sits 5 pp below the market.
  - When it leads by 10+, the model sits 3 pp above.
  - The model reacts to the score more than the market's (compressed) price does.

## What it means

- **The NBA live moneyline gap is not bias, staleness or over-confidence.** It is disagreement with the market that
  carries no information, concentrated early in games, where the live number is still mostly the starting strength.
- **The lead (a trace, not a result).**
  - The college live re-sims are MARGIN-ANCHORED to the market's pregame line (`ncaab/live_resim.py`
    `_anchor_segments`, `marginAnchored`). Their early gap is small: NCAAB +0.006, NCAAF +0.018, neither beyond noise.
  - The NBA live re-sim resumes the PREGAME ENGINE's own inputs (`nba/live_resim.load_engine_inputs`) and carries
    no market anchor. Its early gap is +0.039.
  - `#721` anchors the NBA PREGAME SmartSim to a market line. Whether that anchor survives into the live resume, or is
    a post-hoc shift of the pregame output that the resume never sees, is the next question. It is a code trace, then
    a replay.
- **What it does NOT license:** pausing NBA live moneylines. Every line is its own decision (the user's standing
  rule), and the fix belongs in the model's starting strength, not in a market-wide refusal.
- **Recorded, not acted on:**
  - The market's de-vigged moneyline is compressed (NBA slope 1.47). An edge computed against it inherits that:
    "value" on a heavy favourite can be the de-vig's shape. It belongs with the de-vig work in `#797`'s findings.
  - The NCAAB home lean.

## Nothing was changed in production

- A read-only script.
- `scripts/live_totals_width_fit.py` gained a `__main__` guard so its finals helpers import. Its output is unchanged.
