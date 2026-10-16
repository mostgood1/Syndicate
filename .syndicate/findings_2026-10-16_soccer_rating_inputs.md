# Soccer team ratings: do better rating INPUTS close the domestic 1X2 gap to the close? (lane `soccer-team-strength` stage 1, H39; todo #699) — 2026-10-16

Lane `soccer-team-strength`, session 8b75e513 (re-adopted from 2eff0a12). Research only: nothing in this lane
touches the sim, the board, a worker, `render.yaml` or a deploy. Production rating code
(`syndicate/features/soccer/features/loaders.py`, `scripts/build_soccer_artifacts.py`) is READ, never edited.

Follows `.syndicate/findings_2026-10-16_soccer_rating_compression.md`. There, the shipped rating at its
outcome-optimal slope (arm C, m̂ 1.583, which equals the served engine's gain of 1.593) still trailed the
de-vigged close by +0.0218 [+0.0195, +0.0239] log loss over 26,547 held-out matches. On top-decile favourites
it gave 0.743, against 0.804 from the close and 0.821 actual. Scale and clamp were ruled out, so the remaining
gap is INFORMATION in the rating inputs. This file tests the inputs.

## 1. PRE-REGISTRATION (committed BEFORE any variant is computed or fit)

Written 2026-10-16 17:4xZ. No variant rating, likelihood or score has been computed. The inputs on disk are
the ones the compression study used: `C:/tmp/uefa-offsets/prod_history` and `C:/tmp/team-strength/fd_raw`,
the same 8 leagues, the same aliases and wrong-pairing exclusions (its deviation 1), and the same close
(Pinnacle, else average, else B365; proportional de-vig). Any later change is a deviation and gets its own
dated line in section 5, never an edit here.

### What "shipped" means now (the reference arm, `C*`)

Production's rating for a club on day `t` is:

- `compute_team_ratings(rows, as_of=t, window=W0)` on the fleet's depth (big 5: Understat xG, `W0 = 45`,
  the match season plus 2 before; goals leagues: football-data goals, `W0 = 90`, the season plus 3 before);
- then `clamp(0.55·x, ±0.35)`;
- then **the few-match gate**: a club with 0 rated rows (`_fill_promoted`) or 1..9 rated rows
  (`_gate_few_match`, ON in production since 2026-10-07 18:54Z: `SYNDICATE_SOCCER_CURRENT_HISTORY=1`) gets
  `PROMOTED_TEAM_RATING = (−0.18, −0.18)`.

The compression study's arm C did NOT include the gate. It scored only matches where both sides had at least
5 rated rows. **`C*` = arm C plus the gate**: the per-league Poisson link with `k` refit, on the shipped rating
with production's few-match handling. Every variant changes only the rating INPUT and keeps everything after
it: clamp(0.55·x, ±0.35), then the link with μ_L, η_L and k refit.

### Population

- **FULL (primary):** every football-data match with a close where each side either resolves to a rating key
  or resolves to nothing (0 rows in the depth, which means a promoted club). Wrong pairings are excluded, as
  before. Held out = test seasons 2016..2026, walk-forward, training = 2014..S−1.
- **CORE (secondary):** FULL matches where both sides have at least 10 rated rows under the shipped window,
  so the gate does not fire. This is close to the compression study's set.
- **PROMOTED (secondary):** FULL minus CORE.
- Every arm scores the same matches. Counts by reason are printed.

### Variant families (raw deviation `x`, before the shipped transform)

Notation: for a club as of day `t`, its rows in the depth dated before `t`, sorted by day; `n` = rows used;
`m_f`, `m_a` = its (weighted) mean xG for and against; `μ` = production's league mean (unweighted mean of
`xg_for` over every club's window rows); `x_att = m_f/μ − 1`, `x_def = 1 − m_a/μ`. A club is **ESTABLISHED**
if it has a row in the depth from a season before the match season, otherwise **PROMOTED**.
`p0 = −0.18/0.55 = −0.3273` is the shipped prior in raw space.

