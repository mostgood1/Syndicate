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

- `features.json`: 2,474 rows. **Self-check PASSED:** the max |model log loss − step 3| is 0.0 and the
  max |probs(lam) − p_model| is 6.7e-16, so the dump is step 3's model exactly.
- ANCHORED is scored on 1,890 matches (2022-26). **The gate is scored on 1,551** (2023-26: UCL 536, UEL 553, UECL 462).

## 3. Results

Run 2026-10-19 at Idle, after `515223b5` (code on main before any fit). Output `C:/tmp/uefa-closes/report_anchored.json`.

### THE GATE: NO-GO / FALSIFIED in all three competitions (the primary arm and the live arm alike)

| | n | Δ BLEND_A − CLOSE | verdict |
|---|---|---|---|
| UCL | 536 | 0.0000 | NO-GO / FALSIFIED |
| UEL | 553 | 0.0000 | NO-GO / FALSIFIED |
| UECL | 462 | 0.0000 | NO-GO / FALSIFIED |
| pooled | 1,551 | 0.0000 | NO-GO / FALSIFIED |

- **The walk-forward blend weight was w = 0 in EVERY season (2023-2026), for ANCHORED and ANCHORED-LIVE alike.**
- So the blend IS the close and Δ is exactly 0. By the registered rule a point estimate of 0 or more is FALSIFIED.
- The model carries nothing the close lacks, even after anchoring.

### Secondary (no verdict)

- Log loss, 2022-26 (n 1,890): MODEL 0.9519, ANCHORED 0.9527, ANCHORED-LIVE 0.9489, CLOSE 0.9192.
- **ANCHORED − MODEL +0.0008 [−0.0022, +0.0038]: anchoring to past closes did NOT help.** In/in +0.0027,
  involving an out-of-scope club −0.0002, both CIs including 0.
- The inner rule chose **τ = 100, the grid's upper edge, in 2024 and 2025** (1 in 2022, 30 in 2023, 3 in
  2026). The data mostly asked for corrections shrunk to nothing.
- ANCHORED − CLOSE **+0.0335 [+0.0226, +0.0444]**; LIVE − CLOSE +0.0297 [+0.0193, +0.0398]. The live arm
  helps a little (−0.003 vs MODEL) but closes about a tenth of the gap.
- **Favourites, unchanged by anchoring** (decile of the close's favourite):
  - top decile: close 0.823, model 0.782, anchored 0.784, actual 0.873;
  - decile 9: close 0.725, model 0.677, anchored 0.678, actual 0.741.

### Engine read

- **The favourite gap is not club-specific, so a per-club correction cannot close it.**
  - Every favourite is underrated by roughly the same 4-5 points, whoever the club.
  - A ridge-shrunk per-club term fit to a few UEFA closes per season cannot learn a systematic, cross-club shift.
  - That is why τ ran to the edge.
- **The remaining candidates are SYSTEMATIC, not per club:**
  - a favourite-dependent gain (rating gaps amplified more at the top);
  - in-match information the close sees and the rating cannot (lineups, rotation, motivation in dead rubbers);
  - the market itself (it is closer to the actual rate than the model in every decile).
- **The domestic study already found the same signature** (soccer-team-strength: rating gap +0.022,
  favourites 0.743 / 0.804 / 0.821). That points at a single cause shared across competitions, i.e. the
  rating, not anything UEFA-specific.

## 4. What cannot be estimated

- Domestic closes as an anchor for in-scope clubs (not pulled here).
- A systematic favourite-gain term: not registered, so not tested. It is the next candidate.
- Betting value.

## 5. Deviations from the registration

- None.
