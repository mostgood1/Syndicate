# UEFA ratings anchored to past closes: re-running the #699 gate — 2026-10-19

Lane `uefa-market-anchored-ratings`, session 436c79e2. Research only: wired into nothing; Stage 0's
no-sim guards stay whatever this finds.

Follows `findings_2026-10-16_uefa_close_backtest.md`. That gate was NO-GO for UCL / UEL / UECL:
model − close was +0.0286, the same size for in/in and in/out-of-scope pairs, and the model
underrated favourites (top decile 0.778 vs close 0.821 vs actual 0.854). The weak link is the rating
itself, which lacks information the market has. This step asks whether learning a per-club correction
from the market's OWN past prices closes that gap enough for a model/close blend to beat the close.

## 1. PRE-REGISTRATION (committed BEFORE any fit)

Nothing anchored has been fit or scored when this is committed. The inputs are the step-3 joined
closes and the step-3 model, already published. Any change after this point is a deviation and goes
in section 5.

### Data

- **Matches:** the step-3 set, unchanged. That is ESPN UEFA main draw 2020-2026 joined to an OddsAPI
  de-vigged close (Pinnacle else the book average), 2,474 matches. Closes are cached in
  `C:/tmp/uefa-closes`, so no new API spend.
- **Base model rates:** for every match, the step-3 model's own `(λ_home, λ_away)`, recomputed with
  `scripts/backtest_uefa_vs_close.py run --dump-features`. That is the same walk-forward (CONST
  offsets + production ratings for in-scope clubs; the item-(ii) FITTED model for out-of-scope clubs),
  frozen at July 1 of each season. The dump adds the club ids and rates and changes no number in
  step 3. As a check, the dumped model log loss must equal step 3's to within 1e-9 on every
  season, or the run stops.

### The anchored model

For club `c` (ESPN team id), a correction `(α_c, δ_c)` in log-goal-rate units:

- `log λ'_home = log λ_home + α_home − δ_away`
- `log λ'_away = log λ_away + α_away − δ_home`

1X2 comes from independent Poisson as before. Fitted by weighted **cross-entropy to the CLOSE**
(target = the de-vigged close probabilities, not the outcome) over training matches. Each match is
weighted `0.5 ** (age_days / 365)`, ridge penalty `τ/2 · Σ(α² + δ²)`, and the base rates are fixed.
A club unseen in training gets 0.

- **PRIMARY arm ANCHORED (frozen):** for test season S, fit on all joined matches of seasons
  2020..S−1, weights to July 1 of S, frozen for the season.
- **τ by inner walk-forward:** fit on seasons < S−1, pick from `τ ∈ {1, 3, 10, 30, 100}` by 1X2 log
  loss against OUTCOMES on season S−1. Ties go to the larger τ. This needs two prior seasons of
  closes, so **ANCHORED is scored on S = 2022..2026**.
- **BLEND_A** = `w·p_anchored + (1−w)·p_close`, with `w ∈ {0, 0.05, …, 1}`. `w` is fit on all held-out
  ANCHORED matches of seasons 2022..S−1 (pooled across competitions; ties go to the smaller w), so
  **the gate is scored on S = 2023..2026**.
- **SECONDARY arm ANCHORED-LIVE** (reported with the same rule, NOT the gate): the same model refit
  before each match DATE on every joined match with an earlier kickoff day. The τ for the season
  comes from the primary inner rule, weights are aged to that date, and it gets its own w fit the
  same way. This tests in-season information; it is secondary because it fits many more models
  and so has more chances to look good.

### Metric and verdicts

- Per-match 1X2 log loss (90-minute result; extra time is a draw), with paired 95% bootstrap CIs
  (2,000 resamples, seed 699).
- **H-ANCHOR (primary), per competition (UCL, UEL, UECL) and pooled:** Δ = LL(BLEND_A) − LL(CLOSE),
  test seasons 2023-2026.
  - **GO** if the CI lies entirely below 0;
  - **NO-GO / NOT DEMONSTRATED** if the point estimate is below 0 and the CI includes 0;
  - **NO-GO / FALSIFIED** if the point estimate is ≥ 0.
- **Reported, no verdict:**
  - ANCHORED − MODEL against outcomes (does anchoring help the model at all);
  - ANCHORED − CLOSE;
  - the favourite-decile calibration of MODEL / ANCHORED / CLOSE;
  - the w and τ trajectories;
  - in/in vs involving an out-of-scope club;
  - ANCHORED-LIVE's own numbers.

### Prior expectation, stated up front

Anchoring to past closes uses only information the market had already priced. So beating the CURRENT
close requires the past prices to carry something the current close forgot. **NO-GO is the expected
outcome.** A GO would be surprising and would need a forward test before any serving decision.

### What this does NOT establish

Betting value (no bet-time prices), qualifiers, knockout aggregate state, or anything about domestic
leagues.

## 2. Coverage

## 3. Results

## 4. What cannot be estimated

## 5. Deviations from the registration