| family | what changes | grid (shipped value first) |
|---|---|---|
| **W — window length** | last `W` rows (capped by the depth); `μ` recomputed on the same window | `W/W0 ∈ {1, 1/3, 2/3, 4/3, 2}`: big 5 {45, 15, 30, 60, 90}, goals {90, 30, 60, 120, 180} |
| **R — recency weighting** | weights `0.5^(age/h)` on the window rows, where `age` = 0 for the latest row, 1 for the one before, and so on; `μ` unchanged | `h ∈ {∞, 40, 20, 10}` matches |
| **B — current-season blend** | `x = (1−b)·x_window + b·x_current`, where `x_current` uses only the club's match-season rows (same `μ`) and `b = n_cur/(n_cur + c)` (`b = 0` when `n_cur = 0`) | `c ∈ {∞, 40, 20, 10, 5}` |
| **S — shrinkage strength** (replaces the gate's hard switch) | `x = (n·x_obs + n0·target)/(n + n0)`, where target = 0 (league mean) for ESTABLISHED clubs and `p0` for PROMOTED clubs; `n = 0` gives the target | `n0 ∈ {gate (shipped), 5, 10, 20, 40}` |
| **P — promoted-team prior value** (keeps the gate, changes the value) | the gate's value is `x_prior,L` in place of `p0`, separately for attack and defence: the mean raw `x` of PROMOTED clubs over their promotion-season rows in training seasons `< S` of league `L` (rows rated against that league-season's `μ`) | `{p0 (shipped), fitted}` |

**Selection is walk-forward, never on the test season.** For each test season `S` and each family, the grid
value is the one with the lowest IN-SAMPLE log loss of the link fitted on training seasons `< S`. Every value
has the same parameter count, so in-sample comparison is fair. The family's held-out score is the
concatenation of each season's selected value. Every grid point's held-out score is also reported, but only
as description: picking the best of those after the fact is not a verdict.

**Singly:** each family with the other four at their shipped values.

**Cumulatively, in this fixed order: W → R → B → S → P.** For each test season, choose W first, then R given
that W, and so on, each by in-sample training log loss. When S selects a non-gate value, P's fitted prior
becomes S's PROMOTED target instead of `p0`. The order is fixed in advance and is not tuned.

### Metric, test and verdicts

- Per-match 1X2 log loss vs the outcome, with Brier as a secondary. Paired differences are pooled over every
  held-out FULL match. 95% CI from 2,000 bootstrap resamples over matches, seed 699.
- **Per family and for the cumulative arm: Δ = V − C\*.**
  - **SUPPORTED** if the CI lies entirely below 0.
  - **NOT DEMONSTRATED** if the point estimate is below 0 and the CI includes 0.
  - **FALSIFIED** if the point estimate is ≥ 0. A family whose selection picks the shipped value in every
    season scores Δ = 0 identically, which is FALSIFIED, and is reported as such.
- **Gap to the close:** for C\*, each family, the cumulative arm and the close: mean held-out log loss,
  Δ(arm − close) with its CI, and the share of C\*'s gap closed, `1 − Δ(V−close)/Δ(C*−close)`. The gap
  "narrows" only when Δ(V − C\*) is SUPPORTED.
- **Favourite calibration** (favourite = the side, home or away, with the higher de-vigged close probability):
  for every arm, the mean model probability of that side, the mean close probability and the actual win rate,
  over all held-out matches and over the top decile by close probability.
- **Spread:** sd of p(home) − p(away) per arm and for the close.
- **Reference rows:** N, the naive link with `k = 0` (league μ and η only, the as-of naive baseline the lane
  goal names), and the compression study's arm C without the gate.
- **Lane H39 verdict:** the lane's falsification test reads "no rating variant reduces held-out 1X2 vs the
  SHIPPED model with a CI excluding 0, OR the best variant's rating spread is not wider than shipped". Here:
  - H39 is **FALSIFIED** if neither any family nor the cumulative arm is SUPPORTED, OR if the best
    SUPPORTED arm's model spread (the sd above) is not wider than C\*'s.
  - It is **SUPPORTED as a mechanism** if some arm is SUPPORTED with a wider spread.
  - Separately, the lane GOAL is met only if the favourite gap closes (top-decile model probability moves
    materially toward the actual win rate). The size is reported, not pre-judged.
