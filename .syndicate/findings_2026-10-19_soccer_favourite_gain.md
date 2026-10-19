# Soccer 1X2: a SYSTEMATIC fix for the favourite gap? (lane `soccer-team-strength` stage 3; todo #699) — 2026-10-19

Lane `soccer-team-strength`, session e44b3e73 (adopted 2026-10-19 from archived 2eff0a12 / 8b75e513).
Research only. Nothing here touches the sim, the board, a worker, `render.yaml` or a deploy. Production
rating code is READ, never edited. Shipping anything is a user decision.

The same signature has now been measured three times:

| measurement | model | de-vigged close | actual |
|---|---|---|---|
| domestic top decile (`findings_2026-10-16_soccer_rating_compression.md`, arm C) | 0.743 | 0.804 | 0.821 |
| UEFA step 3 (`findings_2026-10-16_uefa_close_backtest.md`) | 0.778 | 0.821 | 0.854 |
| UEFA anchored (`findings_2026-10-19_uefa_market_anchored.md`) | 0.784 | 0.823 | 0.873 |

Already ruled out: a global rating scale (the outcome-optimal slope 1.58 equals the engine's own gain 1.59),
removing the ±0.35 clamp (worse), the rating INPUT variants (9% of the gap closed), and per-club corrections
fit to past closes (blend weight 0 every season). The anchored study's engine read says every favourite is
underrated by about the same 4-5 points whoever the club, which points at something systematic.

## 1. PRE-REGISTRATION (committed BEFORE any candidate is coded, fit or scored)

Written 2026-10-19 20:2xZ. No candidate parameter, probability or score has been computed. The only numbers
known are the ones published in the three findings above. Any later change is a deviation and gets its own
dated line in section 5, never an edit here.

### Data and reference arm (unchanged from stage 1)

- Inputs exactly as stage 1 used them: `C:/tmp/uefa-offsets/prod_history` (production's rating inputs) and
  `C:/tmp/team-strength/fd_raw` (football-data raw season CSVs), the same 8 leagues (big 5 + eredivisie,
  primeira_liga, belgian_pro_league), the same aliases and wrong-pairing exclusions, the same close (Pinnacle,
  else market average, else B365; proportional de-vig).
- Population: stage 1's **FULL** set (every match with a close; promoted and few-match clubs kept through the
  shipped gate). Held out = test seasons **2016..2026**, walk-forward by season (July..June), training =
  every FULL match of seasons 2014..S−1, parameters frozen through the test season.
- **Reference arm `C*`**: the shipped rating + few-match gate, per-league Poisson link with μ_L, η_L and k
  refit — stage 1's reference exactly. Identity: this run's `C*` held-out mean log loss must equal stage 1's
  0.9777 to within 1e-4 on the same 27,285 matches, or the run stops.

Notation, per match: `gh = A_home − D_away`, `ga = A_away − D_home` (shipped-space ratings), the **rating
gap** `g = gh − ga` and the **level** `s = (gh + ga)/2`. `C*` is
`log λh = μ_L + η_L + k·s + (k/2)·g`, `log λa = μ_L + k·s − (k/2)·g`. 1X2 from the independent-Poisson score
grid truncated at 10 goals, as before.

### Candidates

**(a) Favourite-dependent gain.** Two forms, each with its own verdict (multiplicity handled below).

- **(a1) GAIN-LINK — the goal-rate gain rises with |gap|.**
  `log λh = μ_L + η_L + k·s + (k/2)·g·(1 + γ·|g|)`, `log λa = μ_L + k·s − (k/2)·g·(1 + γ·|g|)`.
  One extra parameter γ, unconstrained in sign, fit jointly with μ_L, η_L, k by Poisson maximum likelihood on
  the training goals (the same objective as `C*`). γ = 0 is `C*` exactly. γ > 0 stretches big gaps more than
  small ones; the term `g·|g|` is the power-on-the-gap idea in a form that is smooth at g = 0.
- **(a2) GAIN-1X2 — the 1X2 log-odds stretched as a function of |gap|.** A post-hoc temperature on `C*`'s
  probabilities: `p'_i ∝ p_i^τ`, `τ = exp(τ0 + τ1·|g|)`. Two parameters fit by 1X2 multinomial log loss
  on the training seasons' in-sample `C*` probabilities (the `C*` link fit on those same seasons).
  τ0 = τ1 = 0 is `C*`. τ1 > 0 is a gain that rises with |gap|; τ0 alone is a global sharpening, reported as
  the decomposition (a2-0) with no verdict.

**(b) Draw-rate correction tied to the gap.** `p'_D ∝ p_D·exp(δ0 + δ1·|g|)`, `p'_H ∝ p_H`, `p'_A ∝ p_A`,
renormalised. Two parameters fit by 1X2 log loss on the training seasons' in-sample `C*` probabilities, as in
(a2). δ = 0 is `C*`. δ1 < 0 deflates draws in lopsided games, which moves probability to the favourite. The
decomposition (b-0), δ0 only (a global draw-rate correction), is reported with no verdict.

**(c) Lineup or rotation input: NOT TESTABLE on these data, registered as not run.** Neither football-data's
season CSVs nor Understat's team rows carry lineups, minutes, injuries or squad value. A rest-days proxy built
from domestic league dates cannot see the midweek European and cup matches that drive rotation, so it would
mis-measure exactly the clubs at issue (the top decile is dominated by clubs in Europe). Verdict
**NOT DEMONSTRATED (untested: no input exists)**, and the input goes to the lane as a lead.

**Secondary, no verdict:** (a1)+(b) together (AB: the (a1) link, then (b) fit on its in-sample
probabilities); and every candidate on the stage-1 cumulative rating (`h 40, c 40, n0 5, fitted prior`, the
stage-2 candidate), each against that rating's own reference link.

### Metrics, test and verdicts

- **Primary:** held-out per-match 1X2 log loss against the OUTCOME (90-minute result), paired Δ = arm − `C*`
  pooled over all held-out matches, 95% CI from 2,000 bootstrap resamples over matches (seed 699). Brier as a
  secondary.
  - **SUPPORTED** if the CI lies entirely below 0. For (a), with two forms, the CI is the Bonferroni
    **97.5%** interval and (a) is SUPPORTED if either form is.
  - **NOT DEMONSTRATED** if the point estimate is below 0 and the CI includes 0.
  - **FALSIFIED** if the point estimate is ≥ 0.
- **Against the close (co-reported):** Δ(arm − close) on outcome log loss with its CI and the share of `C*`'s
  gap closed; and the divergence from the close itself, `KL(close ‖ arm) = Σ p_close·log(p_close/p_arm)`,
  with the paired Δ vs `C*` and its CI. The arm "moves toward the close" only if that KL Δ CI lies below 0.
- **Decisive secondary: top-decile favourite calibration**, two selections, because they answer different
  questions:
  - **F1, top decile by the CLOSE's favourite probability** (the selection of all three prior measurements):
    mean arm probability of that side, mean close, actual win rate, and the share of `C*`'s shortfall to the
    actual rate that the arm closes, `(p_arm − p_C*)/(actual − p_C*)`.
  - **F2, top decile by the ARM's OWN favourite probability**: mean arm probability vs the actual win rate,
    with a bootstrap CI on actual − predicted. This is calibration in the strict sense. Selecting on the
    close picks the matches where the close is high relative to the model, so F1 contains a selection effect
    that no calibration map can remove; F2 does not.
  - Full decile tables (1..10) for `C*`, every arm and the close, under both selections.
- **A candidate counts as a FIX for the favourite gap only if all three hold:** its primary verdict is
  SUPPORTED; it closes **at least 25%** of `C*`'s F1 shortfall to actual; and on F2 it is not over-confident
  (its mean prediction is not above the upper end of the actual rate's CI).
- **Reachability (`off != on`):** every arm must change held-out probabilities by more than 1e-6 on at least
  1% of matches, or it is reported INERT and not scored. The fitted parameter trajectory per season is
  reported.
- **Identity:** at its null parameters each arm reproduces `C*`'s probabilities to 1e-9 (offline test and a
  runtime assertion).
- **Secondary, never a verdict:** per league, per season, big 5 vs goals leagues, CORE vs PROMOTED, 2026
  alone, the AB and cumulative-rating arms, and the decompositions (a2-0), (b-0).

### Prior expectation, stated up front

The compression study read the shortfall as a NOISY rating: errors in the regressor attenuate the
outcome-optimal slope, and the rating cannot reach the close's dispersion (sd 0.320 vs 0.364) at any slope.
If that is right, (a) finds γ / τ1 near 0, because the attenuation is not gap-dependent; (b) finds a small
global draw term; and F2 shows `C*` already near-calibrated on its own favourites, so the F1 gap is
information, not a systematic bias. **The expected outcome is that no candidate is a FIX.** A FIX would
contradict the noisy-rating reading and would need the UEFA re-run below before anything else.

### If a candidate is a FIX

The UEFA gate is re-run under a NEW registration (never this one), applying the fitted domestic form to the
UEFA step-3 model's rates with the domestic parameters frozen. The exact commands go into todo #699.

### What this does NOT establish

- The SERVED sim's 1X2 under any of these maps. No sim is run. The sim reads ratings, not this link; a
  candidate that works here would need its own wiring into the engine and a reachability test.
- Lineup, injury, rotation or squad information (candidate c), MLS, the Championship.
- Betting value: there are no bet-time prices here.

Run at Idle priority. Driver: `scripts/soccer_team_strength_experiments.py stage3`.

## 2. Coverage

- Code on main before any fit: `40806207`, with 8 hermetic tests in `tests/test_soccer_team_strength_gain.py`.
- Run 2026-10-19 ~20:27-20:36Z, `scripts/soccer_team_strength_experiments.py stage3 --root C:/tmp/team-strength`.
  Priority read back as **64 (IDLE_PRIORITY_CLASS)**. Output: `C:/tmp/team-strength/stage3_report.json`,
  `stage3_run.log`.
- **FULL 32,638 matches; held out 27,285** (2016..2026, the 2026 season n 512). Skipped: 8 wrong pairings, 10
  with no close. This is stage 1's population exactly.
- **Identity PASSED.** `C*` held-out log loss is 0.9777, stage 1's value. The null-parameter runtime assertion
  (temper and draw maps at 0 reproduce `C*` to 1e-9) held in every season.
- **Reachability PASSED.** Every arm changes 100% of held-out matches, so none is INERT.
- One family, one window: ratings, outcomes and closes come from the same matches, so the intersection is
  the FULL set itself.

## 3. Results

### Fitted parameters (walk-forward, main rating; every season fits the same sign)

| season fit for | k | (a1) γ | (a2) τ0, τ1 | (b) δ0, δ1 |
|---|---|---|---|---|
| 2016 | 1.532 | +0.68 | −0.136, +0.370 | +0.144, −0.284 |
| 2020 | 1.602 | +0.50 | −0.062, +0.264 | +0.145, −0.381 |
| 2026 | 1.577 | +0.44 | −0.066, +0.271 | +0.163, −0.360 |

All 11 seasons agree in sign: γ ranges +0.39..+0.68, τ1 +0.17..+0.37 and δ1 −0.22..−0.39. The data ask for a
gain that rises with |gap| and for fewer draws in lopsided games, every season.

### Verdicts (Δ held-out 1X2 log loss vs `C*`, 27,285 matches)

| arm | Δ vs C\* | 95% CI | 97.5% CI (Bonferroni, (a) only) | Δ Brier | Δ KL to close [CI] | Δ vs close | F1 top decile (C\* 0.745, close 0.805, actual 0.821) | F1 shortfall closed | F2 own top decile: arm / actual [CI] | rule verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| C\* | 0 | — | — | — | — | +0.0221 | 0.745 | 0 | 0.777 / 0.800 [0.784, 0.813] | reference |
| **(a1) gain in the goal link** | +0.0003 | [−0.0001, +0.0006] | [−0.0002, +0.0007] | +0.0002 | +0.0004 [+0.0003, +0.0005] | +0.0224 | 0.758 | 17% | 0.794 / 0.803 | **FALSIFIED** |
| **(a2) 1X2 temperature exp(τ0 + τ1·\|g\|)** | **−0.0005** | [−0.0010, −0.0001] | **[−0.0010, −0.00002]** | −0.0004 [−0.0006, −0.0002] | **+0.0004 [+0.0003, +0.0005]** | +0.0216 | **0.774** | **39%** | **0.810 / 0.802 [0.789, 0.816]** | **SUPPORTED; meets the FIX rule** |
| (a2-0) global temperature only | −0.0000 | [−0.0003, +0.0003] | | +0.0000 | +0.0005 | +0.0221 | 0.759 | 18% | 0.791 / 0.799 | (decomposition) |
| **(b) draw term exp(δ0 + δ1·\|g\|)** | **−0.0010** | **[−0.0015, −0.0005]** | | −0.0006 [−0.0009, −0.0003] | **−0.0005 [−0.0005, −0.0004]** | +0.0211 | 0.751 | 8% | 0.784 / 0.801 | **SUPPORTED; NOT a fix** |
| (b-0) global draw rate only | −0.0005 | [−0.0009, −0.0002] | | −0.0002 | −0.0005 | +0.0216 | 0.737 | −10% | 0.770 / 0.798 | (decomposition) |
| AB = (a1) + (b) (secondary) | −0.0006 | [−0.0012, +0.0000] | | −0.0003 | −0.0000 | +0.0215 | 0.761 | 21% | 0.798 / 0.801 | (secondary) |

Spread, the sd of p(home) − p(away): C\* 0.323, a1 0.324, **a2 0.340**, b 0.324, close 0.364.

**Per season** (Δ vs C\*, units of 1e-4): (a2) is below 0 in 9 of 11 seasons (2016 +2.9, 2022 +0.1), and
(b) in 10 of 11 (2016 +0.9). By league, (a2) is −28.5 in Primeira (CI below 0), −10.3 in Serie A, and above 0
in Eredivisie (+6.5) and Belgium (+2.5). (b) is below 0 in 7 of 8 leagues; Ligue 1 is +0.5. On PROMOTED
matches, (a2) is +24.4 (n 1,422, CI spans 0): the temperature over-sharpens a gap that a promoted club's
prior rating makes look bigger than it is.

**On the stage-1 cumulative rating** (secondary; its own reference is 0.9754, +0.0197 vs close):
- (a2): −0.0003 [−0.0009, +0.0002], NOT DEMONSTRATED. It is **over-confident on F2**: 0.824 against an actual
  0.801 [0.786, 0.816]. That rating is already wider (k 1.70-1.78 against 1.53-1.62), so the same
  temperature overshoots.
- (b): −0.0010 [−0.0015, −0.0005], SUPPORTED. It replicates exactly.
- (a1): +0.0002, FALSIFIED.

### F2 is the finding: C\* is UNDER-confident on its own favourites

Deciles of C\*'s own favourite probability (model / actual):

| decile | 1 | 2 | 5 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|
| C\* | 0.378 / 0.368 | 0.405 / 0.381 | 0.486 / 0.473 | 0.605 / 0.612 | **0.668 / 0.698** | **0.777 / 0.800** |
| (a2) | 0.377 / 0.365 | 0.402 / 0.385 | 0.482 / 0.483 | 0.613 / 0.618 | 0.687 / 0.691 | 0.810 / 0.802 |

The registered prior expected C\* to be calibrated on its own deciles. **It is not.** The top two deciles
under-predict by 2.3-3.0 points, and the weak-favourite deciles over-predict by about a point. So part of the
favourite gap IS systematic, and a gap-dependent 1X2 temperature removes it: (a2)'s deciles sit within about a
point of actual all the way up.

### Verdicts per candidate

- **(a) favourite-dependent gain: SUPPORTED, through (a2) only**, and (a2) meets the registered FIX rule on
  the primary rating:
  - Δ −0.0005 with the Bonferroni CI below 0;
  - 39% of the F1 shortfall closed (0.745 → 0.774, against an actual 0.821);
  - not over-confident on F2.
  - (a1) is **FALSIFIED**. The same idea fit by goal likelihood in the Poisson link stretches the goal rates
    but loses 1X2 log loss. The goal objective is not the 1X2 objective at the extremes.
  - **The size must be read with the verdict.** The pass is marginal: the 97.5% upper bound is −0.00002. It
    does not replicate on the cumulative rating, where it over-sharpens. And it moves the model AWAY from the
    close (Δ KL +0.0004, CI above 0): (a2) closes 2% of the log-loss gap to the close. It fixes calibration
    on favourites without adding the information the close has.
- **(b) gap-tied draw correction: SUPPORTED** (−0.0010 [−0.0015, −0.0005]). It replicates on the cumulative
  rating, holds in 10 of 11 seasons, and moves TOWARD the close (Δ KL −0.0005, CI below 0). Half of it is a
  global draw-rate correction (b-0 −0.0005): independent Poisson under-predicts draws. The gap term adds the
  other half. **It is not a fix for the favourite gap:** it closes 8% of the F1 shortfall.
- **(c) lineup or rotation input: NOT DEMONSTRATED**, untested because no such input exists in these data (as
  registered).

### Engine read

1. **The favourite gap has two parts, and this study separates them.**
   - A **systematic calibration part**: about 2-3 points on the model's own top two deciles. A gap-dependent
     1X2 temperature removes it.
   - An **information part**: everything else. The close's favourites are still 0.031 above (a2)'s on F1
     (0.805 vs 0.774), and (a2) moves no closer to the close in KL. That is the part the prior reading
     ("noisy rating") was right about.
   - The compression study's conclusion that the shortfall is "lack of INFORMATION in the rating, not a scale
     or clamp setting" was therefore only mostly right. A non-linear shape term exists, but a LINEAR scale
     could never find it.
2. **The sim cannot take (a2) as it stands.** The engine does not output a 1X2 through this link. Its 1X2 comes
   from simulated scores, so a post-hoc temperature would have to be applied to the sim's 1X2, keyed on the
   sim's own |rating gap|. That is a new wiring with its own reachability test, and it is out of scope here.
   (b)'s draw term has the same shape.
3. **Independent Poisson's draw deficit is real and stable** (δ0 +0.12..+0.16 every season, about +14% draw
   odds at |g| = 0). It is the textbook Dixon-Coles effect. The sim's own score model may or may not share it;
   that is unmeasured.

## 4. What cannot be estimated

- **The served sim under (a2) or (b).** No sim was run. Both are post-hoc maps on a 1X2 the engine does not
  emit through this link.
- **Whether (a2)'s calibration gain survives the stage-2 rating.** On the cumulative rating it is NOT
  DEMONSTRATED and over-confident. Anyone shipping both needs a joint refit, and a joint arm was not
  registered.
- **(a2) + (b) together.** Not registered, so not run. AB is (a1) + (b). A joint (a2) + (b) needs a new
  registration.
- **Lineups and rotation** (candidate c), MLS, the Championship, betting value.

## 5. Deviations from the registration

- None. Arms, objectives, CIs, verdict and FIX rules ran as registered; the identity and reachability checks
  passed.
- The prior expectation (F2 calibrated, no FIX) was **wrong** and is left as written.