- **Secondary** (never used for a verdict): CORE and PROMOTED subsets, per league, per test season, big 5 vs
  goals leagues, 2026 alone, and the selected grid value per season and family.

### Identity / reachability check (the run stops if it fails)

The variant code reimplements the window mean so that it can weight and blend. **At the shipped config
(W0, h = ∞, c = ∞, gate, p0) it must reproduce production's `compute_team_ratings` raw output** (scale 1,
cap ∞, the harness's module-global patch) and its `matches` count, for every rated side of every FULL
match, to within 2e-4. A **reachability check** follows: every family's non-shipped grid values must change
the rating vector of at least 1% of FULL matches (`off != on`). A family that changes nothing is reported as
INERT, not scored.

### What this does NOT establish

- The SERVED sim's 1X2 under a changed rating. No sim is run. The compression study measured the engine's gain
  on the rating as linear (R² 0.87) and equal to the refit slope, so a linear-link gain is the expected
  direction, but its size in the sim is not measured.
- Inputs the rating never sees (squad, lineup, injuries, market information). If no family helps, those are
  what remain, and this lane says so.
- MLS and the Championship, which are not rated here.

A SUPPORTED verdict licenses nothing on the board. Stage 2 (production rating code, which sits with another
lane) is a user decision through the model-engine standard.

Run at Idle priority. Driver: `scripts/soccer_team_strength_experiments.py stage1`.

## 2. Coverage

(written after the run's population and identity check, before any score is read;
`C:/tmp/team-strength/stage1_coverage.json`, run 17:46-17:54Z at Idle priority, read back 64)

- **FULL: 32,638 matches** (8 leagues, 2014..2026). Excluded: 8 wrong pairings and 10 with no close.
- **Held out (2016..2026): 27,285 matches.** CORE (both sides ≥ 10 rated rows) 25,863; PROMOTED (either side
  < 10, so the gate fires) 1,422. Of the held-out sides, 145 have 0 rows, 1,315 have 1..9 rows and 53,110 have
  ≥ 10.
  - Close source, held out: Pinnacle 25,386; market average 1,899 (all of 2026-27, plus a few older).
  - Per season 2,495..2,744 matches, and 2026 has 512. The compression study's held-out set (26,547) is
    nearly all of CORE, plus its n 5..9 matches.
- **Identity check PASSED.** At the shipped config, the variant code reproduces production's raw
  `compute_team_ratings` output and its `matches` count on **every one of 65,009 rated sides**, with a max
  error of 5.0e-5 (4-dp rounding). Every production-unrated side has n = 0 in the variant code.
- **Reachability PASSED, so no family is inert.** Share of FULL matches whose rating vector moves off C\*:
  - W: 0.98 / 0.93 / 0.88 / 0.88 for ×1/3, 2/3, 4/3, 2. The two longer windows move nearly the same
    matches, because the depth caps them.
  - R: 0.98 at every half-life.
  - B: 0.91 at every c. Matches with no current-season rows are unchanged.
  - S: 0.998 at every n0.
  - P fitted: **0.066**. Only gated sides change, so P can matter only on PROMOTED.
- **One family, one window.** Ratings, outcomes and closes come from the same matches 2014..2026. The
  intersection is the FULL set itself.

## 3. Results

- **Run:** 2026-10-16 17:55-18:07Z at Idle priority (read back 64).
- **Driver:** `scripts/soccer_team_strength_experiments.py stage1` (`81749579`).
- **Output:** `C:/tmp/team-strength/stage1_report.json` and `stage1_run.log`.
- **Data:** 27,285 held-out FULL matches, 8 leagues, test seasons 2016-2026. Every arm scores the same
  matches.

### Verdicts (Δ 1X2 log loss vs C\*, walk-forward-selected value; 95% match bootstrap)

| arm | selected value per season | Δ vs C\* | 95% CI | Δ Brier | verdict | Δ vs close | share of C\*'s gap closed | top-decile fav | spread sd |
|---|---|---|---|---|---|---|---|---|---|
| C\* (shipped + gate, k refit) | — | 0 | — | — | reference | **+0.0221** | 0 | 0.745 | 0.323 |
| **W** window | ×2/3 in 2016, then shipped ×1 in 2017-26 | +0.0002 | [−0.0001, +0.0005] | +0.0001 | **FALSIFIED** | +0.0223 | −1% | 0.745 | 0.324 |
| **R** recency | h 20 in 2016-17, then 40 | −0.0009 | [−0.0015, −0.0004] | −0.0007 | **SUPPORTED** | +0.0212 | 4% | 0.748 | 0.324 |
| **B** current-season blend | c 20 in 2016, then 40 | **−0.0015** | [−0.0022, −0.0009] | −0.0011 | **SUPPORTED** | +0.0206 | 7% | 0.751 | 0.326 |
| **S** shrinkage (replaces the gate) | n0 5 in every season | −0.0007 | [−0.0012, −0.0001] | −0.0004 | **SUPPORTED** | +0.0215 | 3% | 0.754 | 0.328 |
| **P** fitted promoted prior | fitted in every season | −0.0007 | [−0.0012, −0.0003] | −0.0005 | **SUPPORTED** | +0.0214 | 3% | 0.745 | 0.322 |
| **CUM** W→R→B→S→P | shipped W, h 40, c 40, n0 5, fitted prior (2016: W ×2/3) | **−0.0019** | [−0.0031, −0.0009] | −0.0013 | **SUPPORTED** | **+0.0202** | **9%** | **0.758** | 0.327 |
| C_nogate (production before 2026-10-07) | — | +0.0013 | [+0.0003, +0.0022] | +0.0008 | worse than C\* | +0.0234 | — | 0.733 | 0.312 |
| N naive (k = 0) | — | +0.0925 | [+0.0882, +0.0967] | +0.0658 | — | +0.1146 | — | 0.424 | 0.020 |
| de-vigged close | — | — | — | — | — | 0 | — | 0.805 (actual **0.821**) | **0.364** |

Mean held-out log loss: C\* 0.9777, CUM 0.9758, close 0.9556. Favourites over all matches: actual 0.546,
close 0.535, C\* 0.517, CUM 0.520.

**Grid points** (descriptive; not verdicts, because picking the best after the fact is not one), Δ vs C\*:

- W ×1/3 +0.0089, ×2/3 +0.0014, ×4/3 +0.0004, ×2 +0.0013. **The shipped window lengths are already at the
  optimum.**
- R h 40 −0.0011, h 20 −0.0006, h 10 +0.0031.
- B c 40 −0.0016, c 20 −0.0010, c 10 +0.0007, c 5 +0.0038.
- S n0 5 −0.0007, n0 10 −0.0001, n0 20 +0.0024, n0 40 +0.0088.
- So the gains are only at the MILD end of each grid. Strong recency, blend or shrinkage costs log loss.

### Subsets (secondary), Δ vs C\* [95% CI]

| set | n | C\* − close | B | R | S | P | CUM |
|---|---|---|---|---|---|---|---|
| CORE (both ≥ 10 rows) | 25,863 | +0.0216 | −0.0016 [−0.0022, −0.0010] | −0.0010 | −0.0004 | −0.0003 | −0.0014 [−0.0025, −0.0005] |
| PROMOTED | 1,422 | +0.0311 | −0.0013 | +0.0001 | −0.0047 [−0.0137, +0.0050] | −0.0091 [−0.0172, +0.0007] | **−0.0116 [−0.0230, +0.0009]** |
| big 5 | 18,231 | +0.0213 | −0.0017 | −0.0011 | −0.0003 | −0.0002 | −0.0019 [−0.0030, −0.0007] |
| goals leagues | 9,054 | +0.0237 | −0.0012 | −0.0005 | −0.0015 | −0.0018 | −0.0020 [−0.0044, +0.0003] |

- **Per league, CUM ranges −0.0055 to +0.0013.**
  - Primeira −0.0055 and Ligue 1 −0.0034 have CIs below 0.
  - Eredivisie +0.0013 [−0.0029, +0.0055] is the only point estimate above 0.
  - C\* − close is +0.018 to +0.027 in every league.
- **Per season, CUM is below 0 in 9 of 11 seasons.** The exceptions are 2017 (+0.0021) and 2024 (+0.0003).
- **2026 alone** (n 512): CUM −0.0004 [−0.0103, +0.0090]. S is +0.0061 there.

### What the numbers say

1. **The rating inputs do carry recoverable information.** It is small. Four of the five families, and the
   cumulative arm, beat the shipped rating with CIs below 0, every Brier contrast agrees, and the cumulative
   arm is also wider (sd 0.327 vs 0.323). The largest single piece is the current-season blend: a club's
   current-season rows get weight `n_cur/(n_cur + 40)` on top of the 45/90-match window, so at mid-season
   (19 rows) the blend weight is about 0.32. Next is mild recency (half-life 40 matches).
2. **The families overlap.** The singles sum to −0.0038, but the cumulative arm is −0.0019. Recency and the
   current-season blend both up-weight recent matches, and shrinkage and the fitted prior both act on
   few-row clubs.
3. **The few-match gate production turned on 2026-10-07 is confirmed** on 14 times the earlier sample.
   Without it (C_nogate), log loss is +0.0013 [+0.0003, +0.0022]. A soft version does better:
   shrinkage at n0 = 5 toward a FITTED promoted-club prior. On PROMOTED matches, CUM is −0.0116 (CI just
   spans 0, n 1,422). The fitted prior is the mean raw x of promoted clubs over their promotion seasons in
   training; it replaces the flat −0.18/−0.18.
4. **The gap to the close is almost all still there.** The best arm closes **9%** of C\*'s gap: +0.0221
   becomes +0.0202. Top-decile favourites move 0.745 → 0.758, against a close of 0.805 and an actual win rate
   of 0.821. That is 17% of the shortfall to actual. The model spread is 0.327, against the close's 0.364.

### Verdicts against the lane

- **H39 (lane): SUPPORTED as a mechanism, FAILED as an explanation.** Under the registered rule, H39
  survives: CUM is SUPPORTED and its spread (0.327) is wider than C\*'s (0.323). But the size refutes the
  story that the ratings are badly built. The best set of input changes recovers less than a tenth of the
  gap, and it leaves top-decile favourites 0.063 below actual.
- **Lane GOAL: NOT MET, and not meetable through these inputs.** Most of the favourite gap is information the
  rating never sees: lineups, injuries, squad strength and transfers, the market itself. A 45/90-match xG or
  goals average cannot carry that, however it is weighted.
- **Stage 2 candidate (user decision; production rating code is not this lane's):** the cumulative config, in
  production's shipped transform:
  - `compute_team_ratings` gains recency weights `0.5^(age/40)`;
  - a current-season blend `b = n_cur/(n_cur + 40)`;
  - the hard few-match gate becomes shrinkage `n/(n+5)`, toward 0 for established clubs and toward a
    per-league fitted promoted prior for promoted clubs.
  - **Expected gain: −0.0019 log loss on a linear link.** The engine read in the compression study says
    the sim's gain on the rating is linear, so the direction should transfer. The size in the sim is NOT
    measured. Under the model-engine standard it needs a roster/artifact rebuild and an `off != on` test.
    It is modest beside the +0.020 that remains.

## 4. What cannot be estimated

- **The served sim's 1X2 under the CUM rating.** No sim was run.
- **Whether information outside the rating closes the rest**, such as lineups, injuries or squad value.
  None of it is in these inputs. The 0.9 of the gap that remains points there, which is a lead and not a
  measurement.
- **MLS and the Championship**, which are not rated here.
- **2026-27 on its own** (n 512, every CI spans 0).
- **The share of C\*'s gap that is the close's own skill**, as against noise or hindsight in the closing
  price. The close is treated as the reference, not decomposed.

## 5. Deviations from the registration

- None. The grids, selection rule, order and verdict rules ran as registered. The identity and reachability
  checks passed (section 2).
